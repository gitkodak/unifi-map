"""Manual topology overrides: schema and loader.

Both halves are implemented: the TOML schema and loader, and :func:`apply`,
which resolves selectors against a topology and rewrites it.

Why this exists
---------------
The controller cannot see parts of a real network:

- A direct link it does not participate in. A NAS on a 10G SFP+ DAC to a switch
  shows up with no ``sw_mac``, so the renderer can only anchor it to the
  "uplink not reported by controller" placeholder.
- Gear the controller reports as online but which is not meaningfully on the
  network, such as an access point whose radios were disabled deliberately. It
  is not offline, so ``--show-offline no`` will not remove it, and it is pure
  noise on the map.
- Anything nested inside another host. VMs and containers appear as their own
  clients with no indication that they live on a particular hypervisor.

And some things the controller reports are simply wrong. Ubiquiti's fingerprint
database misidentifies devices (a network-attached bidet confidently labelled a
smart toothbrush), which produces both the wrong name and the wrong artwork.

None of this can be inferred safely, and guessing would invent topology that does
not exist, so instead the user states it, in a small TOML file.

TOML is used because Python 3.11+ reads it from the standard library
(``tomllib``), it takes comments, and it is pleasant to hand-edit. No new
dependency.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path

from .assets import IconAsset, local_icon
from .model import UNKNOWN_UPLINK_ID, Edge, Kind, Node, Topology


class OverrideError(ValueError):
    """Raised for a malformed overrides file."""


@dataclass(frozen=True)
class Link:
    """An explicit connection the controller does not report.

    ``source`` and ``target`` are selectors, not ids: a MAC, an IP, or a
    hostname/device name. Resolution is deliberately deferred so a file stays
    readable and survives a device being renamed in one place only.
    """

    source: str
    target: str
    port: str | None = None
    speed: str | None = None
    note: str | None = None
    wireless: bool = False

    @property
    def label(self) -> str | None:
        """What to print on the edge."""
        parts = [p for p in (f"port {self.port}" if self.port else None, self.speed) if p]
        return " · ".join(parts) or None


@dataclass(frozen=True)
class Device:
    """A device the user knows about and no source reports.

    An unmanaged switch, a non-UniFi access point, something powered off at the
    time of the fetch, or gear on a segment the controller cannot see. The
    controller has no way to know these exist, and this tool will not guess, so
    the user states them.

    The resulting node is marked `asserted` and drawn differently. That is the
    point rather than a detail: a map that presented a device somebody typed in
    identically to one the controller reported would be quietly lying about
    where its information came from.
    """

    name: str
    kind: str = "unknown"
    ip: str | None = None
    model: str | None = None
    parent: str | None = None
    port: str | None = None
    icon: Path | None = None
    note: str | None = None

    @property
    def node_id(self) -> str:
        """A stable id that cannot collide with a MAC address.

        Derived from the name so re-running is deterministic, and prefixed so it
        is obvious in DOT output and draw.io ids where a node came from.
        """
        slug = "".join(c if c.isalnum() else "-" for c in self.name.lower()).strip("-")
        return f"asserted-{slug or 'device'}"


@dataclass(frozen=True)
class Hosted:
    """A node that runs inside another node: a VM, container or jail."""

    guest: str
    host: str
    note: str | None = None


@dataclass(frozen=True)
class NodeOverride:
    """A correction to how one node is presented.

    Exists because Ubiquiti's fingerprint is sometimes wrong, and a wrong
    fingerprint yields both a wrong name and wrong artwork. `icon` points at a
    file the user supplies; nothing is fetched for it.
    """

    match: str
    name: str | None = None
    icon: Path | None = None
    note: str | None = None
    # Drop the node from the map entirely: gear the controller still calls online
    # but which is idle by choice, or a host you would rather not put on a map
    # you are sharing. Leaf nodes only; see the TODO about children.
    hide: bool = False


@dataclass
class Overrides:
    devices: list[Device] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    hosted: list[Hosted] = field(default_factory=list)
    nodes: list[NodeOverride] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.devices or self.links or self.hosted or self.nodes)


def _require_str(table: dict, key: str, context: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise OverrideError(f"{context}: '{key}' is required and must be a non-empty string")
    return value.strip()


def _optional_str(table: dict, key: str) -> str | None:
    value = table.get(key)
    if value is None:
        return None
    # `bool` is a subclass of `int` in Python, so `port = true` used to become
    # the port "1". Checked first, and refused.
    if isinstance(value, bool):
        raise OverrideError(f"'{key}' must be a string or number, got a boolean")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        # `port = 1.9` silently became "1". A port is a whole number, and a
        # fractional one is a typo worth stopping for.
        if value != int(value):
            raise OverrideError(f"'{key}' must be a whole number, got {value}")
        return str(int(value))
    if not isinstance(value, str):
        raise OverrideError(f"'{key}' must be a string or number, got {type(value).__name__}")
    return value.strip() or None


# Every key each block accepts. A file is hand-edited, and a misspelling is the
# most likely mistake in one.
_KNOWN_KEYS: dict[str, frozenset[str]] = {
    "device": frozenset({"name", "kind", "ip", "model", "parent", "port", "icon", "note"}),
    "link": frozenset({"from", "to", "port", "speed", "note", "wireless"}),
    "hosted": frozenset({"guest", "host", "note"}),
    "node": frozenset({"match", "name", "icon", "hide", "note"}),
}


def _refuse_unknown_keys(table: dict, block: str, context: str) -> None:
    """Reject a key this block does not accept.

    `wirless = true` was accepted and ignored, so the link stayed solid and
    nothing said why. That is the same failure as a stale selector, which this
    file already refuses loudly: a typo has to stop the run, or the map quietly
    does not say what the file says.
    """
    unknown = sorted(k for k in table if k not in _KNOWN_KEYS[block])
    if unknown:
        known = ", ".join(sorted(_KNOWN_KEYS[block]))
        raise OverrideError(
            f"{context}: unknown key(s) {', '.join(repr(k) for k in unknown)}. "
            f"[[{block}]] accepts: {known}."
        )


def _optional_bool(table: dict, key: str, context: str) -> bool:
    """A flag that must actually be a TOML boolean.

    `bool("false")` is `True`, so `wireless = "false"` and `hide = "false"` both
    read as the opposite of what they say. Quoting a boolean is an easy mistake
    in a format that has real booleans, and the whole design rule here is that
    an overrides file fails loudly rather than doing something else quietly.
    """
    value = table.get(key)
    if value is None:
        return False
    if not isinstance(value, bool):
        raise OverrideError(
            f"{context}: '{key}' must be true or false without quotes, got {value!r}"
        )
    return value


def _icon_path(table: dict, base_dir: Path | None) -> Path | None:
    """Resolve an `icon` key relative to the overrides file, not the cwd."""
    raw = _optional_str(table, "icon")
    if not raw:
        return None
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute() and base_dir is not None:
        candidate = base_dir / candidate
    return candidate


def _refuse_unknown_blocks(payload: dict) -> None:
    """Reject a table this file does not define.

    Keys *inside* a block were already checked, which made the gap easy to
    miss: `[[lnik]]` parsed, matched nothing, and the run reported "applies
    cleanly" with zero links. A file whose every line is ignored is exactly the
    silence this feature refuses everywhere else.
    """
    unknown = sorted(k for k in payload if k not in _KNOWN_KEYS)
    if unknown:
        known = ", ".join(f"[[{k}]]" for k in sorted(_KNOWN_KEYS))
        raise OverrideError(
            f"Unknown section(s) {', '.join(repr(k) for k in unknown)}. This file accepts: {known}."
        )
    for name in _KNOWN_KEYS:
        value = payload.get(name)
        if value is not None and not isinstance(value, list):
            # `[device]` rather than `[[device]]` is a single table, and TOML
            # accepts it happily. Every block here is a list of tables.
            raise OverrideError(
                f"[[{name}]] must be written as a list of tables, with double "
                f"brackets. Got a {type(value).__name__}."
            )


def _block_table(raw: object, block: str, index: int) -> tuple[dict, str]:
    context = f"[[{block}]] #{index}"
    if not isinstance(raw, dict):
        raise OverrideError(f"{context} must be a table")
    _refuse_unknown_keys(raw, block, context)
    return raw, context


def _parse_devices(payload: dict, base_dir: Path | None) -> list[Device]:
    devices = []
    seen_names: set[str] = set()
    for index, raw in enumerate(payload.get("device") or [], start=1):
        raw, context = _block_table(raw, "device", index)
        name = _require_str(raw, "name", context)
        if name.lower() in seen_names:
            raise OverrideError(f"{context}: a device named {name!r} is already declared")
        seen_names.add(name.lower())

        kind = (_optional_str(raw, "kind") or "unknown").lower()
        valid = sorted(k.value for k in Kind if k is not Kind.INTERNET)
        if kind not in valid:
            raise OverrideError(
                f"{context}: 'kind' must be one of {', '.join(valid)}, got {kind!r}"
            )
        if raw.get("port") is not None and not _optional_str(raw, "parent"):
            raise OverrideError(f"{context}: 'port' means nothing without 'parent'")

        devices.append(
            Device(
                name=name,
                kind=kind,
                ip=_optional_str(raw, "ip"),
                model=_optional_str(raw, "model"),
                parent=_optional_str(raw, "parent"),
                port=_optional_str(raw, "port"),
                icon=_icon_path(raw, base_dir),
                note=_optional_str(raw, "note"),
            )
        )
    return devices


def _parse_links(payload: dict) -> list[Link]:
    links = []
    for index, raw in enumerate(payload.get("link") or [], start=1):
        raw, context = _block_table(raw, "link", index)
        links.append(
            Link(
                source=_require_str(raw, "from", context),
                target=_require_str(raw, "to", context),
                port=_optional_str(raw, "port"),
                speed=_optional_str(raw, "speed"),
                note=_optional_str(raw, "note"),
                wireless=_optional_bool(raw, "wireless", context),
            )
        )
    return links


def _parse_hosted(payload: dict) -> list[Hosted]:
    hosted = []
    for index, raw in enumerate(payload.get("hosted") or [], start=1):
        raw, context = _block_table(raw, "hosted", index)
        hosted.append(
            Hosted(
                guest=_require_str(raw, "guest", context),
                host=_require_str(raw, "host", context),
                note=_optional_str(raw, "note"),
            )
        )
    return hosted


def _parse_nodes(payload: dict, base_dir: Path | None) -> list[NodeOverride]:
    nodes = []
    for index, raw in enumerate(payload.get("node") or [], start=1):
        raw, context = _block_table(raw, "node", index)
        icon = _icon_path(raw, base_dir)
        name = _optional_str(raw, "name")
        note = _optional_str(raw, "note")
        hide = _optional_bool(raw, "hide", context)
        if name is None and icon is None and not hide:
            raise OverrideError(f"{context}: needs at least one of 'name', 'icon' or 'hide'")
        nodes.append(
            NodeOverride(
                match=_require_str(raw, "match", context),
                name=name,
                icon=icon,
                note=note,
                hide=hide,
            )
        )
    return nodes


def parse(payload: dict, base_dir: Path | None = None) -> Overrides:
    """Build :class:`Overrides` from an already-decoded TOML mapping.

    *base_dir* is what relative ``icon`` paths resolve against: the directory
    holding the overrides file, so a config plus an assets folder can be moved
    around together.
    """
    _refuse_unknown_blocks(payload)

    return Overrides(
        devices=_parse_devices(payload, base_dir),
        links=_parse_links(payload),
        hosted=_parse_hosted(payload),
        nodes=_parse_nodes(payload, base_dir),
    )


def load(path: Path) -> Overrides:
    """Read and validate an overrides file."""
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise OverrideError(f"No overrides file at {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise OverrideError(f"{path} is not valid TOML: {exc}") from exc
    return parse(payload, base_dir=path.parent)


@dataclass(frozen=True)
class Displaced:
    """A link the controller reported that an override replaced.

    Carried out to the caller rather than logged from here, for the same reason
    `hidden` is: the labels are identifying, and only the caller knows whether
    `--obfuscate` is in force. Logging it in place scrubbed the diagram while
    printing real names into the terminal the diagram was produced in.
    """

    context: str
    node: str
    parent: str


@dataclass
class ApplyResult:
    """What `apply` did, so the caller can report it rather than guess."""

    topology: Topology
    icons: dict[str, IconAsset] = field(default_factory=dict)
    renamed: int = 0
    hidden: list[str] = field(default_factory=list)
    displaced: list[Displaced] = field(default_factory=list)
    links_added: int = 0
    hosted_applied: int = 0
    devices_added: int = 0

    @property
    def changed(self) -> bool:
        return bool(
            self.renamed
            or self.hidden
            or self.links_added
            or self.hosted_applied
            or self.devices_added
        )


def resolve(selector: str, topo: Topology) -> str:
    """Find the node a selector names, or raise.

    Tried in order of how specific each is: MAC, then address, then the label as
    shown on the map. An unmatched or ambiguous selector is an error rather than
    a silent no-op, because a typo that quietly does nothing is worse than a run
    that stops and says so.
    """
    needle = selector.strip()
    lowered = needle.lower()

    exact = [n.id for n in topo.nodes.values() if n.id.lower() == lowered]
    if len(exact) == 1:
        return exact[0]

    by_ip = [n.id for n in topo.nodes.values() if n.ip and n.ip == needle]
    if len(by_ip) == 1:
        return by_ip[0]

    by_label = [n.id for n in topo.nodes.values() if n.label.lower() == lowered]
    if len(by_label) == 1:
        return by_label[0]

    matches = by_ip or by_label
    if matches:
        names = ", ".join(sorted(topo.nodes[m].label for m in matches))
        raise OverrideError(
            f"{selector!r} matches {len(matches)} nodes ({names}). "
            "Use a MAC address, which is unique."
        )
    raise OverrideError(
        f"{selector!r} matches nothing on the map. Check the spelling, or whether "
        "the device was connected when the snapshot was taken."
    )


def _refuse_cycles(topo: Topology) -> None:
    """Refuse a graph where something is its own ancestor.

    Not because the renderer breaks: DOT is a digraph, cycles are legal in it,
    and Graphviz draws one without complaining. Checked because it is not a
    network. A switch cannot be plugged into something plugged into itself, so
    a cycle means the overrides describe hardware that cannot exist, and this
    tool's whole position is that it does not draw claims it cannot stand
    behind. Drawn silently, the map looks authoritative and is wrong.

    Only reachable through overrides. A controller cannot report one, so this
    runs at the end of `apply()` rather than in `model.py`.
    """
    # Every parent, not just the first. Collapsing to one parent per node was
    # exact only because nothing here currently produces a second one, which is
    # an invariant of the callers rather than of this function. A cycle reachable
    # only through a second parent would have gone undetected, and this check
    # exists precisely for the case where the input is wrong.
    parents: dict[str, list[str]] = {}
    for edge in topo.edges:
        # Edges are stored child to parent.
        parents.setdefault(edge.src, []).append(edge.dst)

    def label(node_id: str) -> str:
        return topo.nodes[node_id].label if node_id in topo.nodes else node_id

    # Iterative depth-first search, so a long chain cannot exhaust the stack on
    # a graph that is by definition already malformed. `settled` stops the whole
    # search being redone for every node in a shared chain.
    settled: set[str] = set()
    for start in parents:
        if start in settled:
            continue
        stack: list[tuple[str, int]] = [(start, 0)]
        path: list[str] = [start]
        on_path: set[str] = {start}
        while stack:
            node, index = stack[-1]
            options = parents.get(node, ())
            if index >= len(options):
                stack.pop()
                settled.add(node)
                on_path.discard(path.pop())
                continue
            stack[-1] = (node, index + 1)
            parent = options[index]
            if parent in on_path:
                loop = [*path[path.index(parent) :], parent]
                raise OverrideError(
                    f"These overrides make a loop: {' -> '.join(label(n) for n in loop)}. "
                    "Something is its own uplink, which is not a network a cable can make."
                )
            if parent not in settled:
                stack.append((parent, 0))
                path.append(parent)
                on_path.add(parent)


def _children(topo: Topology, node_id: str) -> list[str]:
    """Nodes hanging off *node_id*. Edges are stored child to parent."""
    return [e.src for e in topo.edges if e.dst == node_id]


def _drop_parent_edges(
    topo: Topology, node_id: str, context: str, result: ApplyResult | None = None
) -> None:
    """Detach *node_id* from its parent so an asserted edge can replace it.

    Records the displacement when the edge being replaced was a real
    observation. Reparenting is the documented purpose of `[[hosted]]` (a VM is
    genuinely reported on a switch port, and moving it under its hypervisor is
    the whole point), so this cannot be an error. But displacing something the
    controller reported is not the same as tidying up the "uplink not reported"
    placeholder, and the rule here is that an override contradicting the
    controller says so rather than quietly preferring itself.

    Two edges are excluded, and both were wrong in the first version:

    - the `UNKNOWN_UPLINK_ID` placeholder, which is an absence of information
      rather than an observation, and
    - anything already `asserted`, which came from an earlier override in the
      same file. Reporting that as controller-reported would have this function
      telling exactly the lie it exists to prevent.
    """
    displaced = [
        e.dst
        for e in topo.edges
        if e.src == node_id and e.dst != UNKNOWN_UPLINK_ID and not e.asserted
    ]
    if result is not None:
        for parent in displaced:
            result.displaced.append(
                Displaced(
                    context=context,
                    node=topo.nodes[node_id].label if node_id in topo.nodes else node_id,
                    parent=topo.nodes[parent].label if parent in topo.nodes else parent,
                )
            )
    topo.edges[:] = [e for e in topo.edges if e.src != node_id]


def _prune_placeholder(topo: Topology) -> None:
    """Remove the uplink placeholder once nothing hangs off it."""
    if UNKNOWN_UPLINK_ID in topo.nodes and not _children(topo, UNKNOWN_UPLINK_ID):
        del topo.nodes[UNKNOWN_UPLINK_ID]
        topo.edges[:] = [e for e in topo.edges if UNKNOWN_UPLINK_ID not in (e.src, e.dst)]


def _apply_devices(
    working: Topology,
    devices: list[Device],
    cache_dir: Path | None,
    result: ApplyResult,
) -> None:
    for device in devices:
        if device.node_id in working.nodes:
            raise OverrideError(
                f"[[device]] {device.name!r} would collide with an existing node id"
            )
        working.add(
            Node(
                id=device.node_id,
                label=device.name,
                kind=Kind(device.kind),
                ip=device.ip,
                model=device.model,
                detail=device.model,
                asserted=True,
            )
        )
        result.devices_added += 1
        if device.icon is not None:
            result.icons[device.node_id] = local_icon(device.icon, cache_dir)


def _apply_device_parents(working: Topology, devices: list[Device]) -> None:
    # Second pass, and it has to be one. The comment here used to claim parents
    # were "resolved after every declared device exists" while resolving them
    # inside the loop above, so a device could only hang off one declared
    # earlier in the file. Reversing two blocks turned a working file into
    # "'Parent' matches nothing on the map", which reads as a typo rather than
    # as ordering.
    for device in devices:
        if not device.parent:
            continue
        parent_id = resolve(device.parent, working)
        working.edges.append(
            Edge(
                src=device.node_id,
                dst=parent_id,
                label=f"port {device.port}" if device.port else None,
                asserted=True,
            )
        )


def _apply_links(working: Topology, links: list[Link], result: ApplyResult) -> None:
    for link in links:
        source = resolve(link.source, working)
        target = resolve(link.target, working)
        if source == target:
            raise OverrideError(f"[[link]] {link.source!r} and {link.target!r} are the same node")
        _drop_parent_edges(working, source, f"[[link]] {link.source!r}", result)
        label = link.label or link.note
        working.edges.append(
            Edge(src=source, dst=target, label=label, wireless=link.wireless, asserted=True)
        )
        result.links_added += 1


def _apply_hosted(working: Topology, hosted: list[Hosted], result: ApplyResult) -> None:
    for entry in hosted:
        guest = resolve(entry.guest, working)
        host = resolve(entry.host, working)
        if guest == host:
            raise OverrideError(f"[[hosted]] {entry.guest!r} cannot host itself")
        _drop_parent_edges(working, guest, f"[[hosted]] {entry.guest!r}", result)
        working.edges.append(Edge(src=guest, dst=host, label=entry.note or "hosted", asserted=True))
        result.hosted_applied += 1


def _apply_nodes(
    working: Topology,
    nodes: list[NodeOverride],
    cache_dir: Path | None,
    result: ApplyResult,
) -> None:
    for node in nodes:
        node_id = resolve(node.match, working)
        current = working.nodes[node_id]

        if node.hide:
            kids = _children(working, node_id)
            if kids:
                names = ", ".join(sorted(working.nodes[k].label for k in kids))
                raise OverrideError(
                    f"Cannot hide {current.label!r}: {len(kids)} node(s) depend on it "
                    f"({names}). Hiding it would orphan them. Only leaf nodes can be "
                    "hidden."
                )
            del working.nodes[node_id]
            working.edges[:] = [e for e in working.edges if node_id not in (e.src, e.dst)]
            result.hidden.append(current.label)
            continue

        changes: dict[str, object] = {}
        if node.name:
            changes["label"] = node.name
        if changes:
            working.nodes[node_id] = replace(current, **changes)
            result.renamed += 1
        if node.icon is not None:
            result.icons[node_id] = local_icon(node.icon, cache_dir)


def apply(topo: Topology, overrides: Overrides, cache_dir: Path | None = None) -> ApplyResult:
    """Apply *overrides* to a copy of *topo*.

    Order matters, in both directions. Declared devices are added first, so a
    link, a nesting or a rename can refer to one. Hiding comes last, so it sees
    the children an override just gave a node.
    """
    working = Topology(
        nodes=dict(topo.nodes),
        edges=list(topo.edges),
        networks=dict(topo.networks),
    )
    result = ApplyResult(topology=working)

    _apply_devices(working, overrides.devices, cache_dir, result)
    _apply_device_parents(working, overrides.devices)
    _apply_links(working, overrides.links, result)
    _apply_hosted(working, overrides.hosted, result)
    _apply_nodes(working, overrides.nodes, cache_dir, result)
    _prune_placeholder(working)
    _refuse_cycles(working)
    return result
