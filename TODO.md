# Planned work

What is coming, in one place. Kept because the alternatives are a 900-line
context file written for AI agents and a Jira instance nobody outside this house
can reach, and neither is where somebody looking at a checkout would think to
look.

**Where the detail lives.** This file says *what* and *why in one line*.
`CLAUDE.md` carries the reasoning, the constraints and the things already tried
and rejected, and stays authoritative when the two disagree. Jira epic KAN-114
tracks status. Anything here that contradicts `CLAUDE.md` is this file being
out of date.

Nothing here is a commitment except the section immediately below.

## Before 0.6.0

The only things actually promised. Each is promised in code, tests and the
changelog, so removing them is not optional and the version number cannot move
until they are done.

- [ ] **Remove the `sane` layout alias.** Renamed to `tree` in 0.5.0, still
      accepted, hidden from `--help`, and warning that it goes in 0.6.0. Delete
      `DEPRECATED_LAYOUTS`, the warning in `cmd_render`, the widened `choices`,
      the `sane` Makefile target, and the tests asserting the promise.

That is the whole list. `--transparent` and the both-theme screenshots are done
and sitting in `Unreleased`; they need a release, not work.

## Next, in the order that makes sense

Ranked by what makes the following item easier, not by appeal.

- [ ] **Diagnostic report** (KAN-115) — `--report` saying how trustworthy the
      map it just drew is: what came from which endpoint, what could not be
      placed and why, artwork matches refused as ambiguous. Most of these
      decisions are already made at runtime and thrown away as log lines. Picked
      first because everything after it is easier to debug once it exists.
- [ ] **Infrastructure view** (KAN-118) — the console's own second diagram,
      already specced in detail from a screenshot. Needs structured port data on
      `Edge` first, which currently carries a display label like `"port 12"`
      rather than a port, a speed and a medium.
- [ ] **Normalised JSON export** (KAN-119) — `Topology` as JSON rather than raw
      controller payloads, since the model is the stable thing. Shares the
      provenance work with the report above, so do them together.
- [ ] **Overrides tooling** (KAN-120) — `overrides check` to validate selectors
      without rendering, and a candidates generator seeded with what could not
      be placed. Must emit commented boilerplate that still requires a human to
      state the relationship; never a guessed parent.
- [ ] **Generalised filters** (KAN-122) — `--kind`, `--wireless-only`,
      `--guest-only`, and `--root NAME` for a subtree. `--per-network` already
      does the hard part, which is keeping the path back to the gateway.
- [ ] **Mermaid export**, and an interactive HTML viewer (KAN-126) — the first
      is cheap and puts a topology somewhere it currently cannot go, a README or
      a wiki. The second is larger and needs a decision about JavaScript before
      it starts.
- [ ] **Drawn device icons** — seven Pillow-drawn primitives replacing the
      Graphviz shapes, in `--icons builtin` and as the fallback inside
      `--icons unifi` when hardware is not in Ubiquiti's catalogue.
      `_render_cloud()` already proved the approach.
- [ ] **Location and rack grouping** (KAN-121) — clusters from an override
      field. Prototype the layout before fixing the schema; clusters interact
      badly with `--layout unifi` and have never been tried against the
      `unflatten` pass.

## Blocked, and on what

- [ ] **`diff` between two snapshots** (KAN-117) — blocked twice. Each fetch
      overwrites the last, so there is no history (KAN-116), and rotating client
      MACs would report every run as churn (KAN-129). Both are hard blockers.
- [ ] **Snapshot retention** (KAN-116) — opt-in timestamped mode. Not a changed
      default: `fetch` always reflecting current state is documented behaviour.
- [ ] **Randomised client MACs** (KAN-129) — document at minimum, ideally detect
      via the locally-administered bit.
- [ ] **`--color-by vlan`** (KAN-123) — needs a second visual channel decided
      first. Colour is never the only channel here, deliberately.
- [ ] **Wireless signal overlays** (KAN-124) — verify `rssi`, `channel` and band
      exist in a live `stat/sta` before designing anything. The demo dataset
      lacks them, but it is synthetic and proves nothing either way.
- [ ] **OpenBao credential backend** (KAN-128) — not blocked, despite an earlier
      note here saying so. OpenBao has been live since 2026-07-24.

### Blocked on a network nobody here has

Labelled `needs-real-world-data` in Jira. These are not waiting on effort. Until
somebody with the relevant setup turns up, work on them is guessing.
`CONTRIBUTING.md` asks for exactly this.

- [ ] **`--all-sites` and a `sites` command** (KAN-125) — one controller, one
      site, ever. Live cannot even enumerate sites today: every endpoint takes
      the site as a parameter.
- [ ] **Performance at scale** — never profiled on a large network.
      `sysid_for_name()` scanning the catalogue per candidate is the likely
      first problem.
- [ ] **Support-file limits** — all four defaults come from a single 154 MiB
      archive.
- [ ] **Other controller versions** — everything is verified against UniFi OS
      5.1.26 with Network 10.5.67.

## Undecided

- [ ] **Whether a release should produce an artifact.** Today it is a tag and a
      changelog entry. `pip install unifi-map` would mean owning the name and
      never breaking a published build, plus placing the man page in
      `share/man/man1`. A commitment rather than a chore. See `RELEASING.md`.
- [ ] **Preferences in the environment** (KAN-130) — `UNIFI_MAP_THEME` and
      friends, so somebody whose taste differs from the defaults need not retype
      them. The objection is reproducibility between machines; a config file is
      the alternative and shipping both would be worse than either.
- [ ] **Retiring the `UDM_*` environment names.** Warning is in and no removal
      version is promised, on purpose. Rename them in the maintainer's own
      credential file before deleting, or the breakage is discovered by a
      failing fetch.

## Considered and not planned

Recorded so they are not proposed again as oversights.

- **A dependency lock file.** Hashed constraints are ongoing maintenance for a
  dev-only benefit, and Dependabot plus the advisory job cover staying current.
  Revisit if this ever ships an artifact people install.
- **NetBox / IPAM export.** Subsumed by the JSON export above rather than
  refused outright: the ask was structured JSON *for importing into* NetBox, and
  once that exists a transform against our schema beats us tracking theirs. An
  export is fine; a *sync* is not, since `session.get` being the only HTTP verb
  is a headline property.
- **An `AbstractRenderer` protocol.** Two renderers exist, both already pure
  functions from `Topology` to text. A protocol over two implementations is a
  layer to maintain before it has been shown to be needed.
