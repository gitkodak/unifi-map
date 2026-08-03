"""Resolving nodes to artwork.

Given a `Topology` and an `AssetStore`, decide which image each node draws with.
This is a pipeline stage rather than a command-line concern, and lived in
`cli.py` only because that is where it was first written. The tell was a
rendering test having to import `_apply_drawn_icons` from `unifi_map.cli`, which
is a test reaching through the command line to get at the renderer.

The order the three sources are tried in is deliberate and is the whole design:

1. **Ubiquiti's product artwork**, matched on `sysid` for UniFi hardware and on
   the fingerprint `dev_id` for clients. A real picture of the real hardware.
2. **The console's own icon font**, the generic user/guest by wired/wireless
   glyph the UI itself falls back to. Only a controller serves it.
3. **Icons we drew** (`drawn.py`), which need no network and no console.

Better answers come first. Nothing here is vendored into this repository: it is
Ubiquiti's, fetched on first use and cached.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .assets import AssetStore, IconAsset, read_icon_font_dir
from .client import UniFiClient
from .config import load_config
from .model import Kind, Topology

log = logging.getLogger("unifi_map")


def obtain_icon_font(
    store: AssetStore,
    *,
    icon_font_dir: Path | None = None,
    fetch: bool = False,
    env_file: Path | None = None,
) -> None:
    """Get the generic client glyph font, if the user asked for it and how.

    Three routes, deliberately distinct because their costs differ:

    * *icon_font_dir* reads a copy from disk. No credentials, no network.
    * *fetch* asks a controller, which needs an API key. Ubiquiti publish no
      copy of this font, so there is no third option that avoids both.
    * Neither: unfingerprinted clients fall through to the drawn icons, and
      nothing is contacted.

    Takes the three settings rather than an `argparse.Namespace`, so this is
    callable without constructing one.
    """
    if icon_font_dir:
        font, codepoints = read_icon_font_dir(icon_font_dir)
        store.save_icon_font(font, codepoints)
        log.info(
            "Loaded the client glyph font from %s (%d glyphs).", icon_font_dir, len(codepoints)
        )
        return

    if not fetch:
        if not store.glyph_codepoints():
            log.info(
                "Clients with no product artwork will draw with our own icons. "
                "The console's generic glyph font exists only on a controller, "
                "so matching the UI exactly needs either --fetch-icon-font (an "
                "API key) or --icon-font DIR (a copy you made yourself)."
            )
        return

    # Explicitly requested, so the credential requirement is not a surprise.
    config = load_config(env_file)
    log.info("Fetching the client glyph font from %s (this uses your API key).", config.host)
    font, codepoints = UniFiClient(config).fetch_icon_font()
    store.save_icon_font(font, codepoints)
    log.info("Cached the client glyph font (%d glyphs).", len(codepoints))


def _hardware_asset(node, store: AssetStore) -> IconAsset | None:
    """Artwork for UniFi hardware that shows up as a client.

    A Protect camera on a switch port is a client with no fingerprint, so the
    Network app offers nothing to look up. Its hostname can be matched against
    the hardware catalog instead, narrowed by what another app says it is.
    """
    if not node.hardware_type and not (node.oui and "ubiquiti" in node.oui.lower()):
        return None

    sysid = store.sysid_for_name(node.label, device_type=node.hardware_type)
    if sysid is None:
        return None

    asset = store.icon(sysid)
    if asset is not None:
        product = store.product_name(sysid)
        if product:
            node.detail = product
    return asset


def resolve_icons(
    topo: Topology, store: AssetStore, theme, counts: dict[str, int] | None = None
) -> dict[str, IconAsset]:
    """Map node id to cached artwork, fetching as needed.

    UniFi devices are matched on sysid against Ubiquiti's hardware catalog.
    Clients are matched on their fingerprint dev_id against Ubiquiti's client
    artwork, which is what the topology view itself renders; clients with no
    usable fingerprint fall back to the controller's own icon-font glyph, the
    same way the UI does.

    All of it is Ubiquiti's and none of it is vendored into this repository: it
    is downloaded on first use and cached.
    """
    icons: dict[str, IconAsset] = {}

    # --- UniFi hardware ---
    devices = {n.sysid for n in topo.nodes.values() if n.sysid is not None}
    by_sysid: dict[int, IconAsset | None] = {s: store.icon(s) for s in sorted(devices)}
    for node in topo.nodes.values():
        if node.sysid is None:
            continue
        asset = by_sysid.get(node.sysid)
        if asset is not None:
            icons[node.id] = asset
        # Prefer the catalog's product name over the terse model code.
        product = store.product_name(node.sysid)
        if product:
            node.detail = product

    device_total = len(devices)
    device_found = sum(1 for a in by_sysid.values() if a is not None)
    log.info("Artwork: %d/%d UniFi devices", device_found, device_total)
    if counts is not None:
        counts.update(device_found=device_found, device_total=device_total)

    # --- the upstream provider ---
    for node in topo.nodes.values():
        if node.kind is not Kind.INTERNET:
            continue
        logo = store.isp_logo(node.asn) if node.asn is not None else None
        if logo is not None:
            icons[node.id] = logo
            log.info("Artwork: ISP brand mark for AS%d", node.asn)
        elif (cloud := store.internet_icon(theme.text_muted)) is not None:
            # Plenty of providers have no brand mark, so a cloud reads better
            # than the bare polygon the shape renderer would leave behind.
            icons[node.id] = cloud

    # --- clients ---
    client_nodes = [n for n in topo.nodes.values() if n.glyph_name is not None]
    if not client_nodes:
        return icons

    dev_ids = {n.dev_id for n in client_nodes if n.dev_id is not None}
    by_dev_id: dict[int, IconAsset | None] = {d: store.client_icon(d) for d in sorted(dev_ids)}

    glyph_cache: dict[str, IconAsset | None] = {}
    from_glyph = 0
    from_fingerprint = 0
    from_hardware = 0
    for node in client_nodes:
        asset = by_dev_id.get(node.dev_id) if node.dev_id is not None else None
        if asset is not None:
            from_fingerprint += 1
        elif (hardware := _hardware_asset(node, store)) is not None:
            asset = hardware
            from_hardware += 1
        else:
            # Same fallback the UI uses: a generic user/guest x wired/wireless
            # glyph from the controller's icon font.
            name = node.glyph_name
            if name not in glyph_cache:
                glyph_cache[name] = store.client_glyph(name, theme.text_muted)
            asset = glyph_cache[name]
            if asset is not None:
                from_glyph += 1
        if asset is not None:
            icons[node.id] = asset

    # Counted per node, not per dev_id: several clients can share a fingerprint.
    plain = len(client_nodes) - from_fingerprint - from_hardware - from_glyph
    if counts is not None:
        counts.update(
            client_total=len(client_nodes),
            client_found=from_fingerprint + from_hardware + from_glyph,
            from_fingerprint=from_fingerprint,
            from_hardware=from_hardware,
            from_glyph=from_glyph,
        )
    log.info(
        "Artwork: %d/%d clients (%d product, %d UniFi hardware, %d generic glyph, %d none)",
        from_fingerprint + from_hardware + from_glyph,
        len(client_nodes),
        from_fingerprint,
        from_hardware,
        from_glyph,
        plain,
    )
    return icons


def apply_drawn_icons(
    topo: Topology,
    store: AssetStore,
    theme,
    icons: dict[str, IconAsset],
    counts: dict | None = None,
) -> int:
    """Fill remaining nodes with icons we drew ourselves. Returns how many.

    Last, deliberately. Ubiquiti's product artwork is the real picture of the
    real hardware and the console's icon font is what the UI itself falls back
    to; both are better answers than a generic drawing. This only covers what
    neither could name, which previously left a bare Graphviz primitive.

    The Internet node is skipped: `resolve_icons` already gives it a brand mark
    or our cloud, and the cloud is the drawn icon for that kind.
    """
    drawn_count = 0
    for node in topo.nodes.values():
        if node.id in icons or node.kind is Kind.INTERNET:
            continue
        # Clients split four ways on guest/wireless, the same split the
        # console's icon font encodes; everything else is drawn by kind.
        name = node.glyph_name or node.kind.value
        asset = store.drawn_icon(name, theme.text_muted)
        if asset is not None:
            icons[node.id] = asset
            drawn_count += 1
    if counts is not None:
        counts.update(from_drawn=drawn_count)
    return drawn_count
