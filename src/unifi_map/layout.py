"""Run Graphviz and parse the coordinates it computes.

Graphviz's `-Tplain` output is a stable, line-oriented format, which lets us
reuse `dot`'s hierarchical layout for the draw.io export instead of dumping a
pile of unpositioned shapes on the canvas for you to arrange by hand.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

POINTS_PER_INCH = 72.0


class GraphvizMissing(RuntimeError):
    """Raised when the `dot` binary is not on PATH."""


class GraphvizError(RuntimeError):
    """Raised when `dot` runs but fails."""


@dataclass(frozen=True)
class Placed:
    """A node's position in draw.io pixel space (origin top-left)."""

    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class Layout:
    nodes: dict[str, Placed]
    width: float
    height: float
    # Waypoints per (tail, head), in the order Graphviz reported them and in
    # the same pixel space as `nodes`. Both layouts set `splines` to `ortho` or
    # `polyline`, never a bezier, so these are real corners on the route rather
    # than control points, and can be handed to draw.io as-is.
    #
    # A list per pair because two nodes can be joined more than once, and the
    # nth DOT edge between a pair is the nth reported here.
    edges: dict[tuple[str, str], list[list[tuple[float, float]]]] = field(default_factory=dict)


# Names a credential can arrive under. Stripped from any child's environment:
# `config.py` keeps a key read from a file out of `os.environ` entirely, but a
# user is free to export one, and Graphviz is resolved from PATH.
#
# `UDM_API_KEY` outlives its retirement from `config.py` on purpose. We stopped
# *reading* it in 0.9.0, which does nothing about somebody who still exports it
# and has not cleaned up. An unread variable holding a real key is exactly as
# worth withholding from a child process as a read one, and the asymmetry costs
# a string.
_CREDENTIAL_VARS = ("UNIFI_API_KEY", "UDM_API_KEY")


def child_env() -> dict[str, str]:
    """The parent environment with any API key removed."""
    return {k: v for k, v in os.environ.items() if k not in _CREDENTIAL_VARS}


def require_dot() -> str:
    path = shutil.which("dot")
    if not path:
        raise GraphvizMissing(
            "Graphviz `dot` not found on PATH. Install it with: sudo apt install graphviz"
        )
    return path


def run_dot(dot_source: str, output_format: str, engine: str = "dot") -> bytes:
    """Render *dot_source*, returning raw bytes of *output_format*."""
    # Resolved once and executed by absolute path. Passing a bare name would
    # re-resolve it through PATH at exec time, so whatever `dot` resolves to now
    # is what actually runs.
    executable = shutil.which(engine) if engine != "dot" else require_dot()
    if not executable:
        raise GraphvizMissing(f"Layout engine `{engine}` not found on PATH.")
    try:
        result = subprocess.run(
            [executable, f"-T{output_format}"],
            env=child_env(),
            input=dot_source.encode("utf-8"),
            capture_output=True,
            timeout=300,
            check=False,
        )
    except FileNotFoundError as exc:
        raise GraphvizMissing(f"Layout engine `{engine}` not found.") from exc
    except subprocess.TimeoutExpired as exc:
        raise GraphvizError("Graphviz timed out after 300s.") from exc

    stderr = result.stderr.decode("utf-8", errors="replace").strip()
    if result.returncode != 0:
        raise GraphvizError(f"Graphviz failed ({result.returncode}): {stderr}")
    if stderr:
        # Graphviz warns on stderr and still exits 0, and this was discarded.
        # That is how an icon could vanish from a PNG in silence: there is no
        # `svg:cairo` loadimage plugin, so an SVG is dropped from every
        # cairo-backed format with nothing but a warning nobody saw.
        #
        # Surfaced whole rather than filtered. A warning we have not seen
        # before is exactly the one worth reading, and deciding here which of
        # Graphviz's messages matter is how the last one got hidden.
        for line in stderr.splitlines():
            log.warning("Graphviz (-T%s): %s", output_format, line.strip())
    return result.stdout


def stagger(dot_source: str, depth: int) -> str:
    """Stagger leaf nodes via Graphviz's `unflatten` to tame the aspect ratio.

    A network tree is mostly leaves: ~50 clients hanging off a handful of
    switches lays out as a 9:1 ribbon that is technically zoomable but
    miserable to read or print. `unflatten` chains those leaves into shorter
    rows, which on a ~60-node network takes 9192x1021pt to 4953x2736pt.

    Returns *dot_source* unchanged if depth <= 0 or `unflatten` is unavailable,
    since a poor aspect ratio is far better than no diagram.
    """
    if depth <= 0:
        return dot_source
    executable = shutil.which("unflatten")
    if executable is None:
        log.warning("`unflatten` not found; skipping stagger. Diagram may be very wide.")
        return dot_source
    try:
        result = subprocess.run(
            [executable, "-f", "-l", str(depth)],
            env=child_env(),
            input=dot_source.encode("utf-8"),
            capture_output=True,
            timeout=120,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        log.warning("`unflatten` failed; using unstaggered layout.", exc_info=True)
        return dot_source
    if result.returncode != 0 or not result.stdout.strip():
        log.warning("`unflatten` returned no output; using unstaggered layout.")
        return dot_source
    return result.stdout.decode("utf-8", errors="replace")


def _split_plain(line: str) -> list[str]:
    """Split a `-Tplain` line, honouring double-quoted fields."""
    fields: list[str] = []
    current: list[str] = []
    in_quotes = False
    escaped = False
    # An empty quoted field is still a field. Without this, `""` produced no
    # column at all and silently shifted every column after it.
    quoted = False
    for char in line:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            in_quotes = not in_quotes
            quoted = True
        elif char.isspace() and not in_quotes:
            if current or quoted:
                fields.append("".join(current))
                current = []
                quoted = False
        else:
            current.append(char)
    if current or quoted:
        fields.append("".join(current))
    return fields


def _parse_plain_edge(
    fields: list[str],
    raw_edges: dict[tuple[str, str], list[list[tuple[float, float]]]],
) -> None:
    """Record one Graphviz edge, leaving malformed routes to draw.io."""
    try:
        count = int(fields[3])
        coords = [float(value) for value in fields[4 : 4 + count * 2]]
    except (ValueError, IndexError):
        return
    if len(coords) == count * 2:
        points = list(zip(coords[0::2], coords[1::2], strict=True))
        raw_edges.setdefault((fields[1], fields[2]), []).append(points)


def _parse_plain_records(
    plain: str,
) -> tuple[
    float,
    float,
    float,
    dict[str, tuple[float, float, float, float]],
    dict[tuple[str, str], list[list[tuple[float, float]]]],
]:
    """Read Graphviz plain records without applying coordinate transforms."""
    scale = 1.0
    graph_w = graph_h = 0.0
    raw: dict[str, tuple[float, float, float, float]] = {}
    raw_edges: dict[tuple[str, str], list[list[tuple[float, float]]]] = {}

    for line in plain.splitlines():
        fields = _split_plain(line.strip())
        if not fields:
            continue
        if fields[0] == "graph" and len(fields) >= 4:
            scale, graph_w, graph_h = (float(fields[1]), float(fields[2]), float(fields[3]))
        elif fields[0] == "node" and len(fields) >= 6:
            name, x, y, width, height = fields[1], *map(float, fields[2:6])
            raw[name] = (x, y, width, height)
        elif fields[0] == "edge" and len(fields) >= 4:
            _parse_plain_edge(fields, raw_edges)
        elif fields[0] == "stop":
            break

    return scale, graph_w, graph_h, raw, raw_edges


def parse_plain(plain: str) -> Layout:
    """Parse `-Tplain` into pixel-space positions.

    Graphviz emits inches with a bottom-left origin; draw.io wants pixels with
    a top-left origin, so y is flipped against the reported graph height.
    """
    scale, graph_w, graph_h, raw, raw_edges = _parse_plain_records(plain)

    nodes: dict[str, Placed] = {}
    for name, (x, y, w, h) in raw.items():
        # `scale` applies to every coordinate on the drawing, not only to the
        # canvas. Applying it to the canvas alone put draw.io shapes in the
        # wrong places relative to a page sized from the same numbers. Graphviz
        # emits 1.0 unless `size` or `ratio` forces a fit, and this renderer
        # sets neither, so today this is a latent difference rather than a
        # visible one. It is still wrong, and it would be invisible until
        # somebody added a `size` attribute.
        width = w * POINTS_PER_INCH * scale
        height = h * POINTS_PER_INCH * scale
        # x,y is the node centre; draw.io geometry is the top-left corner.
        nodes[name] = Placed(
            x=x * POINTS_PER_INCH * scale - width / 2.0,
            y=(graph_h - y) * POINTS_PER_INCH * scale - height / 2.0,
            width=width,
            height=height,
        )

    # Same transform as the nodes above, so a waypoint and a node centre agree.
    edges = {
        pair: [
            [
                (
                    x * POINTS_PER_INCH * scale,
                    (graph_h - y) * POINTS_PER_INCH * scale,
                )
                for x, y in route
            ]
            for route in routes
        ]
        for pair, routes in raw_edges.items()
    }

    return Layout(
        nodes=nodes,
        width=graph_w * POINTS_PER_INCH * scale,
        height=graph_h * POINTS_PER_INCH * scale,
        edges=edges,
    )


def compute_layout(dot_source: str, engine: str = "dot") -> Layout:
    plain = run_dot(dot_source, "plain", engine=engine).decode("utf-8", errors="replace")
    return parse_plain(plain)
