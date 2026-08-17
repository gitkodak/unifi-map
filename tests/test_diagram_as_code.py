"""Pins the workflow `docs/diagram-as-code.md` documents.

Not a feature this project tests for its own sake -- see that page's own
warning -- but the page makes concrete claims about what works (an all-empty
snapshot plus overrides renders a real diagram) and what does not (kind =
"internet" is refused; that one is pinned in test_overrides.py instead,
alongside the rest of the schema validation it belongs with). A doc making a
claim nothing checks is exactly the failure this project's own AI_DISCLOSURE.md
warns about, so this exists to keep that one honest.
"""

from __future__ import annotations

from unifi_map.client import Snapshot
from unifi_map.model import Kind, build_topology
from unifi_map.overrides import apply, parse
from unifi_map.render_dot import Style, render_dot
from unifi_map.theme import LIGHT

EMPTY_SNAPSHOT = Snapshot(
    payloads={
        "device": {"data": []},
        "client_active": {"data": []},
        "networkconf": {"data": []},
    }
)

FROM_SCRATCH_OVERRIDES = {
    "device": [
        {"name": "Core Switch", "kind": "switch"},
        {"name": "Office Laptop", "kind": "wired_client", "parent": "Core Switch", "port": 3},
        {"name": "Guest Phone", "kind": "wireless_client", "parent": "Core Switch"},
    ]
}


def test_an_all_empty_snapshot_builds_an_empty_topology():
    """The documented starting point: three files reporting nothing."""
    topo = build_topology(EMPTY_SNAPSHOT)
    assert topo.nodes == {}
    assert topo.edges == []


def test_overrides_alone_populate_the_whole_map():
    topo = build_topology(EMPTY_SNAPSHOT)
    result = apply(topo, parse(FROM_SCRATCH_OVERRIDES))

    labels = {n.label for n in result.topology.nodes.values()}
    assert labels == {"Core Switch", "Office Laptop", "Guest Phone"}
    # Every node is asserted: nothing here was ever observed by a controller.
    assert all(n.asserted for n in result.topology.nodes.values())


def test_the_declared_tree_renders():
    topo = build_topology(EMPTY_SNAPSHOT)
    result = apply(topo, parse(FROM_SCRATCH_OVERRIDES))

    dot_source = render_dot(
        result.topology, "Not An Actual Network", Style(theme=LIGHT, icons="builtin")
    )
    assert "Core Switch" in dot_source
    assert "Office Laptop" in dot_source
    assert "Guest Phone" in dot_source
    # Parent -> child link exists between the switch and each client.
    assert dot_source.count("->") == 2


def test_a_floating_device_has_no_parent_edge():
    """`parent` is optional and documented as "without one it floats" --
    the root of a from-scratch tree relies on exactly this."""
    topo = build_topology(EMPTY_SNAPSHOT)
    result = apply(topo, parse({"device": [{"name": "Root", "kind": "gateway"}]}))

    assert result.topology.nodes["asserted-root"].kind is Kind.GATEWAY
    assert result.topology.edges == []
