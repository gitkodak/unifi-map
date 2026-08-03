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

### One change, one entry

An entry describes a change, not the commits that made it. Work spread over a
day arrives as several commits and belongs in the changelog once, written from
where it ended up rather than in the order it was fixed. Four overlapping
entries about one restructure is a commit log, and a reader has to assemble the
story themselves.

Say what it means for somebody else, not only what was done. A restructure that
moves every anchor needs the table of old address to new far more than it needs
the reasoning, however good the reasoning was.

### What counts as a fix

`### Fixed` is for something a user could have hit. A defect found and corrected
before its feature ever shipped was never a bug from outside, so it belongs in
the `### Added` entry for that feature rather than listed separately: somebody
scanning to see whether their problem is solved should not have to read about
problems that never reached them.

Corrections to `CLAUDE.md`, `TODO.md` or the Jira tickets are not changelog
entries either. They are working notes. Corrections to `README.md`,
`SECURITY.md`, `CONTRIBUTING.md` or `RELEASING.md` are, because somebody was
told something untrue and may have acted on it.

## Unreleased

### Fixed

- **The permission repair for pre-0.9.0 SVG caches no longer follows symlinks.**
  It restores private modes to rasters an earlier build left world-readable, and
  did so through `Path.chmod()`, which follows links: a symlink planted at
  `user-svg/` or at one of its cached PNGs redirected the change onto whatever
  it pointed at. Nothing was disclosed, since access was removed rather than
  granted, but an unrelated path could lose group or world access, and in a
  cache directory writable by somebody else that is a local denial-of-service
  primitive.

  Now done through a descriptor opened `O_NOFOLLOW`, so a link fails the open
  outright and the mode is applied to the thing that was inspected rather than
  to whatever the name resolves to a moment later.

## 0.9.0 - 2026-08-03

### Added

- **An `svg` extra, for your own SVG override artwork.** `pip install
  'unifi-map[svg]'` rasterises a supplied SVG to a cached PNG as it is read, so
  it reaches every output format.

  Without it, Graphviz loads SVG artwork only for its own `svg` driver: `png`
  and `pdf` go through cairo, which has no SVG loader, so the icon is dropped
  from both. It also insists on an XML declaration and reports a file that
  plainly exists as missing when there is none. Rasterising sidesteps both, so
  a file exported by a drawing tool works untouched.

  **Optional on purpose**, and converting the file to PNG yourself does the
  same job with no dependency at all. Both routes are documented; the tool
  warns and names the file when an SVG is about to go missing from a format.
  Fetched artwork is unaffected: it is already PNG.

- **A warning when an SVG override will not reach `png` or `pdf`**, naming the
  icons and the formats that will lack them. Graphviz's own message is `No
  loadimage plugin for "svg:cairo"`, which names neither the file nor a way
  forward.

- **A warning when `--theme dark` is combined with `drawio`.** draw.io
  re-themes on load and will render a dark-authored file light. See *Known
  limitations* below.

- **`make build`**, producing a wheel and an sdist in `dist/`. Installing the
  wheel into a clean environment gives you a working `unifi-map` without a
  checkout, which is useful for putting it on a machine that should not carry
  the source.

  It needed almost no new machinery: the entry point and the build backend were
  already in `pyproject.toml`. What was missing was a documented way to invoke
  them, and `dist/` and `build/` in `.gitignore` so the artifacts cannot be
  swept into a commit.

  **This is not a published package and does not promise one.** There is no
  `pip install unifi-map` from PyPI, and whether there ever should be is
  deliberately still an open question, recorded in `TODO.md`. Building an
  artifact and publishing one are separate decisions, and only the second is a
  commitment that cannot be withdrawn.

- **`UNIFI_CACHE_DIR`, `UNIFI_ASSET_CACHE` and `UNIFI_OUT_DIR`**, so the
  directories can be set once instead of passed on every command. A flag still
  wins over the variable, and the variable over the default. They can go in the
  credential file as well as the environment, which is the natural place, since
  that file is already the thing kept outside the project.

  The cache one is the point. A snapshot is a complete inventory of a network,
  the default puts it in the working directory, and for anyone working on this
  tool that directory is a git checkout. A `cache.bak` copy made before a risky
  fetch is not covered by a `.gitignore` entry for `cache/`; one sat untracked
  in this repository, one `git add -A` from being published. The ignore rule was
  widened in 0.8.0, and this removes the question rather than guarding it.

### Removed

- **The `UDM_*` environment variable names.** `UDM_HOST`, `UDM_API_KEY`,
  `UDM_SITE` and `UDM_VERIFY_TLS` are no longer read. They existed only because
  that is what the author had called things before this tool did, and they have
  warned since 0.7.0.

  **If you still use them, rename them to the `UNIFI_*` spellings.** Nothing
  subtle happens if you do not: the tool reports the missing variable by name
  and exits, exactly as on a fresh install. `UDM_USER` and `UDM_PASS` were
  already dead, unread since password authentication was removed, and are worth
  deleting from any credential file that still carries them.

  One deliberate asymmetry: `layout.py` still strips `UDM_API_KEY` from the
  environment Graphviz runs with. We stopped *reading* it, which does nothing
  about somebody who still exports one, and an unread variable holding a real
  key is exactly as worth withholding from a child process as a read one.

### Changed

- **Graphviz's warnings are no longer discarded.** Graphviz warns on stderr and
  still exits 0, and that output was thrown away on every successful run, so
  every warning it has ever emitted was invisible. That is how an icon could
  vanish from a PNG in silence. Surfaced whole rather than filtered: deciding
  which of its messages matter is how the last one stayed hidden.

- **Artwork resolution and output writing moved out of `cli.py`**, into
  `artwork.py` and `output.py`. No behaviour changes. The reason is layering
  rather than length: neither is a command-line concern, and the tell was a
  rendering test having to import a private function from `unifi_map.cli` to
  exercise the renderer. `cli.py` keeps argument parsing, credential resolution,
  logging setup and the `cmd_*` functions that sequence a run, and drops from
  1367 lines to 1027.

  Only relevant to you if you import from `unifi_map.cli` directly, which is not
  a supported interface and which nothing is known to do.

### Fixed

- **A repeated `-f` is refused instead of silently honouring the last one.**
  `-f` takes several values, so `-f svg -f png` overwrote rather than appended
  and wrote png only, with nothing said. That reads as a format that failed to
  render. Pass them together: `-f svg pdf png`.

  Refused rather than made to append, because an error states what happened
  whereas appending would quietly change what an existing invocation produces.
  **If you have a script using the repeated form, it will now stop with an
  error naming the fix.**

- **draw.io connection lines no longer run through unrelated devices.** The
  edges carried only their two endpoints, so draw.io routed them with its own
  router and drew a long run straight through whatever the layout had placed in
  between. Graphviz had already computed a route and it was being discarded;
  those waypoints are now written into the file. Safe to pass through unchanged
  because both layouts use `ortho` or `polyline` splines, never a bezier, so the
  reported points are corners rather than control points.

- **draw.io node captions no longer land on the node below.** The label was
  positioned outside the cell, while Graphviz had sized that cell to hold the
  artwork *and* the text. The box carried dead space and the caption fell onto
  whatever was underneath, so on a dense column every icon wore its neighbour's
  caption. The label now renders inside the box the layout was computed for.

- **An SVG with only a `viewBox` is accepted.** Explicit `width` and `height`
  were required, and most drawing tools export a viewBox instead. Graphviz
  renders those perfectly well and preserves the ratio, checked by rendering
  both through `dot` rather than by reading a spec. Only the ratio is used
  downstream. Explicit dimensions still win where a file has both.

- **A refused icon says which rule it broke.** "Could not read artwork at
  `<path>`" on a file the reader can plainly open is a shrug rather than an
  error, and SVG has requirements that are not guessable from the outside.

- **The README implied you could run `unifi-map` before installing it.** The
  quick-look section ran `make demo` and then `unifi-map all`, as though the
  first had prepared an environment for the second. It had not: `make demo`
  calls the venv's copy by full path and puts nothing on your `PATH`.

- **Nothing anywhere told you to activate the virtual environment.** Install
  ended at `.venv/bin/pip install -e .`, which puts the command at
  `.venv/bin/unifi-map` and nowhere else, while the README and every page under
  `docs/` invoked a bare `unifi-map`. Anyone following the instructions
  literally got `command not found` on their first real command. Install now
  ends with `source .venv/bin/activate` and says why, which makes those examples
  correct rather than editing each of them.

- **`all` now says what it means.** It is `fetch` then `render`, both stages,
  and reads to a newcomer as "all output formats". It writes the same default
  two files any `render` would. The help text says so and `docs/usage.md` has
  the incantation for the other five.

- **Documentation said Lucid's `.drawio` import had not been tried. It has, and
  it does not work.** Lucid reads one cell of the file and stops, a different
  cell each time. Neither stripping the embedded artwork nor writing the payload
  in draw.io's own compressed form changes it, so it is not a size or an
  encoding problem. `docs/output.md` now says so and points at the workarounds,
  which are to export from draw.io or to import the `svg` or `pdf` output.
  draw.io itself remains confirmed working. Nothing about the generated file is
  being reshaped to suit a second tool's parser.

### Known limitations

- **`--theme dark` does not survive into a `.drawio` file.** draw.io re-themes
  a diagram on load, inverting it to contrast with its own appearance setting,
  because its dark mode assumes diagrams are authored light. A file authored
  dark is inverted a second time and displays light; a file authored light is
  correct in both of draw.io's modes.

  Nothing is corrupted when this happens. The inversion is holistic, so cells,
  text and artwork flip together and the file stays coherent; it simply reads as
  the theme you did not ask for.

  **For now the tool warns and renders what you asked for.** Use `--theme light`
  for the `.drawio`, or set the appearance in draw.io explicitly rather than
  leaving it on Automatic. `docs/output.md` covers both.

  **When this is fixed, the behaviour will be:**

  - It will **always warn** when `drawio` is among the requested formats and the
    theme is dark, because the interaction is worth knowing about either way.
  - With **other formats alongside**, the `.drawio` will be authored **light**,
    so it displays dark like everything else in the run.
  - With **only `drawio`** requested (`--theme dark -f drawio`), it will be
    authored **dark** as asked, with a warning that draw.io may not display it
    the way you expect and a pointer to the documentation. Asking for one format
    and that format alone is a clear enough instruction to honour.

## 0.8.0 - 2026-08-02

**If you keep an overrides file, read this before upgrading.** A file
containing `wireless = "false"`, `hide = "false"`, a fractional `port`, or a
misspelled key used to render; it now stops the run with an error naming the
problem. Those files were never doing what they said, which is why this changed,
but the failure is new and it is at the point of use. The fix in every case is
in the error message.

### Changed

- **The documentation is split into `docs/`, and links into the README have
  moved.** It had reached 1233 lines, which is past the point anybody reads,
  and is now 220: what the tool is, what it produces, how to install it, and
  how to see a map without touching your network. Everything else is a page of
  its own, indexed from the README.

  **If you linked to a README anchor, it has moved.** Every `#section` that is
  now a page is a different address:

  | Was | Now |
  | --- | --- |
  | `README.md#usage`, `#reading-the-diagram`, `#flag-reference` | `docs/usage.md` |
  | `README.md#credentials`, `#unifi_api_key` | `docs/credentials.md` |
  | `README.md#mapping-from-a-support-file` | `docs/support-files.md` |
  | `README.md#json-for-programs`, `#mermaid-for-documentation` | `docs/output.md` |
  | `README.md#sharing-a-map---obfuscate` | `docs/sharing.md` |
  | `README.md#artwork-licensing-and-attribution` | `docs/artwork.md` |
  | `README.md#how-it-works`, `#caveats` | `docs/verification.md` |
  | `README.md#manual-overrides` | `docs/overrides.md`, which already existed |

  Pages are organised by why somebody opens them rather than by what they are
  about, and each was then checked against what its own opening sentence
  promises. That found the artwork page describing where pictures come from with
  the answer two files away, the output page covering two formats of seven, and
  three pages repeating their own title as their first section. All were the
  same artefact: splitting on top-level headings moves text correctly and lands
  it by accident.

  The README's `## Manual overrides` and `## Also planned` sections are gone
  rather than moved, because `docs/overrides.md` and `TODO.md` already held the
  same material and the README was carrying second copies to drift against.

  The guards were widened before the split rather than after. Every link used to
  be a same-file `#anchor`; most are now `docs/artwork.md#something`, which can
  fail two ways a browser renders happily: the file may be missing, or present
  without the heading. The link check now resolves cross-file targets, the flag
  and command checks read every document rather than the README alone, and the
  generated flag reference lives in `docs/usage.md`. It caught fourteen links
  the split broke silently.

- The documentation says which UniFi applications this has been run against,
  in the introduction rather than buried: Network for everything, and one
  Protect endpoint read purely to tell a camera from an Access reader. Devices
  from Access, Talk or a UNAS already draw, since they are clients or UniFi
  hardware like anything else, so the gap is narrower than "unsupported": what
  is missing is the second source that would let an ambiguous match resolve.
  `CONTRIBUTING.md` asks for those environments alongside the other things
  nobody here has.
- Two released sections described one change twice. 0.7.0 had two entries for
  `unifi-map shape`, written days apart; 0.6.0 had two for `RELEASING.md` that
  contradicted each other, one saying a fix had been claimed and never made and
  the other making that same claim. Both are merged. A test now fails when a
  release describes the same subject twice, with genuinely separate changes to
  one thing listed as exceptions rather than the rule loosened.
- The artwork page lists user-supplied artwork among its sources. An `icon` in
  an overrides file is where a picture comes from when none of Ubiquiti's
  catalogues has one, and it is the only source that works under `--offline`.
- **Both generated references were wrong in the same two ways, and neither
  staleness check could have noticed.** `docs/usage.md` and the man page each
  printed a synopsis reading `{fetch,render,all}`, two commands behind, and the
  man page listed only those three under `COMMANDS`. Neither said that
  `unifi-map overrides` requires a `check` argument, because the introspection
  walked `option_strings` and a positional has none. All three lists are now
  derived from the parser.

  The two existing checks regenerate the file and fail on a diff, which catches
  an author who forgot to run `make docs` and cannot catch a generator holding a
  hardcoded list: it produces the same wrong file every time and compares equal
  to itself forever. A separate test now asserts that both documents name every
  subcommand and every positional. A document claiming it cannot drift from
  `--help` is worse than a hand-written one when it does, so the claim is tested
  rather than trusted.

- **`overrides check` now validates against the same topology `render` will
  build.** It passed `include_offline=True` unconditionally, which is more
  permissive than the default render, so a selector naming a device the
  controller merely remembers passed the check and then failed the render it had
  just been checked for. That is the one outcome the command exists to prevent.
  `--show-offline` is now shared between the two subcommands rather than
  belonging to `render` alone.
- **An override that displaces a link the controller reported now says so.**
  `[[link]]` and `[[hosted]]` both detach a node from its current parent before
  attaching the stated one, which is necessary and, for `[[hosted]]`, the entire
  point: reparenting a VM under its hypervisor displaces a real observation by
  design. But the code assumed the displaced edge was always the "uplink not
  reported" placeholder, and nothing enforced that, so contradicting the
  controller was silent. It warns now, naming both ends. Tidying the placeholder
  stays quiet, since warning on the documented case is how a warning stops being
  read.
- The runtime hint about unplaceable clients pointed at "Manual overrides in the
  README", a section the documentation split moved to `docs/overrides.md`.
- **The man page omitted exit code 3** (Graphviz not installed), and its
  description listed neither Mermaid nor JSON among the output formats.
- Several documented behaviours did not match the code, all found by an external
  review reading the split documentation against the source. Each is a fix to
  the document except where noted:
  - `docs/output.md` said nothing is ever written to stdout; `unifi-map shape`
    writes its report there, which is what makes it pipeable.
  - It listed `dot` among the formats needing Graphviz. `dot`, `mermaid` and
    `json` are all written directly and work without it; only `svg`, `pdf` and
    `png` need it. Verified by rendering with an empty `PATH`.
  - Its JSON example named version 0.6.0 and omitted `title` and `networks`,
    the latter promised two paragraphs above it.
  - Its Mermaid example claimed to be the shipped demo while showing a direction
    and header no documented command produced. The example is now byte-identical
    to `--layout tree` output, with the one edit stated.
  - `docs/overrides.md` called `[[device]].kind` required; it defaults to
    `unknown`. It also never documented what `note` does, which differs per
    block: an edge label for `[[link]]` and `[[hosted]]`, nothing at all for
    `[[device]]` and `[[node]]`. And it did not mention `overrides check`.
  - `docs/usage.md` said `fetch` downloads the icon font only when missing; it
    replaces any cached copy every time.
  - `docs/support-files.md` said omitting `--fetch-fingerprints` leaves clients
    without product artwork. The flag governs the download, not the lookup: a
    database already cached is read either way.
  - `docs/verification.md` said "all five output formats" when there are seven,
    and ended with a `BEGIN GENERATED FLAGS` marker that had no `END` and no
    content, left behind when the split moved the flag reference to
    `docs/usage.md`.
  - `.env.example` pointed at a Credentials section of the README that is now
    `docs/credentials.md`.
  - The README said Access readers, Talk phones and a UNAS "all still appear".
    `docs/verification.md` correctly calls the UNAS case inference, none of the
    three having been seen here, and the README now matches it.
- **Support-file operational guidance was on the artwork page.** Site selection,
  the four archive limits, the compression-bomb defence and the slow-walk
  warning all sat inside a section about client icons, while
  `docs/support-files.md` covered none of them. Moved, and site selection and
  limits now come before the artwork asides, since a multi-site archive stops
  the run before artwork is reached.
- `CLAUDE.md` proposed the JSON export, `overrides check` and the Mermaid export
  as future work, all three having shipped, and still described removing the
  `sane` layout alias in 0.6.0, which 0.6.0 did. The entries are rewritten to
  keep the constraints that still bind rather than deleted. The issue template
  for feature requests pointed contributors at that file's planned-work section,
  naming two shipped features; it points at `TODO.md`, which exists precisely
  because `CLAUDE.md` is written for agents.

- **Two defects in the override-displacement warning added earlier in this same
  unreleased cycle**, both found by an external review before either reached a
  release:
  - It leaked under `--obfuscate`. Overrides are applied before obfuscation, so
    an ordinary obfuscated render logged the node's real label, its old parent's
    real label and the selector, contradicting the promise that log output is
    scrubbed too. The scrubbed diagram was the whole point, and a terminal
    beside it naming the nodes defeats it. Displacements are now carried out on
    `ApplyResult` for the caller to report, exactly as hidden nodes already
    were, so the policy sits with the code that knows about the flag. Under
    `--obfuscate` the warning survives as a count with no names.
  - It could call an asserted link controller-reported. Only the "uplink not
    reported" placeholder was excluded, so when two overrides reparented the
    same node, the second warning described the first override's own link as
    something the controller had reported: the exact misattribution the warning
    exists to prevent.
- **The documentation no longer counts its own external reviews.** `README.md`,
  `SECURITY.md` and `AI_DISCLOSURE.md` each claimed a specific number of
  independent AI reviews, plus a total number of findings and a per-review
  breakdown. Reviews happen whenever a substantial change lands, so every one of
  those numbers was stale within days of being written and three files had to be
  edited in step to keep them honest. They now describe the practice: security,
  documentation, code and architectural review, more than one of each, by more
  than one system. Nothing else about the claim changed, including that every
  pass so far has found something its predecessors missed and that one finding
  stands declined with its reason recorded.

  While removing them, `AI_DISCLOSURE.md` said two findings were declined and
  later done anyway where `SECURITY.md` and `CLAUDE.md` both say one. Corrected
  to one, and it now names which.
- The overrides guide said the displaced-link warning names both ends. It does,
  except under `--obfuscate`, where the fix above deliberately reduces it to a
  count. The exception is now stated where the guarantee is.
- `--support-max-archive` was the one cap whose error did not name the flag that
  raises it, which is the worst of the four to omit it from, since it is the one
  a legitimately large site is most likely to hit. Now tested for all four.
- Smaller documentation corrections: the support-file page called its four
  adjustable limits "three" twice; the overrides page said three of the four
  block types accept `note` when all four do; the JSON example said everything
  but `nodes` and `edges` was complete while abridging `networks` too; the
  README said Graphviz was required outright, when `dot`, `mermaid` and `json`
  need nothing installed; and three cross-references still pointed at README
  sections the split had moved (`CLAUDE.md`, the `--icon-font` help text, and
  the pull request checklist).

- **A misspelled section name was ignored entirely.** Keys inside a block were
  checked and the block names were not, so `[[lnik]]` parsed, matched nothing,
  and the run reported "applies cleanly" with zero links: a file whose every
  line was ignored, reported as a success. Writing `[link]` instead of
  `[[link]]` is refused too, since TOML accepts it as a table and this file
  wants a list of them.
- **An SVG icon took its size from whatever was drawn inside it.** Dimensions
  were read from the first 4 KiB rather than from the `<svg>` element, so a
  64x32 drawing containing `<rect width="7" height="5"/>` measured as 7x5 and
  rendered at a twelfth of its size.
- **An overrides file could mean the opposite of what it said.** `wireless =
  "false"` and `hide = "false"` both read as true, because `bool("false")` is
  true and TOML has real booleans that are easy to quote by accident. `port =
  true` became port 1, since `bool` subclasses `int`. `port = 1.9` became port
  1. And a misspelled key such as `wirless` was accepted and ignored, so the
  link simply stayed solid with nothing said. All four now stop the run, and the
  unknown-key error lists what the block does accept. This is the rule the
  feature already claimed: a stale or mistyped override fails loudly rather than
  quietly doing something else.

  **This will stop a run that used to work**, for anyone whose file contains one
  of those. That is the point rather than a side effect: a map drawn from a file
  meaning the opposite of what it says is worse than a run that stops and says
  where. Every message names the block, the key and what was expected.
- **SVG artwork was accepted and then broke the render.** Graphviz refuses an
  SVG with no XML declaration, reporting it as a file that "was not found",
  which fails the whole run; measuring it here and letting it through turned a
  bad icon into a bad map. The accepted subset is now what Graphviz will
  actually load, verified by rendering one rather than by reading a spec, and
  `width="."` no longer raises while `width="0.5"` no longer becomes a 0x0 icon
  drawn as nothing.
- **Downloaded artwork bypassed the pixel cap.** The guard was added to the path
  that measures files already on disk and not to the one that decodes bytes off
  the network, which is the path that matters most.
- **An icon whose path contains `&` was left in the output as a path.** Graphviz
  writes it into an XML attribute, so it arrives as `&amp;` and never matched
  the permitted set, defeating the inlining that exists to keep local paths out
  of a file meant for sharing.
- **`unifi-map shape` could print the values it promises never to print.**
  Unrecognised keys were named, filtered to "schema-shaped" tokens on the
  reasoning that a field name is controller schema worth seeing on an unfamiliar
  version. That filter accepted `10.0.0.5`, `nas`, `secretssid` and
  `branch-office`, because a short lowercase token is exactly what an address, a
  hostname, an SSID and a site name look like, so a payload keyed by any of them
  was reproduced under a heading stating that could not happen. Unrecognised
  keys are now counted and never named. That loses the discovery of new field
  names, which was half the reason to run it elsewhere; a document claiming to
  be publishable has to be publishable first.
- **`--obfuscate` left real network names and ids in the JSON export.** Aliases
  were built from the networks nodes referenced, so a configured network with no
  active clients was missed and kept its real name, and every network kept its
  real controller id regardless. The leakage test excluded JSON and Mermaid
  despite being named for every output format; it now covers both, and the
  fixture carries an unused network with an identifying name.
- **A fresh install could not fetch the hardware catalogue at all.** `_fetch`
  returns a small `Fetched` object rather than a `requests.Response`, and the
  catalogue loader called `.json()` on it, which does not exist. The resulting
  `AttributeError` was not caught by the surrounding handler, so the very first
  render on a machine with an empty cache and a reachable CDN crashed. Every
  test either seeded the cache or simulated a network failure, so the ordinary
  success path was the one thing never exercised; it is now.
- **`--obfuscate` erased the difference between an asserted link and an observed
  one.** Edges are rebuilt field by field during obfuscation and `asserted` was
  not carried, so a link stated in an overrides file came out drawn exactly like
  one the controller reported. That distinction is the project's central promise
  and `--obfuscate` is the mode where a reader is least able to check it. A test
  now walks the dataclass, so a field added to `Edge` or `Network` fails until it
  is either carried through obfuscation or deliberately exempted.
- **A cached snapshot could mix two fetches.** `write()` only wrote the payloads
  it had while `read()` loads every recognised file present, so an endpoint that
  succeeded once and failed later left its old file to be read beside fresh
  data. Switching one cache directory between a live fetch and a support file
  did the same. A snapshot is now a complete generation: recognised files absent
  from the new fetch are removed, and nothing else in the directory is touched.
- **The diagram's own subtitle counted the wrong things.** It was computed
  before overrides were applied, so a map that declared devices or hid nodes
  stated the pre-override totals underneath itself.
- **An override could not be trusted to catch every loop.** The cycle check kept
  one parent per node and followed only that, which is exact for the graphs this
  tool builds today but is a property of its callers rather than of the check. A
  cycle reachable only through a second parent went undetected. Now a full
  depth-first search, iterative so a malformed graph cannot exhaust the stack.
- **A user-supplied SVG or JPEG icon left an absolute path in the output.** The
  SVG post-pass inlined only `.png`, so other formats stayed as filesystem
  references, disclosing a local path (usually containing a username) in a file
  whose purpose is to be shared. draw.io export had the matching bug from the
  other side, labelling every icon `image/png` whatever it was.
- **The image size cap was not a cap.** Pillow warns at `MAX_IMAGE_PIXELS` and
  only raises at roughly twice it, so an image up to double the limit decoded
  anyway, and neither exception it raises derives from those being caught. The
  guard is now scoped to each operation with `catch_warnings` rather than
  changing the whole process's warning filters, and covers `_measure`, which
  every cached and user-supplied image passes through.
- **SVG artwork in an overrides file never worked**, though it is documented as
  working: measuring went through Pillow, which does not decode SVG, so every
  SVG was refused before Graphviz saw it. Dimensions are now read from the file,
  by regex rather than an XML parser, since this is a file somebody else may
  have written. An SVG with only a `viewBox` is still refused, because Graphviz
  ignores those silently and a named error beats a blank node.
- Mermaid identifiers deleted punctuation rather than replacing it, so
  `asserted-a-b` and `asserted-ab` became the same node. Labels and titles now
  also survive a newline, which previously ended the statement carrying them and
  let the rest of a device name be read as Mermaid source.
- `unifi-map shape` counted configured networks as "client networks", including
  ones no client is on, and reported every field of the topology graph as absent
  because that payload is a single object rather than a list of records.
- Smaller: a size argument that overflows a float is now a clean error rather
  than a traceback, `--support-max-entries` refuses zero and negatives, private
  directories are created private rather than tightened a moment later, and
  `Network` carries `is_guest`, which the JSON export had been trying to read
  through a `getattr` that could never succeed.

### Added

- **Nine device icons, drawn by this project rather than fetched.** Ubiquiti's
  artwork covers their hardware and the clients their fingerprint database
  recognises; everything else fell through to a bare Graphviz primitive, so an
  access point was a trapezium and an unplaceable client was a diamond.

  Five are infrastructure, keyed on the device's role. Four are clients, split on
  guest and wireless, which is the same four-way split the console's own icon
  font encodes. **Those four close a gap with no other answer**: that font is
  served only by a controller and is absent from a support file, so mapping an
  archive without touching a console left unidentified clients as shapes. It no
  longer does, which removes the last reason a support-file user needs a
  controller.

  They appear in two places. `--icons builtin` no longer means "no artwork"; it
  means artwork that is ours, the Internet cloud included, and produces a
  complete map with no network access at all. And inside `--icons unifi` they
  are the fallback for hardware absent from Ubiquiti's catalogue, which is a
  small, deliberate step away from "`unifi` shows exactly what the console
  shows": on the shipped demo it changes exactly one node. Devices the catalogue
  covers are untouched.

  One defect found before any of this shipped, recorded because it is the kind
  that hides: `render_dot` discarded the resolved icons entirely unless the icon
  set was `unifi`, a leftover from when `builtin` meant no artwork existed. The
  icons drew correctly and never reached the map. The same gate had been
  silently dropping icons supplied through an overrides file, which are not
  fetched from anywhere either, so that is fixed too.

  Nine places across the README, four pages under `docs/` and `SECURITY.md` still
  promised "plain shapes" or "geometric shapes" for `--icons builtin` and for
  unidentified clients. All now describe what happens. Two related corrections
  came out of the same sweep: the artwork page presented one precedence order
  when the implementation has three (infrastructure, clients and the Internet
  node resolve by different code, and the ISP brand mark was missing from the
  table entirely), and the transparency note said `builtin` nodes keep a filled
  background of their own, which stopped being true when the fallback shapes
  became transparent PNGs.

  Drawn with Pillow, which was already a hard dependency, so nothing new is
  required and nothing is vendored. The silhouette carries the meaning rather
  than the colour, with guest drawn hollow rather than in a second hue, so the
  set survives greyscale and colourblind readers. Aspect ratios are real, so a
  switch is wide and short and a handset is taller than it is wide. Each theme
  colour caches separately.

- The shipped demo marks its guest client as one. `is_guest` is a separate fact
  from sitting on the guest VLAN, and without it two of the nine new icons never
  appeared in the demo at all.
- **Every page under `docs/` links back to the documentation index.** A search
  result or a shared link lands a reader on one page of a set, with nothing on
  it saying that a set exists or where it is listed. Suggested by an external
  documentation review, and guarded, because the convention is the sort that
  holds across eight files and quietly lapses on the ninth.
- **Three documentation guards, each for a class of drift the existing checks
  could not see.** The JSON example is parsed and its version and top-level keys
  compared against real output; the Mermaid example is diffed byte-for-byte
  against what its stated command produces; and every document is checked for a
  generated-content marker without its pair. All three were mutation-tested by
  reintroducing the exact defect they were written for.

## 0.7.2 - 2026-08-02

### Fixed

- `unifi-map shape` says when its artwork counts are measuring an empty cache
  rather than the network. Resolved against a cold cache it reported `0 of 19`
  for any network at all, and that section exists precisely so somebody else's
  numbers can tell us how well the fingerprint joins work. The same snapshot
  gives `0 of 19` or `19 of 19` depending only on whether artwork has ever been
  fetched, so reading it as a property of their network was a wrong conclusion
  waiting to be drawn.
- `SECURITY.md` covers `unifi-map shape`. A command whose entire purpose is
  producing something to hand to a stranger was absent from the document about
  what this tool discloses, which is the one place somebody assessing it would
  look.

## 0.7.1 - 2026-08-02

### Fixed

- The README's `## Output` table lists `mermaid` and `json`. It had not, since
  both were added, so the first place a reader looks to find out what the tool
  can produce named five formats out of seven. A test now checks the table
  against `ALL_FORMATS`: the existing guard covers flag names, not the values a
  flag accepts, which is how the table fell behind twice without failing.

## 0.7.0 - 2026-08-02

### Fixed

- `SOURCE_DATE_EPOCH` fixes the time stamped into the title block, following the
  reproducible-builds convention. Without it the committed demo screenshots
  changed on every regeneration, by exactly the thirty pixels of their
  timestamp, which made a real rendering change indistinguishable from the clock
  ticking. `make demo-images` sets it; a real map still stamps the time it was
  drawn.

- The first screenshot's caption said most clients "fall back to plain shapes".
  They have not for some time: eleven of them draw the console's own generic
  glyphs, which is what the image shows. The caption now describes the image,
  and says that those glyphs need an icon font only a controller serves, so a
  fresh clone genuinely does see shapes there. The two statements were both
  true of different machines, which is the confusing kind of wrong.

### Added

- `-f json` writes the normalised topology: nodes, edges, networks and counts,
  rather than the controller's payloads. The model is the stable thing here and
  UniFi's schemas are not, so this is what to build an inventory check or an
  integration against, and it is a far smaller disclosure than a snapshot. It
  honours `--obfuscate`, overrides and `--per-network` like the diagram does.
  Carries a `schema` number: fields may be added and will not be removed.
- `-f mermaid` writes a `.mmd` that GitHub, GitLab and most wikis draw in
  place. It reaches the one destination the other formats cannot: a page that
  renders the diagram itself, with no file to open and no colour scheme to
  guess. Artwork is lost, necessarily, since Mermaid draws boxes and text; node
  kind is carried by shape and link meaning by line style, so nothing depends on
  colour. The README embeds a live one of the demo.
- `unifi-map overrides check` applies an overrides file against the cached
  snapshot and reports, without rendering anything. Overrides fail loudly by
  design, so the only way to find a stale selector used to be producing a whole
  map. Exits non-zero on the first selector matching nothing or several things,
  which makes it usable in a hook or in CI. A missing file is an error rather
  than a pass.
- `unifi-map shape`, which prints a short plain-text description of the shape
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

  It reports counts and fan-out, topology depth, artwork resolution rates, the
  Graphviz version and the offline device count. The artwork numbers were
  already computed and thrown away as log lines, and they measure the most
  fragile join in the tool; depth because fan-out alone does not distinguish a
  flat network from a daisy chain; the Graphviz version because layout differs
  between them.

  Pointed at an archive with `--support-file` it reads that directly rather
  than the cache, and adds how much there was to walk, how many entries, and
  how many sites it holds. Those are the numbers behind the support-file limits
  (set from a single archive) and the untested multi-site handling. Sites are
  counted, never named: the keys carrying those names are user-chosen.

  `CONTRIBUTING.md` asked people to gather this sort of thing by hand and now
  points at the command instead.

  Named `shape` rather than `report` because a diagnostic `--report` is planned
  and does the opposite job: it describes *your* map for *your* benefit and may
  freely name your devices, since it never leaves your terminal. This one
  describes a network for somebody else and is constrained so it can be shared.
  One name for both would have guaranteed the constraint eventually leaked.

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

- `RELEASING.md` describes the process as it now is. Four things in it were
  wrong. It said to rename `## Unreleased` away at release, which would delete
  the section `CONTRIBUTING.md` tells contributors to use. It never mentioned
  `make docs`, which is mandatory now that the man page carries the version. It
  said CI could not be checked from here, which stopped being true once `gh` was
  installed; the instruction now runs `gh run watch` and says to read the
  per-job output, because `Dependency advisories` is `continue-on-error` and
  reports success having failed inside. And it counted how many times things had
  happened, where two of the counts were wrong and none told a reader anything
  the sentence did not.
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
