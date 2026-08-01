"""Reading a UniFi support file.

Everything here builds its own archive in a temp directory. No real support
file is involved: they are enormous, they are a complete inventory of somebody's
house, and one must never end up in this repository.

The archive built by `support_archive` mirrors the real layout, including the
`support-<id>/` top-level directory that member matching has to see past, and a
decoy log file that must be skipped.
"""

from __future__ import annotations

import io
import json
import tarfile
from typing import ClassVar

import pytest

from unifi_map.model import UNKNOWN_UPLINK_ID, Kind, build_topology
from unifi_map.support import SupportFileError, load_support_file

GATEWAY = "aa:bb:cc:00:00:01"
SWITCH = "aa:bb:cc:00:00:02"
AP = "aa:bb:cc:00:00:03"
WIRED_CLIENT = "dd:ee:ff:00:00:10"
WIFI_CLIENT = "dd:ee:ff:00:00:11"
STATIC_CLIENT = "dd:ee:ff:00:00:12"
NESTED_CLIENT = "dd:ee:ff:00:00:13"

ROOT = "support-TEST-1234567890"


def _devices() -> list:
    return [
        {
            "default": [
                {
                    "mac": GATEWAY,
                    "type": "udm",
                    "model": "UDMPROMAX",
                    "sysid": 59954,
                    "name": "gateway",
                    "state": 1,
                    "ip": "10.0.0.1",
                    "network_table": [
                        {
                            "_id": "net1",
                            "name": "lan",
                            "vlan": None,
                            "ip_subnet": "10.0.0.1/24",
                            "is_guest": False,
                            "purpose": "corporate",
                            "enabled": True,
                        },
                        {
                            "_id": "net100",
                            "name": "guest",
                            "vlan": 100,
                            "ip_subnet": "10.0.100.1/24",
                            "is_guest": True,
                            "purpose": "guest",
                            "enabled": True,
                        },
                    ],
                },
                {
                    "mac": SWITCH,
                    "type": "usw",
                    "model": "USL8LP",
                    "sysid": 60714,
                    "name": "switch",
                    "state": 1,
                    "ip": "10.0.0.2",
                    "uplink": {"uplink_mac": GATEWAY, "uplink_remote_port": 1},
                },
                {
                    "mac": AP,
                    "type": "uap",
                    "model": "U7PRO",
                    "sysid": 42626,
                    "name": "ap",
                    "state": 1,
                    "ip": "10.0.0.3",
                    "uplink": {"uplink_mac": SWITCH, "uplink_remote_port": 5},
                },
            ]
        },
        {"super": []},
    ]


def _topology() -> dict:
    return {
        "default": {
            "has_unknown_switch": False,
            "vertices": [
                {"mac": GATEWAY, "type": "DEVICE", "model": "UDMPROMAX", "name": "gateway"},
                {"mac": SWITCH, "type": "DEVICE", "model": "USL8LP", "name": "switch"},
                {"mac": AP, "type": "DEVICE", "model": "U7PRO", "name": "ap"},
                {"mac": WIRED_CLIENT, "type": "CLIENT", "name": "nas", "unifiDevice": False},
                {"mac": WIFI_CLIENT, "type": "CLIENT", "name": "phone", "unifiDevice": False},
                {"mac": STATIC_CLIENT, "type": "CLIENT", "name": "printer", "unifiDevice": False},
                {"mac": NESTED_CLIENT, "type": "CLIENT", "name": "vm", "unifiDevice": False},
            ],
            "edges": [
                {
                    "downlinkMac": SWITCH,
                    "uplinkMac": GATEWAY,
                    "type": "WIRED",
                    "downlinkPortNumber": 1,
                    "uplinkPortNumber": 1,
                    "networkId": "net1",
                },
                {
                    "downlinkMac": AP,
                    "uplinkMac": SWITCH,
                    "type": "WIRED",
                    "downlinkPortNumber": 1,
                    "uplinkPortNumber": 5,
                    "networkId": "net1",
                },
                {
                    "downlinkMac": WIRED_CLIENT,
                    "uplinkMac": SWITCH,
                    "type": "WIRED",
                    "uplinkPortNumber": 7,
                    "networkId": "net1",
                },
                {
                    "downlinkMac": WIFI_CLIENT,
                    "uplinkMac": AP,
                    "type": "WIRELESS",
                    "essid": "test-wifi",
                    "radioBand": "na",
                    "networkId": "net100",
                },
                {
                    "downlinkMac": STATIC_CLIENT,
                    "uplinkMac": SWITCH,
                    "type": "WIRED",
                    "uplinkPortNumber": 8,
                    "networkId": "net1",
                },
                # A client behind another client: the case stat/sta cannot see.
                {
                    "downlinkMac": NESTED_CLIENT,
                    "uplinkMac": WIRED_CLIENT,
                    "type": "WIRED",
                    "uplinkPortNumber": 7,
                    "networkId": "net1",
                },
            ],
        }
    }


def _infrastructure() -> dict:
    return {
        "default": {
            "gatewayMac": GATEWAY,
            "wanMode": "FAILOVER_ONLY",
            "ispData": [
                {
                    "id": "WAN",
                    "name": "Carls Discount Internet",
                    "asn": 64500,
                    "wanIp": "198.51.100.42",
                    "priority": 1,
                    "isActive": True,
                },
                {
                    "id": "WAN2",
                    "name": "Cruelty Cable Co",
                    "asn": 64501,
                    "wanIp": "198.51.100.99",
                    "priority": 2,
                    "isActive": False,
                },
            ],
        }
    }


LEASES = "\n".join(
    [
        f"1785501981 {WIRED_CLIENT} 10.0.0.50 nas 01:aa:bb",
        f"1785457314 {WIFI_CLIENT} 10.0.100.20 phone-dhcp *",
        # A lease whose hostname the client never sent.
        f"1785520082 {NESTED_CLIENT} 10.0.0.51 * *",
    ]
)

# The printer has a static address, so it appears only here.
NEIGHBOURS = "\n".join(
    [
        f"10.0.0.60 dev br0 lladdr {STATIC_CLIENT} ref 30 used 0/0/0 probes 4 REACHABLE",
        "10.0.0.99 dev br0 lladdr aa:aa:aa:aa:aa:aa ref 1 used 0/0/0 probes 6 FAILED",
    ]
)


def _write_archive(path, members: dict[str, bytes]) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for name, payload in members.items():
            info = tarfile.TarInfo(f"{ROOT}/{name}")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))


def _default_members() -> dict[str, bytes]:
    return {
        "unifi/devices.json": json.dumps(_devices()).encode(),
        "unifi/topology.json": json.dumps(_topology()).encode(),
        "unifi/infrastructure.json": json.dumps(_infrastructure()).encode(),
        "system/run/dnsmasq.lease": LEASES.encode(),
        "system/network/ip-neigh": NEIGHBOURS.encode(),
        # Must be ignored. A real archive is mostly this sort of thing.
        "unifi/logs/server.log": b"x" * 4096,
        "system/security/ips/config/config.json": b'{"irrelevant": true}',
    }


@pytest.fixture
def support_archive(tmp_path):
    path = tmp_path / "support-TEST.tgz"
    _write_archive(path, _default_members())
    return path


class TestSnapshotShape:
    def test_it_produces_the_same_payload_keys_as_a_live_fetch(self, support_archive):
        snapshot = load_support_file(support_archive)
        assert set(snapshot.payloads) == {
            "device",
            "client_active",
            "networkconf",
            "health",
            "topology",
        }

    def test_the_super_pseudo_site_is_not_mistaken_for_a_site(self, support_archive):
        # It is always present and always empty; picking it maps nothing.
        assert len(load_support_file(support_archive).get("device")) == 3

    def test_devices_keep_the_sysid_that_artwork_is_matched_on(self, support_archive):
        sysids = {d["sysid"] for d in load_support_file(support_archive).get("device")}
        assert sysids == {59954, 60714, 42626}


class TestNetworks:
    def test_vlan_names_are_recovered_from_the_gateway_network_table(self, support_archive):
        networks = load_support_file(support_archive).get("networkconf")
        assert {n["name"] for n in networks} == {"lan", "guest"}
        assert {n["_id"]: n["vlan"] for n in networks} == {"net1": None, "net100": 100}

    def test_a_missing_network_table_degrades_rather_than_raising(self, tmp_path):
        members = _default_members()
        devices = _devices()
        del devices[0]["default"][0]["network_table"]
        members["unifi/devices.json"] = json.dumps(devices).encode()
        path = tmp_path / "no-networks.tgz"
        _write_archive(path, members)

        snapshot = load_support_file(path)
        assert snapshot.get("networkconf") == []
        # The map is thinner, but it is still a map.
        assert len(snapshot.get("client_active")) == 4


class TestClients:
    def test_wired_and_wireless_clients_are_split_by_edge_type(self, support_archive):
        clients = {c["mac"]: c for c in load_support_file(support_archive).get("client_active")}
        assert clients[WIRED_CLIENT]["is_wired"] is True
        assert clients[WIFI_CLIENT]["is_wired"] is False

    def test_the_switch_port_comes_from_the_uplink_side_of_the_edge(self, support_archive):
        clients = {c["mac"]: c for c in load_support_file(support_archive).get("client_active")}
        # downlinkPortNumber is the client's own interface and is absent; taking
        # it would silently drop every port label.
        assert clients[WIRED_CLIENT]["sw_port"] == 7
        assert clients[WIRED_CLIENT]["sw_mac"] == SWITCH

    def test_wireless_clients_carry_ssid_and_band(self, support_archive):
        clients = {c["mac"]: c for c in load_support_file(support_archive).get("client_active")}
        assert clients[WIFI_CLIENT]["essid"] == "test-wifi"
        assert clients[WIFI_CLIENT]["ap_mac"] == AP

    def test_addresses_come_from_dhcp_leases(self, support_archive):
        clients = {c["mac"]: c for c in load_support_file(support_archive).get("client_active")}
        assert clients[WIRED_CLIENT]["ip"] == "10.0.0.50"

    def test_a_statically_addressed_client_is_found_in_the_neighbour_table(self, support_archive):
        clients = {c["mac"]: c for c in load_support_file(support_archive).get("client_active")}
        # It never took a lease, so the lease file alone would leave it blank.
        assert clients[STATIC_CLIENT]["ip"] == "10.0.0.60"

    def test_an_unresolved_neighbour_is_not_treated_as_an_address(self, support_archive):
        clients = load_support_file(support_archive).get("client_active")
        assert all(c["ip"] != "10.0.0.99" for c in clients)

    def test_a_client_with_no_address_anywhere_is_still_on_the_map(self, tmp_path):
        """Losing an address must never mean losing the device.

        Addresses come from the lease file, then the neighbour table, then DPI.
        Clients come from somewhere else entirely: the topology graph's CLIENT
        vertices. So a statically addressed device that has also aged out of ARP
        keeps its node, its parent and its port, and loses only the line of
        label that would have carried an address.

        Worth pinning down because the natural refactor, building clients from
        whichever source has addresses, would silently drop exactly the devices
        most likely to be infrastructure: printers, NASes, anything given a
        static address precisely because it matters.
        """
        members = _default_members()
        # Strip every address source. The clients themselves are untouched.
        members["system/run/dnsmasq.lease"] = b""
        members["system/network/ip-neigh"] = b""
        path = tmp_path / "no-addresses.tgz"
        _write_archive(path, members)

        topo = build_topology(load_support_file(path))
        for mac in (WIRED_CLIENT, WIFI_CLIENT, STATIC_CLIENT, NESTED_CLIENT):
            assert mac in topo.nodes, f"{mac} vanished with its address"
            assert topo.nodes[mac].ip is None

        # Placement is unaffected: still parented, still labelled with the port.
        parents = {e.src: e.dst for e in topo.edges}
        assert parents[STATIC_CLIENT] == SWITCH
        assert parents[NESTED_CLIENT] == WIRED_CLIENT
        assert {e.src: e.label for e in topo.edges}[STATIC_CLIENT] == "port 8"

    def test_a_guest_network_marks_its_clients(self, support_archive):
        clients = {c["mac"]: c for c in load_support_file(support_archive).get("client_active")}
        assert clients[WIFI_CLIENT]["is_guest"] is True
        assert clients[WIRED_CLIENT]["is_guest"] is False

    def test_an_absent_dhcp_hostname_does_not_become_a_literal_asterisk(self, support_archive):
        clients = {c["mac"]: c for c in load_support_file(support_archive).get("client_active")}
        assert clients[NESTED_CLIENT]["hostname"] is None


class TestHealth:
    def test_the_active_wan_names_the_isp(self, support_archive):
        health = load_support_file(support_archive).get("health")
        assert health[0]["isp_name"] == "Carls Discount Internet"
        assert health[0]["wan_ip"] == "198.51.100.42"

    def test_the_asn_is_carried_through(self, support_archive):
        # Unused by the renderer today, but it is the key an ISP logo lookup
        # would need and discarding it here would hide that it is available.
        assert load_support_file(support_archive).get("health")[0]["asn"] == 64500


class TestDpiFingerprints:
    """`system/network/dpi-util-fprint-stats`, the gateway's DPI table.

    It carries an address, a hostname and an ML fingerprint guess per host. The
    address is an observation; the fingerprint is an inference that disagreed
    with the controller's settled `dev_id` on three of seven hosts when checked,
    always at low confidence. So the two are trusted differently.
    """

    def _archive(self, tmp_path, hosts, name="dpi.tgz"):
        members = _default_members()
        members["system/network/dpi-util-fprint-stats"] = (
            # A `Response:` preamble makes the file not-quite-JSON.
            "Response:\n" + json.dumps({"hosts": hosts})
        ).encode()
        path = tmp_path / name
        _write_archive(path, members)
        return path

    def test_a_confident_fingerprint_is_used(self, tmp_path):
        path = self._archive(
            tmp_path,
            [
                {
                    "mac": WIFI_CLIENT,
                    "ip": "10.0.100.20",
                    "ml": {"deviceNameID": 4680, "confidence": 94},
                }
            ],
        )
        clients = {c["mac"]: c for c in load_support_file(path).get("client_active")}
        assert clients[WIFI_CLIENT]["dev_id"] == 4680

    def test_a_low_confidence_fingerprint_is_discarded(self, tmp_path):
        path = self._archive(
            tmp_path,
            [
                {
                    "mac": WIFI_CLIENT,
                    "ip": "10.0.100.20",
                    "ml": {"deviceNameID": 4183, "confidence": 3},
                }
            ],
        )
        clients = {c["mac"]: c for c in load_support_file(path).get("client_active")}
        # Drawing an HP LaserJet as something else on a 3% hunch is worse than
        # drawing an honest glyph.
        assert "dev_id" not in clients[WIFI_CLIENT]

    def test_it_is_a_last_resort_for_addresses_only(self, tmp_path):
        path = self._archive(
            tmp_path,
            # Disagrees with the lease, which is authoritative.
            [{"mac": WIRED_CLIENT, "ip": "10.0.0.222"}],
        )
        clients = {c["mac"]: c for c in load_support_file(path).get("client_active")}
        assert clients[WIRED_CLIENT]["ip"] == "10.0.0.50"

    def test_it_can_address_a_client_with_no_lease_or_neighbour_entry(self, tmp_path):
        members = _default_members()
        # Strip both of the better sources for this client.
        members["system/run/dnsmasq.lease"] = b""
        members["system/network/ip-neigh"] = b""
        members["system/network/dpi-util-fprint-stats"] = (
            "Response:\n" + json.dumps({"hosts": [{"mac": WIRED_CLIENT, "ip": "10.0.0.77"}]})
        ).encode()
        path = tmp_path / "dpi-only.tgz"
        _write_archive(path, members)

        clients = {c["mac"]: c for c in load_support_file(path).get("client_active")}
        assert clients[WIRED_CLIENT]["ip"] == "10.0.0.77"

    def test_an_unparseable_dpi_file_does_not_break_the_map(self, tmp_path):
        members = _default_members()
        members["system/network/dpi-util-fprint-stats"] = b"Response:\nnot json at all {{{"
        path = tmp_path / "bad-dpi.tgz"
        _write_archive(path, members)
        assert len(load_support_file(path).get("client_active")) == 4


class TestFingerprintFromName:
    """Recovering `dev_id` from the name the console generated.

    A client with no user alias is named "<product> <last two MAC octets>", and
    that product name is the fingerprint entry the controller resolved to. So
    the fingerprint survives in the archive after all, written as text.
    """

    DB: ClassVar[dict] = {
        "dev_ids": {
            "5282": {"name": "Govee Lyra"},
            "2675": {"name": "Google Nest Hub"},
            "292": {"name": "Google Home "},
            "2110": {"name": "Roku Ultra"},
            # Two entries sharing a name, so neither may be chosen.
            "9001": {"name": "Twinned Thing"},
            "9002": {"name": "Twinned Thing"},
        }
    }

    def _archive(self, tmp_path, client_name, mac=WIFI_CLIENT, name="named.tgz"):
        members = _default_members()
        topology = _topology()
        for vertex in topology["default"]["vertices"]:
            if vertex["mac"] == mac:
                vertex["name"] = client_name
        members["unifi/topology.json"] = json.dumps(topology).encode()
        path = tmp_path / name
        _write_archive(path, members)
        return path

    def _dev_id(self, path, mac=WIFI_CLIENT):
        snapshot = load_support_file(path, fingerprint_db=self.DB)
        clients = {c["mac"]: c for c in snapshot.get("client_active")}
        return clients[mac].get("dev_id")

    def test_a_generated_name_resolves_to_its_fingerprint(self, tmp_path):
        # WIFI_CLIENT ends dd:ee:ff:00:00:11, so the tail must be 00:11.
        path = self._archive(tmp_path, "Govee Lyra 00:11")
        assert self._dev_id(path) == 5282

    def test_punctuation_and_spacing_differences_do_not_matter(self, tmp_path):
        path = self._archive(tmp_path, "Google-Home 00:11")
        assert self._dev_id(path) == 292

    def test_a_human_chosen_name_is_refused(self, tmp_path):
        # The real failure this rule exists to prevent: a substring rule mapped
        # "RokuUltraGreatRoom" onto Roku Ultra, which was the wrong product.
        path = self._archive(tmp_path, "RokuUltraGreatRoom")
        assert self._dev_id(path) is None

    def test_a_tail_belonging_to_another_client_is_refused(self, tmp_path):
        # Proves the name was generated for *this* client rather than coined by
        # someone who happened to end it with something MAC-shaped.
        path = self._archive(tmp_path, "Govee Lyra 99:99")
        assert self._dev_id(path) is None

    def test_an_ambiguous_product_name_is_refused(self, tmp_path):
        path = self._archive(tmp_path, "Twinned Thing 00:11")
        assert self._dev_id(path) is None

    def test_without_a_cached_database_nothing_is_resolved(self, tmp_path):
        path = self._archive(tmp_path, "Govee Lyra 00:11")
        snapshot = load_support_file(path)
        clients = {c["mac"]: c for c in snapshot.get("client_active")}
        assert "dev_id" not in clients[WIFI_CLIENT]
        assert "fingerprint" not in snapshot.payloads

    def test_the_name_beats_a_confident_dpi_guess(self, tmp_path):
        members = _default_members()
        topology = _topology()
        for vertex in topology["default"]["vertices"]:
            if vertex["mac"] == WIFI_CLIENT:
                vertex["name"] = "Govee Lyra 00:11"
        members["unifi/topology.json"] = json.dumps(topology).encode()
        members["system/network/dpi-util-fprint-stats"] = (
            "Response:\n"
            + json.dumps(
                {"hosts": [{"mac": WIFI_CLIENT, "ml": {"deviceNameID": 4207, "confidence": 99}}]}
            )
        ).encode()
        path = tmp_path / "name-wins.tgz"
        _write_archive(path, members)
        # The console's name is the answer it settled on; DPI is a live guess.
        assert self._dev_id(path) == 5282


class TestProtect:
    def test_cameras_are_carried_through_when_protect_is_installed(self, tmp_path):
        members = _default_members()
        members["unifi-protect/cameras/cameras.json"] = json.dumps(
            # Protect reports MACs unpunctuated.
            [{"mac": WIRED_CLIENT.replace(":", "").upper(), "name": "G3 Flex"}]
        ).encode()
        path = tmp_path / "with-protect.tgz"
        _write_archive(path, members)

        topo = build_topology(load_support_file(path))
        # Without this, a UniFi camera on a switch port stays ambiguous, because
        # its hostname alone cannot separate a Protect camera from an Access
        # reader, and it falls back to a glyph.
        assert topo.nodes[WIRED_CLIENT].hardware_type == "camera"

    def test_a_console_without_protect_still_loads(self, support_archive):
        snapshot = load_support_file(support_archive)
        assert "protect_cameras" not in snapshot.payloads


class TestBuildsAWholeTopology:
    """The point of the exercise: a support file must produce a real map."""

    def test_every_node_and_edge_lands(self, support_archive):
        topo = build_topology(load_support_file(support_archive))
        counts = topo.counts()
        assert counts[Kind.GATEWAY.value] == 1
        assert counts[Kind.SWITCH.value] == 1
        assert counts[Kind.AP.value] == 1
        assert counts[Kind.WIRED_CLIENT.value] == 3
        assert counts[Kind.WIRELESS_CLIENT.value] == 1

    def test_a_client_behind_another_client_is_placed_not_orphaned(self, support_archive):
        topo = build_topology(load_support_file(support_archive))
        parents = {e.src: e.dst for e in topo.edges}
        assert parents[NESTED_CLIENT] == WIRED_CLIENT
        assert UNKNOWN_UPLINK_ID not in topo.nodes

    def test_port_labels_survive_onto_the_edges(self, support_archive):
        topo = build_topology(load_support_file(support_archive))
        labels = {e.src: e.label for e in topo.edges}
        assert labels[WIRED_CLIENT] == "port 7"

    def test_clients_are_grouped_into_their_named_networks(self, support_archive):
        topo = build_topology(load_support_file(support_archive))
        assert topo.nodes[WIFI_CLIENT].network == "guest"
        assert topo.nodes[WIFI_CLIENT].vlan == 100


class TestRefusals:
    def test_a_file_that_is_not_a_tar_archive_is_reported_clearly(self, tmp_path):
        path = tmp_path / "nonsense.tgz"
        path.write_bytes(b"this is not an archive")
        with pytest.raises(SupportFileError, match="not a readable gzipped tar"):
            load_support_file(path)

    def test_a_missing_file_is_reported_clearly(self, tmp_path):
        with pytest.raises(SupportFileError, match="Could not read"):
            load_support_file(tmp_path / "absent.tgz")

    def test_an_archive_without_the_needed_members_names_what_is_missing(self, tmp_path):
        path = tmp_path / "empty.tgz"
        _write_archive(path, {"unifi/logs/server.log": b"nothing useful here"})
        with pytest.raises(SupportFileError, match=r"devices\.json"):
            load_support_file(path)

    def test_an_oversized_member_is_refused_rather_than_read_into_memory(self, support_archive):
        # A support file is something a stranger sends you, so a member must not
        # be decompressed on trust.
        with pytest.raises(SupportFileError, match="--support-max-member"):
            load_support_file(support_archive, max_member=32)

    def test_the_total_across_members_is_capped_too(self, support_archive):
        # Each member can be under the individual limit while the archive as a
        # whole is not.
        with pytest.raises(SupportFileError, match="--support-max-total"):
            load_support_file(support_archive, max_member=10_000, max_total=64)

    def test_the_caps_are_raisable_rather_than_fatal(self, support_archive):
        # The point of making them arguments: a genuinely large site must have a
        # way through, or people work around the limit instead of raising it.
        snapshot = load_support_file(support_archive, max_member=10_000, max_total=100_000)
        assert snapshot.get("device")

    def test_an_archive_with_absurdly_many_entries_stops_being_walked(self, tmp_path, monkeypatch):
        # The third cap, and the only one with no flag: an archive can be cheap
        # to decompress and still cost real time to walk, since the entry count
        # is unrelated to the bytes decoded. Nothing here is read into memory,
        # so neither size cap fires and this is the only thing that stops it.
        monkeypatch.setattr("unifi_map.support.MAX_ARCHIVE_ENTRIES", 10)
        path = tmp_path / "many.tgz"
        _write_archive(path, {f"{ROOT}/unifi/junk-{i}.txt": b"x" for i in range(25)})
        with pytest.raises(SupportFileError, match="more than 10 entries"):
            load_support_file(path)

    def test_a_symlink_member_is_skipped(self, tmp_path):
        path = tmp_path / "linked.tgz"
        with tarfile.open(path, "w:gz") as archive:
            info = tarfile.TarInfo(f"{ROOT}/unifi/devices.json")
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            archive.addfile(info)
        with pytest.raises(SupportFileError, match=r"devices\.json"):
            load_support_file(path)

    def test_an_unknown_site_name_lists_what_is_available(self, support_archive):
        with pytest.raises(SupportFileError, match="Found: default"):
            load_support_file(support_archive, site="branch-office")


class TestMultipleSites:
    def _two_site_archive(self, tmp_path):
        members = _default_members()
        devices = _devices()
        devices.append({"branch": [dict(devices[0]["default"][0], mac="aa:bb:cc:00:00:99")]})
        members["unifi/devices.json"] = json.dumps(devices).encode()
        path = tmp_path / "multi.tgz"
        _write_archive(path, members)
        return path

    def test_the_largest_site_wins_by_default(self, tmp_path, caplog):
        path = self._two_site_archive(tmp_path)
        with caplog.at_level("WARNING"):
            snapshot = load_support_file(path)
        assert len(snapshot.get("device")) == 3
        # Choosing silently would quietly map the wrong network.
        assert "2 sites" in caplog.text

    def test_a_named_site_is_honoured(self, tmp_path):
        path = self._two_site_archive(tmp_path)
        snapshot = load_support_file(path, site="branch")
        assert len(snapshot.get("device")) == 1


class TestArchiveMemberMatching:
    """Which member is accepted as which file.

    Matching a trailing path fragment is not enough. The premise of this mode is
    that somebody else can send you the archive, so anything they can do to the
    paths inside it is inside the threat model.
    """

    def test_a_decoy_at_a_deeper_path_does_not_win(self, tmp_path):
        members = _default_members()
        real = _devices()
        fake = _devices()
        fake[0]["default"][0]["name"] = "ATTACKER-CONTROLLED"
        members["unifi/devices.json"] = json.dumps(real).encode()

        path = tmp_path / "spoofed.tgz"
        with tarfile.open(path, "w:gz") as archive:
            # Written first, so it is seen first when streaming.
            decoy = json.dumps(fake).encode()
            info = tarfile.TarInfo(f"{ROOT}/evil/unifi/devices.json")
            info.size = len(decoy)
            archive.addfile(info, io.BytesIO(decoy))
            for name, payload in members.items():
                info = tarfile.TarInfo(f"{ROOT}/{name}")
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))

        names = {d["name"] for d in load_support_file(path).get("device")}
        assert "ATTACKER-CONTROLLED" not in names
        assert "gateway" in names

    def test_a_member_at_the_archive_root_is_not_matched(self, tmp_path):
        # Real archives always carry the `support-<id>/` prefix. Anything
        # without it is not the file we are looking for.
        path = tmp_path / "rootlevel.tgz"
        with tarfile.open(path, "w:gz") as archive:
            body = json.dumps(_devices()).encode()
            for name in ("unifi/devices.json", "a/b/unifi/devices.json"):
                info = tarfile.TarInfo(name)
                info.size = len(body)
                archive.addfile(info, io.BytesIO(body))
        with pytest.raises(SupportFileError, match=r"devices\.json"):
            load_support_file(path)
