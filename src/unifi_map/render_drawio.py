"""Emit an uncompressed .drawio file with real, editable shapes.

draw.io accepts uncompressed mxGraphModel XML directly, so no deflate/base64
step is needed. Nodes arrive pre-positioned using Graphviz's layout, artwork is
embedded as a data URI so the file stands alone, and Lucid imports the same
.drawio format.
"""

from __future__ import annotations

import base64
import html
import mimetypes
from pathlib import Path
from xml.etree import ElementTree as ET

from .assets import IconAsset
from .layout import Layout
from .model import Edge, Kind, Node, Provenance, Topology
from .render_dot import _node_id
from .theme import Theme, network_colors

_CLIENT_KINDS = (Kind.WIRED_CLIENT, Kind.WIRELESS_CLIENT)

# Fallback draw.io shape per role, used when there is no artwork. Shape carries
# the role independently of colour, matching the DOT renderer.
_SHAPE_STYLE: dict[Kind, str] = {
    Kind.INTERNET: "ellipse;shape=cloud;",
    Kind.GATEWAY: "shape=hexagon;perimeter=hexagonPerimeter2;",
    Kind.SWITCH: "shape=cube;boundedLbl=1;darkOpacity=0.05;darkOpacity2=0.1;",
    Kind.AP: "shape=trapezoid;perimeter=trapezoidPerimeter;",
    Kind.BRIDGE: "shape=hexagon;perimeter=hexagonPerimeter2;",
    Kind.WIRED_CLIENT: "rounded=1;arcSize=12;",
    Kind.WIRELESS_CLIENT: "rounded=1;arcSize=12;",
    Kind.UNKNOWN: "rhombus;",
}


def _cell_id(raw: str) -> str:
    # Reuse the DOT identifier scheme so layout lookups line up exactly.
    return _node_id(raw).strip('"')


def _drawio_data_uri(path: Path) -> str:
    """draw.io expects `data:<type>,<base64>`: a comma, and no `;base64`.

    The media type is derived rather than assumed. Everything looked up is PNG,
    but an `icon` in an overrides file may be an SVG, and labelling those bytes
    `image/png` produced a shape draw.io could not draw.
    """
    guessed, _ = mimetypes.guess_type(path.name)
    media = guessed if (guessed or "").startswith("image/") else "image/png"
    return f"data:{media}," + base64.b64encode(path.read_bytes()).decode("ascii")


# Artwork box inside a draw.io shape, in points. Matches the DOT renderer so the
# two outputs look like the same diagram.
DRAWIO_ICON_W = 84
DRAWIO_ICON_H = 56


def _node_style(node, theme: Theme, accent: str, icon: IconAsset | None) -> str:
    fill = theme.card_muted if node.offline else theme.card
    parts = [
        "whiteSpace=wrap;html=1;",
        f"fillColor={fill};",
        f"strokeColor={accent};",
        f"fontColor={theme.text};",
        "fontSize=11;align=center;",
        f"strokeWidth={'2' if node.kind not in _CLIENT_KINDS else '1'};",
    ]
    if icon is not None:
        # shape=label keeps the text alongside the image, unlike shape=image.
        parts.insert(0, "shape=label;rounded=1;arcSize=8;")
        img_w, img_h = icon.display_size(DRAWIO_ICON_W, DRAWIO_ICON_H)
        # The label stays *inside* the cell. `verticalLabelPosition=bottom` puts
        # it below the cell bounds instead, and that is wrong here for a
        # specific reason: Graphviz sized this node to hold the artwork and the
        # text together, which is what the SVG draws. Moving the text outside
        # leaves dead space in the box and lands the label on whatever the
        # layout placed underneath, so on a dense map every icon in a column
        # wore its neighbour's caption.
        parts.append(
            f"image={_drawio_data_uri(icon.path)};"
            "imageAlign=center;imageVerticalAlign=top;"
            f"imageWidth={img_w};imageHeight={img_h};"
            "verticalLabelPosition=middle;verticalAlign=bottom;spacingBottom=4;"
        )
    else:
        parts.insert(0, _SHAPE_STYLE[node.kind])
    if node.asserted:
        # Stated by the user, not reported. Dotted, matching asserted edges.
        parts.append("dashed=1;dashPattern=1 3;")
    elif node.offline:
        parts.append("dashed=1;")
    return "".join(parts)


def _text(value: object) -> str:
    """Escape a value that came from the controller before it becomes markup.

    Every cell style here sets `html=1`, which tells draw.io to parse the value
    as HTML. ElementTree XML-escapes the attribute on serialisation, but XML
    escaping is not HTML escaping: draw.io decodes the attribute back to the
    original characters and *then* renders them. So a device named
    `<img src=x onerror=...>` arrives as an element rather than as text.

    Nothing here is trusted. Device and client names come from a controller, or
    from a support file somebody else produced, and both are ultimately set by
    whoever named the device. The intentional `<b>` and `<br>` are added after
    escaping, so only this module can emit markup.
    """
    return html.escape(str(value), quote=False)


def _node_value(node) -> str:
    lines = [f"<b>{_text(node.label)}</b>"]
    if node.ip:
        lines.append(_text(node.ip))
    if node.detail and node.detail != node.label:
        lines.append(_text(node.detail))
    if node.network and node.kind in _CLIENT_KINDS:
        vlan = f" · VLAN {node.vlan}" if node.vlan else ""
        lines.append(_text(f"{node.network}{vlan}"))
    if node.offline:
        lines.append("<b>OFFLINE</b>")
    # html=1 is set on every style, so <br> separates lines.
    return "<br>".join(lines)


def _node_accent(node: Node, theme: Theme, colors: dict[str, str]) -> str:
    if node.kind in _CLIENT_KINDS and node.network in colors:
        return colors[node.network]
    return theme.accent(node.kind)


def _add_node_cell(
    root: ET.Element,
    topo: Topology,
    layout: Layout,
    node_id: str,
    theme: Theme,
    icons: dict[str, IconAsset],
    colors: dict[str, str],
    fallback_y: float,
) -> float:
    node = topo.nodes[node_id]
    cell_id = _cell_id(node_id)
    placed = layout.nodes.get(cell_id)
    cell = ET.SubElement(
        root,
        "mxCell",
        id=cell_id,
        value=_node_value(node),
        style=_node_style(node, theme, _node_accent(node, theme, colors), icons.get(node_id)),
        vertex="1",
        parent="1",
    )
    if placed is not None:
        geometry = {
            "x": f"{placed.x:.1f}",
            "y": f"{placed.y:.1f}",
            "width": f"{placed.width:.1f}",
            "height": f"{placed.height:.1f}",
        }
    else:
        # Should not happen, but an unplaced node is better stacked in a corner
        # than silently dropped from the diagram.
        geometry = {"x": "40", "y": f"{fallback_y:.1f}", "width": "160", "height": "40"}
        fallback_y += 50.0
    _geometry(cell, geometry)
    return fallback_y


def _add_node_cells(
    root: ET.Element,
    topo: Topology,
    layout: Layout,
    theme: Theme,
    icons: dict[str, IconAsset],
) -> None:
    colors = network_colors([n for n in {x.network for x in topo.nodes.values()} if n])
    fallback_y = 40.0
    for node_id in sorted(topo.nodes):
        fallback_y = _add_node_cell(root, topo, layout, node_id, theme, icons, colors, fallback_y)


def _edge_style(edge: Edge, theme: Theme) -> str:
    parts = [
        "edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;",
        f"strokeColor={theme.edge};fontColor={theme.edge_label};fontSize=9;",
    ]
    if edge.provenance is Provenance.TOPOLOGY_GRAPH:
        # A client placed via the v2 topology graph rather than its own
        # reported uplink. Independent of the dash styles below, so it
        # composes with a wireless edge instead of competing with it.
        # Edges run dst -> src (parent -> child, matching the DOT renderer),
        # so the child end is the target, i.e. `endArrow`.
        parts.append("startArrow=none;endArrow=oval;endFill=0;")
    else:
        parts.append("startArrow=none;endArrow=none;")
    if edge.asserted:
        parts.append("dashed=1;dashPattern=1 3;")
    elif edge.wireless:
        parts.append("dashed=1;")
    return "".join(parts)


def _add_edge_cell(
    root: ET.Element,
    edge: Edge,
    index: int,
    theme: Theme,
    routes: dict[tuple[str, str], list[list[tuple[float, float]]]],
    shared: dict[tuple[str, str], list[str]],
) -> None:
    source, target = _cell_id(edge.dst), _cell_id(edge.src)
    label_text = edge.label or ""
    group = shared.get((edge.dst, edge.label)) if edge.label else None
    if group and edge.src in group:
        # Same marker as the DOT/SVG renderer: several clients on this port,
        # flagged rather than drawn as a synthetic switch (KAN-199).
        label_text += " *"
    cell = ET.SubElement(
        root,
        "mxCell",
        id=f"e{index}",
        value=_text(label_text),
        style=_edge_style(edge, theme),
        edge="1",
        parent="1",
        # parent -> child, matching the DOT renderer's direction.
        source=source,
        target=target,
    )
    geometry = _geometry(cell, {"relative": "1"})

    # Hand draw.io the route Graphviz already computed. Without this the edge
    # carries only its endpoints, draw.io routes it with its own router, and a
    # long run is drawn straight through whatever the layout placed in between.
    # Graphviz avoided those obstacles and we were discarding the answer.
    waypoints = routes.get((source, target))
    path = waypoints.pop(0) if waypoints else None
    if path and len(path) > 2:
        # The first and last points sit on the node boundaries, which draw.io
        # derives from the shapes themselves. Passing them as waypoints puts a
        # redundant bend right at each end.
        array = ET.SubElement(geometry, "Array")
        array.set("as", "points")
        for x, y in path[1:-1]:
            ET.SubElement(array, "mxPoint", x=f"{x:.1f}", y=f"{y:.1f}")


def _add_edge_cells(root: ET.Element, topo: Topology, layout: Layout, theme: Theme) -> None:
    # Graphviz reported a route per edge; consumed in order, because two nodes
    # can be joined more than once and the nth here is the nth there.
    routes = {pair: list(paths) for pair, paths in layout.edges.items()}
    shared = topo.shared_ports()
    for index, edge in enumerate(topo.edges):
        if edge.src in topo.nodes and edge.dst in topo.nodes:
            _add_edge_cell(root, edge, index, theme, routes, shared)


def render_drawio(
    topo: Topology,
    layout: Layout,
    title: str,
    theme: Theme,
    icons: dict[str, IconAsset] | None = None,
    transparent: bool = False,
) -> str:
    icons = icons or {}
    mxfile = ET.Element("mxfile", host="unifi-map", type="device")
    diagram = ET.SubElement(mxfile, "diagram", name=title[:50] or "Network", id="unifi-map-1")
    model = ET.SubElement(
        diagram,
        "mxGraphModel",
        dx="1400",
        dy="900",
        grid="1",
        gridSize="10",
        guides="1",
        tooltips="1",
        connect="1",
        arrows="1",
        fold="1",
        page="1",
        pageScale="1",
        pageWidth="1169",
        pageHeight="826",
        # draw.io treats a missing background as none, which is what
        # `--transparent` wants; writing the string "none" is not portable
        # across versions, so the attribute is left out instead.
        **({} if transparent else {"background": theme.background}),
        math="0",
        shadow="0",
    )
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", id="0")
    ET.SubElement(root, "mxCell", id="1", parent="0")

    _add_node_cells(root, topo, layout, theme, icons)
    _add_edge_cells(root, topo, layout, theme)

    return ET.tostring(mxfile, encoding="unicode")


def _geometry(parent: ET.Element, attrs: dict[str, str]) -> ET.Element:
    """Append an mxGeometry child carrying the required `as="geometry"`.

    `as` is a Python keyword, so it cannot be passed as a SubElement kwarg and
    has to be set explicitly.
    """
    geometry = ET.SubElement(parent, "mxGeometry", **attrs)
    geometry.set("as", "geometry")
    return geometry
