"""Strip identifying detail from a topology so it can be shared.

A rendered map is not anonymous. Labels carry hostnames, addresses, VLAN names
and the WAN address, and an SVG holds all of it as selectable text, so somebody
asking for help with a layout problem has to redact by hand or not ask.

What goes: hostnames, IP addresses, MAC addresses (including the node
identifiers, which are derived from them), network and VLAN names, SSIDs, the
ISP name and the WAN address.

What stays, because otherwise the result is useless for the purpose it exists
for: how the topology is connected, device roles, models and artwork, port numbers,
counts, and which clients sit on which network. The point is a diagram somebody
can still diagnose.

This runs on the model, before anything is drawn. Nothing downstream needs to
know about it, and there is no way for a renderer to leak a value the model no
longer holds.
"""

from __future__ import annotations

from dataclasses import replace

from .model import UNKNOWN_UPLINK_ID, Edge, Kind, Network, Node, Topology

# RFC 5737 TEST-NET-3, which exists precisely for documentation.
PLACEHOLDER_WAN_IP = "203.0.113.1"

# Per-role name stems. Internet and the uplink placeholder are deliberately
# absent: neither carries anything identifying, and renaming them would only
# make the diagram harder to read.
_STEM: dict[Kind, str] = {
    Kind.GATEWAY: "gateway",
    Kind.SWITCH: "switch",
    Kind.AP: "ap",
    Kind.BRIDGE: "bridge",
    Kind.WIRED_CLIENT: "client",
    Kind.WIRELESS_CLIENT: "client",
    Kind.UNKNOWN: "device",
}

# The Internet node's label is the ISP name, which is very much identifying, so
# it is replaced rather than kept.
GENERIC_INTERNET_LABEL = "Internet"


def _sorted_nodes(topo: Topology) -> list[Node]:
    """Deterministic order, so the same device gets the same pseudonym twice.

    Sorted by node id, which is a MAC. The order is arbitrary but stable, which
    is what matters: a follow-up render has to line up with the first one.
    Deliberately not derived from the real name, since a hash of a short
    hostname is trivially reversible.
    """
    return sorted(topo.nodes.values(), key=lambda n: n.id)


def _network_names(topo: Topology) -> dict[str, str]:
    real = sorted({n.network for n in topo.nodes.values() if n.network})
    return {name: f"network-{i}" for i, name in enumerate(real, start=1)}


def id_map(topo: Topology) -> dict[str, str]:
    """Old node id to pseudonym, deterministic for a given topology.

    Public because artwork has to be resolved *before* obfuscation and then
    carried across. UniFi hardware that appears as a client is matched on its
    hostname, so scrubbing the hostname first would lose its artwork.
    """
    ids: dict[str, str] = {}
    counters: dict[str, int] = {}
    for node in _sorted_nodes(topo):
        if node.id in (UNKNOWN_UPLINK_ID, "internet"):
            ids[node.id] = node.id
            continue
        stem = _STEM.get(node.kind, "node")
        counters[stem] = counters.get(stem, 0) + 1
        ids[node.id] = f"{stem}-{counters[stem]:02d}"
    return ids


def obfuscate(topo: Topology) -> Topology:
    """Return a copy of *topo* with identifying detail replaced."""
    networks = _network_names(topo)
    net_index = {alias: i for i, alias in enumerate(networks.values(), start=1)}

    ids = id_map(topo)
    labels = {
        node.id: (
            node.label
            if node.id == UNKNOWN_UPLINK_ID
            else GENERIC_INTERNET_LABEL
            if node.id == "internet"
            else ids[node.id]
        )
        for node in topo.nodes.values()
    }
    # Host octet per network, so addresses group the way the real ones did.
    hosts: dict[int, int] = {}

    nodes: dict[str, Node] = {}
    for node in _sorted_nodes(topo):
        new_id = ids[node.id]
        network = networks.get(node.network) if node.network else None

        if node.kind is Kind.INTERNET:
            # The WAN address is as identifying as anything on the map.
            ip = PLACEHOLDER_WAN_IP if node.ip else None
            detail = None
        elif node.ip:
            idx = net_index.get(network, 0)
            hosts[idx] = hosts.get(idx, 9) + 1
            ip = f"10.{idx}.0.{hosts[idx]}"
        else:
            ip = None

        detail = None if node.kind is Kind.INTERNET else node.detail
        if node.kind in (Kind.WIRED_CLIENT, Kind.WIRELESS_CLIENT) and node.dev_id is None:
            # Without a fingerprint, `detail` is whatever the controller offered,
            # which for a wireless client is the SSID. Anything derived from a
            # fingerprint is a catalogue product name and stays.
            detail = None

        nodes[new_id] = replace(
            node,
            id=new_id,
            label=labels[node.id],
            ip=ip,
            network=network,
            detail=detail,
            # Kept on purpose: these drive artwork lookup and say nothing about
            # the owner, only what the hardware is.
            sysid=node.sysid,
            dev_id=node.dev_id,
            oui=node.oui,
            hardware_type=node.hardware_type,
            # Dropped, unlike the other artwork keys. An ASN names the ISP as
            # squarely as `isp_name` does, and it would redraw their brand mark
            # on a map whose whole point is that it can be shared.
            asn=None,
        )

    # `asserted` travels with the edge. Nodes keep theirs for free because they
    # are rebuilt with `replace()`; edges are constructed field by field, so a
    # new field has to be added here or it is silently dropped. It was, and the
    # effect was that obfuscating a map redrew every override-asserted link as
    # though a controller had reported it. That is the one distinction this
    # project promises never to blur, and `--obfuscate` is precisely the mode
    # where the reader cannot check.
    edges = [
        Edge(
            src=ids[e.src],
            dst=ids[e.dst],
            label=e.label,
            wireless=e.wireless,
            asserted=e.asserted,
        )
        for e in topo.edges
        if e.src in ids and e.dst in ids
    ]

    renamed_networks = {
        key: Network(
            id=key,
            name=networks.get(net.name, net.name),
            vlan=net.vlan,
            subnet=f"10.{net_index.get(networks.get(net.name, net.name), 0)}.0.0/24",
            # Whether a network is for guests says nothing about whose network
            # it is, and the node-level `is_guest` already survives obfuscation.
            is_guest=net.is_guest,
        )
        for key, net in topo.networks.items()
    }

    return Topology(nodes=nodes, edges=edges, networks=renamed_networks)
