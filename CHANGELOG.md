# Changelog

Notable changes, newest first. This project follows
[semantic versioning](https://semver.org/).

**Pre-1.0 means the CLI is not stable yet.** Flags and defaults may change
between minor versions while the tool settles. Once there is reason to think the
interface is right, that becomes 1.0 and breaking changes need a major bump.

The version lives in `src/unifi_map/__init__.py` and `pyproject.toml` reads it
from there, so there is only ever one number to change.

### When to bump

The version describes what a *user* would notice, not how much work happened.
Bump when releasing, not per commit: several commits usually make one version.

- **Patch** (0.2.0 to 0.2.1) for fixes and internal changes. Someone upgrading
  gets the same commands, the same flags and better behaviour.
- **Minor** (0.2.0 to 0.3.0) for anything new: a flag, an output format, a
  capability. Also, while pre-1.0, for changes that would otherwise be breaking,
  such as a renamed flag or a changed default.
- **Major** (0.x to 1.0, then 1.x to 2.0) once the interface is declared stable,
  for anything that breaks an existing invocation.

Below 1.0 the promise is deliberately weak: the leading zero says the CLI is
still settling. That is why a changed default is a minor bump here and would be
a major one later.

Refactors, docs and tests alone do not need a release at all.

## Unreleased

### Added

- `unifi-map report`, which prints a short plain-text description of the shape
  of a network: counts, fan-out, which field names the controller returns, and
  versions. Meant for a bug report or for the features that are stuck waiting on
  a network nobody here has.

  Built from an allowlist rather than by redacting: every line is a counted
  integer, a boolean, or a field name from a list written in advance. A filter
  that strips identifying values can be incomplete, and UniFi's own does exactly
  that and was observed leaving unredacted tokens in a real support file. A list
  that only ever adds cannot leak by omission.

  It asks before producing anything, printing what it does and does not collect,
  and `--yes` skips that once read. A non-interactive run without `--yes`
  refuses rather than assuming: a cron job has nobody to consent on behalf of.

  Pointed at an archive with `--support-file` it reads that directly rather
  than the cache, and adds how much there was to walk, how many entries, and
  how many sites it holds. Those are the numbers behind the support-file limits
  (set from a single archive) and the untested multi-site handling. Sites are
  counted, never named: the keys carrying those names are user-chosen.

  `CONTRIBUTING.md` asked people to gather this sort of thing by hand and now
  points at the command instead.

  Two tests hold the promise up. One renders a snapshot built entirely of
  identifying values and searches the output for every one. The other is
  stronger and matches the design: it asserts the report's whole vocabulary is
  closed, so a value arriving by a route nobody predicted fails even though no
  test knew to look for it.
- A small rendering flourish, off unless an environment variable asks for it.
  Not in `--help`, not in the README, and not described further here. It is
  emitted straight into the DOT rather than added to the topology, so it cannot
  reach counts, filtering, obfuscation or the report; a test holds that. Harmless
  and cosmetic, and findable by anyone who already knows to look.

## 0.6.0 - 2026-08-02

### Removed

- `--layout sane`, and the `make sane` target. Renamed to `tree` in 0.5.0, where
  it was deprecated with this version named in the warning, the code, the tests
  and the changelog. `--layout sane` is now an argparse error listing the valid
  choices, and `Style(layout="sane")` raises. One release of overlap was the
  whole point of promising a version rather than leaving it open-ended, which is
  still the right call for the `UDM_*` environment names.

### Added

- `TODO.md`, the planned work in one contributor-facing place, since the
  alternatives were a context file written for AI agents and a Jira instance
  needing an account. Two tests keep it honest: it may not plan work for a
  released version, and its commitment section must name the same version the
  deprecation warning tells users.
- `--transparent` draws no canvas, so a map can be dropped onto a page that
  already has a background. Covers SVG, PDF, PNG and draw.io. The theme still
  applies and still matters: with the default icon set, labels have no card
  behind them, so on a transparent canvas they land straight on the destination
  page and a light map is near-invisible on a dark one.
- Every demo screenshot is committed in both themes rather than only dark, so
  the documentation shows what the default actually produces instead of
  describing it.

### Fixed

- `RELEASING.md` actually tells you to check CI now. The previous entry claimed
  this was corrected when `gh` was installed; the changelog said so and the file
  still said CI could not be checked from here. The instruction now runs
  `gh run watch`, and says to read the per-job output because `Dependency
  advisories` is `continue-on-error` and reports success having failed inside.
- `CLAUDE.md` said the `sane` layout alias goes in 0.5.0. It goes in 0.6.0,
  which the code, the tests and the changelog all said; that one heading was
  missed when the promise moved.

### Changed

- `--site`'s help text no longer reads as though multi-site support files are
  refused outright. They are refused only when you do not say which site you
  want, which the sentence did say, twenty words earlier, in a table cell. It
  now states the requirement rather than the refusal. The README prose leads
  with the same.
- Dependabot auto-merge holds anything whose update type it cannot identify,
  rather than merging it. The condition asked "is this not a major bump", which
  treats an empty or unrecognised value as safe, so anything leaving
  `update-type` unpopulated made the step an unconditional merge. Not
  hypothetical: `fetch-metadata` resolved `update-type` to null for Python pull
  requests until v3.1.0, and Python dependencies are what this repository
  tracks. It now asks "is this a minor or patch bump", so an unknown value
  merges nothing.
- `RELEASING.md` describes the process as it now is. Three things in it were
  wrong: it said to rename `## Unreleased` away at release, which would delete
  the section `CONTRIBUTING.md` tells contributors to use; it never mentioned
  `make docs`, which is mandatory now that the man page carries the version; and
  it said CI could not be checked from here, which stopped being true when `gh`
  was installed. It also no longer counts how many times anything has happened,
  since two of those counts were wrong and none of them told a reader anything
  the sentence did not.
- A test asserts the man page header carries a real date. The date comes from
  the changelog entry for the current version, so bumping `__version__` before
  dating that section produced an empty one, and the regenerate-and-compare
  check could not see it because both sides were generated the same wrong way.

## 0.5.0 - 2026-08-02

### Deprecated

- `--layout sane` is renamed to `--layout tree`, and **`sane` will be removed in
  0.6.0**. It still works and still selects the same layout, but it is hidden
  from `--help` and warns once, naming the replacement and the version.

  The old name implied the other layout was not sane, and borrowed a clinical
  word as a judgement. `tree` describes what the layout is: top down, leaf
  staggered, with port numbers on the links.

  A version is promised here, unlike the open-ended `UDM_*` deprecation, because
  this is one flag value that anyone using it can change in seconds, and an
  indefinite alias would keep the word in `--help` indefinitely. The target is
  0.6.0 rather than 0.5.0 because 0.5.0 is the release that introduces `tree`;
  removing the old name in the same version it is deprecated would leave nobody
  a release to migrate in.

### Fixed

- A support file holding more than one site is refused until `--site` says
  which, instead of mapping whichever site had the most devices and warning.
  The old behaviour was the only place this tool guessed: an ambiguous override
  selector is a loud error, an ambiguous product name resolves to nothing, and
  an unreported uplink gets a placeholder rather than a plausible parent. It was
  also the worst place to guess, because the result is a complete and entirely
  ordinary looking map, and nothing about the diagram says it is the wrong
  network. A single-site archive still needs no flag.
- Every directory this tool creates is restricted, not only the last one.
  `--out-dir out/private/maps` created three directories and locked down one,
  leaving the other two at the umask. Output filenames come from network names,
  so a listable parent disclosed the network layout even though the files
  themselves are `0600`. An existing directory is still left exactly as it is.
- Overrides that make a loop are refused, naming the loop. Nothing crashed:
  Graphviz draws a cycle without complaint, since DOT is a digraph. It is
  refused because a switch cannot be its own uplink, so such a map asserts
  hardware that cannot exist while looking as authoritative as any other.

### Changed

- A man page, `unifi-map.1`, generated from the argument parser and committed
  so it works from a clone with `man ./unifi-map.1`. `make docs` regenerates it
  and `make check` fails when it is stale, the same guard the README flag
  reference has. It carries the sections a parser cannot supply: ENVIRONMENT,
  FILES, EXAMPLES, exit status, and the warning about support files.
- Atomic writes live in one module, `fsio.py`. Three copies had grown apart:
  two called `fsync` before the rename and one did not, and only two set the
  file mode before putting it in place. None of the differences were intended.
- `_fetch` returns a small `Fetched` object rather than a `requests.Response`
  with two private attributes assigned by hand. The body is streamed through a
  size cap rather than read by `requests`, which is why the response had to be
  doctored; callers only ever used three fields.
- The example unmanaged switch is described as "unmanaged" rather than "dumb",
  in `examples/overrides.toml` and the README. "Unmanaged" is also the accurate
  term: it names the absent management plane, which is why such a device has to
  be declared by hand in the first place.
- `make sane` is now `make tree`, and `docs/images/example-sane-dark.png` is now
  `example-tree-dark.png`. The old make target still works and says it is going.

## 0.4.1 - 2026-08-01

A code review by an external AI system, distinct from the two security audits
and the two documentation reviews. Eight findings, all reproduced and fixed.

### Fixed

- An existing output directory is no longer tightened to `0700`. `--out-dir`
  pointed at a shared directory silently took it from `0775` to `0700` and
  locked out everyone else, despite the code saying in its own comment that it
  must only restrict directories it created.
- `--per-network` no longer overwrites one diagram with another. Network names
  differing only in punctuation ("IoT A", "IoT-A", "IoT/A") produced the same
  filename, and the overwrite guard passed it because the file it replaced was
  this tool's own. Colliding names now get a short digest of the name, which is
  stable whatever order the networks arrive in.
- A support archive can no longer force unbounded decompression. Streaming tar
  reads through a member to reach the next header, so a member this tool skips
  still costs its full uncompressed size, and neither size cap measured it: a
  2 MiB archive holding 2 GiB of zeros cost 21 seconds of CPU. `--support-max-archive`
  caps total uncompressed bytes walked, skipped members included.
- A declared `[[device]]` can name a parent declared later in the file. Parents
  were resolved while devices were still being created, so it worked in one
  order only and failed as "matches nothing on the map", which reads as a typo.
- Artwork downloads are streamed and stop at the size cap rather than being
  measured after arrival, so an oversized body is never fully resident. The
  client fingerprint database had no size cap at all and now has one.
- Artwork and catalogue caches are written to a temporary file and renamed, as
  snapshots and rendered output already were, so an interrupted or concurrent
  run cannot leave a truncated file. An unreadable cached icon is now discarded
  and refetched rather than returned broken forever.
- Malformed input produces an error rather than a traceback: an unreadable
  cached snapshot, a neighbour line ending in `lladdr`, and a glyph map whose
  values are not numbers.
- The provenance check reads 4 KiB rather than reading the whole file and
  slicing 4 KiB off it.

## 0.4.0 - 2026-08-01

### Deprecated

- The `UDM_*` environment variable names. `UNIFI_*` is the supported spelling;
  the old one still works and now prints a warning naming its replacement, once
  per run rather than once per variable. No removal version is promised, since
  anything here may change before 1.0.

### Added

- The README shows the demo with the example overrides applied, so what an
  asserted device and an asserted link actually look like is visible without
  running anything. `make demo-images` regenerates every committed demo PNG,
  including a detail crop whose bounds are computed from the layout rather than
  fixed pixel coordinates, so it follows the overrides instead of silently
  framing the wrong part of the map. The two existing screenshots are refreshed
  by the same run; both predated the ISP mark on the Internet node and were
  visibly the wrong shape.
- `docs/overrides.md` and `examples/overrides.toml` document `[[device]]`,
  which they had both missed entirely despite it being implemented, tested and
  described everywhere else. Tests now tie every block the loader accepts to a
  section in the reference and an example in the template, and check that the
  template still parses.
- A flag reference at the bottom of the README, generated from the argument
  parser rather than written, so it cannot drift from `--help`. The flags are
  still explained in context where they are relevant; this is for looking one
  up. `make docs` regenerates it and a test fails if it is stale.
- `--out-dir` and `-v` have help text. They had none, so they were missing from
  `--help` output as well as from every reference.
- Clients with no reported uplink are now counted in the output, with a pointer
  to overrides as the way to place them. The "Uplink not reported by controller"
  placeholder said what had happened but never that it was fixable, so the tool
  refusing to guess looked the same as the tool failing. The README section says
  so too.
- `--site NAME` selects the site from the command line, for a live fetch as
  well as a support file. It overrides `UNIFI_SITE`, so a script can loop over
  sites without re-exporting a variable per invocation. `--support-site` still
  works and now warns; it only ever covered support files.
- A progress spinner on the three steps slow enough to look like a hang:
  reading a support archive, resolving artwork, and running Graphviz. It turns
  itself off whenever output is not a terminal, so piping, redirecting and CI
  are unaffected and need no flag; `--no-progress` covers an interactive
  terminal whose output something else is reading.
- `--support-max-entries` caps how much of a support archive is walked. It was
  already capped at 100,000; what is new is being able to change it. The two
  size caps guard memory and this one guards time, since entry count does not
  follow the bytes decoded, and all three now behave the same way.
- Raising `--support-max-entries` above the default warns that the run may take
  a while, since walking a larger archive prints nothing until it finishes when
  the spinner is disabled, and is then indistinguishable from a hang.
- `RELEASING.md` documents how a version actually goes out, written after doing
  it by hand twice rather than invented in advance. Two tests enforce the parts
  that have gone wrong: the changelog must have a section for the version the
  package reports, and no version may repeat a `### Added` style heading.

### Fixed

- Documentation corrections from an external review. Support-file mode was
  described as touching nothing, when `all` goes on to render and rendering
  fetches artwork; the README said read-only API keys were sufficient while
  `SECURITY.md` explains UniFi will not issue one; the rendering issue template
  still said overrides were unimplemented; and `--per-network` was described as
  per-VLAN when it iterates client networks, which need not have a VLAN.
- The informal register is confined to `README.md`, `AI_DISCLOSURE.md` and
  `HUMAN_INPUT.md`, and kept out of `SECURITY.md`, `docs/` and `examples/`,
  which had picked some up. The tiering is written down in `CLAUDE.md`.
- Global options are accepted after the subcommand as well as before it, so
  `unifi-map all --support-file X.tgz` works. It did not: those options were
  attached only to the top-level parser, which made every `--support-file`
  example in the README unrunnable as printed. Both forms are now supported,
  and a test parses every command the README prints.

## 0.3.0 - 2026-08-01

### Added

- `[[device]]` in an overrides file declares something no source reports: an
  unmanaged switch, a non-UniFi access point, or gear that was powered off when
  you ran the fetch. Optionally with an address, a model, your own artwork, and
  a parent and port. Declared devices can be referenced by other overrides and
  by each other.

  They are drawn as claims rather than observations, with a dotted outline and
  a dotted link, so a reader can tell which parts of a diagram the controller
  reported and which parts somebody typed in.

- The demo dataset ships an example overrides file exercising every block, and
  `make demo-overrides` renders it. A test keeps it applying cleanly, since an
  example that has silently stopped matching is worse than none.

- The Internet node now shows the upstream provider's brand mark, matched on the
  ASN the controller already reports beside the ISP name. Providers Ubiquiti have
  no mark for, and any map rendered with `--obfuscate`, get a plain cloud
  instead of a bare polygon.

### Changed

- `--obfuscate` now covers ordinary log output as well as the diagram. Hidden
  node names were logged in full, so a scrubbed render could sit beside a
  terminal or CI log naming real devices. `-v` still names them, which is what
  it is for, and the README says so.
- Support-file size limits are tunable with `--support-max-member` and
  `--support-max-total`, and the defaults drop from 256M/512M to 64M/128M. The
  old values were large enough to be no real limit; the new ones are about 160x
  the largest member observed in a real archive, and a genuinely large site can
  raise them rather than being refused.
- Snapshots and rendered output are created mode `0600`, with the mode set
  before the file is put in place rather than after, and directories this tool
  creates are `0700`. Snapshots were previously chmodded after writing, leaving
  a window at whatever the umask allowed.

- `SECURITY.md` no longer says "Nothing is uploaded anywhere" about artwork
  fetching. No body is sent, but the URLs carry `sysid`, `dev_id` and `asn`,
  which together disclose a partial hardware inventory to Ubiquiti's CDN. The
  section now says what is actually revealed and what is not.
- CI actions are pinned to commit SHAs rather than mutable tags, Dependabot
  keeps them and the Python dependencies moving, and a non-gating `pip-audit`
  job reports advisories. Dependabot's own pull requests merge themselves once
  the required checks pass, except major version bumps, which stay manual.

- `--obfuscate` also drops the ASN. It identifies the provider as squarely as
  the name does, and would otherwise redraw their logo on a map whose purpose is
  being safe to publish.

### Fixed

- A crafted support file can no longer decide what topology you see. Archive
  members were matched on a trailing path fragment, so an added
  `evil/unifi/devices.json` matched the same fragment as the real
  `unifi/devices.json` and, placed earlier in the stream, won. Matching is now
  anchored to exactly one leading directory component. Reproduced before the
  fix and after it.
- Artwork responses are size-capped, on the declared length and again on what
  actually arrives, and Pillow's decompression-bomb threshold is tightened from
  its default to something appropriate for icons.
- An API key is no longer visible to Graphviz or any other child process. It is
  never written into the process environment, and the environment passed to
  child processes has the key variables removed in case one was exported. Both
  Graphviz executables are now run by resolved absolute path rather than by
  name.
- draw.io labels are HTML-escaped. Every cell sets `html=1`, and draw.io decodes
  the XML attribute and then parses the result as HTML, so a device named
  `<img src=x onerror=...>` previously arrived as an element rather than as
  text. Device names are set by whoever named the device.
- The documented way to create a credential file is now `install -m 600` rather
  than `cp`, which inherited the umask and usually left an API key
  world-readable. `unifi-map` now warns when it reads one others can see.
- A real Ubiquiti device MAC in the test fixtures was replaced with a
  locally administered one.
- Rendering no longer overwrites a `.dot` or `.drawio` that this tool did not
  write. A hand-edited diagram is left alone, with `--force` to override.
  Re-rendering output it recognises as its own is unchanged and needs no flag.
- Output files are written atomically, so an interrupted or failed render leaves
  the previous file intact rather than a truncated one.
- The API key is no longer sent on if a redirect points at a different host.
  `requests` does this for `Authorization` and nothing else, and ours is a
  custom header. It mattered because `UNIFI_VERIFY_TLS=false` is documented as
  the ordinary setting for a bare IP, so with verification off anyone in the
  path could have redirected the tool and collected a working admin key.
  Redirects themselves still work, including on a reverse proxy.

## 0.2.0 - 2026-07-30

### Added

- `--support-file` reads the topology from a UniFi support file archive instead
  of a controller. It needs no credentials and no network access, which makes it
  a safe way to share a real topology when reporting a bug. **That claim was
  wrong and is corrected in later releases: a support file is highly
  sensitive and must not be shared. See `SECURITY.md`.** Add `--support-site`
  to pick a site from a multi-site archive.

  Against a live fetch of the same network it produced identical infrastructure
  and an identical wireless client count. VLAN names, subnets, switch port
  numbers, SSIDs, client addresses, the ISP name and Protect camera artwork all
  survive.

  Reading a support file makes no outbound request at all.

- `--icon-font DIR` loads the generic client glyph font from a copy you made
  yourself, needing neither credentials nor a network. `--fetch-icon-font` gets
  it from a controller instead, which does need an API key and says so. Without
  either, unidentified clients draw as plain shapes. Ubiquiti publish no copy of
  this font, so there is no route to it that avoids a controller, and it is not
  shipped here.

  Some client artwork is recoverable, opt-in via `--fetch-fingerprints`, but
  expect substantially less of it than a live fetch gives: 13 of 47 clients
  against 42 of 48 on the same network. A support file stores no fingerprint id.
  What can be reconstructed is the subset the console named *itself*, after the
  product it identified, since that name can be looked back up against
  Ubiquiti's published fingerprint database. The console only names a client
  that way when it sent no DHCP hostname and was never renamed, which is a
  minority. The database is about 1 MB, downloaded only when the flag is given,
  then cached.

- Manual overrides are now applied, not just parsed. `--overrides` (or an
  `overrides.toml` in the working directory) can add links the controller cannot
  see, declare that one node runs inside another, rename a device, supply your
  own artwork, and hide a node entirely.
- Asserted links are drawn dotted in both SVG and draw.io, and the legend gains
  a "Stated in overrides" entry, so a claim is never mistaken for an observation.
- `--version`.

### Fixed

- Artwork supplied through an override is now embedded in the SVG. It was being
  left as a filesystem path, which both broke portability and disclosed a local
  path, usually containing a username, even under `--obfuscate`.

- Clients behind a non-UniFi device are now placed correctly instead of being
  collected under "Uplink not reported by controller". `stat/sta` only reports an
  uplink when it is a UniFi device, so VMs and containers behind a NAS, or
  clients on an unmanaged switch, appeared unplaced. The controller's own
  topology graph knows where they are, and the console has been drawing them
  correctly all along. On the network this was found on, that node disappeared
  entirely.

## 0.1.0

First versioned release. The tool was already public and working before this
point; the version simply starts being tracked here.

### Output

- SVG and PDF, vector, so labels stay sharp at any zoom. Artwork is embedded in
  the SVG so it is a single portable file.
- `.drawio` with real editable shapes, positioned using Graphviz's layout.
  Confirmed working in draw.io.
- PNG, and Graphviz `.dot` for hand tweaking.
- Optional per-network diagrams, each keeping the full gateway, switch and access
  point skeleton so they read as slices of one map.

### Artwork

- UniFi hardware drawn with its real product artwork, matched on hardware
  `sysid` against Ubiquiti's device catalogue.
- Clients drawn with their real product artwork, matched on the fingerprint
  `dev_id` the controller already reports.
- UniFi hardware that appears as a client, such as a Protect camera on a switch
  port, matched by hostname against the hardware catalogue, disambiguated by
  asking Protect what the device actually is.
- Anything unrecognised falls back to the controller's own icon font glyph, the
  same fallback the UniFi interface uses.
- No artwork is vendored. It is fetched at runtime and cached, and
  `--icons builtin` needs no network at all.

### Presentation

- Two layouts. `unifi` approximates the console view; `sane` is top down with
  leaf nodes staggered and port numbers on the links.
- Light and dark themes.
- Okabe-Ito accent palette, with every distinction also carried by artwork, shape
  or line style so the output survives greyscale and red-green colour blindness.
- A legend that describes only what a given render actually encodes.

### Privacy

- `--obfuscate` replaces hostnames, addresses, MAC addresses, network and VLAN
  names, SSIDs, the ISP name and the WAN address, while keeping the connections,
  roles, artwork and port numbers that make a diagram worth discussing.

### Behaviour

- `--show-offline` defaults to `no`, because a controller remembers hardware long
  after it leaves the rack and the interface offers no way to hide it.
- Clients whose uplink the controller does not report are anchored to an explicit
  placeholder rather than left floating or attached to a guessed parent.
- The Internet node is labelled with the ISP name the controller reports.
- `fetch` and `render` are separate, so styling can be iterated without querying
  the controller again.

### Other

- Authenticates with an API key. The tool only ever reads; `session.get` is the
  only HTTP verb in the source.
- A synthetic demo dataset, so the output can be seen without pointing the tool
  at real infrastructure.
- Manual overrides: schema and loader only. Applying them is not implemented yet.
