# Planned work

Everything intended for this tool, whether or not it has been started. Kept so
that "what is coming?" has an answer that does not require reading a 900-line
context file or having an account on somebody's Jira.

Reviewed at every release. Nothing here carries a date, and items move down the
list or out of it as often as they move up.

**Where the detail lives.** This file is what and one line of why. `CLAUDE.md`
carries the reasoning, the constraints and the approaches already tried and
rejected, and wins if the two disagree. A `KAN-` reference is an internal ticket
and not something you need.

---

## Making the map say how much it can be trusted

The theme running through the next few items: this tool refuses to guess, and
currently that refusal is invisible. A map drawn from a perfect fetch and one
drawn from a thin one look equally authoritative.

- **A diagnostic report. Shipped, as `--report`** (KAN-115). Prints where the
  map came from after rendering it: how many nodes and links came from each
  endpoint, which clients were placed from `stat/sta` versus the controller's
  topology graph versus an override, what could not be placed, clients with no
  address, networks a client references that the controller does not list,
  artwork matches refused as ambiguous, and which endpoints the snapshot was
  missing along with what each absence costs the map.

  **Not the same thing as `unifi-map shape`.** That describes a network for
  somebody else's benefit and is built from an allowlist so it can be shared.
  This one describes *your* map for *your* benefit and names your devices,
  because it is never leaving your terminal; it says so at the top. Both were
  briefly called "report", which is why the shipped one is not.

  Note that it names a device only where something is wrong with it, so a clean
  map produces a report with no names in it.
- **Provenance on the diagram itself. Shipped** (KAN-137). A client placed via
  the controller's v2 topology graph, rather than reporting its own uplink, now
  gets a small hollow-circle arrowhead on that link, in both the SVG/PDF/PNG
  and draw.io outputs. Everything else `Provenance` distinguishes turned out to
  already have a channel: node role via `Kind`, asserted via dotted, offline
  via dashed.
- **Randomised client MACs** (KAN-129). Every join here is on MAC, so a phone
  rotating its address appears as a new client unrelated to the old one. Explains
  apparent duplicates. Detectable from the locally-administered bit.

## More ways to look at the network

- **An infrastructure view** (KAN-118). The console has a second diagram that is
  not simply the client map with clients removed: port badges at both ends of
  every link, speed-coloured edges, live CPU and memory, STP root. Specced in
  detail already. `--no-clients` is the rough approximation available today.
  Needs structured port data on `Edge` first, which currently carries a display
  label rather than a port, a speed and a medium.
- **Generalised filters** (KAN-122). `--kind switch ap`, `--wireless-only`,
  `--guest-only`, and `--root "Rack Switch"` for one subtree of a large map.
  `--per-network` is a special case of this and already does the hard part,
  which is keeping the path back to the gateway.
- **Location and rack grouping** (KAN-121). Say in an overrides file which rack
  something lives in, and have the diagram group by it. A controller cannot know
  this, which is exactly what overrides are for.
- **Colour by VLAN** (KAN-123). Segmentation visible at a glance. Needs a second
  visual channel first: colour is never the only channel here, so that the output
  survives greyscale and colourblind readers.
- **Historical clients** (KAN-127). Opt-in, and visibly dated. An old association
  is not evidence of where something is now, so it must never be drawn as a
  current link.

## Cache housekeeping

- **Decide what to do about a cache that only grows** (KAN-139). Nothing ever
  removes anything from the artwork cache. Product renders, client icons, ISP
  marks, the icon font and the fingerprint database all accumulate, and the
  rasterised copies of user-supplied SVGs are keyed on a hash of the source, so
  editing one leaves its predecessor behind permanently.

  Probably a `--clear-cache`, but the shape needs thought before the flag does.
  There are **two** caches with different characters: the snapshot cache holds a
  full inventory of a network and is regenerable only by talking to the
  controller again, while the artwork cache is entirely regenerable from the
  network. Clearing them is not the same act and one flag covering both would be
  a footgun. Selective clearing, or pruning by age, may be the better answer.

  Not urgent. It is tens of megabytes on a real network, and worth designing
  once rather than adding a flag that has to be redefined later.

## Comparing one fetch to another

- **A `diff` subcommand** (KAN-117). What changed between two snapshots: devices
  added or removed, clients that moved switch, port, AP, network or address.
  Snapshots are already immutable timestamped JSON, so this is a pure function
  over two graphs.
- **Snapshot retention** (KAN-116). Required first, because each fetch currently
  overwrites the last and there is no history to compare. Opt-in, since `fetch`
  always reflecting current state is documented behaviour.

## Credentials and configuration

- **An OpenBao/Vault backend** (KAN-128). `config.py` is the only module that
  reads the environment specifically so this stays a single-file change.
- **Preferences in the environment** (KAN-130), so somebody whose taste differs
  from the defaults need not retype them. Weighed against reproducibility
  between machines; a config file is the alternative and shipping both would be
  worse than either.

## Overrides

- **A candidates generator** (KAN-120). Emit a skeleton overrides file seeded
  with what could not be placed. Commented boilerplate that still requires a
  human to state the relationship; never a guessed parent. The other half of
  that ticket, `overrides check`, ships already.

## Multi-site

- **`--all-sites` and a `sites` command** (KAN-125). Each site to its own
  diagrams, output directory and cache. Note that live cannot enumerate sites at
  all today: every endpoint takes the site as a parameter, so `sites` is a
  prerequisite rather than a companion.

---

## Correctness

- **Author the `.drawio` light whatever `--theme` says** (KAN-140). draw.io
  re-themes on load, inverting a diagram to contrast with its own appearance
  setting, so a light-authored file is right in both of its modes and a
  dark-authored one is right in neither. `--theme dark -f drawio` therefore has
  no configuration that works, which makes it a trap rather than a choice.

  Not a one-line swap, which is why it warns instead today. Three artwork
  sources have the theme baked into their pixels: the drawn icons, the
  console's own client glyphs, and the drawn Internet cloud. Changing only the
  card colours would put light-baked glyphs on a white card. The fix is to
  resolve artwork twice, once per output theme, and give `write_outputs` a
  second icons dict for the draw.io pass.

## Tooling

- **A read-only way to show resolved configuration** (KAN-142). There is no way
  to ask where anything ended up. The only route is `-v` on a real render, which
  writes output and may download artwork just to report a path. That matters
  because the three directory variables can be set in the credential file, so
  they are invisible from the shell.

  Worth showing: the resolved directories and which layer supplied each, which
  credential file was actually read, whether the `svg` extra is importable, and
  whether Graphviz was found. **Never the API key**, not even a prefix: a config
  display is exactly what ends up pasted into a bug report, which is the same
  reasoning that makes `unifi-map shape` allowlist-built.

## Shape of the code

- **Extract capability-sized pieces out of `assets.py`** (KAN-141). It is the
  largest module here and has been accumulating unrelated capabilities: CDN
  retrieval, catalogue parsing, fingerprint lookup, name matching, image
  measurement, bomb guards, SVG rasterisation, and local rendering of the cloud
  and glyphs.

  **Length is not the argument and must not become it.** Same standard as the
  `cli.py` split: by concern, with a reason per file, never by line count.

  Two extractions have a reason of their own. The **SVG conversion adapter**
  (`rasterise_svg`, `_measure_svg`, `_why_unreadable`) is one capability and the
  only part that depends on the optional `svg` extra, so isolating it also puts
  that import behind a single boundary. The **capped-read primitive** was the
  second and is already done: it lives in `httpio.py`, shared by `client.py`
  and `assets.py`, which is why the two schedule together no longer applies.

## Committed to a version

Nothing currently.

A commitment means a version named in the code, the tests and the changelog, so
this section stays empty unless something has actually been promised to users.

## Waiting on a network nobody here has

Not waiting on effort. Everything here has only ever run against one controller,
one site, one support file and one controller version, so work on these would be
guessing. If any of this describes your setup, `CONTRIBUTING.md` says what would
help and what not to send.

- **Multi-site anything.** One site, ever.
- **Performance at scale.** Never profiled on a large network.
  `sysid_for_name()` scanning the catalogue per candidate is the likely first
  problem.
- **The support-file limits.** All four defaults come from a single 154 MiB
  archive.
- **Other controller versions.** Verified against UniFi OS 5.1.26 with Network
  10.5.67.
- **Wireless signal overlays** (KAN-124). Band, channel width and RSSI, if they
  are in a live `stat/sta`. The demo dataset lacks them, but it is synthetic and
  proves nothing either way. `unifi-map shape` now answers this the moment
  anybody runs it against a real controller: the schema section lists `rssi`,
  `signal`, `channel` and `radio` as present or absent.

## Undecided, rather than unstarted

- **Whether to publish to PyPI.** Building an installable artifact is done and
  needs nothing from anyone: `make build` produces a wheel and an sdist, and
  `pip install dist/*.whl` works. What stays undecided is *publishing* one.

  That is deliberately a separate question, because it is the part that cannot
  be undone: it means owning the name, keeping metadata honest and never
  breaking a published version once somebody depends on it. Nothing about the
  local build commits you to it, which is the point of splitting them.

  **Not happening any time soon**, stated 2026-08-03. It stays here rather than
  moving to the declined section below, because the position is about timing
  rather than merit and could change. Treat proposals that assume a PyPI
  release — publishing workflows, trusted publishing, Sigstore or SLSA
  attestations, PyPI-shaped packaging metadata — as out of scope until that
  changes, and do not add any of them speculatively.

  **Attaching the built artifacts to the GitHub Release, the other half of
  this that was "still open", shipped in 0.10.0.** `RELEASING.md` now runs
  `make build` and attaches `dist/*` and `unifi-map.1` to the Release, so
  `pip install <url>` works two ways without owning a PyPI name: a
  `git+https://` install against a tag, or a release wheel by URL. See
  `docs/install-from-github.md`. This is still not a PyPI decision — nothing
  here needs an account, a name, or a promise not to break a published
  version — which is exactly why it stayed separable from the question above.

## Considered and not planned

Recorded so they are not re-proposed as oversights.

- **A static type checker.** Raised by three external reviews across two
  rounds; **declined 2026-08-03**, and the repetition is why it is written down
  here rather than left to be re-proposed a fourth time.

  Annotations stay. They are for readers and editors: `from __future__ import
  annotations`, dataclasses and explicit signatures make the code legible and
  drive autocomplete. What is declined is *enforcement* — no mypy, no pyright,
  in the Makefile, the CI workflow or a pre-commit hook.

  The reasoning is the same shape as the lock file below: real, permanent
  maintenance for a benefit nobody has measured on this project. A checker
  strict enough to catch anything demands annotations on boundaries that
  deliberately accept whatever a controller sends, which is a design property
  here rather than an oversight; `unwrap()` is tolerant on purpose. A checker
  loose enough to avoid that finds little.

- **A coverage threshold.** Suggested by an external review, declined 2026-08-03.

  A number gates the build, so the cheapest way past a failing build is a test
  written to move the number. Those tests exercise lines without asserting
  anything worth asserting, and they are indistinguishable in a report from
  tests that would catch a regression. This repository has already produced two
  tests that could not fail, found by inspection rather than by any metric, and
  a threshold would have counted both as coverage.

  What is actually wanted is that the risky surfaces are tested, and those are
  known by name rather than by percentage: archive parsing, override resolution,
  obfuscation, output escaping, the overwrite guard. Each has adversarial tests
  written against a specific failure.

  **Measuring** coverage is a different question and was never declined, and it
  now happens: CI reports Python coverage to SonarQube Cloud, so the number
  exists and a module worth a second look can be found from it. What stays
  declined is the *gate*. Nothing fails a build on that figure, and a proposal
  to make it do so is a proposal to reverse this decision rather than to finish
  it.

- **A dependency lock file.** Hashed constraints are ongoing maintenance for a
  dev-only benefit, and Dependabot plus the advisory job cover staying current.
  Revisit if this ever ships an artifact people install.
- **NetBox / IPAM export.** Subsumed by `-f json`, which ships, rather than
  refused: the ask was structured JSON *for importing into* NetBox, and once
  that export exists, a transform against our stable schema beats us tracking
  theirs, and it does. An export is fine; a *sync* is not, since `session.get` being the only
  HTTP verb in the source is a headline property.
- **An `AbstractRenderer` protocol.** Two renderers exist, both already pure
  functions from `Topology` to text. A protocol over two implementations is a
  layer to maintain before it has been shown to be needed.
- **A shared `UnifiMapError` base class.** Proposed so a library consumer could
  catch everything with one `except`. There is no library consumer, and the one
  caller that exists wants the opposite: `main()` maps `ConfigError` and
  `OverrideError` to exit 2 and `GraphvizMissing` to exit 3, so it needs the
  distinctions a base class would let people discard. Cheap to add later if
  somebody imports this as a library and asks.
- **`TypedDict` for the controller payloads.** Declined for what it would
  assert. `unwrap()` is deliberately tolerant because UniFi's schemas move
  between versions, and the design is that a changed payload thins the diagram
  rather than raising. Typing those dicts would write down shapes this project
  specifically refuses to rely on, and a strict checker would then enforce them.
  The normalised model is already typed, and that is the part that is stable.
