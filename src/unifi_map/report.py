"""A short, plain-text description of a network, safe to hand to a stranger.

Several things this tool cannot do are blocked on evidence rather than effort:
multi-site handling has only ever seen one site, nothing has been profiled at
scale, the four support-file limits come from a single archive, and every
endpoint shape is verified against exactly one controller version. None of that
is solvable by thinking harder. It needs somebody else's network, and the one
thing they must never be asked for is their data.

So this reports the *shape* of a network and nothing else, in a form somebody
can read in full before deciding to paste it into an issue.

**Built from an allowlist, never by redacting.** Every line is a counted
integer, a boolean, or a field name from a list written in advance. Nothing here
walks user data looking for things to strip out, because a blocklist cannot be
complete: UniFi's own `pii_filter` is exactly that, matches on field names, and
was observed leaving unredacted access tokens in a real support file. Repeating
that here would be worse, since the whole promise of this file is that its
output is safe.

The concrete trap that settles the design: a support file's `devices.json` is a
list of objects **keyed by site name**, which users choose. Enumerating JSON keys
to describe a payload would therefore leak site names, on precisely the
multi-site archives most worth seeing. Container keys are never read; only
records inside them, and only their field names.

Unrecognised keys are **counted, never printed**. An earlier version printed
them, filtered to "schema-shaped" tokens, on the reasoning that a field name is
controller schema and discovering an unfamiliar one is half the point of running
this elsewhere. That filter did not work and could not: `10.0.0.5`, `nas`,
`secretssid` and `branch-office` all satisfy it, because a short lowercase token
is what a hostname, an SSID, an address and a site name look like. A payload
keyed by any of them would have been reproduced verbatim under a heading saying
that could not happen.

So the allowlist is now total: every name in the output comes from
`KNOWN_FIELDS`, and anything else contributes a number.
"""

from __future__ import annotations

import platform
import statistics
import sys
import textwrap
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from . import __version__
from .model import UNKNOWN_UPLINK_ID, Kind, Topology

# Fields worth knowing the presence of, per payload. Absence is as interesting
# as presence: it is how a controller version that moved something gets noticed.
KNOWN_FIELDS: dict[str, tuple[str, ...]] = {
    "device": (
        "mac",
        "type",
        "model",
        "sysid",
        "name",
        "state",
        "ip",
        "uplink",
        "port_table",
        "system-stats",
        "stp_priority",
        "root_switch",
        "last_seen",
        "network_table",
        "version",
        "adopted",
    ),
    "client_active": (
        "mac",
        "hostname",
        "name",
        "ip",
        "sw_mac",
        "sw_port",
        "ap_mac",
        "essid",
        "network_id",
        "network",
        "vlan",
        "dev_id",
        "dev_id_override",
        "oui",
        "is_guest",
        "is_wired",
        "rssi",
        "signal",
        "channel",
        "radio",
        "radio_name",
        "tx_rate",
        "rx_rate",
        "uptime",
    ),
    "networkconf": ("_id", "name", "vlan", "ip_subnet", "purpose", "is_guest", "enabled"),
    "health": (
        "subsystem",
        "status",
        "wan_ip",
        "isp_name",
        "isp_organization",
        "num_sta",
        "asn",
    ),
    "topology": ("vertices", "edges", "has_unknown_switch"),
}

# Wide enough for the header, narrow enough to paste anywhere.
_WIDTH = 74


@dataclass
class Extras:
    """Facts the caller knows that the snapshot does not carry."""

    source: str = "live fetch"
    controller_version: str | None = None
    sites_seen: int | None = None
    graphviz_version: str | None = None
    # Artwork resolution, which measures the most fragile join in the tool and
    # which nothing has ever recorded beyond one network.
    artwork: dict[str, int] = field(default_factory=dict)
    archive_bytes: int | None = None
    archive_entries: int | None = None
    members_found: int | None = None
    notes: list[str] = field(default_factory=list)


def _depth(topo: Topology) -> int:
    """Longest chain of uplinks. Fan-out alone does not describe a network:
    three hundred clients on one switch and three hundred behind five hops of
    daisy-chain are different problems."""
    parents = {}
    for edge in topo.edges:
        parents.setdefault(edge.src, edge.dst)

    best = 0
    for start in topo.nodes:
        seen, node, hops = {start}, start, 0
        while (node := parents.get(node)) is not None and node not in seen:
            seen.add(node)
            hops += 1
        best = max(best, hops)
    return best


def _records(payload: Any) -> list[dict[str, Any]]:
    """The records inside a payload, however it is wrapped.

    Never reads the keys of a mapping that is not the v1 envelope: those can be
    site names. `data` is ours to expect, anything else is left alone.
    """
    if isinstance(payload, dict):
        payload = payload.get("data", [])
    if not isinstance(payload, list):
        return []
    return [r for r in payload if isinstance(r, dict)]


# Payloads that are a single normalised object rather than a list of records.
# `_records` cannot detect this from shape, and must not try: a support file's
# site-keyed `devices.json` has the identical shape, and guessing wrong there
# would print the site names a user chose. So the allowance is by name, and the
# names are ours.
_SINGLE_OBJECT = frozenset({"topology"})


def _records_for(name: str, payload: Any) -> list[dict[str, Any]]:
    """The records to describe for *name*."""
    if name in _SINGLE_OBJECT and isinstance(payload, dict) and "data" not in payload:
        # Reported as zero records before, which made every field of the
        # topology graph read as absent on every controller.
        return [payload]
    return _records(payload)


def _wrapped(label: str, names: list[str]) -> list[str]:
    """One labelled field list, wrapped so the report pastes without reflowing."""
    if not names:
        return [f"    {label:<8} (none)"]
    body = textwrap.wrap(" ".join(names), width=_WIDTH - 13, break_long_words=False)
    return [f"    {label:<8} {body[0]}"] + [f"             {line}" for line in body[1:]]


def _field_report(name: str, records: list[dict[str, Any]]) -> list[str]:
    known = KNOWN_FIELDS.get(name, ())
    seen: set[str] = set()
    for record in records:
        seen |= {k for k in record if isinstance(k, str)}

    present = [f for f in known if f in seen]
    absent = [f for f in known if f not in seen]
    # **Counted, never named.** Naming these was the one judgement call in this
    # file and it was wrong. The filter that was supposed to keep values out
    # accepted `10.0.0.5`, `nas`, `secretssid` and `branch-office`, because a
    # short lowercase token is exactly what a hostname, an SSID, an address and
    # a site name all look like. A payload keyed by any of those would have had
    # this report reproduce them under a heading promising the opposite.
    #
    # The cost is real: discovering a field name nobody here has seen was half
    # the reason to run this against an unfamiliar controller. It is not worth
    # a document that claims to be publishable and is not. If that discovery
    # matters later it needs its own mode, which says plainly that its output
    # is not safe to paste anywhere.
    unknown = len(seen - set(known))

    lines = [f"  {name}: {len(records)} record(s)"]
    lines += _wrapped("present", present)
    lines += _wrapped("absent", absent)
    if unknown:
        lines.append(f"    unknown  {unknown} further key(s), not named: see the note below")
    return lines


def build_report(topo: Topology, payloads: dict[str, Any], extras: Extras | None = None) -> str:
    """Render the report. Every value is counted or chosen here, never copied."""
    extras = extras or Extras()
    kinds = Counter(node.kind for node in topo.nodes.values())
    infra = sum(kinds[k] for k in (Kind.GATEWAY, Kind.SWITCH, Kind.AP, Kind.BRIDGE))
    wireless = kinds[Kind.WIRELESS_CLIENT]
    wired = kinds[Kind.WIRED_CLIENT]
    guests = sum(1 for n in topo.nodes.values() if getattr(n, "is_guest", False))

    parents = Counter(edge.dst for edge in topo.edges)
    fan = sorted(parents.values()) or [0]
    unplaced = sum(1 for e in topo.edges if e.dst == UNKNOWN_UPLINK_ID)
    asserted_nodes = sum(1 for n in topo.nodes.values() if getattr(n, "asserted", False))
    asserted_edges = sum(1 for e in topo.edges if getattr(e, "asserted", False))
    offline = sum(1 for n in topo.nodes.values() if getattr(n, "offline", False))

    out = [
        "=" * _WIDTH,
        f"unifi-map {__version__} network shape report",
        "=" * _WIDTH,
        "",
        f"  source              {extras.source}",
        f"  controller version  {extras.controller_version or 'not reported'}",
        f"  python              {sys.version.split()[0]} on {platform.system()}",
        f"  graphviz            {extras.graphviz_version or 'not found'}",
        "",
        "SCALE",
        f"  infrastructure      {infra}"
        f"   ({kinds[Kind.GATEWAY]} gateway, {kinds[Kind.SWITCH]} switch,"
        f" {kinds[Kind.AP]} ap, {kinds[Kind.BRIDGE]} bridge)",
        f"  clients             {wireless + wired}"
        f"   ({wireless} wireless, {wired} wired, {guests} guest)",
        f"  client networks     {len({n.network for n in topo.nodes.values() if n.network})}"
        f"   (of {len(topo.networks)} configured)",
    ]
    if extras.sites_seen is not None:
        out.append(f"  sites in source     {extras.sites_seen}")

    out += [
        "",
        "SHAPE",
        f"  edges               {len(topo.edges)}",
        f"  children per parent min {fan[0]}, median {int(statistics.median(fan))}, max {fan[-1]}",
        f"  unplaced clients    {unplaced}"
        f"{'   (no uplink reported for these)' if unplaced else ''}",
        f"  depth               {_depth(topo)}",
        f"  from overrides      {asserted_nodes} node(s), {asserted_edges} link(s)",
        f"  offline devices     {offline}",
    ]

    if extras.artwork:
        a = extras.artwork
        out += [
            "",
            "ARTWORK   (how often the joins onto Ubiquiti's catalogues succeed)",
            f"  devices by sysid    {a.get('device_found', 0)} of {a.get('device_total', 0)}",
            f"  clients resolved    {a.get('client_found', 0)} of {a.get('client_total', 0)}"
            f"   ({a.get('from_fingerprint', 0)} product,"
            f" {a.get('from_hardware', 0)} UniFi hardware,"
            f" {a.get('from_glyph', 0)} generic glyph)",
        ]
        if not a.get("catalogue_cached", True):
            # Without this the section reads as a property of the network when
            # it is a property of the cache: the same snapshot gives 0 of 19 or
            # 19 of 19 depending only on whether artwork has ever been fetched.
            out.append("  NOTE: nothing is cached, so these count the cache and not the network.")
        elif not a.get("font_cached", True):
            out.append("  NOTE: no icon font cached, so the generic glyph count is always 0.")

    if extras.archive_bytes is not None:
        out += [
            "",
            "SUPPORT FILE",
            f"  uncompressed walked {extras.archive_bytes:,} bytes",
            f"  entries walked      {extras.archive_entries:,}",
            f"  members read        {extras.members_found} of 7",
        ]

    out += ["", "SCHEMA   (field names only; no values are read or shown)"]
    for name in sorted(payloads):
        out += _field_report(name, _records_for(name, payloads[name]))

    if extras.notes:
        out += ["", "NOTES"] + [f"  {n}" for n in extras.notes]

    out += [
        "",
        "-" * _WIDTH,
        "Counts, versions, and field names chosen in advance. Keys this tool does",
        "not recognise are counted but never printed, because a key can hold a",
        "value: no addresses, MACs, hostnames, SSIDs, site or network names appear",
        "above, by construction.",
        "-" * _WIDTH,
    ]
    return "\n".join(out) + "\n"


CONSENT = """\
This produces a short description of your network to help with a bug report or
a feature that needs data nobody here has.

It reports ONLY:
  * counts, such as how many switches, clients and networks you have
  * shape, such as how many things hang off the busiest device
  * field NAMES your controller returns, so we can see what your version has
  * versions of the tool, Python and your controller

It NEVER reports:
  * MAC addresses, IP addresses, hostnames or device names
  * SSIDs, network names, site names or your WAN address
  * any value from any field, only whether the field exists

The whole report is printed for you to read before you send it anywhere, and
it is short enough to read in full. Sending it is your decision and nothing is
transmitted by this tool.
"""
