"""Command line interface.

Two stages, deliberately separable:

  fetch   talk to the controller, cache raw JSON
  render  turn cached JSON into diagrams

Keeping them apart means you can re-render endlessly while iterating on style
without hammering the controller, and each cached snapshot is a record of what
the network looked like at that moment.

`fetch --support-file` fills the same cache from a support file archive rather
than a controller, so everything downstream behaves identically.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import logging
import sys
from pathlib import Path

from . import __version__
from .assets import AssetError, AssetStore, IconAsset, read_icon_font_dir
from .client import Snapshot, UniFiClient, UniFiError
from .config import ConfigError, load_config
from .fsio import atomic_write, mkdir_private
from .layout import GraphvizError, GraphvizMissing, compute_layout, run_dot, stagger
from .model import (
    UNKNOWN_UPLINK_ID,
    Kind,
    Topology,
    build_topology,
    client_networks,
    filter_by_network,
)
from .obfuscate import id_map, obfuscate
from .overrides import OverrideError
from .overrides import apply as apply_overrides
from .overrides import load as load_overrides
from .progress import SpinnerAwareHandler, spinner
from .render_dot import DEPRECATED_LAYOUTS, ICON_SETS, LAYOUTS, Style, render_dot
from .render_drawio import render_drawio
from .support import MAX_ARCHIVE_BYTES as SUPPORT_MAX_ARCHIVE
from .support import MAX_ARCHIVE_ENTRIES as SUPPORT_MAX_ENTRIES
from .support import MAX_MEMBER_BYTES as SUPPORT_MAX_MEMBER
from .support import MAX_TOTAL_BYTES as SUPPORT_MAX_TOTAL
from .support import SupportFileError, load_support_file
from .svg_post import inline_svg_images
from .theme import THEMES, get_theme

log = logging.getLogger("unifi_map")

DEFAULT_CACHE = Path("cache")
DEFAULT_OUT = Path("out")
# Artwork lives apart from snapshots so --cache-dir can point at a read-only
# dataset without downloads being written into it.
DEFAULT_ASSET_CACHE = Path("cache/assets")
# Picked up automatically when present, so the flag is only needed to point
# somewhere else.
DEFAULT_OVERRIDES = Path("overrides.toml")

# svg first: it is the format that actually solves the readability problem.
ALL_FORMATS = ("svg", "pdf", "png", "dot", "drawio")

# Below this many clients a view is not wide enough to need staggering, and
# unflatten instead chains sibling APs into a pointless diagonal cascade.
STAGGER_MIN_CLIENTS = 15


class _Parser(argparse.ArgumentParser):
    """An ArgumentParser that fills in the shared options' defaults last.

    They cannot be ordinary argparse defaults. The shared options are attached
    to both this parser and every subparser via `parents=`, which shares the
    same action objects rather than copying them, so whichever parser sees the
    option last would write its default over a value supplied to the other.
    `argparse.SUPPRESS` prevents that by leaving the attribute unset, and the
    real value is applied here once parsing is finished.

    `set_defaults()` is not the way to do it: it reassigns `action.default` for
    every matching dest, and since the action objects are shared that puts the
    defaults straight back onto the subparsers. That silently broke every
    invocation that passed an option before the subcommand.
    """

    def parse_args(self, args=None, namespace=None):  # type: ignore[override]
        parsed = super().parse_args(args, namespace)
        for key, value in GLOBAL_DEFAULTS.items():
            if not hasattr(parsed, key):
                setattr(parsed, key, value)
        return parsed


# Defaults for the options shared between the top-level parser and every
# subcommand. They live here rather than on the arguments because those must use
# `argparse.SUPPRESS`; see `_Parser` above.
GLOBAL_DEFAULTS = {
    "env_file": None,
    "cache_dir": DEFAULT_CACHE,
    "asset_cache": DEFAULT_ASSET_CACHE,
    "support_file": None,
    "site": None,
    "support_site": None,
    "support_max_member": SUPPORT_MAX_MEMBER,
    "support_max_total": SUPPORT_MAX_TOTAL,
    "support_max_entries": SUPPORT_MAX_ENTRIES,
    "support_max_archive": SUPPORT_MAX_ARCHIVE,
    "fetch_fingerprints": False,
    "fetch_icon_font": False,
    "icon_font": None,
    "out_dir": DEFAULT_OUT,
    "verbose": False,
    "progress": True,
}


def _bytes_arg(raw: str) -> int:
    """Parse a size like `64M`, `512K` or a plain byte count.

    Bytes are an awkward thing to type accurately, and a limit that is painful
    to raise is a limit people work around instead.
    """
    text = raw.strip().upper()
    units = {"K": 1024, "M": 1024**2, "G": 1024**3}
    multiplier = units.get(text[-1:], 1)
    if multiplier != 1:
        text = text[:-1]
    try:
        value = int(float(text) * multiplier)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"{raw!r} is not a size. Use a number, optionally with K, M or G."
        ) from None
    if value <= 0:
        raise argparse.ArgumentTypeError("Size must be positive.")
    return value


def _safe_name(text: str) -> str:
    keep = [c if (c.isalnum() or c in "-_") else "-" for c in text]
    return "".join(keep).strip("-").lower() or "network"


def _unique_names(names: list[str]) -> dict[str, str]:
    """Map each network name to a filename stem no other network shares.

    `_safe_name` is not injective: "IoT A", "IoT-A" and "IoT/A" all become
    "iot-a". Written straight out, the second network overwrote the first, and
    silently, because the file it replaced carried this tool's own provenance
    marker and so passed the overwrite guard.

    Collisions get a short digest of the original name rather than a counter, so
    a given network keeps its filename whatever order the networks arrive in.
    """
    slugs: dict[str, list[str]] = {}
    for name in names:
        slugs.setdefault(_safe_name(name), []).append(name)

    resolved: dict[str, str] = {}
    for slug, colliding in slugs.items():
        if len(colliding) == 1:
            resolved[colliding[0]] = slug
            continue
        for name in colliding:
            digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:6]
            resolved[name] = f"{slug}-{digest}"
    return resolved


def _hint_about_unplaced(topo: Topology, overrides_path: Path | None) -> None:
    """Say that the placeholder node is fixable, at the moment it appears.

    Somebody meeting "Uplink not reported by controller" on a map has no way to
    know the tool is refusing to guess rather than failing, or that they can
    place it themselves. Saying so in the README only helps whoever reads that
    section; this reaches the person looking at the diagram.

    The count is reported either way, because somebody who already wrote an
    overrides file and still has stranded clients is exactly who benefits from
    knowing how many are left. Only the pointer to the README is dropped once
    they have plainly found it.
    """
    if UNKNOWN_UPLINK_ID not in topo.nodes:
        return
    stranded = sum(1 for edge in topo.edges if edge.dst == UNKNOWN_UPLINK_ID)
    if overrides_path is not None:
        log.info("%d client(s) still have no uplink the controller reports.", stranded)
        return
    log.info(
        "%d client(s) have no uplink the controller reports, so they hang off a "
        "placeholder rather than a guessed parent. An overrides file can place "
        "them: see Manual overrides in the README.",
        stranded,
    )


def _stagger_for(topo: Topology, requested: int, style: Style) -> int:
    if requested <= 0 or not style.staggers:
        return 0
    clients = sum(
        1 for n in topo.nodes.values() if n.kind in (Kind.WIRED_CLIENT, Kind.WIRELESS_CLIENT)
    )
    return requested if clients >= STAGGER_MIN_CLIENTS else 0


def _requested_site(args: argparse.Namespace) -> str | None:
    """The site asked for, from either flag.

    `--support-site` predates `--site` and still works, because 0.3.0 shipped
    it. `--site` wins if somebody passes both.
    """
    if args.support_site and not args.site:
        log.warning("--support-site is deprecated; use --site, which works for both inputs.")
    return args.site or args.support_site


def cmd_fetch(args: argparse.Namespace) -> int:
    if args.support_file:
        return _fetch_from_support_file(args)

    config = load_config(args.env_file, site=_requested_site(args))
    client = UniFiClient(config)
    log.info("Reading %s (site %s)", config.host, config.site)
    with spinner(f"Querying {config.host}", args.progress):
        snapshot = client.snapshot()

    store = AssetStore(cache_dir=args.asset_cache)
    # Kept beside the artwork rather than in the snapshot: it describes
    # Ubiquiti's catalogue, not this network, and a support file has no copy of
    # it, so caching it here is what lets `--support-file` resolve client icons.
    store.save_fingerprint_db(snapshot.get("fingerprint"))

    try:
        font, codepoints = client.fetch_icon_font()
        store.save_icon_font(font, codepoints)
        log.info("Cached the controller's icon font (%d client glyphs).", len(codepoints))
    except UniFiError as exc:
        # Only needed for clients with no usable fingerprint; not fatal.
        log.warning("Could not cache the icon font (%s); generic client glyphs disabled.", exc)

    snapshot.write(args.cache_dir)
    log.info("Wrote snapshot to %s/", args.cache_dir)
    for name, payload in sorted(snapshot.payloads.items()):
        log.info("  %-14s %s", name, _describe(payload))
    return 0


def _fetch_from_support_file(args: argparse.Namespace) -> int:
    """Populate the snapshot cache from a support file instead of a controller.

    Deliberately writes the same cache `fetch` writes, so every render option,
    including per-network diagrams, overrides and obfuscation, works afterwards
    without knowing the difference. No credentials are read and no request is
    made, which is what makes reading one safe. Sending one is a different
    question entirely, and the answer is no; see the warning below.
    """
    # Said here rather than only in the docs, because this is the moment someone
    # has the archive in hand and is deciding what to do with it next. The
    # feature exists so a topology can be shared without an API key, which makes
    # it easy to conclude the file itself is safe to pass around. It is not.
    log.warning(
        "Note: a support file is highly sensitive. It holds every MAC, hostname, "
        "IP and lease on the network, the SSIDs and subnets, the WAN addresses, "
        "and logs of client activity. UniFi redacts some credentials by field "
        "name, but that pass is incomplete. Keep it protected and delete it when "
        "you are done; see SECURITY.md."
    )

    store = AssetStore(cache_dir=args.asset_cache, offline=getattr(args, "offline", False))
    # Not in the archive. Downloading it is opt-in, because someone reading a
    # support file has often chosen this path precisely to avoid outbound
    # traffic; an already-cached copy is used either way, being purely local.
    fingerprint_db = store.fingerprint_db(download=args.fetch_fingerprints)
    if fingerprint_db is None and not args.fetch_fingerprints:
        log.info(
            "Client product artwork is off: it needs Ubiquiti's fingerprint "
            "database, which a support file does not contain. Pass "
            "--fetch-fingerprints to download it (about 1 MB, cached "
            "afterwards). Nothing else here touches the network."
        )

    _obtain_icon_font(args, store)

    with spinner(f"Reading {args.support_file.name}", args.progress):
        snapshot = load_support_file(
            args.support_file,
            _requested_site(args),
            fingerprint_db,
            max_member=args.support_max_member,
            max_total=args.support_max_total,
            max_entries=args.support_max_entries,
            max_archive=args.support_max_archive,
        )
    snapshot.write(args.cache_dir)
    log.info("Wrote snapshot to %s/", args.cache_dir)
    for name, payload in sorted(snapshot.payloads.items()):
        log.info("  %-14s %s", name, _describe(payload))
    return 0


class OutputExistsError(RuntimeError):
    """Raised rather than overwrite a file this tool did not write."""


# Both editable formats carry this already: the DOT opens `digraph unifi` and
# the draw.io file opens `<mxfile host="unifi-map"`. Only the first few KiB are
# searched, which is where a header lives in either.
_PROVENANCE = ("unifi-map", "digraph unifi")


def _is_ours(path: Path) -> bool:
    try:
        # Read 4 KiB, rather than reading the file and slicing 4 KiB off it.
        with path.open("rb") as handle:
            head = handle.read(4096).decode("utf-8", errors="replace")
    except OSError:
        # Unreadable is not proof it is ours, so treat it as somebody else's.
        return False
    return any(marker in head for marker in _PROVENANCE)


def _write_output(path: Path, data: bytes | str, *, force: bool, guard: bool) -> None:
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


def _obtain_icon_font(args: argparse.Namespace, store: AssetStore) -> None:
    """Get the generic client glyph font, if the user asked for it and how.

    Three routes, deliberately distinct because their costs differ:

    * `--icon-font DIR` reads a copy from disk. No credentials, no network.
    * `--fetch-icon-font` asks a controller, which needs an API key. Ubiquiti
      publish no copy of this font, so there is no third option that avoids
      both.
    * Neither: unfingerprinted clients draw as shapes, and nothing is contacted.
    """
    if args.icon_font:
        font, codepoints = read_icon_font_dir(args.icon_font)
        store.save_icon_font(font, codepoints)
        log.info(
            "Loaded the client glyph font from %s (%d glyphs).", args.icon_font, len(codepoints)
        )
        return

    if not args.fetch_icon_font:
        if not store.glyph_codepoints():
            log.info(
                "Clients with no product artwork will draw as shapes. The "
                "generic glyph font exists only on a controller, so it needs "
                "either --fetch-icon-font (an API key) or --icon-font DIR (a "
                "copy you made yourself)."
            )
        return

    # Explicitly requested, so the credential requirement is not a surprise.
    config = load_config(args.env_file)
    log.info("Fetching the client glyph font from %s (this uses your API key).", config.host)
    font, codepoints = UniFiClient(config).fetch_icon_font()
    store.save_icon_font(font, codepoints)
    log.info("Cached the client glyph font (%d glyphs).", len(codepoints))


def _describe(payload: object) -> str:
    """Summarise a payload for the fetch log.

    v1 endpoints wrap records in `data`; the v2 topology endpoint returns a dict
    of `vertices`/`edges` instead, which would otherwise read as "0 records" and
    look like a failure.
    """
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return f"{len(data)} records"
        keys = [k for k in payload if k != "meta"]
        parts = [
            f"{k}={len(payload[k])}" if isinstance(payload[k], list | dict) else f"{k}={payload[k]}"
            for k in keys
        ]
        return ", ".join(parts) or "empty"
    if isinstance(payload, list):
        return f"{len(payload)} records"
    return "no data"


def _resolve_icons(topo: Topology, store: AssetStore, theme) -> dict[str, IconAsset]:
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


def _write_outputs(
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
) -> None:
    mkdir_private(out_dir)

    # Every icon this render used, and nothing else, may be embedded.
    icon_paths = {asset.path for asset in icons.values() if asset.path is not None}

    # Stagger once, up front, so the SVG/PDF and the draw.io coordinates are
    # computed from byte-identical DOT and therefore agree exactly.
    dot_source = stagger(dot_source, stagger_depth)

    if "dot" in formats:
        path = out_dir / f"{stem}.dot"
        _write_output(path, dot_source, force=force, guard=True)
        log.info("  %s", path)

    for fmt in ("svg", "pdf", "png"):
        if fmt not in formats:
            continue
        with spinner(f"Rendering {fmt}", progress):
            data = run_dot(dot_source, fmt)
        if fmt == "svg":
            # Graphviz references artwork by filesystem path; inline it so the
            # SVG is a single portable file.
            data = inline_svg_images(data, allowed=icon_paths)
        path = out_dir / f"{stem}.{fmt}"
        _write_output(path, data, force=force, guard=False)
        log.info("  %s (%.1f KiB)", path, len(data) / 1024)

    if "drawio" in formats:
        layout = compute_layout(dot_source)
        xml = render_drawio(topo, layout, stem, style.theme, icons)
        path = out_dir / f"{stem}.drawio"
        _write_output(path, xml, force=force, guard=True)
        log.info("  %s (%.1f KiB)", path, len(xml.encode()) / 1024)


def cmd_render(args: argparse.Namespace) -> int:
    snapshot = Snapshot.read(args.cache_dir)
    topo = build_topology(
        snapshot,
        include_clients=not args.no_clients,
        include_offline=args.show_offline == "yes",
    )

    if args.layout in DEPRECATED_LAYOUTS:
        log.warning(
            "--layout %s is deprecated and will be removed in 0.6.0; use --layout %s.",
            args.layout,
            DEPRECATED_LAYOUTS[args.layout],
        )

    try:
        style = Style(
            theme=get_theme(args.theme),
            icons=args.icons,
            layout=args.layout,
            legend=args.legend,
            title_block=args.title_block,
        )
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc

    tally = topo.counts()
    log.info(
        "Topology: %s",
        ", ".join(f"{count} {kind}" for kind, count in sorted(tally.items())) or "empty",
    )
    log.info("Style: icons=%s layout=%s theme=%s", style.icons, style.layout, args.theme)

    override_icons: dict[str, IconAsset] = {}
    path = args.overrides or (DEFAULT_OVERRIDES if DEFAULT_OVERRIDES.is_file() else None)
    if path is not None:
        overrides = load_overrides(path)
        result = apply_overrides(topo, overrides)
        topo = result.topology
        override_icons = result.icons
        # Names of hidden nodes are useful confirmation normally, and a leak
        # under --obfuscate: the diagram would be scrubbed while the terminal
        # or CI log it was produced in still carried real labels.
        hidden = f" ({', '.join(result.hidden)})" if result.hidden and not args.obfuscate else ""
        log.info(
            "Overrides from %s: %d device(s) added, %d link(s), %d nested, %d renamed, %d hidden%s",
            path,
            result.devices_added,
            result.links_added,
            result.hosted_applied,
            result.renamed,
            len(result.hidden),
            hidden,
        )

    # After overrides, not before: the whole point is to report what is *still*
    # unplaced, and running first counts the clients an override just placed.
    _hint_about_unplaced(topo, path)

    icons: dict[str, IconAsset] = {}
    store = AssetStore(cache_dir=args.asset_cache, offline=args.offline)
    if style.icons == "unifi":
        with spinner("Resolving artwork", args.progress):
            icons = _resolve_icons(topo, store, style.theme)

    # Artwork the user supplied wins over anything looked up for them.
    icons.update(override_icons)

    if args.obfuscate:
        # Artwork is resolved first and then carried across, because UniFi
        # hardware appearing as a client is matched on its hostname and
        # scrubbing that first would lose the picture.
        mapping = id_map(topo)
        icons = {mapping[k]: v for k, v in icons.items() if k in mapping}
        # The one piece of artwork that must not survive. Every other icon says
        # what a device is; the ISP brand mark says who the owner buys transit
        # from, and hiding the name while drawing the logo would be theatre.
        # `obfuscate()` clears the ASN, but this dict was built before that ran,
        # so swap the mark for the generic cloud rather than just dropping it.
        cloud = store.internet_icon(style.theme.text_muted)
        for node in topo.nodes.values():
            if node.kind is not Kind.INTERNET:
                continue
            key = mapping.get(node.id, node.id)
            if cloud is not None:
                icons[key] = cloud
            else:
                icons.pop(key, None)
        topo = obfuscate(topo)
        log.info("Obfuscated: names, addresses, MACs, network names and SSIDs replaced.")

    title = args.title or "Network map"
    subtitle = _subtitle(tally)
    formats = list(dict.fromkeys(args.formats))
    stem = _safe_name(args.name)

    log.info("Full map:")
    _write_outputs(
        render_dot(topo, title, style, icons, subtitle),
        topo,
        args.out_dir,
        stem,
        formats,
        style,
        icons,
        _stagger_for(topo, args.stagger, style),
        force=args.force,
        progress=args.progress,
    )

    if args.per_network:
        names = client_networks(topo)
        if not names:
            log.warning("No client networks found; skipping per-network views.")
        # Resolved across the whole set, since a collision is a property of the
        # set rather than of any one name.
        stems = _unique_names(names)
        for name in names:
            view = filter_by_network(topo, name)
            log.info("Network view %r:", name)
            _write_outputs(
                render_dot(view, f"{title}: {name}", style, icons, _subtitle(view.counts())),
                view,
                args.out_dir,
                f"{stem}-{stems[name]}",
                formats,
                style,
                icons,
                _stagger_for(view, args.stagger, style),
                force=args.force,
                progress=args.progress,
            )

    return 0


def _subtitle(tally: dict[str, int]) -> str:
    devices = sum(tally.get(k, 0) for k in ("gateway", "switch", "ap", "bridge"))
    clients = tally.get("wired_client", 0) + tally.get("wireless_client", 0)
    stamp = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    return f"{devices} UniFi devices · {clients} clients · generated {stamp}"


def cmd_all(args: argparse.Namespace) -> int:
    result = cmd_fetch(args)
    return result if result != 0 else cmd_render(args)


def build_parser() -> argparse.ArgumentParser:
    # Options accepted both before and after the subcommand.
    #
    # argparse attaches an option to exactly one parser, so with these on the
    # top level only, `unifi-map all --support-file X` is an error. Every
    # documented example reached for that form, because it is the convention
    # every comparable tool follows, so both are accepted rather than teaching
    # people the unusual one.
    #
    # `default=SUPPRESS` is what makes sharing them safe. A subparser defining
    # the same option would otherwise write its own default over a value given
    # before the subcommand, silently discarding it. With SUPPRESS the attribute
    # is absent unless actually supplied, so whichever position it was given in
    # wins and the real defaults come from `set_defaults()` below.
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument(
        "--env-file",
        type=Path,
        default=argparse.SUPPRESS,
        help="Credential file (default: $UNIFI_MAP_ENV, ./.env, ~/.config/unifi-map/env)",
    )
    shared.add_argument(
        "--cache-dir",
        type=Path,
        default=argparse.SUPPRESS,
        help=f"Where controller snapshots are read/written (default: {DEFAULT_CACHE})",
    )
    shared.add_argument(
        "--asset-cache",
        type=Path,
        default=argparse.SUPPRESS,
        help=f"Where downloaded artwork is cached (default: {DEFAULT_ASSET_CACHE}). "
        "Kept separate from --cache-dir so a read-only snapshot directory stays clean.",
    )
    shared.add_argument(
        "--support-file",
        type=Path,
        default=argparse.SUPPRESS,
        metavar="PATH",
        help="Read the topology from a UniFi support file (.tgz) instead of a "
        "controller. Needs no credentials and never contacts a controller. "
        "Rendering may still fetch artwork; add --offline to stop that too.",
    )
    shared.add_argument(
        "--site",
        default=argparse.SUPPRESS,
        metavar="NAME",
        help="Which site to read. Overrides UNIFI_SITE for a live fetch, and "
        "picks the site from a multi-site support file. Without it, a live "
        "fetch uses UNIFI_SITE or `default`; a support file holding more than "
        "one site is refused rather than chosen between.",
    )
    shared.add_argument(
        "--support-site",
        default=argparse.SUPPRESS,
        metavar="NAME",
        # Kept working because 0.3.0 shipped it. --site does both inputs, which
        # is what somebody scripting across sites actually wants.
        help=argparse.SUPPRESS,
    )
    shared.add_argument(
        "--support-max-member",
        type=_bytes_arg,
        default=argparse.SUPPRESS,
        metavar="SIZE",
        help=f"Largest single file to decode from a support archive (default "
        f"{SUPPORT_MAX_MEMBER // (1024 * 1024)}M). Accepts a plain number or a "
        "K/M/G suffix. Raise it if a large site is refused.",
    )
    shared.add_argument(
        "--support-max-total",
        type=_bytes_arg,
        default=argparse.SUPPRESS,
        metavar="SIZE",
        help=f"Total to decode from a support archive across all files (default "
        f"{SUPPORT_MAX_TOTAL // (1024 * 1024)}M).",
    )
    shared.add_argument(
        "--support-max-entries",
        type=int,
        default=argparse.SUPPRESS,
        metavar="N",
        help=f"How many archive entries to walk before giving up (default "
        f"{SUPPORT_MAX_ENTRIES}). Separate from the size caps because entry "
        "count does not follow the bytes decoded.",
    )
    shared.add_argument(
        "--fetch-fingerprints",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Allow downloading Ubiquiti's client fingerprint database, which is "
        "what gives clients real product artwork when reading a support file. "
        "Off by default: reading a support file otherwise contacts nothing.",
    )
    shared.add_argument(
        "--fetch-icon-font",
        action="store_true",
        default=argparse.SUPPRESS,
        help="With --support-file, also fetch the generic client glyph font from "
        "a controller. This one DOES need UNIFI_HOST and UNIFI_API_KEY, because "
        "Ubiquiti publish no copy of that font. Off by default.",
    )
    shared.add_argument(
        "--icon-font",
        type=Path,
        default=argparse.SUPPRESS,
        metavar="DIR",
        help="Load the client glyph font from a directory you copied off a "
        "controller yourself (needs its style.css and .ttf). Needs no "
        "credentials and no network. See the README.",
    )
    shared.add_argument(
        "--support-max-archive",
        type=_bytes_arg,
        default=argparse.SUPPRESS,
        metavar="SIZE",
        help=f"Total uncompressed bytes to walk in a support archive, counting "
        f"files that are skipped (default {SUPPORT_MAX_ARCHIVE // 1024**3}G). This "
        "is what stops a small archive that expands enormously; the other caps "
        "only measure what is decoded.",
    )
    shared.add_argument(
        "--no-progress",
        dest="progress",
        action="store_false",
        default=argparse.SUPPRESS,
        help="Never show the progress spinner. It already turns itself off when "
        "output is not a terminal, so this is only needed for an interactive "
        "run whose output something else is reading.",
    )
    shared.add_argument(
        "--out-dir",
        type=Path,
        default=argparse.SUPPRESS,
        help=f"Where diagrams are written (default: {DEFAULT_OUT})",
    )
    shared.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Log every artwork lookup, including the ones that found nothing, "
        "and name nodes that --obfuscate would otherwise hide.",
    )

    parser = _Parser(
        prog="unifi-map",
        description="Export a UniFi network topology as zoomable vector diagrams "
        "and editable draw.io files.",
        parents=[shared],
    )
    parser.add_argument("--version", action="version", version=f"unifi-map {__version__}")

    sub = parser.add_subparsers(dest="command", required=True)

    render_flags = argparse.ArgumentParser(add_help=False)
    render_flags.add_argument(
        "-f",
        "--formats",
        nargs="+",
        choices=ALL_FORMATS,
        default=["svg", "drawio"],
        help="Output formats (default: svg drawio)",
    )
    render_flags.add_argument(
        "--icons",
        choices=ICON_SETS,
        default="unifi",
        help="unifi: real Ubiquiti product artwork, fetched and cached at runtime. "
        "builtin: geometric shapes only, no network access (default: unifi)",
    )
    render_flags.add_argument(
        "--layout",
        # `sane` is accepted but not advertised: metavar controls what usage
        # prints, while choices still lets the old value through until 0.6.0.
        choices=(*LAYOUTS, *DEPRECATED_LAYOUTS),
        metavar="{" + ",".join(LAYOUTS) + "}",
        default="unifi",
        help="unifi: left-to-right like the UniFi UI, no port labels. "
        "tree: top-down and leaf-staggered, with port labels, built to be "
        "readable on a busy network (default: unifi)",
    )
    render_flags.add_argument(
        "--theme", choices=sorted(THEMES), default="light", help="Colour theme (default: light)"
    )
    render_flags.add_argument(
        "--offline",
        action="store_true",
        help="Never reach the network for artwork; use only what is already cached",
    )
    render_flags.add_argument("--name", default="network-map", help="Output filename stem")
    render_flags.add_argument(
        "--force",
        action="store_true",
        help="Overwrite output files that unifi-map did not write. Without this, "
        "an existing .dot or .drawio it does not recognise is left alone, so a "
        "diagram you have edited by hand is not silently replaced.",
    )
    render_flags.add_argument(
        "--overrides",
        type=Path,
        default=None,
        help=f"Manual corrections: links the controller cannot see, nesting, "
        f"renames, your own artwork, and hiding. Defaults to {DEFAULT_OVERRIDES} "
        "when that file exists",
    )
    render_flags.add_argument(
        "--obfuscate",
        action="store_true",
        help="Replace hostnames, addresses, MACs, network names and SSIDs with "
        "stable placeholders, keeping topology, roles and artwork intact, so the "
        "diagram can be shared",
    )
    render_flags.add_argument(
        "--title",
        default=None,
        help="Diagram title (default: Network map). Note that --obfuscate cannot "
        "clean a title you supply yourself",
    )
    render_flags.add_argument(
        "--no-clients", action="store_true", help="Infrastructure only, no clients"
    )
    render_flags.add_argument(
        "--show-offline",
        choices=("yes", "no"),
        default="no",
        help="Include devices the controller lists but that are not currently "
        "connected. Defaults to no, because a controller keeps remembering "
        "hardware long after it has been pulled from the rack; use yes when you "
        "want to see what it still thinks exists (default: no)",
    )
    render_flags.add_argument(
        "--per-network",
        action="store_true",
        help="Also emit one diagram per client network, which keeps a busy map readable",
    )
    render_flags.add_argument(
        "--legend",
        dest="legend",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Show the legend (default: on for --layout tree, off for --layout unifi)",
    )
    render_flags.add_argument(
        "--title-block",
        dest="title_block",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Show the title and subtitle above the map. A title sets a minimum "
        "canvas width, so turning it off crops dead space on a narrow map "
        "(default: on for --layout tree, off for --layout unifi)",
    )
    render_flags.add_argument(
        "--stagger",
        type=int,
        default=12,
        metavar="N",
        help="With --layout tree, stagger leaf nodes into rows of ~N to control "
        "aspect ratio (0 disables; higher is taller and narrower; default 12)",
    )

    sub.add_parser(
        "fetch", parents=[shared], help="Cache controller data (or read --support-file instead)"
    ).set_defaults(func=cmd_fetch)
    sub.add_parser(
        "render", parents=[shared, render_flags], help="Render diagrams from cache"
    ).set_defaults(func=cmd_render)
    sub.add_parser("all", parents=[shared, render_flags], help="Fetch then render").set_defaults(
        func=cmd_all
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
        # Erases the spinner before each record, so the two never share a line.
        handlers=[SpinnerAwareHandler(sys.stderr)],
    )
    try:
        return int(args.func(args))
    except ConfigError as exc:
        log.error("Configuration error: %s", exc)
        return 2
    except OverrideError as exc:
        log.error("Overrides: %s", exc)
        return 2
    except GraphvizMissing as exc:
        log.error("%s", exc)
        return 3
    except (UniFiError, GraphvizError, SupportFileError, AssetError, OutputExistsError) as exc:
        log.error("%s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
