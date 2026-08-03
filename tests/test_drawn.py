"""Icons this project draws itself.

Nothing here touches the network, which is most of the point: these exist so
`--icons builtin` and any device missing from Ubiquiti's catalogue get a picture
rather than a Graphviz primitive, without fetching anything.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from unifi_map import drawn
from unifi_map.assets import AssetStore

COLOR = "#4c4c4c"
DEMO = Path(__file__).resolve().parent.parent / "examples" / "demo"


@pytest.fixture
def store(tmp_path):
    return AssetStore(cache_dir=tmp_path)


class TestDrawing:
    @pytest.mark.parametrize("name", drawn.NAMES)
    def test_every_declared_icon_actually_draws(self, store, name):
        """`NAMES` is what the resolver iterates, so a name with no drawing
        behind it is a node that silently keeps its bare shape."""
        asset = store.drawn_icon(name, COLOR)
        assert asset is not None, f"{name} did not draw"
        assert asset.path.is_file()
        assert asset.width > 0 and asset.height > 0

    def test_an_unknown_name_raises_rather_than_guessing(self, tmp_path):
        """Same rule as `local_icon()`: never substitute a different picture.

        A wrong icon is worse than a missing one, because a missing one is
        visible as a fallback shape and a wrong one just looks like a fact.
        """
        with pytest.raises(ValueError, match="no drawn icon named"):
            drawn.render("router-deluxe", COLOR, tmp_path / "x.png", 64)

    def test_the_store_degrades_instead_of_raising(self, store):
        """Artwork must never fail a run, so the store swallows what `render`
        raises and returns None, which puts the node back on a shape."""
        assert store.drawn_icon("router-deluxe", COLOR) is None


class TestShape:
    """The constraints that stop these looking wrong beside real artwork."""

    def test_a_switch_is_wide_and_short(self, store):
        """Rack gear has a real aspect ratio and `display_size()` honours it.

        Forcing a switch into a square cell letterboxes it into a thin strip
        surrounded by dead space, which is the specific failure that made
        aspect ratio part of `IconAsset` in the first place.
        """
        switch = store.drawn_icon("switch", COLOR)
        assert switch.width > switch.height * 3

    def test_a_wireless_client_is_taller_than_wide(self, store):
        # A handset, and the only tall icon in the set, so it is separable from
        # the boxy ones by outline alone.
        phone = store.drawn_icon("user-wireless", COLOR)
        assert phone.height > phone.width

    def test_an_access_point_is_round_and_square_in_the_box(self, store):
        ap = store.drawn_icon("ap", COLOR)
        assert ap.width == ap.height

    @pytest.mark.parametrize(
        "pair", [("user-wired", "guest-wired"), ("user-wireless", "guest-wireless")]
    )
    def test_guest_differs_from_user_by_shape_not_colour(self, store, pair):
        """Guest is hollow, and that has to be a silhouette difference.

        Colour is never the only channel in this project: the palette has to
        survive greyscale and deuteran vision, and guest is exactly the
        distinction somebody would reach for a second hue to carry. Compared as
        pixels, drawn in the same colour, so only the shape can differ.
        """
        from PIL import Image

        user, guest = (store.drawn_icon(n, COLOR) for n in pair)
        a = Image.open(user.path).convert("RGBA")
        b = Image.open(guest.path).convert("RGBA")
        assert a.size == b.size, "the pair must be the same silhouette, differently filled"
        solid, hollow = a.getchannel("A"), b.getchannel("A")
        assert solid.tobytes() != hollow.tobytes(), "guest is indistinguishable from user"
        # Hollow means strictly less ink, which is what "outline" amounts to.
        assert sum(hollow.tobytes()) < sum(solid.tobytes())

    def test_every_icon_has_a_distinct_silhouette(self, store):
        """No two icons may render identically, or the map says less than it
        appears to. Compared as alpha masks, so colour cannot rescue a tie."""
        from PIL import Image

        seen: dict[bytes, str] = {}
        for name in drawn.NAMES:
            asset = store.drawn_icon(name, COLOR)
            mask = Image.open(asset.path).convert("RGBA").getchannel("A").tobytes()
            assert mask not in seen, f"{name} is identical to {seen.get(mask)}"
            seen[mask] = name


class TestCaching:
    def test_each_colour_caches_separately(self, store):
        """Sharing one file would put a dark icon on a dark canvas.

        The same bug the cloud already had to avoid; the theme colour is part of
        the cache key for exactly this reason.
        """
        light = store.drawn_icon("switch", "#4c4c4c")
        dark = store.drawn_icon("switch", "#c8c8c8")
        assert light.path != dark.path
        assert light.path.read_bytes() != dark.path.read_bytes()

    def test_a_second_call_reuses_the_file(self, store):
        first = store.drawn_icon("ap", COLOR)
        stamp = first.path.stat().st_mtime_ns
        second = store.drawn_icon("ap", COLOR)
        assert second.path == first.path
        assert second.path.stat().st_mtime_ns == stamp, "redrawn instead of read from cache"

    def test_nothing_is_fetched(self, store, monkeypatch):
        """These exist so the network-free path has artwork. If drawing one ever
        needed a request, `--offline` and support-file mode would both regress.
        """
        import requests

        def explode(*args, **kwargs):
            raise AssertionError("drawing an icon made a network request")

        monkeypatch.setattr(requests.Session, "get", explode)
        monkeypatch.setattr(requests, "get", explode)
        for name in drawn.NAMES:
            assert store.drawn_icon(name, COLOR) is not None


class TestUsedByTheRenderer:
    """Where the icons actually land, which is the part a user sees."""

    def test_builtin_gives_every_node_a_picture(self, tmp_path):
        """`--icons builtin` used to mean no artwork at all, so every node fell
        through to a Graphviz primitive. It now means artwork we drew rather
        than artwork fetched from Ubiquiti."""
        from unifi_map.cli import _apply_drawn_icons
        from unifi_map.client import Snapshot
        from unifi_map.model import Kind, build_topology
        from unifi_map.theme import LIGHT

        topo = build_topology(Snapshot.read(DEMO))
        icons: dict = {}
        _apply_drawn_icons(topo, AssetStore(cache_dir=tmp_path), LIGHT, icons)

        # Internet is excluded: it has a brand mark or the cloud, not a kind icon.
        expected = {n.id for n in topo.nodes.values() if n.kind is not Kind.INTERNET}
        assert set(icons) == expected

    def test_drawn_never_displaces_real_artwork(self, tmp_path):
        """Last resort, and it has to stay last. Ubiquiti's product render is a
        picture of the actual hardware; ours is a generic drawing of its role.
        """
        from unifi_map.assets import IconAsset
        from unifi_map.cli import _apply_drawn_icons
        from unifi_map.client import Snapshot
        from unifi_map.model import build_topology
        from unifi_map.theme import LIGHT

        topo = build_topology(Snapshot.read(DEMO))
        taken = next(iter(topo.nodes))
        sentinel = IconAsset(path=Path("/real/product.png"), width=10, height=10)
        icons = {taken: sentinel}

        _apply_drawn_icons(topo, AssetStore(cache_dir=tmp_path), LIGHT, icons)
        assert icons[taken] is sentinel

    def test_the_renderer_no_longer_discards_them(self, tmp_path):
        """`render_dot` gated on `style.icons == "unifi"` and threw the dict
        away otherwise, so the icons drew correctly and never reached the map.

        That gate also silently dropped icons a user supplied through an
        overrides file, which are not fetched from anywhere either.
        """
        from unifi_map.client import Snapshot
        from unifi_map.model import build_topology
        from unifi_map.render_dot import Style, render_dot
        from unifi_map.theme import LIGHT

        topo = build_topology(Snapshot.read(DEMO))
        store = AssetStore(cache_dir=tmp_path)
        icons: dict = {}
        from unifi_map.cli import _apply_drawn_icons

        _apply_drawn_icons(topo, store, LIGHT, icons)

        assert icons, "nothing was drawn, so this proves nothing"
        style = Style(theme=LIGHT, icons="builtin", layout="tree")
        dot = render_dot(topo, "Network map", style, icons)

        # The actual cached files, not a substring of the markup: the tag is
        # `<IMG SCALE="TRUE" SRC=...>`, so looking for "IMG SRC" matched nothing
        # and would have passed for the wrong reason had the assertion been
        # inverted.
        drawn_paths = {str(a.path) for a in icons.values()}
        assert any(path in dot for path in drawn_paths), "builtin still renders bare shapes"
