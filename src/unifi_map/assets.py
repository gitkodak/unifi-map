"""Fetch real UniFi product artwork and cache it locally.

Where these come from
---------------------
**Not the controller.** Network application 10.5.67 serves no device imagery
locally: every path under ``/proxy/network/manage/angular/<hash>/`` that could
plausibly hold device PNGs returns the SPA's HTML 404 fallback. The web UI pulls
its artwork from Ubiquiti's public CDN, and so do we.

- Catalog: ``https://static.ui.com/fingerprint/ui/public.json`` (~700 KB, 680
  devices), the same hardware database the UI uses.
- Artwork: ``.../images/{id}/{variant}/{hash}.png``, where the ``topology``
  variant is the render UniFi itself uses in its topology view.

Devices are matched on **sysid**, not model name: the controller's ``model``
string does not reliably match the catalog's ``shortnames`` (a USW Pro HD 24 PoE
reports ``USWED72`` while the catalog calls it ``USPH24P``). Catalog sysids are
hex strings and the controller reports a decimal int; all 1178 catalog values
are unambiguously hex, so strict base-16 parsing is correct.

Everything degrades: no network, no Pillow, or an unknown device all fall back to
the plain shape renderer rather than failing the run.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import logging
import math
import re
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from . import drawn
from .fsio import atomic_write, mkdir_private

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Fetched:
    """The parts of a response callers here actually use.

    `_fetch` used to hand back a `requests.Response` with `_content` and
    `_content_consumed` assigned by hand, because the body is streamed and read
    through a cap rather than by `requests` itself. That worked, and depended on
    two private attributes of somebody else's library staying where they are.

    Callers only ever touch `status_code`, `content` and `raise_for_status`, so
    those are all this carries.
    """

    status_code: int
    content: bytes
    url: str

    def raise_for_status(self) -> None:
        """Match `requests` closely enough that existing handlers still catch it."""
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} for {self.url}")


def _cache_write(path: Path, data: bytes) -> None:
    """Atomic, but without the fsync: artwork is refetchable, so paying for
    durability on every icon would be a cost with nothing behind it."""
    atomic_write(path, data, mode=0o644, fsync=False)


CATALOG_URL = "https://static.ui.com/fingerprint/ui/public.json"

# Filenames for the controller-sourced icon font, written by `fetch`.
FONT_FILE = "ubnt-icon.ttf"
FONT_MAP_FILE = "ubnt-icon.json"

# The generic client glyphs. UniFi picks one of exactly these four by CSS class
# for any client it has no product artwork for, so they are the whole of the
# fallback. They live in a custom icon font that only a controller serves; there
# is no published copy, which is why obtaining it is a deliberate step.
CLIENT_GLYPHS = ("user-wired", "user-wireless", "guest-wired", "guest-wireless")
_GLYPH_RULE = r"ubnt-icon--{name}[^{{]*\{{[^}}]*content:\s*\"\\([0-9a-fA-F]+)\""


def parse_glyph_codepoints(css: str) -> dict[str, int]:
    """Codepoints for the client glyphs, read from the icon font's stylesheet.

    Shared by the controller fetch and by loading a copy from disk, so both
    routes agree on what a glyph is.
    """
    codepoints: dict[str, int] = {}
    for name in CLIENT_GLYPHS:
        match = re.search(_GLYPH_RULE.format(name=name), css)
        if match:
            codepoints[name] = int(match.group(1), 16)
        else:
            log.warning("Glyph %s not found in the icon font stylesheet.", name)
    return codepoints


def read_icon_font_dir(path: Path) -> tuple[bytes, dict[str, int]]:
    """Load an icon font copied off a controller by hand.

    *path* is a directory holding the font's `style.css` and its `.ttf`, in any
    arrangement: the controller's own `ubnt-icon` directory works as-is, and so
    does a folder someone dropped both files into. This is the route that needs
    neither credentials nor a network, for people who will not point this tool
    at a console but can still copy two files off one.

    Raises `AssetError` with a specific reason, because a silent fallback here
    would look identical to the glyphs simply not working.
    """
    if not path.is_dir():
        raise AssetError(f"{path} is not a directory.")

    css_files = sorted(path.rglob("*.css"))
    fonts = sorted(path.rglob("*.ttf"))
    if not css_files:
        raise AssetError(
            f"No stylesheet under {path}. The glyph codepoints live in the "
            "font's style.css, so that file is needed as well as the .ttf."
        )
    if not fonts:
        raise AssetError(f"No .ttf font under {path}.")

    codepoints: dict[str, int] = {}
    for css in css_files:
        codepoints = parse_glyph_codepoints(css.read_text(encoding="utf-8", errors="replace"))
        if codepoints:
            break
    if not codepoints:
        raise AssetError(
            f"Found no client glyph codepoints in the stylesheets under {path}. "
            'Expected rules like `.ubnt-icon--user-wired:before {content: "\\e8a1"}`.'
        )
    return fonts[0].read_bytes(), codepoints


IMAGE_URL = "https://static.ui.com/fingerprint/ui/images/{id}/{variant}/{hash}.png"

# Client artwork, keyed by the fingerprint dev_id that stat/sta already reports.
# This is `staticFingerprintOld` in the Network UI's config, and it is what the
# topology view actually renders for clients: real product artwork, not glyphs.
# Only these three sizes exist; anything else 302s to ui.com.
CLIENT_ICON_URL = "https://static.ui.com/fingerprint/0/{dev_id}_{size}.png"
CLIENT_ICON_SIZES = ("257x257", "129x129", "101x101")

# The client fingerprint database: dev_id to product name, family and vendor.
# Published alongside the icons, so it needs no controller and no credentials.
# The controller serves its own copy at v2/api/fingerprint_devices/0, but this
# is the same data and was a superset when compared, which is what allows
# `--support-file` to resolve client artwork without connecting to a console.
# Found in a support file's own logs; both static.ui.com and the older
# static.ubnt.com serve it identically.
CLIENT_CATALOG_URL = "https://static.ui.com/fingerprint/0/devicelist.json"

# ISP brand marks, keyed purely on the autonomous system number that
# `stat/health` already reports. The console's own speed-test daemon logs the
# URL it builds for this as `ispImg`, which is how the pattern was found after
# a long search through the web bundles turned up nothing. Largest first;
# unlike the fingerprint paths, a missing ASN or size returns a real 404.
ISP_LOGO_URL = "https://static.ui.com/asn/{asn}_{size}.png"
ISP_LOGO_SIZES = ("257x257", "129x129", "101x101", "51x51", "25x25")

# Preference order. `topology` is what the UniFi topology view uses; the others
# are fallbacks for hardware that lacks it.
VARIANTS = ("topology", "nopadding", "default")

# Product renders are 1-2 MB each. Downscaling keeps an embedded diagram in the
# low hundreds of KB instead of tens of MB.
ICON_PX = 256

# An icon is a few hundred KB. Anything past this is not artwork, whether it is
# a hostile CDN response or a user pointing --icons at the wrong file.
MAX_ASSET_BYTES = 16 * 1024 * 1024

# The published client fingerprint database is about 1 MB. This is generous
# enough not to break on growth and small enough that a hostile or wrong
# response cannot be read into memory unbounded, which it previously could:
# this download had no cap at all.
MAX_CATALOG_BYTES = 64 * 1024 * 1024


def _read_capped(response: requests.Response, limit: int) -> bytes | None:
    """Body bytes, or None once *limit* is passed.

    Reads in chunks and stops at the cap rather than measuring afterwards, so an
    oversized or endless response is abandoned instead of buffered whole.
    """
    chunks: list[bytes] = []
    total = 0
    try:
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > limit:
                response.close()
                return None
            chunks.append(chunk)
    except requests.RequestException:
        response.close()
        return None
    return b"".join(chunks)


# Pillow's own decompression-bomb threshold is deliberately generous, because it
# has to serve people processing real photographs. Ours only ever opens icons,
# so a far tighter ceiling costs nothing and turns a memory-exhaustion image
# into an ordinary error. 40 megapixels is roughly 600x the largest icon seen.
MAX_IMAGE_PIXELS = 40_000_000


class AssetError(RuntimeError):
    """Raised only for unrecoverable local problems, never for network failures."""


def describe_network_error(exc: BaseException) -> str:
    """A short, plain explanation of a failed request.

    `requests` wraps `urllib3` which wraps the underlying socket error, so
    `str(exc)` is a three-layer nested repr, complete with an object address,
    that runs well past a terminal width. It buries the one fact the reader
    needs, which is which of a handful of ordinary things went wrong.

    Matching partly on message text is unavoidable because urllib3 does not
    expose these distinctly, but this only ever produces a message, and an
    unrecognised error still yields something short.
    """
    if isinstance(exc, requests.exceptions.SSLError):
        return "TLS verification failed"
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return "timed out connecting"
    if isinstance(exc, requests.exceptions.ReadTimeout):
        return "timed out waiting for a reply"
    if isinstance(exc, requests.exceptions.Timeout):
        return "timed out"
    if isinstance(exc, requests.exceptions.ConnectionError):
        text = str(exc).lower()
        if "nameresolution" in text or "name or service not known" in text:
            return "the name could not be resolved"
        if "nodename nor servname" in text or "temporary failure in name resolution" in text:
            return "the name could not be resolved"
        if "refused" in text:
            return "the connection was refused"
        if "no route to host" in text:
            return "there is no route to that host"
        if "network is unreachable" in text:
            return "the network is unreachable"
        return "the connection failed"
    if isinstance(exc, ValueError):
        return "the reply was not valid JSON"
    return type(exc).__name__


def _normalise(text: Any) -> str:
    """Lowercase alphanumerics only, so "g3-flex" and "UVC G3 Flex" compare."""
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def _to_int(value: Any, base: int) -> int | None:
    try:
        return int(str(value).strip(), base)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class IconAsset:
    """A cached artwork file and its pixel dimensions.

    Dimensions travel with the path so renderers can size a cell to the real
    aspect ratio without depending on Pillow themselves. Rack switches are wide
    and short; forcing them into a square cell letterboxes them into a thin
    strip surrounded by dead space.
    """

    path: Path
    width: int
    height: int

    def display_size(self, box_w: float, box_h: float) -> tuple[int, int]:
        """Fit inside the box, preserving aspect ratio."""
        if self.width <= 0 or self.height <= 0:
            return int(box_w), int(box_h)
        scale = min(box_w / self.width, box_h / self.height)
        return max(1, round(self.width * scale)), max(1, round(self.height * scale))


@dataclass
class AssetStore:
    """Local cache of the device catalog and downscaled artwork.

    Deliberately separate from the controller-snapshot cache: a snapshot can be
    read from anywhere (a demo dataset shipped in the repo, say) without
    downloaded artwork landing next to it.
    """

    cache_dir: Path
    offline: bool = False
    timeout: float = 30.0
    _catalog: dict[int, dict[str, Any]] | None = None
    # Tripped by the first transport-level failure. A map of any size asks for
    # a lot of artwork, so without this a render against an unreachable CDN
    # retries once per icon: 117 requests on a 48-client network, each waiting
    # out its own timeout, which is the better part of an hour of apparent
    # hanging. One failure is enough to know the rest will fail too.
    _unreachable: bool = False

    def _fetch(self, url: str, *, allow_redirects: bool = True) -> Fetched | None:
        """GET *url*, or None if artwork is unavailable for any reason.

        Transport failures trip `_unreachable` so the rest of the run stops
        trying. An HTTP status is *not* a transport failure: a 404 means this
        one asset is missing, which says nothing about the next one.
        """
        if self.offline or self._unreachable:
            return None
        try:
            # Streamed, so an oversized body is never fully resident. Checking
            # `response.content` after a plain get() is a cap that only reports
            # what already happened: the bytes are in memory by the time it runs,
            # and Content-Length is supplied by the server and may simply lie.
            response = requests.get(
                url, timeout=self.timeout, allow_redirects=allow_redirects, stream=True
            )
            declared = response.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > MAX_ASSET_BYTES:
                log.warning("%s claims %s bytes; refusing to read it as artwork.", url, declared)
                response.close()
                return None
            body = _read_capped(response, MAX_ASSET_BYTES)
            if body is None:
                log.warning("%s is larger than %d bytes; not artwork.", url, MAX_ASSET_BYTES)
                return None
            return Fetched(status_code=response.status_code, content=body, url=url)
        except requests.RequestException as exc:
            self._unreachable = True
            log.warning(
                "Cannot reach Ubiquiti's asset CDN: %s. Continuing with our own "
                "icons instead of product artwork. Re-run when you have "
                "connectivity, or pass --offline to skip the attempt.",
                describe_network_error(exc),
            )
            return None

    @property
    def catalog_path(self) -> Path:
        return self.cache_dir / "ui-device-catalog.json"

    @property
    def icon_dir(self) -> Path:
        return self.cache_dir / "icons"

    @property
    def font_path(self) -> Path:
        return self.cache_dir / FONT_FILE

    @property
    def font_map_path(self) -> Path:
        return self.cache_dir / FONT_MAP_FILE

    @property
    def fingerprint_db_path(self) -> Path:
        return self.cache_dir / "client-fingerprints.json"

    def save_icon_font(self, font: bytes, codepoints: dict[str, int]) -> None:
        """Cache the controller's icon font. Never vendored into the repo."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        _cache_write(self.font_path, font)
        _cache_write(self.font_map_path, json.dumps(codepoints, indent=2).encode("utf-8"))

    def save_fingerprint_db(self, payload: Any) -> None:
        """Cache the controller's client fingerprint database.

        Kept in the asset cache rather than the snapshot because it describes
        Ubiquiti's catalogue, not this network, and outlives any one snapshot.
        A support file does not contain it, so having it here is what lets a
        support file resolve client artwork at all. Like all artwork, it is
        Ubiquiti's data: cached at runtime, never vendored.
        """
        if not isinstance(payload, dict) or not payload.get("dev_ids"):
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        _cache_write(self.fingerprint_db_path, json.dumps(payload).encode("utf-8"))

    def _cached_fingerprint_db(self) -> dict[str, Any] | None:
        if not self.fingerprint_db_path.is_file():
            return None
        try:
            payload = json.loads(self.fingerprint_db_path.read_text(encoding="utf-8"))
        except ValueError:
            return None
        return payload if isinstance(payload, dict) and payload.get("dev_ids") else None

    def fingerprint_db(self, download: bool = False) -> dict[str, Any] | None:
        """The client fingerprint database, from cache or Ubiquiti's CDN.

        Ubiquiti publish this at `CLIENT_CATALOG_URL`, so it needs no controller
        and no credentials. The published copy is a superset of what a
        controller serves: 5809 entries against 5789 when compared, containing
        every id the controller had.

        **`download` defaults to False deliberately.** The reason to read a
        support file is often that you do not want this tool talking to
        anything, and reaching out to a CDN unasked would quietly break that.
        Reading an existing cache is always permitted, because it touches no
        network.
        """
        cached = self._cached_fingerprint_db()
        if cached is not None or not download or self.offline:
            return cached

        try:
            response = requests.get(CLIENT_CATALOG_URL, timeout=self.timeout, stream=True)
            response.raise_for_status()
            body = _read_capped(response, MAX_CATALOG_BYTES)
            if body is None:
                log.warning(
                    "The client fingerprint database is larger than %d bytes; "
                    "refusing it and disabling client artwork.",
                    MAX_CATALOG_BYTES,
                )
                return None
            payload = json.loads(body)
        except (requests.RequestException, ValueError) as exc:
            log.warning(
                "Could not fetch the client fingerprint database (%s); client artwork disabled.",
                exc,
            )
            return None

        if not isinstance(payload, dict) or not payload.get("dev_ids"):
            return None
        self.save_fingerprint_db(payload)
        return payload

    def glyph_codepoints(self) -> dict[str, int]:
        if not self.font_map_path.is_file():
            return {}
        try:
            raw = json.loads(self.font_map_path.read_text(encoding="utf-8"))
        except ValueError:
            return {}
        # A cached map is just a file on disk and may be corrupt or hand-edited,
        # so a non-numeric value drops that glyph rather than raising ValueError
        # from under the CLI.
        codepoints: dict[str, int] = {}
        for key, value in raw.items():
            point = _to_int(value, 10) if not isinstance(value, int) else value
            if point is not None:
                codepoints[str(key)] = point
        return codepoints

    def isp_logo(self, asn: int | None) -> IconAsset | None:
        """The upstream provider's brand mark, keyed on its ASN.

        The console shows one beside each WAN, and derives it from the ASN alone:
        its speed-test daemon logs the URL it builds, `ispImg`, verbatim. So a
        single number from `stat/health` is the whole lookup, with no table to
        maintain and nothing provider-specific in this code.

        Unlike the fingerprint paths on the same host, a missing ASN really does
        404 here, so absence is distinguishable from a wrong guess.
        """
        if asn is None:
            return None

        cached = self.icon_dir / f"isp-{asn}-{ICON_PX}.png"
        if cached.is_file():
            return _measure(cached)
        if self.offline:
            return None

        for size in ISP_LOGO_SIZES:
            url = ISP_LOGO_URL.format(asn=asn, size=size)
            response = self._fetch(url, allow_redirects=False)
            if response is None:
                return None
            if response.status_code != 200 or not response.content:
                continue
            self.icon_dir.mkdir(parents=True, exist_ok=True)
            try:
                return _downscale(response.content, cached, ICON_PX)
            except AssetError as exc:
                log.warning("%s", exc)
                return None

        # Plenty of providers will simply not have one.
        log.debug("No brand mark for ASN %s.", asn)
        return None

    def internet_icon(self, color: str) -> IconAsset | None:
        """A generic cloud for the Internet node, drawn locally.

        Used when there is no provider brand mark to draw: an ASN Ubiquiti have
        no logo for, or a map that has been obfuscated on purpose. Needs no
        network, because nothing is fetched.

        *color* should be the theme's muted text colour, so the cloud tracks the
        theme rather than being pinned to one background. Measured at 5.8:1 on
        light and 8.4:1 on dark, both past WCAG AA for graphics, and it is a
        luminance difference rather than a hue one so it survives greyscale and
        colour blindness. Each colour caches to its own file; sharing one would
        leave a dark cloud on a dark canvas.
        """
        cached = self.icon_dir / f"internet-{color.lstrip('#')}-{ICON_PX}.png"
        if cached.is_file():
            return _measure(cached)
        try:
            return _render_cloud(color, cached, ICON_PX)
        except (AssetError, OSError, ValueError):
            # No Pillow, or a bad colour: fall back to the shape renderer.
            log.debug("Could not draw the Internet icon.", exc_info=True)
            return None

    def drawn_icon(self, name: str, color: str) -> IconAsset | None:
        """One of our own device icons, drawn locally. Never fetches anything.

        Used in two places: `--icons builtin`, which is the network-free mode
        and previously drew nothing but Graphviz primitives, and as the fallback
        inside `--icons unifi` when hardware is absent from Ubiquiti's
        catalogue. The second is a small, deliberate step away from "`unifi`
        shows exactly what the console shows", taken because a drawn access
        point beats a trapezium either way.

        *color* should be the theme's muted text colour, as the cloud uses, so
        the icon tracks the theme. Each colour caches separately; sharing one
        file would leave a dark icon on a dark canvas.

        Returns None rather than raising if Pillow is missing or the colour is
        unusable, because artwork must always degrade to the shape renderer
        rather than failing a run.
        """
        cached = self.icon_dir / f"drawn-{name}-{color.lstrip('#')}-{ICON_PX}.png"
        if cached.is_file():
            return _measure(cached)
        try:
            width, height = drawn.render(name, color, cached, ICON_PX)
        except (ImportError, OSError, ValueError):
            log.debug("Could not draw the %s icon.", name, exc_info=True)
            return None
        return IconAsset(path=cached, width=width, height=height)

    def client_icon(self, dev_id: int | None) -> IconAsset | None:
        """Real product artwork for a fingerprinted client.

        The fingerprint is Ubiquiti's and is sometimes plain wrong (a phone
        identified as an appliance). That is a data problem to fix with
        overrides, not a reason to draw something generic instead.
        """
        if dev_id is None:
            return None

        cached = self.icon_dir / f"client-{dev_id}-{ICON_PX}.png"
        if cached.is_file():
            return _measure(cached)
        if self.offline:
            return None

        for size in CLIENT_ICON_SIZES:
            url = CLIENT_ICON_URL.format(dev_id=dev_id, size=size)
            response = self._fetch(url, allow_redirects=False)
            if response is None:
                return None
            # A missing size 302s to ui.com rather than 404ing, so a redirect
            # means "not available", not "follow me".
            if response.status_code != 200 or not response.content:
                continue
            self.icon_dir.mkdir(parents=True, exist_ok=True)
            try:
                return _downscale(response.content, cached, ICON_PX)
            except AssetError as exc:
                log.warning("%s", exc)
                return None

        log.debug("No artwork for client dev_id %s.", dev_id)
        return None

    def client_glyph(self, name: str, color: str) -> IconAsset | None:
        """Rasterize one of UniFi's client glyphs from its own icon font.

        UniFi picks a client icon by CSS class, not by device type: its
        `getIconClassName` resolves every client to one of user/guest x
        wired/wireless. Rendering that same font glyph is therefore the actual
        artwork the UI shows, not an approximation of it.

        The font comes from the controller and is cached; it is deliberately not
        shipped in this repository.
        """
        codepoints = self.glyph_codepoints()
        codepoint = codepoints.get(name)
        if codepoint is None or not self.font_path.is_file():
            return None

        safe = color.lstrip("#").lower()
        cached = self.icon_dir / f"glyph-{name}-{safe}-{ICON_PX}.png"
        if cached.is_file():
            return _measure(cached)

        self.icon_dir.mkdir(parents=True, exist_ok=True)
        try:
            return _render_glyph(self.font_path, codepoint, color, cached, ICON_PX)
        except AssetError as exc:
            log.warning("%s", exc)
            return None

    def _load_catalog_json(self) -> Any | None:
        if self.catalog_path.is_file():
            try:
                return json.loads(self.catalog_path.read_text(encoding="utf-8"))
            except ValueError:
                log.warning("Cached device catalog is corrupt; refetching.")

        if self.offline:
            log.warning("Offline and no cached device catalog; icons disabled.")
            return None

        response = self._fetch(CATALOG_URL)
        if response is None:
            return None
        try:
            response.raise_for_status()
            # `json.loads`, not `response.json()`. `_fetch` returns `Fetched`,
            # which carries only what callers use and has never had a `json()`
            # method; calling it raised AttributeError, which the clause below
            # does not catch. That made a successful catalogue download on a
            # cold cache crash the run, the single most ordinary first-use path
            # there is. Every test either seeded the cache or simulated a
            # transport failure, so nothing exercised success.
            payload = json.loads(response.content)
        except (requests.RequestException, ValueError) as exc:
            log.warning(
                "Could not read the UniFi device catalog: %s. Icons disabled.",
                describe_network_error(exc),
            )
            return None
        if not isinstance(payload, dict):
            log.warning("The UniFi device catalog is not an object; icons disabled.")
            return None

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        _cache_write(self.catalog_path, json.dumps(payload).encode("utf-8"))
        return payload

    def catalog(self) -> dict[int, dict[str, Any]]:
        """Map sysid (as int) to catalog entry."""
        if self._catalog is not None:
            return self._catalog

        payload = self._load_catalog_json()
        index: dict[int, dict[str, Any]] = {}
        for entry in (payload or {}).get("devices", []):
            if not isinstance(entry, dict):
                continue
            raw = list(entry.get("sysids") or [])
            if entry.get("sysid") is not None:
                raw.append(entry["sysid"])
            for value in raw:
                # Catalog sysids are hex strings; verified unambiguous.
                sysid = _to_int(value, 16)
                if sysid is not None:
                    index.setdefault(sysid, entry)

        self._catalog = index
        log.debug("Device catalog indexed: %d sysids", len(index))
        return index

    def product_name(self, sysid: int | None) -> str | None:
        if sysid is None:
            return None
        entry = self.catalog().get(sysid)
        if not entry:
            return None
        name = (entry.get("product") or {}).get("name")
        return str(name) if name else None

    def sysid_for_name(self, text: str | None, device_type: str | None = None) -> int | None:
        """Find UniFi hardware by name, for clients with no fingerprint.

        A UniFi device that appears as a *client* (a Protect camera on a switch
        port, say) has no fingerprint dev_id, so the only handle is its hostname.
        Matching is deliberately strict: a unique hit or nothing. "g3-flex"
        matches both UVC-G3-FLEX (a Protect camera) and UA-G3-Flex (an Access
        reader), and picking one at random would be inventing data.

        *device_type* filters the catalog first, which is how that particular
        ambiguity gets resolved when Protect confirms the MAC is a camera.
        """
        needle = _normalise(text)
        if not needle or len(needle) < 4:
            return None

        matches: set[int] = set()
        for sysid, entry in self.catalog().items():
            if device_type:
                types = [str(t).lower() for t in (entry.get("deviceTypes") or [])]
                types.append(str(entry.get("deviceType") or "").lower())
                if not any(device_type.lower() in t for t in types):
                    continue
            names = [(entry.get("product") or {}).get("name"), entry.get("sku")]
            names.extend(entry.get("shortnames") or [])
            if any(needle in _normalise(n) for n in names if n):
                matches.add(sysid)

        if len(matches) == 1:
            return matches.pop()
        if matches:
            log.debug("Name %r matched %d catalog entries; refusing to guess.", text, len(matches))
        return None

    def icon(self, sysid: int | None) -> IconAsset | None:
        """Cached, downscaled artwork for *sysid*, or None."""
        if sysid is None:
            return None
        entry = self.catalog().get(sysid)
        if not entry:
            return None

        images = entry.get("images") or {}
        variant = next((v for v in VARIANTS if images.get(v)), None)
        if variant is None:
            return None

        cached = self.icon_dir / f"{sysid:04x}-{variant}-{ICON_PX}.png"
        if cached.is_file():
            measured = _measure(cached)
            if measured is not None:
                return measured
            # Unreadable: from an interrupted write predating atomic caching, or
            # a truncated file. Drop it so this run refetches rather than
            # returning a broken asset forever.
            log.debug("Cached icon %s is unreadable; refetching.", cached)
            cached.unlink(missing_ok=True)
        if self.offline:
            return None

        url = IMAGE_URL.format(id=entry.get("id"), variant=variant, hash=images[variant])
        response = self._fetch(url)
        if response is None:
            return None
        try:
            response.raise_for_status()
            raw = response.content
        except requests.RequestException as exc:
            log.warning(
                "Could not fetch artwork for sysid %04x: %s.", sysid, describe_network_error(exc)
            )
            return None

        self.icon_dir.mkdir(parents=True, exist_ok=True)
        try:
            return _downscale(raw, cached, ICON_PX)
        except AssetError as exc:
            log.warning("%s", exc)
            return None


def rasterise_svg(path: Path, cache_dir: Path) -> IconAsset | None:
    """An SVG turned into a cached PNG, or None if that is not possible.

    Graphviz loads SVG artwork only for its own `svg` driver: `png` and `pdf`
    go through cairo, which has no SVG loader, so the image is dropped from
    both with a warning and an exit status of 0. Rasterising here is what makes
    a user's SVG reach every format.

    Two things fall out of doing it ourselves, and both are the point:

    * **The XML declaration stops mattering.** Graphviz refuses an SVG without
      one; CairoSVG does not care, and produces byte-identical output either
      way. So the file the user already has works untouched, and nothing needs
      to write a corrected copy into their pictures folder.
    * **The result is a PNG like everything else.** All fetched artwork is
      already PNG, including inside the SVG output, so this makes a supplied
      SVG consistent rather than a special case. The alternative, vector in the
      SVG and raster elsewhere, needs two assets per node and the pipeline
      carries one.

    Optional: CairoSVG is an extra, and without it the caller keeps the SVG and
    warns about the formats it will miss.

    Cached under a hash of the file's contents, so editing the original
    produces a new entry rather than a stale hit.
    """
    try:
        import cairosvg
    except ImportError:
        return None

    try:
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) > MAX_ASSET_BYTES:
        log.warning("%s is larger than %d bytes; not rasterising.", path, MAX_ASSET_BYTES)
        return None

    out_dir = cache_dir / "user-svg"
    target = out_dir / f"{hashlib.sha256(data).hexdigest()[:16]}.png"
    if not target.is_file():
        # Ratio from the source, so a wide drawing stays wide. `_measure_svg`
        # already knows how to read it, including from a viewBox.
        measured = _measure_svg(path)
        kwargs: dict[str, int] = {}
        if measured is not None and measured.height > measured.width:
            kwargs["output_height"] = ICON_PX
        else:
            kwargs["output_width"] = ICON_PX
        try:
            # `unsafe` stays False, its default, which blocks external file and
            # URL references. CairoSVG parses with defusedxml, so an entity
            # expansion attack is refused rather than merely capped.
            png = cairosvg.svg2png(bytestring=data, **kwargs)
        except Exception as exc:  # cairosvg raises a wide variety
            log.warning("Could not rasterise %s: %s", path, exc)
            return None
        # Private, unlike the rest of this cache. Everything else here is
        # Ubiquiti's public artwork, fetched from a CDN and written 0644
        # because there is nothing to protect. This is a rendering of a file
        # the *user* supplied, which may itself be private, and turning it into
        # a world-readable copy would be a change in exposure they did not ask
        # for. Directory and file both, since a 0600 file under a 0755 parent
        # still leaks its name.
        mkdir_private(out_dir)
        atomic_write(target, png, mode=0o600, fsync=False)
        log.info("Rasterised %s to PNG so it reaches every output format.", path.name)

    return _measure(target)


def local_icon(path: Path, cache_dir: Path | None = None) -> IconAsset:
    """Artwork the user supplied, read from where they put it.

    Loud on failure rather than silent: falling back to the wrong fingerprint
    picture would defeat the point of overriding it in the first place.
    """
    if not path.is_file():
        raise AssetError(f"No artwork file at {path}")
    if path.suffix.lower() == ".svg" and cache_dir is not None:
        rasterised = rasterise_svg(path, cache_dir)
        if rasterised is not None:
            return rasterised
        # Falls through to the SVG itself, which still works in the svg and
        # drawio outputs. `write_outputs` warns about the ones it will miss.
    asset = _measure(path)
    if asset is None:
        # "Could not read" on a file the user can plainly see and open is not
        # an error message, it is a shrug. SVG has specific rules that are not
        # guessable, so say which one the file broke.
        raise AssetError(f"Could not read artwork at {path}{_why_unreadable(path)}")
    return asset


def _why_unreadable(path: Path) -> str:
    """A reason to append to a failure, or an empty string if there is none."""
    if path.suffix.lower() != ".svg":
        return ". Supported: PNG, JPEG, GIF, and SVG that Graphviz can load."
    try:
        with path.open("rb") as handle:
            head = handle.read(4096)
    except OSError:
        return ""
    if b"<?xml" not in head:
        return (
            ". The SVG needs an <?xml ...?> declaration on the first line. Add "
            "one, or install the svg extra (`pip install 'unifi-map[svg]'`), "
            "which does not require it."
        )
    if re.search(rb"<svg\b[^>]*>", head, re.I | re.S) is None:
        return ". No opening <svg> tag was found in the first 4 KiB."
    return (
        ". The opening <svg> tag needs usable dimensions: either width and "
        "height, or a viewBox to take the ratio from."
    )


def _pillow_image():
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise AssetError("Pillow is not installed; cannot process artwork.") from exc
    # Applied on every use rather than once at import, since Pillow is imported
    # lazily and a caller could have relaxed it.
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    return Image


@contextlib.contextmanager
def _bomb_guard(Image):
    """Make `MAX_IMAGE_PIXELS` an actual limit, for the duration of one call.

    The threshold alone is not one: Pillow *warns* at `MAX_IMAGE_PIXELS` and
    only raises at roughly twice it, so an image between the two decoded
    anyway. Promoting the warning closes that gap.

    Scoped with `catch_warnings` rather than a bare `simplefilter`, which is
    process-global and would have changed warning behaviour for anything else
    importing this, including the caller's own code. An earlier version claimed
    to be scoped and was not.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        yield


def _measure(path: Path) -> IconAsset | None:
    """Dimensions of an image already on disk, or None if it cannot be read.

    Everything reaches this: cached downloads, and artwork a user supplied in
    an overrides file. So the size guard has to be here too, and its exceptions
    caught: neither Pillow bomb type derives from OSError or ValueError, so an
    oversized cached or user-supplied image escaped as an uncaught exception.
    """
    if path.suffix.lower() == ".svg":
        return _measure_svg(path)
    try:
        Image = _pillow_image()
        with _bomb_guard(Image), Image.open(path) as image:
            return IconAsset(path=path, width=image.width, height=image.height)
    except (
        AssetError,
        OSError,
        ValueError,
        _bomb_types()[0],
        _bomb_types()[1],
    ):
        log.debug("Could not measure %s", path, exc_info=True)
        return None


def _bomb_types() -> tuple[type[BaseException], type[BaseException]]:
    from PIL import Image as _Image

    return (_Image.DecompressionBombError, _Image.DecompressionBombWarning)


# `width="64px"`, `height="32"`. Deliberately a regex rather than an XML parser:
# this file may be attacker-supplied through an overrides file, and an XML
# parser is an entity-expansion surface that nothing here needs.
_SVG_DIM = re.compile(rb"""\b(width|height)\s*=\s*["\']\s*([0-9.]+)\s*(?:px)?\s*["\']""", re.I)


def _measure_svg(path: Path) -> IconAsset | None:
    """Dimensions of an SVG, which Pillow cannot open.

    `docs/overrides.md` documents SVG as usable artwork, and it was not: every
    SVG was rejected at this function, because measuring went through Pillow.
    Accepts only what Graphviz will actually load, which is narrower than
    "valid SVG". Refusing here names the file, which beats a Graphviz warning
    about a file that plainly exists, or silence.

    Dimensions come from `width` and `height` if present, and from `viewBox`
    otherwise. The fallback was added after a real icon was refused for having
    only a viewBox, which is how most drawing tools export: Graphviz renders
    those perfectly well and preserves the ratio, so demanding explicit
    dimensions was stricter than the thing being protected against. Checked by
    rendering both through `dot` rather than by reasoning about it.
    """
    try:
        # Only the head, rather than reading the file and then slicing it.
        with path.open("rb") as handle:
            head = handle.read(4096)
    except OSError:
        return None
    # Graphviz rejects an SVG with no XML declaration, reporting it as a file
    # that "was not found", which fails the entire render. Measuring it here
    # and letting it through turned a bad icon into a bad run. Learned by
    # rendering one, not from a spec.
    if b"<?xml" not in head:
        return None
    # Only the opening `<svg ...>` tag. Scanning the whole head let a child
    # element win: `<rect width="7"/>` inside a 64x32 drawing measured as 7x5,
    # because the last match replaced the first.
    opening = re.search(rb"<svg\b[^>]*>", head, re.I | re.S)
    if opening is None:
        return None
    found: dict[bytes, float] = {}
    for match in _SVG_DIM.finditer(opening.group(0)):
        try:
            found[match.group(1).lower()] = float(match.group(2))
        except ValueError:
            # `width="."` matches the pattern and is not a number.
            return None
    width, height = found.get(b"width"), found.get(b"height")
    if width is None or height is None:
        # Only the ratio is used downstream, by `display_size()`, so a viewBox
        # carries everything needed. Its first two numbers are the origin and
        # are deliberately ignored.
        box = re.search(rb"viewBox\s*=\s*[\"']([^\"']+)", opening.group(0), re.I)
        if box is None:
            return None
        try:
            parts = [float(v) for v in box.group(1).replace(b",", b" ").split()]
        except ValueError:
            return None
        if len(parts) != 4:
            return None
        width, height = parts[2], parts[3]
    if not (math.isfinite(width) and math.isfinite(height)) or width <= 0 or height <= 0:
        return None
    # Rounded, never to zero: `width="0.5"` truncated to a 0x0 icon, which
    # Graphviz draws as nothing at all.
    return IconAsset(path=path, width=max(1, round(width)), height=max(1, round(height)))


def _render_cloud(color: str, dest: Path, box: int) -> IconAsset:
    """Draw a plain cloud silhouette.

    Ours, not Ubiquiti's: it is four overlapping ellipses and a bar, drawn here
    rather than fetched, so it works offline and raises no licensing question.
    It stands in for the Internet node whenever no provider brand mark applies,
    which is either an ASN with no logo or a deliberately obfuscated map.

    Drawn oversized and downscaled, the same trick the glyph renderer uses to
    keep curved edges smooth.
    """
    Image = _pillow_image()
    try:
        from PIL import ImageDraw
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise AssetError("Pillow is not installed; cannot draw the Internet icon.") from exc

    scale = 4
    width = box * scale
    height = int(width * 0.62)
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    def blob(cx: float, cy: float, r: float) -> None:
        draw.ellipse(
            [
                (cx - r) * width,
                (cy - r) * width,
                (cx + r) * width,
                (cy + r) * width,
            ],
            fill=color,
        )

    # Five puffs of differing size on a rounded bar. The asymmetry is the point:
    # evenly spaced equal circles read as a flower, not a cloud.
    #
    # Every circle's lowest point is exactly the baseline. A puff reaching even
    # slightly past it leaves a visible lump hanging off the flat bottom edge,
    # which is the one way this goes obviously wrong.
    base = 0.53
    draw.rounded_rectangle(
        [0.07 * width, 0.38 * width, 0.93 * width, base * width],
        radius=0.075 * width,
        fill=color,
    )
    for cx, radius in ((0.22, 0.165), (0.38, 0.185), (0.56, 0.225), (0.75, 0.195), (0.87, 0.135)):
        blob(cx, base - radius, radius)

    cropped = canvas.crop(canvas.getbbox() or (0, 0, width, height))
    cropped.thumbnail((box, box), Image.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    cropped.save(dest, "PNG")
    return IconAsset(path=dest, width=cropped.width, height=cropped.height)


def _render_glyph(font_path: Path, codepoint: int, color: str, dest: Path, box: int) -> IconAsset:
    """Draw a single font glyph, tightly cropped, into a transparent PNG."""
    Image = _pillow_image()
    try:
        from PIL import ImageDraw, ImageFont
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise AssetError("Pillow is not installed; cannot render glyphs.") from exc

    char = chr(codepoint)
    try:
        # Render oversized, then crop and downscale, so edges stay smooth.
        font = ImageFont.truetype(str(font_path), box * 2)
        canvas = Image.new("RGBA", (box * 4, box * 4), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        bbox = draw.textbbox((0, 0), char, font=font)
        if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
            raise AssetError(f"Glyph U+{codepoint:04X} is empty in {font_path.name}.")
        draw.text((-bbox[0] + 4, -bbox[1] + 4), char, font=font, fill=color)
        cropped = canvas.crop(canvas.getbbox() or (0, 0, box, box))
        cropped.thumbnail((box, box), Image.LANCZOS)
        cropped.save(dest, format="PNG", optimize=True)
        return IconAsset(path=dest, width=cropped.width, height=cropped.height)
    except (
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise AssetError(f"Could not render glyph U+{codepoint:04X}: {exc}") from exc


def _downscale(raw: bytes, dest: Path, box: int) -> IconAsset:
    """Shrink *raw* PNG to fit *box*, preserving alpha and aspect ratio.

    Product renders arrive 1-2 MB each; trimming transparent margins first means
    the visible artwork actually fills the box rather than floating in padding.
    """
    from io import BytesIO

    Image = _pillow_image()
    try:
        # Same guard as `_measure`. This is the path that decodes bytes
        # straight off the network, so leaving it out meant the cap applied
        # to artwork already on disk and not to artwork arriving.
        with _bomb_guard(Image), Image.open(BytesIO(raw)) as image:
            image = image.convert("RGBA")
            bbox = image.getbbox()
            if bbox:
                image = image.crop(bbox)
            image.thumbnail((box, box), Image.LANCZOS)
            # Written aside and renamed into place: a half-written icon is
            # indistinguishable from a good one to the `is_file()` check that
            # decides whether to refetch, so it would be cached corrupt forever.
            buffer = BytesIO()
            image.save(buffer, format="PNG", optimize=True)
            _cache_write(dest, buffer.getvalue())
            return IconAsset(path=dest, width=image.width, height=image.height)
    except (
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise AssetError(f"Could not process artwork: {exc}") from exc


def data_uri(path: Path) -> str:
    """base64 data URI for embedding in SVG or a draw.io style."""
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"
