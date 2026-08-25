# Planned work

This file lists everything planned for this tool, whether or not work
started on it. It exists so that "what is coming?" has an answer that
does not require you to read a 900-line context file or have an account
on somebody's Jira.

A maintainer reviews this at every release. Nothing here carries a date, and
items move down the list or out of it as often as they move up.

**Where the detail lives.** This file is what and one line of why. `CLAUDE.md`
carries the reasoning, the constraints and the approaches already tried and
rejected, and wins if the two disagree. A `KAN-` reference is an internal ticket
and not something you need.

---

## Making the map say how much it can be trusted

The theme through the next few items: this tool refuses to guess, and
currently that refusal is invisible. A map drawn from a perfect fetch and one
drawn from a thin one look equally authoritative.

- **A diagnostic report. Shipped, as `--report`** (KAN-115). This
  prints where the map came from after it renders: how many nodes and
  links came from each endpoint, which clients `stat/sta` placed versus
  the controller's topology graph versus an override, what it could not
  place, clients with no address, networks a client references that the
  controller does not list, artwork matches refused as ambiguous, and
  which endpoints the snapshot lacked, along with what each absence
  costs the map.

  **Not the same thing as `unifi-map shape`.** That describes a network
  for somebody else's benefit, and it builds from an allowlist so you
  can share it. This one describes *your* map for *your* benefit, and
  names your devices, because it never leaves your terminal. It says so
  at the top. This project briefly called both of them "report". That
  is why the shipped one has a different name.

  Note that it names a device only where something is wrong with it, so a clean
  map produces a report with no names in it.
- **Provenance on the diagram itself. Shipped** (KAN-137). A client placed via
  the controller's v2 topology graph, rather than reporting its own uplink, now
  gets a small hollow-circle arrowhead on that link, in both the SVG/PDF/PNG
  and draw.io outputs. Everything else `Provenance` distinguishes turned out to
  already have a channel: node role via `Kind`, asserted via dotted, offline
  via dashed.
- **Randomised client MACs. Shipped**, as a `--report` section (KAN-129).
  Every join here is on MAC, so a phone rotating its address appears as a new
  client unrelated to the old one. `--report` now counts how many currently
  show a locally-administered MAC and says why, without naming any of them:
  there is nothing wrong with a specific device and no overrides entry that
  would fix it.
- **Say when something is hiding on a switch port** (KAN-199). Two
  signals exist, and they are complementary. This project only built
  one.

  **Several wired clients reporting the same switch and port. Shipped**,
  2026-08-16. This needs no cooperation from the hidden device, which
  is what makes it work where LLDP cannot. The tool flags this, rather
  than drawing a node for it: the diagram marks the shared edges with a
  small diamond arrowhead, present in every layout, including the
  default `unifi` (`--layout tree` additionally appends `*` to the port
  label, and gets a legend row. draw.io gets the label marker alone,
  since it has no legend). `--report` names the port and lists the
  clients in a `SHARED SWITCH PORTS` section, and the console warns
  once per shared port (a bare count under `--obfuscate`). Several MACs
  on a port means an unmanaged switch or a virtualisation host bridging
  its guests, and neither the diagram nor the console picks one.
  `[[device]]` or `[[hosted]]` is how you say which it actually is.
  `unifi-map overrides generate` (KAN-120) now prints a starting
  skeleton for exactly this case.

  **The controller's own `has_unknown_switch` boolean is still
  unread.** It says one exists somewhere, never where, so it
  complements the signal above, rather than replacing it. It is also
  unverified: whether it is per-site, whether it clears, and whether an
  all-UniFi network ever sets it are all still open questions. See
  `CLAUDE.md`'s KAN-199 notes before you build this half.

## More ways to look at the network

- **An infrastructure view** (KAN-118). The console has a second
  diagram that is not simply the client map with clients removed: port
  badges at both ends of every link, speed-coloured edges, live CPU and
  memory, STP root. This project specced it in detail already.
  `--no-clients` is the rough approximation available today. It needs
  structured port data on `Edge` first, which currently carries a
  display label, rather than a port, a speed, and a medium.
- **Generalised filters** (KAN-122). `--kind switch ap`, `--wireless-only`,
  `--guest-only`, and `--root "Rack Switch"` for one subtree of a large map.
  `--per-network` is a special case of this and already does the hard part,
  which is keeping the path back to the gateway.
- **Location and rack grouping** (KAN-121). Say in an overrides file which rack
  something lives in, and have the diagram group by it. A controller cannot know
  this, which is exactly what overrides are for.
- **Colour by VLAN** (KAN-123). This would make segmentation visible
  at a glance. It needs a second visual channel first: colour is never
  the only channel here, so that the output survives greyscale and
  colourblind readers.
- **Historical clients** (KAN-127). This would be opt-in, and visibly
  dated. An old association is not evidence of where something is now,
  so the map must never draw it as a current link.
- **User-written port names** (KAN-197). The controller already holds
  them, in `port_overrides[].name` rather than the `port_table[].name`
  you would reach for first, and this project reads neither. On the
  reference network that is 26 human labels sitting unused in every
  snapshot this project writes. This is blocked until an obfuscation
  guard lands in the same change, since a port named after a person or
  a room is identifying in a way "port 12" never was.
- **A `serve` subcommand** (KAN-196). This would re-poll on a timer, so
  a browser gets a live view, rather than a file that was true only
  when someone wrote it. This project marked it *consider*: the
  objection to answer first is that live polling needs controller
  credentials, and anyone who holds those can open the console, which
  already has a live topology view. What the console cannot show is a
  map that carries your overrides, which is the case for building it
  anyway.

## Cache housekeeping

- **Decide what to do about a cache that only grows** (KAN-139).
  Nothing ever removes anything from the artwork cache. Product
  renders, client icons, ISP marks, the icon font, and the fingerprint
  database all accumulate. The rasterised copies of user-supplied SVGs
  are keyed on a hash of the source, so if you edit one, its
  predecessor stays behind permanently.

  This probably needs a `--clear-cache` flag, but the shape needs
  thought before the flag does. There are **two** caches with
  different characters: the snapshot cache holds a full inventory of a
  network, and only talking to the controller again can regenerate it.
  The artwork cache, in contrast, is entirely regenerable from the
  network. Clearing them is not the same act, and one flag that covers
  both would be a footgun. Selective clearing, or pruning by age, may
  be the better answer.

  This is not urgent. It is tens of megabytes on a real network, and it
  is worth designing once, rather than adding a flag someone has to
  redefine later.

## Comparing one fetch to another

- **A `diff` subcommand** (KAN-117). What changed between two snapshots: devices
  added or removed, clients that moved switch, port, AP, network or address.
  Snapshots are already immutable timestamped JSON, so this is a pure function
  over two graphs.
- **Snapshot retention** (KAN-116). This project needs this first,
  because each fetch currently overwrites the last, and there is no
  history to compare. It should be opt-in, since `fetch` always
  reflects current state, which is documented behaviour.

## Credentials and configuration

- **An OpenBao/Vault backend** (KAN-128). `config.py` is the only module that
  reads the environment specifically so this stays a single-file change.
- **A config file, and environment variables. Shipped** (KAN-130).
  `~/.config/unifi-map/config.toml` sits beside the credential file,
  plus `UNIFI_MAP_*` variables, with precedence flag > environment >
  config file > default. This project shipped both, rather than one,
  because they answer different needs: a file for somebody whose taste
  differs from the defaults, variables for anybody who runs this in a
  container, where mounting a file to set four preferences is friction
  a `-e` flag does not have.

  This project excludes `--obfuscate` and `--force` on purpose. One is
  a claim that the output is safe to share, and the other overwrites
  files. Neither should come from ambient state invisible at the call
  site. Every render now says where a setting it did not get from the
  command line came from.

## Overrides

- **A candidates generator. Shipped**, as `unifi-map overrides generate`
  (KAN-120), 2026-08-16. This prints a commented skeleton to stdout,
  seeded from the same signals `--report` names: clients with no
  reported uplink, switch ports shared by several wired clients
  (KAN-199), and artwork matches refused as ambiguous. Every block is
  commented out, so the file changes nothing until a human edits and
  uncomments it. The one field it never fills in is a client's real
  uplink. `--report` now points at it from each of those three
  sections. `overrides check`, the other half of the original ticket,
  shipped earlier.

## Multi-site

- **`--all-sites` and a `sites` command** (KAN-125). Each site would
  get its own diagrams, output directory, and cache. Note that live
  cannot enumerate sites at all today: every endpoint takes the site as
  a parameter, so `sites` is a prerequisite, not a companion.

---

## Correctness

- **Author the `.drawio` light whatever `--theme` says** (KAN-140).
  draw.io re-themes on load. It inverts a diagram to contrast with its
  own appearance setting, so a light-authored file is right in both of
  its modes, and a dark-authored one is right in neither. `--theme dark
  -f drawio` therefore has no configuration that works, which makes it
  a trap, not a choice.

  This is not a one-line swap, which is why it only warns today. Three
  artwork sources have the theme baked into their pixels: the drawn
  icons, the console's own client glyphs, and the drawn Internet cloud.
  If this project changed only the card colours, that would put
  light-baked glyphs on a white card. The fix is to resolve artwork
  twice, once per output theme, and give `write_outputs` a second icons
  dict for the draw.io pass.

## Tooling

- **A read-only way to show resolved configuration** (KAN-142). There
  is no way to ask where anything ended up. The only route is `-v` on a
  real render, which writes output and may download artwork just to
  report a path. That matters because you can set the three directory
  variables in the credential file, so they stay invisible from the
  shell.

  This should show: the resolved directories and which layer supplied
  each, which credential file the tool actually read, whether the `svg`
  extra is importable, and whether it found Graphviz. **Never the API
  key**, not even a prefix: a config display is exactly what ends up
  pasted into a bug report, the same reasoning that makes `unifi-map
  shape` allowlist-built.

## Shape of the code

- **Extract capability-sized pieces out of `assets.py`** (KAN-141). It
  is the largest module here, and it accumulated unrelated capabilities
  over time: CDN retrieval, catalogue parsing, fingerprint lookup, name
  matching, image measurement, bomb guards, SVG rasterisation, and
  local rendering of the cloud and glyphs.

  **Length is not the argument and must not become it.** This uses the
  same standard as the `cli.py` split: split by concern, with a reason
  per file, never by line count.

  Two extractions have a reason of their own. The **SVG conversion
  adapter** (`rasterise_svg`, `_measure_svg`, `_why_unreadable`) is one
  capability, and the only part that depends on the optional `svg`
  extra. So isolating it also puts that import behind a single
  boundary. The **capped-read primitive** was the second, and it is
  already done: it lives in `httpio.py`, shared by `client.py` and
  `assets.py`. That is why the two no longer need to schedule together.

## Committed to a version

Nothing currently.

A commitment means a version named in the code, the tests, and the
changelog. So this section stays empty unless this project actually
promised something to users.

## Waiting on a network nobody here has

This project is not waiting on effort. Everything here only ever ran
against one controller, one site, one support file, and one controller
version, so work on these would be guessing. If any of this describes
your setup, `CONTRIBUTING.md` says what would help and what not to
send.

- **Multi-site anything.** One site, ever.
- **Performance at scale.** Nobody ever profiled this on a large
  network. `sysid_for_name()` scanning the catalogue per candidate is
  the likely first problem.
- **The support-file limits.** All four defaults come from a single 154 MiB
  archive.
- **Other controller versions.** This project verified everything
  against UniFi OS 5.1.26 with Network 10.5.67.
- **Wireless signal overlays** (KAN-124). Band, channel width, and
  RSSI, if a live `stat/sta` carries them. The demo dataset lacks them,
  but it is synthetic and proves nothing either way. `unifi-map shape`
  now answers this the moment anybody runs it against a real
  controller: the schema section lists `rssi`, `signal`, `channel`, and
  `radio` as present or absent.

## Undecided, rather than unstarted

- **Whether to publish to PyPI.** This project already built an
  installable artifact, and that needs nothing from anyone: `make
  build` produces a wheel and an sdist, and `pip install dist/*.whl`
  works. What stays undecided is *publishing* one.

  That is deliberately a separate question, because nobody can undo it
  once done: it means owning the name, keeping metadata honest, and
  never breaking a published version once somebody depends on it.
  Nothing about the local build commits you to it, which is the point
  of splitting them.

  **Not happening any time soon**, stated 2026-08-03. It stays here rather than
  moving to the declined section below, because the position is about timing
  rather than merit and could change. Treat proposals that assume a PyPI
  release (publishing workflows, trusted publishing, Sigstore or SLSA
  attestations, PyPI-shaped packaging metadata) as out of scope until that
  changes, and do not add any of them speculatively.

  **Attaching the built artifacts to the GitHub Release, the other half of
  this that was "still open", shipped in 0.10.0.** `RELEASING.md` now runs
  `make build` and attaches `dist/*` and `unifi-map.1` to the Release, so
  `pip install <url>` works two ways without owning a PyPI name: a
  `git+https://` install against a tag, or a release wheel by URL. See
  `docs/install-from-github.md`. This is still not a PyPI decision. Nothing
  here needs an account, a name, or a promise not to break a published
  version, which is exactly why it stayed separable from the question above.

## Considered and not planned

This project records these so nobody re-proposes them as oversights.

- **A generic Diagram-as-Code tool.** The capability already exists,
  as a side effect rather than a design: `[[device]]` +
  `[[link]]`/`[[hosted]]` is already a complete node-and-edge
  declaration language, and the renderers are pure functions from a
  `Topology` to a picture with nothing UniFi-specific in them. So if
  you point `--cache-dir` at a snapshot that reports nothing, and
  describe an entire network by hand, that genuinely works today. This
  is documented at
  [`docs/diagram-as-code.md`](docs/diagram-as-code.md), as explicitly
  **not** a feature: no tests beyond pinning the two or three claims
  that page makes, no compatibility promise, and a real chance a future
  change breaks it without that counting as a breaking change from this
  project's own point of view. Turning this into an actual generic
  diagramming tool would mean a different `Kind` vocabulary,
  rack/location grouping, an icon library instead of one image per
  node: a different product, with different design pressures, aimed at
  a market (D2, Structurizr, plain Graphviz) this project has no reason
  to compete in.

- **A `[[merge]]` override, to declare that several MACs are one
  machine.** The tool draws a server with interfaces on three VLANs as
  three clients, because the controller reports interfaces, and no
  field anywhere says they share a chassis.

  It founders on the model, not the syntax. A merged node belongs to
  every network its interfaces are on. `Node.network` holds one value,
  and `--per-network` filters on it. Making that plural, to serve the
  combined view, would complicate the view that already handles this
  correctly: in a per-network diagram, the machine appears exactly
  once, as the interface that belongs to that network, with the
  address it has there. A merge would also have to refuse a node whose
  interfaces sit on different uplinks, and refuse to merge anything
  with its own ancestor, which is the physically correct case for a NAS
  behind its own host's NIC.

  What exists instead: `--per-network` as the clean view, `[[node]]`
  renames to tell interfaces apart in the combined one, and a note in
  `docs/usage.md` that explains this is a logical map, not a rack
  diagram. If a rack diagram is the goal, draw it somewhere that knows
  about racks.

- **A static type checker.** Three external reviews raised this across
  two rounds. This project **declined it on 2026-08-03**, and the
  repetition is why it is written down here, rather than left to be
  re-proposed a fourth time.

  Annotations stay. They are for readers and editors: `from __future__
  import annotations`, dataclasses, and explicit signatures make the
  code legible and drive autocomplete. What this project declines is
  *enforcement*: no mypy, no pyright, in the Makefile, the CI workflow,
  or a pre-commit hook.

  The reasoning has the same shape as the lock file below: real,
  permanent maintenance for a benefit nobody measured on this project.
  A checker strict enough to catch anything demands annotations on
  boundaries that deliberately accept whatever a controller sends. That
  is a design property here, not an oversight. `unwrap()` is tolerant
  on purpose. A checker loose enough to avoid that finds little.

- **A coverage threshold.** An external review suggested this. This
  project declined it on 2026-08-03.

  A number gates the build, so the cheapest way past a failing build is
  a test written to move the number. Those tests exercise lines
  without asserting anything worth asserting, and a report cannot
  distinguish them from tests that would catch a regression. This
  repository already produced two tests that could not fail, found by
  inspection rather than by any metric, and a threshold would have
  counted both as coverage.

  What this project actually wants is that the risky surfaces get
  tests, and it knows those by name, rather than by percentage: archive
  parsing, override resolution, obfuscation, output escaping, the
  overwrite guard. Each has adversarial tests written against a
  specific failure.

  **Measuring** coverage is a different question, and this project
  never declined it. It now happens: CI reports Python coverage to
  SonarQube Cloud, so the number exists, and you can find a module
  worth a second look from it. What stays declined is the *gate*.
  Nothing fails a build on that figure, and a proposal to make it do so
  is a proposal to reverse this decision, not to finish it.

- **NetBox / IPAM export.** `-f json` subsumes this, rather than
  refusing it: the ask was structured JSON *for importing into* NetBox,
  and once that export exists, a transform against our stable schema
  beats this project tracking theirs, and it does. An export is fine. A
  *sync* is not, since `session.get` is the only HTTP verb in the
  source, which is a headline property.
- **An `AbstractRenderer` protocol.** Two renderers exist, both already
  pure functions from `Topology` to text. A protocol over two
  implementations is a layer to maintain before anyone shows it is
  needed.
- **A shared `UnifiMapError` base class.** Somebody proposed this so a
  library consumer could catch everything with one `except`. There is
  no library consumer, and the one caller that exists wants the
  opposite: `main()` maps `ConfigError` and `OverrideError` to exit 2
  and `GraphvizMissing` to exit 3, so it needs the distinctions a base
  class would let people discard. This is cheap to add later, if
  somebody imports this as a library and asks.
- **`TypedDict` for the controller payloads.** This project declined
  it, for what it would assert. `unwrap()` is deliberately tolerant
  because UniFi's schemas move between versions, and the design is that
  a changed payload thins the diagram, rather than raising an error. If
  this project typed those dicts, that would write down shapes it
  specifically refuses to rely on, and a strict checker would then
  enforce them. The normalised model is already typed, and that is the
  part that is stable.
