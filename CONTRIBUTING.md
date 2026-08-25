# Contributing

Contributions are welcome. This is a spare-time project, so replies may take a
few days.

## Something you should know first

An AI assistant wrote most of this code, working from the maintainer's
direction, review, and testing against a real network. It has tests, and
the design decisions have reasons behind them, recorded in `CLAUDE.md`.
No human reviews it line by line.

This is context, not an apology. Read or extend the code with that in mind.

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

You can develop and review most changes entirely against that.

## The gate

```bash
make check
```

That runs `ruff format --check`, `ruff check` and `pytest`. All three
have to pass. Please run it before you open a pull request.

If you check it in a script, check the exit code, rather than eyeball
the output. If you pipe `pytest` into something that discards its
status, that hides a failure. This happened here before.

**New functionality needs tests in the same pull request that adds it.**
The tests must cover the behavior the changelog entry describes, not
just the code path. A passing suite that never exercised the new
behavior is worse than an obviously-missing test, because it looks like
coverage. `CLAUDE.md` has a section on mutation-testing a guard before
you trust it. Read that before you write one.

## Rules that are not obvious

These exist for reasons, and `CLAUDE.md` has the longer version.

**Tests never touch the network.** Not the controller, not Ubiquiti's CDN. If
something needs remote data, feed it a fixture. `tests/test_assets.py` writes a
catalogue into a temporary cache to show the pattern.

**Fixtures must be non-identifying.** No real hostnames, subnets, SSIDs or device
addresses, in code, tests, docs or demo data. Use RFC 1918 or documentation
ranges and locally administered (`02:`) MAC addresses. `tests/test_demo.py`
enforces this for the demo dataset.

**Never vendor Ubiquiti artwork.** Device images are Ubiquiti's
intellectual property. This tool fetches them at runtime and caches
them under `cache/`, which is gitignored. `--icons builtin` must remain
a fully working, network-free path.

**Never commit `cache/` or `out/`.** They contain a MAC, hostname and IP
inventory of a real network. See `SECURITY.md`.

**Do not guess on the user's behalf.** Where the data is ambiguous, the
tool says so. It does not guess at something plausible instead. The
tool anchors a client whose uplink the controller does not report to an
explicit placeholder. It does not attach the client to a likely-looking
switch. A hostname that matches several products resolves to nothing,
unless something else can break the tie. Preserve that. A wrong diagram
is worse than an incomplete one, because it looks correct.

**Colour is never the only channel.** The maintainer is deuteran
colourblind. Artwork, shape, or line style also carries every
distinction, so the output stays readable in greyscale. Do not add a
red and green pair that carries meaning by itself.

**The documentation has to match the render.** If you change what the
tool draws, check that the legend still describes it. The legend
deliberately lists only what a given render actually encodes.

## House style

Ordinary Python, `ruff` settled, 100 column lines, modern type hints.

Comments should explain why, not what. The reason a line exists, the constraint
it satisfies, or the bug it prevents. Not a restatement of the code.

## Versioning

Semantic versioning, currently pre-1.0, so the command line interface is not
stable yet: flags and defaults may change between minor versions while the tool
settles.

The version lives in `src/unifi_map/__init__.py`, and `pyproject.toml`
reads it from there, so there is one number to change, not two to keep
in step. Note the change in `CHANGELOG.md`, under Unreleased. A
maintainer moves it under a version at release time.

## Architecture in one paragraph

Each stage owns one concern and nothing downstream of `model.py` sees raw
controller JSON. `config.py` reads the environment, `client.py` talks to the
controller, `model.py` normalises into a `Topology`, `assets.py` fetches artwork,
`layout.py` shells out to Graphviz, and the renderers are pure functions from a
`Topology` to text. Keep new work inside whichever of those it belongs to.

`CLAUDE.md` documents the traps in detail, including several that cost
real time to find. Skim it before a non-trivial change.

## What would help most, if you have a network we do not

Some of this project is stuck on evidence, not effort. This project
only ran against **one controller with one site** (UniFi Network
10.5.67 on a UDM Pro Max). So this documents several things from a
single sample, and says so wherever that applies. Reasoning will not
improve them. A second data point will.

If any of these describe you, an issue that says so is genuinely more
useful than a patch:

- **A console with more than one site.** Multi-site handling exists
  and remains untested. `--all-sites` is designed but deliberately
  unbuilt, because building it against an assumed API response is how
  it would end up subtly wrong.
- **A large network**, a few hundred clients or more. This project
  never profiled anything at scale, and the first thing likely to hurt
  is a per-candidate scan of the hardware catalogue.
- **A different controller version**, older or newer. This tool absorbs
  endpoint shapes, rather than asserting them, on the assumption they
  will thin gracefully. It would be good to know whether that
  assumption survives contact.
- **UniFi Access, Talk, or a UNAS.** This project only tested Network
  and Protect. Devices from the other applications already draw as
  ordinary clients or hardware, so nothing is broken. What is missing is
  the extra source that would let an ambiguous match resolve. A
  `g3-flex` is both a Protect camera and an Access reader, and this
  project can currently confirm only one of those. Even the shape of an
  empty response from one of those apps is useful.
- **A support file from a big site.** The four size and walk limits
  come from one 154 MiB archive. The archive-walk default in
  particular has no measured basis, only a number that is obviously
  absurd to exceed.

**There is a command for this.** `unifi-map shape` prints exactly what
is useful here and nothing else: counts, fan-out, which field names
your controller returns, versions. It shows you what it collects, and
asks before it produces anything. The output is short enough to read in
full before you decide.

```bash
unifi-map shape                              # from a cached snapshot
unifi-map shape --support-file support.tgz    # or straight from an archive
```

The archive form also reports how large the file is to walk and how many sites
it holds, which are the two numbers behind most of the guesses above.

**Do not send the data itself.** A snapshot is a full MAC, hostname and IP
inventory, and a support file is that plus SSIDs, subnets, WAN addresses and
client activity logs. Neither belongs in an issue.

What helps instead: run the command, and paste what the tool says about
itself. That might be counts, warnings, an error, the output of `-v`, or
the shape of a payload with the values removed. If only real data can
answer something, say so, and we will work out how to get the answer
without you handing over your network.

## Pull requests

Small and focused beats large and sweeping. Say what changed and why. If it fixes
something subtle, a test that would have caught it is more persuasive than a
description.

If you submit a contribution, you license it under AGPL-3.0-only, so
the project can distribute it. The bundled Panzoom library is a
separate MIT-licensed third-party component, and it is not a
contribution to unifi-map.

If you disagree with a decision recorded in `CLAUDE.md`, that is fair
game. Say so in the pull request. Do not quietly reverse it instead.
