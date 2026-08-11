"""The JSON export.

It is a published contract in a way the diagrams are not: somebody can build an
inventory check or an integration on it, so the tests here are mostly about what
must keep being true rather than about how it looks.
"""

from __future__ import annotations

import json

from unifi_map.client import Snapshot
from unifi_map.model import (
    Edge,
    Kind,
    Node,
    Provenance,
    Topology,
    build_topology,
    filter_by_network,
)
from unifi_map.obfuscate import obfuscate
from unifi_map.render_json import SCHEMA_VERSION, render_json


def _doc(topo, **kw):
    return json.loads(render_json(topo, **kw))


def test_it_is_valid_json_with_a_schema_version(snapshot: Snapshot):
    doc = _doc(build_topology(snapshot))
    assert doc["schema"] == SCHEMA_VERSION
    assert doc["generator"].startswith("unifi-map ")


def test_every_node_and_edge_is_present(snapshot: Snapshot):
    topo = build_topology(snapshot)
    doc = _doc(topo)
    assert len(doc["nodes"]) == len(topo.nodes)
    assert len(doc["edges"]) == len(topo.edges)


def test_every_edge_points_at_a_node_in_the_document(snapshot: Snapshot):
    """A reader joining edges to nodes must not find a dangling id."""
    doc = _doc(build_topology(snapshot))
    ids = {n["id"] for n in doc["nodes"]}
    for edge in doc["edges"]:
        assert edge["child"] in ids
        assert edge["parent"] in ids


def test_provenance_is_exported_for_every_node_and_edge():
    """JSON is the programmatic counterpart to the diagram and report, so it
    must preserve how every item was placed rather than flattening confidence.
    """
    topo = Topology(
        nodes={
            "device": Node("device", "device", Kind.SWITCH, provenance=Provenance.DEVICE),
            "client": Node("client", "client", Kind.WIRED_CLIENT, provenance=Provenance.CLIENT),
            "unknown": Node("unknown", "unknown", Kind.UNKNOWN, provenance=Provenance.SYNTHETIC),
            "asserted": Node("asserted", "asserted", Kind.SWITCH, provenance=Provenance.OVERRIDE),
        },
        edges=[
            Edge("client", "device", provenance=Provenance.CLIENT_UPLINK),
            Edge("asserted", "client", provenance=Provenance.TOPOLOGY_GRAPH),
            Edge("unknown", "device", provenance=Provenance.UNPLACED),
            Edge("device", "asserted", asserted=True, provenance=Provenance.OVERRIDE),
        ],
    )

    doc = _doc(topo)
    assert {node["provenance"] for node in doc["nodes"]} == {
        "device",
        "client",
        "synthetic",
        "override",
    }
    assert {edge["provenance"] for edge in doc["edges"]} == {
        "client_uplink",
        "topology_graph",
        "unplaced",
        "override",
    }
    assert _doc(obfuscate(topo))["edges"][1]["provenance"] == "topology_graph"


def test_absent_facts_are_omitted_not_null(snapshot: Snapshot):
    # Absent and null mean the same thing to a reader, and omitting keeps the
    # document readable by a person, which is half of why it is JSON.
    doc = _doc(build_topology(snapshot))
    assert all(v is not None for node in doc["nodes"] for v in node.values())


def test_false_flags_are_omitted_too(snapshot: Snapshot):
    doc = _doc(build_topology(snapshot))
    assert all(node.get("offline") is not False for node in doc["nodes"])


def test_child_and_parent_are_named_not_numbered(snapshot: Snapshot):
    """Edges are stored child to parent everywhere in this codebase.

    Exporting `src`/`dst` would make a reader guess which way round it is.
    """
    doc = _doc(build_topology(snapshot))
    assert set(doc["edges"][0]) >= {"child", "parent"}


def test_obfuscation_applies(snapshot: Snapshot):
    """Whatever cleaning was applied to the diagram applies here too."""
    from unifi_map.model import UNKNOWN_UPLINK_ID

    plain = _doc(build_topology(snapshot))
    scrubbed = _doc(obfuscate(build_topology(snapshot)))
    # Two nodes keep their identity through obfuscation, exempted by id in
    # `obfuscate.py`: the uplink placeholder and the internet node. Both labels
    # are ours rather than the user's, and scrubbing the node that explains
    # itself would leave a pseudonym where the explanation was.
    exempt = {UNKNOWN_UPLINK_ID, "internet"}
    ours = {n["label"] for n in scrubbed["nodes"] if n["id"] in exempt}
    survived = {n["label"] for n in scrubbed["nodes"]} & {n["label"] for n in plain["nodes"]}
    assert survived <= ours, f"user labels survived obfuscation: {sorted(survived - ours)}"
    assert len(scrubbed["nodes"]) == len(plain["nodes"])


def test_per_network_filtering_applies(snapshot: Snapshot):
    topo = build_topology(snapshot)
    name = next(iter(topo.networks.values())).name
    doc = _doc(filter_by_network(topo, name))
    assert len(doc["nodes"]) < len(topo.nodes)


def test_a_title_is_included_only_when_given(snapshot: Snapshot):
    topo = build_topology(snapshot)
    assert "title" not in _doc(topo)
    assert _doc(topo, title="Demo")["title"] == "Demo"


def test_counts_agree_with_the_topology(snapshot: Snapshot):
    topo = build_topology(snapshot)
    assert _doc(topo)["counts"] == topo.counts()
