"""Render a `Topology` as JSON, for anything that wants the graph rather than a picture.

The model is the stable thing here and UniFi's payloads are not: endpoints move
between controller versions, `unwrap()` exists to absorb that, and half the notes
in `CLAUDE.md` are about schema quirks. So this exports the normalised graph and
not the raw responses, which lets somebody write an inventory check or a Home
Assistant integration against something that will still parse next year.

It is also the least dangerous way to hand the data to another program. A cached
snapshot is a full controller dump; this is nodes, edges and networks, subject to
`--obfuscate`, overrides and per-network filtering exactly like the diagram, so
whatever cleaning was applied to the picture applies here too.

**The schema may gain fields and will not lose them.** Provenance in particular
is coming: nothing currently records whether a client was placed from `stat/sta`,
from the topology graph or from an override, and when that exists it belongs
here. Written as additive from the start so that arriving does not break a reader.
"""

from __future__ import annotations

import json
from typing import Any

from . import __version__
from .model import Topology

# Bumped only if something is removed or changes meaning. New fields do not.
SCHEMA_VERSION = 1


def _node(node: Any) -> dict[str, Any]:
    """One node, omitting what is not known rather than emitting null.

    Absent and null would mean the same thing to every reader, and omitting
    keeps the output readable by a human, which is half of why it is JSON.
    """
    out: dict[str, Any] = {"id": node.id, "label": node.label, "kind": node.kind.value}
    for name in ("ip", "model", "network", "vlan", "detail", "sysid", "dev_id"):
        value = getattr(node, name, None)
        if value is not None:
            out[name] = value
    for name in ("offline", "is_guest", "wireless", "asserted"):
        if getattr(node, name, False):
            out[name] = True
    return out


def _edge(edge: Any) -> dict[str, Any]:
    # `src` is the child and `dst` the parent, as everywhere else in this
    # codebase. Named rather than renumbered so the two agree.
    out: dict[str, Any] = {"child": edge.src, "parent": edge.dst}
    if edge.label:
        out["label"] = edge.label
    for name in ("wireless", "asserted"):
        if getattr(edge, name, False):
            out[name] = True
    return out


def render_json(topo: Topology, title: str | None = None) -> str:
    """The topology as JSON text, newline-terminated."""
    document = {
        "schema": SCHEMA_VERSION,
        "generator": f"unifi-map {__version__}",
        "title": title or None,
        "counts": topo.counts(),
        "networks": [
            {
                k: v
                for k, v in (
                    ("id", getattr(n, "id", None)),
                    ("name", getattr(n, "name", None)),
                    ("vlan", getattr(n, "vlan", None)),
                    ("is_guest", getattr(n, "is_guest", None) or None),
                )
                if v is not None
            }
            for n in topo.networks.values()
        ],
        "nodes": [_node(n) for n in topo.nodes.values()],
        "edges": [_edge(e) for e in topo.edges],
    }
    if document["title"] is None:
        del document["title"]
    return json.dumps(document, indent=2, sort_keys=False) + "\n"
