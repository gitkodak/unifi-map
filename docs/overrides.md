# Manual topology overrides

[← Documentation index](../README.md#documentation)

Manual corrections for the things a controller cannot tell you.

## The problem

A controller can only report what it participates in. So two real
relationships stay invisible to it:

**Links it is not in the path of.** A NAS that connects to a switch over
a 10G SFP+ DAC often has no `sw_mac` in `stat/sta`. The renderer has
nothing to attach it to, so it lands under the "Uplink not reported by
controller" placeholder. [`[[link]]`](#link) is the fix. The placeholder
disappears once nothing remains under it.

**Nesting.** A VM or container appears as an ordinary client, with its
own MAC and IP. Nothing in the data says it lives inside a particular
hypervisor. So the map draws it as a peer of the host it runs on, which
actively misleads a reader.

**Noise that is technically online.** An access point whose radios you
disabled on purpose is still `state: 1` to the controller, so
`--show-offline no` does not remove it. It is not broken, and it is not
offline. It is just not doing anything, and on a busy map that is
clutter.

**Wrong identification.** Ubiquiti's fingerprint database is confident
and sometimes wrong. A wrong fingerprint costs you twice: the client
gets the wrong name and the wrong artwork. Take a network-attached bidet
that the database reliably identifies as a smart toothbrush. No
cleverness in this tool can fix that. The upstream data says toothbrush.

None of this is safe to infer. A plausible guessed parent, or a quietly
substituted generic icon when the fingerprint looks improbable, would
both invent data. So you state it yourself.

## Format

This uses TOML. Python 3.11+ reads it from the standard library
(`tomllib`), it takes comments, and it is pleasant to hand-edit. It adds
no new dependency.

See [`examples/overrides.toml`](../examples/overrides.toml) for a working file.

### `[[device]]`

`[[device]]` declares a device the controller cannot see. A controller
only reports what it manages. So this covers an unmanaged switch with no
management plane, a fully managed third-party switch, and UniFi gear
that was off when you ran the fetch, all for the same reason. Everything
else here corrects a node that exists. This one creates it.

| Key | Required | Meaning |
| --- | --- | --- |
| `name` | yes | Label on the map, and what other blocks select it by |
| `kind` | no | `gateway`, `switch`, `ap`, `bridge`, `wired_client`, `wireless_client` or `unknown`. Defaults to `unknown`, which draws the generic shape. |
| `ip` | no | Address, shown under the name |
| `model` | no | Model string, shown under the address |
| `parent` | no | Selector for what it attaches to. Without one, it floats. |
| `port` | no | Port on the parent, for the edge label. Needs a `parent`. |
| `icon` | no | Path to artwork you supply |
| `note` | no | Free text. Recorded but not drawn. See [Where `note` shows up](#where-note-shows-up). |

The tool adds declared devices before every other override, so a
`[[link]]`, a `[[hosted]]`, or a `[[node]]` can reference one, and one
declared device can attach to another. Their ids carry an `asserted-`
prefix. This stops a device named after a MAC from shadowing a real
node.

They render with a **dotted outline**, for the same reason asserted
links render dotted: a map must never present something you typed in as
though the controller reported it. Offline devices use dashes, and
asserted devices use dots, so the two stay distinguishable without
colour.

### `[[link]]`

| Key | Required | Meaning |
| --- | --- | --- |
| `from` | yes | Selector for one end |
| `to` | yes | Selector for the other end |
| `port` | no | Port number, for the edge label. May be unquoted. |
| `speed` | no | e.g. `"10G"`, for the edge label |
| `note` | no | Free text. Becomes the edge label when there is no `port` or `speed`. See [Where `note` shows up](#where-note-shows-up). |
| `wireless` | no | `true` renders the link dashed |

### `[[hosted]]`

| Key | Required | Meaning |
| --- | --- | --- |
| `guest` | yes | Selector for the nested node |
| `host` | yes | Selector for the node it runs on |
| `note` | no | e.g. `"VM"`, `"container"`. Becomes the edge label, replacing the default `hosted`. |

### `[[node]]`

`[[node]]` corrects how the map presents a single node.

| Key | Required | Meaning |
| --- | --- | --- |
| `match` | yes | Selector for the node to correct |
| `name` | no* | Replacement label |
| `icon` | no* | Path to artwork you supply |
| `hide` | no* | `true` drops the node from the map entirely |
| `note` | no | Free text. Recorded but not drawn. See [Where `note` shows up](#where-note-shows-up). |

\* You must set at least one of `name`, `icon`, or `hide`. The tool
rejects an entry that changes nothing, rather than silently ignoring it.

```toml
[[node]]
match = "10.0.30.22"
name = "Network Bidet"
icon = "assets/bidet.png"
note = "UniFi is convinced this is a smart toothbrush"
```

#### Hiding a node

```toml
[[node]]
match = "10.0.20.99"
hide = true
note = "internal service, not for a diagram I am sharing"
```

Two reasons you might want this. One is noise: "online" and "actually
participating" are different things, and the controller only reports
the first. So an access point whose radios you disabled on purpose is
still `state: 1`, and `--show-offline no` cannot touch it. The other is
discretion, for when the map goes to somebody else, and not everything
on your network is their business.

**You can only hide leaf nodes.** Hiding a switch or an access point
would orphan everything behind it, and there is no good answer for what
should happen to the children: dropping them silently loses real
devices, and reattaching them to the hidden node's parent invents a link
that does not exist. So the tool refuses to hide a node that has
children. It reports an error naming the node and its children, instead
of guessing.

#### Choosing artwork that looks right

The tool fits your image into the same box as every other icon, about
168 by 90 points, and keeps its aspect ratio. It never crops the image
or scales it up beyond that box, so it cannot come out oversized. What
varies is how much of the box the image fills. That is what makes an
image look wrong next to its neighbours.

For reference, Ubiquiti's own artwork ranges from 87 to 256 pixels on a
side, with aspect ratios from about 1:3 for a tall access point to 7:1
for a rack-mount switch. Most devices are close to square.

Practical guidance:

- **Match the proportions of the thing you are replacing.** A roughly
  square image is the safest default. A very wide image fits the box on
  its width and ends up short. A very tall one fits on its height and
  ends up narrow. Either can look small beside a square neighbour, even
  with an identical box.
- **Trim empty margins yourself.** The tool crops fetched artwork to its
  visible content automatically. It uses artwork you supply exactly as
  given. Padding counts as part of the image, so a subject that floats
  in a large transparent canvas renders noticeably smaller than
  everything around it. This is the most common reason a custom icon
  looks wrong.
- **Use PNG with transparency.** A white or opaque background becomes a bright
  slab on the dark theme. Transparent PNG is what the fetched artwork uses.
- **Around 256 pixels on the long edge is plenty.** The tool scales
  everything down to the box anyway, and it base64-embeds the file into
  every SVG you produce. So a large photograph inflates the output for
  no visible gain.
- **An SVG needs one of two treatments, and either is fine.**

  **Install the extra.** The tool rasterises an SVG to a cached PNG as
  it reads it in, then treats it exactly like any other artwork, in
  every output format. The file needs no preparation first.

  ```bash
  pip install 'unifi-map[svg]'
  ```

  **Or convert the file to PNG.** That adds no dependency, and it leaves
  nothing to install on the next machine. It is the better answer if the
  artwork is finished and stays fixed.

  Prefer the extra if you are still editing the artwork, or you have
  several SVGs, or you would rather keep the source file as the thing
  you maintain.

  **Without the extra, two limitations apply**, and both belong to
  Graphviz, not this tool:

  - The icon is **missing from `png` and `pdf`**. Graphviz loads SVG
    images only for its own `svg` driver. `png` and `pdf` go through
    cairo instead, which has no SVG loader, so Graphviz reports `No
    loadimage plugin for "svg:cairo"` and continues. The `svg` and
    `drawio` outputs are fine. You get a warning that names the file.
  - The file **must open with an XML declaration**
    (`<?xml version="1.0"?>`). Graphviz refuses one without it, and it
    reports the whole file as missing, failing the entire render. This
    tool refuses the file first instead, with an error that names the
    reason. Many drawing tools omit the declaration, so check that first
    if an SVG gets rejected.

  Either way, the tool reads size from the `<svg>` tag's `width` and
  `height`, if it has them, or from its `viewBox` otherwise, which is
  how most tools export. Only the ratio matters. Dimensions come from
  the `<svg>` element itself, so shapes inside it do not affect the
  size.

  **PNG needs none of this.** A one-time conversion is a real answer,
  not a consolation prize.
- **Graphviz also accepts JPEG, GIF, and WebP**, but none of them handle
  transparency as reliably as PNG.

A photograph of the actual device, background removed and cropped tight, sits
alongside Ubiquiti's renders better than an icon or a logo does.

Relative `icon` paths resolve against **the overrides file's
directory**, not the working directory. So you can move a config and
its assets folder together, and it still works, regardless of where you
run the tool.

The tool embeds your artwork into the SVG the same way it embeds fetched
artwork. So the output stays a single portable file, and no local path
appears in it.

**An SVG leaves a copy on disk.** With the `svg` extra installed, the
tool rasterises an SVG override to PNG once, and keeps that PNG under
`<asset-cache>/user-svg/`, named after a hash of the source file's
contents. If you edit your SVG, that produces a new entry, rather than
replacing the old one. Nothing removes either copy automatically, so
copies accumulate.

Unlike the rest of the artwork cache, which holds Ubiquiti's public
imagery and is world-readable, these files are `0600` inside a `0700`
directory. A rendering of your own file is not the same thing as a
downloaded product photo.

This means **deleting your original SVG does not delete the rendered
copy**. The copies live in `user-svg/`, inside whatever you set as the
asset cache. By default, that is:

```bash
rm -rf cache/assets/user-svg
```

If you moved the cache with `--asset-cache` or `UNIFI_ASSET_CACHE`, delete
`user-svg/` inside that directory instead.

**Type the path out. Do not let a shell expand it.** People often set
`UNIFI_ASSET_CACHE` in the credential file, not the shell, so the
variable can be empty in your terminal while the tool still uses it. An
empty expansion inside `rm -rf` then aims at an absolute path you did
not mean.

If you are not sure where it ended up, `-v` reports the resolved
directories while it runs:

```
Directories: cache=... assets=... out=...
```

That means you must run a render, which writes output and may download
artwork, so it is a heavier way to read a path than it looks. Check your
credential file and `unifi-map render --help` instead, which states the
default. That is usually quicker.

The tool does not copy PNG or other raster overrides anywhere. Only SVG
rasterisation writes to the cache.

### Selectors

`from`, `to`, `guest`, `host`, `parent`, and `match` all accept a MAC, an
IP, or a hostname/device name, as the map displays it. Names, rather
than ids, keep the file readable, and they mean you only correct one
place when the controller renames a device.

## How selectors are matched

The tool tries a selector as a MAC address, then an IP address, then the
label the map shows, in that order of specificity. A selector that
matches nothing, or matches more than one node, stops the run with an
error that names what it found. A typo that silently does nothing is
worse than a failed render, because you would believe the tool applied
the correction.

MAC addresses are the only selectors that are always unique. Names are
easier to read, and usually fine.

## What it looks like

The map draws anything you assert as a **dotted** line. The legend gains
a "Stated in overrides" entry when a render contains one. The map never
lets something you claim look like something the controller reported.

## Checking a file without rendering

```bash
unifi-map overrides check
```

This applies the file against the cached snapshot, and reports what it
would do, without drawing anything. This matters, because overrides
fail loudly by design: a selector that matches nothing, or that matches
two things, stops the run. That is the right behaviour. Before this
command existed, the only way to discover a bad selector was to render
the whole map.

It reads the cache, so it contacts no controller and needs no credentials.

**This honours `--show-offline`, and defaults to `no`, exactly as
`render` does.** That matters more than it sounds. A selector that names
a device the controller remembers, but that is not currently connected,
resolves only when you include offline devices. If you check with
different settings than the render you are checking for, a file could
pass here and fail there. That is the one outcome this command exists
to prevent. If you render with `--show-offline yes`, check with it too.

## Generating a starting point

```bash
unifi-map overrides generate > candidates.toml
```

This prints a commented skeleton to stdout. It seeds the skeleton from
the same three things
[`--report`](usage.md#how-much-to-trust-the-map---report) names: clients
with no reported uplink, switch ports shared by several wired clients (a
hint that an unmanaged switch or a virtualisation host is hiding there),
and artwork matches refused as ambiguous.

**Every block is commented out.** The file changes nothing until you
edit and uncomment the parts you want. So you can redirect it straight
to a file and read it at your leisure. You do not need to review it
line by line before it can touch anything.

**The one thing it never fills in is a client's real uplink.** A
`[[link]]` skeleton always sets `from` to the client's MAC, the one
selector that is always unique, and leaves `to = ""` for you. Guessing
where a cable actually goes would be exactly the invented topology this
file exists to avoid. A shared-port skeleton fills in more, because less
is actually unknown: the skeleton reads the suggested device name and
its `parent`/`port` straight off the map. You only decide whether the
device is real, by choosing whether to uncomment it.

Like `check`, this reads the cache and contacts no controller. It
resolves artwork ambiguity offline, best-effort, the same way
`unifi-map shape` resolves it. Only what is already cached counts, and
it fetches nothing.

**A cold artwork cache gets a `NOTE`, not silence.** This command never
fetches the UniFi hardware catalogue itself. So if nobody downloaded it
yet (no `unifi-map render --icons unifi` or `fetch` run), the
ambiguous-artwork check did not merely find nothing. It never ran at
all. The printed file says so explicitly. It does not read like a clean
bill of health for a network the tool simply never checked.

## Where `note` shows up

`note` behaves differently per block. All four blocks accept it, but
only two draw it.

| Block | Effect |
| --- | --- |
| `[[link]]` | The edge label, but only when neither `port` nor `speed` is set. Those win. |
| `[[hosted]]` | The edge label, replacing the default text `hosted`. |
| `[[device]]`, `[[node]]` | None. Read and validated, never drawn: a comment for whoever edits the file next. |

A `#` comment does the same job for the two that do not draw it, and
TOML keeps those perfectly well. The tool accepts `note` there anyway,
so a block moved between kinds does not fail on a key that was fine a
moment earlier.

## Order of application

The tool applies links and nesting first, then renames, artwork, and
hiding. That ordering matters. If an override gives a node a child, the
tool correctly refuses an attempt to hide that node in the same file.

## Design constraints

- **Overrides add rather than rewrite. Where they must rewrite, they say
  so.** `[[link]]` and `[[hosted]]` both detach a node from its current
  parent before they attach the one you stated, because a node with two
  parents is not a tree. Usually the detached node is the "uplink not
  reported" placeholder, which is no loss. Sometimes it is a real
  observation: this is exactly what happens when you reparent a VM under
  its hypervisor, the whole point of `[[hosted]]`. When the displaced
  link was something the controller actually reported, a warning names
  both ends, so a contradiction is never silent, even though the tool
  allows it. Under `--obfuscate`, the warning still appears, but it
  reports only how many links it replaced. Those labels are exactly what
  that flag exists to keep out of a terminal or a CI log.
- **Never invent topology.** This feature exists precisely so the tool doesn't
  have to guess. Its output must remain distinguishable from observed data.
- **A stale override should fail loudly.** Devices get replaced and
  renamed over time. An overrides file that no longer matches must
  complain, not degrade silently.
