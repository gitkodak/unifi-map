#!/usr/bin/env python3
"""Regenerate the demo images committed under `docs/images/`.

These are in the README, so they go stale silently: a rendering change makes
every committed screenshot wrong and nothing fails. Both of the full-map images
had already drifted far enough to be noticeably the wrong shape by the time this
script was written. Run `make demo-images` after anything that changes how the
map is drawn.

Four images, all from `examples/demo/` so no controller is involved:

    example-unifi-dark.png        the default layout
    example-tree-dark.png         the readable layout
    example-overrides-dark.png    the example overrides applied
    example-overrides-detail.png  a crop of the above

Plus two committed copies of the interactive viewer:

    docs/demo-light.html
    docs/demo-dark.html

**These two are `--icons builtin --offline` on purpose, unlike the PNGs
above.** A PNG is a flattened raster; whatever product photography went into
drawing it cannot be pulled back out. `-f html` is the opposite: it embeds
every icon as a separately extractable base64 image, byte-identical to
whatever was fetched. Committing that with the default `--icons unifi` would
mean committing verbatim, re-extractable copies of Ubiquiti's product
photography into git history, which is exactly what this project never does
with their artwork elsewhere. `builtin` draws every icon itself, so there is
nothing Ubiquiti made anywhere in the file, and `--offline` makes the two
reproducible on a clean clone with no cache and no network, which the PNGs
above are explicitly not.

**These are not reproducible on a clean clone, and that is not fixable here.**
The demo *data* is committed, but the artwork is not: product renders come from
Ubiquiti's CDN, and the generic client glyphs come from an icon font that only a
controller serves. Regenerating on a machine without `cache/assets/ubnt-icon.ttf`
produces the same maps with our own drawn client icons where the glyphs are. That is why the
README caption says what the glyphs need rather than implying every reader sees
them.

`example-obfuscated-dark.png` is deliberately not here. It comes from a real
network and cannot be regenerated from anything in this repository.

The crop is the interesting part. Cropping to fixed pixel fractions would break
the moment Graphviz moved anything, and it would break *silently*, producing a
picture of the wrong corner of the map. Instead the crop box is computed from
the same layout that produced the PNG: find every asserted node and every
endpoint of an asserted edge, take their bounding box, pad it. If an override is
added to the demo the crop follows it, and if the layout shifts the crop shifts
with it.

That works because `_write_outputs()` staggers once and writes the *same* DOT it
renders from, so positions parsed out of the written `.dot` are the positions in
the PNG. `tests/test_render.py::TestStaggerIsAppliedOnceToBothRenderers` is what
keeps that true.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "demo"
OVERRIDES = DEMO / "overrides.toml"
IMAGES = ROOT / "docs" / "images"
DOCS = ROOT / "docs"

# Space left around the cropped region, in layout points. Enough that labels
# under the lowest node are not sheared off.
CROP_PADDING = 38.0

# The date stamped into the committed screenshots. Any fixed value would do;
# this is the day the images were last deliberately regenerated. Bump it when
# they are redone for a real reason, not otherwise.
SOURCE_DATE_EPOCH = "1785672000"

# Dark first: it is what the README shows. `light` is the tool's default and is
# generated so the docs can show both rather than describe one.
THEMES = ("dark", "light")

sys.path.insert(0, str(ROOT / "src"))


def _render(
    name: str, theme: str, *extra: str, formats: str = "png", out_dir: Path = IMAGES
) -> None:
    """Render one image through the CLI, so this uses the documented path."""
    command = [
        sys.executable,
        "-m",
        "unifi_map",
        "--cache-dir",
        str(DEMO),
        "--out-dir",
        str(out_dir),
        "--no-progress",
        "render",
        "-f",
        *formats.split(),
        "--theme",
        theme,
        "--name",
        name,
        *extra,
    ]
    # Fixed clock, so regenerating produces the same bytes. Without it the
    # title block stamps the current time and every run is a diff.
    environment = {**os.environ, "SOURCE_DATE_EPOCH": SOURCE_DATE_EPOCH}
    subprocess.run(command, check=True, cwd=ROOT, env=environment)


def _crop_box(dot_path: Path, image: Image.Image) -> tuple[int, int, int, int]:
    """The region holding everything the overrides asserted.

    Derived from the layout rather than guessed, so it tracks the data.
    """
    from unifi_map.client import Snapshot
    from unifi_map.layout import compute_layout
    from unifi_map.model import build_topology
    from unifi_map.overrides import apply as apply_overrides
    from unifi_map.overrides import load as load_overrides
    from unifi_map.render_dot import _node_id

    topo = build_topology(Snapshot.read(DEMO), include_offline=False)
    topo = apply_overrides(topo, load_overrides(OVERRIDES)).topology

    wanted = {node.id for node in topo.nodes.values() if node.asserted}
    for edge in topo.edges:
        if edge.asserted:
            wanted.update((edge.src, edge.dst))
    if not wanted:
        raise SystemExit("No asserted nodes or edges in the demo overrides; nothing to crop to.")

    layout = compute_layout(dot_path.read_text(encoding="utf-8"))
    # `_node_id` returns the quoted form used in DOT source; layout keys are bare.
    placed = [layout.nodes[key] for i in wanted if (key := _node_id(i).strip('"')) in layout.nodes]
    if not placed:
        raise SystemExit("Asserted nodes are missing from the layout; did node ids change?")

    left = min(p.x for p in placed) - CROP_PADDING
    top = min(p.y for p in placed) - CROP_PADDING
    right = max(p.x + p.width for p in placed) + CROP_PADDING
    bottom = max(p.y + p.height for p in placed) + CROP_PADDING

    # Layout is in points, the PNG in pixels, and Graphviz picks the scale.
    scale_x = image.width / layout.width
    scale_y = image.height / layout.height
    return (
        max(0, int(left * scale_x)),
        max(0, int(top * scale_y)),
        min(image.width, int(right * scale_x)),
        min(image.height, int(bottom * scale_y)),
    )


def main() -> int:
    IMAGES.mkdir(parents=True, exist_ok=True)

    # Both themes, every image. The README shows the dark ones because they
    # read better against its own page, but `--theme light` is the default, so
    # a reader running the tool unmodified should be able to see what they will
    # actually get rather than inferring it.
    for theme in THEMES:
        _render(f"example-unifi-{theme}", theme)
        _render(f"example-tree-{theme}", theme, "--layout", "tree", "--title", "Demo network")
        _render(
            f"example-overrides-{theme}",
            theme,
            "--overrides",
            str(OVERRIDES),
            "--title",
            "Demo network, with overrides",
            formats="png dot",
        )

        # Cropped from this theme's own render rather than one of them: the
        # layout is identical between themes, but reusing one theme's crop box
        # would silently depend on that staying true.
        dot_path = IMAGES / f"example-overrides-{theme}.dot"
        full = IMAGES / f"example-overrides-{theme}.png"
        with Image.open(full) as image:
            box = _crop_box(dot_path, image)
            image.crop(box).save(IMAGES / f"example-overrides-detail-{theme}.png")
        # The .dot was only a means of getting coordinates; committing it would
        # be a second copy of the map that nothing reads.
        dot_path.unlink()

    for path in sorted(IMAGES.glob("example-*.png")):
        with Image.open(path) as image:
            print(f"  {path.relative_to(ROOT)}  {image.width}x{image.height}")

    # builtin + offline: see the module docstring for why these two, alone
    # among everything this script generates, must never carry --icons unifi.
    for theme in ("light", "dark"):
        _render(
            f"demo-{theme}",
            theme,
            "--icons",
            "builtin",
            "--offline",
            "--title",
            "Demo network",
            formats="html",
            out_dir=DOCS,
        )
        path = DOCS / f"demo-{theme}.html"
        print(f"  {path.relative_to(ROOT)}  {path.stat().st_size / 1024:.1f} KiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
