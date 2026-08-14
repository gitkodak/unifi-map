# Usage

[← Documentation index](../README.md#documentation)

Every command and flag, and how to read what comes out of them. The reference
at the end is generated from the argument parser, so it cannot drift from
`--help`.

Every example below assumes `unifi-map` is on your `PATH`. If you installed into
a virtual environment, that means activating it (`source .venv/bin/activate`) or
writing `.venv/bin/unifi-map` in full. See
[Install](../README.md#install).

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

**`all` means both stages, not all output formats.** It is `fetch` then
`render`, and it writes the same default two files any `render` would: an SVG
and a draw.io file. If you want the others, ask for them:

```bash
unifi-map all -f svg pdf png dot drawio mermaid json
```

The default is two rather than seven because those two answer the common cases,
one to look at and one to edit, and the rest cost time and disk on every run.
[Every format and what it is for](output.md).

### What actually touches the network

Worth being precise about, because there are two caches and they behave
differently:

| Command | Controller | Artwork |
| --- | --- | --- |
| `fetch` | Unless `--support-file` is given. Never checks the cache first, so it always overwrites the snapshot with current state. | Fetches the icon font, replacing any cached copy |
| `render` | Never. Reads whatever snapshot is in `--cache-dir`, however old. | Downloads any artwork not already cached, unless `--offline` |
| `all` | Same as `fetch`, because it is `fetch` then `render` | Same as `render` |

Reading a support file therefore contacts no controller, but `all` goes on to
render, and rendering fetches artwork. For a genuinely network-free run add
`--offline` or `--icons builtin`.

So `unifi-map all` does not skip the fetch when a cache already exists; it
refreshes unconditionally. If you want to re-render without going near the
controller, use `render`.

Each `fetch` writes one complete generation of the snapshot and switches a
pointer to it as its last step. A fetch cut off mid-way therefore never leaves a
mixture of old and new payloads: `render` reads the previous complete
generation until the next one is fully in place, and older generations are
removed. A cache written before this layout still reads, and is migrated by the
next fetch.

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

### How much to trust the map: `--report`

```bash
unifi-map render --report
```

A map drawn from a complete fetch and one drawn from a thin one look equally
authoritative. `--report` is how you tell them apart: after rendering, it prints
where every part of the map came from.

```
WHERE THE MAP CAME FROM
  nodes               29
          8  stat/device (the device inventory)
         19  stat/sta (the client list; 'sta' is UniFi's term for a connected client)
          2  ours (Internet, placeholder)

  links               27
          7  stat/device uplink (a device reporting its own connection)
          1  gateway to the Internet
         16  stat/sta sw_mac or ap_mac (a client reporting which switch or AP it's on)
          1  the controller's topology graph
          2  nothing reported one
```

**What these labels mean.** The controller's own web UI draws itself from
several JSON endpoints, and this tool calls the same ones — the names above are
theirs, not invented for this report:

- **`stat/device`** is the device inventory: every switch, access point, gateway
  and other piece of infrastructure the controller manages directly.
- **`stat/sta`** is the client list: phones, laptops, IoT gear, anything that
  isn't itself managed UniFi hardware. `sta` is short for "station", a term
  UniFi borrowed from wireless networking, where every connected device — wired
  or not — is called a station. It has nothing to do with "static."
- **The controller's topology graph** is a separate endpoint that tracks link
  relationships directly, used as a fallback when a client's own record doesn't
  say what it's plugged into. This happens for anything sitting behind
  non-UniFi gear — a VM behind a NAS, say — since `stat/sta` only reports an
  uplink when that uplink is itself a UniFi device.
- **An overrides file** means a human typed it in; nothing here observed it.
  See [Overrides](overrides.md).

It also lists what the snapshot actually carried, and what each missing piece
costs. An optional endpoint that failed is logged once when it is fetched and
never mentioned again, so a snapshot cached before an app was installed renders
thinner every time with nothing saying why:

```
  MISSING OR UNUSABLE
  topology          clients behind non-UniFi gear cannot be placed without it
  protect_cameras   tells a camera from an Access reader of the same name
```

Then, where anything needs attention, it names the devices involved rather than
only counting them: clients that could not be placed, clients with no address
from any source, networks a client claims to be on that the controller does not
list, and artwork matches [refused as ambiguous](artwork.md). A map with nothing
wrong prints no device names at all, so a short report is a good sign.

The counts are the point of the first section: how much of the map the
controller reported directly versus filled in from a second endpoint versus
you asserted yourself. A link from the topology graph also gets a small
hollow-circle marker on the diagram itself — see [Reading the
diagram](#reading-the-diagram) — and an asserted one is drawn dotted, so this
report and the picture agree rather than the report being the only place the
distinction shows.

**Every join here is on MAC address**, and most phones and laptops rotate
theirs periodically. When that happens the same physical device reappears as
an unrelated new client rather than as an update to the one already on the
map — nothing is wrong, and there is no overrides entry that fixes it. A
rotated MAC is detectable without any cooperation from the controller (it sets
IEEE 802's locally-administered bit), so `--report` counts how many clients
currently show one:

```
RANDOMISED MAC ADDRESSES
  3 of 19 client(s) advertise a locally-administered
  MAC, which most phones and laptops rotate periodically. The same physical
  device can reappear here as a new client rather than as the one already on
  the map; this is expected, and not something an overrides file can fix.
```

Counted rather than named, unlike the sections above: there is nothing wrong
with any specific device here.

**This report is not safe to share.** It names your devices, addresses and
networks by design, and it says so at the top. For something you can paste into
a bug report, use [`unifi-map shape`](sharing.md), which is built from an
allowlist and never reports a value from any field.

It reports the map *as drawn*, so it runs after overrides and after
`--obfuscate`. Combining it with `--obfuscate` gives a report with the same
placeholders as the diagram, which is the version to keep beside a shared map.

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
cached, with our own drawings standing in for hardware absent from Ubiquiti's
catalogue. **`--icons builtin`** uses only the icons we draw ourselves: no
network access, no external assets, and still a picture on every node.

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
| Client placed via the topology graph, not its own uplink report | Small hollow circle at the child end of the link |

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
client's uplink, which is how the console draws them correctly. That link is
still something the controller reported, just from a different endpoint than
usual, so it gets the small hollow-circle marker from the table above rather
than the dotted style reserved for what you asserted yourself.

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

`--report` lists exactly which clients ended up there, with their addresses and
networks, which is usually enough to recognise them without opening the diagram.

<!-- BEGIN GENERATED FLAGS -->

## Flag reference

Generated from the argument parser by `scripts/generate_cli_docs.py`, so it
cannot drift from `--help`. Each flag is explained in context further up;
this is for looking one up. Run `unifi-map --help` for the same thing in a
terminal.

```
unifi-map [global options] {fetch,render,all,shape,overrides} [command options]
```

Global options are accepted on either side of the subcommand, so
`unifi-map all --support-file X` and `unifi-map --support-file X all` are
equivalent. Command options must follow the subcommand.

### Global options

| Flag | What it does | Default |
| --- | --- | --- |
| `--env-file` | Credential file (default: $UNIFI_MAP_ENV, ./.env, ~/.config/unifi-map/env) |  |
| `--cache-dir` | Where controller snapshots are read/written. A snapshot is a full inventory of your network, so keeping it outside a git repository is worth doing: set $UNIFI_CACHE_DIR once instead of passing this every time (default: cache) | `cache` |
| `--asset-cache` | Where downloaded artwork is cached (default: cache/assets). Kept separate from --cache-dir so a read-only snapshot directory stays clean. | `cache/assets` |
| `--support-file` `PATH` | Read the topology from a UniFi support file (.tgz) instead of a controller. Needs no credentials and never contacts a controller. Rendering may still fetch artwork; add --offline to stop that too. |  |
| `--site` `NAME` | Which site to read. For a live fetch this overrides UNIFI_SITE, which otherwise falls back to `default`. For a support file it picks one of the sites inside, and is required when the file holds more than one: the run stops and lists them rather than choosing for you. |  |
| `--support-max-member` `SIZE` | Largest single file to decode from a support archive (default 64M). Accepts a plain number or a K/M/G suffix. Raise it if a large site is refused. | `64M` |
| `--support-max-total` `SIZE` | Total to decode from a support archive across all files (default 128M). | `128M` |
| `--support-max-entries` `N` | How many archive entries to walk before giving up (default 100000). Separate from the size caps because entry count does not follow the bytes decoded. | `100000` |
| `--fetch-fingerprints` | Allow downloading Ubiquiti's client fingerprint database, which is what gives clients real product artwork when reading a support file. Off by default: reading a support file otherwise contacts nothing. |  |
| `--fetch-icon-font` | With --support-file, also fetch the generic client glyph font from a controller. This one DOES need UNIFI_HOST and UNIFI_API_KEY, because Ubiquiti publish no copy of that font. Off by default. |  |
| `--icon-font` `DIR` | Load the client glyph font from a directory you copied off a controller yourself (needs its style.css and .ttf). Needs no credentials and no network. See docs/artwork.md. |  |
| `--support-max-archive` `SIZE` | Total uncompressed bytes to walk in a support archive, counting files that are skipped (default 4G). This is what stops a small archive that expands enormously; the other caps only measure what is decoded. | `4G` |
| `--no-progress` | Never show the progress spinner. It already turns itself off when output is not a terminal, so this is only needed for an interactive run whose output something else is reading. |  |
| `--out-dir` | Where diagrams are written (default: out) | `out` |
| `-v`, `--verbose` | Log every artwork lookup, including the ones that found nothing, and name nodes that --obfuscate would otherwise hide. |  |
| `--version` | show program's version number and exit |  |

`fetch` takes only the global options above.


### `render` and `all` options

| Flag | What it does | Default |
| --- | --- | --- |
| `--show-offline` `{yes,no}` | Include devices the controller lists but that are not currently connected. Defaults to no, because a controller keeps remembering hardware long after it has been pulled from the rack; use yes when you want to see what it still thinks exists (default: no) | `no` |
| `-f`, `--formats` `{svg,pdf,png,dot,drawio,mermaid,json,html}` | Output formats (default: svg drawio) | `svg drawio` |
| `--icons` `{unifi,builtin}` | unifi: real Ubiquiti product artwork, fetched and cached at runtime, falling back to our own drawings for any node it cannot resolve, including unidentified clients when no icon font is cached. builtin: our drawings only, nothing fetched (default: unifi) | `unifi` |
| `--layout` `{tree,unifi}` | unifi: left-to-right like the UniFi UI, no port labels. tree: top-down and leaf-staggered, with port labels, built to be readable on a busy network (default: unifi) | `unifi` |
| `--theme` `{dark,light}` | Colour theme (default: light) | `light` |
| `--transparent` | Draw no background, so the map sits on whatever page it is placed on. Applies to svg, pdf, png and drawio. Pick the theme to match the destination: labels are drawn straight onto the canvas with nothing behind them, so light text vanishes on a light page. |  |
| `--offline` | Never reach the network for artwork; use only what is already cached |  |
| `--name` | Output filename stem | `network-map` |
| `--force` | Overwrite output files that unifi-map did not write. Without this, an existing .dot or .drawio it does not recognise is left alone, so a diagram you have edited by hand is not silently replaced. |  |
| `--overrides` | Manual corrections: links the controller cannot see, nesting, renames, your own artwork, and hiding. Defaults to overrides.toml when that file exists |  |
| `--obfuscate` | Replace hostnames, addresses, MACs, network names and SSIDs with stable placeholders, keeping topology, roles and artwork intact, so the diagram can be shared |  |
| `--report` | After rendering, print a diagnostic report on stdout saying where the map came from: which endpoint placed each client, what could not be placed, and which artwork matches were refused as ambiguous. NOT safe to share, since it names your devices; use `unifi-map shape` for that |  |
| `--title` | Diagram title (default: Network map). Note that --obfuscate cannot clean a title you supply yourself |  |
| `--no-clients` | Infrastructure only, no clients |  |
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
| `action` `{check}` | check: apply the file against the cached snapshot and report, failing on any selector that matches nothing or several things |  |
| `--show-offline` `{yes,no}` | Include devices the controller lists but that are not currently connected. Defaults to no, because a controller keeps remembering hardware long after it has been pulled from the rack; use yes when you want to see what it still thinks exists (default: no) | `no` |
| `--overrides` | Which file to check. Defaults to overrides.toml when it exists. |  |

<!-- END GENERATED FLAGS -->
