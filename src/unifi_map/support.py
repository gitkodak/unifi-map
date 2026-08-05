"""Read a UniFi support file as an alternative to querying a controller.

A support file is the archive the console produces under Settings > System >
Support File. It contains, among a great deal of else, everything this tool
needs to draw a map, which makes it a second input worth supporting: it needs
neither credentials nor network access.

That is not the same as the archive being safe to hand over, and the two get
conflated easily. Reading one requires no trust; *sending* one discloses far
more than this module reads, including material this module never opens. See the
warning in `cli._fetch_from_support_file` and the section in `SECURITY.md`.

The output is a `Snapshot` carrying the same payload keys, in the same shapes,
that `client.py` produces from the live API. Everything downstream of `model.py`
is therefore unchanged and unaware of where the data came from.

Two of the payloads are reconstructed rather than copied, because the archive
stores them differently from the endpoints they stand in for:

* `networkconf` comes from the gateway's own `network_table`, which carries the
  same `_id`, `name`, `vlan` and `ip_subnet` fields as `rest/networkconf`. The
  archive's `setting.json` looks like the obvious place for this and is not: its
  contents are replaced with `**dynamic-hidden**`.
* `client_active` is assembled from the topology graph's CLIENT vertices joined
  to their edges, with addresses recovered from the gateway's DHCP leases and
  neighbour table.

Client fingerprints (`dev_id`) are not stored anywhere in the archive, but they
are recoverable for un-aliased clients, because the console names those
`"<product name> <last two MAC octets>"` and that product name is the catalogue
entry it resolved to. See `_dev_id_from_name`. That needs the fingerprint
database, which the archive also lacks, so it is supplied from the asset cache
of a previous live fetch. Without one, clients simply draw as glyphs.

Devices are unaffected either way: `devices.json` carries `sysid`, which is the
artwork join key for hardware.

The archive is large (150 MiB and several thousand entries is typical) and full
of logs that are none of our business, so it is read as a stream and only the
handful of members below are ever decoded.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re
import tarfile
from pathlib import Path
from typing import Any

from .client import Snapshot

log = logging.getLogger(__name__)

# The console names an un-aliased client "<product name> <last two MAC octets>".
_GENERATED_NAME = re.compile(r"^(?P<product>.+)\s+(?P<tail>[0-9a-f]{2}:[0-9a-f]{2})$", re.I)

# Members we read, keyed by a short internal name. Anchored to exactly one
# leading directory component, because everything sits under a `support-<id>/`
# directory whose name varies per file.
#
# The anchoring is load-bearing rather than tidy. Matching on a trailing path
# fragment instead lets a crafted archive add `evil/unifi/devices.json`, which
# ends with the same fragment; put it earlier in the stream and it is taken as
# the real file. Since the entire premise of this mode is that somebody else
# can send you the archive, that hands them the topology you see.
MEMBERS: dict[str, str] = {
    "devices": "unifi/devices.json",
    "topology": "unifi/topology.json",
    "infrastructure": "unifi/infrastructure.json",
    # The gateway's DHCP leases: MAC, address and the name the client asked for.
    "leases": "system/run/dnsmasq.lease",
    # The neighbour (ARP) table, which also covers statically addressed hosts
    # that never took a lease.
    "neighbours": "system/network/ip-neigh",
    # Only present when Protect is installed. Protect is the one authoritative
    # answer to whether a MAC is a camera, which is how UniFi hardware sitting
    # on a switch port as a client gets the right artwork instead of an
    # ambiguous guess.
    "protect_cameras": "unifi-protect/cameras/cameras.json",
    # The gateway's DPI engine: address, hostname and an ML fingerprint guess
    # per host. Read as a last-resort address source and, above
    # MIN_FINGERPRINT_CONFIDENCE, as a fingerprint. See _dpi_hosts.
    "dpi": "system/network/dpi-util-fprint-stats",
}

# One leading component, then exactly the expected path. Nothing deeper, nothing
# with an extra directory spliced in front of the tail.
_MEMBER_PATTERNS: dict[str, re.Pattern[str]] = {
    name: re.compile(r"^[^/]+/" + re.escape(tail) + r"$") for name, tail in MEMBERS.items()
}

# `ml.deviceNameID` is in the same id space as the controller's `dev_id`, but it
# is the gateway's live guess rather than the controller's settled answer, and
# it carries its own confidence. Checked against a live fetch of the same
# network: of seven hosts carrying a guess, four matched the controller and
# three did not, at confidences 25, 3 and 6. The one high-confidence guess (94)
# was right. There is no clean separation lower down (a 5 agreed, a 6 did not),
# so anything below this is discarded rather than drawn. Wrong product artwork
# is worse than an honest glyph.
MIN_FINGERPRINT_CONFIDENCE = 80

# A support file is attacker-supplied data as far as this tool is concerned: the
# whole point is that someone else can send you one. Decompressed members are
# held in memory, so cap them rather than trusting the archive's own headers.
#
# Defaults sized from a real 154 MiB archive off a UDM Pro Max, where the
# largest member read was `devices.json` at 400 KiB. 64 MiB is therefore about
# 160x observed and still refuses anything absurd. A very large site could
# exceed it legitimately, which is why both are tunable rather than guessed
# once: `--support-max-member` and `--support-max-total`.
MAX_MEMBER_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024

# An archive with millions of entries costs time to walk even though nothing is
# decoded, so neither size cap above stops one: entry count is unrelated to the
# bytes decoded.
#
# Tunable for the same reason the size caps are, and not because a hit is
# expected. The one archive measured held about 2,500 entries, but one sample of
# one small site says nothing about whether that number grows with the site, and
# the archive does carry per-client material. Rather than assume it does not
# scale, this is raisable like the others. Refusing to guess costs one flag.
MAX_ARCHIVE_ENTRIES = 100_000

# The cap the three above do not provide: total uncompressed bytes the archive
# is allowed to make us walk, wanted or not.
#
# Streaming tar has to read through a member's data to reach the next header, so
# a member we skip still costs its full decompressed size. Nothing above notices:
# the size caps only measure members we decode, and the entry cap counts headers.
# A 2 MiB archive holding one 2 GiB run of zeros passes all three and costs 21
# seconds of CPU, measured. Scaled up it is an afternoon.
#
# The default bounds the amplification rather than removing it: 4 GiB of zeros
# still costs about 40 seconds, from an archive a few MiB on disk. It is set
# against the compressed size of the one real support file seen (154 MiB),
# because that file is gone and its *uncompressed* size was never measured, so
# there is no honest basis for a tighter number. Treat 4 GiB as "obviously
# absurd" rather than as a measured ceiling, and tune it if you have data.
MAX_ARCHIVE_BYTES = 4 * 1024**3


def _human(size: int) -> str:
    """Byte count as a person would write it, for error messages."""
    for unit, scale in (("GiB", 1024**3), ("MiB", 1024**2), ("KiB", 1024)):
        if size >= scale:
            return f"{size / scale:.6g} {unit}"
    return f"{size} bytes"


class SupportFileError(RuntimeError):
    """Raised when a support file is unreadable or missing what we need."""


def _read_members(
    path: Path,
    max_member: int = MAX_MEMBER_BYTES,
    max_total: int = MAX_TOTAL_BYTES,
    max_entries: int = MAX_ARCHIVE_ENTRIES,
    max_archive: int = MAX_ARCHIVE_BYTES,
    stats: dict[str, int] | None = None,
) -> dict[str, bytes]:
    """Pull the wanted members out of the archive in a single streaming pass.

    Opened in stream mode (`r|gz`), so the archive is never seeked and never
    held in memory whole. Nothing is written to disk: members are decoded into
    memory and everything else is skipped as it goes past.

    The caps are arguments rather than constants because the right number
    depends on the site. Refusing a legitimate archive from a large network
    would be worse than the exhaustion the caps exist to prevent, so they are
    raisable from the command line and the error says which flag to use.
    """
    if max_entries > MAX_ARCHIVE_ENTRIES:
        # Raising this is a deliberate act, but the consequence is invisible:
        # the archive is walked entry by entry with nothing printed, so a run
        # that now takes minutes looks identical to one that has hung.
        log.warning(
            "Walking up to %s archive entries (the default is %s). This can take "
            "a while on a large archive, and produces no output until it finishes "
            "if the spinner is disabled.",
            f"{max_entries:,}",
            f"{MAX_ARCHIVE_ENTRIES:,}",
        )

    found: dict[str, bytes] = {}
    total = 0
    entries = 0
    walked = 0
    if stats is not None:
        stats.update(archive_bytes=0, archive_entries=0, members_found=0)
    try:
        with tarfile.open(path, "r|gz") as archive:
            for member in archive:
                entries += 1
                if entries > max_entries:
                    raise SupportFileError(
                        f"{path} holds more than {max_entries} entries; refusing to "
                        "keep walking it. The one archive measured held about 2,500. "
                        "Raise it with --support-max-entries if yours is legitimately "
                        "larger, and please open an issue saying so."
                    )
                # Counted for every member, including the ones skipped below,
                # because reaching the next header decompresses this one either
                # way. This is the only cap that sees a compression bomb.
                walked += max(0, member.size)
                if walked > max_archive:
                    raise SupportFileError(
                        f"{path} expands to more than {_human(max_archive)}. That is "
                        "far larger than any real support file, and reading further "
                        "would cost time without reading anything useful. Raise it "
                        "with --support-max-archive if yours is legitimately bigger."
                    )
                if len(found) == len(MEMBERS):
                    break
                # Skip anything that is not a plain file. A support file has no
                # business containing links or devices, and refusing them here
                # means we never have to reason about what one would mean.
                if not member.isfile():
                    continue
                name = next(
                    (
                        key
                        for key, pattern in _MEMBER_PATTERNS.items()
                        if pattern.match(member.name)
                    ),
                    None,
                )
                if name is None or name in found:
                    continue
                if member.size > max_member:
                    raise SupportFileError(
                        f"{member.name} is {member.size} bytes, over the {max_member} "
                        "byte limit. If this is a genuinely large site, raise it with "
                        "--support-max-member."
                    )
                handle = archive.extractfile(member)
                if handle is None:
                    continue
                data = handle.read(max_member + 1)
                if len(data) > max_member:
                    raise SupportFileError(
                        f"{member.name} expands past the {max_member} byte limit. "
                        "Raise it with --support-max-member if that is legitimate."
                    )
                total += len(data)
                if total > max_total:
                    raise SupportFileError(
                        f"Support file members exceed {max_total} bytes in total. "
                        "Raise it with --support-max-total if that is legitimate."
                    )
                found[name] = data
    except tarfile.TarError as exc:
        raise SupportFileError(f"{path} is not a readable gzipped tar archive: {exc}") from exc
    except OSError as exc:
        raise SupportFileError(f"Could not read {path}: {exc}") from exc
    if stats is not None:
        stats.update(archive_bytes=walked, archive_entries=entries, members_found=len(found))
    return found


def _load_json(members: dict[str, bytes], name: str) -> Any:
    raw = members.get(name)
    if raw is None:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        raise SupportFileError(
            f"{MEMBERS[name]} in the support file is not valid JSON: {exc}"
        ) from exc


def _device_sites(devices: Any) -> dict[str, list[dict[str, Any]]]:
    """Collect valid per-site device records from devices.json."""
    sites: dict[str, list[dict[str, Any]]] = {}
    if isinstance(devices, list):
        for block in devices:
            if not isinstance(block, dict):
                continue
            for site, records in block.items():
                if isinstance(records, list):
                    sites[site] = [record for record in records if isinstance(record, dict)]
    return sites


def _pick_site(devices: Any, requested: str | None) -> tuple[str, list[dict[str, Any]]]:
    """Choose which site to map, and return its device records.

    `devices.json` is a list of single-key objects, one per site, plus a `super`
    entry that is the controller's own pseudo-site and always empty. A console
    with one site therefore still needs picking apart.
    """
    sites = _device_sites(devices)

    real = {name: records for name, records in sites.items() if name != "super"}
    if not real:
        raise SupportFileError(
            "The support file's devices.json lists no sites. It may be from a "
            "console version this tool has not seen."
        )

    if requested is not None:
        if requested not in real:
            available = ", ".join(sorted(real)) or "none"
            raise SupportFileError(
                f"No site named {requested!r} in this support file. Found: {available}"
            )
        return requested, real[requested]

    if len(real) > 1:
        # Refused rather than guessed. This used to map whichever site had the
        # most devices and warn, which is the one thing the rest of this tool
        # never does: `resolve()` calls an ambiguous selector a loud error,
        # `sysid_for_name()` returns nothing rather than pick a favourite, and
        # an unreported uplink gets a placeholder rather than a plausible
        # parent. "Most devices" is a guess with no claim to being the one you
        # meant, and its failure mode is the worst kind: a complete, ordinary
        # looking map of the wrong network, off a warning nobody reads when
        # stderr is redirected.
        available = ", ".join(sorted(real))
        raise SupportFileError(
            f"This support file holds {len(real)} sites ({available}). Pass "
            "--site NAME to say which one to map; there is no sensible way to "
            "choose for you."
        )

    name = next(iter(real))
    return name, real[name]


def _site_block(payload: Any, site: str) -> dict[str, Any]:
    """Pull one site's object out of a `{site: {...}}` file."""
    if not isinstance(payload, dict):
        return {}
    block = payload.get(site)
    if isinstance(block, dict):
        return block
    # Fall back to the sole entry when the site key does not line up, which
    # keeps a single-site archive working if the naming ever diverges.
    values = [v for v in payload.values() if isinstance(v, dict)]
    return values[0] if len(values) == 1 else {}


def _networkconf(devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reconstruct `rest/networkconf` from the gateway's `network_table`.

    Only the gateway carries it, and it holds the same identifying fields the
    real endpoint returns, so VLAN names and subnets survive rather than
    degrading to opaque ids.
    """
    for device in devices:
        table = device.get("network_table")
        if not isinstance(table, list):
            continue
        records = [
            {
                "_id": entry.get("_id"),
                "name": entry.get("name"),
                "vlan": entry.get("vlan"),
                "ip_subnet": entry.get("ip_subnet"),
                "is_guest": entry.get("is_guest"),
                "purpose": entry.get("purpose"),
                "enabled": entry.get("enabled"),
            }
            for entry in table
            if isinstance(entry, dict) and entry.get("_id")
        ]
        if records:
            return records
    log.warning("No gateway network_table in the support file; VLAN names will be missing.")
    return []


def _parse_leases(raw: bytes | None) -> dict[str, tuple[str, str | None]]:
    """MAC to (address, hostname) from a dnsmasq lease file.

    Format is `<expiry> <mac> <address> <hostname> <client-id>`, with the
    hostname given as `*` when the client did not send one.
    """
    leases: dict[str, tuple[str, str | None]] = {}
    if not raw:
        return leases
    for line in raw.decode("utf-8", errors="replace").splitlines():
        fields = line.split()
        if len(fields) < 4:
            continue
        mac, address, hostname = fields[1].lower(), fields[2], fields[3]
        if not _is_address(address):
            continue
        leases[mac] = (address, None if hostname == "*" else hostname)
    return leases


def _parse_neighbours(raw: bytes | None) -> dict[str, str]:
    """MAC to address from `ip neigh` output.

    Covers hosts with static addresses, which never appear in a lease file. A
    MAC can hold several addresses across VLANs; the first wins, and IPv4 is
    preferred because that is what the rest of the map shows.
    """
    neighbours: dict[str, str] = {}
    if not raw:
        return neighbours
    for line in raw.decode("utf-8", errors="replace").splitlines():
        fields = line.split()
        if len(fields) < 2 or "lladdr" not in fields:
            continue
        # A neighbour the gateway could not resolve tells us nothing.
        if fields[-1] in {"FAILED", "INCOMPLETE"}:
            continue
        address = fields[0]
        # A line ending in `lladdr` has no MAC after it. Truncated log lines are
        # ordinary, and this file comes out of an attacker-supplied archive, so
        # the index is checked rather than assumed.
        index = fields.index("lladdr") + 1
        if index >= len(fields):
            continue
        mac = fields[index].lower()
        if not _is_address(address) or mac in neighbours:
            continue
        neighbours[mac] = address
    return neighbours


def _fingerprint_index(database: Any) -> dict[str, int]:
    """Normalized product name to `dev_id`, for names that identify exactly one.

    A name shared by two catalogue entries is dropped rather than guessed at,
    the same rule `AssetStore.sysid_for_name()` applies to hardware.
    """
    dev_ids = database.get("dev_ids") if isinstance(database, dict) else None
    if not isinstance(dev_ids, dict):
        return {}
    seen: dict[str, set[int]] = {}
    for raw_id, entry in dev_ids.items():
        if not isinstance(entry, dict):
            continue
        try:
            dev_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        key = _normalize_product(entry.get("name"))
        if key:
            seen.setdefault(key, set()).add(dev_id)
    return {name: next(iter(ids)) for name, ids in seen.items() if len(ids) == 1}


def _normalize_product(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _dev_id_from_name(name: str, mac: str, index: dict[str, int]) -> int | None:
    """Recover the fingerprint the controller assigned, from the client's name.

    When a client has no user-assigned alias, the console names it
    `"<product name> <last two MAC octets>"`, and that product name is the
    fingerprint database entry it resolved to. So the name is the fingerprint,
    written down. A support file keeps the name, which is how client artwork
    survives a fetch that has no `dev_id` anywhere in it.

    The rule is deliberately strict, because the alternative is inventing a
    product match. The trailing octets must genuinely be this client's, which
    is what proves the console generated the name rather than a person; and the
    remaining text must equal exactly one catalogue entry. On the network this
    was developed against it resolved 12 clients with no wrong answers, while
    correctly refusing a human-named "RokuUltraGreatRoom" that a looser
    substring rule mapped to the wrong Roku.
    """
    match = _GENERATED_NAME.match(name)
    if not match:
        return None
    tail = match.group("tail").lower()
    if not mac.endswith(tail):
        return None
    return index.get(_normalize_product(match.group("product")))


def _dpi_record(entry: Any) -> tuple[str, dict[str, Any]] | None:
    """Build one trusted DPI host record, if the entry contains usable data."""
    if not isinstance(entry, dict):
        return None
    mac = str(entry.get("mac") or "").lower()
    if not mac:
        return None

    record: dict[str, Any] = {}
    address = entry.get("ip")
    if isinstance(address, str) and _is_address(address):
        record["ip"] = address
    ml = entry.get("ml")
    if isinstance(ml, dict):
        confidence = ml.get("confidence")
        dev_id = ml.get("deviceNameID")
        if (
            isinstance(confidence, int | float)
            and confidence >= MIN_FINGERPRINT_CONFIDENCE
            and isinstance(dev_id, int)
        ):
            record["dev_id"] = dev_id
    return (mac, record) if record else None


def _dpi_hosts(raw: bytes | None) -> dict[str, dict[str, Any]]:
    """MAC to {ip, dev_id} from the gateway's DPI fingerprint stats.

    The file is a JSON object behind a `Response:` preamble, so it is not quite
    JSON and cannot be handed straight to the parser.

    Two things are taken from it, with different levels of trust. The address is
    an observation and is used freely, as a fallback behind the lease and
    neighbour tables. The fingerprint is an inference and is used only when the
    gateway itself is confident; see MIN_FINGERPRINT_CONFIDENCE.
    """
    hosts: dict[str, dict[str, Any]] = {}
    if not raw:
        return hosts
    text = raw.decode("utf-8", errors="replace")
    start = text.find("{")
    if start < 0:
        return hosts
    try:
        payload = json.loads(text[start:])
    except ValueError:
        log.debug("DPI fingerprint stats were not parseable; skipping them.")
        return hosts

    entries = payload.get("hosts") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return hosts

    for entry in entries:
        parsed = _dpi_record(entry)
        if parsed is not None:
            mac, record = parsed
            hosts[mac] = record
    return hosts


def _is_address(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def _client_record(
    vertex: Any,
    by_downlink: dict[str, dict[str, Any]],
    leases: dict[str, tuple[str, str | None]],
    neighbours: dict[str, str],
    dpi: dict[str, dict[str, Any]],
    guest_networks: set[str],
    fingerprint_index: dict[str, int],
) -> dict[str, Any] | None:
    """Rebuild one client record from a valid topology vertex."""
    if not isinstance(vertex, dict) or vertex.get("type") != "CLIENT":
        return None
    mac = str(vertex.get("mac") or "").lower()
    if not mac:
        return None

    edge = by_downlink.get(mac, {})
    wired = str(edge.get("type", "")).upper() == "WIRED"
    network_id = edge.get("networkId")
    address, lease_name = leases.get(mac, (None, None))
    seen = dpi.get(mac, {})
    record: dict[str, Any] = {
        "mac": mac,
        "name": vertex.get("name") or None,
        # The name the client asked DHCP for, used only when the console has no
        # alias of its own for it.
        "hostname": lease_name,
        "is_wired": wired,
        # A lease is authoritative, the neighbour table is a live observation,
        # and DPI is a last resort.
        "ip": address or neighbours.get(mac) or seen.get("ip"),
        "network_id": network_id,
        "is_guest": network_id in guest_networks,
    }
    # The console's own name is the better fingerprint where it exists,
    # because it is the answer the controller settled on rather than the
    # gateway's live guess.
    named = _dev_id_from_name(str(vertex.get("name") or ""), mac, fingerprint_index)
    if named is not None:
        record["dev_id"] = named
    elif seen.get("dev_id") is not None:
        record["dev_id"] = seen["dev_id"]
    if wired:
        record["sw_mac"] = edge.get("uplinkMac")
        # The port is the one occupied on the *uplink* device;
        # downlinkPortNumber is the client's own interface and is absent.
        record["sw_port"] = edge.get("uplinkPortNumber")
    else:
        record["ap_mac"] = edge.get("uplinkMac")
        record["essid"] = edge.get("essid")
        record["radio"] = edge.get("radioBand")
    return record


def _client_active(
    topology: dict[str, Any],
    leases: dict[str, tuple[str, str | None]],
    neighbours: dict[str, str],
    dpi: dict[str, dict[str, Any]],
    guest_networks: set[str],
    fingerprint_index: dict[str, int],
) -> list[dict[str, Any]]:
    """Rebuild `stat/sta` records from topology vertices and their edges.

    Each CLIENT vertex has exactly one edge naming it as the downlink, which
    carries the uplink, the port, and for wireless the SSID and band. That is
    everything the client builder reads apart from the fingerprint, which the
    archive does not contain.
    """
    vertices = topology.get("vertices")
    edges = topology.get("edges")
    if not isinstance(vertices, list) or not isinstance(edges, list):
        return []

    by_downlink: dict[str, dict[str, Any]] = {}
    for edge in edges:
        if isinstance(edge, dict):
            mac = str(edge.get("downlinkMac") or "").lower()
            if mac:
                by_downlink.setdefault(mac, edge)

    clients: list[dict[str, Any]] = []
    for vertex in vertices:
        record = _client_record(
            vertex,
            by_downlink,
            leases,
            neighbours,
            dpi,
            guest_networks,
            fingerprint_index,
        )
        if record is not None:
            clients.append(record)
    return clients


def _health(infrastructure: dict[str, Any]) -> list[dict[str, Any]]:
    """A `stat/health` WAN subsystem record from `ispData`.

    The archive names every WAN, active or not. The active one is what the
    Internet node should be labelled with; failing that, the highest priority.
    """
    isp_data = infrastructure.get("ispData")
    if not isinstance(isp_data, list):
        return []
    entries = [e for e in isp_data if isinstance(e, dict)]
    if not entries:
        return []
    active = next((e for e in entries if e.get("isActive")), None)
    if active is None:
        active = min(entries, key=lambda e: e.get("priority") or 99)
    return [
        {
            "subsystem": "wan",
            "isp_name": active.get("name"),
            "wan_ip": active.get("wanIp"),
            # Not read by the renderer today, but it is the key a brand-logo
            # lookup would need, and throwing it away here would hide that.
            "asn": active.get("asn"),
        }
    ]


def load_support_file(
    path: Path,
    site: str | None = None,
    fingerprint_db: Any = None,
    max_member: int = MAX_MEMBER_BYTES,
    max_total: int = MAX_TOTAL_BYTES,
    max_entries: int = MAX_ARCHIVE_ENTRIES,
    max_archive: int = MAX_ARCHIVE_BYTES,
    stats: dict[str, int] | None = None,
) -> Snapshot:
    """Read *path* and return a Snapshot equivalent to a live fetch.

    *fingerprint_db* is the client fingerprint database, which a support file
    does not contain. Supplying it is what lets client artwork resolve; without
    it clients still draw, without product artwork. `AssetStore.fingerprint_db()`
    obtains it from Ubiquiti's published copy, so no controller is involved.

    *max_member* and *max_total* cap what is decoded into memory; *max_entries*
    and *max_archive* cap how much of the archive is walked, in entries and in
    uncompressed bytes, which are separate concerns because neither follows the
    bytes decoded. All four are arguments because the right value depends on the
    site; see the constants.

    Raises `SupportFileError` if the archive is unreadable or does not carry
    the device and topology data a map needs.
    """
    members = _read_members(path, max_member, max_total, max_entries, max_archive, stats)
    missing = [MEMBERS[name] for name in ("devices", "topology") if name not in members]
    if missing:
        raise SupportFileError(
            f"{path} is missing {', '.join(missing)}. It may not be a UniFi "
            "support file, or may be from a console without the Network application."
        )

    all_devices = _load_json(members, "devices")
    if stats is not None:
        # Counted, never named: these keys are user-chosen site names.
        stats["sites_seen"] = sum(
            1
            for block in (all_devices if isinstance(all_devices, list) else [])
            if isinstance(block, dict)
            for name in block
            if name != "super"
        )
    site_name, devices = _pick_site(all_devices, site)
    topology = _site_block(_load_json(members, "topology"), site_name)
    infrastructure = _site_block(_load_json(members, "infrastructure"), site_name)

    networks = _networkconf(devices)
    guest_networks = {n["_id"] for n in networks if n.get("is_guest")}
    index = _fingerprint_index(fingerprint_db)
    clients = _client_active(
        topology,
        _parse_leases(members.get("leases")),
        _parse_neighbours(members.get("neighbours")),
        _dpi_hosts(members.get("dpi")),
        guest_networks,
        index,
    )

    log.info(
        "Read site %r from %s: %d devices, %d clients, %d networks.",
        site_name,
        path.name,
        len(devices),
        len(clients),
        len(networks),
    )
    addressed = sum(1 for c in clients if c.get("ip"))
    if clients and addressed < len(clients):
        log.info(
            "  %d of %d clients have an address; the rest took no DHCP lease "
            "and were not in the neighbour table.",
            addressed,
            len(clients),
        )
    fingerprinted = sum(1 for c in clients if c.get("dev_id") is not None)
    if index:
        log.info(
            "  %d of %d clients resolved a fingerprint for product artwork; the "
            "rest fall back to glyphs.",
            fingerprinted,
            len(clients),
        )
    else:
        log.info("  Clients will draw without product artwork.")

    payloads: dict[str, Any] = {
        "device": devices,
        "client_active": clients,
        "networkconf": networks,
        "health": _health(infrastructure),
        "topology": topology,
    }
    # Carried into the snapshot so the resolved ids also yield product names and
    # device types in labels, exactly as they would from a live fetch.
    if isinstance(fingerprint_db, dict) and fingerprint_db.get("dev_ids"):
        payloads["fingerprint"] = fingerprint_db
    # Absent unless Protect is installed, and the map is fine without it.
    cameras = _load_json(members, "protect_cameras")
    if isinstance(cameras, list):
        payloads["protect_cameras"] = cameras
    return Snapshot(payloads=payloads)
