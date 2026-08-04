"""Normalize controller JSON into a plain graph.

Everything downstream (DOT, draw.io) renders from :class:`Topology` and never
touches raw controller payloads, so a schema change upstream is absorbed here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .client import Snapshot, unwrap

# UniFi's device `type` field, mapped to our own kinds. Prefix-matched, longest
# first, because new hardware families appear regularly and an unrecognised
# device should still land on the map.
_DEVICE_TYPE_PREFIXES: list[tuple[str, str]] = [
    ("udm", "gateway"),
    ("ugw", "gateway"),
    ("uxg", "gateway"),
    ("ucg", "gateway"),
    ("usw", "switch"),
    ("usl", "switch"),
    ("uap", "ap"),
    ("ubb", "bridge"),
]


# Synthetic parent for clients whose uplink the controller does not report.
UNKNOWN_UPLINK_ID = "unknown-uplink"


class Kind(StrEnum):
    GATEWAY = "gateway"
    SWITCH = "switch"
    AP = "ap"
    BRIDGE = "bridge"
    WIRED_CLIENT = "wired_client"
    WIRELESS_CLIENT = "wireless_client"
    INTERNET = "internet"
    UNKNOWN = "unknown"


@dataclass
class Node:
    id: str
    label: str
    kind: Kind
    ip: str | None = None
    model: str | None = None
    network: str | None = None
    vlan: int | None = None
    detail: str | None = None
    offline: bool = False
    # UniFi hardware id. The join key to Ubiquiti's device catalog for artwork;
    # `model` strings do not reliably match the catalog's shortnames.
    sysid: int | None = None
    # Clients only. UniFi picks its client glyph from exactly these two facts.
    is_guest: bool = False
    wireless: bool = False
    # Fingerprint id, the join key to Ubiquiti's client artwork.
    dev_id: int | None = None
    # Vendor string from the controller. A Ubiquiti OUI means the client may be
    # UniFi hardware that happens to appear as a client, so it can be looked up
    # in the hardware catalog instead.
    oui: str | None = None
    # Set when another UniFi app can vouch for what the device is, for example
    # "camera" when Protect reports this MAC as one. Used to disambiguate a
    # hostname that matches several products.
    hardware_type: str | None = None
    # Internet node only. The upstream provider's autonomous system number,
    # which is the join key to Ubiquiti's ISP brand marks.
    asn: int | None = None
    # Stated in an overrides file rather than reported by anything. Drawn
    # differently for the same reason `Edge.asserted` is: the map must never
    # present a claim and an observation as though they were the same thing.
    asserted: bool = False

    @property
    def glyph_name(self) -> str | None:
        """The UniFi client-icon class this node would get in the web UI.

        Mirrors `getIconClassName` in the controller's web app, which resolves
        every client to one of user/guest x wired/wireless.
        """
        if self.kind not in (Kind.WIRED_CLIENT, Kind.WIRELESS_CLIENT):
            return None
        who = "guest" if self.is_guest else "user"
        how = "wireless" if self.wireless else "wired"
        return f"{who}-{how}"


@dataclass
class Edge:
    src: str
    dst: str
    label: str | None = None
    wireless: bool = False
    # Stated by the user in an overrides file rather than reported by the
    # controller. Drawn differently, so an assertion is never mistaken for an
    # observation.
    asserted: bool = False


@dataclass
class Network:
    id: str
    name: str
    vlan: int | None
    subnet: str | None
    # `rest/networkconf` reports this and the JSON export already tried to emit
    # it, through a `getattr` that could never succeed because the field did not
    # exist. Carried properly rather than dropping the export: which networks
    # are guest networks is exactly the sort of thing a consumer of the JSON
    # wants and cannot derive.
    is_guest: bool = False


@dataclass
class Topology:
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    networks: dict[str, Network] = field(default_factory=dict)

    def add(self, node: Node) -> None:
        self.nodes[node.id] = node

    @property
    def infrastructure(self) -> list[Node]:
        # UNKNOWN is included so unclassified hardware and the
        # "uplink not reported" placeholder survive into per-network views;
        # without it their clients would float unlinked again.
        infra = {
            Kind.GATEWAY,
            Kind.SWITCH,
            Kind.AP,
            Kind.BRIDGE,
            Kind.INTERNET,
            Kind.UNKNOWN,
        }
        return [n for n in self.nodes.values() if n.kind in infra]

    def counts(self) -> dict[str, int]:
        tally: dict[str, int] = {}
        for node in self.nodes.values():
            tally[node.kind.value] = tally.get(node.kind.value, 0) + 1
        return tally


def _classify(device: dict[str, Any]) -> Kind:
    raw = str(device.get("type") or "").lower()
    for prefix, kind in _DEVICE_TYPE_PREFIXES:
        if raw.startswith(prefix):
            return Kind(kind)
    return Kind.UNKNOWN


def _device_label(device: dict[str, Any]) -> str:
    for key in ("name", "device_name", "model_display", "model"):
        value = device.get(key)
        if value:
            return str(value)
    return str(device.get("mac") or "unknown")


def _client_label(client: dict[str, Any]) -> str:
    for key in ("name", "hostname", "display_name"):
        value = client.get(key)
        if value:
            return _shorten(str(value))
    # Fall back to manufacturer + MAC tail, which is far more useful on a
    # diagram than a bare MAC.
    oui = client.get("oui")
    mac = str(client.get("mac") or "")
    tail = mac.replace(":", "")[-6:].upper()
    if oui and tail:
        return f"{_shorten(str(oui))} {tail}"
    return mac or "unknown client"


def _shorten(text: str, limit: int = 24) -> str:
    """Trim overlong vendor strings.

    Registered OUI names run to things like "Motorola (Wuhan) Mobility
    Technologies Communication Co., Ltd.", which Graphviz renders as an ellipse
    wide enough to distort the whole layout. Trailing corporate suffixes carry
    no identifying information, so cutting them costs nothing and buys density.
    """
    cleaned = " ".join(text.split())
    for suffix in (
        " Co., Ltd.",
        " Co.,Ltd.",
        " Co., Ltd",
        " Ltd.",
        " Inc.",
        " GmbH",
        " Corporation",
    ):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)]
            break
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _coerce_int(value: Any) -> int | None:
    """The controller reports sysid as a decimal int, but be tolerant."""
    if value is None:
        return None
    try:
        return int(str(value).strip(), 10)
    except (TypeError, ValueError):
        return None


def _norm_mac(value: Any) -> str | None:
    if not value:
        return None
    mac = str(value).strip().lower()
    return mac or None


def topology_uplinks(snapshot: Snapshot) -> dict[str, tuple[str, bool]]:
    """Downlink MAC to (uplink MAC, wireless) from the controller's own graph.

    `stat/sta` only reports a client's uplink when that uplink is a UniFi device,
    so anything behind a non-UniFi box comes back with no `sw_mac` at all: VMs
    and containers behind a NAS, or a client on an unmanaged switch. The console
    still draws those correctly, because it uses this endpoint, where a CLIENT
    can be another client's uplink.

    Read defensively. This is a v2 endpoint whose structure has changed before,
    so anything unexpected yields nothing rather than raising.
    """
    payload = snapshot.get("topology")
    if not isinstance(payload, dict):
        return {}
    edges = payload.get("edges")
    if not isinstance(edges, list):
        return {}

    uplinks: dict[str, tuple[str, bool]] = {}
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        down = _norm_mac(edge.get("downlinkMac"))
        up = _norm_mac(edge.get("uplinkMac"))
        if down and up and down != up:
            uplinks[down] = (up, str(edge.get("type", "")).upper() == "WIRELESS")
    return uplinks


def protect_camera_macs(snapshot: Snapshot) -> set[str]:
    """MACs that UniFi Protect reports as cameras.

    Protect is the only authoritative source for this. A camera on a switch port
    is just a client to the Network app, with no fingerprint, so its hostname is
    the only clue. That hostname is often ambiguous ("g3-flex" matches both a
    Protect camera and an Access reader), and this resolves it.
    """
    payload = snapshot.get("protect_cameras")
    records = payload if isinstance(payload, list) else unwrap(payload)
    macs: set[str] = set()
    for entry in records:
        raw = entry.get("mac")
        if not raw:
            continue
        # Protect reports MACs unpunctuated: 02AABB0B5F76.
        hexed = "".join(ch for ch in str(raw).lower() if ch in "0123456789abcdef")
        if len(hexed) == 12:
            macs.add(":".join(hexed[i : i + 2] for i in range(0, 12, 2)))
    return macs


def _fingerprint_record(
    raw_id: Any,
    entry: Any,
    families: Any,
    types: Any,
    vendors: Any,
) -> tuple[int, dict[str, str]] | None:
    """Normalize one controller fingerprint record, if it is usable."""
    if not isinstance(entry, dict):
        return None
    try:
        dev_id = int(raw_id)
    except (TypeError, ValueError):
        return None

    record: dict[str, str] = {}
    name = str(entry.get("name") or "").strip()
    if name:
        record["name"] = name
    for key, table in (
        ("family", families),
        ("dev_type", types),
        ("vendor", vendors),
    ):
        value = table.get(entry.get(f"{key}_id")) if isinstance(table, dict) else None
        if isinstance(value, str) and value.strip():
            record[key] = value.strip()
    return (dev_id, record) if record else None


def build_fingerprints(snapshot: Snapshot) -> dict[int, dict[str, str]]:
    """Index the controller's fingerprint database by dev_id.

    Gives real product names and device families, so an unnamed client reads
    "Govee H61E1 / Smart Light Strip" instead of "Espressif 003003".
    """
    payload = snapshot.get("fingerprint")
    if not isinstance(payload, dict):
        return {}

    dev_ids = payload.get("dev_ids")
    if not isinstance(dev_ids, dict):
        return {}

    families = payload.get("family_ids") or {}
    types = payload.get("dev_type_ids") or {}
    vendors = payload.get("vendor_ids") or {}

    index: dict[int, dict[str, str]] = {}
    for raw_id, entry in dev_ids.items():
        parsed = _fingerprint_record(raw_id, entry, families, types, vendors)
        if parsed is not None:
            dev_id, record = parsed
            index[dev_id] = record
    return index


def build_networks(snapshot: Snapshot) -> dict[str, Network]:
    networks: dict[str, Network] = {}
    for entry in unwrap(snapshot.get("networkconf")):
        net_id = str(entry.get("_id") or "")
        if not net_id:
            continue
        vlan_raw = entry.get("vlan")
        try:
            vlan = int(vlan_raw) if vlan_raw not in (None, "") else None
        except (TypeError, ValueError):
            vlan = None
        networks[net_id] = Network(
            id=net_id,
            name=str(entry.get("name") or "unnamed"),
            vlan=vlan,
            subnet=entry.get("ip_subnet"),
            is_guest=bool(entry.get("is_guest")),
        )
    return networks


def _resolve_network(
    record: dict[str, Any], networks: dict[str, Network]
) -> tuple[str | None, int | None]:
    """Best-effort network name/VLAN for a client record."""
    net_id = str(record.get("network_id") or "")
    if net_id and net_id in networks:
        net = networks[net_id]
        return net.name, net.vlan

    name = record.get("network")
    vlan_raw = record.get("vlan")
    try:
        vlan = int(vlan_raw) if vlan_raw not in (None, "") else None
    except (TypeError, ValueError):
        vlan = None

    if name:
        return str(name), vlan

    # Match on VLAN id if that is all we have.
    if vlan is not None:
        for net in networks.values():
            if net.vlan == vlan:
                return net.name, net.vlan
    return None, vlan


def wan_info(snapshot: Snapshot) -> tuple[str | None, str | None, int | None]:
    """(isp_name, wan_ip, asn) from the health endpoint's WAN subsystem.

    The controller knows who the upstream provider is, so the Internet node can
    say "Carl's Discount Internet & Tackle" rather than a generic label, and the
    ASN alongside it is what Ubiquiti key their provider brand marks on.
    """
    for entry in unwrap(snapshot.get("health")):
        if entry.get("subsystem") != "wan":
            continue
        isp = entry.get("isp_name") or entry.get("isp_organization")
        return (str(isp) if isp else None, entry.get("wan_ip"), _coerce_int(entry.get("asn")))
    return None, None, None


def _build_device_nodes(
    topo: Topology, devices: list[dict[str, Any]], include_offline: bool
) -> set[str]:
    """Add included infrastructure devices and return their MAC addresses."""
    device_macs: set[str] = set()
    for device in devices:
        mac = _norm_mac(device.get("mac"))
        if not mac:
            continue
        kind = _classify(device)
        # UniFi state: 1 = connected. Anything else is not currently adopted
        # and online.
        offline = device.get("state") not in (1, "1")
        if offline and not include_offline:
            # Left out of device_macs too, so nothing links to a device that is
            # not on the map.
            continue
        device_macs.add(mac)
        topo.add(
            Node(
                id=mac,
                label=_device_label(device),
                kind=kind,
                ip=device.get("ip"),
                model=device.get("model"),
                detail=str(device.get("model") or "") or None,
                offline=offline,
                sysid=_coerce_int(device.get("sysid")),
            )
        )
    return device_macs


def _build_infrastructure_edges(
    topo: Topology,
    devices: list[dict[str, Any]],
    device_macs: set[str],
) -> bool:
    """Add device uplinks and report whether the Internet node is needed."""
    has_internet = False
    for device in devices:
        mac = _norm_mac(device.get("mac"))
        # Excluded devices (offline, when include_offline is False) have no node,
        # so they can neither carry nor terminate an uplink edge.
        if not mac or mac not in topo.nodes:
            continue
        uplink = device.get("uplink") or {}
        parent = _norm_mac(uplink.get("uplink_mac") or uplink.get("ap_mac"))
        port = uplink.get("uplink_remote_port") or uplink.get("remote_port")
        wireless = str(uplink.get("type") or "").lower() in {"wireless", "wifi"}

        if parent and parent in device_macs and parent != mac:
            topo.edges.append(
                Edge(
                    src=mac,
                    dst=parent,
                    label=f"port {port}" if port else None,
                    wireless=wireless,
                )
            )
        elif topo.nodes[mac].kind == Kind.GATEWAY:
            has_internet = True
            topo.edges.append(Edge(src=mac, dst="internet", label="WAN"))
    return has_internet


def build_topology(
    snapshot: Snapshot,
    include_clients: bool = True,
    include_offline: bool = True,
) -> Topology:
    """Normalize a snapshot into a graph.

    *include_offline* keeps devices the controller still lists but that are not
    currently connected. Set it False to drop hardware that has been
    decommissioned but never forgotten by the controller.
    """
    topo = Topology(networks=build_networks(snapshot))

    devices = unwrap(snapshot.get("device"))
    device_macs = _build_device_nodes(topo, devices, include_offline)

    # A device whose uplink MAC is not itself a known device is treated as
    # top-of-tree and attached to the Internet node.
    has_internet = _build_infrastructure_edges(topo, devices, device_macs)

    if has_internet:
        isp, wan_ip, asn = wan_info(snapshot)
        topo.add(
            Node(
                id="internet",
                label=isp or "Internet",
                kind=Kind.INTERNET,
                ip=wan_ip,
                detail="Internet" if isp else None,
                asn=asn,
            )
        )

    if include_clients:
        _add_clients(
            topo,
            snapshot,
            device_macs,
            build_fingerprints(snapshot),
            protect_camera_macs(snapshot),
            topology_uplinks(snapshot),
        )

    return topo


def _add_clients(
    topo: Topology,
    snapshot: Snapshot,
    device_macs: set[str],
    fingerprints: dict[int, dict[str, str]] | None = None,
    camera_macs: set[str] | None = None,
    uplinks: dict[str, tuple[str, bool]] | None = None,
) -> None:
    fingerprints = fingerprints or {}
    camera_macs = camera_macs or set()
    unplaced: list[str] = []
    for client in unwrap(snapshot.get("client_active")):
        mac = _norm_mac(client.get("mac"))
        if not mac or mac in topo.nodes:
            continue

        is_wired = bool(client.get("is_wired"))
        net_name, vlan = _resolve_network(client, topo.networks)
        # dev_id_override is the user's correction in the UI, so it wins.
        fp_id = _coerce_int(client.get("dev_id_override")) or _coerce_int(client.get("dev_id"))
        fingerprint = fingerprints.get(fp_id) if fp_id is not None else None

        if is_wired:
            parent = _norm_mac(client.get("sw_mac"))
            port = client.get("sw_port")
            edge_label = f"port {port}" if port not in (None, "") else None
            detail = None
            wireless = False
        else:
            parent = _norm_mac(client.get("ap_mac"))
            essid = client.get("essid")
            radio = client.get("radio_name") or client.get("radio")
            edge_label = str(radio) if radio else None
            detail = str(essid) if essid else None
            wireless = True

        label = _client_label(client)
        if fingerprint:
            # Only substitute when the client has no name of its own: a
            # user-assigned alias is more useful than a catalogue name.
            if not any(client.get(k) for k in ("name", "hostname", "display_name")):
                label = _shorten(fingerprint.get("name") or label, limit=28)
            detail = fingerprint.get("dev_type") or fingerprint.get("family") or detail

        topo.add(
            Node(
                id=mac,
                label=label,
                kind=Kind.WIRED_CLIENT if is_wired else Kind.WIRELESS_CLIENT,
                ip=client.get("ip"),
                network=net_name,
                vlan=vlan,
                detail=detail,
                is_guest=bool(client.get("is_guest")),
                wireless=not is_wired,
                dev_id=fp_id,
                oui=str(client.get("oui")) if client.get("oui") else None,
                hardware_type="camera" if mac in camera_macs else None,
            )
        )

        if parent and parent in device_macs:
            topo.edges.append(Edge(src=mac, dst=parent, label=edge_label, wireless=wireless))
        else:
            # Deferred. The controller's own graph often knows this client's
            # uplink even when stat/sta does not, and that uplink may be another
            # client that has not been added yet.
            unplaced.append(mac)

    _place_remaining(topo, unplaced, uplinks or {})


def _place_remaining(
    topo: Topology, unplaced: list[str], uplinks: dict[str, tuple[str, bool]]
) -> None:
    """Attach clients that stat/sta could not place, using the controller graph.

    Runs once every client exists, because an uplink is frequently another
    client, such as a NAS host carrying its own VMs. Anything still unresolved
    gets the explicit placeholder, which is honest about the gap rather than
    guessing a plausible parent.
    """
    for mac in unplaced:
        parent, wireless = uplinks.get(mac, (None, False))
        if parent and parent in topo.nodes and parent != mac:
            topo.edges.append(Edge(src=mac, dst=parent, wireless=wireless))
            continue
        if UNKNOWN_UPLINK_ID not in topo.nodes:
            topo.add(
                Node(
                    id=UNKNOWN_UPLINK_ID,
                    label="Uplink not reported by controller",
                    kind=Kind.UNKNOWN,
                )
            )
        topo.edges.append(Edge(src=mac, dst=UNKNOWN_UPLINK_ID))


def filter_by_network(topo: Topology, network_name: str) -> Topology:
    """A view containing all infrastructure plus only clients on *network_name*.

    Infrastructure is always kept so each per-VLAN diagram stays anchored to
    the same gateway/switch/AP skeleton and reads as a slice of one map.
    """
    keep: dict[str, Node] = {n.id: n for n in topo.infrastructure}
    for node in topo.nodes.values():
        if node.kind in (Kind.WIRED_CLIENT, Kind.WIRELESS_CLIENT) and node.network == network_name:
            keep[node.id] = node
    edges = [e for e in topo.edges if e.src in keep and e.dst in keep]
    return Topology(nodes=keep, edges=edges, networks=topo.networks)


def client_networks(topo: Topology) -> list[str]:
    """Network names that actually have clients, in stable order."""
    names = {
        n.network
        for n in topo.nodes.values()
        if n.kind in (Kind.WIRED_CLIENT, Kind.WIRELESS_CLIENT) and n.network
    }
    return sorted(names)
