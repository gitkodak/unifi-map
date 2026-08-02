"""Mermaid output.

Verified against the real Mermaid parser during development, not only by
inspection: `npx @mermaid-js/mermaid-cli` rendered both the infrastructure-only
graph and the full one with wireless and asserted edges. These tests hold the
properties that would break it, since the parser is not available in CI.
"""

from __future__ import annotations

import re

from unifi_map.client import Snapshot
from unifi_map.model import Edge, Kind, Node, Topology, build_topology
from unifi_map.render_mermaid import SHAPES, render_mermaid


def _ids(source: str) -> set[str]:
    return set(re.findall(r"^\s+(n[A-Za-z0-9]+)[\[({]", source, re.M))


def test_it_declares_every_node(snapshot: Snapshot):
    topo = build_topology(snapshot)
    assert len(_ids(render_mermaid(topo))) == len(topo.nodes)


def test_every_edge_endpoint_is_declared(snapshot: Snapshot):
    """A reference to an undeclared id is what Mermaid actually rejects."""
    source = render_mermaid(build_topology(snapshot))
    declared = _ids(source)
    referenced = set(re.findall(r"^\s+(n\w+) [-.]", source, re.M))
    referenced |= set(re.findall(r"[->|.] (n\w+)$", source, re.M))
    assert referenced <= declared, f"undeclared: {sorted(referenced - declared)}"


def test_ids_never_start_with_a_digit():
    # A MAC-derived id would, and Mermaid will not take it.
    topo = Topology()
    topo.add(Node(id="02:00:00:00:01:01", label="a", kind=Kind.SWITCH))
    assert re.search(r"^\s+n\w+", render_mermaid(topo), re.M)


def test_a_quote_in_a_label_cannot_end_it():
    """Labels are user-supplied and Mermaid has no escape inside a quoted one."""
    topo = Topology()
    topo.add(Node(id="a", label='He said "hello"', kind=Kind.SWITCH))
    source = render_mermaid(topo)
    assert '""' not in source
    assert source.count('"') == 2, "an unbalanced quote would end the label early"


def test_a_pipe_in_an_edge_label_cannot_end_it():
    topo = Topology()
    for node in ("a", "b"):
        topo.add(Node(id=node, label=node, kind=Kind.SWITCH))
    topo.edges.append(Edge(src="b", dst="a", label="port|1"))
    line = next(ln for ln in render_mermaid(topo).splitlines() if "-->" in ln)
    assert line.count("|") == 2


def test_kinds_are_distinguished_by_shape_not_colour(snapshot: Snapshot):
    """Same rule as every other backend: colour is never the only channel."""
    source = render_mermaid(build_topology(snapshot))
    used = {
        open_
        for kind, (open_, _) in SHAPES.items()
        if any(n.kind is kind for n in build_topology(snapshot).nodes.values())
    }
    assert len(used) > 2
    for open_ in used:
        assert open_ in source


def test_wireless_and_asserted_links_are_visually_distinct():
    topo = Topology()
    for node in ("a", "b", "c", "d"):
        topo.add(Node(id=node, label=node, kind=Kind.SWITCH))
    topo.edges += [
        Edge(src="b", dst="a"),
        Edge(src="c", dst="a", wireless=True),
        Edge(src="d", dst="a", asserted=True),
    ]
    source = render_mermaid(topo)
    assert "-->" in source and "-..-" in source and "-.->" in source


def test_direction_follows_the_layout(snapshot: Snapshot):
    topo = build_topology(snapshot)
    assert "flowchart LR" in render_mermaid(topo, direction="LR")
    assert "flowchart TB" in render_mermaid(topo, direction="TB")


def test_a_title_becomes_front_matter(snapshot: Snapshot):
    source = render_mermaid(build_topology(snapshot), title="Demo network")
    assert source.startswith("---\ntitle: Demo network\n---\n")


def test_no_title_means_no_front_matter(snapshot: Snapshot):
    assert render_mermaid(build_topology(snapshot)).startswith("flowchart ")
