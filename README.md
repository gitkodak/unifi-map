# unifi-map

[![CI](https://github.com/gitkodak/unifi-map/actions/workflows/ci.yml/badge.svg)](https://github.com/gitkodak/unifi-map/actions/workflows/ci.yml)
[![SonarQube Cloud Quality Gate](https://sonarcloud.io/api/project_badges/measure?project=gitkodak_unifi-map&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=gitkodak_unifi-map)
[![SonarQube Cloud Coverage](https://sonarcloud.io/api/project_badges/measure?project=gitkodak_unifi-map&metric=coverage)](https://sonarcloud.io/summary/new_code?id=gitkodak_unifi-map)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/gitkodak/unifi-map/badge)](https://securityscorecards.dev/viewer/?uri=github.com/gitkodak/unifi-map)
[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/14071/badge)](https://www.bestpractices.dev/projects/14071)

Export a UniFi network topology as **zoomable vector diagrams** and **editable
draw.io files**. The tool uses real Ubiquiti product artwork.

The UniFi Network web UI has no topology export. Screenshots do not help
either. The topology view is a fixed-size viewport that wraps a pan/zoom
canvas. A full-page capture extension can return only the visible region. If
you zoom out far enough to fit the whole network, the labels become
unreadable.

This tool does not scrape pixels. The UI draws the map from JSON endpoints on
the console. This tool reads the same endpoints and renders the map directly.

![A short showcase of unifi-map output: exported topology, readable tree layout, asserted overrides, and obfuscated sharing output](docs/images/unifi-map-promo.gif)

**This is a UniFi Network tool.** It reads one Protect endpoint, to tell a
camera from an Access reader when the hardware names collide, and it
touches nothing else in the Protect suite. Access readers and Talk phones
already appear as ordinary clients. A UNAS should appear as ordinary UniFi
hardware, but this project's tests do not cover one, so that part is
inference, not observation.
[What that costs, and what would fix it](docs/verification.md#which-unifi-applications-this-has-seen).

![Example output: the demo network in the default UniFi layout, dark theme](docs/images/example-unifi-dark.png)

*This is the default layout, `--layout unifi`. It approximates the
console's own view: left to right from the Internet, orthogonal links, no
title or legend, because the UniFi UI has neither.

The UniFi hardware carries real artwork, because the dataset uses real
hardware IDs. Eight of the **clients** resolve to real product renders. The
rest are invented and have no fingerprint, so they use the console's own
generic glyphs, the same fallback the UniFi UI uses. Those glyphs need the
icon font, which only a controller serves. A clone of this repository draws
its own client icons instead until it has one. See [the generic client
glyph](docs/artwork.md#the-generic-client-glyph-and-why-it-is-awkward) for
the three routes to it.

These screenshots use `--theme dark`, because dark reads better on this
page. **The tool defaults to `--theme light`.** A [light version of this
map](docs/images/example-unifi-light.png) is committed alongside every
other one, so you can see what an unmodified run produces.*

![The same network in the readable tree layout](docs/images/example-tree-dark.png)

*This is the same data with `--layout tree`. It runs top to bottom and
staggers leaf nodes to keep the aspect ratio reasonable, with port numbers
on the links, plus a title block and a legend. On a busy network, this is
usually the layout to hand to somebody else.
([Light version](docs/images/example-tree-light.png).) See
[Install](#install) before you point this at your own controller.*

## Features

- **Maps every active client, not just infrastructure.** This includes
  gateways, switches, APs, and everything connected to them, including
  clients behind a non-UniFi device.
- **Real Ubiquiti product artwork** covers your hardware and your clients,
  plus your ISP's brand mark on the Internet node. The tool fetches artwork
  at runtime and caches it. [It never ships artwork in this
  repo](docs/artwork.md#artwork-licensing-and-attribution). If it cannot
  identify a device, it uses [an icon this project
  draws](docs/artwork.md#the-icons-we-draw-ourselves) instead of a bare
  shape. `--icons builtin` needs no network access at all.
- **Vector output that stays readable.** [SVG and PDF](#output) zoom to any
  size and keep crisp labels. The tool also writes PNG, for when something
  needs it, and Graphviz `.dot`, for hand editing.
- **Editable draw.io files.** Graphviz positions the real shapes in advance,
  so you can rearrange the map instead of only looking at it.
- **Two layouts.** [`unifi`](docs/usage.md#how-close-is---layout-unifi)
  approximates the console's own view. `tree` runs top to bottom and stays
  readable on a busy network. The tool also offers light and dark themes,
  with a colourblind-safe palette.
- **Works with no credentials at all.** It reads a [support
  file](docs/support-files.md#mapping-from-a-support-file) instead of a
  controller. Use this if you would rather not give a script an API key, or
  if you are mapping a network you cannot reach.
- **Safe to publish.** [`--obfuscate`](docs/sharing.md#sharing-a-map---obfuscate)
  replaces hostnames, addresses, MACs, SSIDs, VLAN names, and your ISP. It
  keeps the shape of the network intact.
- **One diagram per client network, optionally.** Each diagram keeps the
  full gateway and switch skeleton, so each one reads as a slice of one map.
- **Hides decommissioned hardware by default.** The console itself offers no
  way to do this.
- **[Manual overrides](docs/overrides.md).** The console has no equivalent
  of this. You can declare a device the controller cannot see, such as a
  switch it does not manage. You can assert a link the controller does not
  report. You can say that a VM lives on a particular host. You can correct
  a wrong fingerprint, or hide something. The diagram draws all of this as a
  claim, not as an observation, so a reader can tell the difference. `make
  demo-overrides` renders the shipped example.

  (As a side effect, and only as one, the same schema can describe a
  network with no controller at all. See
  [Diagram-as-code](docs/diagram-as-code.md).)
- **Read-only, always.** `session.get` is the only HTTP verb in the source.
- **Scriptable by default.** The [progress
  spinner](docs/output.md#progress-and-turning-it-off) turns itself off
  whenever output is not a terminal. A pipe or a redirect gets clean text,
  with no escape sequences and no need to remember `--no-progress`.

Here is the quickest look, with no credentials and no controller needed.
From a clone, with Graphviz and Python 3.11+ installed
([Install](#install) covers both):

```bash
make demo
```

This command builds its own virtual environment. It renders the shipped
dataset into `examples/demo/`, next to the input data. Git ignores the
rendered files by extension. It does not ignore the input.

**To run this against your own network, start at [Install](#install).** You
need the tool on your `PATH`. You need a credential file with your host and
API key. At this point, you have neither.

Two things carry risk. Read about both before you continue. An API key is
[broader than this tool needs](docs/credentials.md#unifi_api_key). A support
file is [highly sensitive](docs/support-files.md#mapping-from-a-support-file).

## How this was built

An AI assistant (Claude) wrote nearly all of the code here. It worked from
my direction, review, and testing against my own network. I decided what it
should do and what "good" looked like. It wrote nearly every line.

It works well for me. It has automated tests, and the design decisions have
reasons behind them. Other AI systems review it regularly. These reviews
cover security, documentation, code, and architecture. The project fixes or
records their findings. No human audits it line by line.

It only ever reads from your controller. There is no code path here that
changes anything on it. It requires admin credentials. See `client.py`,
which is short.

[`AI_DISCLOSURE.md`](AI_DISCLOSURE.md) covers what this project verified,
what it did not verify, and how the AI failed here.
[`HUMAN_INPUT.md`](HUMAN_INPUT.md) records what "my direction" meant in
practice, including the times I was wrong.

## Output

The tool writes vector `svg` and `pdf`, plus `png` for when something needs
it. It writes Graphviz `dot` for hand editing, editable `drawio`, `html` for
a searchable pan-and-zoom viewer, `mermaid` for a page that renders in
place, and `json` for other programs. [What each format is
for](docs/output.md).

## Install

```bash
sudo apt install graphviz          # provides `dot` and `unflatten`
python3 -m venv .venv && .venv/bin/pip install -e .
source .venv/bin/activate          # puts `unifi-map` on your PATH
```

A virtual environment install puts the command at `.venv/bin/unifi-map` and
nowhere else. If you do not activate it, every `unifi-map ...` example here
and under `docs/` returns `command not found`. Activate it, as above, or
spell the path out in full. The `make` targets are not affected. They call
the venv's copy directly.

This tool requires Python 3.11+. It needs Graphviz for the graphical
formats, which are the defaults: `svg`, `pdf`, `png`, `html` (`html` embeds
a rendered SVG), and the positions inside a `drawio` file. The tool writes
`dot`, `mermaid`, and `json` directly. These three need nothing installed.
`unflatten` is optional, but it improves layout on large networks.

### If you supply your own SVG artwork

Install the extra:

```bash
pip install -e ".[svg]"
```

This only matters if you point an [override](docs/overrides.md) at an
`.svg` file for a device icon. Without the extra, Graphviz loads SVG
artwork **only for the `svg` output**. `png` and `pdf` go through cairo,
which has no SVG loader, so both formats silently drop the icon. The tool
warns you before this happens, and it names the file.

With the extra, the tool rasterises an SVG to a cached PNG on the way in,
so the icon reaches every format. A file that lacks the XML declaration
Graphviz needs still works, untouched.

**Or convert the file to PNG, which needs no dependency at all.** Either
answer works. Use the extra if you keep changing the artwork, or if you
have several files. Convert to PNG if you would rather not add a
dependency. PNG override artwork needs none of this either way.

### Installing it somewhere else

`make build` produces a wheel and an sdist in `dist/`. Both install
anywhere, with no checkout needed:

```bash
make build
pip install dist/*.whl             # here, or copy the wheel to another machine
```

Use this to put the tool on a machine that should not carry the source.
Graphviz is still a system dependency. A wheel cannot bring it along.

There is **no published package**. `pip install unifi-map` does not work,
and it is not meant to. Whether this project should ever own a name on
PyPI is an open question, not an oversight. Publishing is the one step
nobody can undo, once somebody depends on it.

This project commits a man page as `unifi-map.1`, so it works straight
from a clone with nothing to install:

```bash
man ./unifi-map.1
```

`make docs` generates it from the argument parser. `make check` fails if
the man page goes stale.

### Installing from GitHub, no checkout needed

`pip install git+https://...` against a tag, or a release wheel by URL:
both work with no PyPI account. See [Installing from
GitHub](docs/install-from-github.md) for both methods, and for how `man
unifi-map` works either way from 0.10.0 on.

## Try it without touching your network

A synthetic dataset ships in `examples/demo/`, so you can see the output
before you point this at real infrastructure. It needs no credentials and
no controller:

```bash
make demo
# or:
unifi-map --cache-dir examples/demo --out-dir examples/demo render --per-network
```

Every MAC, address and hostname in it is invented. Some identifiers are
deliberately real, because they are what artwork lookup joins on:

- **Hardware `sysid` values are real**, so every UniFi device in the demo draws
  its actual product artwork.
- **A few client `dev_id` values are real** (a laptop, a phone, a TV, a
  thermostat and so on), so those clients get real artwork too.

The rest of the clients are pure invention with no fingerprint, so they render
with our own drawn client icons. This is expected, not a defect: made-up
devices have no product artwork to match. The console's own glyph is not
available either, because that font comes from a live controller. Against a
real controller both gaps close, and coverage is usually near total.

The dataset deliberately includes an offline device, four VLANs, and a client the
controller cannot place, so those behaviours are visible too.

An example overrides file ships alongside it, at
`examples/demo/overrides.toml`. It exercises every block against that data.
`make demo-overrides` renders it. Compare the two outputs to see what each
override actually changes.

**The interactive `-f html` viewer needs nothing running.** Browse it
directly: [`docs/demo-light.html`](docs/demo-light.html) and
[`docs/demo-dark.html`](docs/demo-dark.html). GitHub shows an `.html`
file's source instead of rendering it. Download the file, or clone the
repository, and open it locally to use it. Then you can pan, zoom, and
search. Click a client to trace its path. Click a switch or AP to collapse
its clients.

This project renders these two files with `--icons builtin` instead of the
default. This keeps anything Ubiquiti made out of a committed file. Every
other demo output here is gitignored for the same reason.

Regenerate the dataset with `make demo-snapshot` (see
`scripts/make_demo_snapshot.py`).

## Documentation

The README stops here on purpose. It helps you decide whether you want
this tool, and it gets you a first map. Everything else is a page of its
own.

| | |
| --- | --- |
| [Usage](docs/usage.md) | Every command and flag, and how to read the diagram. The parser generates the flag reference. |
| [Credentials](docs/credentials.md) | Connecting to a controller, what an API key can actually do, and the config file and `UNIFI_MAP_*` variables for settings you would rather not retype. |
| [Support files](docs/support-files.md) | Mapping without credentials, and why the file is a secret. |
| [Output formats](docs/output.md) | What each format is for, plus `--transparent` and turning the spinner off. |
| [Overrides](docs/overrides.md) | Stating what the controller cannot see: unreported links, nesting, corrections. |
| [Diagram-as-code (unsupported)](docs/diagram-as-code.md) | Skipping the controller entirely, as a side effect of the overrides schema. Not a feature. Read the caveats. |
| [Artwork](docs/artwork.md) | Where the pictures come from, how they are matched, and the licensing position. |
| [Sharing a map](docs/sharing.md) | `--obfuscate`, and the report meant for a bug report. |
| [Installing from GitHub](docs/install-from-github.md) | `pip install` from a tag or a release wheel, no PyPI and no checkout. |
| [What has been checked](docs/verification.md) | What was verified directly, what was not, and the caveats. |
| [Security](SECURITY.md) | The credential model, what reaches Ubiquiti's CDN, support-file risk. |
| [Contributing](CONTRIBUTING.md) | Including which data would genuinely help. |
| [☭ Values](VALUES.md) | The project's socialist free-software commitments and path to collective governance. |
| [Planned work](TODO.md) | What is coming, what is blocked and on what. |

## License

**unifi-map is AGPL-3.0-only.** You may use it, study it, modify it, and sell
copies or services around it. If you distribute a modified version, or run one
for users over a network, you must offer its corresponding source code under
AGPLv3 as well. There is no feature-limited edition, hosted upsell, or
proprietary version of this project.

Earlier releases remain under the MIT or GPL-3.0-only license under which
this project published them. The bundled Panzoom library is a separate
MIT-licensed component. Its required notice stays in the source. See
[LICENSE](LICENSE).
