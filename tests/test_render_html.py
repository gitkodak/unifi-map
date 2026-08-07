from __future__ import annotations

import base64
import json
import shutil

import pytest

from unifi_map.model import Edge, Kind, Node, Topology, build_topology
from unifi_map.render_dot import Style, render_dot
from unifi_map.render_html import render_html
from unifi_map.theme import LIGHT
from unifi_map.vendor_panzoom import PANZOOM_JS

needs_graphviz = pytest.mark.skipif(
    shutil.which("dot") is None, reason="graphviz `dot` not installed"
)

TREE = Style(theme=LIGHT, icons="builtin", layout="tree")


class TestTheVendoredLibrary:
    def test_it_carries_its_own_license_banner(self):
        # The MIT license requires the notice to survive in a redistributed
        # copy; this is that notice, and it is read from the constant itself
        # rather than the module docstring so a banner-stripping edit fails
        # this rather than only the human-facing prose above it.
        assert "Copyright Timmy Willison" in PANZOOM_JS
        assert "MIT license" in PANZOOM_JS

    def test_it_matches_the_exact_bytes_fetched_from_upstream(self):
        # Pinned by content, not just by size: a single flipped character in
        # a 10 KiB minified bundle is not something a human proofreads for.
        import hashlib

        digest = hashlib.sha256(PANZOOM_JS.encode("utf-8")).hexdigest()
        assert digest == "3ce354ef7b493efb62a4d4acaaf86fa2d6027eb629857a4e144041de1a112c1e"


class TestSvgCorrelation:
    """Every node and edge in the topology must be findable from the DOM.

    Graphviz's own `<title>` is the only link between an SVG group and the
    topology node it draws; `render_html` has to reproduce that exactly or
    the viewer's click handlers silently do nothing.
    """

    @needs_graphviz
    def test_every_node_gets_a_data_id(self, snapshot):
        from unifi_map.layout import run_dot

        topo = build_topology(snapshot)
        dot_source = render_dot(topo, "t", TREE)
        svg = run_dot(dot_source, "svg").decode("utf-8")

        page = render_html(topo, svg, LIGHT, title="t")

        assert page.count(' data-id="') == len(topo.nodes)
        for node_id in topo.nodes:
            assert f' data-id="{node_id}"' in page

    @needs_graphviz
    def test_every_edge_gets_a_data_parent_and_data_child(self, snapshot):
        from unifi_map.layout import run_dot

        topo = build_topology(snapshot)
        dot_source = render_dot(topo, "t", TREE)
        svg = run_dot(dot_source, "svg").decode("utf-8")

        page = render_html(topo, svg, LIGHT, title="t")

        assert page.count(' data-parent="') == len(topo.edges)
        for edge in topo.edges:
            assert f' data-parent="{edge.dst}" data-child="{edge.src}"' in page

    @needs_graphviz
    def test_an_id_containing_a_colon_still_correlates(self, snapshot):
        # MACs are the common case and they are exactly what `_node_id()`
        # strips colons from before handing to Graphviz. If the forward and
        # reverse transforms ever disagree, this is the case that catches it.
        from unifi_map.layout import run_dot

        topo = build_topology(snapshot)
        assert any(":" in node_id for node_id in topo.nodes), "fixture must include a MAC id"

        dot_source = render_dot(topo, "t", TREE)
        svg = run_dot(dot_source, "svg").decode("utf-8")
        page = render_html(topo, svg, LIGHT, title="t")

        for node_id in topo.nodes:
            if ":" in node_id:
                assert f' data-id="{node_id}"' in page


class TestHostileLabelsCannotEscapeTheDataBlock:
    """Client names are attacker-supplied, same rule as everywhere else here.

    The topology payload is embedded base64-encoded specifically so a label
    containing `</script>` cannot end the block early. This constructs that
    exact label and checks both halves: the hostile text must survive into
    the decoded payload, and it must not appear as a literal substring
    anywhere in the page.
    """

    def _topo_with_hostile_label(self, label: str) -> Topology:
        topo = Topology()
        topo.add(Node(id="gw", label="gateway", kind=Kind.GATEWAY))
        topo.add(Node(id="victim", label=label, kind=Kind.WIRED_CLIENT))
        topo.edges.append(Edge(src="victim", dst="gw"))
        return topo

    def _minimal_svg(self, topo: Topology) -> str:
        # Real Graphviz output for exactly these two nodes and one edge,
        # trimmed to the parts render_html actually reads. Avoids requiring
        # a `dot` binary for a test that is about string handling, not layout.
        from unifi_map.render_html import _dot_token

        return (
            "<svg>"
            f'<g id="node1" class="node"><title>{_dot_token("gw")}</title></g>'
            f'<g id="node2" class="node"><title>{_dot_token("victim")}</title></g>'
            f'<g id="edge1" class="edge">'
            f"<title>{_dot_token('gw')}->{_dot_token('victim')}</title></g>"
            "</svg>"
        )

    def test_a_closing_script_tag_in_a_label_does_not_end_the_block(self):
        hostile = "</script><script>window.pwned=true</script>"
        topo = self._topo_with_hostile_label(hostile)
        page = render_html(topo, self._minimal_svg(topo), LIGHT, title="t")

        # Exactly the three real blocks this module writes: the vendored
        # library, the base64 data, and the viewer's own script. A fourth
        # would mean the hostile label broke out of the data block.
        assert page.count("</script>") == 3
        assert "window.pwned" not in page

    def test_the_hostile_label_survives_into_the_decoded_payload(self):
        hostile = "</script><script>window.pwned=true</script>"
        topo = self._topo_with_hostile_label(hostile)
        page = render_html(topo, self._minimal_svg(topo), LIGHT, title="t")

        start = page.index('id="um-data">') + len('id="um-data">')
        end = page.index("</script>", start)
        payload = json.loads(base64.b64decode(page[start:end]))
        labels = [n["label"] for n in payload["nodes"]]
        assert hostile in labels


class TestWriteOutputsWiring:
    @needs_graphviz
    def test_html_can_be_written_without_svg_also_being_requested(self, snapshot, tmp_path):
        from unifi_map.output import write_outputs

        topo = build_topology(snapshot)
        write_outputs(
            render_dot(topo, "t", TREE),
            topo,
            tmp_path,
            "m",
            ["html"],
            TREE,
            {},
        )

        assert (tmp_path / "m.html").exists()
        assert not (tmp_path / "m.svg").exists()

    @needs_graphviz
    def test_the_written_html_embeds_a_working_svg(self, snapshot, tmp_path):
        from unifi_map.output import write_outputs

        topo = build_topology(snapshot)
        write_outputs(
            render_dot(topo, "t", TREE),
            topo,
            tmp_path,
            "m",
            ["html", "svg"],
            TREE,
            {},
        )

        html_text = (tmp_path / "m.html").read_text(encoding="utf-8")
        svg_text = (tmp_path / "m.svg").read_text(encoding="utf-8")

        # Not byte-identical: render_html stamps data-id/data-parent attributes
        # onto the copy embedded in the html, which the standalone svg does not
        # carry. Compare properties tagging cannot change instead: the same
        # canvas size and the same number of node/edge groups.
        def viewbox(svg: str) -> str:
            start = svg.index('viewBox="') + len('viewBox="')
            return svg[start : svg.index('"', start)]

        assert viewbox(svg_text) == viewbox(html_text)
        assert html_text.count('class="node"') == svg_text.count('class="node"')
        assert html_text.count('class="edge"') == svg_text.count('class="edge"')
