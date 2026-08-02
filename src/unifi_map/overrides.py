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
    # Ports are naturally written unquoted in TOML, so accept an int too.
    if isinstance(value, int | float):
        return str(int(value))
    if not isinstance(value, str):
        raise OverrideError(f"'{key}' must be a string or number, got {type(value).__name__}")
    return value.strip() or None


def _icon_path(table: dict, base_dir: Path | None) -> Path | None:
    """Resolve an `icon` key relative to the overrides file, not the cwd."""
    raw = _optional_str(table, "icon")
    if not raw:
        return None
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute() and base_dir is not None:
        candidate = base_dir / candidate
    return candidate


def parse(payload: dict, base_dir: Path | None = None) -> Overrides:
    """Build :class:`Overrides` from an already-decoded TOML mapping.

    *base_dir* is what relative ``icon`` paths resolve against: the directory
    holding the overrides file, so a config plus an assets folder can be moved
    around together.
    """
    result = Overrides()

    seen_names: set[str] = set()
    for index, raw in enumerate(payload.get("device") or [], start=1):
        if not isinstance(raw, dict):
            raise OverrideError(f"[[device]] #{index} must be a table")
        context = f"[[device]] #{index}"
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

        result.devices.append(
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

    for index, raw in enumerate(payload.get("link") or [], start=1):
        if not isinstance(raw, dict):
            raise OverrideError(f"[[link]] #{index} must be a table")
        context = f"[[link]] #{index}"
        result.links.append(
            Link(
                source=_require_str(raw, "from", context),
                target=_require_str(raw, "to", context),
                port=_optional_str(raw, "port"),
                speed=_optional_str(raw, "speed"),
                note=_optional_str(raw, "note"),
                wireless=bool(raw.get("wireless", False)),
            )
        )

    for index, raw in enumerate(payload.get("hosted") or [], start=1):
        if not isinstance(raw, dict):
            raise OverrideError(f"[[hosted]] #{index} must be a table")
        context = f"[[hosted]] #{index}"
        result.hosted.append(
            Hosted(
                guest=_require_str(raw, "guest", context),
                host=_require_str(raw, "host", context),
                note=_optional_str(raw, "note"),
            )
        )

    for index, raw in enumerate(payload.get("node") or [], start=1):
        if not isinstance(raw, dict):
            raise OverrideError(f"[[node]] #{index} must be a table")
        context = f"[[node]] #{index}"
        icon = _icon_path(raw, base_dir)
        name = _optional_str(raw, "name")
        note = _optional_str(raw, "note")
        hide = bool(raw.get("hide", False))
        if name is None and icon is None and not hide:
            raise OverrideError(f"{context}: needs at least one of 'name', 'icon' or 'hide'")
        result.nodes.append(
            NodeOverride(
                match=_require_str(raw, "match", context),
                name=name,
                icon=icon,
                note=note,
                hide=hide,
            )
        )

    return result


def load(path: Path) -> Overrides:
    """Read and validate an overrides file."""
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise OverrideError(f"No overrides file at {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise OverrideError(f"{path} is not valid TOML: {exc}") from exc
    return parse(payload, base_dir=path.parent)


@dataclass
class ApplyResult:
    """What `apply` did, so the caller can report it rather than guess."""

    topology: Topology
    icons: dict[str, IconAsset] = field(default_factory=dict)
    renamed: int = 0
    hidden: list[str] = field(default_factory=list)
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
    parents: dict[str, str] = {}
    for edge in topo.edges:
        # Edges are stored child to parent. A node with several parents is not a
        # cycle and is left alone; the first is enough to walk.
        parents.setdefault(edge.src, edge.dst)

    for start in parents:
        seen = [start]
        node = start
        while (node := parents.get(node)) is not None:
            if node in seen:
                loop = [*seen[seen.index(node) :], node]
                labels = " -> ".join(topo.nodes[n].label if n in topo.nodes else n for n in loop)
                raise OverrideError(
                    f"These overrides make a loop: {labels}. Something is its own "
                    "uplink, which is not a network a cable can make."
                )
            seen.append(node)


def _children(topo: Topology, node_id: str) -> list[str]:
    """Nodes hanging off *node_id*. Edges are stored child to parent."""
    return [e.src for e in topo.edges if e.dst == node_id]


def _drop_parent_edges(topo: Topology, node_id: str) -> None:
    topo.edges[:] = [e for e in topo.edges if e.src != node_id]


def _prune_placeholder(topo: Topology) -> None:
    """Remove the uplink placeholder once nothing hangs off it."""
    if UNKNOWN_UPLINK_ID in topo.nodes and not _children(topo, UNKNOWN_UPLINK_ID):
        del topo.nodes[UNKNOWN_UPLINK_ID]
        topo.edges[:] = [e for e in topo.edges if UNKNOWN_UPLINK_ID not in (e.src, e.dst)]


def apply(topo: Topology, overrides: Overrides) -> ApplyResult:
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

    for device in overrides.devices:
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
            result.icons[device.node_id] = local_icon(device.icon)

    # Second pass, and it has to be one. The comment here used to claim parents
    # were "resolved after every declared device exists" while resolving them
    # inside the loop above, so a device could only hang off one declared
    # earlier in the file. Reversing two blocks turned a working file into
    # "'Parent' matches nothing on the map", which reads as a typo rather than
    # as ordering.
    for device in overrides.devices:
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

    for link in overrides.links:
        source = resolve(link.source, working)
        target = resolve(link.target, working)
        if source == target:
            raise OverrideError(f"[[link]] {link.source!r} and {link.target!r} are the same node")
        # The controller could not place this node, so whatever it was anchored
        # to was a placeholder rather than an observation.
        _drop_parent_edges(working, source)
        label = link.label or link.note
        working.edges.append(
            Edge(src=source, dst=target, label=label, wireless=link.wireless, asserted=True)
        )
        result.links_added += 1

    for entry in overrides.hosted:
        guest = resolve(entry.guest, working)
        host = resolve(entry.host, working)
        if guest == host:
            raise OverrideError(f"[[hosted]] {entry.guest!r} cannot host itself")
        _drop_parent_edges(working, guest)
        working.edges.append(Edge(src=guest, dst=host, label=entry.note or "hosted", asserted=True))
        result.hosted_applied += 1

    for node in overrides.nodes:
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
            result.icons[node_id] = local_icon(node.icon)

    _prune_placeholder(working)
    _refuse_cycles(working)
    return result
