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

- **A diagnostic report** (KAN-115). `--report` describing the map it just drew:
  how many nodes came from which endpoint, which clients were placed from
  `stat/sta` versus the topology graph versus an override, what could not be
  placed and why, artwork matches refused as ambiguous, networks a client
  references that the controller does not list. Most of this is already decided
  at runtime and thrown away as log lines.

  **Not the same thing as `unifi-map shape`**, which ships already. That
  describes a network for somebody else's benefit and is built from an
  allowlist so it can be shared. This one describes *your* map for *your*
  benefit and may freely name your devices, because it is never leaving your
  terminal. Both were briefly called "report", which is why the shipped one
  is not.
- **Provenance on the diagram itself.** An override-asserted link is drawn
  dotted; nothing else distinguishes observed from inferred. A client placed
  from the topology graph, one placed from `stat/sta`, and one whose fingerprint
  was recovered from its name are drawn identically.
- **Randomised client MACs** (KAN-129). Every join here is on MAC, so a phone
  rotating its address appears as a new client unrelated to the old one. Explains
  apparent duplicates. Detectable from the locally-administered bit.

## More ways to look at the network

- **An infrastructure view** (KAN-118). The console has a second diagram that is
  not simply the client map with clients removed: port badges at both ends of
  every link, speed-coloured edges, live CPU and memory, STP root. Specced in
  detail already. Needs structured port data on `Edge` first, which today
  carries a display label rather than a port, a speed and a medium.
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

## More things to do with the output

- **An interactive HTML viewer** (KAN-126). Search and filter, pan and zoom,
  click a node to highlight its path to the gateway, collapse client subtrees.
  That last one addresses the problem this tool exists for. Wants a decision
  about JavaScript before it starts.
- **Drawn device icons.** Seven Pillow-drawn shapes replacing the Graphviz
  primitives, used in `--icons builtin` and as the fallback inside
  `--icons unifi` for hardware absent from Ubiquiti's catalogue.
  `_render_cloud()` already proved the approach: ours, so no network and no
  licensing question.

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
- **Retiring the `UDM_*` environment names.** They warn already. No removal
  version promised, on purpose.

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

## Committed to a version

Nothing currently. The last entry here, removing the `sane` layout alias, shipped
in 0.6.0.

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

- **Whether a release should produce an artifact.** Today it is a tag and a
  changelog entry. `pip install unifi-map` would mean owning the name, never
  breaking a published build, and placing the man page in `share/man/man1`. A
  commitment rather than a chore.

## Considered and not planned

Recorded so they are not re-proposed as oversights.

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
