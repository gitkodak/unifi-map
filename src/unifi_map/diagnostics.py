"""How good is the map that was just drawn?

The counterpart to `report.py`, and deliberately its opposite. That one
describes a network for *somebody else's* benefit and is built from an allowlist
so it is safe to paste into an issue. This one describes *your* map for *your*
benefit, and it may freely name your devices, addresses and networks, because it
is never leaving your terminal. The header says so, and the two must not be
confused: `unifi-map shape` is the shareable one.

The problem it exists for: this tool refuses to invent, and until this existed
that refusal was invisible. A map built from a perfect fetch and one built from
a thin one looked equally authoritative, because a client placed from
`stat/sta`, one placed from the controller's own topology graph, and one placed
by a line somebody typed into an overrides file were drawn identically. The
diagram itself now marks the topology-graph and overrides cases (KAN-137); this
report is the text form of the same underlying `Provenance` data, and existed
first. Most of the reasoning was already available at runtime and thrown away
as log lines.

**Almost everything here is derived from the `Topology`, not collected
separately.** Once `Provenance` is recorded on each node and edge at the moment
the decision is made, the counts, the unplaced list, the dangling network
references and the confidence split all fall out of a finished map. That is why
there is no diagnostics object threaded through the pipeline: the two things
that genuinely cannot be recovered afterwards are artwork resolution, which
happens after the model is built, and facts about the source, which the caller
knows and the map does not.

Nothing here is counted-only, unlike `report.py`. Naming is the point: a count
of unplaced clients tells you there is a problem, and their labels tell you
which cupboard to go and look in.

**But a device is named only where something is wrong with it.** Healthy nodes
are counted and never listed, so a map with nothing wrong produces a report with
no device names in it at all. That is not a privacy guarantee and must not be
described as one, since the header has to stay accurate for the map that *does*
have problems. It is a readability decision: the report is a list of things
worth looking at, and a full node listing added "for completeness" would turn
every clean run into a network inventory printed to stdout. A test pins it.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from . import __version__
from .model import UNKNOWN_UPLINK_ID, Kind, Node, Provenance, Topology

_WIDTH = 74

_CLIENT_KINDS = (Kind.WIRED_CLIENT, Kind.WIRELESS_CLIENT)

# How each provenance reads in the report, and the order sections list them in.
# Ordered best-evidence first, so a map degrades down the list: what a device
# reported about itself, then what the controller reported about a client, then
# what a second endpoint knew, then what a person asserted, then the admission
# that nothing knew at all.
_NODE_SOURCES: tuple[tuple[Provenance, str], ...] = (
    (Provenance.DEVICE, "stat/device (the device inventory)"),
    (Provenance.CLIENT, "stat/sta (the client list; 'sta' is UniFi's term for a connected client)"),
    (Provenance.SYNTHETIC, "ours (Internet, placeholder)"),
    (Provenance.OVERRIDE, "an overrides file"),
    (Provenance.UNSPECIFIED, "UNRECORDED (a bug, please report)"),
)

_EDGE_SOURCES: tuple[tuple[Provenance, str], ...] = (
    (Provenance.DEVICE_UPLINK, "stat/device uplink (a device reporting its own connection)"),
    (Provenance.WAN, "gateway to the Internet"),
    (
        Provenance.CLIENT_UPLINK,
        "stat/sta sw_mac or ap_mac (a client reporting which switch or AP it's on)",
    ),
    (Provenance.TOPOLOGY_GRAPH, "the controller's topology graph"),
    (Provenance.UNPLACED, "nothing reported one"),
    (Provenance.OVERRIDE, "an overrides file"),
    (Provenance.UNSPECIFIED, "UNRECORDED (a bug, please report)"),
)

# Provenance values that mean the controller observed the link itself. Kept as
# one set rather than tested inline, because "observed" is a judgement and it
# should be made once. An override is excluded because it is a claim, and
# UNPLACED because it is the absence of one.
_OBSERVED = frozenset(
    {
        Provenance.DEVICE_UPLINK,
        Provenance.WAN,
        Provenance.CLIENT_UPLINK,
        Provenance.TOPOLOGY_GRAPH,
    }
)


@dataclass
class Sources:
    """What the caller knows and the map does not."""

    origin: str = "live fetch"
    controller_version: str | None = None
    site: str | None = None
    # Straight from `artwork.resolve_icons`, which already counts this.
    artwork: dict[str, int] = field(default_factory=dict)
    # `(name, how many catalogue entries matched)`, from `AssetStore`.
    ambiguous_artwork: list[tuple[str, int]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _describe(node: Node) -> str:
    """A node in one line: what it is called, and enough to go and find it."""
    bits = [node.label]
    if node.id and node.id != node.label:
        bits.append(node.id)
    if node.ip:
        bits.append(node.ip)
    if node.network:
        bits.append(f"on {node.network}")
    return "  ".join(bits)


def _counted(
    title: str, total: int, order: tuple[tuple[Provenance, str], ...], tally: Counter
) -> list[str]:
    """One provenance breakdown, listing only what is actually present.

    Zero rows are omitted rather than printed as `0`. A report is read to find
    something wrong, and eleven zeroes between the two numbers that matter is
    how a reader stops reading.
    """
    lines = [f"  {title:<20}{total}"]
    for source, description in order:
        count = tally.get(source, 0)
        if count:
            lines.append(f"      {count:>5}  {description}")
    return lines


def _unplaced_section(topo: Topology) -> list[str]:
    """Clients hanging off the placeholder, named so they can be chased."""
    stranded = sorted(
        (
            topo.nodes[e.src]
            for e in topo.edges
            if e.dst == UNKNOWN_UPLINK_ID and e.src in topo.nodes
        ),
        key=lambda n: n.label.lower(),
    )
    if not stranded:
        return []
    out = [
        "",
        "COULD NOT BE PLACED",
        "  Neither stat/sta nor the controller's topology graph reported an uplink",
        "  for these, so they hang off a placeholder rather than a guessed parent.",
        "  An overrides file is how you say where they really are; see",
        "  docs/overrides.md.",
        "",
    ]
    out += [f"  {_describe(node)}" for node in stranded]
    return out


def _addressless_section(topo: Topology) -> list[str]:
    """Clients that are correctly placed but have no address from any source.

    Worth naming separately from unplaced: these are on the map in the right
    place and merely thin, which is a different problem from not knowing where
    something is. On a support file it is normal for a few, since addresses come
    from a lease file and a neighbour table rather than from the client record.

    **Unplaced clients are excluded, not merely listed twice.** One with no
    address qualifies on both counts, and it was appearing in both sections with
    this one asserting it was "correctly placed" while the section above said
    the opposite. Being unplaced is the larger problem and already names it, so
    this reports what is left. The docstring said so before the code did.
    """
    unplaced = {e.src for e in topo.edges if e.dst == UNKNOWN_UPLINK_ID}
    nameless = sorted(
        (
            n
            for n in topo.nodes.values()
            if n.kind in _CLIENT_KINDS and not n.ip and n.id not in unplaced
        ),
        key=lambda n: n.label.lower(),
    )
    if not nameless:
        return []
    return [
        "",
        f"NO ADDRESS   ({len(nameless)} client(s))",
        "  On the map and correctly placed, but no source had an address.",
        "",
    ] + [f"  {_describe(node)}" for node in nameless]


def _dangling_networks(topo: Topology) -> list[str]:
    """Networks a client claims to be on that the controller does not list.

    Derivable rather than collected: `_resolve_network` falls back to the name on
    the client's own record when `network_id` matches no configured network, so a
    node whose network is not among the configured names is exactly that case.

    Usually harmless and worth seeing anyway. A support file's `network_table`
    omits WAN and VPN networks that a live `networkconf` returns, so the same
    network can be configured on one source and dangling on the other.
    """
    configured = {net.name for net in topo.networks.values()}
    referenced = Counter(
        n.network for n in topo.nodes.values() if n.kind in _CLIENT_KINDS and n.network
    )
    dangling = sorted((name, c) for name, c in referenced.items() if name not in configured)
    if not dangling:
        return []
    return [
        "",
        "NETWORKS NOT IN THE CONTROLLER'S LIST",
        "  A client reports being on these, but they are absent from networkconf,",
        "  so their VLAN and subnet are unknown to this map.",
        "",
    ] + [f"  {name}   ({count} client(s))" for name, count in dangling]


# What each payload contributes, and what a map loses without it. The
# consequence is the whole value of this section: "topology absent" means
# nothing to somebody who does not already know the pipeline, while "clients
# behind non-UniFi gear cannot be placed" is the symptom they are looking at.
#
# `device`, `client_active` and `networkconf` are required and a fetch fails
# without them, so they are here to be counted rather than to be missed.
_PAYLOADS: tuple[tuple[str, str, str], ...] = (
    ("device", "device", "infrastructure; the map is empty without it"),
    ("client_active", "client", "clients; without it the map is infrastructure only"),
    ("networkconf", "network", "network names and VLANs"),
    ("topology", "edge", "clients behind non-UniFi gear cannot be placed without it"),
    # Names only. Client *artwork* is keyed on the `dev_id` carried on each
    # client record, so it survives this being absent; the demo dataset is
    # exactly that case and draws product icons with no fingerprint payload at
    # all. Saying "and artwork" here would send somebody hunting the wrong gap.
    ("fingerprint", "product", "product names in client labels"),
    ("health", "subsystem", "the ISP name and ASN on the Internet node"),
    ("protect_cameras", "camera", "tells a camera from an Access reader of the same name"),
)


def _payload_records(name: str, payload: object) -> int | None:
    """How many records a payload holds, or None if it is unusable.

    Deliberately does not distinguish "absent" from "malformed" beyond this:
    both mean the map lost whatever that endpoint contributes, which is the
    question the report answers. Guessing at *why* a payload is unusable from
    its shape is how `report.py` nearly leaked site names.
    """
    if payload is None:
        return None
    if name == "topology":
        # A single object rather than a list of records, so it is counted by
        # the edges it carries. An empty `edges` list stays *present* with a
        # count of zero rather than being called unusable: the controller
        # answered, and "0 edges" is both honest and enough for a reader to see
        # the graph contributed nothing. Only a shape that cannot be read at all
        # is unusable.
        if not isinstance(payload, dict):
            return None
        edges = payload.get("edges")
        return len(edges) if isinstance(edges, list) else None
    if name == "fingerprint":
        if not isinstance(payload, dict):
            return None
        dev_ids = payload.get("dev_ids")
        return len(dev_ids) if isinstance(dev_ids, dict) else None
    if isinstance(payload, dict):
        payload = payload.get("data")
    if isinstance(payload, list):
        return len(payload)
    return None


def _endpoints_section(payloads: dict[str, object] | None) -> list[str]:
    """Which sources the map was actually built from.

    An optional endpoint that failed is logged once at fetch time and then never
    mentioned again, so a snapshot cached before an app was installed produces a
    thinner map every render with nothing saying why. The consequences are named
    because that is the part somebody can act on.
    """
    if payloads is None:
        return []
    missing = [
        (name, why)
        for name, _unit, why in _PAYLOADS
        if _payload_records(name, payloads.get(name)) is None
    ]
    present = [
        (name, unit, count)
        for name, unit, _why in _PAYLOADS
        if (count := _payload_records(name, payloads.get(name))) is not None
    ]

    out = ["", "WHAT THE SNAPSHOT CARRIES"]
    out += [
        f"  {name:<18}{count} {unit}{'' if count == 1 else 's'}" for name, unit, count in present
    ]
    if missing:
        out += [
            "",
            "  MISSING OR UNUSABLE",
            "  Each of these thins the map. Absence is often legitimate: an app",
            "  that is not installed, or an endpoint a controller version moved.",
            "",
        ]
        out += [f"  {name:<18}{why}" for name, why in missing]
    return out


def _artwork_summary(art: dict[str, int]) -> list[str]:
    """The ARTWORK section: counts by source, keyed on lookups that ran."""
    if not art:
        return []
    out = ["", "ARTWORK"]
    # Keyed on the presence of the totals, not on their value. Under
    # `--icons builtin` no catalogue lookup is attempted at all, so these
    # keys are absent and printing "0 of 0" would report a failure that
    # never happened: nothing was looked up, rather than looked up and not
    # found. Only `resolve_icons` sets them.
    looked_up = "device_total" in art or "client_total" in art
    if "device_total" in art:
        out.append(f"  devices by sysid    {art.get('device_found', 0)} of {art['device_total']}")
    if "client_total" in art:
        out.append(
            f"  clients             {art.get('client_found', 0)} of {art['client_total']}"
            f"   ({art.get('from_fingerprint', 0)} product,"
            f" {art.get('from_hardware', 0)} UniFi hardware,"
            f" {art.get('from_glyph', 0)} console glyph)"
        )
    if art.get("from_drawn"):
        # The reason differs by mode and the parenthetical has to follow it.
        # In `builtin` these were drawn because that is what was asked for;
        # saying "no catalogue match" there would invent a lookup failure.
        why = "no catalogue match" if looked_up else "--icons builtin, nothing was looked up"
        out.append(f"  drawn by us         {art['from_drawn']}   ({why})")
    return out


def _artwork_refused(ambiguous_artwork: list[tuple[str, int]]) -> list[str]:
    """The ARTWORK REFUSED AS AMBIGUOUS section."""
    if not ambiguous_artwork:
        return []
    counted = Counter(ambiguous_artwork)
    out = [
        "",
        "ARTWORK REFUSED AS AMBIGUOUS",
        "  These names matched more than one product, so no artwork was used.",
        "  Refusing is deliberate: picking one would be inventing data. Rename",
        "  the device in the console, or set an icon in an overrides file.",
        "",
    ]
    for (name, matches), times in sorted(counted.items()):
        seen = f" x{times}" if times > 1 else ""
        out.append(f"  {name!r}   matched {matches} catalogue entries{seen}")
    return out


def _artwork_section(sources: Sources) -> list[str]:
    """Artwork resolution, including the matches that were deliberately refused."""
    return _artwork_summary(sources.artwork) + _artwork_refused(sources.ambiguous_artwork)


def build_diagnostics(
    topo: Topology,
    sources: Sources | None = None,
    payloads: dict[str, object] | None = None,
) -> str:
    """Render the diagnostic report for a finished map.

    *payloads* is a `Snapshot.payloads`, and is the one input that is not
    derivable from the topology: an endpoint that failed at fetch time leaves no
    trace in the graph it would have enriched, only an absence.
    """
    sources = sources or Sources()

    node_tally = Counter(n.provenance for n in topo.nodes.values())
    edge_tally = Counter(e.provenance for e in topo.edges)

    observed = sum(edge_tally.get(p, 0) for p in _OBSERVED)
    asserted = edge_tally.get(Provenance.OVERRIDE, 0)
    unplaced = edge_tally.get(Provenance.UNPLACED, 0)

    out = [
        "=" * _WIDTH,
        f"unifi-map {__version__} map diagnostic report",
        "=" * _WIDTH,
        "",
        "  NOT SAFE TO SHARE. This names your devices, addresses and networks.",
        "  For something you can paste into a bug report, use `unifi-map shape`.",
        "",
        f"  source              {sources.origin}",
    ]
    if sources.site:
        out.append(f"  site                {sources.site}")
    if sources.controller_version:
        out.append(f"  controller          {sources.controller_version}")

    out += ["", "WHERE THE MAP CAME FROM"]
    out += _counted("nodes", len(topo.nodes), _NODE_SOURCES, node_tally)
    out.append("")
    out += _counted("links", len(topo.edges), _EDGE_SOURCES, edge_tally)

    out += [
        "",
        "HOW MUCH OF IT IS OBSERVED",
        f"  observed            {observed} of {len(topo.edges)} link(s)",
        f"  asserted by you     {asserted}",
        f"  no uplink reported  {unplaced}",
    ]

    out += _endpoints_section(payloads)
    out += _unplaced_section(topo)
    out += _addressless_section(topo)
    out += _dangling_networks(topo)
    out += _artwork_section(sources)

    if sources.notes:
        out += ["", "NOTES"] + [f"  {n}" for n in sources.notes]

    out += [
        "",
        "-" * _WIDTH,
        "Everything above describes the map this run drew. Nothing here was",
        "guessed: where a source is unknown it says so rather than choosing one.",
        "-" * _WIDTH,
    ]
    return "\n".join(out) + "\n"
