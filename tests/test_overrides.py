"""The overrides schema and loader.

Applying overrides is not implemented; these cover the parts that are, so the
stub is not untested dead code.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from unifi_map.assets import AssetError
from unifi_map.client import Snapshot
from unifi_map.model import UNKNOWN_UPLINK_ID, Kind, build_topology
from unifi_map.overrides import (
    Hosted,
    Link,
    OverrideError,
    Overrides,
    apply,
    load,
    parse,
    resolve,
)

from .conftest import AP_MAC, SWITCH_MAC


@pytest.fixture
def topo(snapshot):
    return build_topology(snapshot)


@pytest.fixture
def unplaced_topo(devices, clients, networkconf):
    """Includes a client the controller could not place, like a VM."""
    clients["data"].append(
        {
            "mac": "dd:ee:ff:00:00:60",
            "hostname": "vm-host",
            "is_wired": True,
            "ip": "10.0.20.60",
            "network_id": "net2",
        }
    )
    return build_topology(
        Snapshot(payloads={"device": devices, "client_active": clients, "networkconf": networkconf})
    )


EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "overrides.toml"


class TestParse:
    def test_links_and_hosted_are_read(self):
        result = parse(
            {
                "link": [{"from": "nas", "to": "Rack Switch", "port": 10, "speed": "10G"}],
                "hosted": [{"guest": "runner", "host": "hypervisor", "note": "VM"}],
            }
        )
        assert result.links == [Link(source="nas", target="Rack Switch", port="10", speed="10G")]
        assert result.hosted == [Hosted(guest="runner", host="hypervisor", note="VM")]

    def test_unquoted_integer_port_is_normalised_to_a_string(self):
        # Ports are naturally written unquoted in TOML.
        link = parse({"link": [{"from": "a", "to": "b", "port": 24}]}).links[0]
        assert link.port == "24"

    def test_empty_payload_is_falsy(self):
        assert not parse({})
        assert not Overrides()

    def test_wireless_flag_defaults_false(self):
        assert parse({"link": [{"from": "a", "to": "b"}]}).links[0].wireless is False
        assert parse({"link": [{"from": "a", "to": "b", "wireless": True}]}).links[0].wireless

    @pytest.mark.parametrize(
        "payload,message",
        [
            ({"link": [{"to": "b"}]}, "'from' is required"),
            ({"link": [{"from": "a"}]}, "'to' is required"),
            ({"link": [{"from": "", "to": "b"}]}, "'from' is required"),
            ({"link": ["nope"]}, "must be a table"),
            ({"hosted": [{"host": "h"}]}, "'guest' is required"),
            ({"hosted": [{"guest": "g"}]}, "'host' is required"),
            ({"hosted": ["nope"]}, "must be a table"),
        ],
    )
    def test_malformed_entries_are_rejected_loudly(self, payload, message):
        # A typo must fail the run, not silently do nothing.
        with pytest.raises(OverrideError, match=message):
            parse(payload)

    def test_error_message_identifies_the_offending_entry(self):
        with pytest.raises(OverrideError, match=r"\[\[link\]\] #2"):
            parse({"link": [{"from": "a", "to": "b"}, {"from": "c"}]})

    def test_non_string_optional_value_is_rejected(self):
        with pytest.raises(OverrideError, match="must be a string or number"):
            parse({"link": [{"from": "a", "to": "b", "note": ["x"]}]})


class TestLabels:
    def test_port_and_speed_are_combined(self):
        assert Link("a", "b", port="10", speed="10G").label == "port 10 · 10G"

    def test_partial_information_still_labels(self):
        assert Link("a", "b", port="3").label == "port 3"
        assert Link("a", "b", speed="1G").label == "1G"

    def test_no_detail_means_no_label(self):
        assert Link("a", "b").label is None


class TestLoad:
    def test_the_shipped_example_parses(self):
        result = load(EXAMPLE)
        # It documents both override kinds, so it must contain both.
        assert result.links
        assert result.hosted
        assert any(link.speed == "10G" for link in result.links)

    def test_missing_file_raises_override_error(self, tmp_path):
        with pytest.raises(OverrideError, match="No overrides file"):
            load(tmp_path / "absent.toml")

    def test_invalid_toml_raises_override_error(self, tmp_path):
        path = tmp_path / "bad.toml"
        path.write_text("[[link]\nfrom =", encoding="utf-8")
        with pytest.raises(OverrideError, match="not valid TOML"):
            load(path)


class TestResolve:
    def test_matches_a_mac(self, topo):
        assert resolve(SWITCH_MAC, topo) == SWITCH_MAC

    def test_matches_an_address(self, topo):
        assert resolve("10.0.20.10", topo) == "dd:ee:ff:00:00:01"

    def test_matches_a_label_case_insensitively(self, topo):
        assert resolve("core switch", topo) == SWITCH_MAC

    def test_an_unmatched_selector_is_a_loud_error(self, topo):
        with pytest.raises(OverrideError, match="matches nothing"):
            resolve("no-such-device", topo)

    def test_an_ambiguous_selector_is_a_loud_error(self, devices, clients, networkconf):
        # Two clients sharing a name is entirely plausible.
        for mac in ("dd:ee:ff:00:00:70", "dd:ee:ff:00:00:71"):
            clients["data"].append(
                {"mac": mac, "hostname": "printer", "is_wired": True, "network_id": "net1"}
            )
        topo = build_topology(
            Snapshot(
                payloads={"device": devices, "client_active": clients, "networkconf": networkconf}
            )
        )
        with pytest.raises(OverrideError, match="matches 2 nodes"):
            resolve("printer", topo)


class TestApplyLinks:
    def test_adds_an_asserted_edge(self, topo):
        result = apply(topo, parse({"link": [{"from": "nas", "to": "Core Switch", "port": 10}]}))
        added = [e for e in result.topology.edges if e.asserted]
        assert len(added) == 1
        assert added[0].dst == SWITCH_MAC
        assert added[0].label == "port 10"
        assert result.links_added == 1

    def test_replaces_the_uplink_placeholder(self, unplaced_topo):
        assert UNKNOWN_UPLINK_ID in unplaced_topo.nodes
        result = apply(unplaced_topo, parse({"link": [{"from": "vm-host", "to": "Core Switch"}]}))
        # Nothing hangs off the placeholder any more, so it goes.
        assert UNKNOWN_UPLINK_ID not in result.topology.nodes
        assert not any(UNKNOWN_UPLINK_ID in (e.src, e.dst) for e in result.topology.edges)

    def test_an_asserted_parent_is_not_called_controller_reported(self, topo):
        """A second override displacing the first must not blame the controller.

        `_drop_parent_edges` excluded only the unplaceable-client placeholder,
        so an edge an earlier override had asserted counted as an observation.
        Two `[[link]]` blocks naming the same node therefore produced "was
        reported by the controller under gateway" about a link the file itself
        had just created: this function telling exactly the lie it exists to
        prevent.
        """
        result = apply(
            topo,
            parse(
                {"link": [{"from": "nas", "to": "gateway"}, {"from": "nas", "to": "Core Switch"}]}
            ),
        )
        # One real observation displaced, not two.
        assert len(result.displaced) == 1
        assert result.displaced[0].parent != "gateway"

    def test_displacing_an_observed_parent_says_so(self, topo):
        """Replacing a real observation is not the same as tidying a placeholder.

        The design rule is that an override contradicting the controller says
        so rather than quietly preferring itself. `_drop_parent_edges` used to
        be silent on the assumption, written into the call site, that anything
        being linked had been unplaceable. Nothing enforced that, and
        `[[hosted]]` breaks it deliberately.
        """
        result = apply(topo, parse({"link": [{"from": "nas", "to": "gateway"}]}))
        assert [(d.node, d.parent) for d in result.displaced] == [("nas", "Core Switch")]

    def test_tidying_the_placeholder_stays_quiet(self, unplaced_topo):
        """The documented case is not a contradiction, so it must not warn.

        Warning here would put a line in front of every user doing exactly what
        the feature is for, which is how a warning stops being read.
        """
        result = apply(unplaced_topo, parse({"link": [{"from": "vm-host", "to": "Core Switch"}]}))
        assert result.displaced == []

    def test_a_node_ends_up_with_exactly_one_parent(self, topo):
        result = apply(topo, parse({"link": [{"from": "nas", "to": "gateway"}]}))
        nas = resolve("nas", result.topology)
        assert len([e for e in result.topology.edges if e.src == nas]) == 1

    def test_linking_a_node_to_itself_is_rejected(self, topo):
        with pytest.raises(OverrideError, match="same node"):
            apply(topo, parse({"link": [{"from": "nas", "to": "nas"}]}))


class TestApplyHosted:
    def test_reparents_the_guest(self, unplaced_topo):
        result = apply(unplaced_topo, parse({"hosted": [{"guest": "vm-host", "host": "nas"}]}))
        guest = resolve("vm-host", result.topology)
        host = resolve("nas", result.topology)
        edges = [e for e in result.topology.edges if e.src == guest]
        assert len(edges) == 1
        assert edges[0].dst == host
        assert edges[0].asserted is True
        assert result.hosted_applied == 1

    def test_the_note_becomes_the_edge_label(self, unplaced_topo):
        result = apply(
            unplaced_topo,
            parse({"hosted": [{"guest": "vm-host", "host": "nas", "note": "VM"}]}),
        )
        assert any(e.label == "VM" for e in result.topology.edges if e.asserted)

    def test_hosting_itself_is_rejected(self, topo):
        with pytest.raises(OverrideError, match="cannot host itself"):
            apply(topo, parse({"hosted": [{"guest": "nas", "host": "nas"}]}))


class TestApplyNode:
    def test_renames(self, topo):
        result = apply(topo, parse({"node": [{"match": "nas", "name": "Network Bidet"}]}))
        assert any(n.label == "Network Bidet" for n in result.topology.nodes.values())
        assert result.renamed == 1

    def test_user_artwork_is_loaded(self, topo, tmp_path, png_bytes):
        art = tmp_path / "bidet.png"
        art.write_bytes(png_bytes(40, 30))
        result = apply(topo, parse({"node": [{"match": "nas", "icon": str(art)}]}))
        node_id = resolve("nas", result.topology)
        assert result.icons[node_id].path == art
        assert (result.icons[node_id].width, result.icons[node_id].height) == (40, 30)

    def test_missing_artwork_is_a_loud_error(self, topo, tmp_path):
        with pytest.raises(AssetError, match="No artwork file"):
            apply(topo, parse({"node": [{"match": "nas", "icon": str(tmp_path / "nope.png")}]}))


class TestApplyHide:
    def test_hides_a_leaf(self, topo):
        before = len(topo.nodes)
        result = apply(topo, parse({"node": [{"match": "nas", "hide": True}]}))
        assert len(result.topology.nodes) == before - 1
        assert result.hidden == ["nas"]
        assert all(n.label != "nas" for n in result.topology.nodes.values())

    def test_hiding_leaves_no_dangling_edges(self, topo):
        result = apply(topo, parse({"node": [{"match": "nas", "hide": True}]}))
        for edge in result.topology.edges:
            assert edge.src in result.topology.nodes
            assert edge.dst in result.topology.nodes

    def test_refuses_to_hide_something_with_children(self, topo):
        with pytest.raises(OverrideError, match="depend on it"):
            apply(topo, parse({"node": [{"match": "Core Switch", "hide": True}]}))

    def test_the_refusal_names_the_children(self, topo):
        with pytest.raises(OverrideError) as excinfo:
            apply(topo, parse({"node": [{"match": "Core Switch", "hide": True}]}))
        assert "nas" in str(excinfo.value)

    def test_links_are_applied_before_hiding(self, unplaced_topo, tmp_path):
        # Giving a node a child and then hiding it must be refused, which only
        # works if links are applied first.
        payload = {
            "link": [{"from": "vm-host", "to": "nas"}],
            "node": [{"match": "nas", "hide": True}],
        }
        with pytest.raises(OverrideError, match="depend on it"):
            apply(unplaced_topo, parse(payload))


def test_apply_does_not_mutate_the_original(topo):
    before = len(topo.edges)
    apply(topo, parse({"link": [{"from": "nas", "to": "gateway"}]}))
    assert len(topo.edges) == before


def test_nothing_to_do_is_not_an_error(topo):
    result = apply(topo, Overrides())
    assert result.changed is False
    assert len(result.topology.nodes) == len(topo.nodes)


class TestNodeOverrides:
    def test_name_and_icon_are_read(self):
        result = parse(
            {
                "node": [
                    {
                        "match": "10.0.30.22",
                        "name": "Network Bidet",
                        "icon": "assets/bidet.png",
                        "note": "UniFi says smart toothbrush",
                    }
                ]
            },
            base_dir=Path("/cfg"),
        )
        node = result.nodes[0]
        assert node.match == "10.0.30.22"
        assert node.name == "Network Bidet"
        assert node.note == "UniFi says smart toothbrush"
        # Relative to the overrides file, not the working directory.
        assert node.icon == Path("/cfg/assets/bidet.png")

    def test_absolute_icon_path_is_left_alone(self):
        node = parse(
            {"node": [{"match": "x", "icon": "/srv/art/bidet.png"}]}, base_dir=Path("/cfg")
        ).nodes[0]
        assert node.icon == Path("/srv/art/bidet.png")

    def test_relative_icon_without_base_dir_stays_relative(self):
        node = parse({"node": [{"match": "x", "icon": "a/b.png"}]}).nodes[0]
        assert node.icon == Path("a/b.png")

    def test_name_only_and_icon_only_are_both_valid(self):
        assert parse({"node": [{"match": "x", "name": "Renamed"}]}).nodes[0].icon is None
        assert parse({"node": [{"match": "x", "icon": "i.png"}]}).nodes[0].name is None

    def test_an_entry_that_changes_nothing_is_rejected(self):
        # Silently ignoring it would hide a typo'd key.
        with pytest.raises(OverrideError, match="at least one of 'name', 'icon' or 'hide'"):
            parse({"node": [{"match": "x", "note": "just a comment"}]})

    def test_match_is_required(self):
        with pytest.raises(OverrideError, match="'match' is required"):
            parse({"node": [{"name": "Renamed"}]})

    def test_non_table_entry_is_rejected(self):
        with pytest.raises(OverrideError, match=r"\[\[node\]\] #1 must be a table"):
            parse({"node": ["nope"]})

    def test_node_overrides_count_towards_truthiness(self):
        assert parse({"node": [{"match": "x", "name": "y"}]})


def test_the_shipped_example_documents_node_overrides():
    result = load(EXAMPLE)
    assert result.nodes
    # The bidet is the documented example of a wrong fingerprint.
    bidet = next(n for n in result.nodes if n.name == "Network Bidet")
    assert bidet.icon is not None
    # Resolved against the examples/ directory.
    assert bidet.icon.parent == EXAMPLE.parent / "assets"


class TestHideOverride:
    def test_hide_alone_is_a_valid_entry(self):
        node = parse({"node": [{"match": "Garage", "hide": True}]}).nodes[0]
        assert node.hide is True
        assert node.name is None and node.icon is None

    def test_hide_defaults_false(self):
        assert parse({"node": [{"match": "x", "name": "y"}]}).nodes[0].hide is False

    def test_hide_combines_with_a_rename(self):
        node = parse({"node": [{"match": "x", "name": "y", "hide": True}]}).nodes[0]
        assert (node.name, node.hide) == ("y", True)

    def test_an_entry_with_only_a_note_is_still_rejected(self):
        with pytest.raises(OverrideError, match="'name', 'icon' or 'hide'"):
            parse({"node": [{"match": "x", "note": "just a comment"}]})

    def test_hide_false_does_not_count_as_a_change(self):
        # hide = false is the default, so it changes nothing and must not sneak
        # past the "entry does nothing" check.
        with pytest.raises(OverrideError, match="'name', 'icon' or 'hide'"):
            parse({"node": [{"match": "x", "hide": False}]})

    def test_the_shipped_example_documents_hiding(self):
        hidden = [n for n in load(EXAMPLE).nodes if n.hide]
        # Both reasons to hide are worth showing: discretion and noise. Asserted
        # on the note existing rather than on its wording, which was previously
        # pinned to one specific phrase and broke when the example was reworded.
        assert len(hidden) >= 2, "examples/overrides.toml should show hide entries"
        assert all(n.note for n in hidden), "each hide example should say why"
        assert any(n.match == "Garage" for n in hidden)


class TestDeclaredDevices:
    """`[[device]]` states something no source reports.

    A controller only reports what it manages, so the category is defined by a
    relationship rather than by any property of the device: an unmanaged switch,
    a fully managed third-party one, and UniFi gear that was powered off during
    the fetch are all invisible for the same reason. This tool will not guess,
    so the user says so.
    """

    def _apply(self, topo, table):
        from unifi_map.overrides import apply, parse

        return apply(topo, parse(table))

    def test_a_declared_device_becomes_a_node(self, topo):
        result = self._apply(topo, {"device": [{"name": "Basement switch", "kind": "switch"}]})
        node = result.topology.nodes["asserted-basement-switch"]
        assert node.label == "Basement switch"
        assert node.kind is Kind.SWITCH
        assert result.devices_added == 1

    def test_it_is_marked_asserted_so_it_cannot_pass_for_observed(self, topo):
        # The whole point. A map that drew a typed-in device identically to a
        # reported one would misrepresent where its information came from.
        result = self._apply(topo, {"device": [{"name": "Basement switch"}]})
        assert result.topology.nodes["asserted-basement-switch"].asserted is True
        assert all(
            not n.asserted
            for n in result.topology.nodes.values()
            if n.id != "asserted-basement-switch"
        )

    def test_a_parent_produces_an_asserted_edge(self, topo):
        result = self._apply(
            topo,
            {
                "device": [
                    {"name": "Basement switch", "kind": "switch", "parent": SWITCH_MAC, "port": 7}
                ]
            },
        )
        edge = next(e for e in result.topology.edges if e.src == "asserted-basement-switch")
        assert edge.dst == SWITCH_MAC
        assert edge.label == "port 7"
        assert edge.asserted is True

    def test_one_declared_device_can_hang_off_another(self, topo):
        # Devices are added before anything resolves selectors, so order within
        # the file does not matter and a chain works.
        result = self._apply(
            topo,
            {
                "device": [
                    {"name": "Basement switch", "kind": "switch", "parent": SWITCH_MAC},
                    {"name": "Old laptop", "kind": "wired_client", "parent": "Basement switch"},
                ]
            },
        )
        parents = {e.src: e.dst for e in result.topology.edges}
        assert parents["asserted-old-laptop"] == "asserted-basement-switch"

    def test_a_declared_device_can_be_referenced_by_other_overrides(self, topo):
        result = self._apply(
            topo,
            {
                "device": [{"name": "Basement switch", "kind": "switch"}],
                "link": [{"from": AP_MAC, "to": "Basement switch"}],
            },
        )
        assert any(
            e.src == AP_MAC and e.dst == "asserted-basement-switch" for e in result.topology.edges
        )

    def test_an_id_cannot_collide_with_a_mac(self, topo):
        # Ids are prefixed, so a device named after a MAC cannot shadow a real
        # node or be mistaken for one in DOT output.
        result = self._apply(topo, {"device": [{"name": SWITCH_MAC}]})
        assert SWITCH_MAC in result.topology.nodes
        assert result.topology.nodes[SWITCH_MAC].asserted is False
        assert any(n.startswith("asserted-") for n in result.topology.nodes)

    def test_an_unknown_kind_is_refused(self, topo):
        with pytest.raises(OverrideError, match="'kind' must be one of"):
            self._apply(topo, {"device": [{"name": "Thing", "kind": "toaster"}]})

    def test_a_duplicate_name_is_refused(self, topo):
        with pytest.raises(OverrideError, match="already declared"):
            self._apply(topo, {"device": [{"name": "Thing"}, {"name": "thing"}]})

    def test_a_port_without_a_parent_is_refused(self, topo):
        # Silently ignoring it would leave the user believing they had labelled
        # a link that does not exist.
        with pytest.raises(OverrideError, match="means nothing without"):
            self._apply(topo, {"device": [{"name": "Thing", "port": 3}]})

    def test_an_unresolvable_parent_is_a_loud_error(self, topo):
        with pytest.raises(OverrideError):
            self._apply(topo, {"device": [{"name": "Thing", "parent": "no-such-device"}]})


class TestDeclaredDevicesAreOrderIndependent:
    """A declared device may name a parent declared later in the file.

    The comment claimed parents were resolved "after every declared device
    exists" while resolving them inside the creation loop, so this worked in one
    order only. The failure reads as a typo, naming a parent that "matches
    nothing on the map", rather than as ordering.
    """

    def _apply(self, text: str, tmp_path):
        from unifi_map.model import Topology

        path = tmp_path / "o.toml"
        path.write_text(text)
        return apply(Topology(), load(path))

    CHILD_FIRST = """
[[device]]
name = "Child"
kind = "switch"
parent = "Parent"

[[device]]
name = "Parent"
kind = "switch"
"""

    PARENT_FIRST = """
[[device]]
name = "Parent"
kind = "switch"

[[device]]
name = "Child"
kind = "switch"
parent = "Parent"
"""

    def test_a_parent_declared_later_still_resolves(self, tmp_path):
        result = self._apply(self.CHILD_FIRST, tmp_path)
        assert result.devices_added == 2
        assert len(result.topology.edges) == 1

    def test_both_orders_produce_the_same_graph(self, tmp_path):
        first = self._apply(self.CHILD_FIRST, tmp_path)
        second = self._apply(self.PARENT_FIRST, tmp_path)
        assert sorted(first.topology.nodes) == sorted(second.topology.nodes)
        assert [(e.src, e.dst) for e in first.topology.edges] == [
            (e.src, e.dst) for e in second.topology.edges
        ]

    def test_a_genuinely_missing_parent_is_still_an_error(self, tmp_path):
        # The fix must not turn a real typo into a silent no-op.
        with pytest.raises(OverrideError, match="matches nothing"):
            self._apply(
                '[[device]]\nname = "Child"\nkind = "switch"\nparent = "Nowhere"\n', tmp_path
            )


class TestCyclesAreRefused:
    """Something cannot be its own uplink.

    Not a rendering problem: DOT is a digraph, cycles are legal, and Graphviz
    draws one without complaining. Verified before adding this. Refused because
    it is not a network a cable can make, and drawing it silently produces a map
    that looks authoritative and is wrong.
    """

    def _apply(self, text, tmp_path):
        from unifi_map.model import Topology

        path = tmp_path / "o.toml"
        path.write_text(text)
        return apply(Topology(), load(path))

    def test_two_devices_parenting_each_other_are_refused(self, tmp_path):
        text = """
[[device]]
name = "A"
kind = "switch"
parent = "B"

[[device]]
name = "B"
kind = "switch"
parent = "A"
"""
        with pytest.raises(OverrideError, match="loop"):
            self._apply(text, tmp_path)

    def test_the_error_names_the_loop(self, tmp_path):
        text = """
[[device]]
name = "A"
kind = "switch"
parent = "B"

[[device]]
name = "B"
kind = "switch"
parent = "A"
"""
        with pytest.raises(OverrideError, match=r"A -> B -> A|B -> A -> B"):
            self._apply(text, tmp_path)

    def test_a_longer_loop_is_caught_too(self):
        from unifi_map.model import Edge, Kind, Node, Topology
        from unifi_map.overrides import _refuse_cycles

        topo = Topology()
        for name in "abc":
            topo.add(Node(id=name, label=name.upper(), kind=Kind.SWITCH))
        topo.edges += [Edge(src="a", dst="b"), Edge(src="b", dst="c"), Edge(src="c", dst="a")]
        with pytest.raises(OverrideError, match="loop"):
            _refuse_cycles(topo)

    def test_a_node_parented_to_itself_is_caught(self):
        from unifi_map.model import Edge, Kind, Node, Topology
        from unifi_map.overrides import _refuse_cycles

        topo = Topology()
        topo.add(Node(id="x", label="X", kind=Kind.SWITCH))
        topo.edges.append(Edge(src="x", dst="x"))
        with pytest.raises(OverrideError, match="loop"):
            _refuse_cycles(topo)

    def test_an_ordinary_tree_is_not_a_cycle(self):
        # Two children of one parent share a destination, which is not a loop.
        from unifi_map.model import Edge, Kind, Node, Topology
        from unifi_map.overrides import _refuse_cycles

        topo = Topology()
        for name in "abc":
            topo.add(Node(id=name, label=name.upper(), kind=Kind.SWITCH))
        topo.edges += [Edge(src="a", dst="b"), Edge(src="c", dst="b")]
        _refuse_cycles(topo)

    def test_the_demo_overrides_are_still_acyclic(self):
        # Applied to the demo topology, not an empty one: the shipped examples
        # reference real devices, so an empty graph fails at selector
        # resolution long before anything looks for a cycle.
        import json
        from pathlib import Path

        from unifi_map.client import Snapshot
        from unifi_map.model import build_topology

        demo = Path(__file__).resolve().parents[1] / "examples" / "demo"
        payloads = {p.stem: json.loads(p.read_text()) for p in demo.glob("*.json")}
        topo = build_topology(Snapshot(payloads=payloads), include_offline=False)
        apply(topo, load(demo / "overrides.toml"))
