"""Asset fetching, caching and SVG inlining.

No test here touches the network: the catalog is written straight into the cache
so AssetStore reads it from disk.
"""

from __future__ import annotations

import json
import shutil
import stat
import subprocess
from typing import ClassVar

import pytest
import requests

from unifi_map.assets import (
    AssetError,
    AssetStore,
    IconAsset,
    describe_network_error,
    read_icon_font_dir,
)
from unifi_map.svg_post import inline_svg_images

CATALOG = {
    "version": "test",
    "devices": [
        {
            "id": "aaaa-bbbb",
            # Catalog sysids are hex strings; the controller reports decimal.
            "sysids": ["a682"],
            "product": {"name": "Access Point U7 Pro"},
            "images": {"topology": "topohash", "default": "defhash"},
            "icon": {"id": "icon-uuid"},
        },
        {
            "id": "cccc-dddd",
            "sysid": "ed72",
            "product": {"name": "Switch Pro HD 24 PoE"},
            # No topology variant: must fall back down the preference list.
            "images": {"default": "onlydefault"},
        },
        {"id": "eeee", "sysids": ["ffff"], "product": {"name": "No Art"}, "images": {}},
    ],
}


@pytest.fixture
def store(tmp_path) -> AssetStore:
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "ui-device-catalog.json").write_text(json.dumps(CATALOG), encoding="utf-8")
    return AssetStore(cache_dir=cache, offline=True)


class TestCatalog:
    def test_hex_sysids_are_parsed_to_the_controllers_decimal_values(self, store: AssetStore):
        # 0xa682 == 42626, which is what stat/device reports for a U7 Pro.
        assert 42626 in store.catalog()
        assert 0xED72 in store.catalog()

    def test_product_name_lookup(self, store: AssetStore):
        assert store.product_name(42626) == "Access Point U7 Pro"
        assert store.product_name(0xFFFF) == "No Art"

    def test_unknown_sysid_resolves_to_nothing(self, store: AssetStore):
        assert store.product_name(0x1234) is None
        assert store.icon(0x1234) is None

    def test_none_sysid_is_tolerated(self, store: AssetStore):
        assert store.product_name(None) is None
        assert store.icon(None) is None

    def test_corrupt_cached_catalog_does_not_raise_when_offline(self, tmp_path):
        cache = tmp_path / "cache"
        cache.mkdir()
        (cache / "ui-device-catalog.json").write_text("{not json", encoding="utf-8")
        store = AssetStore(cache_dir=cache, offline=True)
        # Degrades to an empty catalog rather than exploding.
        assert store.catalog() == {}


class TestIconCache:
    def test_offline_with_no_cached_file_yields_nothing(self, store: AssetStore):
        assert store.icon(42626) is None

    def test_a_cached_file_is_measured_and_reused(self, store: AssetStore, png_bytes):
        from unifi_map.assets import ICON_PX

        store.icon_dir.mkdir(parents=True, exist_ok=True)
        # Filename encodes sysid, variant and size; `topology` is preferred.
        target = store.icon_dir / f"{42626:04x}-topology-{ICON_PX}.png"
        target.write_bytes(png_bytes(40, 10))

        asset = store.icon(42626)
        assert asset is not None
        assert asset.path == target
        assert (asset.width, asset.height) == (40, 10)

    def test_variant_preference_falls_back_when_topology_is_absent(
        self, store: AssetStore, png_bytes
    ):
        from unifi_map.assets import ICON_PX

        store.icon_dir.mkdir(parents=True, exist_ok=True)
        target = store.icon_dir / f"{0xED72:04x}-default-{ICON_PX}.png"
        target.write_bytes(png_bytes(20, 20))
        assert store.icon(0xED72) is not None

    def test_device_with_no_images_yields_nothing(self, store: AssetStore):
        assert store.icon(0xFFFF) is None


class TestSvgInlining:
    def test_png_reference_becomes_a_data_uri(self, tmp_path, png_bytes):
        icon = tmp_path / "icon.png"
        icon.write_bytes(png_bytes(4, 4))
        svg = f'<svg><image xlink:href="{icon}" /></svg>'.encode()

        out = inline_svg_images(svg, allowed=[icon])
        assert b"data:image/png;base64," in out
        assert str(icon).encode() not in out

    def test_repeated_reference_is_encoded_once_and_reused(self, tmp_path, png_bytes):
        icon = tmp_path / "icon.png"
        icon.write_bytes(png_bytes(4, 4))
        svg = f'<svg><image href="{icon}"/><image href="{icon}"/></svg>'.encode()
        out = inline_svg_images(svg, allowed=[icon])
        assert out.count(b"data:image/png;base64,") == 2

    def test_artwork_the_user_supplied_is_embedded_too(self, tmp_path, png_bytes):
        # Override artwork lives wherever the user keeps it, not in the cache.
        # Leaving it as a path both breaks portability and discloses a local
        # path, which usually contains a username.
        cached = tmp_path / "cache" / "a.png"
        cached.parent.mkdir()
        cached.write_bytes(png_bytes(4, 4))
        supplied = tmp_path / "mine" / "bidet.png"
        supplied.parent.mkdir()
        supplied.write_bytes(png_bytes(8, 6))

        svg = f'<svg><image href="{cached}"/><image href="{supplied}"/></svg>'.encode()
        out = inline_svg_images(svg, allowed=[cached, supplied])
        assert out.count(b"data:image/png;base64,") == 2
        assert b"/mine/bidet.png" not in out
        assert b"/cache/a.png" not in out

    def test_a_file_that_was_not_used_is_refused(self, tmp_path, png_bytes):
        used = tmp_path / "used.png"
        used.write_bytes(png_bytes(4, 4))
        other = tmp_path / "secret.png"
        other.write_bytes(png_bytes(4, 4))
        svg = f'<svg><image href="{other}"/></svg>'.encode()

        out = inline_svg_images(svg, allowed=[used])
        # Left untouched rather than embedded.
        assert b"data:image/png" not in out
        assert str(other).encode() in out

    def test_missing_file_is_left_alone(self, tmp_path):
        absent = tmp_path / "nope.png"
        svg = f'<svg><image href="{absent}"/></svg>'.encode()
        assert inline_svg_images(svg, allowed=[absent]).count(b"data:") == 0

    def test_existing_data_uri_is_not_double_encoded(self, tmp_path):
        svg = b'<svg><image href="data:image/png;base64,QQ==.png"/></svg>'
        assert inline_svg_images(svg, allowed=[]) == svg

    def test_non_png_references_are_ignored(self, tmp_path):
        svg = b'<svg><image href="/etc/passwd"/></svg>'
        assert inline_svg_images(svg, allowed=[]) == svg

    def test_nothing_allowed_means_nothing_embedded(self, tmp_path, png_bytes):
        icon = tmp_path / "icon.png"
        icon.write_bytes(png_bytes(4, 4))
        svg = f'<svg><image href="{icon}"/></svg>'.encode()
        assert b"data:" not in inline_svg_images(svg)


def test_icon_asset_display_size_never_returns_zero():
    tiny = IconAsset(path=None, width=1, height=1000)  # type: ignore[arg-type]
    w, h = tiny.display_size(168, 90)
    assert w >= 1
    assert h >= 1


class TestClientArtwork:
    def test_offline_yields_nothing_without_a_cached_file(self, store: AssetStore):
        assert store.client_icon(4425) is None

    def test_none_dev_id_is_tolerated(self, store: AssetStore):
        assert store.client_icon(None) is None

    def test_a_cached_client_icon_is_measured_and_reused(self, store: AssetStore, png_bytes):
        from unifi_map.assets import ICON_PX

        store.icon_dir.mkdir(parents=True, exist_ok=True)
        target = store.icon_dir / f"client-4425-{ICON_PX}.png"
        target.write_bytes(png_bytes(32, 24))

        asset = store.client_icon(4425)
        assert asset is not None
        assert asset.path == target
        assert (asset.width, asset.height) == (32, 24)


class TestClientGlyphs:
    def test_no_font_means_no_glyph(self, store: AssetStore):
        assert store.client_glyph("user-wired", "#888888") is None

    def test_codepoints_are_read_from_the_cached_map(self, store: AssetStore):
        store.cache_dir.mkdir(parents=True, exist_ok=True)
        store.font_map_path.write_text('{"user-wired": 59681}', encoding="utf-8")
        assert store.glyph_codepoints() == {"user-wired": 59681}

    def test_corrupt_codepoint_map_degrades_quietly(self, store: AssetStore):
        store.cache_dir.mkdir(parents=True, exist_ok=True)
        store.font_map_path.write_text("{nope", encoding="utf-8")
        assert store.glyph_codepoints() == {}

    def test_saving_the_font_writes_both_files(self, store: AssetStore):
        store.save_icon_font(b"not-a-real-font", {"user-wired": 1})
        assert store.font_path.read_bytes() == b"not-a-real-font"
        assert store.glyph_codepoints() == {"user-wired": 1}

    def test_unknown_glyph_name_yields_nothing(self, store: AssetStore):
        store.save_icon_font(b"x", {"user-wired": 1})
        assert store.client_glyph("no-such-glyph", "#888888") is None


class TestHardwareNameLookup:
    """UniFi hardware that appears as a client has no fingerprint, so its
    hostname is matched against the hardware catalog instead."""

    def test_unique_match_resolves(self, store: AssetStore):
        assert store.sysid_for_name("U7 Pro") == 42626
        assert store.sysid_for_name("u7-pro") == 42626

    def test_matching_is_punctuation_insensitive(self, store: AssetStore):
        assert store.sysid_for_name("Pro HD 24 PoE") == 0xED72
        assert store.sysid_for_name("pro-hd-24-poe") == 0xED72

    def test_ambiguous_name_refuses_to_guess(self, tmp_path):
        # "g3flex" really does match both a Protect camera and an Access reader
        # in the real catalog. Picking one would be inventing data.
        catalog = {
            "devices": [
                {
                    "id": "a",
                    "sysid": "a534",
                    "product": {"name": "Camera G3 Flex"},
                    "shortnames": ["UVC-G3-FLEX"],
                    "deviceType": "camera",
                    "images": {},
                },
                {
                    "id": "b",
                    "sysid": "b100",
                    "product": {"name": "G3 Reader Flex"},
                    "shortnames": ["UA-G3-Flex"],
                    "deviceType": "door-access",
                    "images": {},
                },
            ]
        }
        cache = tmp_path / "c"
        cache.mkdir()
        (cache / "ui-device-catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
        store = AssetStore(cache_dir=cache, offline=True)

        assert store.sysid_for_name("g3-flex") is None
        # A device type breaks the tie, which is what Protect provides.
        assert store.sysid_for_name("g3-flex", device_type="camera") == 0xA534
        assert store.sysid_for_name("g3-flex", device_type="door-access") == 0xB100

    def test_unknown_name_resolves_to_nothing(self, store: AssetStore):
        assert store.sysid_for_name("definitely-not-a-product") is None

    def test_short_or_empty_names_are_ignored(self, store: AssetStore):
        # Two characters would match half the catalog.
        assert store.sysid_for_name("u7") is None
        assert store.sysid_for_name("") is None
        assert store.sysid_for_name(None) is None


class TestClientFingerprintDatabase:
    """The dev_id to product-name catalogue.

    Ubiquiti publish this, so it needs no controller. That is what keeps
    `--support-file` usable by someone who deliberately will not point this tool
    at their console.
    """

    def _store(self, tmp_path, offline: bool) -> AssetStore:
        cache = tmp_path / "cache"
        cache.mkdir()
        return AssetStore(cache_dir=cache, offline=offline)

    def test_a_cached_database_is_read_without_the_network(self, tmp_path):
        store = self._store(tmp_path, offline=True)
        store.save_fingerprint_db({"dev_ids": {"5282": {"name": "Govee Lyra"}}})
        assert store.fingerprint_db()["dev_ids"]["5282"]["name"] == "Govee Lyra"

    def test_offline_with_no_cache_yields_nothing_rather_than_failing(self, tmp_path):
        # Clients still render; they just do not get product artwork.
        assert self._store(tmp_path, offline=True).fingerprint_db() is None

    def test_a_payload_without_dev_ids_is_not_cached(self, tmp_path):
        store = self._store(tmp_path, offline=True)
        store.save_fingerprint_db({"nonsense": True})
        assert not store.fingerprint_db_path.exists()
        assert store.fingerprint_db() is None

    def test_a_corrupt_cache_does_not_raise(self, tmp_path):
        store = self._store(tmp_path, offline=True)
        store.fingerprint_db_path.write_text("{not json", encoding="utf-8")
        assert store.fingerprint_db() is None

    def test_downloading_is_off_by_default(self, tmp_path, monkeypatch):
        # Reading a support file should contact nothing unless asked, so a bare
        # call must not reach the network even when not marked offline.
        store = AssetStore(cache_dir=tmp_path / "cache")

        def explode(*args, **kwargs):  # pragma: no cover - must never run
            raise AssertionError("fingerprint_db() made a network request")

        monkeypatch.setattr("unifi_map.assets.requests.get", explode)
        assert store.fingerprint_db() is None

    def test_a_cache_is_used_without_asking_to_download(self, tmp_path, monkeypatch):
        # Reading a local file is not network access, so it needs no opt-in.
        store = AssetStore(cache_dir=tmp_path / "cache")
        store.save_fingerprint_db({"dev_ids": {"1": {"name": "Thing"}}})

        def explode(*args, **kwargs):  # pragma: no cover - must never run
            raise AssertionError("fingerprint_db() made a network request")

        monkeypatch.setattr("unifi_map.assets.requests.get", explode)
        assert store.fingerprint_db()["dev_ids"]["1"]["name"] == "Thing"

    def test_offline_beats_an_explicit_download_request(self, tmp_path, monkeypatch):
        store = AssetStore(cache_dir=tmp_path / "cache", offline=True)

        def explode(*args, **kwargs):  # pragma: no cover - must never run
            raise AssertionError("fingerprint_db() made a network request")

        monkeypatch.setattr("unifi_map.assets.requests.get", explode)
        assert store.fingerprint_db(download=True) is None


class TestIconFontFromDisk:
    """Loading the client glyph font from a copy made by hand.

    Ubiquiti publish no copy of this font, so the alternatives are an API key or
    copying two files off a controller. This is the second, and it must need
    neither credentials nor a network.
    """

    CSS = (
        '@font-face{font-family:"ubnt";src:url("fonts/ubnt.ttf?6vxos8")}\n'
        '.ubnt-icon--user-wired:before{content:"\\e8a1"}\n'
        '.ubnt-icon--user-wireless:before{content:"\\e8a2"}\n'
        '.ubnt-icon--guest-wired:before{content:"\\e8a3"}\n'
        '.ubnt-icon--guest-wireless:before{content:"\\e8a4"}\n'
    )

    def _dir(self, tmp_path, css=None, font=b"fake-ttf", nested=True):
        root = tmp_path / "ubnt-icon"
        (root / "fonts").mkdir(parents=True)
        if css is not None:
            (root / "style.css").write_text(css, encoding="utf-8")
        if font is not None:
            target = (root / "fonts" / "ubnt.ttf") if nested else (root / "ubnt.ttf")
            target.write_bytes(font)
        return root

    def test_the_controller_directory_layout_is_read_as_is(self, tmp_path):
        font, codepoints = read_icon_font_dir(self._dir(tmp_path, self.CSS))
        assert font == b"fake-ttf"
        assert codepoints == {
            "user-wired": 0xE8A1,
            "user-wireless": 0xE8A2,
            "guest-wired": 0xE8A3,
            "guest-wireless": 0xE8A4,
        }

    def test_both_files_dropped_in_one_flat_folder_also_work(self, tmp_path):
        # People will not necessarily preserve the controller's directory shape.
        _, codepoints = read_icon_font_dir(self._dir(tmp_path, self.CSS, nested=False))
        assert len(codepoints) == 4

    def test_a_missing_stylesheet_says_why_it_is_needed(self, tmp_path):
        directory = self._dir(tmp_path, css=None)
        with pytest.raises(AssetError, match="codepoints"):
            read_icon_font_dir(directory)

    def test_a_missing_font_is_reported(self, tmp_path):
        directory = self._dir(tmp_path, self.CSS, font=None)
        with pytest.raises(AssetError, match=r"No \.ttf"):
            read_icon_font_dir(directory)

    def test_an_unrelated_stylesheet_does_not_pass_silently(self, tmp_path):
        # Failing loudly matters: a silent fallback is indistinguishable from
        # the glyphs simply not rendering.
        directory = self._dir(tmp_path, "body{color:red}")
        with pytest.raises(AssetError, match="no client glyph codepoints"):
            read_icon_font_dir(directory)

    def test_a_path_that_is_not_a_directory_is_refused(self, tmp_path):
        loose = tmp_path / "ubnt.ttf"
        loose.write_bytes(b"x")
        with pytest.raises(AssetError, match="not a directory"):
            read_icon_font_dir(loose)


class TestIspBrandMark:
    """Provider logos, keyed on ASN.

    Ubiquiti derive these from the autonomous system number alone, so there is
    no provider table here to go stale.
    """

    def test_no_asn_means_no_request(self, tmp_path, monkeypatch):
        store = AssetStore(cache_dir=tmp_path / "cache")

        def explode(*args, **kwargs):  # pragma: no cover - must never run
            raise AssertionError("isp_logo() made a network request for a null ASN")

        monkeypatch.setattr("unifi_map.assets.requests.get", explode)
        assert store.isp_logo(None) is None

    def test_offline_yields_nothing_rather_than_failing(self, tmp_path):
        assert AssetStore(cache_dir=tmp_path / "cache", offline=True).isp_logo(7018) is None


class TestInternetCloud:
    """The generic Internet icon, drawn locally rather than fetched.

    It stands in wherever there is no brand mark: an ASN Ubiquiti have no logo
    for, and every obfuscated map.
    """

    def test_it_is_drawn_without_any_network(self, tmp_path, monkeypatch):
        store = AssetStore(cache_dir=tmp_path / "cache", offline=True)

        def explode(*args, **kwargs):  # pragma: no cover - must never run
            raise AssertionError("internet_icon() made a network request")

        monkeypatch.setattr("unifi_map.assets.requests.get", explode)
        asset = store.internet_icon("#5A626E")
        assert asset is not None
        assert asset.path.is_file()

    def test_it_is_wider_than_it_is_tall(self, tmp_path):
        # A cloud in a square cell would letterbox, the same reason rack
        # switches carry their real aspect ratio.
        asset = AssetStore(cache_dir=tmp_path / "cache").internet_icon("#5A626E")
        assert asset.width > asset.height

    def test_the_second_call_reuses_the_cached_file(self, tmp_path):
        store = AssetStore(cache_dir=tmp_path / "cache")
        first = store.internet_icon("#5A626E")
        stamp = first.path.stat().st_mtime_ns
        second = store.internet_icon("#5A626E")
        assert second.path == first.path
        assert second.path.stat().st_mtime_ns == stamp

    def test_each_colour_gets_its_own_file(self, tmp_path):
        # Light and dark themes must not share one cached image.
        store = AssetStore(cache_dir=tmp_path / "cache")
        assert store.internet_icon("#5A626E").path != store.internet_icon("#AAB2BF").path


class TestNetworkFailure:
    """What happens when the CDN is unreachable.

    Two things matter: the run must still finish with a usable diagram, and it
    must not spend an hour discovering that the network is down.
    """

    def _store(self, tmp_path):
        return AssetStore(cache_dir=tmp_path / "cache")

    def _break(self, monkeypatch, exc):
        calls = []

        def fake_get(url, **kwargs):
            calls.append(url)
            raise exc

        monkeypatch.setattr("unifi_map.assets.requests.get", fake_get)
        return calls

    def test_one_failure_stops_the_whole_run_trying(self, tmp_path, monkeypatch):
        # Without this, a 48-client map issues 117 requests and waits out a
        # separate timeout on every one of them.
        calls = self._break(monkeypatch, requests.ConnectionError("boom"))
        store = self._store(tmp_path)
        store.catalog()
        for dev_id in range(20):
            store.client_icon(dev_id)
        store.isp_logo(7018)
        assert len(calls) == 1, f"kept trying after the first failure: {len(calls)} requests"

    def test_it_says_what_went_wrong_in_one_short_line(self, tmp_path, monkeypatch, caplog):
        self._break(
            monkeypatch,
            requests.ConnectionError(
                "HTTPSConnectionPool(host='static.ui.com', port=443): Max retries exceeded "
                "with url: /x (Caused by NewConnectionError('<urllib3.connection."
                "HTTPSConnection object at 0x7f3a1c0d4e50>: Failed to establish a new "
                "connection: [Errno -3] Temporary failure in name resolution'))"
            ),
        )
        with caplog.at_level("WARNING"):
            self._store(tmp_path).catalog()
        message = caplog.text
        assert "the name could not be resolved" in message
        # The raw exception is a three-layer nested repr with an object address.
        assert "urllib3" not in message
        assert "0x7f3a" not in message

    def test_a_404_does_not_trip_the_breaker(self, tmp_path, monkeypatch):
        # One missing asset says nothing about the next. Only transport
        # failures mean the CDN is unreachable.
        calls = []

        class Missing:
            status_code = 404
            content = b""
            headers: ClassVar[dict[str, str]] = {}

            # Streamed like a real response; an empty body still has to be
            # iterable now that the reader is bounded rather than eager.
            def iter_content(self, chunk_size=8192):
                return iter(())

            def close(self):
                return None

        def fake_get(url, **kwargs):
            calls.append(url)
            return Missing()

        monkeypatch.setattr("unifi_map.assets.requests.get", fake_get)
        store = self._store(tmp_path)
        store.client_icon(1)
        store.client_icon(2)
        assert len(calls) > 2, "a 404 should not stop later lookups"

    @pytest.mark.parametrize(
        ("exc", "expected"),
        [
            (requests.exceptions.ConnectTimeout(), "timed out connecting"),
            (requests.exceptions.ReadTimeout(), "timed out waiting for a reply"),
            (requests.exceptions.Timeout(), "timed out"),
            (requests.exceptions.SSLError(), "TLS verification failed"),
            (requests.ConnectionError("NameResolutionError"), "the name could not be resolved"),
            (requests.ConnectionError("nodename nor servname"), "the name could not be resolved"),
            (requests.ConnectionError("Connection refused"), "the connection was refused"),
            (requests.ConnectionError("No route to host"), "there is no route to that host"),
            (requests.ConnectionError("Network is unreachable"), "the network is unreachable"),
            (requests.ConnectionError("something else entirely"), "the connection failed"),
            (ValueError(), "the reply was not valid JSON"),
            (RuntimeError(), "RuntimeError"),
        ],
    )
    def test_each_common_failure_gets_plain_words(self, exc, expected):
        assert describe_network_error(exc) == expected


class TestResourceLimits:
    """Artwork arrives from a CDN or from a user-supplied override path."""

    class _Streamed:
        """A response shaped like the streaming ones the code now requests.

        The doubles here used to expose only `.content`, which matched a plain
        `requests.get`. Downloads are streamed now precisely so an oversized body
        is never fully resident, so the double has to stream too or the test
        would be asserting against an interface the code no longer uses.
        """

        status_code = 200

        def __init__(self, body: bytes, declared: str | None = None):
            self._body = body
            self.headers = {"Content-Length": declared} if declared is not None else {}
            self.closed = False
            self.chunks_served = 0

        def iter_content(self, chunk_size=8192):
            for start in range(0, len(self._body), chunk_size):
                self.chunks_served += 1
                yield self._body[start : start + chunk_size]

        def close(self):
            self.closed = True

        def raise_for_status(self):
            return None

    def test_an_oversized_response_is_not_treated_as_artwork(self, tmp_path, monkeypatch):
        from unifi_map.assets import MAX_ASSET_BYTES

        response = self._Streamed(b"x" * 16, declared=str(MAX_ASSET_BYTES + 1))
        monkeypatch.setattr("unifi_map.assets.requests.get", lambda *a, **k: response)
        assert AssetStore(cache_dir=tmp_path / "c").client_icon(1) is None
        # Refused on the declared length, so the body is never read at all.
        assert response.chunks_served == 0
        assert response.closed

    def test_a_lying_content_length_is_still_caught(self, tmp_path, monkeypatch):
        from unifi_map.assets import MAX_ASSET_BYTES

        response = self._Streamed(b"x" * (MAX_ASSET_BYTES + 1), declared="10")
        monkeypatch.setattr("unifi_map.assets.requests.get", lambda *a, **k: response)
        assert AssetStore(cache_dir=tmp_path / "c").client_icon(1) is None

    def test_reading_stops_at_the_cap_rather_than_after_it(self, tmp_path, monkeypatch):
        # The point of streaming: a body twice the cap must not be buffered
        # whole before being rejected.
        from unifi_map.assets import MAX_ASSET_BYTES

        response = self._Streamed(b"x" * (MAX_ASSET_BYTES * 2), declared=None)
        monkeypatch.setattr("unifi_map.assets.requests.get", lambda *a, **k: response)
        assert AssetStore(cache_dir=tmp_path / "c").client_icon(1) is None
        assert response.closed
        served = response.chunks_served * 64 * 1024
        assert served <= MAX_ASSET_BYTES + 64 * 1024, f"buffered {served} bytes past the cap"

    def test_the_pillow_bomb_threshold_is_tightened(self):
        from PIL import Image

        from unifi_map.assets import MAX_IMAGE_PIXELS, _pillow_image

        _pillow_image()
        assert Image.MAX_IMAGE_PIXELS == MAX_IMAGE_PIXELS


class TestFetchDoesNotDependOnRequestsInternals:
    """`_fetch` returns our own object, not a hand-modified `requests.Response`.

    The body is streamed through a size cap rather than read by `requests`, so
    handing back a `Response` meant assigning `_content` and `_content_consumed`
    ourselves. Two private attributes of somebody else's library is a poor thing
    to depend on for a feature that only needs three fields.
    """

    def test_it_is_not_a_requests_response(self, tmp_path, monkeypatch):
        import requests

        from unifi_map.assets import Fetched

        captured = {}

        class Streamed:
            status_code = 200
            headers: ClassVar[dict[str, str]] = {}

            def iter_content(self, chunk_size=8192):
                yield b"payload"

            def close(self):
                return None

        monkeypatch.setattr("unifi_map.assets.requests.get", lambda *a, **k: Streamed())
        store = AssetStore(cache_dir=tmp_path / "c")
        captured["r"] = store._fetch("https://example.invalid/x")
        assert isinstance(captured["r"], Fetched)
        assert not isinstance(captured["r"], requests.Response)
        assert captured["r"].content == b"payload"

    def test_raise_for_status_still_raises_what_callers_catch(self):
        import requests

        from unifi_map.assets import Fetched

        Fetched(status_code=200, content=b"", url="u").raise_for_status()
        missing = Fetched(status_code=404, content=b"", url="u")
        with pytest.raises(requests.RequestException):
            missing.raise_for_status()


class TestColdCacheDownload:
    """The successful download path, which nothing exercised.

    Every existing catalogue test either seeded the cache or simulated a
    transport failure, so the one branch a new user hits first, a reachable CDN
    and an empty cache, was never run. It was broken: `_fetch` returns
    `Fetched`, which is not a `requests.Response` and has no `json()`, and the
    resulting AttributeError was not caught by the surrounding clause.
    """

    def _store(self, tmp_path, payload: bytes, monkeypatch):
        from unifi_map import assets

        store = assets.AssetStore(cache_dir=tmp_path)
        monkeypatch.setattr(
            assets.AssetStore,
            "_fetch",
            lambda self, url, **kw: assets.Fetched(status_code=200, content=payload, url=url),
        )
        return store

    def test_a_reachable_cdn_and_an_empty_cache_produces_a_catalogue(self, tmp_path, monkeypatch):
        import json as _json

        payload = _json.dumps({"devices": [{"sysid": "ea11", "shortnames": ["X"]}]}).encode()
        store = self._store(tmp_path, payload, monkeypatch)
        # Keyed by sysid as an int; 0xea11 is 59921. Reaching this at all is
        # the point: it used to raise AttributeError before returning.
        assert store.catalog() == {59921: {"sysid": "ea11", "shortnames": ["X"]}}

    def test_the_download_is_cached_for_next_time(self, tmp_path, monkeypatch):
        import json as _json

        payload = _json.dumps({"devices": []}).encode()
        store = self._store(tmp_path, payload, monkeypatch)
        store.catalog()
        assert store.catalog_path.is_file(), "nothing was written to the cache"

    def test_a_catalogue_that_is_not_an_object_is_refused(self, tmp_path, monkeypatch):
        # A JSON array parses fine and is not a catalogue. Artwork degrades
        # rather than failing the run, so this is an empty map, not an error.
        store = self._store(tmp_path, b"[1, 2, 3]", monkeypatch)
        assert store.catalog() == {}

    def test_malformed_json_degrades_rather_than_raising(self, tmp_path, monkeypatch):
        store = self._store(tmp_path, b"{not json", monkeypatch)
        assert store.catalog() == {}


class TestOversizedImagesAndNonPngArtwork:
    """Two things a user-supplied override file can be."""

    def _bomb(self, tmp_path):
        """A small file that decodes to more than MAX_IMAGE_PIXELS."""
        from PIL import Image

        from unifi_map import assets

        path = tmp_path / "bomb.png"
        side = int(assets.MAX_IMAGE_PIXELS**0.5) + 2000
        # Solid colour, so it compresses to almost nothing on disk.
        Image.new("RGBA", (side, side), (0, 0, 0, 0)).save(path, "PNG")
        return path

    def test_an_oversized_image_is_refused_rather_than_raising(self, tmp_path):
        """`MAX_IMAGE_PIXELS` alone is a warning threshold, not a limit: Pillow
        raises only at roughly twice it, and neither bomb type derives from
        OSError or ValueError, so both escaped `_measure` uncaught."""
        from unifi_map.assets import _measure

        assert _measure(self._bomb(tmp_path)) is None

    def test_the_size_guard_does_not_leak_into_global_warning_state(self, tmp_path):
        """Scoped with `catch_warnings`. A bare `simplefilter` is process-global
        and would change warning behaviour for anything else in the process."""
        import warnings

        from unifi_map.assets import _measure

        with warnings.catch_warnings(record=True) as seen:
            warnings.simplefilter("always")
            _measure(self._bomb(tmp_path))
            # Filters restored, so this one is still merely recorded.
            warnings.warn("ordinary", UserWarning, stacklevel=1)
        assert any(w.category is UserWarning for w in seen)

    def test_an_svg_override_is_usable(self, tmp_path):
        """`docs/overrides.md` documents SVG as acceptable artwork. It was not:
        measuring went through Pillow, which does not decode SVG, so every SVG
        was rejected before Graphviz ever saw it."""
        from unifi_map.assets import local_icon

        path = tmp_path / "icon.svg"
        # The XML declaration is required: without it Graphviz refuses the file
        # and the render fails, so accepting it here would trade a missing icon
        # for a broken run. This test asserted the version without one.
        path.write_text(
            '<?xml version="1.0"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" width="64px" height="32px"></svg>',
            encoding="utf-8",
        )
        asset = local_icon(path)
        assert (asset.width, asset.height) == (64, 32)

    def test_an_svg_without_explicit_dimensions_is_refused(self, tmp_path):
        """Graphviz silently ignores one with only a `viewBox`, so refusing it
        here turns a blank node into an error naming the file."""
        from unifi_map.assets import AssetError, local_icon

        path = tmp_path / "icon.svg"
        path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 32"></svg>',
            encoding="utf-8",
        )
        with pytest.raises(AssetError):
            local_icon(path)

    def test_inlined_artwork_declares_its_real_media_type(self, tmp_path):
        """The href pattern was widened to every image type while the data URI
        still said PNG, so a JPEG or SVG was embedded correctly and labelled
        wrongly."""
        from unifi_map.svg_post import inline_svg_images

        icon = tmp_path / "icon.svg"
        icon.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="8px" height="8px"/>', "utf-8"
        )
        svg = f'<image href="{icon}"/>'.encode()
        out = inline_svg_images(svg, [icon]).decode()
        assert "data:image/svg+xml;base64," in out
        assert str(icon) not in out, "the absolute path survived, which is the disclosure"


class TestSvgRendersNotJustMeasures:
    """Measuring an SVG is not evidence Graphviz will draw it.

    The first version checked only that dimensions could be read, and happily
    accepted a standards-valid SVG that Graphviz then refused with "was not
    found as a file", failing the whole render. Accepting an icon that breaks
    the run is worse than refusing it.
    """

    HEAD = '<?xml version="1.0"?>'
    BODY = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="64px" height="32px">'
        '<rect width="64" height="32" fill="#888"/></svg>'
    )

    @pytest.mark.skipif(shutil.which("dot") is None, reason="graphviz `dot` not installed")
    def test_an_accepted_svg_actually_renders(self, tmp_path):
        from unifi_map.assets import local_icon

        icon = tmp_path / "icon.svg"
        icon.write_text(self.HEAD + self.BODY, encoding="utf-8")
        assert local_icon(icon) is not None

        dot = (
            'digraph{n[shape=none,label=<<TABLE BORDER="0"><TR><TD>'
            f'<IMG SRC="{icon}"/></TD></TR></TABLE>>];}}'
        )
        # Graphviz reports a rejected image as a warning on **stderr** and
        # still exits 0. `run_dot` returns stdout and discards stderr on
        # success, so asserting against its return value could never fail: the
        # first version of this test passed for a file Graphviz had refused.
        # Run it directly so the warning is visible.
        result = subprocess.run(
            [shutil.which("dot"), "-Tsvg"],
            input=dot.encode(),
            capture_output=True,
            check=True,
        )
        stderr = result.stderr.decode("utf-8", errors="replace")
        assert "was not found" not in stderr, f"Graphviz refused the icon: {stderr.strip()}"
        assert result.stdout

    @pytest.mark.parametrize(
        "body,why",
        [
            (BODY, "no XML declaration: Graphviz refuses it and fails the render"),
            (HEAD + '<svg width="." height="5"/>', "not a number"),
            (HEAD + "<svg/>", "no dimensions and no viewBox"),
            (HEAD + '<svg viewBox="0 0 64"/>', "viewBox with too few numbers"),
            (HEAD + '<svg width="0" height="10"/>', "zero width"),
            (HEAD + '<svg width="-4" height="10"/>', "negative width"),
        ],
    )
    def test_an_svg_graphviz_would_reject_is_refused_here(self, tmp_path, body, why):
        from unifi_map.assets import AssetError, local_icon

        icon = tmp_path / "icon.svg"
        icon.write_text(body, encoding="utf-8")
        with pytest.raises(AssetError):
            local_icon(icon)

    def test_rasterising_makes_the_xml_declaration_irrelevant(self, tmp_path):
        """The whole point of the `svg` extra, and it removes a workaround.

        Graphviz demands the declaration; CairoSVG does not. So with the extra
        installed a file that would otherwise be refused works untouched, and
        nothing has to write a corrected copy into the user's own directory.
        """
        pytest.importorskip("cairosvg")
        from unifi_map.assets import local_icon

        icon = tmp_path / "icon.svg"
        # No declaration, and no width/height either: refused without the extra.
        icon.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 32">'
            '<rect width="64" height="32" fill="#888"/></svg>',
            encoding="utf-8",
        )
        asset = local_icon(icon, cache_dir=tmp_path / "cache")
        assert asset.path.suffix == ".png"
        assert asset.path.is_file()

    def test_the_raster_is_private_unlike_the_rest_of_the_cache(self, tmp_path):
        """A rendering of the user's own file is not public CDN artwork.

        Everything else in the artwork cache is Ubiquiti's imagery, written
        0644 because there is nothing to protect. This one is derived from a
        file the user supplied, which may itself be private, so writing a
        world-readable copy would change their exposure without being asked.

        Directory as well as file: a 0600 file under a 0755 parent still leaks
        its name, and the name is a hash of their artwork.
        """
        pytest.importorskip("cairosvg")
        import os
        import stat

        from unifi_map.assets import local_icon

        if os.name != "posix":
            pytest.skip("POSIX modes only")

        cache = tmp_path / "cache"
        icon = tmp_path / "icon.svg"
        icon.write_text(
            '<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 32"/>',
            encoding="utf-8",
        )
        asset = local_icon(icon, cache_dir=cache)

        file_mode = stat.S_IMODE(asset.path.stat().st_mode)
        dir_mode = stat.S_IMODE(asset.path.parent.stat().st_mode)
        assert not file_mode & 0o077, f"raster is group/world readable: {file_mode:o}"
        assert not dir_mode & 0o077, f"user-svg dir is traversable: {dir_mode:o}"

    def test_a_cache_left_public_by_an_earlier_version_is_repaired(self, tmp_path):
        """The permission fix has to reach caches that already exist.

        Before rasters were made private the directory was created at the umask
        and the PNG written 0644. Neither `mkdir_private` nor the "already
        rendered, skip" path would ever touch them again, so an upgraded
        checkout kept a world-readable copy of the user's artwork forever. The
        original regression test only covered a cache created from scratch.
        """
        pytest.importorskip("cairosvg")
        import os
        import stat

        from unifi_map.assets import local_icon

        if os.name != "posix":
            pytest.skip("POSIX modes only")

        cache = tmp_path / "cache"
        icon = tmp_path / "icon.svg"
        icon.write_text(
            '<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 32"/>',
            encoding="utf-8",
        )

        # Render once, then put it back the way the old code left it.
        first = local_icon(icon, cache_dir=cache).path
        first.parent.chmod(0o755)
        first.chmod(0o644)

        again = local_icon(icon, cache_dir=cache).path
        assert not stat.S_IMODE(again.stat().st_mode) & 0o077
        assert not stat.S_IMODE(again.parent.stat().st_mode) & 0o077

    @pytest.mark.parametrize("link_is_dir", [True, False])
    def test_the_repair_refuses_to_follow_a_symlink(self, tmp_path, link_is_dir):
        """A link in the cache must not redirect the chmod onto its target.

        `Path.chmod()` follows links, so before this a symlink planted at
        `user-svg/` or at one of its PNGs made the repair strip permissions from
        whatever it pointed at. Nothing is disclosed — access is removed, not
        granted — but an unrelated path loses group or world access, and in a
        cache directory somebody else can write to that is a local
        denial-of-service primitive.

        Both shapes are covered because the directory and the file take
        different branches: one is opened as a directory, one as a file.
        """
        pytest.importorskip("cairosvg")
        import os

        from unifi_map.assets import _make_private

        if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
            pytest.skip("needs POSIX modes and O_NOFOLLOW")

        if link_is_dir:
            victim = tmp_path / "victim-dir"
            victim.mkdir()
            expected = 0o755
        else:
            victim = tmp_path / "victim-file"
            victim.write_text("not yours", encoding="utf-8")
            expected = 0o644
        victim.chmod(expected)

        link = tmp_path / "link"
        link.symlink_to(victim)
        _make_private(link)

        assert stat.S_IMODE(victim.stat().st_mode) == expected
        assert link.is_symlink(), "the link itself should still be a link"

    def test_the_raster_keeps_the_aspect_ratio(self, tmp_path):
        pytest.importorskip("cairosvg")
        from unifi_map.assets import local_icon

        icon = tmp_path / "wide.svg"
        icon.write_text(
            '<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" '
            'viewBox="0 0 64 16"><rect width="64" height="16" fill="#888"/></svg>',
            encoding="utf-8",
        )
        asset = local_icon(icon, cache_dir=tmp_path / "cache")
        assert asset.width > asset.height * 3

    def test_editing_the_source_produces_a_new_raster(self, tmp_path):
        """Cached on a hash of the contents, so a stale hit is not possible."""
        pytest.importorskip("cairosvg")
        from unifi_map.assets import local_icon

        cache = tmp_path / "cache"
        icon = tmp_path / "icon.svg"
        head = '<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" '
        icon.write_text(head + 'viewBox="0 0 64 32"/>', encoding="utf-8")
        first = local_icon(icon, cache_dir=cache).path
        icon.write_text(head + 'viewBox="0 0 32 64"/>', encoding="utf-8")
        second = local_icon(icon, cache_dir=cache).path
        assert first != second

    def test_without_the_extra_the_svg_is_used_as_is(self, tmp_path, monkeypatch):
        """Degrades to today's behaviour rather than failing the run."""
        import builtins

        from unifi_map.assets import local_icon

        real_import = builtins.__import__

        def no_cairosvg(name, *args, **kwargs):
            if name == "cairosvg":
                raise ImportError("simulated: extra not installed")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", no_cairosvg)

        icon = tmp_path / "icon.svg"
        icon.write_text(self.HEAD + '<svg width="64" height="32"/>', encoding="utf-8")
        asset = local_icon(icon, cache_dir=tmp_path / "cache")
        assert asset.path == icon

    def test_a_viewbox_supplies_the_size_when_width_and_height_are_absent(self, tmp_path):
        """How most drawing tools export, and Graphviz renders them fine.

        Previously refused for lacking explicit dimensions, which was stricter
        than the thing being protected against. Verified by rendering one
        through `dot` before relaxing it, not by reading a spec.
        """
        from unifi_map.assets import local_icon

        icon = tmp_path / "icon.svg"
        icon.write_text(
            self.HEAD + '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 486.2 497.8"/>',
            encoding="utf-8",
        )
        asset = local_icon(icon)
        assert (asset.width, asset.height) == (486, 498)

    def test_explicit_dimensions_win_over_a_viewbox(self, tmp_path):
        from unifi_map.assets import local_icon

        icon = tmp_path / "icon.svg"
        icon.write_text(
            self.HEAD + '<svg width="64" height="32" viewBox="0 0 999 111"/>',
            encoding="utf-8",
        )
        asset = local_icon(icon)
        assert (asset.width, asset.height) == (64, 32)

    def test_viewbox_fallback_distinguishes_missing_from_invalid_dimensions(self, tmp_path):
        from unifi_map.assets import AssetError, local_icon

        partial = tmp_path / "partial.svg"
        partial.write_text(self.HEAD + '<svg width="999" viewBox="0 0 64 32"/>', encoding="utf-8")
        asset = local_icon(partial)
        assert (asset.width, asset.height) == (64, 32)

        invalid = tmp_path / "invalid.svg"
        invalid.write_text(
            self.HEAD + '<svg width="." height="32" viewBox="0 0 64 32"/>',
            encoding="utf-8",
        )
        with pytest.raises(AssetError):
            local_icon(invalid)

    def test_the_refusal_says_which_rule_was_broken(self, tmp_path):
        """ "Could not read" on a file the user can open is a shrug, not an error."""
        from unifi_map.assets import AssetError, local_icon

        icon = tmp_path / "icon.svg"
        icon.write_text(self.BODY, encoding="utf-8")  # no XML declaration
        with pytest.raises(AssetError, match="declaration"):
            local_icon(icon)

    def test_a_fractional_size_never_rounds_to_nothing(self, tmp_path):
        """`int(0.5)` is 0, and a 0x0 icon is drawn as nothing at all."""
        from unifi_map.assets import local_icon

        icon = tmp_path / "icon.svg"
        icon.write_text(self.HEAD + '<svg width="0.5px" height="0.5px"/>', encoding="utf-8")
        asset = local_icon(icon)
        assert asset.width >= 1
        assert asset.height >= 1


def test_an_oversized_download_is_refused_too(tmp_path):
    """The size guard went on `_measure` and not on `_downscale`, which is the
    path that decodes bytes straight off the network."""
    from io import BytesIO

    from PIL import Image

    from unifi_map import assets

    side = int(assets.MAX_IMAGE_PIXELS**0.5) + 2000
    buffer = BytesIO()
    Image.new("RGBA", (side, side), (0, 0, 0, 0)).save(buffer, "PNG")

    raw = buffer.getvalue()
    with pytest.raises(assets.AssetError):
        assets._downscale(raw, tmp_path / "out.png", 256)


def test_an_xml_escaped_path_is_still_inlined(tmp_path):
    """Graphviz writes the path into an XML attribute, so `&` arrives as
    `&amp;`. Compared literally it never matched the permitted set, and the
    absolute path stayed in the output: the disclosure the function prevents."""
    from unifi_map.svg_post import inline_svg_images

    icon = tmp_path / "private&name.png"
    icon.write_bytes(b"\x89PNG\r\n\x1a\n")
    svg = f'<image href="{str(icon).replace("&", "&amp;")}"/>'.encode()

    out = inline_svg_images(svg, [icon]).decode()
    assert "data:image/png;base64," in out
    assert "private" not in out.split("data:")[0], "the path survived alongside the data URI"


def test_svg_dimensions_come_from_the_root_element(tmp_path):
    """A child element must not decide the icon's size.

    The pattern scanned the whole file head, so the last match won: a 64x32
    drawing containing `<rect width="7" height="5"/>` measured as 7x5, and the
    icon rendered at a twelfth of its intended size.
    """
    from unifi_map.assets import local_icon

    icon = tmp_path / "icon.svg"
    icon.write_text(
        '<?xml version="1.0"?>\n'
        '<svg width="64" height="32">\n  <rect width="7" height="5"/>\n</svg>',
        encoding="utf-8",
    )
    asset = local_icon(icon)
    assert (asset.width, asset.height) == (64, 32)
