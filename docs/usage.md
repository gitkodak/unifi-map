# Usage

Every command and flag, and how to read what comes out of them. The reference
at the end is generated from the argument parser, so it cannot drift from
`--help`.

```bash
unifi-map all                              # fetch + render
unifi-map fetch                            # snapshot the controller into cache/
unifi-map fetch --support-file FILE.tgz     # or read a support file instead
unifi-map render                           # render from the cached snapshot
unifi-map render --per-network              # one diagram per client network
unifi-map overrides check                   # validate overrides without rendering
unifi-map shape                             # describe the network, for sharing
unifi-map render --no-clients               # infrastructure only
unifi-map render -f svg pdf drawio dot      # pick formats
```

`fetch` and `render` are separate on purpose: you can re-render endlessly while
adjusting style without hammering the controller, and each cached snapshot is a
record of what the network looked like at that moment.

### What actually touches the network

Worth being precise about, because there are two caches and they behave
differently:

| Command | Controller | Artwork |
| --- | --- | --- |
| `fetch` | Unless `--support-file` is given. Never checks the cache first, so it always overwrites the snapshot with current state. | Fetches the icon font if it is missing |
| `render` | Never. Reads whatever snapshot is in `--cache-dir`, however old. | Downloads any artwork not already cached, unless `--offline` |
| `all` | Same as `fetch`, because it is `fetch` then `render` | Same as `render` |

Reading a support file therefore contacts no controller, but `all` goes on to
render, and rendering fetches artwork. For a genuinely network-free run add
`--offline` or `--icons builtin`.

So `unifi-map all` does not skip the fetch when a cache already exists; it
refreshes unconditionally. If you want to re-render without going near the
controller, use `render`.

And `render` is not automatically offline. On a cold artwork cache it reaches
Ubiquiti's CDN for product images. Pass `--offline` to forbid that, or
`--icons builtin` to avoid needing artwork at all. Once the artwork cache is
warm, `render` makes no network calls in practice, but that is a consequence of
the cache being populated rather than a guarantee of the command.

### When something looks wrong: `-v`

```bash
unifi-map -v render
```

Verbose mode logs every artwork lookup, including the ones that came back
empty. That is usually enough to tell the two common cases apart:

- **Ubiquiti has no artwork for that device.** The lookup ran and the asset
  genuinely is not published. Nothing to fix here; the shape or glyph fallback
  is correct.
- **The match went wrong.** The device resolved to the wrong product, or to
  nothing when it should have resolved. [Overrides](overrides.md) can
  correct it, and it is worth reporting.

Missing artwork is deliberately quiet at the normal log level, because a
handful of unrecognised devices is ordinary on any network and a warning per
device would drown the output. `-v` is where the detail lives.

It also raises the detail on everything else, so it is the first thing to
attach to a bug report. Redact addresses and hostnames before pasting.

### Overwriting: `--force`

Rendering refuses to replace a `.dot` or `.drawio` it did not write, so a
diagram you have opened and rearranged is left alone rather than silently
replaced. Re-rendering output it recognises as its own needs no flag.

```bash
unifi-map render --force        # replace it anyway
```

PNG, PDF and SVG are not guarded. Nothing hand-authors one at exactly that path,
and there is nowhere convenient in them to record that this tool produced it.

### Style options

```bash
--icons unifi|builtin      # default: unifi
--layout unifi|tree        # default: unifi
--theme light|dark         # default: light
```

**Defaults reproduce the UniFi web view.** Out of the box you get what the
console shows you, just exportable and zoomable. The one deliberate exception is
`--show-offline`, below.

**`--icons unifi`** uses real Ubiquiti product artwork for both UniFi hardware
*and* clients (the same images the topology view shows). Fetched on first run and
cached. **`--icons builtin`** uses geometric shapes only: no network access, no
external assets.

**`--layout unifi`** approximates the UniFi UI: left-to-right tree, orthogonal
links, no port labels, no title or legend chrome, canvas trimmed to the drawing.
See below for how close that actually gets.
**`--layout tree`** is top-down with leaf staggering, port numbers on links, a
title block and a legend, built to actually be readable on a busy network. Try
both; on a network with many clients `tree` is usually the one you want to hand
to someone else.

### How close is `--layout unifi`?

Close, not exact. It won't look *exactly* like the controller UI, and it can't:
the tooling necessarily leaves its mark on the output. I've made my best attempt
to get as close as possible.

Concretely, what differs:

- **Graphviz does the layout, not UniFi.** The tree is connected the same way, but
  the order siblings appear in and the precise spacing are Graphviz's decisions.
- **Link routing is orthogonal but not identical.** Corners, channel spacing and
  where a line breaks are up to the renderer.
- **Fingerprints are sometimes wrong.** Client artwork comes from Ubiquiti's
  fingerprint database, and it misidentifies things (a phone shown as an
  appliance, that sort of thing). That is upstream data, not a rendering bug;
  correcting it is what [overrides](overrides.md) are for.
- **Typography and label content differ.** This uses Helvetica/Arial and shows
  name, address and product name; the UI has its own font and its own idea of
  what belongs on a node.
- **It's a static picture.** No hover, no expanding and collapsing, no live state.

If you need the real thing, the real thing is in your browser. This is for when
you need it in a file.

**`--show-offline yes|no`** (default `no`) controls whether devices the
controller still lists but that aren't connected appear. This is the one place
the defaults deviate from the web view, on purpose: a controller keeps
remembering hardware long after it's been pulled from the rack, and the UI gives
you no way to hide it. Use `yes` to see everything yours still thinks exists.

Further knobs: `--legend` / `--no-legend`, `--title-block` / `--no-title-block`,
`--stagger N` (aspect-ratio control for `tree`), `--offline` (never touch the
network for artwork), `--title`, `--name`, `--out-dir`, `--cache-dir`,
`--asset-cache` (artwork cache, kept separate from snapshots).

## Reading the diagram

Colour is never the only signal. The accent palette is
[Okabe-Ito](https://jfly.uni-koeln.de/color/), chosen to stay separable under
red-green colour blindness, and every distinction is *also* carried by artwork,
shape, or line style, so the diagram survives greyscale printing.

| Element | Encoding |
| --- | --- |
| UniFi device | Real product artwork, matched on hardware `sysid` |
| Client | Real product artwork, matched on fingerprint `dev_id` |
| UniFi hardware appearing as a client | Its catalogue artwork, matched by hostname (see below) |
| Unrecognised client | A generic user/guest x wired/wireless glyph, the same fallback the UI uses |
| Client network | Border colour, plus the VLAN in the label |
| Wired link | Solid line |
| Wireless link | Dashed line |
| Offline device | Dashed border, `OFFLINE` in the label |

With `--layout tree`, edge labels are switch port numbers (`port 12`) or the
radio for wireless clients.

The legend only lists what a given render actually encodes. A node drawn as
artwork has no border and no fill, so it carries no accent colour and gets no
role swatch; its role is the artwork. Swatches appear only for roles that fell
back to shapes in that render, under "Without artwork". `--layout unifi` omits
the legend entirely, matching the UniFi UI.

### "Uplink not reported by controller"

You will probably never see this node, but it exists for the case where the
controller genuinely does not know where something is attached.

`stat/sta` only reports a client's uplink when that uplink is a UniFi device, so
anything behind a non-UniFi box (VMs and containers behind a NAS, or a client on
a switch the controller does not manage) comes back with no `sw_mac` at all. Those are resolved
against the controller's own topology graph, where a client can be another
client's uplink, which is how the console draws them correctly.

Anything still unresolved after that is anchored to an explicit placeholder,
rather than left floating (which looks like a bug) or attached to a guessed
parent (which would invent a connection that does not exist).

**You can place them yourself.** The tool refuses to guess, but you know where
the cable goes, and [manual overrides](overrides.md) are how you say so. A
`[[link]]` attaches the client to its real parent, and if that parent is an
switch the controller cannot see either, `[[device]]` declares the switch first
and the link hangs off it. Both are drawn dotted, so the map still distinguishes
what you asserted from what the controller reported. The placeholder disappears
once nothing is left under it.

<!-- BEGIN GENERATED FLAGS -->

## Flag reference

Generated from the argument parser by `scripts/generate_cli_docs.py`, so it
cannot drift from `--help`. Each flag is explained in context further up;
this is for looking one up. Run `unifi-map --help` for the same thing in a
terminal.

```
unifi-map [global options] {fetch,render,all} [command options]
```

Global options are accepted on either side of the subcommand, so
`unifi-map all --support-file X` and `unifi-map --support-file X all` are
equivalent. Command options must follow the subcommand.

### Global options

| Flag | What it does | Default |
| --- | --- | --- |
| `--env-file` | Credential file (default: $UNIFI_MAP_ENV, ./.env, ~/.config/unifi-map/env) |  |
| `--cache-dir` | Where controller snapshots are read/written (default: cache) | `cache` |
| `--asset-cache` | Where downloaded artwork is cached (default: cache/assets). Kept separate from --cache-dir so a read-only snapshot directory stays clean. | `cache/assets` |
| `--support-file` `PATH` | Read the topology from a UniFi support file (.tgz) instead of a controller. Needs no credentials and never contacts a controller. Rendering may still fetch artwork; add --offline to stop that too. |  |
| `--site` `NAME` | Which site to read. For a live fetch this overrides UNIFI_SITE, which otherwise falls back to `default`. For a support file it picks one of the sites inside, and is required when the file holds more than one: the run stops and lists them rather than choosing for you. |  |
| `--support-max-member` `SIZE` | Largest single file to decode from a support archive (default 64M). Accepts a plain number or a K/M/G suffix. Raise it if a large site is refused. | `64M` |
| `--support-max-total` `SIZE` | Total to decode from a support archive across all files (default 128M). | `128M` |
| `--support-max-entries` `N` | How many archive entries to walk before giving up (default 100000). Separate from the size caps because entry count does not follow the bytes decoded. | `100000` |
| `--fetch-fingerprints` | Allow downloading Ubiquiti's client fingerprint database, which is what gives clients real product artwork when reading a support file. Off by default: reading a support file otherwise contacts nothing. |  |
| `--fetch-icon-font` | With --support-file, also fetch the generic client glyph font from a controller. This one DOES need UNIFI_HOST and UNIFI_API_KEY, because Ubiquiti publish no copy of that font. Off by default. |  |
| `--icon-font` `DIR` | Load the client glyph font from a directory you copied off a controller yourself (needs its style.css and .ttf). Needs no credentials and no network. See the README. |  |
| `--support-max-archive` `SIZE` | Total uncompressed bytes to walk in a support archive, counting files that are skipped (default 4G). This is what stops a small archive that expands enormously; the other caps only measure what is decoded. | `4G` |
| `--no-progress` | Never show the progress spinner. It already turns itself off when output is not a terminal, so this is only needed for an interactive run whose output something else is reading. |  |
| `--out-dir` | Where diagrams are written (default: out) | `out` |
| `-v`, `--verbose` | Log every artwork lookup, including the ones that found nothing, and name nodes that --obfuscate would otherwise hide. |  |
| `--version` | show program's version number and exit |  |

`fetch` takes only the global options above.


### `render` and `all` options

| Flag | What it does | Default |
| --- | --- | --- |
| `-f`, `--formats` `{svg,pdf,png,dot,drawio,mermaid,json}` | Output formats (default: svg drawio) | `svg drawio` |
| `--icons` `{unifi,builtin}` | unifi: real Ubiquiti product artwork, fetched and cached at runtime. builtin: geometric shapes only, no network access (default: unifi) | `unifi` |
| `--layout` `{tree,unifi}` | unifi: left-to-right like the UniFi UI, no port labels. tree: top-down and leaf-staggered, with port labels, built to be readable on a busy network (default: unifi) | `unifi` |
| `--theme` `{dark,light}` | Colour theme (default: light) | `light` |
| `--transparent` | Draw no background, so the map sits on whatever page it is placed on. Applies to svg, pdf, png and drawio. Pick the theme to match the destination: labels are drawn straight onto the canvas with nothing behind them, so light text vanishes on a light page. |  |
| `--offline` | Never reach the network for artwork; use only what is already cached |  |
| `--name` | Output filename stem | `network-map` |
| `--force` | Overwrite output files that unifi-map did not write. Without this, an existing .dot or .drawio it does not recognise is left alone, so a diagram you have edited by hand is not silently replaced. |  |
| `--overrides` | Manual corrections: links the controller cannot see, nesting, renames, your own artwork, and hiding. Defaults to overrides.toml when that file exists |  |
| `--obfuscate` | Replace hostnames, addresses, MACs, network names and SSIDs with stable placeholders, keeping topology, roles and artwork intact, so the diagram can be shared |  |
| `--title` | Diagram title (default: Network map). Note that --obfuscate cannot clean a title you supply yourself |  |
| `--no-clients` | Infrastructure only, no clients |  |
| `--show-offline` `{yes,no}` | Include devices the controller lists but that are not currently connected. Defaults to no, because a controller keeps remembering hardware long after it has been pulled from the rack; use yes when you want to see what it still thinks exists (default: no) | `no` |
| `--per-network` | Also emit one diagram per client network, which keeps a busy map readable |  |
| `--legend`, `--no-legend` | Show the legend (default: on for --layout tree, off for --layout unifi) |  |
| `--title-block`, `--no-title-block` | Show the title and subtitle above the map. A title sets a minimum canvas width, so turning it off crops dead space on a narrow map (default: on for --layout tree, off for --layout unifi) |  |
| `--stagger` `N` | With --layout tree, stagger leaf nodes into rows of ~N to control aspect ratio (0 disables; higher is taller and narrower; default 12) | `12` |

### `shape` options

| Flag | What it does | Default |
| --- | --- | --- |
| `--yes` | Skip the consent prompt. Read what the report contains first; `unifi-map shape` on its own prints that and asks. |  |

### `overrides` options

| Flag | What it does | Default |
| --- | --- | --- |
| `--overrides` | Which file to check. Defaults to overrides.toml when it exists. |  |

<!-- END GENERATED FLAGS -->
