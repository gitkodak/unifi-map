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

Unrecognised field names *are* reported, which is the one judgement call. Field
names are controller schema and identical across installations, and discovering
one nobody here has seen is half the point on an unfamiliar version. They are
filtered to schema-shaped tokens (`_SCHEMA_TOKEN`) so that a value cannot arrive
disguised as a key.
"""

from __future__ import annotations

import platform
import re
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

# A field name is lowercase-ish, short, and has no spaces. A hostname, an SSID or
# a site name would not survive this, which is the point: it is a shape filter,
# not a content filter, so it cannot be argued into letting something through.
_SCHEMA_TOKEN = re.compile(r"^[a-z0-9][a-z0-9_.\-]{0,39}$")

# Wide enough for the header, narrow enough to paste anywhere.
_WIDTH = 74


@dataclass
class Extras:
    """Facts the caller knows that the snapshot does not carry."""

    source: str = "live fetch"
    controller_version: str | None = None
    sites_seen: int | None = None
    archive_bytes: int | None = None
    archive_entries: int | None = None
    members_found: int | None = None
    notes: list[str] = field(default_factory=list)


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
    # Reported so an unfamiliar controller version is visible, shape-filtered so
    # nothing that looks like a value can arrive here.
    unknown = sorted(f for f in seen - set(known) if _SCHEMA_TOKEN.match(f))
    rejected = len(seen - set(known)) - len(unknown)

    lines = [f"  {name}: {len(records)} record(s)"]
    lines += _wrapped("present", present)
    lines += _wrapped("absent", absent)
    if unknown:
        lines += _wrapped("unknown", unknown)
    if rejected:
        # Counted rather than named: these did not look like field names.
        lines.append(f"    ({rejected} further key(s) not reported: not schema-shaped)")
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

    out = [
        "=" * _WIDTH,
        f"unifi-map {__version__} network shape report",
        "=" * _WIDTH,
        "",
        f"  source              {extras.source}",
        f"  controller version  {extras.controller_version or 'not reported'}",
        f"  python              {sys.version.split()[0]} on {platform.system()}",
        "",
        "SCALE",
        f"  infrastructure      {infra}"
        f"   ({kinds[Kind.GATEWAY]} gateway, {kinds[Kind.SWITCH]} switch,"
        f" {kinds[Kind.AP]} ap, {kinds[Kind.BRIDGE]} bridge)",
        f"  clients             {wireless + wired}"
        f"   ({wireless} wireless, {wired} wired, {guests} guest)",
        f"  client networks     {len(topo.networks)}",
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
        f"  from overrides      {asserted_nodes} node(s), {asserted_edges} link(s)",
    ]

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
        out += _field_report(name, _records(payloads[name]))

    if extras.notes:
        out += ["", "NOTES"] + [f"  {n}" for n in extras.notes]

    out += [
        "",
        "-" * _WIDTH,
        "Counts, field names and versions only. No addresses, MACs, hostnames,",
        "SSIDs, site names or network names appear above, by construction.",
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
