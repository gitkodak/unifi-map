"""Render a `Topology` as a self-contained, interactive HTML viewer.

Pure function from `Topology` plus an already-rendered SVG string to one HTML
document, the same shape as every other backend. Nothing here talks to
Graphviz or the network; the caller renders the SVG exactly as it would for
`-f svg` (icons already inlined by `svg_post.inline_svg_images`) and hands it
here.

**What it adds over a plain SVG**: pan and zoom, a text search that dims
non-matching nodes, click a client to trace its path back to the gateway, and
click a switch or AP to collapse the client leaves hanging off it. That last
one is the actual point: a busy switch with thirty clients is unreadable in
any static format, and it is exactly the thing collapsing solves.

**Pan/zoom is a vendored library, not hand-rolled.** See
`vendor_panzoom.py` for why: a small, dependency-free, MIT-licensed file
checked into the repo is a different category of "vendoring" than the rule
against committing Ubiquiti's artwork, which is about somebody else's
copyright, not about third-party code existing at all.

**Node/edge correlation is done here, in Python, not guessed in JavaScript.**
Graphviz's SVG writer gives every node and edge group a `<title>` holding the
same DOT-safe identifier `render_dot._node_id()` generated, colons stripped.
Rather than have the browser re-derive that transform, this module computes
the same identifiers from the topology it already has and stamps a
`data-id` (nodes) or `data-parent`/`data-child` (edges) attribute directly
onto each matching `<g>`, using the *real* topology id as the value. The
JavaScript below never needs to know the DOT-safe encoding exists.

**The topology payload is base64-encoded**, not embedded as a JSON literal
inside a `<script>` tag. A label can come from a controller or, worse, a
support file, both hostile input by this project's own rule, and a label
containing a literal `</script>` would end the block early no matter how
carefully the JSON around it was escaped. Base64 sidesteps the whole
category: there is no text content for a crafted string to break out of.
"""

from __future__ import annotations

import base64
import html
import json
import re

from .model import Topology
from .render_json import render_json
from .theme import Theme
from .vendor_panzoom import PANZOOM_JS

# Matches a Graphviz node or edge group immediately followed by its <title>,
# e.g. `<g id="node3" class="node">\n<title>n_020000000103</title>`. Grouped
# so the replacement can insert a data attribute right before the opening
# tag's closing `>` without disturbing anything else.
_G_WITH_TITLE = re.compile(
    rb'(<g id="(?:node|edge)\d+" class="(node|edge)")(>)\s*<title>([^<]*)</title>'
)


def _dot_token(raw_id: str) -> str:
    """The exact `<title>` text Graphviz emits for this node.

    Mirrors `render_dot._node_id()`, minus the DOT quoting: escaping a quote
    or backslash for DOT syntax is reversed by Graphviz's own SVG writer, so
    the title text is always `"n_" + raw_id` with colons removed, regardless
    of what the id contains.
    """
    return "n_" + raw_id.replace(":", "")


def _tag_svg_with_data_ids(svg: bytes, topo: Topology) -> bytes:
    """Stamp `data-id` / `data-parent` + `data-child` onto the matching `<g>`.

    Nodes or edges the lookup does not recognise (the legend, the title
    block, `DON'T PANIC`) are left exactly as Graphviz wrote them: no
    attribute is added, and the viewer's JavaScript only ever selects
    elements that carry one.
    """
    node_by_token = {_dot_token(n.id): n.id for n in topo.nodes.values()}
    edge_by_token = {
        f"{_dot_token(e.dst)}->{_dot_token(e.src)}": (e.dst, e.src) for e in topo.edges
    }

    def replace(match: re.Match[bytes]) -> bytes:
        open_tag, kind, close_gt, raw_title = match.groups()
        title_text = html.unescape(raw_title.decode("utf-8", errors="replace"))

        extra = b""
        if kind == b"node":
            node_id = node_by_token.get(title_text)
            if node_id is not None:
                extra = f' data-id="{html.escape(node_id, quote=True)}"'.encode()
        else:
            pair = edge_by_token.get(title_text)
            if pair is not None:
                parent_id, child_id = pair
                extra = (
                    f' data-parent="{html.escape(parent_id, quote=True)}"'
                    f' data-child="{html.escape(child_id, quote=True)}"'
                ).encode()

        return open_tag + extra + close_gt + b"\n<title>" + raw_title + b"</title>"

    return _G_WITH_TITLE.sub(replace, svg)


def _b64_json(payload: dict) -> str:
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


_CSS = """
:root {{
  --um-bg: {bg}; --um-card: {card}; --um-border: {border};
  --um-text: {text}; --um-text-muted: {text_muted};
}}
* {{ box-sizing: border-box; }}
html, body {{
  margin: 0; height: 100%; background: var(--um-bg); color: var(--um-text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
}}
#um-toolbar {{
  display: flex; align-items: center; gap: 0.75rem; padding: 0.6rem 1rem;
  background: var(--um-card); border-bottom: 1px solid var(--um-border);
  position: sticky; top: 0; z-index: 1; flex-wrap: wrap;
}}
#um-toolbar input[type="search"] {{
  flex: 0 1 20rem; padding: 0.4rem 0.6rem; border: 1px solid var(--um-border);
  border-radius: 6px; background: var(--um-bg); color: var(--um-text); font-size: 0.9rem;
}}
#um-toolbar button {{
  padding: 0.4rem 0.8rem; border: 1px solid var(--um-border); border-radius: 6px;
  background: var(--um-bg); color: var(--um-text); font-size: 0.9rem; cursor: pointer;
}}
#um-toolbar button:hover {{ background: var(--um-border); }}
#um-hint, #um-match-count {{ color: var(--um-text-muted); font-size: 0.85rem; }}
#um-stage {{ width: 100%; height: calc(100% - 3.1rem); overflow: hidden; touch-action: none; }}
#um-stage svg {{ display: block; width: 100%; height: 100%; }}
[data-id], [data-parent] {{ transition: opacity 150ms ease; }}
[data-id] {{ cursor: pointer; }}
.um-dim {{ opacity: 0.15; }}
.um-hidden {{ display: none; }}
"""

# `{graph}` and `{data}` are filled with `%`-style placeholders instead of
# `.format()`, because the vendored library's own source (and the CSS above)
# already uses `{` and `}` constantly and escaping every one of them would
# make both far harder to keep in sync with upstream.
_PAGE = (
    """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%(title)s</title>
<style>%(css)s</style>
</head>
<body>
<div id="um-toolbar">
  <input id="um-search" type="search" placeholder="Search nodes\u2026" autocomplete="off">
  <span id="um-match-count"></span>
  <button id="um-reset" type="button">Reset view</button>
  <span id="um-hint">Scroll or drag to pan, pinch or Ctrl+scroll to zoom. Click a """
    """client to trace its path to the gateway. Click a switch or AP to collapse its """
    """clients.</span>
</div>
<div id="um-stage">
%(svg)s
</div>
<script>%(panzoom_js)s</script>
<script type="application/octet-stream" id="um-data">%(data_b64)s</script>
<script>%(viewer_js)s</script>
</body>
</html>
"""
)

_VIEWER_JS = r"""
(function () {
  "use strict";

  function decodeData(el) {
    var bytes = Uint8Array.from(atob(el.textContent), function (c) {
      return c.charCodeAt(0);
    });
    return JSON.parse(new TextDecoder().decode(bytes));
  }

  var graph = decodeData(document.getElementById("um-data"));
  var nodeById = {};
  graph.nodes.forEach(function (n) {
    nodeById[n.id] = n;
  });
  var parentOf = {};
  var childrenOf = {};
  graph.edges.forEach(function (e) {
    parentOf[e.child] = e.parent;
    (childrenOf[e.parent] = childrenOf[e.parent] || []).push(e.child);
  });

  var CLIENT_KINDS = { wired_client: true, wireless_client: true };

  function hasClientChildren(id) {
    return (childrenOf[id] || []).some(function (c) {
      var n = nodeById[c];
      return n && CLIENT_KINDS[n.kind];
    });
  }

  var stage = document.getElementById("um-stage");
  var svg = stage.querySelector("svg");
  var allNodeGroups = Array.prototype.slice.call(svg.querySelectorAll("[data-id]"));
  var allEdgeGroups = Array.prototype.slice.call(svg.querySelectorAll("[data-parent]"));

  function nodeEl(id) {
    return svg.querySelector('[data-id="' + cssEscape(id) + '"]');
  }
  function edgeEl(parentId, childId) {
    return svg.querySelector(
      '[data-parent="' + cssEscape(parentId) + '"][data-child="' + cssEscape(childId) + '"]'
    );
  }
  function cssEscape(s) {
    return window.CSS && CSS.escape ? CSS.escape(s) : s.replace(/["\\]/g, "\\$&");
  }

  // ---- Pan and zoom, via the vendored Panzoom. ----
  // No `contain` option. Panzoom's containment math divides the element's
  // current bounding-box size by the current scale to find its "natural"
  // size, but the svg is styled `width:100%;height:100%`, so that box is
  // always exactly the container's size regardless of zoom: dividing it out
  // makes the "natural" size always equal the container too, leaving no
  // slack to pan within before containment clamps straight back to the
  // origin. That is what made panning feel like it was fighting back.
  // Freely panning into empty space around the diagram is normal for a
  // canvas viewer (every pan/zoom tool behaves this way) and needs no
  // containment at all.
  var panzoom = Panzoom(svg, { maxScale: 8, minScale: 0.1 });

  // A plain wheel event is ambiguous: it is what a two-finger trackpad swipe
  // sends, and it is what a mouse wheel sends, and those two devices want
  // opposite things from it. Every pan/zoom canvas that gets this right
  // (Figma, Miro, Google Maps) agrees on the resolution: ctrlKey means zoom.
  // Browsers set it on their own for a trackpad pinch — no physical Ctrl
  // involved — so this also covers an actual Ctrl+scroll for free. Anything
  // without ctrlKey pans, which is what a two-finger swipe is for. Binding
  // every wheel event straight to zoom, as an earlier version of this did,
  // meant the single most common gesture (swipe to pan) zoomed instead.
  stage.addEventListener(
    "wheel",
    function (ev) {
      if (ev.ctrlKey) {
        panzoom.zoomWithWheel(ev);
        return;
      }
      ev.preventDefault();
      var scale = panzoom.getScale();
      panzoom.pan(-ev.deltaX / scale, -ev.deltaY / scale, { relative: true, force: true });
    },
    { passive: false }
  );

  // ---- Search: dims nodes whose label/ip/detail does not match. ----
  var searchInput = document.getElementById("um-search");
  var matchCountEl = document.getElementById("um-match-count");

  function clearDim() {
    allNodeGroups.concat(allEdgeGroups).forEach(function (el) {
      el.classList.remove("um-dim");
    });
  }

  function clearSelection() {
    clearDim();
    searchInput.value = "";
    matchCountEl.textContent = "";
  }

  searchInput.addEventListener("input", function () {
    var q = searchInput.value.trim().toLowerCase();
    if (!q) {
      clearDim();
      matchCountEl.textContent = "";
      return;
    }
    var count = 0;
    allEdgeGroups.forEach(function (el) {
      el.classList.remove("um-dim");
    });
    allNodeGroups.forEach(function (el) {
      var n = nodeById[el.getAttribute("data-id")];
      var hay = [n.label, n.ip, n.detail].filter(Boolean).join(" ").toLowerCase();
      var hit = hay.indexOf(q) !== -1;
      if (hit) count++;
      el.classList.toggle("um-dim", !hit);
    });
    matchCountEl.textContent = count + (count === 1 ? " match" : " matches");
  });

  // ---- Click a client: highlight its path back to the root. ----
  function highlightPath(id) {
    var chain = [id];
    var cur = id;
    while (Object.prototype.hasOwnProperty.call(parentOf, cur)) {
      cur = parentOf[cur];
      chain.push(cur);
    }
    var keepNodes = {};
    chain.forEach(function (n) {
      keepNodes[n] = true;
    });
    var keepEdges = {};
    for (var i = 0; i < chain.length - 1; i++) {
      keepEdges[chain[i] + "\u0000" + chain[i + 1]] = true; // "child\u0000parent"
    }
    allNodeGroups.forEach(function (el) {
      el.classList.toggle("um-dim", !keepNodes[el.getAttribute("data-id")]);
    });
    allEdgeGroups.forEach(function (el) {
      var key = el.getAttribute("data-child") + "\u0000" + el.getAttribute("data-parent");
      el.classList.toggle("um-dim", !keepEdges[key]);
    });
  }

  // ---- Click a switch or AP with clients: collapse just those clients. ----
  function toggleCollapse(id) {
    var kids = (childrenOf[id] || []).filter(function (c) {
      var n = nodeById[c];
      return n && CLIENT_KINDS[n.kind];
    });
    var el = nodeEl(id);
    var collapsed = el.classList.toggle("um-collapsed");
    kids.forEach(function (childId) {
      var childEl = nodeEl(childId);
      var linkEl = edgeEl(id, childId);
      if (childEl) childEl.classList.toggle("um-hidden", collapsed);
      if (linkEl) linkEl.classList.toggle("um-hidden", collapsed);
    });
  }

  // A real click, not the tail end of a drag: Panzoom's own down/move/up
  // handling does not distinguish the two, and a synthetic click still
  // fires after a small drag in most browsers. A movement threshold is
  // cheap and avoids collapsing a node the user only meant to pan past.
  var DRAG_THRESHOLD = 4;
  allNodeGroups.forEach(function (g) {
    var downX, downY, dragged;
    g.addEventListener("pointerdown", function (ev) {
      downX = ev.clientX;
      downY = ev.clientY;
      dragged = false;
    });
    g.addEventListener("pointermove", function (ev) {
      if (downX === undefined) return;
      var dx = Math.abs(ev.clientX - downX);
      var dy = Math.abs(ev.clientY - downY);
      if (dx > DRAG_THRESHOLD || dy > DRAG_THRESHOLD) {
        dragged = true;
      }
    });
    g.addEventListener("click", function (ev) {
      if (dragged) return;
      ev.stopPropagation();
      var id = g.getAttribute("data-id");
      if (hasClientChildren(id)) {
        toggleCollapse(id);
      } else {
        highlightPath(id);
      }
    });
  });

  stage.addEventListener("click", function (ev) {
    if (ev.target === stage || ev.target === svg) clearSelection();
  });
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape") clearSelection();
  });

  document.getElementById("um-reset").addEventListener("click", function () {
    panzoom.reset();
    clearSelection();
  });
})();
"""


def render_html(topo: Topology, svg: str, theme: Theme, title: str | None = None) -> str:
    """A single self-contained HTML file: pan/zoom, search, path highlight, collapse.

    *svg* is the already-rendered, already-icon-inlined SVG for *topo* — the
    same string `-f svg` would write. Callers pass the theme actually used to
    render it, purely for the toolbar chrome to match; the SVG's own colours
    are untouched.
    """
    tagged_svg = _tag_svg_with_data_ids(svg.encode("utf-8"), topo).decode("utf-8")

    payload = json.loads(render_json(topo, title))
    data_b64 = _b64_json(payload)

    css = _CSS.format(
        bg=theme.background,
        card=theme.card,
        border=theme.border,
        text=theme.text,
        text_muted=theme.text_muted,
    )

    return _PAGE % {
        "title": html.escape(title or "unifi-map"),
        "css": css,
        "svg": tagged_svg,
        "panzoom_js": PANZOOM_JS,
        "data_b64": data_b64,
        "viewer_js": _VIEWER_JS,
    }
