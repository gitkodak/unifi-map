# Output formats and options

[← Documentation index](../README.md#documentation)

Every format `-f` accepts, and the flags that change how a run behaves rather
than what it draws.

| Format | Why |
| --- | --- |
| `svg` | Vector. Zoom to any size, labels stay crisp. Artwork is embedded, so it's one portable file. |
| `pdf` | Vector, for printing. |
| `png` | Raster, when something insists on it. |
| `drawio` | Real editable shapes, pre-positioned with Graphviz's layout. Confirmed working in [draw.io](https://app.diagrams.net), which [re-themes it on load](#drawio-decides-its-own-light-and-dark). Lucid documents `.drawio` import but does not work; see [below](#lucid-does-not-import-these-files). |
| `html` | A single file: pan, zoom, search, trace a client's path to the gateway, collapse a switch's clients. [More below](#html-for-exploring-a-busy-map). |
| `dot` | Graphviz source, to tweak styling by hand. |
| `mermaid` | Text that GitHub, GitLab and most wikis draw in place. No artwork; shape only. [More below](#mermaid-for-documentation). |
| `json` | The normalised topology, for programs rather than people. [More below](#json-for-programs). |

`svg`, `pdf` and `png` need nothing said about them beyond that row: Graphviz
does the drawing, so those three are the formats that require it installed.
`dot`, `mermaid` and `json` are written directly and work without it, which is
worth knowing if you only want the source or the data. `drawio` is in between:
the file is written here, but Graphviz computed the positions in it. `html` is
in the same position as `drawio`: it embeds a Graphviz-rendered SVG, so it
needs Graphviz too.

**Your own SVG artwork does not reach `png` or `pdf` on its own.** Graphviz
loads SVG images only for its own `svg` driver; the cairo-backed formats drop
them with a warning and carry on. Two ways to fix it, and neither is better:
`pip install 'unifi-map[svg]'`, which rasterises SVG overrides on the way in,
or convert the file to PNG yourself and add no dependency. This applies only to
artwork *you* supply: everything fetched from Ubiquiti is already PNG. See
[overrides](overrides.md#node).

The two text formats below are the ones that need explaining.

## draw.io decides its own light and dark

`--theme` reaches every other format intact, because we produce the final
pixels. A `.drawio` file is different: it is handed to an application that
themes it on load, and that application gets the last word.

**draw.io inverts a diagram to contrast with its own appearance setting.** Its
dark mode assumes diagrams are authored light and flips them so they stay
readable. A diagram already authored dark is flipped a second time and comes
back out light. Observed with one unchanged `--theme dark` file:

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

Nothing is corrupted when the inversion happens. It is holistic, so cells, text
and artwork flip together and the file stays internally coherent. It simply
reads as the theme you did not ask for.

Two ways to get what you want:

- **Render `.drawio` with `--theme light`** and let draw.io theme it. Right for
  every reader, whatever their appearance setting, which matters most when the
  file is going to somebody whose setup you do not know. `unifi-map` warns if
  you ask for `--theme dark` and `drawio` together.
- **Set the appearance in draw.io explicitly**, rather than leaving it on
  Automatic. Enough when the file is for you and you know how your own editor
  is configured, though it does not help anybody you send it to.

If you want a dark diagram whose colours are fixed and cannot be re-themed by a
viewer, use `svg` or `pdf` instead. Those we control completely.

**The re-theming itself is not something this tool can fix.** It happens inside
draw.io, after the file is written, and there is no attribute we can set that is
known to opt out of it.

What we could do is author `.drawio` light whatever `--theme` says. That is not
done yet, and the reason is worth knowing: the icons this project draws itself
are **baked** in a colour taken from the theme, and one set of images is shared
by every format in a run. Rendering the draw.io file light while the run is dark
would put light-baked icons on a white card. Doing it properly means resolving
artwork twice, which is a real change rather than a flag flip.

## Lucid does not import these files

Lucid documents `.drawio` import. It was tried, against a 52-client map and a
12-node infrastructure map, and it imports **exactly one cell and stops**, a
different cell each time.

It is not the embedded artwork: a copy with every image stripped, 25 cells and
11 edges in 9.5 KiB, behaves identically. It is not the storage form either.
draw.io can hold its payload deflate-compressed, and a compressed variant was
round-trip verified and imported the same way.

draw.io is the reference implementation of this format and the file works there,
so nothing here is going to be reshaped to suit a second tool's parser. If you
need the diagram in Lucid, open it in draw.io and export from there, or import
the `svg` or `pdf` output, which Lucid ingests without complaint.

## HTML, for exploring a busy map

A static picture is the wrong shape for a network with real client counts: a
switch with thirty clients is unreadable in `svg`, `pdf` or `drawio` alike,
because nothing about those formats can hide the leaves you don't currently
care about. `-f html` is one self-contained file — open it, nothing else to
install — with four things a still image can't do:

- **Scroll or drag to pan, pinch or Ctrl+scroll to zoom.** A trackpad's
  two-finger swipe and a mouse wheel both fire the same kind of event, so
  something has to decide which one means what. This follows the convention
  every other pan/zoom canvas settled on (Figma, Miro, Google Maps): Ctrl
  means zoom, which a browser also sets on its own for a trackpad pinch, so
  an actual Ctrl+scroll works the same way for free. Anything else pans,
  because that is what a swipe is for.
- **Search** dims every node whose label, address or detail line doesn't
  match, so a busy map narrows to what you typed.
- **Click a client** to trace its path back to the gateway: everything off
  that path dims too.
- **Click a switch or AP** that has clients to collapse just those clients.
  Clicking it again brings them back. This is the actual point of the format:
  the console has no equivalent of hiding the noise to see the skeleton.

**Pan and zoom is a vendored copy of [Panzoom](https://github.com/timmywil/panzoom)**,
not hand-rolled and not fetched from a CDN. It's MIT-licensed with zero
dependencies of its own, checked into the repo as a single file. This is a
different kind of "vendoring" than the rule against committing Ubiquiti's
artwork: that rule is about somebody else's copyrighted product images, not
about third-party code existing at all.

Everything is computed once, in Python, from the same `Topology` and the same
rendered SVG `-f svg` would write — this is not a second renderer, it embeds
the first one's output. There is nothing to keep in sync by hand.

## JSON, for programs

```bash
unifi-map render -f json
```

The normalised topology rather than the controller's payloads: nodes, edges,
networks and counts. The model is the stable thing here and UniFi's schemas are
not, so this is what to build an inventory check or a Home Assistant integration
against.

It is also the least dangerous way to hand the data to another program. A cached
snapshot is a full controller dump; this is the graph, and it honours
`--obfuscate`, overrides and `--per-network` exactly as the diagram does, so
whatever cleaning was applied to the picture applies here.

Every top-level key, from the shipped demo. `networks`, `nodes` and `edges` are
abridged to one entry each; `schema`, `generator`, `title` and `counts` are
complete:

```json
{
  "schema": 1,
  "generator": "unifi-map 0.11.0",
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
  "edges": [ { "child": "02:00:00:00:01:01", "parent": "internet", "label": "WAN", "provenance": "wan" } ]
}
```

`counts` covers the whole map rather than the abridged arrays above, so it does
not add up to the single node shown. The demo has four networks, not one.

Edges are named `child` and `parent` rather than `src` and `dst`, because a
reader should not have to guess which way round they point. Facts that are not
known are omitted rather than set to `null`, and flags appear only when true.

**The schema may gain fields and will not lose them**, which is what `schema`
tracks. Each node and edge includes `provenance`: the source that placed it,
such as `device`, `client_uplink`, `topology_graph`, `unplaced`, or `override`.
It is an additive schema-1 field, so an existing reader can ignore it safely.

## Mermaid, for documentation

```bash
unifi-map render -f mermaid --no-clients
```

Writes a `.mmd` that GitHub, GitLab and most wikis draw in place. It is the one
destination the other formats cannot reach: a README cannot embed an SVG that
adapts to the reader's colour scheme, and a draw.io file is not a picture until
somebody opens it.

**The direction follows `--layout`**, as everywhere else: `unifi` (the default)
draws left to right, `tree` draws top to bottom. The file also opens with a
`title` front matter block, which Mermaid renders as a caption.

Below is the shipped demo, infrastructure only, drawn by whatever is showing you
this page. It is the output of

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

**It loses all artwork**, necessarily: Mermaid draws boxes and text, so the
product renders that make the SVG worth looking at have nowhere to go. What
survives is the shape, which is what documentation usually wants.

Node kind is carried by shape rather than colour, the same rule the other
backends follow: rounded for the Internet, `[[double]]` for a switch, hexagonal
for an access point. Links keep their meaning too, dashed for wireless and
dotted for anything asserted in an overrides file. Nodes the controller lists
as offline carry an `OFFLINE` label marker; nodes stated in overrides carry an
`ASSERTED` marker. Mermaid has no separate node-border style that can coexist
with its kind shapes, so the markers keep those facts visible in plain text.

`--no-clients` is doing real work in that example. The full demo is 29 nodes,
which is a wall of boxes on a page; the infrastructure is nine and reads at a
glance.

## Putting a map on a page: `--transparent`

```bash
unifi-map render --transparent --theme dark
```

Draws no canvas, so the diagram sits on whatever is behind it. Applies to SVG,
PDF, PNG and draw.io. Without it, every theme paints a solid background, which
means an SVG dropped into a page is an opaque rectangle whichever theme you
picked.

**The theme still matters, and more than it looks.** With the default
`--icons unifi`, device labels have no card behind them: the artwork is the
node, and the text sits on the canvas. Remove the canvas and every label, edge
label and title lands directly on the destination page, so a light-theme map is
near-invisible on a dark one and vice versa. Match the theme to where the image
is going.

This applies to `--icons builtin` too. It used to be the exception, because the
fallback shapes carried their own fill and kept a background of their own; the
icons that replaced them are transparent PNGs, so nothing behind a node is
filled in and every label sits directly on the destination page.

## Progress, and turning it off

Reading an archive, fetching artwork on a cold cache and running Graphviz on a
large network can each take long enough that a silent terminal looks like a
hang, so a spinner says which step is running.

**It disables itself whenever output is not a terminal.** Piping, redirecting to
a file or running under cron or CI all produce clean text with no escape
sequences, without passing anything. `--no-progress` covers the case that check
cannot see: an interactive terminal whose output something else is reading.

```bash
unifi-map --no-progress all          # never spin
unifi-map all > map.log 2>&1         # already silent, no flag needed
```

Log output goes to stderr with or without the spinner, so neither choice changes
what a script sees. The rendering commands write nothing to stdout at all; their
output is the files they produce. The one exception is `unifi-map shape`, whose
report *is* its output and goes to stdout so it can be piped or redirected.
