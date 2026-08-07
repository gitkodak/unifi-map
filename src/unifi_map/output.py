"""Turning a rendered topology into files on disk.

Separate from `artwork.py` rather than folded in with it, because the two share
nothing: this module knows about paths, atomic replacement and overwrite
guards, and imports every renderer; that one knows about `AssetStore` and
imports none of them. One module holding both would be a bag of things that
happened to leave `cli.py` together.

Two rules run through everything here:

* **Nothing is overwritten unless this tool wrote it**, for the two formats a
  person plausibly hand-edits.
* **Every write is atomic.** An interrupt or a full disk leaves the previous
  good file rather than a truncated one.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from .assets import IconAsset
from .fsio import atomic_write, mkdir_private
from .layout import compute_layout, run_dot, stagger
from .model import Topology
from .progress import spinner
from .render_dot import Style
from .render_drawio import render_drawio
from .render_html import render_html
from .render_json import render_json
from .render_mermaid import render_mermaid
from .svg_post import inline_svg_images

log = logging.getLogger("unifi_map")


class OutputExistsError(RuntimeError):
    """Raised rather than overwrite a file this tool did not write."""


# Both editable formats carry this already: the DOT opens `digraph unifi` and
# the draw.io file opens `<mxfile host="unifi-map"`. Only the first few KiB are
# searched, which is where a header lives in either.
_PROVENANCE = ("unifi-map", "digraph unifi")


def safe_name(text: str) -> str:
    keep = [c if (c.isalnum() or c in "-_") else "-" for c in text]
    return "".join(keep).strip("-").lower() or "network"


def unique_names(names: list[str]) -> dict[str, str]:
    """Map each network name to a filename stem no other network shares.

    `safe_name` is not injective: "IoT A", "IoT-A" and "IoT/A" all become
    "iot-a". Written straight out, the second network overwrote the first, and
    silently, because the file it replaced carried this tool's own provenance
    marker and so passed the overwrite guard.

    Collisions get a short digest of the original name rather than a counter, so
    a given network keeps its filename whatever order the networks arrive in.
    """
    slugs: dict[str, list[str]] = {}
    for name in names:
        slugs.setdefault(safe_name(name), []).append(name)

    resolved: dict[str, str] = {}
    for slug, colliding in slugs.items():
        if len(colliding) == 1:
            resolved[colliding[0]] = slug
            continue
        for name in colliding:
            digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:6]
            resolved[name] = f"{slug}-{digest}"
    return resolved


def _is_ours(path: Path) -> bool:
    try:
        # Read 4 KiB, rather than reading the file and slicing 4 KiB off it.
        with path.open("rb") as handle:
            head = handle.read(4096).decode("utf-8", errors="replace")
    except OSError:
        # Unreadable is not proof it is ours, so treat it as somebody else's.
        return False
    return any(marker in head for marker in _PROVENANCE)


def write_output(path: Path, data: bytes | str, *, force: bool, guard: bool) -> None:
    """Write *data* to *path*, atomically, without eating anyone's work.

    Two separate problems, both real.

    *guard* is set for the formats a person plausibly hand-edits: `.drawio`,
    which is advertised as editable and is the whole point of that output, and
    `.dot`, which exists to be tweaked. Re-rendering must stay cheap, since
    `fetch` and `render` are split precisely so render can be run over and over,
    so this refuses only when the existing file carries none of our markers.
    Overwriting our own previous output needs no ceremony. The raster and PDF
    outputs are not guarded: nothing hand-authors those at exactly this path,
    and they carry nowhere convenient to put a marker.

    The write itself goes to a temporary file beside the target and is renamed
    over it, so an interrupt or a full disk leaves the previous good file in
    place rather than a truncated one. `os.replace` is atomic within a
    filesystem, and the temporary is created in the destination directory to
    guarantee that.

    Mode is set on the temporary *before* the rename, so the file is never
    briefly readable by others. Renders are as sensitive as the snapshot they
    came from: labels carry hostnames, addresses, VLAN names and the WAN
    address, and the SVG holds all of it as selectable text. `0600` restricts
    who can read it on this machine; it does not stop you sending it to anyone.
    """
    if guard and not force and path.exists() and not _is_ours(path):
        raise OutputExistsError(
            f"{path} was not written by unifi-map, so it is being left alone. "
            "Pass --force to overwrite it, or use --name or --out-dir to write "
            "somewhere else."
        )

    atomic_write(path, data)


# Formats Graphviz renders through cairo, which has no SVG loader.
_CAIRO_FORMATS = ("png", "pdf")


def warn_about_svg_artwork(icons: dict[str, IconAsset], formats: list[str]) -> None:
    """Say so when SVG artwork cannot survive into a requested format.

    Called once per run by the CLI, not from `write_outputs`. That runs once per
    network under `--per-network`, so warning there produced one identical line
    for the whole map and another for every network. This is a property of the
    run rather than of a file being written.

    Graphviz loads an SVG image only for its own `svg` output driver. There is
    no `svg:cairo` loadimage plugin, so `png` and `pdf` drop the image entirely,
    warn on stderr and exit 0. The node still draws, without its artwork, which
    looks like the override not working rather than like a format limitation.

    Warned here, before rendering, because Graphviz's own message names neither
    the file nor a way forward: it says `No loadimage plugin for "svg:cairo"`.

    Only reached when the SVG was not rasterised, which means the `svg` extra
    is not installed. With it, an SVG becomes a cached PNG and none of this
    applies, so the message leads with that rather than with the workaround.
    """
    svgs = sorted(
        a.path for a in icons.values() if a.path is not None and a.path.suffix.lower() == ".svg"
    )
    affected = [f for f in _CAIRO_FORMATS if f in formats]
    if not svgs or not affected:
        return
    log.warning(
        "%d SVG icon(s) will be missing from the %s output: Graphviz loads SVG "
        "artwork only for its own svg format, so cairo-backed formats drop it. "
        "The svg and drawio outputs are unaffected. Fix it for every format "
        "with `pip install 'unifi-map[svg]'`, which rasterises SVG artwork on "
        "the way in, or convert the file to PNG yourself: %s",
        len(svgs),
        " and ".join(affected),
        ", ".join(str(p) for p in svgs[:3]) + (", ..." if len(svgs) > 3 else ""),
    )


def _write_sized(path: Path, data: bytes | str, *, force: bool, guard: bool) -> None:
    """Write one output and log it with its size on disk.

    The size is measured in bytes for text as well as binary. Reporting
    `len(str)` counts characters, which understates any file holding non-ASCII,
    and a label carrying one is ordinary rather than exotic.
    """
    write_output(path, data, force=force, guard=guard)
    size = len(data.encode("utf-8") if isinstance(data, str) else data)
    log.info("  %s (%.1f KiB)", path, size / 1024)


def _write_rasters(
    dot_source: str,
    out_dir: Path,
    stem: str,
    formats: list[str],
    *,
    force: bool,
    progress: bool,
) -> None:
    """Render the formats Graphviz rasterises for us, in a fixed order.

    Split out of `write_outputs` to keep that function's branching flat. These
    two are the only outputs that are a plain `run_dot` of the same DOT with no
    post-processing, which is why they share a loop at all.

    The order is spelled out rather than reusing `_CAIRO_FORMATS`, which holds
    the same two names for a different reason and in the other order. Write
    order is observable in the log, so it is pinned here deliberately.
    """
    for fmt in ("pdf", "png"):
        if fmt not in formats:
            continue
        with spinner(f"Rendering {fmt}", progress):
            data = run_dot(dot_source, fmt)
        _write_sized(out_dir / f"{stem}.{fmt}", data, force=force, guard=False)


def write_outputs(
    dot_source: str,
    topo: Topology,
    out_dir: Path,
    stem: str,
    formats: list[str],
    style: Style,
    icons: dict[str, IconAsset],
    stagger_depth: int = 0,
    force: bool = False,
    progress: bool = True,
    title: str = "",
) -> None:
    mkdir_private(out_dir)

    # Every icon this render used, and nothing else, may be embedded.
    icon_paths = {asset.path for asset in icons.values() if asset.path is not None}

    # An empty title means "no title" to the renderers that take an optional
    # one. Resolved once so the two call sites cannot drift apart.
    opt_title = title or None

    # Stagger once, up front, so the SVG/PDF and the draw.io coordinates are
    # computed from byte-identical DOT and therefore agree exactly.
    dot_source = stagger(dot_source, stagger_depth)

    if "dot" in formats:
        path = out_dir / f"{stem}.dot"
        write_output(path, dot_source, force=force, guard=True)
        log.info("  %s", path)

    # `html` needs the same inlined SVG as `-f svg` even when svg itself was
    # not requested, so the two share one render rather than the html branch
    # below re-deriving it. Only "svg" in *formats* controls whether the
    # `.svg` file itself gets written.
    svg_data = b""
    if "svg" in formats or "html" in formats:
        with spinner("Rendering svg", progress):
            svg_data = run_dot(dot_source, "svg")
        # Graphviz references artwork by filesystem path; inline it so the
        # SVG is a single portable file.
        svg_data = inline_svg_images(svg_data, allowed=icon_paths)
        if "svg" in formats:
            _write_sized(out_dir / f"{stem}.svg", svg_data, force=force, guard=False)

    _write_rasters(dot_source, out_dir, stem, formats, force=force, progress=progress)

    if "html" in formats:
        # Not hand-edited, same as svg/pdf/png: a generated artifact, not
        # something re-rendering must avoid clobbering.
        page = render_html(topo, svg_data.decode("utf-8"), style.theme, opt_title)
        _write_sized(out_dir / f"{stem}.html", page, force=force, guard=False)

    if "mermaid" in formats:
        # No Graphviz involved: Mermaid does its own layout, so the staggered
        # DOT above has nothing to contribute here.
        path = out_dir / f"{stem}.mmd"
        write_output(
            path,
            render_mermaid(topo, title, "TB" if style.layout == "tree" else "LR"),
            force=force,
            guard=False,
        )
        log.info("  %s", path)

    if "json" in formats:
        # Like mermaid, no Graphviz involved: this is the model, not a drawing.
        path = out_dir / f"{stem}.json"
        write_output(path, render_json(topo, opt_title), force=force, guard=False)
        log.info("  %s", path)

    if "drawio" in formats:
        layout = compute_layout(dot_source)
        xml = render_drawio(topo, layout, stem, style.theme, icons, style.transparent)
        _write_sized(out_dir / f"{stem}.drawio", xml, force=force, guard=True)
