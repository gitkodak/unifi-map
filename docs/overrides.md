# Manual topology overrides

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

### `[[link]]`

| Key | Required | Meaning |
| --- | --- | --- |
| `from` | yes | Selector for one end |
| `to` | yes | Selector for the other end |
| `port` | no | Port number, for the edge label. May be unquoted. |
| `speed` | no | e.g. `"10G"`, for the edge label |
| `note` | no | Free text |
| `wireless` | no | `true` renders the link dashed |

### `[[hosted]]`

| Key | Required | Meaning |
| --- | --- | --- |
| `guest` | yes | Selector for the nested node |
| `host` | yes | Selector for the node it runs on |
| `note` | no | e.g. `"VM"`, `"container"` |

### `[[node]]`

Corrects how a single node is presented.

| Key | Required | Meaning |
| --- | --- | --- |
| `match` | yes | Selector for the node to correct |
| `name` | no* | Replacement label |
| `icon` | no* | Path to artwork you supply |
| `hide` | no* | `true` drops the node from the map entirely |
| `note` | no | Free text |

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
note = "super-secret naughty server, not for the group chat"
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
- **SVG works, with a caveat.** Graphviz will load one only if it declares
  explicit `width` and `height` in pixels; an SVG with just a `viewBox` is
  silently rejected. PNG avoids the question.
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

`from`, `to`, `guest` and `host` accept a MAC, an IP, or a hostname/device name
as displayed on the map. Names rather than ids keep the file readable and mean a
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

## Order of application

Links and nesting are applied first, then renames, artwork and hiding. That
ordering matters: if an override gives a node a child, an attempt to hide that
node in the same file is correctly refused.

## Design constraints

- **Overrides add, they don't silently rewrite.** If an override contradicts what
  the controller reported, say so rather than quietly preferring one.
- **Never invent topology.** This feature exists precisely so the tool doesn't
  have to guess. Its output must remain distinguishable from observed data.
- **A stale override should fail loudly.** Devices get replaced and renamed; an
  overrides file that no longer matches must complain, not degrade silently.
