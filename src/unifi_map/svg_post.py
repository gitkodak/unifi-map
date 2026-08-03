"""Make Graphviz SVG output self-contained.

Graphviz can only read an `<IMG SRC=...>` from the filesystem, so the SVG it
emits references artwork by absolute path. That file is fine locally but breaks
the moment the SVG is moved, emailed or opened on another machine. Rewriting
each reference into a base64 data URI makes the diagram a single portable file.
"""

from __future__ import annotations

import base64
import logging
import re
from collections.abc import Iterable
from pathlib import Path

log = logging.getLogger(__name__)

# Matches xlink:href="..." and href="..." on <image> elements.
#
# Every image extension, not just PNG. Looked-up artwork is always PNG, but an
# `icon` in an overrides file can be anything Graphviz will load, and SVG is
# documented as working. Matching only PNG left those as absolute filesystem
# paths in the output, which is the exact disclosure this function exists to
# prevent: the path usually contains a username.
_HREF = re.compile(
    rb'(?P<attr>(?:xlink:)?href=")(?P<path>[^"]+\.(?:png|svg|jpe?g|gif|webp))(?P<tail>")',
    re.IGNORECASE,
)


def inline_svg_images(svg: bytes, allowed: Iterable[Path] = ()) -> bytes:
    """Replace on-disk PNG references in *svg* with base64 data URIs.

    *allowed* is the exact set of files that may be embedded, which is every
    icon this render actually used. Naming files rather than a directory keeps
    a crafted device name from pulling in anything else, and lets artwork the
    user supplied from their own folder be embedded alongside cached artwork.

    A reference left as a filesystem path is not merely unportable: it discloses
    a local path, which usually contains a username.
    """
    cache: dict[bytes, bytes] = {}
    permitted = {p.resolve() for p in allowed}

    def replace(match: re.Match[bytes]) -> bytes:
        raw = match.group("path")
        if raw.startswith(b"data:"):
            return match.group(0)
        if raw in cache:
            return match.group("attr") + cache[raw] + match.group("tail")

        try:
            path = Path(raw.decode("utf-8")).resolve()
        except (UnicodeDecodeError, OSError):
            return match.group(0)

        if path not in permitted:
            log.warning(
                "Not embedding %s: it is not one of this render's icons. The SVG "
                "will reference it by path rather than carrying it.",
                path,
            )
            return match.group(0)
        if not path.is_file():
            return match.group(0)

        encoded = base64.b64encode(path.read_bytes())
        uri = b"data:image/png;base64," + encoded
        cache[raw] = uri
        return match.group("attr") + uri + match.group("tail")

    return _HREF.sub(replace, svg)
