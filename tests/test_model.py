from __future__ import annotations

import pytest

from unifi_map.client import Snapshot, unwrap
from unifi_map.model import (
    UNKNOWN_UPLINK_ID,
    Edge,
    Kind,
    Node,
    Provenance,
    Topology,
    build_fingerprints,
    build_topology,
    client_networks,
    filter_by_network,
)

from .conftest import AP_MAC, GATEWAY_MAC, SPARE_SWITCH_MAC, SWITCH_MAC


def test_unwrap_handles_both_response_shapes():
    assert unwrap({"data": [{"a": 1}]}) == [{"a": 1}]
    assert unwrap([{"a": 1}]) == [{"a": 1}]


def test_unwrap_tolerates_unexpected_shapes():
    # A controller version change must thin the diagram, not raise.
    assert unwrap(None) == []
    assert unwrap({"meta": {"rc": "error"}}) == []
    assert unwrap("nonsense") == []
    assert unwrap([1, 2, {"a": 1}]) == [{"a": 1}]


def test_devices_are_classified_by_type_prefix(snapshot: Snapshot):
    topo = build_topology(snapshot)
    assert topo.nodes[GATEWAY_MAC].kind is Kind.GATEWAY
    assert topo.nodes[SWITCH_MAC].kind is Kind.SWITCH
    assert topo.nodes[AP_MAC].kind is Kind.AP


def test_uplinks_become_edges_with_port_labels(snapshot: Snapshot):
    topo = build_topology(snapshot)
    edges = {(e.src, e.dst): e for e in topo.edges}
    assert edges[(SWITCH_MAC, GATEWAY_MAC)].label == "port 9"
    assert edges[(AP_MAC, SWITCH_MAC)].label == "port 5"


def test_gateway_gets_an_internet_node(snapshot: Snapshot):
    topo = build_topology(snapshot)
    assert topo.nodes["internet"].kind is Kind.INTERNET
    assert any(e.src == GATEWAY_MAC and e.dst == "internet" for e in topo.edges)


def test_offline_device_is_kept_and_flagged(snapshot: Snapshot):
    topo = build_topology(snapshot)
    assert topo.nodes[SPARE_SWITCH_MAC].offline is True
    assert topo.nodes[SWITCH_MAC].offline is False


def test_clients_attach_to_their_switch_port_and_ap(snapshot: Snapshot):
    topo = build_topology(snapshot)
    edges = {(e.src, e.dst): e for e in topo.edges}

    wired = edges[("dd:ee:ff:00:00:01", SWITCH_MAC)]
    assert wired.label == "port 12"
    assert wired.wireless is False

    wireless = edges[("dd:ee:ff:00:00:03", AP_MAC)]
    assert wireless.wireless is True


def test_client_networks_resolve_via_network_id(snapshot: Snapshot):
    topo = build_topology(snapshot)
    nas = topo.nodes["dd:ee:ff:00:00:01"]
    assert nas.network == "servers"
    assert nas.vlan == 2


def test_nameless_client_falls_back_to_oui(snapshot: Snapshot):
    topo = build_topology(snapshot)
    assert topo.nodes["dd:ee:ff:00:00:04"].label == "Espressif 000004"


def test_long_vendor_labels_are_shortened(devices: dict, clients: dict, networkconf: dict):
    clients["data"].append(
        {
            "mac": "dd:ee:ff:00:00:aa",
            "oui": "Motorola (Wuhan) Mobility Technologies Communication Co., Ltd.",
            "is_wired": False,
            "ap_mac": AP_MAC,
            "network_id": "net1",
        }
    )
    topo = build_topology(
        Snapshot(payloads={"device": devices, "client_active": clients, "networkconf": networkconf})
    )
    label = topo.nodes["dd:ee:ff:00:00:aa"].label
    # Must stay short enough not to distort layout, and keep the MAC tail.
    assert len(label) <= 32, label
    assert label.endswith("0000AA")


def test_shortening_leaves_reasonable_names_untouched(
    devices: dict, clients: dict, networkconf: dict
):
    clients["data"].append(
        {
            "mac": "dd:ee:ff:00:00:bb",
            "hostname": "living-room-tv",
            "is_wired": False,
            "ap_mac": AP_MAC,
            "network_id": "net1",
        }
    )
    topo = build_topology(
        Snapshot(payloads={"device": devices, "client_active": clients, "networkconf": networkconf})
    )
    assert topo.nodes["dd:ee:ff:00:00:bb"].label == "living-room-tv"


def test_no_clients_flag_excludes_clients(snapshot: Snapshot):
    topo = build_topology(snapshot, include_clients=False)
    kinds = {n.kind for n in topo.nodes.values()}
    assert Kind.WIRED_CLIENT not in kinds
    assert Kind.WIRELESS_CLIENT not in kinds
    assert Kind.SWITCH in kinds


def test_filter_by_network_keeps_all_infrastructure(snapshot: Snapshot):
    topo = build_topology(snapshot)
    view = filter_by_network(topo, "servers")

    # Infrastructure is retained so each slice stays anchored to one skeleton.
    assert SWITCH_MAC in view.nodes
    assert AP_MAC in view.nodes
    assert "dd:ee:ff:00:00:01" in view.nodes
    # Clients on other networks are dropped.
    assert "dd:ee:ff:00:00:03" not in view.nodes


def test_filter_drops_edges_with_missing_endpoints(snapshot: Snapshot):
    view = filter_by_network(build_topology(snapshot), "servers")
    for edge in view.edges:
        assert edge.src in view.nodes
        assert edge.dst in view.nodes


def test_client_without_reported_uplink_is_anchored_not_orphaned(
    devices: dict, clients: dict, networkconf: dict
):
    # A VM behind another host: the controller reports neither sw_mac nor ap_mac.
    clients["data"].append(
        {
            "mac": "dd:ee:ff:00:00:99",
            "hostname": "runner",
            "is_wired": True,
            "ip": "10.0.20.12",
            "network_id": "net1",
        }
    )
    topo = build_topology(
        Snapshot(payloads={"device": devices, "client_active": clients, "networkconf": networkconf})
    )

    assert UNKNOWN_UPLINK_ID in topo.nodes
    linked = {e.src for e in topo.edges} | {e.dst for e in topo.edges}
    assert "dd:ee:ff:00:00:99" in linked, "orphan must be anchored, not left floating"
    assert any(e.src == "dd:ee:ff:00:00:99" and e.dst == UNKNOWN_UPLINK_ID for e in topo.edges)


def test_unknown_uplink_placeholder_is_absent_when_every_client_resolves(snapshot: Snapshot):
    # No placeholder should appear just because the code can create one.
    assert UNKNOWN_UPLINK_ID not in build_topology(snapshot).nodes


def test_unknown_uplink_survives_per_network_filtering(
    devices: dict, clients: dict, networkconf: dict
):
    clients["data"].append(
        {
            "mac": "dd:ee:ff:00:00:99",
            "hostname": "runner",
            "is_wired": True,
            "ip": "10.0.20.12",
            "network_id": "net1",
        }
    )
    topo = build_topology(
        Snapshot(payloads={"device": devices, "client_active": clients, "networkconf": networkconf})
    )
    view = filter_by_network(topo, "lan")
    assert UNKNOWN_UPLINK_ID in view.nodes
    linked = {e.src for e in view.edges} | {e.dst for e in view.edges}
    assert "dd:ee:ff:00:00:99" in linked


def test_client_networks_lists_only_networks_with_clients(snapshot: Snapshot):
    topo = build_topology(snapshot)
    assert client_networks(topo) == ["iot", "lan", "servers"]


class TestShowOffline:
    def test_offline_devices_are_kept_by_default_at_the_api_level(self, snapshot: Snapshot):
        topo = build_topology(snapshot)
        assert SPARE_SWITCH_MAC in topo.nodes
        assert topo.nodes[SPARE_SWITCH_MAC].offline is True

    def test_excluding_offline_drops_the_node_entirely(self, snapshot: Snapshot):
        topo = build_topology(snapshot, include_offline=False)
        assert SPARE_SWITCH_MAC not in topo.nodes
        assert not any(n.offline for n in topo.nodes.values())
        # Connected hardware is untouched.
        assert SWITCH_MAC in topo.nodes

    def test_excluding_offline_leaves_no_dangling_edges(self, snapshot: Snapshot):
        # Regression: the uplink pass used to index topo.nodes for every device
        # in the payload, including ones it had just skipped, and raised KeyError.
        topo = build_topology(snapshot, include_offline=False)
        for edge in topo.edges:
            assert edge.src in topo.nodes
            assert edge.dst in topo.nodes

    def test_an_offline_device_with_an_uplink_is_skipped_cleanly(
        self, devices: dict, networkconf: dict
    ):
        # The spare switch in the fixture has no uplink; give one an uplink too,
        # so the skip path is exercised with an edge that must not be created.
        devices["data"].append(
            {
                "mac": "aa:bb:cc:00:00:09",
                "name": "Retired AP",
                "type": "uap",
                "state": 0,
                "uplink": {"uplink_mac": SWITCH_MAC, "uplink_remote_port": 22, "type": "wire"},
            }
        )
        topo = build_topology(
            Snapshot(payloads={"device": devices, "networkconf": networkconf}),
            include_offline=False,
        )
        assert "aa:bb:cc:00:00:09" not in topo.nodes
        assert not any(e.src == "aa:bb:cc:00:00:09" for e in topo.edges)

    def test_clients_on_an_excluded_switch_are_anchored_not_dropped(self, snapshot: Snapshot):
        # A client whose switch vanished still exists on the network, so it must
        # stay on the map rather than silently disappear with the switch.
        topo = build_topology(snapshot, include_offline=False)
        assert "dd:ee:ff:00:00:01" in topo.nodes


class TestClientFingerprints:
    def _snapshot(self, devices, clients, networkconf, fingerprint):
        return Snapshot(
            payloads={
                "device": devices,
                "client_active": clients,
                "networkconf": networkconf,
                "fingerprint": fingerprint,
            }
        )

    def test_glyph_name_mirrors_the_unifi_ui_classes(self, snapshot: Snapshot):
        topo = build_topology(snapshot)
        # Wired non-guest client.
        assert topo.nodes["dd:ee:ff:00:00:01"].glyph_name == "user-wired"
        # Wireless non-guest client.
        assert topo.nodes["dd:ee:ff:00:00:03"].glyph_name == "user-wireless"
        # Infrastructure has no client glyph.
        assert topo.nodes[SWITCH_MAC].glyph_name is None

    def test_guest_clients_get_the_guest_glyph(
        self, devices: dict, clients: dict, networkconf: dict
    ):
        clients["data"].append(
            {
                "mac": "dd:ee:ff:00:00:77",
                "hostname": "visitor",
                "is_wired": False,
                "is_guest": True,
                "ap_mac": AP_MAC,
                "network_id": "net1",
            }
        )
        topo = build_topology(self._snapshot(devices, clients, networkconf, {}))
        assert topo.nodes["dd:ee:ff:00:00:77"].glyph_name == "guest-wireless"

    def test_fingerprint_names_an_otherwise_unnamed_client(
        self, devices: dict, clients: dict, networkconf: dict
    ):
        fingerprint = {
            "dev_ids": {"4425": {"name": "Nest Audio", "family_id": "1", "dev_type_id": "2"}},
            "family_ids": {"1": "Multimedia Device"},
            "dev_type_ids": {"2": "Soundbar"},
        }
        clients["data"].append(
            {
                "mac": "dd:ee:ff:00:00:88",
                "oui": "Google",
                "is_wired": False,
                "ap_mac": AP_MAC,
                "network_id": "net1",
                "dev_id": 4425,
            }
        )
        topo = build_topology(self._snapshot(devices, clients, networkconf, fingerprint))
        node = topo.nodes["dd:ee:ff:00:00:88"]
        assert node.label == "Nest Audio"
        assert node.detail == "Soundbar"
        assert node.dev_id == 4425

    def test_a_user_assigned_name_beats_the_fingerprint_name(
        self, devices: dict, clients: dict, networkconf: dict
    ):
        fingerprint = {"dev_ids": {"4425": {"name": "Nest Audio"}}}
        clients["data"].append(
            {
                "mac": "dd:ee:ff:00:00:89",
                "name": "kitchen speaker",
                "is_wired": False,
                "ap_mac": AP_MAC,
                "network_id": "net1",
                "dev_id": 4425,
            }
        )
        topo = build_topology(self._snapshot(devices, clients, networkconf, fingerprint))
        assert topo.nodes["dd:ee:ff:00:00:89"].label == "kitchen speaker"

    def test_dev_id_override_wins_over_dev_id(
        self, devices: dict, clients: dict, networkconf: dict
    ):
        # The override is the user's correction in the UI for a wrong fingerprint.
        fingerprint = {"dev_ids": {"111": {"name": "Wrong"}, "222": {"name": "Right"}}}
        clients["data"].append(
            {
                "mac": "dd:ee:ff:00:00:90",
                "is_wired": True,
                "sw_mac": SWITCH_MAC,
                "sw_port": 4,
                "network_id": "net1",
                "dev_id": 111,
                "dev_id_override": 222,
            }
        )
        topo = build_topology(self._snapshot(devices, clients, networkconf, fingerprint))
        node = topo.nodes["dd:ee:ff:00:00:90"]
        assert node.dev_id == 222
        assert node.label == "Right"

    def test_missing_fingerprint_payload_is_harmless(self, snapshot: Snapshot):
        topo = build_topology(snapshot)
        assert topo.nodes["dd:ee:ff:00:00:01"].dev_id is None

    def test_malformed_fingerprint_records_and_tables_are_ignored(self):
        snapshot = Snapshot(
            payloads={
                "fingerprint": {
                    "dev_ids": {
                        "42": {
                            "name": " ",
                            "family_id": "1",
                            "dev_type_id": "2",
                            "vendor_id": "3",
                        },
                        "bad-id": {"name": "Ignored"},
                        "43": "not a record",
                        "44": {"name": " Known Device "},
                    },
                    "family_ids": {"1": " Device Family "},
                    "dev_type_ids": ["not", "a", "mapping"],
                    "vendor_ids": {"3": 99},
                }
            }
        )

        assert build_fingerprints(snapshot) == {
            42: {"family": "Device Family"},
            44: {"name": "Known Device"},
        }


class TestWanInfo:
    def test_isp_name_labels_the_internet_node(self, devices: dict, networkconf: dict):
        health = {
            "data": [
                {"subsystem": "wlan", "status": "ok"},
                {"subsystem": "wan", "isp_name": "Example ISP", "wan_ip": "203.0.113.10"},
            ]
        }
        topo = build_topology(
            Snapshot(payloads={"device": devices, "networkconf": networkconf, "health": health})
        )
        node = topo.nodes["internet"]
        assert node.label == "Example ISP"
        assert node.ip == "203.0.113.10"

    def test_the_asn_reaches_the_internet_node(self, devices: dict, networkconf: dict):
        # It is the whole of the ISP brand-mark lookup, so losing it here would
        # silently disable provider logos with nothing to show why.
        health = {"data": [{"subsystem": "wan", "isp_name": "Example ISP", "asn": 64500}]}
        topo = build_topology(
            Snapshot(payloads={"device": devices, "networkconf": networkconf, "health": health})
        )
        assert topo.nodes["internet"].asn == 64500

    def test_a_missing_asn_is_none_not_zero(self, devices: dict, networkconf: dict):
        # 0 looks like a valid ASN and would send us fetching something absent.
        health = {"data": [{"subsystem": "wan", "isp_name": "Example ISP"}]}
        topo = build_topology(
            Snapshot(payloads={"device": devices, "networkconf": networkconf, "health": health})
        )
        assert topo.nodes["internet"].asn is None

    def test_a_non_numeric_asn_is_ignored(self, devices: dict, networkconf: dict):
        health = {"data": [{"subsystem": "wan", "isp_name": "X", "asn": "not-a-number"}]}
        topo = build_topology(
            Snapshot(payloads={"device": devices, "networkconf": networkconf, "health": health})
        )
        assert topo.nodes["internet"].asn is None

    def test_falls_back_to_isp_organization(self, devices: dict, networkconf: dict):
        health = {"data": [{"subsystem": "wan", "isp_organization": "Example ISP, Inc."}]}
        topo = build_topology(
            Snapshot(payloads={"device": devices, "networkconf": networkconf, "health": health})
        )
        assert topo.nodes["internet"].label == "Example ISP, Inc."

    def test_no_health_payload_keeps_the_generic_label(self, snapshot: Snapshot):
        assert build_topology(snapshot).nodes["internet"].label == "Internet"

    def test_wan_subsystem_absent_keeps_the_generic_label(self, devices: dict, networkconf: dict):
        health = {"data": [{"subsystem": "wlan", "status": "ok"}]}
        topo = build_topology(
            Snapshot(payloads={"device": devices, "networkconf": networkconf, "health": health})
        )
        assert topo.nodes["internet"].label == "Internet"


class TestProtectCameras:
    def test_unpunctuated_protect_macs_are_normalised(self):
        from unifi_map.model import protect_camera_macs

        snap = Snapshot(payloads={"protect_cameras": [{"mac": "02AABB0B5F76", "name": "G3 Flex"}]})
        assert protect_camera_macs(snap) == {"02:aa:bb:0b:5f:76"}

    def test_wrapped_and_missing_payloads_are_tolerated(self):
        from unifi_map.model import protect_camera_macs

        assert protect_camera_macs(Snapshot(payloads={})) == set()
        assert protect_camera_macs(Snapshot(payloads={"protect_cameras": None})) == set()
        # Malformed MACs are skipped rather than producing junk keys.
        assert (
            protect_camera_macs(Snapshot(payloads={"protect_cameras": [{"mac": "nope"}]})) == set()
        )
        wrapped = Snapshot(payloads={"protect_cameras": {"data": [{"mac": "02AABB0B5F76"}]}})
        assert wrapped.get("protect_cameras") is not None
        assert protect_camera_macs(wrapped) == {"02:aa:bb:0b:5f:76"}

    def test_a_protect_camera_client_is_flagged(
        self, devices: dict, clients: dict, networkconf: dict
    ):
        clients["data"].append(
            {
                "mac": "02:aa:bb:0b:5f:76",
                "hostname": "g3-flex",
                "oui": "Ubiquiti Inc",
                "is_wired": True,
                "sw_mac": SWITCH_MAC,
                "sw_port": 7,
                "network_id": "net1",
            }
        )
        topo = build_topology(
            Snapshot(
                payloads={
                    "device": devices,
                    "client_active": clients,
                    "networkconf": networkconf,
                    "protect_cameras": [{"mac": "02AABB0B5F76"}],
                }
            )
        )
        node = topo.nodes["02:aa:bb:0b:5f:76"]
        assert node.hardware_type == "camera"
        assert node.oui == "Ubiquiti Inc"
        # No fingerprint, so artwork has to come from the hardware catalog.
        assert node.dev_id is None

    def test_a_non_protect_client_is_not_flagged(self, snapshot: Snapshot):
        assert topo_camera_types(build_topology(snapshot)) == set()


def topo_camera_types(topo):
    return {n.hardware_type for n in topo.nodes.values() if n.hardware_type}


class TestControllerGraphPlacement:
    """stat/sta only reports an uplink when it is a UniFi device, so anything
    behind a non-UniFi box needs the controller's own topology graph."""

    def _snapshot(self, devices, clients, networkconf, topology=None):
        payloads = {"device": devices, "client_active": clients, "networkconf": networkconf}
        if topology is not None:
            payloads["topology"] = topology
        return Snapshot(payloads=payloads)

    def test_a_client_behind_another_client_is_placed(
        self, devices: dict, clients: dict, networkconf: dict
    ):
        # A NAS on a switch port, with a VM behind it. The VM has no sw_mac.
        clients["data"].append(
            {
                "mac": "dd:ee:ff:00:00:a1",
                "hostname": "nas-host",
                "is_wired": True,
                "sw_mac": SWITCH_MAC,
                "sw_port": 5,
                "network_id": "net1",
            }
        )
        clients["data"].append(
            {"mac": "dd:ee:ff:00:00:a2", "hostname": "vm", "is_wired": True, "network_id": "net1"}
        )
        topology = {
            "edges": [
                {
                    "downlinkMac": "DD:EE:FF:00:00:A2",
                    "uplinkMac": "dd:ee:ff:00:00:a1",
                    "type": "WIRED",
                }
            ]
        }
        topo = build_topology(self._snapshot(devices, clients, networkconf, topology))
        parents = [e.dst for e in topo.edges if e.src == "dd:ee:ff:00:00:a2"]
        assert parents == ["dd:ee:ff:00:00:a1"]
        # Nothing is unplaced, so the placeholder never appears.
        assert UNKNOWN_UPLINK_ID not in topo.nodes

    def test_the_graph_marks_a_wireless_uplink(
        self, devices: dict, clients: dict, networkconf: dict
    ):
        clients["data"].append(
            {
                "mac": "dd:ee:ff:00:00:b1",
                "hostname": "roamer",
                "is_wired": False,
                "network_id": "net1",
            }
        )
        topology = {
            "edges": [{"downlinkMac": "dd:ee:ff:00:00:b1", "uplinkMac": AP_MAC, "type": "WIRELESS"}]
        }
        topo = build_topology(self._snapshot(devices, clients, networkconf, topology))
        edge = next(e for e in topo.edges if e.src == "dd:ee:ff:00:00:b1")
        assert edge.wireless is True

    def test_an_uplink_naming_an_unknown_node_still_falls_back(
        self, devices: dict, clients: dict, networkconf: dict
    ):
        clients["data"].append(
            {
                "mac": "dd:ee:ff:00:00:c1",
                "hostname": "orphan",
                "is_wired": True,
                "network_id": "net1",
            }
        )
        topology = {
            "edges": [{"downlinkMac": "dd:ee:ff:00:00:c1", "uplinkMac": "99:99:99:99:99:99"}]
        }
        topo = build_topology(self._snapshot(devices, clients, networkconf, topology))
        assert any(e.src == "dd:ee:ff:00:00:c1" and e.dst == UNKNOWN_UPLINK_ID for e in topo.edges)

    def test_no_topology_payload_still_works(self, devices: dict, clients: dict, networkconf: dict):
        clients["data"].append(
            {"mac": "dd:ee:ff:00:00:d1", "hostname": "vm", "is_wired": True, "network_id": "net1"}
        )
        topo = build_topology(self._snapshot(devices, clients, networkconf))
        assert UNKNOWN_UPLINK_ID in topo.nodes

    @pytest.mark.parametrize(
        "payload", [None, "nonsense", {}, {"edges": "no"}, {"edges": [1, 2]}, {"edges": [{}]}]
    )
    def test_a_malformed_graph_yields_nothing_rather_than_raising(self, payload):
        from unifi_map.model import topology_uplinks

        assert topology_uplinks(Snapshot(payloads={"topology": payload})) == {}

    def test_a_self_referential_edge_is_ignored(self):
        from unifi_map.model import topology_uplinks

        snap = Snapshot(
            payloads={"topology": {"edges": [{"downlinkMac": "aa:bb", "uplinkMac": "aa:bb"}]}}
        )
        assert topology_uplinks(snap) == {}


class TestProvenance:
    """Every node and edge must say where it came from.

    The point of these is the first one: `UNSPECIFIED` is the default, so a new
    node- or edge-building path that forgets to name a source is caught here
    rather than quietly reporting itself as synthetic. Mutation-tested by
    dropping `provenance=` from each construction site in `model.py` in turn and
    confirming this goes red.
    """

    def test_build_topology_never_leaves_a_node_unspecified(self, snapshot: Snapshot):
        topo = build_topology(snapshot)
        unspecified = [n.id for n in topo.nodes.values() if n.provenance is Provenance.UNSPECIFIED]
        assert unspecified == []

    def test_build_topology_never_leaves_an_edge_unspecified(self, snapshot: Snapshot):
        topo = build_topology(snapshot)
        unspecified = [(e.src, e.dst) for e in topo.edges if e.provenance is Provenance.UNSPECIFIED]
        assert unspecified == []

    def test_devices_and_clients_are_distinguishable(self, snapshot: Snapshot):
        topo = build_topology(snapshot)
        by_source: dict[Provenance, set[Kind]] = {}
        for node in topo.nodes.values():
            by_source.setdefault(node.provenance, set()).add(node.kind)

        # A device never reports itself as a client and vice versa, which is the
        # distinction the report is built on.
        assert Kind.WIRED_CLIENT not in by_source.get(Provenance.DEVICE, set())
        assert Kind.WIRELESS_CLIENT not in by_source.get(Provenance.DEVICE, set())
        assert by_source[Provenance.CLIENT] <= {Kind.WIRED_CLIENT, Kind.WIRELESS_CLIENT}

    def test_the_internet_node_is_synthetic_not_a_device(self, snapshot: Snapshot):
        topo = build_topology(snapshot)
        assert topo.nodes["internet"].provenance is Provenance.SYNTHETIC
        # It is ours, so it must never be counted as something the controller
        # inventoried; that would overstate the device count by one on every map.
        assert topo.nodes["internet"].provenance is not Provenance.DEVICE

    def test_a_client_placed_from_stat_sta_says_so(self, snapshot: Snapshot):
        topo = build_topology(snapshot)
        client_edges = [
            e
            for e in topo.edges
            if topo.nodes[e.src].kind in (Kind.WIRED_CLIENT, Kind.WIRELESS_CLIENT)
        ]
        assert client_edges
        assert any(e.provenance is Provenance.CLIENT_UPLINK for e in client_edges)

    def test_an_unplaceable_client_edge_is_marked_unplaced(
        self, devices: dict, clients: dict, networkconf: dict
    ):
        clients["data"].append({"mac": "dd:ee:ff:00:00:e1", "hostname": "orphan", "is_wired": True})
        snap = Snapshot(
            payloads={"device": devices, "client_active": clients, "networkconf": networkconf}
        )
        topo = build_topology(snap)
        placeholder = [e for e in topo.edges if e.dst == UNKNOWN_UPLINK_ID]
        assert placeholder
        assert all(e.provenance is Provenance.UNPLACED for e in placeholder)

    def test_a_client_placed_from_the_controller_graph_says_so(
        self, devices: dict, clients: dict, networkconf: dict
    ):
        """The two placement routes must be distinguishable, which is the point.

        A NAS reported by `stat/sta` and a VM behind it that only the v2 topology
        graph knows about are drawn identically today. This is the assertion that
        makes `--report` able to say which is which, and it was written after a
        mutation test showed `TOPOLOGY_GRAPH` could be deleted outright with the
        whole suite still green.
        """
        clients["data"].append(
            {
                "mac": "dd:ee:ff:00:00:a1",
                "hostname": "nas-host",
                "is_wired": True,
                "sw_mac": SWITCH_MAC,
                "sw_port": 5,
                "network_id": "net1",
            }
        )
        clients["data"].append(
            {"mac": "dd:ee:ff:00:00:a2", "hostname": "vm", "is_wired": True, "network_id": "net1"}
        )
        snap = Snapshot(
            payloads={
                "device": devices,
                "client_active": clients,
                "networkconf": networkconf,
                "topology": {
                    "edges": [
                        {
                            "downlinkMac": "DD:EE:FF:00:00:A2",
                            "uplinkMac": "dd:ee:ff:00:00:a1",
                            "type": "WIRED",
                        }
                    ]
                },
            }
        )
        topo = build_topology(snap)
        by_src = {e.src: e for e in topo.edges}

        assert by_src["dd:ee:ff:00:00:a2"].provenance is Provenance.TOPOLOGY_GRAPH
        # The host beside it came from stat/sta, so the two must not collapse
        # onto one value: a report that called both "reported by the controller"
        # would be true and useless.
        assert by_src["dd:ee:ff:00:00:a1"].provenance is Provenance.CLIENT_UPLINK

    def test_asserted_and_provenance_never_disagree(self, snapshot: Snapshot, tmp_path):
        """Two fields describing one fact, so pin that they agree.

        `asserted` drives the dotted rendering and `provenance` is the record.
        Nothing stops a future override path from setting one and not the other,
        and the failure would be silent: a link drawn as observed while the
        report calls it an assertion, or the reverse.
        """
        from unifi_map.overrides import apply, load

        path = tmp_path / "o.toml"
        path.write_text(
            '[[device]]\nname = "Unmanaged Switch"\nkind = "switch"\n\n'
            f'[[link]]\nfrom = "Unmanaged Switch"\nto = "{GATEWAY_MAC}"\n',
            encoding="utf-8",
        )
        topo = apply(build_topology(snapshot), load(path), tmp_path).topology

        for node in topo.nodes.values():
            assert node.asserted == (node.provenance is Provenance.OVERRIDE), node.id
        for edge in topo.edges:
            assert edge.asserted == (edge.provenance is Provenance.OVERRIDE), (edge.src, edge.dst)


class TestSharedPorts:
    """KAN-199: several wired clients on one switch port hint at a hidden switch."""

    def _topo(self):
        topo = Topology()
        topo.add(Node(id="sw", label="switch", kind=Kind.SWITCH))
        topo.add(Node(id="c1", label="c1", kind=Kind.WIRED_CLIENT))
        topo.add(Node(id="c2", label="c2", kind=Kind.WIRED_CLIENT))
        topo.edges.append(
            Edge(src="c1", dst="sw", label="port 7", provenance=Provenance.CLIENT_UPLINK)
        )
        topo.edges.append(
            Edge(src="c2", dst="sw", label="port 7", provenance=Provenance.CLIENT_UPLINK)
        )
        return topo

    def test_two_clients_on_one_port_are_grouped(self):
        topo = self._topo()
        groups = topo.shared_ports()
        assert groups == {("sw", "port 7"): ["c1", "c2"]}

    def test_a_single_client_on_a_port_is_not_flagged(self):
        topo = self._topo()
        topo.edges.pop()
        assert topo.shared_ports() == {}

    def test_different_ports_are_not_grouped_together(self):
        topo = self._topo()
        topo.edges[-1].label = "port 8"
        assert topo.shared_ports() == {}

    def test_a_topology_graph_inferred_edge_does_not_count(self):
        """An inferred uplink is a step removed from what the port itself said."""
        topo = self._topo()
        topo.edges[-1].provenance = Provenance.TOPOLOGY_GRAPH
        assert topo.shared_ports() == {}

    def test_a_wireless_edge_does_not_count(self):
        topo = self._topo()
        topo.edges[-1].wireless = True
        assert topo.shared_ports() == {}

    def test_an_override_that_reparents_a_client_resolves_the_sharing(self):
        """Once `[[hosted]]` moves a client off the shared port, it's explained."""
        topo = self._topo()
        topo.edges[-1] = Edge(src="c2", dst="c1", provenance=Provenance.OVERRIDE, asserted=True)
        assert topo.shared_ports() == {}
