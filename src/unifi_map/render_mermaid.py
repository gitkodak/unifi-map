"""Render a `Topology` as Mermaid, for places that render Markdown natively.

The other backends produce files. This produces text that GitHub, GitLab and
most wikis draw in place, which is the one destination the rest of the tool
cannot reach: a README cannot embed an SVG that needs a colour scheme, and a
draw.io file is not a picture until somebody opens it.

**It loses all artwork, necessarily.** Mermaid draws boxes and text, so the
product renders that make the other outputs worth looking at have nowhere to
go. What survives is the shape: who is plugged into what, on which port, over
what medium. That is enough for documentation and not enough for the wall
display, which is the honest division of labour between this and the SVG.

Node kind survives as shape rather than as colour, matching the rule the rest of
the tool follows: `([round])` for the internet, `[[switch]]` for a switch,
`{{hex}}` for an access point, `[box]` for a client. Greyscale and colourblind
readers lose nothing, because colour was never carrying the meaning.
"""

from __future__ import annotations

import re

from .model import Edge, Kind, Node, Topology

# Mermaid node ids may not contain punctuation that means something to it, and a
# MAC is mostly punctuation.
_ID = re.compile(r"[^A-Za-z0-9]")

# Shape per kind, as `(open, close)`. Mermaid has no notion of an icon, so this
# is the only channel available for what a thing is.
SHAPES: dict[Kind, tuple[str, str]] = {
    Kind.INTERNET: ("([", "])"),
    Kind.GATEWAY: ("[/", "\\]"),
    Kind.SWITCH: ("[[", "]]"),
    Kind.AP: ("{{", "}}"),
    Kind.BRIDGE: ("[(", ")]"),
    Kind.WIRED_CLIENT: ("[", "]"),
    Kind.WIRELESS_CLIENT: ("(", ")"),
    Kind.UNKNOWN: ("{", "}"),
}


def _ident(raw: str) -> str:
    """A Mermaid-safe node id. Prefixed, because an id may not start a digit."""
    return "n" + _ID.sub("", raw)


def _label(node: Node) -> str:
    """The node's text. Quoted, because a label is user-supplied.

    Mermaid takes `"` inside a quoted label as the end of it, and there is no
    escape, so the character is replaced rather than escaped. `#quot;` is the
    documented entity but is not honoured everywhere it is documented.
    """
    parts = [node.label]
    if node.ip:
        parts.append(node.ip)
    return " · ".join(p.replace('"', "'") for p in parts)


def _edge(edge: Edge) -> str:
    """One link. Dotted for asserted, dashed for wireless, solid otherwise.

    Same visual grammar as every other backend: dashes mean the controller
    reported it over the air, dots mean a human asserted it and nothing
    observed it.
    """
    if edge.asserted:
        arrow = "-.->"
    elif edge.wireless:
        arrow = "-..-"
    else:
        arrow = "-->"
    if edge.label:
        # Pipes delimit an edge label, so one inside it would end the label.
        return f"{arrow}|{edge.label.replace('|', '/')}|"
    return arrow


def render_mermaid(topo: Topology, title: str | None = None, direction: str = "LR") -> str:
    """Mermaid `flowchart` source for *topo*.

    `direction` is Mermaid's, not ours: `LR` matches the console's left-to-right
    view and `TB` matches the readable one.
    """
    lines: list[str] = []
    if title:
        # A YAML front-matter title is rendered by Mermaid 10+ and ignored
        # harmlessly by older versions, which is the right way round.
        lines += ["---", f"title: {title}", "---"]
    lines.append(f"flowchart {direction}")

    for node in topo.nodes.values():
        open_, close = SHAPES.get(node.kind, ("[", "]"))
        lines.append(f'    {_ident(node.id)}{open_}"{_label(node)}"{close}')

    # Parent to child, matching the DOT backend, so the root reads first.
    for edge in topo.edges:
        lines.append(f"    {_ident(edge.dst)} {_edge(edge)} {_ident(edge.src)}")

    return "\n".join(lines) + "\n"
