"""Tests for `--report`, the diagnostic report.

The distinction that matters throughout: `unifi-map shape` is built from an
allowlist and is safe to share; this one names devices on purpose and is not.
Several tests below exist only to keep that boundary from eroding in either
direction.
"""

from __future__ import annotations

from unifi_map.client import Snapshot
from unifi_map.diagnostics import Sources, build_diagnostics
from unifi_map.model import Edge, Kind, Node, Provenance, Topology, build_topology

from .conftest import AP_MAC, SWITCH_MAC


def _topo() -> Topology:
    topo = Topology()
    topo.add(Node(id="gw", label="gateway", kind=Kind.GATEWAY, provenance=Provenance.DEVICE))
    topo.add(
        Node(
            id="c1",
            label="laptop",
            kind=Kind.WIRELESS_CLIENT,
            ip="10.0.0.5",
            provenance=Provenance.CLIENT,
        )
    )
    topo.edges.append(Edge(src="c1", dst="gw", provenance=Provenance.CLIENT_UPLINK))
    return topo


class TestItSaysWhereThingsCameFrom:
    def test_each_source_is_counted_separately(self, snapshot: Snapshot):
        text = build_diagnostics(build_topology(snapshot))
        assert "stat/device" in text
        assert "stat/sta" in text

    def test_a_source_with_nothing_in_it_is_omitted_not_zeroed(self):
        """Zero rows are dropped on purpose.

        A report is read to find something wrong, and a column of zeroes between
        the two numbers that matter is how a reader stops reading.
        """
        text = build_diagnostics(_topo())
        assert "an overrides file" not in text
        assert "stat/device" in text

    def test_the_two_client_placement_routes_do_not_collapse(
        self, devices: dict, clients: dict, networkconf: dict
    ):
        """The whole point of the report: a client the controller saw directly
        and one recovered from its topology graph must not read the same."""
        clients["data"].append(
            {
                "mac": "dd:ee:ff:00:00:a1",
                "hostname": "nas",
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
                        {"downlinkMac": "dd:ee:ff:00:00:a2", "uplinkMac": "dd:ee:ff:00:00:a1"}
                    ]
                },
            }
        )
        text = build_diagnostics(build_topology(snap))
        assert "the controller's topology graph" in text
        assert "stat/sta sw_mac or ap_mac" in text


class TestItNamesWhatWentWrong:
    def test_an_unplaced_client_is_named_not_just_counted(
        self, devices: dict, clients: dict, networkconf: dict
    ):
        """A count says there is a problem; a name says which cupboard to open."""
        clients["data"].append(
            {
                "mac": "dd:ee:ff:00:00:99",
                "hostname": "mystery-box",
                "is_wired": True,
                "ip": "10.0.20.12",
                "network_id": "net1",
            }
        )
        snap = Snapshot(
            payloads={"device": devices, "client_active": clients, "networkconf": networkconf}
        )
        text = build_diagnostics(build_topology(snap))
        assert "COULD NOT BE PLACED" in text
        assert "mystery-box" in text
        assert "10.0.20.12" in text

    def test_no_unplaced_section_when_everything_resolves(self, snapshot: Snapshot):
        assert "COULD NOT BE PLACED" not in build_diagnostics(build_topology(snapshot))

    def test_a_client_with_no_address_is_reported(
        self, devices: dict, clients: dict, networkconf: dict
    ):
        clients["data"].append(
            {
                "mac": "dd:ee:ff:00:00:77",
                "hostname": "no-address-here",
                "is_wired": False,
                "ap_mac": AP_MAC,
                "network_id": "net1",
            }
        )
        snap = Snapshot(
            payloads={"device": devices, "client_active": clients, "networkconf": networkconf}
        )
        text = build_diagnostics(build_topology(snap))
        assert "NO ADDRESS" in text
        assert "no-address-here" in text

    def test_an_unplaced_client_is_not_also_listed_as_merely_addressless(
        self, devices: dict, clients: dict, networkconf: dict
    ):
        """A client can qualify for both sections, and must only appear in one.

        One with no uplink *and* no address was being listed twice, with the
        second entry asserting it was "correctly placed" while the section above
        it said the opposite. Being unplaced is the larger problem and already
        names the device, so the addressless section reports what is left.
        """
        clients["data"].append(
            {"mac": "dd:ee:ff:00:00:99", "hostname": "orphan-no-ip", "is_wired": True}
        )
        snap = Snapshot(
            payloads={"device": devices, "client_active": clients, "networkconf": networkconf}
        )
        text = build_diagnostics(build_topology(snap))
        assert text.count("orphan-no-ip") == 1
        assert "COULD NOT BE PLACED" in text

    def test_a_placed_client_with_no_address_is_still_reported(
        self, devices: dict, clients: dict, networkconf: dict
    ):
        """The other half of the fix: excluding unplaced ones must not empty the
        section. A correctly placed client with no address is its own finding."""
        clients["data"].append(
            {
                "mac": "dd:ee:ff:00:00:98",
                "hostname": "placed-no-ip",
                "is_wired": True,
                "sw_mac": SWITCH_MAC,
                "sw_port": 3,
                "network_id": "net1",
            }
        )
        snap = Snapshot(
            payloads={"device": devices, "client_active": clients, "networkconf": networkconf}
        )
        text = build_diagnostics(build_topology(snap))
        assert "NO ADDRESS" in text
        assert "placed-no-ip" in text

    def test_a_network_the_controller_does_not_list_is_reported(
        self, devices: dict, clients: dict, networkconf: dict
    ):
        """A client naming a network absent from networkconf.

        Derived rather than collected: the model falls back to the name on the
        client's own record when `network_id` matches nothing, so a network name
        that is not among the configured ones is exactly this case.
        """
        clients["data"].append(
            {
                "mac": "dd:ee:ff:00:00:66",
                "hostname": "stray",
                "is_wired": False,
                "ap_mac": AP_MAC,
                "network": "ghost-vlan",
            }
        )
        snap = Snapshot(
            payloads={"device": devices, "client_active": clients, "networkconf": networkconf}
        )
        text = build_diagnostics(build_topology(snap))
        assert "NETWORKS NOT IN THE CONTROLLER'S LIST" in text
        assert "ghost-vlan" in text

    def test_a_configured_network_is_not_reported_as_dangling(self, snapshot: Snapshot):
        text = build_diagnostics(build_topology(snapshot))
        assert "NETWORKS NOT IN THE CONTROLLER'S LIST" not in text


class TestWhatTheSnapshotCarries:
    """An optional endpoint that failed is logged once at fetch time and then
    never mentioned again, so a snapshot cached before an app was installed
    renders thinner every time with nothing saying why."""

    def test_a_missing_optional_endpoint_is_named_with_its_consequence(self):
        text = build_diagnostics(
            _topo(),
            payloads={"device": {"data": [{}]}, "client_active": {"data": []}},
        )
        assert "MISSING OR UNUSABLE" in text
        # The consequence is the actionable half. "topology absent" means
        # nothing to somebody who does not know the pipeline.
        assert "clients behind non-UniFi gear cannot be placed" in text

    def test_present_endpoints_are_counted_in_their_own_units(self):
        text = build_diagnostics(
            _topo(),
            payloads={"device": {"data": [{}, {}]}, "topology": {"edges": [{}]}},
        )
        assert "2 devices" in text
        # Singular, and counted as edges rather than as "records": a graph is
        # one payload and reporting it as "1 record" says nothing useful.
        assert "1 edge" in text

    def test_a_malformed_payload_counts_as_unusable_not_as_empty(self):
        """Present but the wrong shape is the same loss as absent.

        `unwrap()` is deliberately tolerant so a controller upgrade thins the
        diagram instead of raising, which is exactly the failure this section
        exists to make visible.
        """
        text = build_diagnostics(_topo(), payloads={"topology": "nonsense"})
        assert "clients behind non-UniFi gear cannot be placed" in text

    def test_an_empty_graph_is_present_with_zero_not_called_unusable(self):
        """The controller answered, so saying it failed would be wrong.

        `0 edges` is honest and tells the reader the graph contributed nothing,
        which is the same information without the false claim. Only a shape that
        cannot be read at all counts as unusable.
        """
        text = build_diagnostics(_topo(), payloads={"topology": {"edges": []}})
        assert "0 edges" in text
        assert "clients behind non-UniFi gear cannot be placed" not in text

    def test_the_fingerprint_consequence_does_not_claim_artwork(self):
        """Client artwork is keyed on the `dev_id` carried on each client
        record, so it survives the fingerprint database being absent: the demo
        dataset draws product icons with no fingerprint payload at all. Saying
        "and artwork" here would send somebody hunting the wrong gap."""
        text = build_diagnostics(_topo(), payloads={"device": {"data": [{}]}})
        assert "product names in client labels" in text

    def test_no_section_at_all_when_no_payloads_are_supplied(self):
        assert "WHAT THE SNAPSHOT CARRIES" not in build_diagnostics(_topo())


class TestArtwork:
    def test_an_ambiguous_name_is_reported_with_its_match_count(self):
        sources = Sources(ambiguous_artwork=[("g3-flex", 2)])
        text = build_diagnostics(_topo(), sources)
        assert "ARTWORK REFUSED AS AMBIGUOUS" in text
        assert "g3-flex" in text
        assert "matched 2 catalogue entries" in text

    def test_a_name_ambiguous_several_times_is_counted_once_with_a_multiplier(self):
        sources = Sources(ambiguous_artwork=[("g3-flex", 2), ("g3-flex", 2)])
        text = build_diagnostics(_topo(), sources)
        assert text.count("g3-flex") == 1
        assert "x2" in text

    def test_no_artwork_section_without_artwork_facts(self):
        assert "ARTWORK" not in build_diagnostics(_topo())

    def test_builtin_icons_do_not_report_a_lookup_that_never_ran(self):
        """`--icons builtin` attempts no catalogue lookup at all.

        The totals used to print as `0 of 0`, which reads as "looked up and
        found nothing" when the truth is "never looked". Keyed on the presence
        of the totals rather than their value, since only `resolve_icons` sets
        them.
        """
        text = build_diagnostics(_topo(), Sources(artwork={"from_drawn": 28}))
        assert "0 of 0" not in text
        assert "devices by sysid" not in text
        # And the reason the icons were drawn has to follow the mode: they were
        # asked for, not fallen back to.
        assert "nothing was looked up" in text
        assert "no catalogue match" not in text

    def test_unifi_icons_do_report_the_totals_and_the_fallback_reason(self):
        text = build_diagnostics(
            _topo(),
            Sources(
                artwork={
                    "device_total": 7,
                    "device_found": 7,
                    "client_total": 19,
                    "client_found": 19,
                    "from_drawn": 1,
                }
            ),
        )
        assert "devices by sysid    7 of 7" in text
        assert "no catalogue match" in text


class TestItIsNotTheShareableOne:
    """`shape` is allowlist-built and safe to paste anywhere. This is not, and
    the difference has to stay obvious to somebody who runs both."""

    def test_it_says_plainly_that_it_is_not_safe_to_share(self):
        text = build_diagnostics(_topo())
        assert "NOT SAFE TO SHARE" in text
        # And points at the one that is, since a reader who wants to send
        # something needs an answer rather than only a refusal.
        assert "unifi-map shape" in text

    def test_it_really_does_name_a_device_that_needs_attention(
        self, devices: dict, clients: dict, networkconf: dict
    ):
        """The inverse guard to `shape`'s.

        `test_shape.py` asserts no hostname ever appears in that report. This
        asserts one does appear here, so a change that made this allowlist-built
        would fail rather than silently produce a report that cannot do its job.

        Note what it takes to make a name appear: the client has to be *broken*.
        A healthy client is only ever counted, which is the property the test
        below pins.
        """
        clients["data"].append(
            {"mac": "dd:ee:ff:00:00:55", "hostname": "findable-name", "is_wired": True}
        )
        snap = Snapshot(
            payloads={"device": devices, "client_active": clients, "networkconf": networkconf}
        )
        assert "findable-name" in build_diagnostics(build_topology(snap))

    def test_a_healthy_map_names_nothing(self, snapshot: Snapshot):
        """Not a privacy guarantee, and must not be mistaken for one.

        It falls out of the design: devices are named only in the sections about
        what went wrong, so a map with nothing wrong has no names in it. Worth
        pinning because it is the difference between a report that is read and
        one that is skimmed, and because somebody will eventually be tempted to
        add a full node listing "for completeness", which would quietly turn
        every clean run into a network inventory on stdout.
        """
        text = build_diagnostics(build_topology(snapshot))
        for node in build_topology(snapshot).nodes.values():
            if node.kind in (Kind.WIRED_CLIENT, Kind.WIRELESS_CLIENT):
                assert node.label not in text


class TestObfuscation:
    def test_a_scrubbed_topology_produces_a_scrubbed_report(self, snapshot: Snapshot):
        """The report is built after `obfuscate()` runs, so it inherits the
        scrubbing rather than needing its own. Pinned because the ordering in
        `cmd_render` is what makes it true, and ordering is easy to disturb."""
        from unifi_map.obfuscate import obfuscate

        topo = build_topology(snapshot)
        real_labels = {
            n.label for n in topo.nodes.values() if n.kind in (Kind.WIRED_CLIENT, Kind.SWITCH)
        }
        text = build_diagnostics(obfuscate(topo))
        for label in real_labels:
            assert label not in text, f"{label!r} survived obfuscation into the report"


class TestRandomisedMacAddresses:
    """KAN-129: every join here is on MAC, so a rotated MAC looks like a new,
    unrelated client rather than an update to the one already on the map."""

    def _topo_with(self, *macs: str) -> Topology:
        topo = Topology()
        for i, mac in enumerate(macs):
            topo.add(
                Node(
                    id=mac,
                    label=f"client{i}",
                    kind=Kind.WIRELESS_CLIENT,
                    provenance=Provenance.CLIENT,
                )
            )
        return topo

    def test_absent_when_no_client_mac_is_locally_administered(self):
        text = build_diagnostics(self._topo_with("00:11:22:33:44:55", "b8:27:eb:aa:bb:cc"))
        assert "RANDOMISED MAC ADDRESSES" not in text

    def test_counts_only_the_locally_administered_ones(self):
        text = build_diagnostics(
            self._topo_with("00:11:22:33:44:55", "aa:bb:cc:dd:ee:ff", "02:00:00:00:01:04")
        )
        assert "RANDOMISED MAC ADDRESSES" in text
        assert "2 of 3 client(s)" in text

    def test_infrastructure_macs_are_not_counted_as_clients(self):
        """A switch or gateway can be locally administered too (this project's
        own demo fixtures are); only clients are what MAC randomisation is
        actually about, and infrastructure MACs don't rotate."""
        topo = self._topo_with("aa:bb:cc:dd:ee:ff")
        topo.add(Node(id="gw", label="gateway", kind=Kind.GATEWAY, provenance=Provenance.DEVICE))
        text = build_diagnostics(topo)
        assert "1 of 1 client(s)" in text

    def test_names_no_device(self):
        """Counted, not named: there is nothing wrong with any one device here,
        and no overrides file entry that would fix it, so naming one would
        imply an action the reader cannot actually take.

        Gives the client an address so `_addressless_section` -- a different
        section, with a different and legitimate reason to print a name --
        does not fire and confound the assertion.
        """
        topo = self._topo_with("aa:bb:cc:dd:ee:ff")
        topo.nodes["aa:bb:cc:dd:ee:ff"].ip = "10.0.0.5"
        text = build_diagnostics(topo)
        assert "client0" not in text

    def test_malformed_mac_does_not_raise(self):
        build_diagnostics(self._topo_with("not-a-mac"))
