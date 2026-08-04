"""Artwork source selection and caching."""

from unifi_map.artwork import resolve_icons
from unifi_map.assets import IconAsset
from unifi_map.model import Kind, Node, Topology
from unifi_map.theme import LIGHT


class _Store:
    def __init__(self, fingerprint: IconAsset, hardware: IconAsset, glyph: IconAsset):
        self.fingerprint = fingerprint
        self.hardware = hardware
        self.glyph = glyph
        self.client_icon_calls: list[int] = []
        self.client_glyph_calls: list[str] = []
        self.hardware_name_calls: list[str] = []

    def client_icon(self, dev_id: int):
        self.client_icon_calls.append(dev_id)
        return self.fingerprint if dev_id == 7 else None

    def client_glyph(self, name: str, color: str):
        self.client_glyph_calls.append(name)
        return self.glyph

    def sysid_for_name(self, name: str, device_type: str | None = None):
        self.hardware_name_calls.append(name)
        return 55 if name == "camera" and device_type == "camera" else None

    def icon(self, sysid: int):
        return self.hardware if sysid == 55 else None

    def product_name(self, sysid: int):
        return "Camera" if sysid == 55 else None

    def isp_logo(self, asn: int | None):
        return None

    def internet_icon(self, color: str):
        return None


def _asset(tmp_path, name: str) -> IconAsset:
    return IconAsset(path=tmp_path / name, width=32, height=24)


def test_client_sources_keep_their_precedence_and_share_cached_glyphs(tmp_path):
    fingerprint = _asset(tmp_path, "fingerprint.png")
    hardware = _asset(tmp_path, "hardware.png")
    glyph = _asset(tmp_path, "glyph.png")
    store = _Store(fingerprint, hardware, glyph)
    topo = Topology(
        nodes={
            "fingerprint": Node(
                "fingerprint",
                "fingerprinted camera",
                Kind.WIRED_CLIENT,
                dev_id=7,
                hardware_type="camera",
            ),
            "hardware": Node("hardware", "camera", Kind.WIRED_CLIENT, hardware_type="camera"),
            "glyph-1": Node("glyph-1", "client one", Kind.WIRED_CLIENT),
            "glyph-2": Node("glyph-2", "client two", Kind.WIRED_CLIENT),
        }
    )
    counts: dict[str, int] = {}

    icons = resolve_icons(topo, store, LIGHT, counts)

    assert icons == {
        "fingerprint": fingerprint,
        "hardware": hardware,
        "glyph-1": glyph,
        "glyph-2": glyph,
    }
    assert store.client_icon_calls == [7]
    assert store.hardware_name_calls == ["camera"]
    assert store.client_glyph_calls == ["user-wired"]
    assert counts == {
        "device_found": 0,
        "device_total": 0,
        "client_total": 4,
        "client_found": 4,
        "from_fingerprint": 1,
        "from_hardware": 1,
        "from_glyph": 2,
    }
