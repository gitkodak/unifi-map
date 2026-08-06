"""The only module that talks to the UniFi controller.

Authentication is an API key in an ``X-API-KEY`` header. Keys reach everything
this tool needs, including the web app's static assets, so there is no login, no
session and no CSRF token to manage. The header is set once in the constructor
and every request carries it.

The one UniFi OS quirk that matters: every Network application path is prefixed
with ``/proxy/network``.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import logging
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
import urllib3

from .assets import describe_network_error, parse_glyph_codepoints
from .config import ExporterConfig
from .fsio import atomic_write, mkdir_private
from .httpio import declared_size, read_capped

log = logging.getLogger(__name__)

# Endpoints we pull, keyed by the cache filename they land in. Each value is a
# path relative to the Network application root.
ENDPOINTS: dict[str, str] = {
    "device": "api/s/{site}/stat/device",
    "client_active": "api/s/{site}/stat/sta",
    "networkconf": "api/s/{site}/rest/networkconf",
    # WAN subsystem, which carries isp_name / isp_organization / wan_ip.
    "health": "api/s/{site}/stat/health",
    # The client fingerprint database: 5789 known devices with real product
    # names, families and vendors. Turns "Espressif 003003" into
    # "Govee H61E1". Not site-scoped.
    "fingerprint": "v2/api/fingerprint_devices/0",
    # Supplementary. The UI's own graph; shape varies between controller
    # versions, so the renderer treats it as optional enrichment rather than
    # the source of truth.
    "topology": "v2/api/site/{site}/topology",
}

# Not under /proxy/network/, and only present when UniFi Protect is installed.
# Protect knows which MACs are cameras, which is the only authoritative way to
# tell a Protect camera from an Access reader when both share a model name.
EXTRA_ENDPOINTS: dict[str, str] = {
    "protect_cameras": "proxy/protect/integration/v1/cameras",
}

# The largest controller response this tool will read. A payload from a real
# network of any size sits far below this; the ceiling exists so a hostile or
# broken response is refused while streaming rather than buffered whole. It is
# the same cap discipline the CDN artwork has always had, applied to the
# endpoint people reach with UNIFI_VERIFY_TLS=false.
MAX_RESPONSE_BYTES = 64 * 1024 * 1024

# A snapshot is a set of files, and a set cannot be replaced atomically in
# place, so each fetch writes a complete set under `gens/` and switches a
# pointer to it. See `Snapshot.write` for the full argument.
GENERATIONS_DIR = "gens"
CURRENT_POINTER = "snapshot-current"
# The only shape a pointer may name. The pointer is a path read off disk and
# handed to `Path` arithmetic, so it is anchored rather than resolved, the same
# rule support-archive member paths follow: anything else is refused.
_GEN_NAME = re.compile(rf"^{GENERATIONS_DIR}/[0-9]{{8}}T[0-9]{{12}}-[0-9]+$")

_ASSET_HASH = re.compile(rb"angular/([A-Za-z0-9]+)/")


class UniFiError(RuntimeError):
    """Raised for authentication and transport failures."""


class _Session(requests.Session):
    """A session that will not carry the API key to a different host.

    `requests` already does this for `Authorization`: on a redirect that
    changes host it deletes the header, so a credential cannot be handed to
    somewhere the caller never chose. It does not do it for anything else, and
    ours is the custom header `X-API-KEY`, which would ride along untouched.

    That matters more here than it looks. `UNIFI_VERIFY_TLS=false` is
    documented as the ordinary setting for a bare IP, because consoles serve a
    self-signed certificate there. With verification off, anyone in the path can
    answer with a redirect to a host of their choosing, and without this the
    next request hands them a working admin key.

    Redirects themselves are left enabled. Refusing them outright would work
    against a console today, since none of the endpoints used redirect, but it
    would break anyone who fronts their controller with a reverse proxy that
    normalises a path or a trailing slash. Stripping keeps those working and
    only disarms the case that is actually dangerous.
    """

    def rebuild_auth(self, prepared_request: Any, response: Any) -> None:
        super().rebuild_auth(prepared_request, response)
        if not self.should_strip_auth(response.request.url, prepared_request.url):
            return
        if prepared_request.headers.pop("X-API-KEY", None) is not None:
            log.warning(
                "Redirected from %s to a different host; the API key was not "
                "sent on. If this is a legitimate proxy, point UNIFI_HOST at "
                "the address it answers on rather than following a redirect.",
                response.request.url,
            )


@dataclass
class Snapshot:
    """Raw controller responses, as fetched or as loaded from cache."""

    payloads: dict[str, Any]

    def get(self, name: str) -> Any:
        return self.payloads.get(name)

    def write(self, cache_dir: Path) -> None:
        """Write the snapshot as one generation, switched into place at the end.

        These hold a MAC, hostname and IP inventory of an entire network, so
        mode is set on a temporary before the rename rather than on the target
        afterwards. Chmod-after-write leaves a window at the umask default, and
        an already-present file keeps its old permissions for the whole write.

        A snapshot is several files, and several files cannot be replaced
        atomically as a set. Writing them beside each other in place left an
        interruption or two concurrent fetches able to mix old and new payloads,
        and `read()` accepted the mixture: a map built from two different
        moments, looking exactly like one built from one. So each fetch writes a
        complete set into its own directory under `gens/`, and the last step
        swaps a pointer file to it. `read()` only ever sees a complete
        generation, and an interrupted fetch leaves the pointer on the previous
        one rather than destroying it, which is what keeps `render` working
        after a fetch that was cut off.
        """
        cache_dir.mkdir(parents=True, exist_ok=True)
        # A mount without POSIX modes is not a reason to refuse to write.
        with contextlib.suppress(OSError):
            cache_dir.chmod(0o700)

        # Uniquely named per process as well as per moment, so two concurrent
        # fetches never write into the same directory.
        generation = f"{dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%S%f')}-{os.getpid()}"
        gen_dir = cache_dir / GENERATIONS_DIR / generation
        mkdir_private(gen_dir)
        for name, payload in sorted(self.payloads.items()):
            body = json.dumps(payload, indent=2, sort_keys=True)
            atomic_write(gen_dir / f"{name}.json", body)

        # The commit point: one atomic rename, after which the set above is what
        # every reader sees.
        atomic_write(cache_dir / CURRENT_POINTER, f"{GENERATIONS_DIR}/{generation}\n")

        # Best-effort housekeeping, only while we are still the generation the
        # pointer names. Superseded generations are complete and nothing points
        # at them any more, so they are removed rather than left to accumulate a
        # second copy of the inventory. If a concurrent fetch has already
        # superseded us, its own pass will do this when it finishes, and tidying
        # from a superseded position could race it.
        #
        # One residual stays open on purpose: a fetch that started before ours
        # and is still writing when we finish first can have its working
        # directory removed from under it, failing that fetch loudly rather than
        # leaving a mixed snapshot behind. Closing that needs a lock or an age
        # guard; the failure is loud, and two simultaneous fetches into one
        # cache directory were already asking for trouble.
        try:
            current = (cache_dir / CURRENT_POINTER).read_text(encoding="utf-8").strip()
        except OSError:
            current = f"{GENERATIONS_DIR}/{generation}"
        if current != f"{GENERATIONS_DIR}/{generation}":
            return

        try:
            for old in sorted((cache_dir / GENERATIONS_DIR).iterdir()):
                if old.is_dir() and old.name != generation:
                    shutil.rmtree(old, ignore_errors=True)
        except OSError:
            # Nothing useful to say: the next fetch tries again, and a leftover
            # generation is inert now that the pointer has moved.
            pass

        # A cache that predates generations holds flat endpoint files beside the
        # pointer. They are a full inventory nothing reads any more, which is
        # exactly the stale copy this used to remove; take them out once the
        # pointer is in place.
        for name in (*ENDPOINTS, *EXTRA_ENDPOINTS):
            stale = cache_dir / f"{name}.json"
            try:
                if stale.is_file():
                    stale.unlink()
                    log.debug("Removed %s, superseded by a generation.", stale)
            except OSError:
                log.warning(
                    "Could not remove %s, left over from a pre-generation cache. "
                    "It is no longer read; delete it by hand.",
                    stale,
                )

    @classmethod
    def read(cls, cache_dir: Path) -> Snapshot:
        if not cache_dir.is_dir():
            raise UniFiError(f"No cached snapshot at {cache_dir}. Run `unifi-map fetch` first.")
        snapshot_dir = cls._snapshot_dir(cache_dir)
        payloads: dict[str, Any] = {}
        for name in list(ENDPOINTS) + list(EXTRA_ENDPOINTS):
            path = snapshot_dir / f"{name}.json"
            if path.is_file():
                try:
                    payloads[name] = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    raise UniFiError(
                        f"Cached snapshot {path} is not readable JSON ({exc}). "
                        "Re-run `unifi-map fetch` to replace it."
                    ) from exc
        if not payloads:
            raise UniFiError(f"Cache directory {cache_dir} contains no snapshot files.")
        return cls(payloads=payloads)

    @classmethod
    def _snapshot_dir(cls, cache_dir: Path) -> Path:
        """The directory holding the current generation, or the cache itself.

        A cache with no pointer is the legacy flat layout: the shipped demo
        dataset, and anything written before generations existed. Both keep
        working, and the next `fetch` migrates them.
        """
        pointer = cache_dir / CURRENT_POINTER
        if not pointer.is_file():
            return cache_dir
        try:
            target = pointer.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise UniFiError(
                f"Could not read the snapshot pointer {pointer} ({exc}). Re-run `unifi-map fetch`."
            ) from exc
        if not _GEN_NAME.fullmatch(target):
            raise UniFiError(
                f"Snapshot pointer {pointer} names {target!r}, which is not a "
                "generation. Re-run `unifi-map fetch`."
            )
        generation = cache_dir / target
        if not generation.is_dir():
            raise UniFiError(
                f"Snapshot pointer {pointer} names {target}, which is missing. "
                "The generation was probably removed by hand; re-run "
                "`unifi-map fetch`."
            )
        return generation


class UniFiClient:
    def __init__(self, config: ExporterConfig, timeout: float = 30.0) -> None:
        self.config = config
        self.timeout = timeout
        self.session = _Session()
        self.session.verify = config.verify_tls
        # Keys need no session, so there is nothing to log in or out of: the
        # header is set once and every request carries it.
        self.session.headers["X-API-KEY"] = config.api_key
        if config.verify_tls is False:
            # Expected on a LAN console with a self-signed cert. Suppress the
            # per-request warning rather than let it drown real output.
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def _get(self, url: str) -> bytes:
        """GET *url* and return the body, capped like every download here.

        The controller is the endpoint people reach with
        `UNIFI_VERIFY_TLS=false`, which is the same threat model that strips
        the API key across a host-changing redirect: anyone in the path can
        answer. So the response is streamed and read through a size cap, the
        way CDN artwork has always been, rather than buffered whole.
        """
        try:
            response = self.session.get(url, timeout=self.timeout, stream=True)
        except requests.RequestException as exc:
            raise UniFiError(
                f"Could not reach {self.config.host}: {describe_network_error(exc)}. "
                "Check UNIFI_HOST, that the console is up, and that this machine "
                "can route to it."
            ) from exc
        if response.status_code in (401, 403):
            raise UniFiError(
                f"HTTP {response.status_code} from {url}. The API key is wrong, "
                "revoked, or lacks permission for this site."
            )
        if not response.ok:
            raise UniFiError(f"HTTP {response.status_code} from {url}")
        declared = declared_size(response)
        if declared is not None and declared > MAX_RESPONSE_BYTES:
            response.close()
            raise UniFiError(
                f"Response from {url} claims {declared} bytes, past the "
                f"{MAX_RESPONSE_BYTES}-byte cap. This is not normal for a "
                "controller payload."
            )
        body = read_capped(response, MAX_RESPONSE_BYTES)
        if body is None:
            raise UniFiError(
                f"Response from {url} exceeded the {MAX_RESPONSE_BYTES}-byte "
                "cap. This is not normal for a controller payload."
            )
        return body

    def _fetch(self, path: str) -> Any:
        url = f"{self.config.base_url}/proxy/network/{path.format(site=self.config.site)}"
        try:
            return json.loads(self._get(url))
        except ValueError as exc:
            raise UniFiError(f"Non-JSON response from {url}") from exc

    def _fetch_json(self, path: str) -> Any:
        """GET JSON from a path relative to the console root, not /proxy/network/."""
        url = f"{self.config.base_url}/{path}"
        try:
            return json.loads(self._get(url))
        except ValueError as exc:
            raise UniFiError(f"Non-JSON response from {url}") from exc

    def _fetch_raw(self, path: str) -> bytes:
        """GET a non-JSON asset from under /proxy/network/."""
        url = f"{self.config.base_url}/proxy/network/{path}"
        return self._get(url)

    def asset_hash(self) -> str:
        """The web app's build hash, needed to address its static assets.

        Read from the manage page rather than guessed: it changes with every
        controller release, and a wrong hash silently returns the SPA's HTML 404
        instead of the asset.
        """
        html = self._fetch_raw("manage/")
        match = _ASSET_HASH.search(html)
        if not match:
            raise UniFiError("Could not find the web app asset hash in /manage/.")
        return match.group(1).decode("ascii")

    def fetch_icon_font(self) -> tuple[bytes, dict[str, int]]:
        """The icon font and the codepoints of the four client glyphs.

        UniFi renders client icons as an icon-font glyph chosen by CSS class,
        not as a per-device image, so this font *is* the artwork.
        """
        build = self.asset_hash()
        base = f"manage/angular/{build}/fonts/ubnt-icon"
        css = self._fetch_raw(f"{base}/style.css").decode("utf-8", errors="replace")

        codepoints = parse_glyph_codepoints(css)
        if not codepoints:
            raise UniFiError("Found no client glyph codepoints in the icon font stylesheet.")

        # The stylesheet cache-busts with a query string; the path itself is stable.
        font = self._fetch_raw(f"{base}/fonts/ubnt.ttf")
        return font, codepoints

    def snapshot(self) -> Snapshot:
        """Fetch every endpoint. Optional ones are allowed to fail."""
        payloads: dict[str, Any] = {}
        required = {"device", "client_active", "networkconf"}
        for name, path in ENDPOINTS.items():
            try:
                payloads[name] = self._fetch(path)
            except UniFiError as exc:
                if name in required:
                    raise
                log.warning("Optional endpoint %s unavailable: %s", name, exc)

        for name, path in EXTRA_ENDPOINTS.items():
            try:
                payloads[name] = self._fetch_json(path)
            except UniFiError as exc:
                # Absent whenever the app is not installed, which is normal.
                log.debug("Optional app endpoint %s unavailable: %s", name, exc)
        return Snapshot(payloads=payloads)


def unwrap(payload: Any) -> list[dict[str, Any]]:
    """Return the list of records from a controller response.

    Version 1 endpoints wrap results in ``{"meta": ..., "data": [...]}``; some
    v2 endpoints return a bare list. Anything else yields an empty list so a
    surprising shape degrades into a thinner diagram instead of a traceback.
    """
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []
