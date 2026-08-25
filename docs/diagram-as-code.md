# Drawing a network with no controller at all

[← Documentation index](../README.md#documentation)

**This is not a supported feature.** It is a side effect of how this
project built two other features. This page documents it because it
works today, and somebody will find it, not because this project aims
to build it. Read [What this is](#what-this-is) before you build
anything around it.

## What this is

`unifi-map` normally does one thing: it fetches a UniFi controller's own
description of your network, and draws it. The renderer, though, has no
idea where the `Topology` it receives came from. It is a pure function
from a graph of nodes and edges to a picture. By the time it runs, the
controller is long gone. Everything upstream of it just happens to be a
controller, most of the time.

[Manual overrides](overrides.md) exist to state facts a controller
cannot see: a switch it does not manage, a link it is not in the path
of, a VM that lives on a particular host. `[[device]]` and
`[[link]]`/`[[hosted]]`, between them, are already a complete language
for declaring nodes and edges by hand. Nothing stops you from declaring
*all* of them, and pointing `--cache-dir` at a snapshot that reports
nothing at all.

So yes, you can describe an entire network in a TOML file, get a real,
correctly laid out diagram, with your own artwork, and never speak to a
controller. This is not a trick or an exploit. It follows from two
things: the schema exists, and the renderer does not check where the
data came from.

## Why it will never be officially supported

Nobody designs for this path, and nobody tests it. This project's own
tests and its normal compatibility promise fully cover the overrides
schema and the renderers, but only for their actual purpose: they
describe what a real controller could not see about a real network.
That is a different purpose from using overrides as the *only* source
of truth, and nothing here watches for it. A future change could break
it: a new required field discovered from a real snapshot, a validation
rule tightened, or a change in how the tool handles an empty topology.
Such a change would not count as a breaking one, from this project's
point of view, and `CHANGELOG.md` would not mention it.

If you need a network-diagram-as-code tool as your actual job, use one built
for that: [D2](https://d2lang.com/), [Structurizr](https://structurizr.com/),
plain [Graphviz](https://graphviz.org/), or similar. What a UniFi
console shows decides this project's shape, its `Kind` vocabulary, and
its artwork pipeline, all of it. That stays true, regardless of what
this page documents.

## How to do it

### 1. A snapshot that reports nothing

`unifi-map render` reads `--cache-dir` and refuses to run without *something*
there. The simplest legitimate snapshot is three files reporting empty lists,
written by hand: no controller, no Python, nothing generated.

```bash
mkdir -p cache
echo '{"data": []}' > cache/device.json
echo '{"data": []}' > cache/client_active.json
echo '{"data": []}' > cache/networkconf.json
```

This is the same flat layout `Snapshot.read()` already falls back to for a
cache written before generations existed, so nothing about it is a hack on
that front. Every node and edge you see afterward comes entirely from your
overrides file.

### 2. Declare the network

```toml
# overrides.toml
[[device]]
name = "Core Switch"
kind = "switch"

[[device]]
name = "Office Laptop"
kind = "wired_client"
parent = "Core Switch"
port = 3

[[device]]
name = "Guest Phone"
kind = "wireless_client"
parent = "Core Switch"
```

`kind` accepts `gateway`, `switch`, `ap`, `bridge`, `wired_client`,
`wireless_client` or `unknown`. See [the full table](overrides.md#device).
A device with no `parent` floats at the top, which is what you want for
whatever is playing the root of your tree.

### 3. Render it

```bash
unifi-map render --cache-dir cache --overrides overrides.toml --icons builtin
```

**Use `--icons builtin`, not the default `--icons unifi`.** The `unifi` icon
set matches hardware by `sysid` and clients by fingerprint `dev_id`, neither
of which exists on a device you typed in yourself, so it would spend time
finding nothing. `builtin` draws the same nine role-shaped icons this project
draws for anything Ubiquiti's catalogue does not recognise, which is a
perfectly good generic node shape for this.

### 4. Your own artwork

`[[device]].icon` (or `[[node]].icon` for something already on the map)
points at any PNG, JPEG, GIF or SVG, resolved relative to the overrides file
itself:

```toml
[[device]]
name = "Core Switch"
kind = "switch"
icon = "icons/core-switch.png"
```

The tool fetches nothing, and caches nothing against a lookup key. It is
your file, read and placed, exactly as given.

## What does not work

- **No Internet/cloud node.** `[[device]]` cannot declare
  `Kind.INTERNET`, deliberately: `build_topology()` only ever
  synthesises that node from a real device's real uplink. Fake a `kind =
  "unknown"` node with your own cloud icon if you want one. There is no
  way to get the real cloud renderer without a controller behind it.
- **The vocabulary is UniFi's, not a generic one.** No router/firewall/server/
  cloud-provider kinds, no rack or location grouping (not built for real
  networks either, see `TODO.md`), one icon per node rather than a shape
  library.
- **The labels still talk about UniFi devices**, because nothing told
  them not to. The title block on a fabricated map still says "N UniFi
  devices · M clients". `--report` still lists sections named after
  controller endpoints (`stat/device`, `stat/sta`) that, in this case,
  answered nothing, because nothing asked them anything. Both are
  honest, in the sense that they describe exactly what the pipeline
  actually did. Neither reads like something built for this use case,
  because neither was.
- **`overrides check` and `overrides generate` still work**, since they
  build on the same `Topology`, but their output assumes you are
  reconciling overrides against a real fetch. Read past the framing.
- **Every link is dotted, and there is no override for that.** Dotted is
  what an asserted edge renders as, deliberately and permanently. It is
  the channel this project uses to guarantee that something a human
  typed in never looks like something a controller reported. That
  guarantee has to hold on a real map, which means the rendering code
  cannot tell a real map from a fabricated one, and cannot make an
  exception here. This project considered a different line style and
  declined it for exactly that reason, not because it would be hard to
  build. It would not be hard. On a from-scratch network, every link
  genuinely is asserted anyway, so the line is still accurate, just for
  a different reason than usual. If you want a different line style
  regardless, this tool is the wrong place to ask for it. The output is
  plain DOT or SVG text, so `sed 's/style=dotted/style=solid/'
  network-map.dot` is the actual answer, outside anything this project
  promises to maintain.

## Example

Six `[[device]]` blocks, six custom icons, `--icons builtin`, `--layout
tree`, nothing else. The PoE Bidet and the Smart Toothbrush are the same
pair `docs/overrides.md` uses to explain why fingerprint matching can be
confidently wrong.

![A small invented network: Trash Router, Toaster Switch, Sentient Toaster, PoE Bidet, Grandma's iPad (2011) and Smart Toothbrush, drawn entirely from overrides with custom placeholder artwork and no controller involved](images/example-diagram-as-code.png)

Every icon there comes from a Pillow script that draws a coloured blob
with a label on it. That is deliberate: nothing about this page should
read as an invitation to make something that looks like a real product
diagram, out of invented data. If you use this, make it obviously not
that.

## Summary

This works because nothing stops it, not because it is meant to. Treat it
as a curiosity you are free to use, not a roadmap item, and do not file an
issue if it eventually breaks.
