"""Device icons drawn here, with Pillow, rather than fetched from anywhere.

Ubiquiti's artwork is theirs, is fetched at runtime and cannot be shipped in
this repository. That leaves two cases drawing nothing but a Graphviz primitive:
`--icons builtin`, which is the deliberately network-free mode, and any device
in `--icons unifi` whose `sysid` is absent from the catalogue. A trapezium
labelled "Office AP" is readable but plainly geometric.

These are ours, so they need no network, raise no licensing question, and work
in both cases. `_render_cloud()` in `assets.py` proved the approach for the
Internet node; this is the same trick applied to the rest of the map.

Three constraints, each learned the hard way elsewhere in this project:

- **The silhouette carries the meaning, not the colour.** Everything here is a
  single-colour shape on transparency, and each outline is distinguishable from
  every other with the colour discarded. The accent palette is Okabe-Ito and the
  maintainer is deuteran colourblind, so an icon set that needed hue to be read
  would be the one place that promise broke.
- **Real aspect ratios.** A rack switch is wide and short and says so here.
  `IconAsset.display_size()` honours it, and forcing one into a square cell
  letterboxes it into a thin strip surrounded by dead space.
- **Cached per colour**, like the cloud, because a single shared file would put
  a dark icon on a dark canvas.

Interior detail is punched rather than overdrawn: the body is filled in *color*
and then features are drawn again in fully transparent pixels. `ImageDraw`
writes pixels rather than compositing, so that cuts holes, which is what makes
a switch's ports and a hollow guest body possible without a second colour.

Drawn oversized and downscaled, the same supersampling the cloud and the glyph
renderer use to keep curves and small features smooth.
"""

from __future__ import annotations

from pathlib import Path

# Every name this module can draw. Infrastructure is keyed by `Kind.value`;
# clients are keyed by `Node.glyph_name`, which is the same user/guest x
# wired/wireless split the console's own icon font encodes.
#
# Drawing all four client variants is the point rather than completeness: that
# font is served only by a controller and is nowhere in a support file, so it
# was the last reason a support-file user needed to touch a console at all.
INFRASTRUCTURE = ("gateway", "switch", "ap", "bridge", "unknown")
CLIENTS = ("user-wired", "user-wireless", "guest-wired", "guest-wireless")
NAMES = INFRASTRUCTURE + CLIENTS

# Height as a fraction of width. A switch is a rack unit; a phone is taller than
# it is wide. These are what stop every icon rendering as a square.
_ASPECT: dict[str, float] = {
    "gateway": 0.80,
    "switch": 0.30,
    "ap": 1.00,
    "bridge": 0.52,
    "unknown": 0.92,
    "user-wired": 0.88,
    "user-wireless": 1.35,
    "guest-wired": 0.88,
    "guest-wireless": 1.35,
}

_CLEAR = (0, 0, 0, 0)


def _rounded(draw, box: tuple[float, float, float, float], radius: float, fill) -> None:
    draw.rounded_rectangle([box[0], box[1], box[2], box[3]], radius=radius, fill=fill)


def _ports(draw, left: float, right: float, top: float, height: float, count: int) -> None:
    """A row of punched-out port squares, which is what reads as networking gear."""
    pitch = (right - left) / count
    inset = pitch * 0.24
    for i in range(count):
        x0 = left + i * pitch + inset
        draw.rectangle([x0, top, x0 + pitch - 2 * inset, top + height], fill=_CLEAR)


def _draw_gateway(draw, w: float, h: float, color: str) -> None:
    # A squarish console body: vent slot high, a row of ports low. Distinct from
    # the switch purely by proportion and by having one port row rather than two.
    _rounded(draw, (0.06 * w, 0.05 * h, 0.94 * w, 0.95 * h), 0.10 * w, color)
    _rounded(draw, (0.20 * w, 0.20 * h, 0.80 * w, 0.30 * h), 0.03 * w, _CLEAR)
    _ports(draw, 0.14 * w, 0.86 * w, 0.62 * h, 0.22 * h, 4)


def _draw_switch(draw, w: float, h: float, color: str) -> None:
    # Wide and short, with two staggered port rows: the shape of the thing.
    _rounded(draw, (0.02 * w, 0.10 * h, 0.98 * w, 0.90 * h), 0.03 * w, color)
    _ports(draw, 0.08 * w, 0.80 * w, 0.24 * h, 0.24 * h, 8)
    _ports(draw, 0.08 * w, 0.80 * w, 0.56 * h, 0.24 * h, 8)
    # The two SFP cages at the far end, which is why the rows stop at 0.80.
    _ports(draw, 0.84 * w, 0.96 * w, 0.38 * h, 0.28 * h, 2)


def _draw_ap(draw, w: float, h: float, color: str) -> None:
    # A disc with a punched ring: UniFi APs are round, and roundness alone
    # separates this from every boxy icon here at a glance.
    draw.ellipse([0.02 * w, 0.02 * h, 0.98 * w, 0.98 * h], fill=color)
    draw.ellipse([0.30 * w, 0.30 * h, 0.70 * w, 0.70 * h], fill=_CLEAR)
    draw.ellipse([0.44 * w, 0.44 * h, 0.56 * w, 0.56 * h], fill=color)


def _draw_bridge(draw, w: float, h: float, color: str) -> None:
    # Two bodies joined by a span. Says "link between two things" without
    # needing a label to disambiguate it from a switch.
    _rounded(draw, (0.02 * w, 0.12 * h, 0.34 * w, 0.88 * h), 0.05 * w, color)
    _rounded(draw, (0.66 * w, 0.12 * h, 0.98 * w, 0.88 * h), 0.05 * w, color)
    draw.rectangle([0.34 * w, 0.42 * h, 0.66 * w, 0.58 * h], fill=color)


def _draw_unknown(draw, w: float, h: float, color: str) -> None:
    # A hollow diamond, keeping continuity with the `diamond` primitive this
    # replaces so a reader who has seen both maps is not relearning anything.
    draw.polygon(
        [(0.5 * w, 0.02 * h), (0.98 * w, 0.5 * h), (0.5 * w, 0.98 * h), (0.02 * w, 0.5 * h)],
        fill=color,
    )
    draw.polygon(
        [(0.5 * w, 0.24 * h), (0.76 * w, 0.5 * h), (0.5 * w, 0.76 * h), (0.24 * w, 0.5 * h)],
        fill=_CLEAR,
    )


def _draw_wired_body(draw, w: float, h: float, color: str) -> None:
    """A monitor on a stand: the desktop-ish thing a wired client usually is."""
    _rounded(draw, (0.02 * w, 0.04 * h, 0.98 * w, 0.66 * h), 0.05 * w, color)
    draw.polygon(
        [(0.40 * w, 0.66 * h), (0.60 * w, 0.66 * h), (0.66 * w, 0.86 * h), (0.34 * w, 0.86 * h)],
        fill=color,
    )
    _rounded(draw, (0.20 * w, 0.86 * h, 0.80 * w, 0.98 * h), 0.04 * w, color)


def _draw_wireless_body(draw, w: float, h: float, color: str) -> None:
    """A handset under signal arcs. Taller than wide, unlike everything else."""
    # Arcs occupy the top third. Drawn as stroked arcs rather than filled
    # wedges so they read as signal at small sizes.
    stroke = max(1, int(0.07 * w))
    for radius in (0.44, 0.30, 0.16):
        draw.arc(
            [
                (0.5 - radius) * w,
                0.30 * h - radius * w,
                (0.5 + radius) * w,
                0.30 * h + radius * w,
            ],
            start=200,
            end=340,
            fill=color,
            width=stroke,
        )
    _rounded(draw, (0.28 * w, 0.38 * h, 0.72 * w, 0.98 * h), 0.07 * w, color)


def _hollow(draw, w: float, h: float, name: str) -> None:
    """Punch the body out, leaving a thick outline.

    This is how guest is distinguished from user, and it is deliberately a
    *shape* difference. Colour is never the only channel here, and guest is
    exactly the distinction somebody would reach for a second hue to carry.
    """
    if name.endswith("wired"):
        _rounded(draw, (0.14 * w, 0.16 * h, 0.86 * w, 0.54 * h), 0.03 * w, _CLEAR)
    else:
        _rounded(draw, (0.38 * w, 0.48 * h, 0.62 * w, 0.88 * h), 0.03 * w, _CLEAR)


_DRAW = {
    "gateway": _draw_gateway,
    "switch": _draw_switch,
    "ap": _draw_ap,
    "bridge": _draw_bridge,
    "unknown": _draw_unknown,
    "user-wired": _draw_wired_body,
    "guest-wired": _draw_wired_body,
    "user-wireless": _draw_wireless_body,
    "guest-wireless": _draw_wireless_body,
}


def render(name: str, color: str, dest: Path, box: int) -> tuple[int, int]:
    """Draw *name* in *color* into *dest*, returning its pixel size.

    Raises rather than falling back, exactly like `local_icon()`: the caller
    decides what an absent icon means, and silently substituting something else
    would make a wrong picture indistinguishable from a right one.
    """
    from PIL import Image, ImageDraw

    if name not in _DRAW:
        raise ValueError(f"no drawn icon named {name!r}; have {', '.join(sorted(_DRAW))}")

    scale = 4
    width = box * scale
    height = max(1, int(width * _ASPECT[name]))
    canvas = Image.new("RGBA", (width, height), _CLEAR)
    draw = ImageDraw.Draw(canvas)

    _DRAW[name](draw, width, height, color)
    if name.startswith("guest-"):
        _hollow(draw, width, height, name)

    cropped = canvas.crop(canvas.getbbox() or (0, 0, width, height))
    cropped.thumbnail((box, box), Image.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    cropped.save(dest, "PNG")
    return cropped.width, cropped.height
