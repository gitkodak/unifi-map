"""Render a :class:`Topology` as Graphviz DOT.

Two independent choices drive the look, both exposed on the command line:

``icons``
    ``unifi``   real Ubiquiti product artwork, drawn bare with the label
                beneath, the way the UniFi topology view presents devices.
    ``builtin`` only icons drawn by this project (see ``drawn.py``). No network
                access, no external assets, and role stays encoded in the
                silhouette so it survives greyscale. Bare Graphviz primitives
                remain only as the degradation path, when drawing fails.

``layout``
    ``unifi``   left-to-right tree with orthogonal links and no port labels,
                mirroring how the UniFi UI arranges things. The default: out of
                the box this tool should reproduce what the web view shows.
    ``tree``    top-down, leaf-staggered, with port numbers on the links.
                Built to actually be readable on a busy network.

Defaults deliberately match the UniFi web view. The one exception is offline
devices, which are hidden by default because the UI offers no way to do that and
a controller remembers hardware long after it leaves the rack.

DOT is the intermediate format for every output, draw.io included, because
`dot` does the hierarchical layout that makes a network tree legible.
"""

from __future__ import annotations

from dataclasses import dataclass

from .assets import IconAsset
from .model import Kind, Topology
from .theme import KIND_LABEL, KIND_SHAPE, Theme, network_colors

_CLIENT_KINDS = (Kind.WIRED_CLIENT, Kind.WIRELESS_CLIENT)
_TABLE_END = "</TABLE>>"

FONT = "Helvetica,Arial,sans-serif"

ICON_SETS = ("unifi", "builtin")
LAYOUTS = ("tree", "unifi")


# Artwork is fitted inside this box, in points, preserving aspect ratio. Wider
# than tall because rack-mount switch renders are long and thin.
ICON_BOX_W = 168
ICON_BOX_H = 90


@dataclass(frozen=True)
class Style:
    theme: Theme
    icons: str = "unifi"
    layout: str = "unifi"
    # None means "decide from the layout".
    legend: bool | None = None
    title_block: bool | None = None
    # Draw no canvas at all, so the map sits on whatever it is placed on.
    # Everything else still comes from the theme, which matters more here than
    # it looks: node labels have no card behind them, so on a transparent
    # canvas every label lands directly on the destination page.
    transparent: bool = False

    def __post_init__(self) -> None:
        if self.icons not in ICON_SETS:
            raise ValueError(f"icons must be one of {ICON_SETS}, got {self.icons!r}")
        if self.layout not in LAYOUTS:
            raise ValueError(f"layout must be one of {LAYOUTS}, got {self.layout!r}")

    @property
    def show_legend(self) -> bool:
        # The UniFi UI has no legend, and a legend cluster widens the canvas.
        return self.layout != "unifi" if self.legend is None else self.legend

    @property
    def show_title(self) -> bool:
        # A graph label sets a minimum canvas width, so on a tall narrow map it
        # pads the drawing with dead space on both sides. The UniFi view has no
        # title either, so dropping it is both faithful and tighter.
        return self.layout != "unifi" if self.title_block is None else self.title_block

    @property
    def show_port_labels(self) -> bool:
        # The UniFi UI does not label links with port numbers, and `ortho`
        # routing cannot place edge labels well anyway.
        return self.layout != "unifi"

    @property
    def staggers(self) -> bool:
        return self.layout == "tree"


def _flourish(theme: Theme) -> list[str]:
    """An unconnected node, when the environment asks for one.

    Emitted straight into the DOT rather than added to the `Topology`, so it
    cannot reach counts, per-network filtering, obfuscation or the report. It is
    decoration and stays decoration.
    """
    from .config import flourish

    if flourish() != "map":
        return []
    # Large friendly letters, as specified.
    return [
        f'  "_f" [shape=none, margin=0, fontsize=34, fontname="{FONT}", '
        f'fontcolor="{theme.accents.get(Kind.AP, theme.text)}", label="DON\'T PANIC"];'
    ]


def _escape(text: str) -> str:
    """Escape for a plain DOT quoted string."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _html(text: str) -> str:
    """Escape for inside a Graphviz HTML-like label."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _node_id(raw: str) -> str:
    """A DOT-safe identifier. MACs contain colons, which DOT reads as ports."""
    return '"n_' + _escape(raw).replace(":", "") + '"'


def _text_row(text: str, size: float, color: str, bold: bool = False) -> str:
    inner = _html(text)
    if bold:
        inner = f"<B>{inner}</B>"
    return (
        f'<TR><TD><FONT POINT-SIZE="{size}" COLOR="{color}" FACE="{FONT}">{inner}</FONT></TD></TR>'
    )


def _icon_label(topo: Topology, node_id: str, theme: Theme, accent: str, icon: IconAsset) -> str:
    """Bare artwork with the label beneath, as the UniFi topology view shows it.

    No border and no fill: the artwork is the node. SRC must be a filesystem
    path because Graphviz cannot read a data URI here; inline_svg_images()
    rewrites these into data URIs afterwards so the SVG stands alone.
    """
    node = topo.nodes[node_id]
    cell_w, cell_h = icon.display_size(ICON_BOX_W, ICON_BOX_H)
    rows = [
        f'<TR><TD FIXEDSIZE="TRUE" WIDTH="{cell_w}" HEIGHT="{cell_h}">'
        f'<IMG SCALE="TRUE" SRC="{_html(str(icon.path))}"/></TD></TR>',
        _text_row(node.label, 13, theme.text, bold=True),
    ]
    if node.ip:
        rows.append(_text_row(node.ip, 10, theme.text_muted))
    if node.detail and node.detail != node.label:
        rows.append(_text_row(node.detail, 9, theme.text_faint))
    if node.network and node.kind in _CLIENT_KINDS:
        vlan = f" · VLAN {node.vlan}" if node.vlan else ""
        rows.append(_text_row(f"{node.network}{vlan}", 9, accent))
    if node.offline:
        rows.append(_text_row("OFFLINE", 9, "#D55E00", bold=True))

    return (
        '<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0" CELLPADDING="1">'
        + "".join(rows)
        + _TABLE_END
    )


def _plain_label(topo: Topology, node_id: str) -> str:
    node = topo.nodes[node_id]
    lines = [node.label]
    if node.ip:
        lines.append(node.ip)
    if node.detail and node.detail != node.label:
        lines.append(node.detail)
    if node.network and node.kind in _CLIENT_KINDS:
        vlan = f" (VLAN {node.vlan})" if node.vlan else ""
        lines.append(f"{node.network}{vlan}")
    if node.offline:
        lines.append("OFFLINE")
    return "\\n".join(_escape(line) for line in lines)


def _graph_attrs(style: Style) -> list[str]:
    theme = style.theme
    if style.layout == "unifi":
        shape = [
            "  rankdir=LR;",
            "  splines=ortho;",
            "  nodesep=0.45;",
            "  ranksep=1.3;",
            # Trim the canvas to the drawing; no framing whitespace.
            "  pad=0.08;",
        ]
    else:
        shape = [
            "  rankdir=TB;",
            "  pad=0.4;",
            # Not `ortho`: Graphviz cannot place edge labels on orthogonal
            # routes, so port numbers drift away from the link they describe.
            "  splines=polyline;",
            "  nodesep=0.4;",
            "  ranksep=1.0;",
        ]
    return [
        *shape,
        "  compound=true;",
        # Graphviz spells it "transparent" and honours it for svg, png and pdf.
        f'  bgcolor="{"transparent" if style.transparent else theme.background}";',
        *_flourish(theme),
    ]


def render_dot(
    topo: Topology,
    title: str,
    style: Style,
    icons: dict[str, IconAsset] | None = None,
    subtitle: str | None = None,
) -> str:
    icons = icons or {}
    theme = style.theme
    colors = network_colors([n for n in {x.network for x in topo.nodes.values()} if n])

    out: list[str] = [
        "digraph unifi {",
        "  // Generated by unifi-map. Edit the generator, not this file.",
        *_graph_attrs(style),
        f'  node [shape=none, margin=0.04, penwidth=0, style="", fontname="{FONT}"];',
        f'  edge [fontname="{FONT}", fontsize=9, color="{theme.edge}",'
        f' fontcolor="{theme.edge_label}", arrowhead=none, penwidth=1.5];',
        "",
    ]
    if style.show_title:
        out += [
            f"  label={_title_block(title, subtitle, theme)};",
            "  labelloc=t;",
            "  labeljust=l;",
            "",
        ]

    for node_id, node in sorted(topo.nodes.items()):
        accent = theme.accent(node.kind)
        if node.kind in _CLIENT_KINDS and node.network in colors:
            accent = colors[node.network]

        # Whatever the caller resolved, without second-guessing it. This used to
        # be gated on `style.icons == "unifi"`, back when `builtin` meant no
        # artwork existed at all; now it means artwork we drew ourselves rather
        # than artwork fetched from Ubiquiti, and there is plenty of it. The
        # gate also silently discarded icons a user supplied through an
        # overrides file, which were never fetched from anywhere either.
        icon = icons.get(node_id)
        if icon is not None:
            attrs = [f"label={_icon_label(topo, node_id, theme, accent, icon)}"]
            if node.asserted:
                # Artwork alone would read as something the controller reported,
                # so an asserted device gets a dotted outline around it. Dotted
                # matches the asserted edge style; offline uses dashed, so the
                # two stay distinguishable and both survive greyscale.
                attrs += ["shape=box", "style=dotted", f'color="{accent}"', "penwidth=1"]
        else:
            attrs = [
                f'label="{_plain_label(topo, node_id)}"',
                f"shape={KIND_SHAPE[node.kind]}",
                'style="filled,rounded,dotted"'
                if node.asserted
                else 'style="filled,rounded,dashed"'
                if node.offline
                else 'style="filled,rounded"',
                f'fillcolor="{theme.card_muted if node.offline else theme.card}"',
                f'color="{accent}"',
                f'fontcolor="{theme.text}"',
                "fontsize=11",
                "penwidth=2",
            ]
        out.append(f"  {_node_id(node_id)} [{', '.join(attrs)}];")

    out.append("")
    for edge in topo.edges:
        if edge.src not in topo.nodes or edge.dst not in topo.nodes:
            continue
        attrs = []
        if edge.label and style.show_port_labels:
            attrs.append(f'label="{_escape(edge.label)}"')
        if edge.asserted:
            # Dotted means "you told me this", so it never reads as something
            # the controller reported.
            attrs.append("style=dotted")
        elif edge.wireless:
            # The wired/wireless distinction must survive greyscale printing.
            attrs.append("style=dashed")
        suffix = f" [{', '.join(attrs)}]" if attrs else ""
        # Emitted parent -> child, the reverse of how edges are stored, so the
        # root lands at the top (rankdir=TB) or the left (rankdir=LR) instead of
        # trailing at the far end. Matches UniFi and normal network-diagram
        # convention: Internet and gateway first, leaves last.
        out.append(f"  {_node_id(edge.dst)} -> {_node_id(edge.src)}{suffix};")

    if style.show_legend:
        out.extend(_legend(topo, theme, colors, icons))

    out.append("}")
    return "\n".join(out) + "\n"


def _title_block(title: str, subtitle: str | None, theme: Theme) -> str:
    rows = [
        f'<TR><TD ALIGN="LEFT"><FONT POINT-SIZE="30" COLOR="{theme.title}" FACE="{FONT}">'
        f"<B>{_html(title)}</B></FONT></TD></TR>"
    ]
    if subtitle:
        rows.append(
            f'<TR><TD ALIGN="LEFT"><FONT POINT-SIZE="12" COLOR="{theme.text_muted}" '
            f'FACE="{FONT}">{_html(subtitle)}</FONT></TD></TR>'
        )
    return (
        '<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0" CELLPADDING="2">'
        + "".join(rows)
        + _TABLE_END
    )


def _legend_swatch(theme: Theme, color: str, label: str) -> str:
    return (
        f'<TR><TD WIDTH="16" HEIGHT="12" FIXEDSIZE="TRUE" BGCOLOR="{color}"></TD>'
        f'<TD ALIGN="LEFT"><FONT POINT-SIZE="10" COLOR="{theme.text_muted}" '
        f'FACE="{FONT}">{_html(label)}</FONT></TD></TR>'
    )


def _legend_note(theme: Theme, text: str) -> str:
    return (
        f'<TR><TD COLSPAN="2" ALIGN="LEFT"><FONT POINT-SIZE="9" '
        f'COLOR="{theme.text_faint}" FACE="{FONT}">{_html(text)}</FONT></TD></TR>'
    )


def _legend_role_rows(
    topo: Topology, theme: Theme, icons: dict[str, IconAsset]
) -> tuple[list[str], bool]:
    shaped = {n.kind for n in topo.nodes.values() if n.id not in icons}
    drawn_as_art = any(n.id in icons for n in topo.nodes.values())
    rows = []

    if drawn_as_art:
        rows.append(_legend_note(theme, "Device role: shown by its artwork"))
    if shaped:
        if drawn_as_art:
            rows.append(
                f'<TR><TD COLSPAN="2" ALIGN="LEFT"><FONT POINT-SIZE="11" '
                f'COLOR="{theme.text}" FACE="{FONT}"><BR/><B>Without artwork</B>'
                f"</FONT></TD></TR>"
            )
        for kind in Kind:
            if kind in shaped:
                rows.append(_legend_swatch(theme, theme.accent(kind), KIND_LABEL[kind]))

    return rows, drawn_as_art


def _legend_network_rows(
    topo: Topology, theme: Theme, colors: dict[str, str], drawn_as_art: bool
) -> list[str]:
    used = sorted({n.network for n in topo.nodes.values() if n.kind in _CLIENT_KINDS and n.network})
    if not used:
        return []

    label = "Client network" if not drawn_as_art else "Client network (label colour)"
    rows = [
        f'<TR><TD COLSPAN="2" ALIGN="LEFT"><FONT POINT-SIZE="11" COLOR="{theme.text}" '
        f'FACE="{FONT}"><BR/><B>{label}</B></FONT></TD></TR>'
    ]
    for name in used:
        vlans = {n.vlan for n in topo.nodes.values() if n.network == name and n.vlan}
        suffix = f" · VLAN {sorted(vlans)[0]}" if vlans else ""
        rows.append(_legend_swatch(theme, colors[name], f"{name}{suffix}"))
    return rows


def _legend_link_rows(topo: Topology, theme: Theme) -> list[str]:
    rows = [
        f'<TR><TD COLSPAN="2" ALIGN="LEFT"><FONT POINT-SIZE="11" COLOR="{theme.text}" '
        f'FACE="{FONT}"><BR/><B>Links</B></FONT></TD></TR>'
    ]
    link_styles = [("&#9472;&#9472;", "Wired"), ("- - -", "Wireless")]
    if any(e.asserted for e in topo.edges) or any(n.asserted for n in topo.nodes.values()):
        link_styles.append((". . .", "Stated in overrides"))
    for glyph, label in link_styles:
        rows.append(
            f'<TR><TD ALIGN="RIGHT"><FONT POINT-SIZE="10" COLOR="{theme.edge}" '
            f'FACE="{FONT}">{glyph}</FONT></TD>'
            f'<TD ALIGN="LEFT"><FONT POINT-SIZE="10" COLOR="{theme.text_muted}" '
            f'FACE="{FONT}">{label}</FONT></TD></TR>'
        )
    return rows


def _legend(
    topo: Topology,
    theme: Theme,
    colors: dict[str, str],
    icons: dict[str, IconAsset] | None = None,
) -> list[str]:
    """Legend as its own card, kept out of the tree layout with rank=sink.

    Only describes what the diagram actually encodes. A node drawn as artwork has
    no border and no fill, so its accent colour is never visible and a role
    swatch for it would be a lie; role is carried by the artwork instead. Swatches
    are therefore emitted only for roles that really were drawn as shapes in this
    render.
    """
    icons = icons or {}
    rows = [
        f'<TR><TD COLSPAN="2" ALIGN="LEFT"><FONT POINT-SIZE="12" COLOR="{theme.text}" '
        f'FACE="{FONT}"><B>Legend</B></FONT></TD></TR>'
    ]
    role_rows, drawn_as_art = _legend_role_rows(topo, theme, icons)
    rows.extend(role_rows)
    rows.extend(_legend_network_rows(topo, theme, colors, drawn_as_art))
    rows.extend(_legend_link_rows(topo, theme))

    table = (
        f'<<TABLE BORDER="1" CELLBORDER="0" CELLSPACING="2" CELLPADDING="3" '
        f'BGCOLOR="{theme.card}" COLOR="{theme.border}" STYLE="ROUNDED">'
        + "".join(rows)
        + _TABLE_END
    )
    return [
        "",
        "  subgraph cluster_legend {",
        '    label="";',
        "    style=invis;",
        "    rank=sink;",
        f'    legend [shape=none, style="", penwidth=0, label={table}];',
        "  }",
    ]
