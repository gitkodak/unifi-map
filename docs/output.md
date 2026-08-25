# Output formats and options

[← Documentation index](../README.md#documentation)

This page covers every format `-f` accepts, and the flags that change how
a run behaves, rather than what it draws.

| Format | Why |
| --- | --- |
| `svg` | Vector. Zoom to any size, labels stay crisp. Artwork is embedded, so it's one portable file. |
| `pdf` | Vector, for printing. |
| `png` | Raster, when something insists on it. |
| `drawio` | Real editable shapes, pre-positioned with Graphviz's layout. Confirmed working in [draw.io](https://app.diagrams.net), which [re-themes it on load](#drawio-decides-its-own-light-and-dark). Lucid documents `.drawio` import but does not work. See [below](#lucid-does-not-import-these-files). |
| `html` | A single file: pan, zoom, search, trace a client's path to the gateway, collapse a switch's clients. [More below](#html-for-exploring-a-busy-map). |
| `dot` | Graphviz source, to tweak styling by hand. |
| `mermaid` | Text that GitHub, GitLab and most wikis draw in place. No artwork. Shape only. [More below](#mermaid-for-documentation). |
| `json` | The normalised topology, for programs rather than people. [More below](#json-for-programs). |

`svg`, `pdf`, and `png` need no more explanation than that row: Graphviz
does the drawing, so those three require it installed. This project
writes `dot`, `mermaid`, and `json` directly, and they work without
Graphviz. That is worth knowing if you only want the source or the data.
`drawio` sits in between: this project writes the file, but Graphviz
computes the positions in it. `html` sits in the same position as
`drawio`: it embeds a Graphviz-rendered SVG, so it needs Graphviz too.

**Your own SVG artwork does not reach `png` or `pdf` on its own.**
Graphviz loads SVG images only for its own `svg` driver. The
cairo-backed formats drop them with a warning and continue. Two ways fix
this, and neither is better: run `pip install 'unifi-map[svg]'`, which
rasterises SVG overrides on the way in, or convert the file to PNG
yourself, which adds no dependency. This applies only to artwork *you*
supply. Everything fetched from Ubiquiti is already PNG. See
[overrides](overrides.md#node).

The two text formats below need more explanation.

## draw.io decides its own light and dark

`--theme` reaches every other format intact, because this project
produces the final pixels. A `.drawio` file is different. draw.io themes
it on load, and that application gets the last word.

**draw.io inverts a diagram to contrast with its own appearance
setting.** Its dark mode assumes diagrams are authored light, and flips
them so they stay readable. A diagram already authored dark gets flipped
a second time, and comes back out light. This project observed this
with one unchanged `--theme dark` file:

| draw.io appearance | how the dark file renders |
| --- | --- |
| Dark, or Automatic on a dark desktop | **Light** |
| Light | **Dark** |

A file authored **light**, by contrast, is right in both:

| draw.io appearance | light file | dark file |
| --- | --- | --- |
| Light | light canvas, dark text | dark canvas |
| Dark, or Automatic on a dark desktop | dark canvas, light text | light canvas |

So `--theme light` is not a workaround here, it is the answer. Read the left
column: a light-authored file gives you a light diagram in light mode and a
dark diagram in dark mode, which is what you wanted from `--theme` in the first
place. A dark-authored one is wrong in both.

The inversion does not corrupt anything. It is holistic: cells, text,
and artwork flip together, and the file stays internally coherent. It
simply reads as the theme you did not ask for.

There are two ways to get what you want:

- **Render `.drawio` with `--theme light`**, and let draw.io theme it.
  This is right for every reader, whatever their appearance setting.
  That matters most when the file goes to somebody whose setup you do
  not know. `unifi-map` warns if you ask for `--theme dark` and `drawio`
  together.
- **Set the appearance in draw.io explicitly**, rather than leave it on
  Automatic. This is enough when the file is for you, and you know how
  your own editor is configured. It does not help anybody you send it
  to, though.

If you want a dark diagram whose colours are fixed, and that a viewer
cannot re-theme, use `svg` or `pdf` instead. This project controls those
completely.

**This tool cannot fix the re-theming itself.** It happens inside
draw.io, after this project writes the file. There is no attribute this
project can set that is known to opt out of it.

This project could author `.drawio` light, whatever `--theme` says. It
does not do that yet, and the reason is worth knowing. The icons this
project draws itself are **baked** in a colour the theme sets, and every
format in a run shares one set of images. If the draw.io file rendered
light while the run is dark, that would put light-baked icons on a white
card. A proper fix means resolving artwork twice, a real change, not a
flag flip.

## Lucid does not import these files

Lucid documents `.drawio` import. This project tried it, against a
52-client map and a 12-node infrastructure map. It imports **exactly one
cell and stops**, a different cell each time.

The embedded artwork is not the cause: a copy with every image stripped,
25 cells and 11 edges in 9.5 KiB, behaves identically. The storage form
is not the cause either. draw.io can hold its payload
deflate-compressed, and this project round-trip verified a compressed
variant, which imported the same way.

draw.io is the reference implementation of this format, and the file
works there. So this project will not reshape anything here to suit a
second tool's parser. If you need the diagram in Lucid, open it in
draw.io and export from there, or import the `svg` or `pdf` output
instead, which Lucid ingests without complaint.

## HTML, for exploring a busy map

A static picture is the wrong shape for a network with real client counts: a
switch with thirty clients is unreadable in `svg`, `pdf` or `drawio` alike,
because nothing about those formats can hide the leaves you don't currently
care about. `-f html` is one self-contained file (open it, nothing else to
install) with four things a still image can't do:

- **Scroll or drag to pan, pinch or Ctrl+scroll to zoom.** A trackpad's
  two-finger swipe and a mouse wheel both fire the same kind of event, so
  something has to decide which one means what. This follows the
  convention every other pan/zoom canvas settled on (Figma, Miro, Google
  Maps): Ctrl means zoom. A browser also sets that on its own for a
  trackpad pinch, so an actual Ctrl+scroll works the same way for free.
  Anything else pans, because that is what a swipe is for.
- **Search** dims every node whose label, address, or detail line does
  not match, so a busy map narrows to what you typed.
- **Click a client** to trace its path back to the gateway. Everything
  off that path dims too.
- **Click a switch or AP that has clients** to collapse just those
  clients. Click it again to bring them back. This is the actual point
  of the format: the console has no way to hide the noise and show the
  skeleton.

**Pan and zoom is a vendored copy of [Panzoom](https://github.com/timmywil/panzoom)**,
not hand-rolled and not fetched from a CDN. It is MIT-licensed, with
zero dependencies of its own, and this project checked it into the repo
as a single file. This is a different kind of "vendoring" than the rule
against committing Ubiquiti's artwork. That rule is about somebody
else's copyrighted product images, not about third-party code in
general.

Everything is computed once, in Python, from the same `Topology` and the same
rendered SVG `-f svg` would write. This is not a second renderer. It embeds
the first one's output. There is nothing to keep in sync by hand.

## JSON, for programs

```bash
unifi-map render -f json
```

This writes the normalised topology, rather than the controller's
payloads: nodes, edges, networks, and counts. The model is the stable
thing here, and UniFi's schemas are not. So build an inventory check or
a Home Assistant integration against this instead.

It is also the least dangerous way to hand the data to another program.
A cached snapshot is a full controller dump. This is the graph instead.
It honours `--obfuscate`, overrides, and `--per-network` exactly as the
diagram does, so whatever cleaning this project applied to the picture
also applies here.

Here is every top-level key, from the shipped demo. `networks`, `nodes`,
and `edges` are cut down to one entry each. `schema`, `generator`,
`title`, and `counts` are complete:

```json
{
  "schema": 1,
  "generator": "unifi-map 0.13.0",
  "title": "Network map",
  "counts": {
    "gateway": 1, "switch": 4, "ap": 3, "internet": 1,
    "wired_client": 8, "wireless_client": 11, "unknown": 1
  },
  "networks": [ { "id": "net-lan", "name": "lan", "vlan": 1 } ],
  "nodes": [
    { "id": "02:00:00:00:01:01", "label": "gateway", "kind": "gateway", "provenance": "device",
      "ip": "10.0.0.1", "model": "UDMPROMAX", "detail": "UDMPROMAX",
      "sysid": 59954 }
  ],
  "edges": [ { "child": "02:00:00:00:01:01", "parent": "internet", "provenance": "wan", "label": "WAN" } ]
}
```

`counts` covers the whole map, not the abridged arrays above, so it does
not add up to the single node shown here. The demo has four networks,
not one.

This project names edges `child` and `parent`, rather than `src` and
`dst`, because a reader should not have to guess which way round they
point. It omits facts it does not know, rather than setting them to
`null`, and flags appear only when true.

**The schema may gain fields and will not lose them**, which is what `schema`
tracks. Each node and edge includes `provenance`: the source that placed it,
such as `device`, `client_uplink`, `topology_graph`, `unplaced`, or `override`.
It is an additive schema-1 field, so an existing reader can ignore it safely.

## Mermaid, for documentation

```bash
unifi-map render -f mermaid --no-clients
```

This writes a `.mmd` file that GitHub, GitLab, and most wikis draw in
place. It is the one destination the other formats cannot reach. A
README cannot embed an SVG that adapts to the reader's colour scheme,
and a draw.io file is not a picture until somebody opens it.

**The direction follows `--layout`**, as everywhere else: `unifi` (the default)
draws left to right, `tree` draws top to bottom. The file also opens with a
`title` front matter block, which Mermaid renders as a caption.

Below is the shipped demo, infrastructure only. Whatever shows you this
page draws it directly. It is the output of

```bash
unifi-map render -f mermaid --no-clients --layout tree
```

with the front matter removed, because a caption on top of a heading reads as a
duplicate of it. Everything else is verbatim:

```mermaid
flowchart TB
    n02_00_00_00_01_01[/"gateway · 10.0.0.1"\]
    n02_00_00_00_01_02[["Core Switch · 10.0.0.2"]]
    n02_00_00_00_01_03[["Rack Switch · 10.0.0.3"]]
    n02_00_00_00_01_04[["Desk Switch · 10.0.0.4"]]
    n02_00_00_00_02_01{{"Living Room · 10.0.0.11"}}
    n02_00_00_00_02_02{{"Bedroom · 10.0.0.12"}}
    n02_00_00_00_02_04{{"Office · 10.0.0.14"}}
    n02_00_00_00_03_01[["Rack UPS · 10.0.0.20"]]
    ninternet(["Example ISP · 203.0.113.10"])
    ninternet -->|WAN| n02_00_00_00_01_01
    n02_00_00_00_01_01 -->|port 25| n02_00_00_00_01_02
    n02_00_00_00_01_02 -->|port 24| n02_00_00_00_01_03
    n02_00_00_00_01_02 -->|port 12| n02_00_00_00_01_04
    n02_00_00_00_01_02 -->|port 5| n02_00_00_00_02_01
    n02_00_00_00_01_02 -->|port 6| n02_00_00_00_02_02
    n02_00_00_00_01_03 -->|port 8| n02_00_00_00_02_04
    n02_00_00_00_01_03 -->|port 2| n02_00_00_00_03_01
```

**It loses all artwork**, necessarily. Mermaid draws boxes and text, so
the product renders that make the SVG interesting have nowhere to go.
What survives is the shape, which is what documentation usually wants.

Shape carries node kind, not colour, the same rule the other backends
follow: rounded for the Internet, `[[double]]` for a switch, hexagonal
for an access point. Links keep their meaning too: dashed for wireless,
dotted for anything asserted in an overrides file. Nodes the controller
lists as offline carry an `OFFLINE` label marker. Nodes stated in
overrides carry an `ASSERTED` marker. Mermaid has no separate
node-border style that can coexist with its kind shapes, so the markers
keep those facts visible in plain text.

`--no-clients` does real work in that example. The full demo has 29
nodes, a wall of boxes on a page. The infrastructure alone is nine, and
it reads at a glance.

## Putting a map on a page: `--transparent`

```bash
unifi-map render --transparent --theme dark
```

This draws no canvas, so the diagram sits on whatever is behind it. It
applies to SVG, PDF, PNG, and draw.io. Without it, every theme paints a
solid background. This means an SVG dropped into a page is an opaque
rectangle, whichever theme you picked.

**The theme still matters, more than it looks.** With the default
`--icons unifi`, device labels have no card behind them: the artwork is
the node, and the text sits on the canvas. If you remove the canvas,
every label, edge label, and title lands directly on the destination
page. So a light-theme map is near-invisible on a dark page, and a
dark-theme map is near-invisible on a light one. Match the theme to the
destination.

This applies to `--icons builtin` too. It used to be the exception,
because the fallback shapes carried their own fill and kept a background
of their own. The icons that replaced them are transparent PNGs. So
nothing fills in behind a node, and every label sits directly on the
destination page.

## Progress, and turning it off

Three steps can each take long enough that a silent terminal looks like
a hang: reading an archive, fetching artwork on a cold cache, and
running Graphviz on a large network. So a spinner names the step
underway.

**It disables itself whenever output is not a terminal.** A pipe, a
redirect to a file, or a run under cron or CI all produce clean text,
with no escape sequences, and need no flag. `--no-progress` covers the
one case that check cannot see: an interactive terminal whose output
something else reads.

```bash
unifi-map --no-progress all          # never spin
unifi-map all > map.log 2>&1         # already silent, no flag needed
```

Log output goes to stderr, with or without the spinner, so neither
choice changes what a script sees. The rendering commands write nothing
to stdout at all. Their output is the files they produce. The one
exception is `unifi-map shape`, whose report *is* its output. It goes to
stdout, so you can pipe or redirect it.
