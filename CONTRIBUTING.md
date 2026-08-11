# Contributing

Contributions are welcome. This is a spare-time project, so replies may take a
few days.

## Something you should know first

Most of this code was written by an AI assistant working from the maintainer's
direction, review and testing against a real network. It has tests and the
design decisions have reasons behind them, recorded in `CLAUDE.md`, but it has
not been reviewed line by line by a human.

That is not an apology, it is context. If you are going to read or extend the
code, you deserve to know how it got here.

## Getting set up

```bash
sudo apt install graphviz          # provides dot and unflatten
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
make check
```

You do not need a UniFi controller to work on this. A synthetic dataset ships in
`examples/demo/`:

```bash
make demo
```

Most changes can be developed and reviewed entirely against that.

## The gate

```bash
make check
```

That runs `ruff format --check`, `ruff check` and `pytest`. All three have to
pass. Please run it before opening a pull request.

If you are checking it in a script, check the exit code rather than eyeballing
the output. Piping `pytest` into something that discards its status will hide a
failure, which has happened here before.

## Rules that are not obvious

These exist for reasons, and `CLAUDE.md` has the longer version.

**Tests never touch the network.** Not the controller, not Ubiquiti's CDN. If
something needs remote data, feed it a fixture. `tests/test_assets.py` writes a
catalogue into a temporary cache to show the pattern.

**Fixtures must be non-identifying.** No real hostnames, subnets, SSIDs or device
addresses, in code, tests, docs or demo data. Use RFC 1918 or documentation
ranges and locally administered (`02:`) MAC addresses. `tests/test_demo.py`
enforces this for the demo dataset.

**Never vendor Ubiquiti artwork.** Device images are Ubiquiti's intellectual
property. They are fetched at runtime and cached under `cache/`, which is
gitignored. `--icons builtin` must remain a fully working, network-free path.

**Never commit `cache/` or `out/`.** They contain a MAC, hostname and IP
inventory of a real network. See `SECURITY.md`.

**Do not guess on the user's behalf.** Where the data is ambiguous, the tool says
so rather than picking something plausible. A client whose uplink the controller
does not report is anchored to an explicit placeholder rather than attached to a
likely-looking switch. A hostname matching several products resolves to nothing
unless something else can break the tie. Preserve that: a wrong diagram is worse
than an incomplete one, because it looks correct.

**Colour is never the only channel.** The maintainer is deuteran colourblind.
Every distinction is also carried by artwork, shape or line style, so the output
stays readable in greyscale. Do not add a red and green pair that carries meaning
by itself.

**The documentation has to match the render.** If you change what is drawn, check
the legend still describes it. The legend deliberately lists only what a given
render actually encodes.

## House style

Ordinary Python, `ruff` settled, 100 column lines, modern type hints.

Comments should explain why, not what. The reason a line exists, the constraint
it satisfies, or the bug it prevents. Not a restatement of the code.

## Versioning

Semantic versioning, currently pre-1.0, so the command line interface is not
stable yet: flags and defaults may change between minor versions while the tool
settles.

The version lives in `src/unifi_map/__init__.py` and `pyproject.toml` reads it
from there, so there is one number to change rather than two to keep in step.
Note the change in `CHANGELOG.md` under Unreleased; a maintainer moves it under a
version at release time.

## Architecture in one paragraph

Each stage owns one concern and nothing downstream of `model.py` sees raw
controller JSON. `config.py` reads the environment, `client.py` talks to the
controller, `model.py` normalises into a `Topology`, `assets.py` fetches artwork,
`layout.py` shells out to Graphviz, and the renderers are pure functions from a
`Topology` to text. Keep new work inside whichever of those it belongs to.

`CLAUDE.md` documents the traps in detail, including several that cost real time
to find. It is worth skimming before a non-trivial change.

## What would help most, if you have a network we do not

Some of this project is stuck on evidence rather than on effort. It has only
ever been run against **one controller with one site** — UniFi Network 10.5.67
on a UDM Pro Max — so several things are written from a single sample and say so
where they are documented. More reasoning will not improve them. Only a second
data point will.

If any of these describe you, an issue saying so is genuinely more useful than a
patch:

- **A console with more than one site.** Multi-site handling exists and is
  untested. `--all-sites` is designed but deliberately unbuilt, because building
  it against an assumed API response is how it would end up subtly wrong.
- **A large network**, a few hundred clients or more. Nothing here has been
  profiled at scale, and the first thing likely to hurt is a per-candidate scan
  of the hardware catalogue.
- **A different controller version**, older or newer. Endpoint shapes are
  absorbed rather than asserted, on the assumption they will thin gracefully. It
  would be good to know whether that assumption survives contact.
- **UniFi Access, Talk, or a UNAS.** This has only ever run against Network and
  Protect. Devices from the other applications already draw as ordinary clients
  or hardware, so nothing is broken; what is missing is the extra source that
  would let an ambiguous match resolve. A `g3-flex` is both a Protect camera and
  an Access reader, and only one of those can currently be confirmed. Even the
  shape of an empty response from one of those apps is useful.
- **A support file from a big site.** The four size and walk limits are set from
  one 154 MiB archive; the archive-walk default in particular has no measured
  basis, only a number that is obviously absurd to exceed.

**There is a command for this.** `unifi-map shape` prints exactly what is
useful here and nothing else: counts, fan-out, which field names your controller
returns, versions. It shows you what it collects and asks before producing
anything, and the output is short enough to read in full before you decide.

```bash
unifi-map shape                              # from a cached snapshot
unifi-map shape --support-file support.tgz    # or straight from an archive
```

The archive form also reports how large the file is to walk and how many sites
it holds, which are the two numbers behind most of the guesses above.

**Do not send the data itself.** A snapshot is a full MAC, hostname and IP
inventory, and a support file is that plus SSIDs, subnets, WAN addresses and
client activity logs. Neither belongs in an issue.

What helps instead: run the command, and paste what the tool says about itself.
Counts, warnings, an error, the output of `-v`, or the shape of a payload with
the values removed. If something can only be answered by real data, say so and
we will work out how to get the answer without you handing over your network.

## Pull requests

Small and focused beats large and sweeping. Say what changed and why. If it fixes
something subtle, a test that would have caught it is more persuasive than a
description.

By submitting a contribution, you license that contribution under GPL-3.0-only,
so it can be distributed with the project. The bundled Panzoom library is a
separate MIT-licensed third-party component and is not a contribution to
unifi-map.

If you disagree with a decision recorded in `CLAUDE.md`, that is fair game.
Say so in the pull request rather than quietly reversing it.
