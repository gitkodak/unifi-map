# Manual topology overrides

[← Documentation index](../README.md#documentation)

Manual corrections for the things a controller cannot tell you.

## The problem

A controller can only report what it participates in, so two real relationships
are invisible to it:

**Links it isn't in the path of.** A NAS connected to a switch over a 10G SFP+
DAC often has no `sw_mac` in `stat/sta`. The renderer has nothing to attach it
to, so it lands under the "Uplink not reported by controller" placeholder.
[`[[link]]`](#link) is the fix, and the placeholder disappears once nothing is
left under it.

**Nesting.** A VM or container appears as an ordinary client with its own MAC and
IP. Nothing in the data says it lives inside a particular hypervisor, so it is
drawn as a peer of the host it runs on, which is actively misleading.

**Noise that is technically online.** An access point whose radios you disabled
on purpose is still `state: 1` to the controller, so `--show-offline no` will not
remove it. It is not broken and it is not offline; it is just not doing anything,
and on a busy map that is clutter.

**Wrong identification.** Ubiquiti's fingerprint database is confident and
sometimes wrong, and a wrong fingerprint costs you twice: the client gets the
wrong name *and* the wrong artwork. A network-attached bidet reliably
identified as a smart toothbrush is not a rendering bug this tool can fix by
being cleverer; the upstream data says toothbrush.

None of this can be inferred safely. Guessing a plausible parent, or quietly
substituting a generic icon when the fingerprint looks improbable, would both
amount to inventing data. So the user states it.

## Format

TOML, because Python 3.11+ reads it from the standard library (`tomllib`), it
takes comments, and it's pleasant to hand-edit. No new dependency.

See [`examples/overrides.toml`](../examples/overrides.toml) for a working file.

### `[[device]]`

Declares a device the controller cannot see. A controller only reports what it
manages, so this covers an unmanaged switch with no management plane, a fully
managed third-party switch, and UniFi gear that was powered off when you ran the
fetch, all for the same reason. Everything else here
corrects a node that exists; this one creates it.

| Key | Required | Meaning |
| --- | --- | --- |
| `name` | yes | Label on the map, and what other blocks select it by |
| `kind` | no | `gateway`, `switch`, `ap`, `bridge`, `wired_client`, `wireless_client` or `unknown`. Defaults to `unknown`, which draws the generic shape. |
| `ip` | no | Address, shown under the name |
| `model` | no | Model string, shown under the address |
| `parent` | no | Selector for what it hangs off. Without one it floats. |
| `port` | no | Port on the parent, for the edge label. Needs a `parent`. |
| `icon` | no | Path to artwork you supply |
| `note` | no | Free text. Recorded but not drawn; see [Where `note` shows up](#where-note-shows-up). |

Declared devices are added before every other override, so a `[[link]]`, a
`[[hosted]]` or a `[[node]]` can reference one, and one declared device can hang
off another. Their ids are prefixed `asserted-`, which stops a device named
after a MAC from shadowing a real node.

They render with a **dotted outline**, the same reason asserted links render
dotted: a map must never present something you typed in as though a controller
had reported it. Offline devices use dashes and asserted ones use dots, so the
two stay distinguishable without relying on colour.

### `[[link]]`

| Key | Required | Meaning |
| --- | --- | --- |
| `from` | yes | Selector for one end |
| `to` | yes | Selector for the other end |
| `port` | no | Port number, for the edge label. May be unquoted. |
| `speed` | no | e.g. `"10G"`, for the edge label |
| `note` | no | Free text. Becomes the edge label when there is no `port` or `speed`; see [Where `note` shows up](#where-note-shows-up). |
| `wireless` | no | `true` renders the link dashed |

### `[[hosted]]`

| Key | Required | Meaning |
| --- | --- | --- |
| `guest` | yes | Selector for the nested node |
| `host` | yes | Selector for the node it runs on |
| `note` | no | e.g. `"VM"`, `"container"`. Becomes the edge label, replacing the default `hosted`. |

### `[[node]]`

Corrects how a single node is presented.

| Key | Required | Meaning |
| --- | --- | --- |
| `match` | yes | Selector for the node to correct |
| `name` | no* | Replacement label |
| `icon` | no* | Path to artwork you supply |
| `hide` | no* | `true` drops the node from the map entirely |
| `note` | no | Free text. Recorded but not drawn; see [Where `note` shows up](#where-note-shows-up). |

\* at least one of `name`, `icon` or `hide` is required; an entry that changes
nothing is rejected rather than silently ignored.

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
participating" are different things and the controller only reports the first, so
an access point whose radios you disabled on purpose is still `state: 1` and
`--show-offline no` cannot touch it. The other is discretion, for when the map is
going to somebody else and not everything on your network is their business.

**Only leaf nodes can be hidden.** Hiding a switch or an access point would orphan
everything behind it, and there is no good answer to what should happen to the
children (dropping them silently loses real devices, reattaching them to the
hidden node's parent invents a link that does not exist). So hiding a node that
has children is refused with an error naming the node and its children, rather
than guessed at.

#### Choosing artwork that looks right

Your image is fitted into the same box as every other icon, about 168 by 90
points, keeping its aspect ratio. It is never cropped or scaled up beyond that
box, so it cannot come out oversized. What varies is how much of the box it
fills, and that is what makes an image look wrong next to its neighbours.

For reference, Ubiquiti's own artwork ranges from 87 to 256 pixels on a side,
with aspect ratios from about 1:3 for a tall access point to 7:1 for a
rack-mount switch. Most devices are close to square.

Practical guidance:

- **Match the proportions of the thing you are replacing.** A roughly square
  image is the safest default. A very wide image fits the box on its width and
  ends up short; a very tall one fits on its height and ends up narrow. Either
  can look small beside a square neighbour even though the box is identical.
- **Trim empty margins yourself.** Fetched artwork is cropped to its visible
  content automatically; artwork you supply is used exactly as given. Padding is
  counted as part of the image, so a subject floating in a large transparent
  canvas renders noticeably smaller than everything around it. This is the most
  common reason a custom icon looks wrong.
- **Use PNG with transparency.** A white or opaque background becomes a bright
  slab on the dark theme. Transparent PNG is what the fetched artwork uses.
- **Around 256 pixels on the long edge is plenty.** Everything is scaled down to
  the box anyway, and the file is base64 embedded into every SVG you produce, so
  a large photograph inflates the output for no visible gain.
- **SVG works, with one caveat: it must open with an XML declaration**
  (`<?xml version="1.0"?>`). Graphviz refuses one without it, and its way of
  saying so is to report a file that plainly exists as missing and fail the
  whole render, so it is refused here instead with an error naming the file and
  the reason. Many drawing tools omit the declaration, so this is worth
  checking first if an SVG is rejected; adding the line by hand is enough.

  Size is taken from `width` and `height` if the `<svg>` tag has them, and from
  its `viewBox` otherwise, which is how most tools export. Only the ratio
  matters downstream. Dimensions are read from the `<svg>` element itself, so
  shapes inside it do not affect the size.
- **Other formats** Graphviz accepts include JPEG, GIF and WebP, but none of
  them handle transparency as reliably as PNG.

A photograph of the actual device, background removed and cropped tight, sits
alongside Ubiquiti's renders better than an icon or a logo does.

Relative `icon` paths resolve against **the overrides file's directory**, not the
working directory, so a config and its assets folder can be moved together and
still work regardless of where you run the tool from.

Artwork you supply is never fetched or cached; it is read from where you put it,
every time you render. It is embedded into the SVG the same way fetched artwork
is, so the output stays a single portable file and no local path appears in it.

### Selectors

`from`, `to`, `guest`, `host`, `parent` and `match` all accept a MAC, an IP, or
a hostname/device name as displayed on the map. Names rather than ids keep the file readable and mean a
device renamed in the controller only has to be corrected in one place.

## How selectors are matched

A selector is tried as a MAC address, then an IP address, then the label shown on
the map, in that order of specificity. A selector that matches nothing, or more
than one node, stops the run with an error naming what it found. A typo that
silently does nothing is worse than a failed render, because you would believe
the correction had been applied.

MAC addresses are the only selectors guaranteed to be unique. Names are easier to
read and usually fine.

## What it looks like

Anything you assert is drawn as a **dotted** line, and the legend gains a
"Stated in overrides" entry when a render contains one. Nothing you claim is ever
mistaken for something the controller reported.

## Checking a file without rendering

```bash
unifi-map overrides check
```

Applies the file against the cached snapshot and reports what it would do,
without drawing anything. Worth knowing about because overrides fail loudly by
design: a selector matching nothing, or matching two things, stops the run. That
is the right behaviour, and before this command the only way to discover it was
to render the whole map.

It reads the cache, so it contacts no controller and needs no credentials.

**It honours `--show-offline`, and defaults to `no` exactly as `render` does.**
That matters more than it sounds: a selector naming a device the controller
remembers but that is not currently connected resolves only when offline devices
are included. Checking with different settings from the render it is checking
for would let a file pass here and fail there, which is the one outcome this
command exists to prevent. If you render with `--show-offline yes`, check with
it too.

## Where `note` shows up

`note` behaves differently per block, which is worth stating because all four
accept it and only two draw it.

| Block | Effect |
| --- | --- |
| `[[link]]` | The edge label, but only when neither `port` nor `speed` is set. Those win. |
| `[[hosted]]` | The edge label, replacing the default text `hosted`. |
| `[[device]]`, `[[node]]` | None. Read and validated, never drawn: a comment for whoever edits the file next. |

A `#` comment does the same job for the two that do not draw it, and TOML keeps
those perfectly well. `note` is accepted there so that moving a block between
kinds does not fail on a key that was fine a moment earlier.

## Order of application

Links and nesting are applied first, then renames, artwork and hiding. That
ordering matters: if an override gives a node a child, an attempt to hide that
node in the same file is correctly refused.

## Design constraints

- **Overrides add rather than rewrite, and where they must rewrite, they say
  so.** `[[link]]` and `[[hosted]]` both detach a node from its current parent
  before attaching the one you stated, because a node with two parents is not a
  tree. Usually what is detached is the "uplink not reported" placeholder, which
  is no loss. Sometimes it is a real observation: reparenting a VM under its
  hypervisor is exactly that, and is the whole point of `[[hosted]]`. When the
  displaced link was something the controller actually reported, a warning says
  so, naming both ends, so a contradiction is never silent even though it is
  allowed. Under `--obfuscate` the warning still appears but reports only how
  many links were replaced: those labels are exactly what that flag exists to
  keep out of a terminal or a CI log.
- **Never invent topology.** This feature exists precisely so the tool doesn't
  have to guess. Its output must remain distinguishable from observed data.
- **A stale override should fail loudly.** Devices get replaced and renamed; an
  overrides file that no longer matches must complain, not degrade silently.
