# Usage

[← Documentation index](../README.md#documentation)

This page covers every command and flag, and how to read what they produce.
`scripts/generate_cli_docs.py` generates the reference at the end from the
argument parser, so it cannot drift from `--help`.

Every example below assumes `unifi-map` is on your `PATH`. If you installed
into a virtual environment, activate it first
(`source .venv/bin/activate`), or write `.venv/bin/unifi-map` in full. See
[Install](../README.md#install).

```bash
unifi-map all                              # fetch + render
unifi-map fetch                            # snapshot the controller into cache/
unifi-map fetch --support-file FILE.tgz     # or read a support file instead
unifi-map render                           # render from the cached snapshot
unifi-map render --per-network              # one diagram per client network
unifi-map overrides check                   # validate overrides without rendering
unifi-map overrides generate                # print a starting overrides.toml skeleton
unifi-map shape                             # describe the network, for sharing
unifi-map render --no-clients               # infrastructure only
unifi-map render -f svg pdf drawio dot      # pick formats
```

`fetch` and `render` are separate on purpose. You can re-render endlessly
while you adjust style, without extra load on the controller. Each cached
snapshot is a record of what the network looked like at that moment.

**`all` means both stages, not all output formats.** It runs `fetch`, then
`render`. It writes the same default two files any `render` would: an SVG
and a draw.io file. If you want the other formats, ask for them:

```bash
unifi-map all -f svg pdf png dot drawio mermaid json
```

The default is two formats, not seven, because those two answer the common
cases: one to look at, one to edit. The rest cost time and disk on every
run. [Every format and what it is for](output.md).

### What actually touches the network

This needs precision, because there are two caches, and they behave
differently:

| Command | Controller | Artwork |
| --- | --- | --- |
| `fetch` | Contacts the controller unless you give `--support-file`. It never checks the cache first, so it always overwrites the snapshot with current state. | Fetches the icon font and replaces any cached copy |
| `render` | Never. Reads whatever snapshot is in `--cache-dir`, however old. | Downloads any artwork not already cached, unless `--offline` |
| `all` | Same as `fetch`, because it is `fetch` then `render` | Same as `render` |

If you read a support file, this contacts no controller. But `all` still
renders afterward, and rendering fetches artwork. For a genuinely
network-free run, add `--offline` or `--icons builtin`.

So `unifi-map all` does not skip the fetch when a cache already exists. It
refreshes unconditionally. If you want to re-render without contacting the
controller, use `render`.

Each `fetch` writes one complete generation of the snapshot, then switches
a pointer to it as its last step. So a fetch cut off mid-way never leaves a
mixture of old and new payloads. `render` reads the previous complete
generation until the next one is fully in place. The fetch then removes
older generations. A cache written before this layout still reads. The
next fetch migrates it.

`render` is not automatically offline. On a cold artwork cache, it reaches
Ubiquiti's CDN for product images. Pass `--offline` to forbid that, or
`--icons builtin` to avoid artwork entirely. Once the artwork cache is
warm, `render` makes no network calls in practice. That is a side effect
of a full cache, not a guarantee this command makes.

### When something looks wrong: `-v`

```bash
unifi-map -v render
```

Verbose mode logs every artwork lookup, including the ones that came back
empty. That is usually enough to distinguish the two common cases:

- **Ubiquiti has no artwork for that device.** The lookup ran, and the
  asset genuinely is not published. There is nothing to fix here. The
  shape or glyph fallback is correct.
- **The match went wrong.** The device resolved to the wrong product, or
  to nothing when a correct match exists. [Overrides](overrides.md) can
  correct it. Please report this too.

Missing artwork stays quiet at the normal log level, on purpose. A handful
of unrecognised devices is ordinary on any network, and a warning per
device would drown the output. `-v` is where the detail lives.

It also raises the detail on everything else, so attach it first to any
bug report. Redact addresses and hostnames before you paste it.

### Less output: `-q`/`--quiet`

```bash
unifi-map -q all
```

This is the opposite of `-v`. It logs only errors: no topology/style
summary, no artwork tally, and none of the unplaced-client or shared-port
hints. Those all restate steady-state facts about the network, not
something that just changed. That is exactly the noise a scripted or cron
run wants silenced. Otherwise, the same run prints the identical warning
every single time, even when nothing changed.

It implies `--no-progress`. A spinner is the same kind of interactive
narration `-q` exists to suppress. `-q` and `-v` together are refused
outright, rather than letting one silently win.

**It only touches console narration, not printed output.** `--report`,
`unifi-map shape`, and `unifi-map overrides generate` all print straight to
stdout, instead of logging. So `-q` does not shorten any of them. This
includes the cold-cache `NOTE` that `overrides generate` can print. That
note is part of the file it writes, not a log line.

### How much to trust the map: `--report`

```bash
unifi-map render --report
```

A map drawn from a complete fetch and one drawn from a thin one look
equally authoritative. `--report` lets you distinguish them. After
rendering, it prints where every part of the map came from.

```
WHERE THE MAP CAME FROM
  nodes               29
          8  stat/device (the device inventory)
         19  stat/sta (the client list. 'sta' is UniFi's term for a connected client)
          2  ours (Internet, placeholder)

  links               27
          7  stat/device uplink (a device reporting its own connection)
          1  gateway to the Internet
         16  stat/sta sw_mac or ap_mac (a client reporting which switch or AP it's on)
          1  the controller's topology graph
          2  nothing reported one
```

**What these labels mean.** The controller's own web UI draws itself from
several JSON endpoints, and this tool calls the same ones. The names above
are theirs, not invented for this report:

- **`stat/device`** is the device inventory: every switch, access point, gateway
  and other piece of infrastructure the controller manages directly.
- **`stat/sta`** is the client list: phones, laptops, IoT gear, anything that
  isn't itself managed UniFi hardware. `sta` is short for "station", a term
  UniFi borrowed from wireless networking, where every connected device, wired
  or not, is called a station. It has nothing to do with "static."
- **The controller's topology graph** is a separate endpoint that tracks link
  relationships directly, used as a fallback when a client's own record doesn't
  say what it's plugged into. This happens for anything sitting behind
  non-UniFi gear (a VM behind a NAS, say), since `stat/sta` only reports an
  uplink when that uplink is itself a UniFi device.
- **An overrides file** means a human typed it in. Nothing here observed
  it. See [Overrides](overrides.md).

It also lists what the snapshot actually carried, and what each missing
piece costs. The tool logs a failed optional endpoint once, when it
fetches it, and never mentions it again. So a snapshot cached before an
app was installed renders thinner every time, with nothing to explain why:

```
  MISSING OR UNUSABLE
  topology          clients behind non-UniFi gear cannot be placed without it
  protect_cameras   tells a camera from an Access reader of the same name
```

Then, where anything needs attention, it names the devices involved,
rather than only counting them:

- Clients that could not be placed.
- Clients with no address from any source.
- Networks a client claims to be on that the controller does not list.
- Switch ports shared by several wired clients. This hints that an
  unmanaged switch or a virtualisation host is hiding there.
- Artwork matches [refused as ambiguous](artwork.md).

A map with nothing wrong prints no device names at all, so a short report
is a good sign. Where any of these apply, `unifi-map overrides generate`
prints a commented starting point, seeded from exactly what the report
found.

The counts are the point of the first section: how much of the map the
controller reported directly, how much came from a second endpoint, and
how much you asserted yourself. A link from the topology graph also gets a
small hollow-circle marker on the diagram itself (see [Reading the
diagram](#reading-the-diagram)). The tool draws an asserted link dotted.
So the report and the picture agree. The report is not the only place
this distinction shows.

**Every join here is on MAC address**, and most phones and laptops rotate
theirs periodically. When that happens, the same physical device
reappears as an unrelated new client, not as an update to the one already
on the map. Nothing is wrong. No overrides entry fixes this. A rotated MAC
is detectable without any cooperation from the controller, because it
sets IEEE 802's locally-administered bit. So `--report` counts how many
clients currently show one:

```
RANDOMISED MAC ADDRESSES
  3 of 19 client(s) advertise a locally-administered
  MAC, which most phones and laptops rotate periodically. The same physical
  device can reappear here as a new client rather than as the one already on
  the map. This is expected, and not something an overrides file can fix.
```

This section counts, rather than names, unlike the sections above. There
is nothing wrong with any specific device here.

**This report is not safe to share.** It names your devices, addresses,
and networks by design, and it says so at the top. For something you can
paste into a bug report, use [`unifi-map shape`](sharing.md) instead. It
builds its output from an allowlist and never reports a value from any
field.

It reports the map *as drawn*, so it runs after overrides and after
`--obfuscate`. If you combine it with `--obfuscate`, the report gets the
same placeholders as the diagram. Keep that version beside a shared map.

### Overwriting: `--force`

By default, `render` refuses to replace a `.dot` or `.drawio` file it did
not write. So it leaves alone a diagram you have opened and rearranged,
instead of silently replacing it. It needs no flag to re-render output it
recognises as its own.

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

**`--icons unifi`** uses real Ubiquiti product artwork for both UniFi
hardware and clients, the same images the topology view shows. It fetches
this on first run and caches it. Our own drawings stand in for hardware
absent from Ubiquiti's catalogue. **`--icons builtin`** uses only the
icons we draw ourselves. It needs no network access and no external
assets, but it still gives every node a picture.

**`--layout unifi`** approximates the UniFi UI: left-to-right tree,
orthogonal links, no port labels, no title or legend chrome, and a canvas
trimmed to the drawing. See below for how close that actually gets.
**`--layout tree`** runs top to bottom, with staggered leaf nodes, port
numbers on links, a title block, and a legend. It stays readable on a
busy network. Try both. On a network with many clients, `tree` is usually
the one to hand to someone else.

### Not retyping them: `~/.config/unifi-map/config.toml`

If your taste differs from the defaults, put it in a config file instead of on
every command line:

```toml
theme   = "dark"
layout  = "tree"
formats = ["svg", "png"]
```

The same settings are readable from `UNIFI_MAP_*` environment variables
too. This makes the tool configurable in a container, with no file to
mount. Precedence runs flag, then environment, then config file, then the
default. Every render prints which settings it did not get from the
command line, and where each one came from.

`--obfuscate` and `--force` are not settable this way, on purpose. See
[credentials and configuration](credentials.md#preferences-the-config-file-and-unifi_map_)
for the full list of keys.

### How close is `--layout unifi`?

This layout gets close, not exact. It cannot look *exactly* like the
controller UI: the tooling necessarily leaves its mark on the output.
This project aims to get as close as possible.

Concretely, what differs:

- **Graphviz does the layout, not UniFi.** The tree connects the same
  way, but Graphviz decides the sibling order and the precise spacing.
- **Link routing is orthogonal but not identical.** The renderer decides
  the corners, the channel spacing, and where a line breaks.
- **Fingerprints are sometimes wrong.** Client artwork comes from
  Ubiquiti's fingerprint database, and it misidentifies things, such as a
  phone shown as an appliance. That is upstream data, not a rendering
  bug. [Overrides](overrides.md) exist to correct it.
- **Typography and label content differ.** This tool uses Helvetica/Arial
  and shows name, address, and product name. The UI has its own font and
  its own idea of what belongs on a node.
- **It is a static picture.** It has no hover, no expand or collapse, and
  no live state.

If you need the real thing, the real thing is in your browser. This is for when
you need it in a file.

**`--show-offline yes|no`** (default `no`) controls whether devices the
controller still lists, but that are not connected, appear on the map.
This is the one place the defaults deviate from the web view, on purpose.
A controller keeps remembering hardware long after somebody removes it
from the rack, and the UI gives you no way to hide it. Use `yes` to see
everything the controller still thinks exists.

Further options:

- `--legend` / `--no-legend`
- `--title-block` / `--no-title-block`
- `--stagger N` (aspect-ratio control for `tree`)
- `--offline` (never touch the network for artwork)
- `--title`
- `--name`
- `--out-dir`
- `--cache-dir`
- `--asset-cache` (artwork cache, kept separate from snapshots)

## Reading the diagram

Colour is never the only signal. The accent palette is
[Okabe-Ito](https://jfly.uni-koeln.de/color/). This project chose it to
stay separable under red-green colour blindness. Every distinction is
*also* carried by artwork, shape, or line style, so the diagram survives
greyscale printing.

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
| Switch port shared by several wired clients | Small diamond at the child end of the link, present in every layout |

With `--layout tree`, edge labels show switch port numbers (`port 12`) or
the radio for wireless clients. A shared port also gets a trailing `*`
(`port 12 *`). `--layout unifi` never shows port labels at all, because
ortho routing cannot place them. That is why the diamond marker above
does not depend on one.

The legend only lists what a given render actually encodes. A node drawn
as artwork has no border and no fill, so it carries no accent colour and
gets no role swatch. Its role is the artwork itself. Swatches appear only
for roles that used a shape in that render, under "Without artwork".
`--layout unifi` omits the legend entirely. This matches the UniFi UI.

### "Uplink not reported by controller"

You will probably never see this node, but it exists for the case where the
controller genuinely does not know where something is attached.

`stat/sta` only reports a client's uplink when that uplink is a UniFi
device. So anything behind a non-UniFi box, such as VMs and containers
behind a NAS, or a client on a switch the controller does not manage,
comes back with no `sw_mac` at all. The tool resolves these against the
controller's own topology graph instead, where a client can be another
client's uplink. This is how the console draws them correctly too. That
link is still something the controller reported, just from a different
endpoint than usual. So it gets the small hollow-circle marker from the
table above, not the dotted style reserved for what you assert yourself.

The tool anchors anything still unresolved to an explicit placeholder. It
does not leave the node floating, which looks like a bug. It does not
attach the node to a guessed parent either, because that would invent a
connection that does not exist.

**You can place them yourself.** The tool refuses to guess, but you know
where the cable goes. [Manual overrides](overrides.md) are how you say
so. A `[[link]]` attaches the client to its real parent. If that parent
is also a switch the controller cannot see, `[[device]]` declares the
switch first, and the link attaches to it. Both render dotted, so the map
still distinguishes what you asserted from what the controller reported.
The placeholder disappears once nothing remains under it. [`unifi-map
overrides generate`](overrides.md#generating-a-starting-point) prints a
skeleton with the selectors already filled in, so you only have to say
where they connect.

`--report` lists exactly which clients ended up there, with their
addresses and networks. That is usually enough to recognise them. You do
not need to open the diagram.

### One machine, several nodes

The tool draws a server with an interface on three VLANs as **three
clients**, each with its own name and address, side by side. A
hypervisor's bridge interfaces work the same way. Nothing is wrong. The
map shows you what the network reports.

**The controller reports network interfaces, not machines.** As far as
any of its endpoints are concerned, three MAC addresses on three VLANs
are three clients. No field anywhere says they share a chassis. So the
tool draws a logical map, of what is reachable and how, rather than a
physical map of what is in the building.

**`--per-network` solves this.** Each VLAN gets its own diagram. In it,
that machine appears exactly once, as the interface that belongs to that
network, with the address it has there. The duplication only exists in
the combined map, because that map shows every network at once.

In the combined view, a `[[node]]` rename in an [overrides file](overrides.md)
gives the interfaces distinguishable names, which turns a confusing repeat into
an obvious one: `nas (storage)` beside `nas (management)`.

<!-- BEGIN GENERATED FLAGS -->

## Flag reference

Generated from the argument parser by `scripts/generate_cli_docs.py`, so it
cannot drift from `--help`. Each flag is explained in context further up.
This is for looking one up. Run `unifi-map --help` for the same thing in a
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
| `--support-file` `PATH` | Read the topology from a UniFi support file (.tgz) instead of a controller. Needs no credentials and never contacts a controller. Rendering may still fetch artwork. Add --offline to stop that too. |  |
| `--site` `NAME` | Which site to read. For a live fetch this overrides UNIFI_SITE, which otherwise falls back to `default`. For a support file it picks one of the sites inside, and is required when the file holds more than one: the run stops and lists them rather than choosing for you. |  |
| `--support-max-member` `SIZE` | Largest single file to decode from a support archive (default 64M). Accepts a plain number or a K/M/G suffix. Raise it if a large site is refused. | `64M` |
| `--support-max-total` `SIZE` | Total to decode from a support archive across all files (default 128M). | `128M` |
| `--support-max-entries` `N` | How many archive entries to walk before giving up (default 100000). Separate from the size caps because entry count does not follow the bytes decoded. | `100000` |
| `--fetch-fingerprints` | Allow downloading Ubiquiti's client fingerprint database, which is what gives clients real product artwork when reading a support file. Off by default: reading a support file otherwise contacts nothing. |  |
| `--fetch-icon-font` | With --support-file, also fetch the generic client glyph font from a controller. This one DOES need UNIFI_HOST and UNIFI_API_KEY, because Ubiquiti publish no copy of that font. Off by default. |  |
| `--icon-font` `DIR` | Load the client glyph font from a directory you copied off a controller yourself (needs its style.css and .ttf). Needs no credentials and no network. See docs/artwork.md. |  |
| `--support-max-archive` `SIZE` | Total uncompressed bytes to walk in a support archive, counting files that are skipped (default 4G). This is what stops a small archive that expands enormously. The other caps only measure what is decoded. | `4G` |
| `--no-progress` | Never show the progress spinner. It already turns itself off when output is not a terminal, so this is only needed for an interactive run whose output something else is reading. |  |
| `--out-dir` | Where diagrams are written (default: out) | `out` |
| `-v`, `--verbose` | Log every artwork lookup, including the ones that found nothing, and name nodes that --obfuscate would otherwise hide. |  |
| `-q`, `--quiet` | Only log errors: no topology/style summary, no artwork tally, no unplaced-client or shared-port hints. Those restate steady-state facts about the network rather than something that just changed, which is exactly the noise a scripted or cron run wants silenced. Does not touch printed output (--report, shape, overrides generate), only console narration. Implies --no-progress. Not allowed with -v/--verbose. |  |
| `--version` | show program's version number and exit |  |

`fetch` takes only the global options above.


### `render` and `all` options

| Flag | What it does | Default |
| --- | --- | --- |
| `--show-offline` `{yes,no}` | Include devices the controller lists but that are not currently connected. Defaults to no, because a controller keeps remembering hardware long after somebody pulls it from the rack. Use yes when you want to see what it still thinks exists (default: no) | `no` |
| `-f`, `--formats` `{svg,pdf,png,dot,drawio,mermaid,json,html}` | Output formats (default: svg drawio) | `svg drawio` |
| `--icons` `{unifi,builtin}` | unifi: real Ubiquiti product artwork, fetched and cached at runtime, falling back to our own drawings for any node it cannot resolve, including unidentified clients when no icon font is cached. builtin: our drawings only, nothing fetched (default: unifi) | `unifi` |
| `--layout` `{tree,unifi}` | unifi: left-to-right like the UniFi UI, no port labels. tree: top-down and leaf-staggered, with port labels, built to be readable on a busy network (default: unifi) | `unifi` |
| `--theme` `{dark,light}` | Colour theme (default: light) | `light` |
| `--transparent` | Draw no background, so the map sits on whatever page it is placed on. Applies to svg, pdf, png and drawio. Pick the theme to match the destination: labels are drawn straight onto the canvas with nothing behind them, so light text vanishes on a light page. |  |
| `--offline` | Never reach the network for artwork. Use only what is already cached |  |
| `--name` | Output filename stem | `network-map` |
| `--force` | Overwrite output files that unifi-map did not write. Without this, an existing .dot or .drawio it does not recognise is left alone, so a diagram you have edited by hand is not silently replaced. |  |
| `--overrides` | Manual corrections: links the controller cannot see, nesting, renames, your own artwork, and hiding. Defaults to overrides.toml when that file exists |  |
| `--obfuscate` | Replace hostnames, addresses, MACs, network names and SSIDs with stable placeholders, keeping topology, roles and artwork intact, so the diagram can be shared |  |
| `--report` | After rendering, print a diagnostic report on stdout saying where the map came from: which endpoint placed each client, what could not be placed, and which artwork matches were refused as ambiguous. NOT safe to share, since it names your devices. Use `unifi-map shape` for that |  |
| `--title` | Diagram title (default: Network map). Note that --obfuscate cannot clean a title you supply yourself |  |
| `--no-clients` | Infrastructure only, no clients |  |
| `--per-network` | Also emit one diagram per client network, which keeps a busy map readable |  |
| `--legend`, `--no-legend` | Show the legend (default: on for --layout tree, off for --layout unifi) |  |
| `--title-block`, `--no-title-block` | Show the title and subtitle above the map. A title sets a minimum canvas width, so turning it off crops dead space on a narrow map (default: on for --layout tree, off for --layout unifi) |  |
| `--stagger` `N` | With --layout tree, stagger leaf nodes into rows of ~N to control aspect ratio (0 disables. Higher is taller and narrower. Default 12) | `12` |

### `shape` options

| Flag | What it does | Default |
| --- | --- | --- |
| `--yes` | Skip the consent prompt. Read what the report contains first. `unifi-map shape` on its own prints that and asks. |  |

### `overrides` options

| Flag | What it does | Default |
| --- | --- | --- |
| `action` `{check,generate}` | check: apply the file against the cached snapshot and report, failing on any selector that matches nothing or several things. generate: print a commented overrides skeleton, seeded from what the cached snapshot could not resolve, to stdout |  |
| `--show-offline` `{yes,no}` | Include devices the controller lists but that are not currently connected. Defaults to no, because a controller keeps remembering hardware long after somebody pulls it from the rack. Use yes when you want to see what it still thinks exists (default: no) | `no` |
| `--overrides` | Which file to check. Defaults to overrides.toml when it exists. Not used by generate. |  |

<!-- END GENERATED FLAGS -->
