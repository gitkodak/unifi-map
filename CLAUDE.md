# CLAUDE.md: unifi-map

Pulls the UniFi topology from a controller's JSON API and renders it as vector
diagrams and editable draw.io files, using real Ubiquiti product artwork. See
`README.md` for usage; this covers what's easy to get wrong when changing it.

This is intended to be published publicly, so keep it site-agnostic and
non-identifying: no real hostnames, subnets, SSIDs, device addresses or
site-specific defaults in code, tests, docs or fixtures. Test data should look
like a plausible generic network, not like anyone's actual one.

## Commands

```bash
make check     # ruff format --check, ruff check, pytest (run before committing)
make map       # fetch + render against the live controller
make tree      # render in the readable (non-UniFi) layout
make offline   # builtin icons, no network access
make demo      # render the shipped demo dataset, no controller needed
make test      # pytest only
```

Single test: `.venv/bin/python -m pytest tests/test_assets.py::TestCatalog`

Tests never touch the network. Fixtures in `tests/conftest.py` are synthetic
payloads with invented MACs; `tests/test_assets.py` writes a catalog straight
into a temp cache so `AssetStore` reads from disk.

## Mistakes that have actually happened here

Each of these cost real time or shipped a real defect. They are listed because
every one of them looked fine at the moment it was made. General lessons of
this shape (pipe exit-status traps, mutation-testing guards, fixing the class
not the instance, elapsed-time claims, `stat -L`) live in the global
`~/.claude/CLAUDE.md` now; this file keeps only what's specific to this repo.

### A repeated `-f` used to overwrite rather than append

`-f` is `nargs="+"`, so `-f svg -f png` silently yielded **png only**, which
read as a format that had failed to render. Fixed in 0.9.0: `_FormatsAction`
now refuses the repeat and names the working form, `-f svg pdf png`.

Kept here because the shape recurs. Any `nargs="+"` or `action="store"` option
behaves this way, so a future flag that accepts several values needs the same
treatment or it will reintroduce the same silent loss.

### Do not use `git commit --no-verify`

See `~/.claude/CLAUDE.md` for why generally. Specific to this repo: the
globally configured hooks refuse assistant session URLs and identifiers in
commit messages and in staged file content — see the commit-trailer section
below for why that rule exists here.

## Pipeline

Each stage owns one concern; nothing downstream of `model.py` sees raw
controller JSON.

1. **`config.py`** is the only module that reads `os.environ`. Keep it that way:
   it's what makes a future Vault/OpenBao backend a single-file change.
   Credentials are `UNIFI_HOST` plus `UNIFI_API_KEY`, and nothing else. The
   `UDM_*` aliases were removed in 0.9.0; `layout.py` still strips
   `UDM_API_KEY` from Graphviz's environment, which is deliberate and explained
   there.

   **`base_url` forces HTTPS; there is no way to ask for plaintext.** A host
   with no scheme gets `https://`, and an explicit `http://` is *upgraded*,
   not honoured or refused. Deliberate: the credential file is hand-edited, a
   mistyped scheme is the likely way a key leaks in clear, and silently
   weakening the connection over four typed characters is worse than
   ignoring them. Pairs with `_Session.rebuild_auth` below. No opt-out;
   `UNIFI_VERIFY_TLS=false` already covers the bare-IP case.
2. **`client.py`** is the only module that talks to the controller. Auth is an
   `X-API-KEY` header set once in the constructor; no login, session or CSRF
   token. Paths are prefixed `/proxy/network`. `unwrap()` absorbs both the v1
   `{"data": [...]}` envelope and bare v2 lists, returning `[]` on anything
   unexpected so a controller upgrade thins the diagram instead of raising.
   **`support.py`** is the alternative source: same `Snapshot`, out of a
   support file archive, no credentials, no network. Keep the two
   interchangeable — anything added to one is considered for the other.
   `_Session` overrides `rebuild_auth` so `X-API-KEY` is dropped on a
   redirect that changes host, matching what `requests` already does for
   `Authorization`. Redirects stay enabled: nothing here redirects today, but
   refusing outright would break anyone fronting their controller with a
   normalising proxy. Since `UNIFI_VERIFY_TLS=false` is documented as
   ordinary for a bare IP, without the strip anyone in the path could
   redirect the tool and be handed a working admin key.
3. **`model.py`** normalizes into `Topology`. All schema quirks land here.
4. **`assets.py`** is the only module that fetches artwork. Cached under
   `--asset-cache` (default `cache/assets`), deliberately separate from the
   snapshot cache so `--cache-dir examples/demo` doesn't get downloads written
   into it.
5. **`layout.py`** is the only module that shells out to Graphviz (`dot`,
   `unflatten`) to render. Both are executed by the absolute path `shutil.which`
   resolved, not by bare name, so what runs is what was found rather than
   whatever `PATH` resolves to at exec time. Both get `child_env()`, the parent
   environment with any API key removed.

   That pairs with `config.py` never writing a credential into `os.environ`:
   `read_dotenv()` returns a mapping and `load_config()` merges it under the
   real environment. Keep it that way. An API key in the process environment is
   inherited by every child, and Graphviz comes off `PATH`.

   **A third Graphviz child process was missed when this scrubbing was added**
   (external review of 2db752d, fixed same day). `cli._graphviz_version()` —
   what `unifi-map shape` reports, the command meant to be safe to paste into
   a bug report — ran `dot -V` with the plain inherited environment, not
   `child_env()`: the fix-the-class-not-the-instance failure, since scrubbing
   was added to the two render call sites but not the version-reporting one
   added separately. `child_env()` was promoted out of `layout.py`'s privacy
   (`_child_env`) into a shared primitive rather than reimplemented in
   `cli.py`, same reasoning as the capped-read primitive moving into
   `httpio.py`. A regression test runs a stand-in `dot` and asserts the
   exported key never reaches it, mutation-tested against the pre-fix code.
6. **`render_dot.py` / `render_drawio.py` / `svg_post.py`** are pure functions
   from `Topology` to text. `theme.py` holds every colour, shape and label.

## Artwork constraints

- **Never vendor Ubiquiti artwork into the repo.** It is their IP. It is fetched
  at runtime and cached under `cache/` (gitignored). `--icons builtin` must stay
  a fully working, network-free path.
- **Match devices on `sysid`, not `model`.** The controller's `model` string does
  not reliably match the catalog's `shortnames` (`USWED72` vs `USPH24P`).
  Catalog sysids are hex strings, the controller reports decimal ints; all 1178
  catalog values are unambiguously hex, so strict base-16 parsing is correct.
- The controller does **not** serve device *images* locally (verified on Network
  10.5.67: every plausible path under `/proxy/network/manage/angular/<hash>/`
  returns the SPA's HTML 404). It DOES serve the icon font, and it serves the
  fingerprint database at `/proxy/network/v2/api/fingerprint_devices/0`.
- **Client artwork is `static.ui.com/fingerprint/0/{dev_id}_{size}.png`**, keyed
  on the fingerprint `dev_id` in `stat/sta` (`dev_id_override` wins). Only
  257x257, 129x129 and 101x101 exist; any other size 302s to ui.com, so treat a
  redirect as "absent" and do not follow it. This is `staticFingerprintOld` in
  the Network UI config.
- **Two frontends exist. Read the right one.** `/manage/` is the legacy Angular
  app; its `getIconClassName` resolves clients to just four icon-font glyphs, so
  reading it will convince you no client artwork exists. The app the browser
  actually loads is the React one served from the UniFi OS root (`/275.*.js`,
  `/main~2.*.js`), and that is where the real image URLs live. When hunting an
  asset, find it in the bundle the browser loads rather than inferring from a
  failed guess.
- **ISP brand marks are `static.ui.com/asn/{asn}_{size}.png`**, keyed on the
  `asn` that `stat/health` reports beside `isp_name`. Sizes 257, 129, 101, 51
  and 25 square. There is no provider table and none is wanted: the ASN is the
  whole lookup.

  Unlike the `/fingerprint/` paths on the same host, a missing ASN or size
  returns a genuine 404 here, so absence is detectable. Do not carry the
  fingerprint paths' "200 means nothing" assumption over to this one.

  Hunted through the web bundles across many passes with no luck; found in
  one grep of a **support file's own logs** instead — the speed-test daemon
  logs the URL it builds as `ispImg`. Search data the device already wrote
  down before searching bundles again.
- **The Internet node falls back to a locally drawn cloud**, not to a bare
  polygon. `_render_cloud()` is a few Pillow ellipses and a bar, ours rather than
  Ubiquiti's, so it needs no network and raises no licensing question. Every
  circle's lowest point sits exactly on the baseline; a puff reaching past it
  leaves a lump hanging off the flat bottom edge.
- **`--obfuscate` drops the ASN**, alone among the artwork keys. `sysid`,
  `dev_id` and `oui` all survive because they say what hardware *is*; an ASN says
  who the owner buys transit from, and drawing the provider's logo on a map
  meant for publishing would give the game away no matter what the label said.
  The icon dict is built before `obfuscate()` runs, so `cmd_render` also swaps
  the mark for the cloud; clearing `Node.asn` alone is not enough.
- Artwork must degrade: no network, no Pillow, or unknown hardware all fall back
  to the shape renderer rather than failing the run.
- **An asset that 404s stays quiet at the default log level, on purpose.** A
  handful of unrecognised devices is ordinary on any network, and a warning
  per device would drown the output that matters. Detail lives behind `-v`,
  which logs every lookup including empty ones, documented in `docs/usage.md`
  and asked for by both issue templates. A summary count at end-of-pass was
  considered and dropped: the existing flag was enough.

## Rendering constraints

- **Don't switch `--layout tree` edges to `splines=ortho`.** It looks tidier but
  Graphviz cannot place edge labels on orthogonal routes, so port numbers drift
  far from their link and float beside unrelated nodes. `--layout unifi` *does*
  use ortho, and deliberately suppresses port labels for exactly this reason.
- **Edges are emitted parent → child, the reverse of how they're stored**, so the
  root lands at the top (TB) or left (LR) rather than trailing at the far end.
- **`--layout unifi` omits the title block and legend.** A graph label sets a
  minimum canvas width, which pads a tall narrow map with dead space on both
  sides. The UniFi UI has neither, so dropping them is faithful *and* tighter.
- **Stagger once, before rendering.** `_write_outputs()` applies `unflatten`
  then feeds the *same* DOT to the SVG render and the draw.io coordinate pass.
  Different DOT means draw.io positions disagree with the SVG.
- **`unflatten` reformats the file.** It re-tabs and drops trailing semicolons,
  so `sed`-style patches against generated `.dot` files silently no-op. Change
  `render_dot.py` instead.
- **Graphviz identifiers cannot contain a raw MAC.** DOT reads `:` as a port
  specifier, so `_node_id()` strips colons; `render_drawio.py` reuses it so
  layout lookups line up.
- **Graphviz `<IMG SRC>` needs a filesystem path**, not a data URI.
  `svg_post.inline_svg_images()` rewrites those paths into data URIs afterwards,
  restricted to the icon cache dir so a crafted device name cannot pull in
  arbitrary files.
- **draw.io wants `data:image/png,<base64>`**: comma, *not* `;base64,`.
- **`mxGeometry` needs `as="geometry"`.** `as` is a Python keyword and cannot be
  a `SubElement` kwarg; `_geometry()` sets it afterwards. Without it draw.io
  silently ignores every position and piles all shapes at the origin.
- **Size icon cells to the real aspect ratio** via `IconAsset.display_size()`.
  Rack switches are wide and short; a square cell letterboxes them into a thin
  strip surrounded by dead space.
- **Colour is never the only channel.** The accent palette is Okabe-Ito and every
  distinction is also carried by artwork, shape or line style. Don't add a
  red/green pair that carries meaning alone.
- **Never invent a product match.** `AssetStore.sysid_for_name()` is how UniFi
  hardware appearing as a client gets artwork, and it returns a match only when
  exactly one catalogue entry matches. `g3-flex` genuinely matches both
  `UVC-G3-FLEX` (Protect camera) and `UA-G3-Flex` (Access reader), so ties are
  broken with a device type from another app (Protect's camera list), never by
  preference or ordering. Ambiguous stays ambiguous and falls back to the glyph.
- **`stat/sta` is not the whole graph.** It reports a client's uplink only when
  that uplink is a UniFi device, so anything behind a non-UniFi box has no
  `sw_mac`. `topology_uplinks()` reads the controller's own `v2` graph, where a
  CLIENT can be another client's uplink, and `_place_remaining()` runs after every
  client exists because an uplink is frequently another client. This was missed
  repeatedly: the placeholder node was blamed on the controller when the
  data was in an endpoint already being fetched and ignored. Check the console
  against the output before concluding the controller does not know something.
- **Never invent topology.** Clients whose uplink the controller doesn't report
  get anchored to `UNKNOWN_UPLINK_ID`. Don't guess a plausible parent switch.
- **`Topology.infrastructure` includes `Kind.UNKNOWN`** so that placeholder
  survives per-network filtering. Removing it re-orphans those clients.

## Defaults reproduce the UniFi web view

`--icons unifi --layout unifi --theme light` is chosen so the tool matches what
the console shows out of the box.

**`--theme light` was questioned and confirmed, 2026-08-02.** Jason started
the project wanting dark and was surprised light was the documented default;
fair, since nothing recorded it as his decision and the only justification on
file was the sentence above, written while documenting rather than deciding.
Kept anyway, on unsurprising-over-stylish: light is the norm for tools that
render to files rather than screens (Graphviz included), and `pdf` is a
printing format where dark costs real ink. Neither theme is safe to embed:
both set `bgcolor`, so an SVG is an opaque block against the opposite-mode
page.

**`--theme` does not survive into draw.io, and that is not a bug to fix.**
Reported from a real network 2026-08-03, misdiagnosed twice first: draw.io
inverts a diagram to contrast with its own appearance setting, since its dark
mode assumes diagrams are authored light. A file we authored dark gets
inverted a second time and displays light — confirmed with an unchanged
`--theme dark` file rendering light in draw.io's dark/Automatic mode and dark
in draw.io's light mode. Nothing is broken when this happens (the inversion
is holistic — cells, text and baked icon colours flip together and the file
stays coherent), which is why it took three passes to identify; two wrong
explanations along the way — swapped files, an ignored `background`
attribute — are recorded so they aren't retried. The attribute is written
correctly for both themes.

**A light-authored file is right in both of draw.io's modes**, established a
day later: light mode leaves it light, dark mode inverts it to dark — exactly
what `--theme` should deliver. A dark-authored file is right in neither, so
`--theme dark -f drawio` isn't a trade-off, it's a combination with no
configuration that works. An earlier note here rejected forcing `.drawio`
light, reasoning that silently discarding an explicit flag is worse than a
documented surprise — that assumed dark was right for somebody. It isn't, so
the objection is answered by evidence rather than argument; recorded because
the earlier note reads persuasively and would otherwise stop the fix twice.

What exists today is a warning: `cmd_render` says so once when `--theme dark`
and `drawio` are combined. The real fix, **KAN-140**: always warn when
`drawio` is requested with a dark theme; with other formats alongside it,
author the `.drawio` **light** so it displays dark like the rest of the run;
with `drawio` requested *alone*, author it **dark** as asked, warning it may
not display as expected — asking for one format only is instruction enough to
honour. **Blocked on something real**: icons are baked in `theme.text_muted`
and one `icons` dict is shared by every format in a run, so rendering the
draw.io file light while the run is dark would put light-baked icons on a
white card — trading a reported bug for an unreported one. Fixing it properly
means resolving artwork twice, once per output theme, which `write_outputs`
isn't shaped for.

Same shape as the `bgcolor` note above: where we produce the final pixels,
`--theme` means what it says; where the output is handed to another
application, that application gets the last word, and `svg`/`pdf` answer
anyone who needs colours that can't be re-themed.

Screenshots stay dark because they read better on the README's own page, and
every one is now committed in both themes so a reader sees what the default
actually produces rather than inferring it from a caption (one had wrongly
called `--theme dark` the default outright). Don't change a default for
"better looking" without a reason — fidelity first, with `tree` available for
readability.

The single deliberate exception is `--show-offline no`: the UI offers no way to
hide stale hardware, which was specifically wanted. `build_topology()` still
defaults `include_offline=True` (a library shouldn't drop data silently); only the
CLI flips it.

When excluding offline devices, they are left out of `device_macs` too, so the
uplink pass must skip any device not in `topo.nodes`; indexing it directly was a
real KeyError.

## `--layout unifi` is an approximation, and the docs say so

It is deliberately not claimed to be pixel-identical to the controller UI:
Graphviz owns the layout, so sibling order and spacing are its decisions, link
routing differs in its corners and channels, typography and label content are
ours, clients without a usable fingerprint fall back to the console's own glyph
or to one we draw rather than to its real icon, and the output is static.
`docs/usage.md` has a section spelling this out. Keep improving fidelity if you like, but do not let the documentation
start implying an exactness that is not there.

## Whether `unifi` layout is narrower than `tree` is data-dependent

It is on a real network with many sibling clients (1305pt vs 4648pt observed),
and inverts on a small fixture where tree depth dominates. Don't assert it.

## Demo dataset

`examples/demo/` is generated by `scripts/make_demo_snapshot.py`; edit the
script, not the JSON. MACs use the locally-administered `02:` prefix and
addresses are RFC 1918, but the **sysids are real** because that is the artwork
join key; fake ones would leave the demo unable to show icons. `tests/test_demo.py`
enforces both of those properties. The dataset intentionally includes an offline
device, four VLANs, and an unplaceable client so those behaviours are visible.

## Overrides

Implemented end to end: schema, loader, `resolve()` and `apply()`. Notes:

- `resolve()` tries MAC, then IP, then label. Unmatched or ambiguous is a loud
  error, never a silent no-op.
- `apply()` works on a copy and returns an `ApplyResult` carrying counts, the
  hidden labels and any user-supplied icons, so the CLI can report what happened
  rather than guess.
- **Order matters.** Links and nesting are applied before hiding, so hiding a
  node that an override just gave a child is correctly refused.
- Hiding is leaf-only by design. Do not add child-reparenting; there is no
  honest answer to what should happen to them.
- Asserted edges carry `Edge.asserted` and render dotted in both backends. Keep
  them visually distinct from observed links.
- **`[[device]]` declares a node the controller cannot see**, for a switch it
  does not manage (managed or not, in itself) or
  gear that was off during the fetch. Those carry `Node.asserted` and render
  with a dotted outline, for the same reason edges do: the map must never
  present something typed in as though a controller had reported it. Offline
  uses dashes and asserted uses dots, so the two remain distinguishable without
  relying on colour.
- Declared devices are added **before** every other override is applied, so a
  link, a nesting or a rename can reference one, and one declared device can
  hang off another. Their ids are prefixed `asserted-`, which is what keeps a
  device named after a MAC from shadowing a real node.
- User artwork is loaded through `assets.local_icon()`, which raises rather than
  falling back, and override icons are merged over looked-up ones in the CLI.

## Open work

Restored after being deleted by accident in 9b18a1a, where a section replacement
spanned two headings and took this with it. If you replace a range between
headings, check what was in between.

### Blocked on data nobody here has

A category worth naming separately, because it does not look like a blocker in
a backlog. These are not waiting on effort or a decision. They are waiting on a
network, an archive or a controller that this project has never seen, and until
one turns up any work on them is guessing dressed as engineering.

Jira label: `needs-real-world-data`.

- **Multi-site anything** (KAN-125). One controller, one site, ever. Every
  multi-site code path here is inference from the shape of a payload.
- **Performance at scale.** Never profiled on a large network. The joins are
  dictionary-based and probably fine, and `sysid_for_name()` scans the catalogue
  per candidate, which is the one that would show up first.
- **The support-file caps.** All four defaults come from a single 154 MiB
  archive, and `support.py` says outright there is no honest basis for a tighter
  archive-walk number. A second real archive would be worth more than any amount
  of reasoning about the first.
- **Controller versions.** Everything is verified against UniFi OS 5.1.26 with
  Network 10.5.67. `unwrap()` is written to thin a diagram rather than raise
  when a schema moves, which is a guess about how it will move.

The useful response is not to speculate harder, it is to ask. `CONTRIBUTING.md`
now says what data would help and what to send, so somebody who has a network we
do not can offer it without having to guess what is useful.

- **Rendering preferences in the environment** (KAN-130). **Shipped
  2026-08-14, as both mechanisms rather than one:** `~/.config/unifi-map/
  config.toml` beside the credential file that directory already holds, plus
  `UNIFI_MAP_*` variables. Precedence: flag > environment > config file >
  default — not new here, `--site` already worked this way and
  `read_dotenv()` already merges under the real environment.

  **"Shipping both would be worse than either" is withdrawn**, having been
  asserted three times (here, `TODO.md`, the ticket) without ever being
  argued — same shape as the `pip-audit` note further down. Jason broke it
  with containers: mounting a file to set four preferences is friction `-e`
  doesn't have, and KAN-196's `serve` makes that likely, so it needed
  settling before serve ships.

  **`--obfuscate` and `--force` stay flag-only.** One claims the output is
  safe to share, the other overwrites files; ambient, call-site-invisible
  state is the wrong source for either, more so for an environment variable
  than a named file. The surviving objection, reproducibility across
  machines, is mitigated in the same change: `cmd_render` prints "Settings
  not from the command line", naming every flag-unsupplied source. Flags are
  excluded since they're already visible in the command typed.

  **Two things the implementation turned up that the plan had wrong.** First,
  `UNIFI_CACHE_DIR`, `UNIFI_ASSET_CACHE` and `UNIFI_OUT_DIR` already existed
  and already broke the naming rule this ticket restated; renamed to
  `UNIFI_MAP_*` with old spellings warning, same treatment `UDM_*` got. Do
  not add a fourth `UNIFI_*` tool setting. Second, **the render flags had
  real argparse defaults rather than `SUPPRESS`**, so `hasattr` couldn't tell
  a flag from a default and nothing from the environment would ever have
  applied. `formats`, `icons`, `layout`, `theme` and `overrides` moved to
  `SUPPRESS` with defaults in `GLOBAL_DEFAULTS` — no doc-generator change
  needed, since it already falls back to `GLOBAL_DEFAULTS` for a suppressed
  action. An injected value never passes argparse's `choices` check, so
  `_validate_injected` checks it against the same constants and names the
  source in the error.

  **The tests were reading the developer's own environment.** A deprecation
  warning from Jason's real `UNIFI_CACHE_DIR` broke an unrelated `--site`
  test; `TestDirectoriesFromTheEnvironment` had carried a per-class
  workaround for years for exactly this. Now an autouse `conftest.py`
  fixture strips the whole search path, so the suite no longer depends on
  whose machine runs it — it removes only *implicit* discovery; a test
  pointing `UNIFI_MAP_ENV`/`UNIFI_MAP_CONFIG` at a file it wrote still
  exercises the real feature.

### Sweep the prose when a fallback changes

Adding a capability leaves every sentence describing the old behaviour spread
across files the change itself doesn't touch. The drawn icons landed with
nine places still promising "plain shapes" for `--icons builtin` and
unfingerprinted clients, across `README.md`, four `docs/` pages and
`SECURITY.md`; an external reviewer found six of the nine.

Before handing over a rendering change, grep for the behaviour being
replaced, not the feature being added:

```bash
grep -rniE "plain shapes|geometric shapes|bare shapes|falls? back to" \
  README.md docs/*.md SECURITY.md
```

Not tested — whether a sentence is still true isn't a property a test can
check. The phrase list is the useful part; the failure is always that the
old behaviour had a name.

### Sweep "the README" references too, for the same reason

The documentation split moved most of the README into `docs/`, and this file
kept pointing at where things used to be. Three separate reviews found stale
ones, each a different subset, because each fix only touched the sentence
under discussion — the last pass found five, after an external reviewer had
already spotted two.

Same failure as `TODO.md` below, same remedy:

```bash
grep -n "README" CLAUDE.md
grep -n "^## \|^### " README.md      # what is genuinely still there
```

Two counts travel with those references and were wrong after the first
sweep: the multi-site check names five files, not four, and `make docs`
covers two of those five.

### Check `TODO.md` before handing anything over

Not at release — **every time work is handed back for review.** Jason asked
for this after `TODO.md` was left claiming Mermaid was coming when it had
shipped, then, in the same turn that fixed it, left claiming the JSON export
and `overrides check` were coming when they'd shipped too.

The failure is order, not forgetfulness: the file gets updated for whatever
was most recently discussed rather than swept. Sweep it mechanically:

```bash
unifi-map --help                     # subcommands that exist
python -c "from unifi_map.cli import ALL_FORMATS; print(ALL_FORMATS)"
grep -nE "shape|check|export|-f " TODO.md
```

Anything shipped comes out of the planned sections and, if the reasoning is
worth keeping, moves to "considered and not planned". Watch for entries that
*reference* a removed one: the NetBox note said "subsumed by the JSON export
above" after the JSON export was no longer above.

`RELEASING.md` still requires the same read at release — the backstop, not
the routine.

### Three places, and which one wins

| Where | What it is for |
| --- | --- |
| `TODO.md` | The contributor-facing list. What and one line of why. |
| This file | The reasoning, the constraints, what was tried and rejected. **Authoritative.** |
| Jira epic KAN-114 | Status and workflow, not visible outside the house. |

`TODO.md` exists because neither of the others is where somebody with a
checkout would look: this file runs to hundreds of lines, and Jira needs an
account.

**There is a second epic, KAN-144**, "SonarQube Cloud triage (2026-08-03)",
a closed batch of findings from one analysis run rather than a roadmap — all
Done, accounting for the `KAN-145`–`KAN-170` run in the git log. Deliberately
**not** in `TODO.md`: a reader with a checkout doesn't need a list of landed
complexity refactors, same reason releases aren't listed there. Don't fold a
future triage batch into KAN-114 — a roadmap epic that never closes and a
triage epic that closes when findings clear measure different things.

**Sweep all three or none.** The handover rule below covers `TODO.md` and
this file but said nothing about Jira, so Jira drifted furthest: a
2026-08-03 reconciliation found the JSON export still open long after
shipping, and two tickets each covering one shipped thing and one unstarted
thing (`overrides check` with the candidates generator, Mermaid export with
the HTML viewer). Splitting a ticket when half of it ships isn't optional
bookkeeping — half-done reads as untouched. The same reconciliation found
five `TODO.md` items with no ticket at all; nothing syncs these, and nothing
can — only a person knows whether a line is worth a ticket.

**It has no test behind it, deliberately.** A first version was guarded by
two tests asserting the file contained a particular heading — wrong in kind,
since that lets the test dictate structure rather than accuracy. A list of
intentions can't be checked mechanically for being the right list.
`RELEASING.md` promises a read at every release instead: a process guarantee
rather than a mechanical one, and the honest tool for this.

It should read as **what is coming**, grouped by what the features do.
Leading with commitments was the first attempt and read as a release plan —
what a maintainer wants, not what a reader wants.

### Tracked in Jira as well

All of the below is also **epic KAN-114** in the `bhomelan` project, with a
ticket per item, so it is visible without reading this file. **This file stays
authoritative**: the tickets carry the summaries, this carries the reasoning,
and if they disagree this one is newer. Update both or neither.

### Proposals from two external reviews, with assessments

From agy and from Codex, both 2026-08-02, recorded with what was thought
about them so the thinking isn't redone. They overlap heavily — the same
three ideas arrived independently — so merged rather than listed twice, and
ordered by fit rather than arrival.

**A second round ran against 2dcf791 on 2026-08-03**, asking for a maturity
and security assessment rather than features. It produced four defects worth
acting on, verified at source. **Three are fixed** — read the list as what a
review caught, not open work: the `pip-audit` job that never worked
(KAN-132, repaired), the venv make target that stranded a failed install
(KAN-133, now keyed on a `.installed` stamp), the missing controller
response cap (KAN-134, now `httpio.py`). Sparse package metadata is still
outstanding and only matters if artifacts are ever distributed. It also
raised static type checking (two reviewers now want it independently) and a
coverage threshold (declined below).

**Write review findings in the past tense and name their outcome.** This
entry said the audit job "has never worked" until 2026-08-10, long after it
was repaired, three paragraphs from the entry recording the repair — accurate
the day it was written, rotted without being touched. A present-tense finding
becomes a false claim the moment it's fixed, since the fix never revisits the
paragraph describing the problem.

Both rounds are worth the trouble: between them they found things many
passes over this file did not, and the pattern holds — they're better at
spotting a control that doesn't do what its documentation says than at
anything requiring UniFi knowledge.

- **A `diff` subcommand**, comparing two cached snapshots and reporting what
  moved. The strongest of the set: snapshots are already immutable, timestamped
  JSON, `build_topology()` already turns one into a graph, so a diff is a pure
  function over two `Topology` objects needing no new input path.

  **Two prerequisites, and the first was missed when this was first written
  here.** `Snapshot.write()` replaces the whole generation every fetch, so
  there's no history to diff against — something has to retain snapshots
  first, as a timestamped mode rather than a changed default. Codex caught
  this; the entry originally named only the second blocker (randomised
  client MACs, its own gap below): every join here is on MAC, so a phone
  rotating its address appears as one device leaving and another arriving,
  and a diff would report that as churn every run.

- **A diagnostic report. Shipped, as `--report` (KAN-115), 2026-08-10.**
  Merged two gaps listed separately below, "no reconciliation report" and
  "provenance and confidence" — the same feature seen from two ends, the
  second being what made the first worth reading.

  **The feature is the model change, not the printing.** Decisions were
  already being made at runtime and thrown away as log lines, so the work
  was recording them where they happen: `Provenance` on `Node` and `Edge`,
  set at every construction site in `model.py`/`overrides.py`. The report is
  then mostly derivation — counts, unplaced list, dangling network
  references, observed/asserted split all fall out of a finished `Topology`
  — no diagnostics object threaded through the pipeline. Only two things
  can't be recovered afterwards: artwork resolution (happens after the model
  is built) and facts the caller knows that the map doesn't.

  **`Provenance.UNSPECIFIED` is the design's own guard**: the default, so a
  new node/edge path that forgets to say where its data came from is caught
  by a test rather than quietly reporting itself synthetic. Don't default to
  something "sensible" like `DEVICE`; that turns a loud failure into a
  plausible lie. **Mutation-testing it found a real hole**: deleting each
  `provenance=` in turn reddened its test except `TOPOLOGY_GRAPH`, removable
  with the whole suite green — nothing covered the path that places a client
  from the controller's own graph, the same path this file elsewhere records
  as "missed repeatedly". A test now pins that it and `CLIENT_UPLINK` stay
  distinguishable, since a report calling both "reported by the controller"
  would be true and useless.

  **A device is named only where something is wrong with it.** Healthy
  nodes are counted, never listed — a readability decision, not a privacy
  guarantee, and must not be described as one: the "not safe to share"
  header must stay accurate for maps that do have problems. Written down
  because the tempting change is a full node listing "for completeness",
  which would turn every clean run into a network inventory on stdout. A
  test pins it.

  **It runs last, after overrides and `--obfuscate`**, describing the map
  that was written rather than the one fetched — same reasoning as moving
  `_hint_about_unplaced` after overrides. Tested: the report inherits
  scrubbing instead of needing its own.

  **The snapshot-contents section is the one part not derived**, nearly
  missed: the ticket asked for "optional endpoints missing or malformed" but
  neither `TODO.md` nor this file carried that line, so the first
  implementation lacked it. A fetch-time failure leaves no trace in the
  graph it would have enriched, only an absence, so the report takes
  `Snapshot.payloads` as its one non-derivable input, naming the
  *consequence* rather than the endpoint since "topology absent" means
  nothing to someone who doesn't know the pipeline.

  Two accuracy traps there, both caught by checking rather than reasoning:
  the `fingerprint` payload supplies **product names in labels, not
  artwork** (artwork is keyed on `dev_id`; the demo dataset draws product
  icons with no fingerprint payload at all), and an empty `edges` list is
  *present with zero*, not unusable — the controller did answer. A comment
  claiming otherwise was written first and a test matched it, the exact
  mutation-testing failure this file warns about.

  Printed to stdout while logs go to stderr, so `--report > file` captures
  the report alone. `report.py` (the shareable `shape`) and `diagnostics.py`
  (this) are deliberately opposite in kind — the naming most likely to
  confuse later.

- **A normalised JSON export of `Topology`. Shipped, as `-f json`.** Honours
  `--obfuscate`, overrides and per-network filtering — an export ignoring
  the cleaning applied to the picture would leak what the picture hid.
  `SCHEMA_VERSION` is 1; the schema gains fields and never loses them. Does
  **not** yet carry the diagnostic report's provenance fields; doing both
  together was the argument for doing them together, now half spent.

- **Generalised filters**: `--kind switch ap`, `--wireless-only`,
  `--guest-only`, and most usefully `--root "Rack Switch"` for a subtree of
  a large map. `--per-network` is a special case that already does the hard
  part — keeping the ancestor path back to the gateway so a slice still
  reads as part of one network.

- **`--all-sites`, and a `sites` command.** Designed out with Jason
  2026-08-02; full version is KAN-125. Each site gets its own diagrams,
  output directory and cache directory (the last because `Snapshot.read()`
  globs a directory and a snapshot is a full inventory). Three things
  settled: spell it `--all-sites` not `--site all` (a site literally named
  `all` is possible, so overloading the value space would force a guess);
  the restriction is on *naming* a network, not on networks —
  `--all-sites --per-network` is fine since each site's networks land in
  its own directory, `--all-sites --network IoT` is ambiguous and should be
  refused, narrower than Jason's instinct to forbid VLAN selection entirely;
  and support files can do this almost free while live cannot, since every
  live endpoint is `api/s/{site}/...` (site always supplied, never
  discovered, so live needs a site-listing call never made here) while a
  support file already carries every site in `devices.json` — so the
  support-file half could ship first, with `sites` a hard prerequisite for
  the live half. Still untested against a real multi-site console, which is
  where this should start.

  **Three pieces of wording have to change on the day this ships**, none of
  them in the code that changes: `--site`'s help text in `cli.py` says the
  flag is *required* for a multi-site support file (propagates into
  `docs/usage.md`'s generated table and `unifi-map.1`), `docs/
  support-files.md` says the same at greater length, and `_pick_site()`'s
  error should offer `--all-sites` alongside `--site`. No phrase is common
  to all three — the help text says "more than one", the error says "holds
  N sites" — so check all five files, not one grep:

  ```bash
  grep -rn "sites" docs/support-files.md docs/usage.md unifi-map.1 \
    src/unifi_map/cli.py src/unifi_map/support.py
  ```

  `unifi-map.1` and the `docs/usage.md` table are generated, so fixing
  `cli.py` and running `make docs` covers two of the five.

- **Historical clients**, opt-in and visibly dated. Codex's caveat matches
  the rules here: an old association isn't evidence of where something is
  now, so a stale client must never be drawn as a current link, and if it
  can't be made obviously historical it shouldn't be drawn at all.

- **`overrides check`, validating selectors without rendering. Shipped.**
  Must build its topology with the same `--show-offline` the render will
  use — it originally passed `include_offline=True` unconditionally, more
  permissive than the default render, so a selector naming an offline
  device passed the check and then failed the render just checked for. The
  flag is now shared between the two subparsers rather than duplicated.

- **`overrides generate`. Shipped**, 2026-08-16 (KAN-120). `unifi-map
  overrides generate` prints a commented `overrides.toml` skeleton to
  stdout, seeded from unplaced clients, shared switch ports (KAN-199) and
  ambiguous artwork matches — the same three signals `--report` already
  names, closing the loop that section described as half open; `--report`
  now points at it from all three. `overrides.generate_candidates()` is the
  pure function; `cmd_overrides`'s `generate` action just prints its
  result, resolving artwork offline and best-effort the same way `unifi-map
  shape` does, so it never touches the network and a catalogue miss can't
  stop it printing what it found. A subcommand, sibling to `overrides
  check`, rather than a `render` flag: this produces a config skeleton not
  a diagram, and being its own subcommand makes it opt-in for free — Jason
  asked for that explicitly, so nobody reaches it by accident.

  **The generated TOML was not actually safe to uncomment**, caught the
  same day by external review of cfcd2fe. A controller-supplied label went
  straight into the skeleton unescaped: a `"` in a switch named `Core "A"`
  broke the surrounding `name = "..."` value the moment the block was
  uncommented, generating invalid TOML. Worse, a raw newline in a label
  would have ended the `#` line it sat on and let whatever followed be read
  as real TOML unreviewed — a genuine break of "inert until edited", the
  one promise this command makes. Fixed with two helpers in
  `overrides.py`: `_comment_safe()` collapses whitespace (same technique as
  `render_mermaid._flatten()`, reused not reinvented) so nothing can end
  the line it sits on, and `_toml_value()` additionally escapes `\` and `"`
  for quoted values. Applied everywhere a label or id reaches the output
  (MACs are equally attacker-controlled; `_norm_mac()` never validates
  shape), not just where the repro hit. Six tests pin it, including one
  that parses the *entire* generated file with `tomllib` and asserts it
  comes back empty.

  **A cold artwork cache read as a clean result**, raised by Jason directly.
  Ambiguous-artwork matching needs the UniFi hardware catalogue, resolved
  offline-only like `shape`; on a cache that never had a `render --icons
  unifi` or `fetch` run against it, the catalogue simply isn't there, so
  the check silently never ran and an empty `[[node]]` section looked
  identical to "checked, nothing ambiguous" — the same failure already
  fixed once for `--report`/`shape`'s artwork counts, not carried over
  here. Fixed by checking `AssetStore.catalog_path.is_file()` before
  resolution and threading that through to `generate_candidates(...,
  artwork_catalog_cached=...)`, printing an explicit `NOTE` when the cache
  is cold. Jason's stated principle going forward: err toward verbosity
  over letting something slip past an unknowing user.

- **`-q`/`--quiet`. Shipped, 2026-08-16.** Direct consequence of that
  principle: verbosity-by-default is only sustainable if the person who
  doesn't want it can turn it off. Raised by Jason right after the
  cold-cache `NOTE` above; `-v`/`--verbose` already existed so the opposite
  needed no debate about naming, only about what "quiet" means here.

  **Maps to `logging.ERROR`, not the more common "drop INFO, keep
  WARNING."** The warnings added all night (shared ports, unplaced clients,
  the cold-cache note) are steady-state network observations, not
  "something changed" alerts — no diff/history mechanism yet (KAN-116/117)
  distinguishes the two, so a recurring cron run sees the identical warning
  every invocation. That's exactly the noise `-q` exists to silence, which
  only follows if it silences warnings too.

  **`-v` and `-q` are refused together rather than one winning**, read
  straight from raw `argv` in `main()` before parsing starts, same place
  and reason `-v` already was: logging must be configured before parsing
  can fail nicely. Extracted into a pure `_log_level(argv) -> int | None`
  (`None` meaning "refuse") so the decision is unit-testable without
  touching global logging state — `logging.basicConfig()` no-ops if the
  root logger already has handlers, which it always does under pytest, so
  asserting on `main()`'s actual side effect would test pytest's own
  logging plugin more than this code. `test_nothing_identifying_reaches_
  the_log_either` sidesteps the same trap with `caplog.at_level(...)`.

  **Implies `--no-progress`** — a spinner is interactive narration exactly
  like the log lines `-q` suppresses, with no flag to turn it back on, so
  `_apply_quiet()` just overwrites `args.progress` after parsing.

  **Does not, and should not, touch printed output.** `--report`, `shape`
  and `overrides generate` all `print()` to stdout rather than logging
  (deliberate: `--report > file` captures the report alone while progress
  still reaches the terminal), so `-q` has no reason to reach them — the
  help text says so explicitly, after a first draft wrongly claimed it
  would suppress `overrides generate`'s cold-cache `NOTE`, caught by
  rereading the help text against the actual code.

- **Mermaid export. Shipped, as `-f mermaid`.** Necessarily loses artwork —
  it's the shape of the network and nothing else, and the docs say so. Its
  direction follows `--layout` (`unifi` gives LR, `tree` gives TB) and it
  emits a `title` front matter block; `docs/output.md` embeds the `tree`
  output with the front matter stripped, and a test diffs the embedded block
  against real output so that claim can't rot.

- **An interactive HTML viewer. Shipped, as `-f html` (KAN-126), 2026-08-07.**
  Collapsible client subtrees address the exact problem the tool exists for
  — a switch with thirty clients is unreadable in any static format — and
  path highlighting is genuinely useful on a busy map.

  **The dependency question was reopened and answered the other way.** This
  file previously said vendoring a pan/zoom library "sits badly beside the
  rule against vendoring anything else" and leaned toward hand-rolling — a
  false equivalence, caught by Jason: the no-vendoring rule is specifically
  about **Ubiquiti's copyrighted product artwork**, an IP restriction, not a
  stance against third-party code existing at all. A small,
  permissively-licensed, dependency-free file is a different category, and
  reinventing pan/zoom (momentum, pinch, edge-case math) is exactly where
  "janky" comes from. Shipped as `vendor_panzoom.py`:
  [Panzoom](https://github.com/timmywil/panzoom) 4.6.2, MIT, pinned to the
  release commit rather than a mutable tag (same reasoning as CI action
  pins), checked to have zero runtime dependencies of its own. A CDN pull
  was rejected outright: it would add a live external-host dependency and
  break `--offline`.

  **Node and edge correlation is computed in Python, not guessed in
  JavaScript.** Graphviz's SVG writer already gives every node/edge group a
  `<title>` holding `render_dot._node_id()`'s output; `render_html.py`
  computes the same string and stamps a `data-id` (or
  `data-parent`/`data-child`) holding the *real* topology id directly onto
  the matching `<g>` — JavaScript never reconstructs the DOT-safe encoding.

  **The topology payload is base64-encoded, not a JSON literal in a
  `<script>` tag.** A label can come from a controller or support file, both
  hostile input by this project's rule elsewhere, and a literal `</script>`
  in a label would end the block early regardless of JSON escaping. Base64
  has no text content for a crafted string to break out of.

  **The interaction model is a single click, split by what was clicked**,
  rather than a separate collapse control layered on the SVG: clicking a
  client highlights its path to the root, clicking a switch or AP with
  client children collapses them. A badge positioned over a Graphviz-placed,
  pan/zoom-transformed node was considered and dropped — CSS generated
  content doesn't composite reliably inside an SVG `<g>` across browsers,
  and the geometry math wasn't worth it for what one click target already
  gives free.

  **Dimming, not colour, carries both search and path-highlight.** Colour
  is never the only channel here, and opacity satisfies it for free: full
  opacity means "in the current selection", `0.15` doesn't, independent of
  hue, reading the same in greyscale or under deuteranopia.

  **Reported "janky" 2026-08-07 — two real bugs, not a vague complaint.**
  Verified with the actual pan/zoom math, not by eyeballing a screenshot: a
  screenshot via this project's own browser tooling can look identical
  whether the fix landed or not, since the automated tab is frequently
  `document.hidden` and Chrome suspends `requestAnimationFrame` for hidden
  tabs — exactly the step Panzoom defers its transform write through. The
  fix was patching `requestAnimationFrame` to run synchronously and
  re-check.

  1. **Every wheel event zoomed, including a plain two-finger swipe.** A
     trackpad swipe and a mouse wheel fire the same `wheel` event shape, and
     the first version treated all of it as zoom, inverting the gesture
     every trackpad user has. Fixed by reading `event.ctrlKey`, which
     browsers set on their own for a trackpad pinch; anything without it
     now pans via `panzoom.pan(..., {relative: true})`, scaled by current
     zoom so pan speed stays constant on screen.
  2. **`contain: "outside"` fought the pan it was meant to merely bound.**
     The svg is styled `width:100%;height:100%`, always filling its
     container regardless of zoom, so Panzoom's containment math (natural
     size = bounding box / scale) always computed natural size equal to
     container size, leaving no slack before containment clamped straight
     back to the origin. Removed entirely — panning into empty space is
     normal for a canvas viewer.

  Zoom-to-cursor accuracy was verified directly: screen position of a node
  under the cursor before/after a zoom differed by about 0.01px.

- **Location and rack grouping via overrides.** Philosophically the best fit:
  a controller can't know which rack something is in, precisely what
  `[[device]]` and friends are for. The unknown is rendering — Graphviz
  clusters interact badly with `--layout unifi` (`rankdir=LR` with ortho
  routing), there's already a legend cluster in `tree`, and the `unflatten`
  stagger pass hasn't been tried against nested clusters. Prototype the
  layout before committing to the schema.

- **Link and wireless metadata overlays.** Partly specced: the
  infrastructure view below covers speed/media colouring, and
  `port_table[].speed`/`.media` are verified present on a live snapshot —
  fold that half in there. The wireless half (RSSI, band, channel width) is
  **not verified**: the demo dataset carries only `essid`/`radio_name`, and
  is synthetic, so its silence proves nothing. Check a live `stat/sta` first.
  **`--color-by vlan` conflicts with a standing rule**: colour is never the
  only channel here, so grouping by VLAN needs a second channel (cluster,
  node shape, border style) or it breaks that promise.

- **OpenBao credential backend.** Already anticipated: `config.py` is the only
  module that reads the environment specifically so this stays a single-file
  change, and its docstring says so.

  **Not blocked.** First written up here as waiting on a Vault instance to
  exist. It already does: OpenBao has been live at `vault.bhomelan.com`
  since 2026-07-24, initialised, unsealed, AppRole auth verified, with a
  pilot secret migrated. `homelab-apps/scripts/render_secrets.py` is the
  pattern to copy. When built, the key must still never reach `os.environ`
  — `layout.py` strips credential variables from Graphviz's environment
  precisely so an exported key can't leak that way, and a backend that
  helpfully exports what it fetched would undo that silently.

- **NetBox/IPAM export: subsumed by the JSON export above, not declined.**
  First written up as declined on three grounds, one of which doesn't
  survive scrutiny and is recorded so the argument isn't reused. What
  holds: mapping onto NetBox's model is lossy and opinionated (is a
  wireless client a Device? is an association a Cable?), and means tracking
  another project's API across breaking majors — nothing in this homelab
  runs NetBox, Nautobot, phpIPAM or RackTables, checked against the app
  inventory. What doesn't hold: "no second use case justifies the
  abstraction" — a NetBox export is an output format, not an abstraction,
  exactly like the welcomed Mermaid export; that reason reached for a rule
  that didn't apply. The real answer is the normalised JSON export: the
  proposal was structured JSON of connections, roles and port mappings *for
  importing into* NetBox, which is that export with a NetBox-shaped schema
  — once it exists, a NetBox user writes a short transform against our
  stable schema instead of us tracking theirs. One line worth keeping
  either way: an export is fine, a **sync** is not. `session.get` being the
  only HTTP verb in the source is a headline property, and creating or
  updating objects in somebody else's system would end it.

### Diagram-as-code turned out to already work, and stayed a side effect

Jason's question, 2026-08-16, right after `-q`/`--quiet`: since
`overrides.toml` can declare a device the controller can't see, could
someone skip the controller entirely and draw an invented network? Checked
by doing it: three hand-written JSON files reporting empty lists
(`{"data": []}`) satisfy `Snapshot.read()`, `[[device]]` +
`[[link]]`/`[[hosted]]` populate the whole `Topology`, and
`render_dot`/`render_drawio` draw it, custom artwork included. Works today,
unmodified, because the renderer is a pure function of a `Topology` and
never asks where one came from.

**Not pursued as a goal.** Jason was explicit before asking what was
stopping it: not "should this become a feature" but "can we mention it
exists." Becoming a real generic diagramming tool competes in a market this
project has no reason to enter (D2, Structurizr, plain Graphviz) and would
mean stretching `Kind` past what a UniFi console actually shows.

**Documented instead**, as loudly labelled as everything else here is
carefully labelled: `docs/diagram-as-code.md`, linked from the README's
documentation table and from the Overrides bullet as an aside, not a
headline feature. Says twice — top and last line — that it's a side effect,
never officially supported, and explains why: nothing here is designed or
tested for a zero-real-data path, so a future change could break it without
that counting as breaking from this project's point of view.

**The example uses deliberately silly custom artwork on purpose**, per
Jason's request — a Pillow-drawn "Trash Router" / "Toaster Switch" /
"Sentient Toaster" / "PoE Bidet" / "Grandma's iPad (2011)" / "Smart
Toothbrush" network, committed as `docs/images/example-diagram-as-code.png`.
The bidet and toothbrush aren't a second joke: they're the exact pair
`docs/overrides.md` uses to explain why a fingerprint match can be
confidently wrong, so the callback is intentional. Not decoration otherwise:
a clean-looking invented topology would invite something resembling a real
product diagram out of data no controller ever reported — the "Never invent
topology" failure mode, just self-inflicted.

**Two claims the page makes are pinned, not just asserted**:
`tests/test_diagram_as_code.py` renders the documented three-file
workflow end to end, and `test_overrides.py::TestDeclaredDevices::
test_kind_internet_is_refused` pins that `[[device]]` cannot declare
`kind = "internet"` — `Kind.INTERNET` is excluded from `_parse_devices`'s
valid set since that node is only ever synthesised from a real device's
real uplink, previously untested anywhere in the suite.

**A per-link line-style override was raised immediately afterward and
declined on the spot, correctly for the wrong first reason.** Jason's
instinct was to resist it as "incredibly difficult"; checked and that's
false — same shape as every other optional override field, a few hours of
work at most. The real reason to decline holds regardless of cost: dotted
guarantees an asserted edge can never be mistaken for a controller-reported
one, and the renderer can't tell a real map from a fabricated one, so it
can't carve out an exception without weakening every other override.
Recorded so effort-estimate is never the reason this gets re-proposed. The
pressure valve for anyone who wants it anyway, outside this project:
`sed 's/style=dotted/style=solid/'` on the `.dot` or `.svg`. Documented at
`docs/diagram-as-code.md`'s "What does not work" section.

### Splitting `cli.py`. Done, and the reason was never length

Raised by both external reviewers, twice, as "it is ~1350 lines". Length was
the symptom and a poor criterion: splitting a long file by line count
produces `commands.py`/`writers.py` that nobody can predict the contents of.
The real complaint was layering — the tell arrived during the drawn-icon
work, when a rendering test had to `from unifi_map.cli import
_apply_drawn_icons`, reaching through the CLI to get at the renderer.

Split in 0.9.0 into **two** modules, not the one this section previously
guessed at: **`artwork.py`** resolves nodes to images (knows `AssetStore`
and the three-source fallback order, imports no renderer), and
**`output.py`** writes files (paths, atomic replacement, overwrite guard;
imports every renderer). One module holding both would've been a bag of
things that happened to leave `cli.py` together — they share nothing, so "a
reason per file" is satisfied, the actual criterion rather than module
count. `cli.py` keeps argument parsing, credential resolution, logging setup
and the `cmd_*` functions, going 1367 → 1027 lines. `obtain_icon_font()`
also stopped taking an `argparse.Namespace`, now takes the three settings it
actually reads — the layering fix in miniature: a pipeline function should
be callable without constructing a parser.

`cli.py` still holds `GLOBAL_DEFAULTS` and the `_Parser` subclass, subtle
enough to have their own warnings here — leave them together. Don't go on
to the three-way `cli/` package the reviews suggested without a reason per
file.

### One machine, several nodes, and why `[[merge]]` is not the answer

A host with interfaces on several VLANs draws as several clients. Raised
2026-08-14 by Jason, who sketched a `[[collapse]]` override with repeated
`duplicate =` keys. Not built.

**Three corrections to the sketch, before the real objection.** Repeated
keys are a hard TOML parse error, so it'd have to be an array. `collapse`
already means the HTML viewer's collapsible subtrees (KAN-126). And
"duplicate" is the wrong noun: these are three real interfaces the
controller reported correctly, and this project's whole posture is that the
map never implies the controller was mistaken.

**The real objection is the model, not the syntax.** A merged node belongs
to every network its interfaces are on; `Node.network` holds one value and
`--per-network` filters on it, so serving the combined view means making
that plural. Two further cases would need refusing: interfaces on
different uplinks (breaks the tree assumption in `--layout tree` and the
draw.io coordinate pass), and merging a node with its own ancestor (a NAS
behind its own host's NIC, which would create a self-loop).

**`--per-network` already solves it**, verified: on the reference network
TrueNAS has three interfaces, all locally-administered, one uplink:
`bhomelan` (no address), `bhome-iot` (192.168.7.27), `servers`
(192.168.20.27). Rendered with `--per-network`, each slice contains exactly
one, correctly placed and addressed — duplication exists only in the
combined map.

The framing to keep is **logical versus physical**: the controller reports
what's reachable, never what shares a chassis, so a physical map isn't
derivable from it. A "physical mode" would just be the merge feature under
another name.

The signature is detectable, and that's worth building instead: a
multi-homed host's interface usually has a locally-administered MAC and
empty OUI, while genuinely distinct devices behind an unmanaged switch have
neither. Both groups separate cleanly on that test on the reference
network, safe for `--report` to mention (KAN-199) and for the candidates
generator to act on (KAN-120).

**The generator shipped 2026-08-16 and does not yet act on this signature.**
`unifi-map overrides generate` (`overrides.generate_candidates`) covers the
three signals `--report` already names — unplaced clients, shared switch
ports, ambiguous artwork — none of which distinguish a multi-homed host from
a genuinely hidden switch. Using the locally-administered-MAC test to
annotate or split the shared-port candidate block is still open.

### Gaps worth considering

- **`has_unknown_switch` is in the v2 topology payload and we ignore it**
  (KAN-199). The payload has three top-level keys, `vertices`, `edges` and
  `has_unknown_switch`. We read two.

  Observed on the reference network: `false` with two clients on the
  Netgear's port, `true` after a third was plugged into the same switch.
  **One before/after observation with unknown uncontrolled variables** —
  hints at a controller-side threshold above two, doesn't establish one; do
  not write a threshold down. Solid: the field exists and went true on a
  network that provably has an unmanaged switch.

  **There is no matching vertex.** The flag says one exists somewhere,
  never where — why it pairs with the heuristic below rather than
  replacing it. Unverified: whether it's per-site, whether it clears,
  whether an all-UniFi network ever sets it.

- **Several wired clients on one switch port means something is hiding
  there. Shipped**, the shared-port half of KAN-199, 2026-08-16. Found
  2026-08-14 when Jason remembered a Netgear PoE switch the map had been
  drawing wrong since the map existed.

  **The controller cannot see that switch at all**: no device entry, client
  entry, LLDP entry or v2 topology edge — both things behind it report as
  sitting directly on port 7 of the USW Pro HD 24 PoE, so that's what we
  drew. The signal was in the data the whole time: **two wired clients
  reporting the same `sw_mac` and `sw_port`**, where every other occupied
  port on that switch has one. Two corroborating facts too weak to trigger
  on but worth quoting when present: `poe_enable = false` /
  `poe_power = 0.00` behind a running PoE camera, and 1000 Mb negotiated on
  `2P5GE`-capable media — neither is implemented, only the shared-port
  count is.

  **This is the general answer that LLDP is not**: LLDP needs the foreign
  device to advertise and this one doesn't, while a shared-port check needs
  nothing from it. See the LLDP entry above for the full correction.

  **Report it, and flag it, but never draw a node for it.** Several MACs on
  one port means an unmanaged switch *or* a virtualisation host with
  bridged guests (`topology_uplinks()`'s docstring names both), and
  synthesising a switch that might be a hypervisor is inventing topology,
  so no node is ever added. `--report` names the port and lists the
  clients in a `SHARED SWITCH PORTS` section
  (`diagnostics._shared_ports_section`); the diagram marks the same edges
  with a plain `*` on the port label plus a legend row in the
  DOT/SVG/PDF/PNG backend, and the label marker alone in draw.io.

  **The `*` alone shipped invisible in the default render**, caught the
  same day by external review. `--layout unifi` is the default and
  suppresses port labels entirely (`Style.show_port_labels`, since ortho
  routing can't place them without drift) and the legend too — so on the
  render most people produce, the `*` and its legend row were both gone,
  though detection/reporting/logging still worked. Fixed by giving the
  edge its own layout-independent channel, `arrowhead=diamond`,
  unconditional rather than gated on `show_port_labels`, same as
  `TOPOLOGY_GRAPH`'s `arrowhead=odot` (the two never collide since
  `shared_ports()` only counts direct `CLIENT_UPLINK` edges). The legend
  row stays gated on `show_legend`, matching every other marker. draw.io
  needed no equivalent fix — it has no `show_port_labels` concept.

  `cmd_render` also warns on the console once per shared port
  (`_hint_about_shared_ports`), obfuscation-aware like
  `_report_displacements`: named normally, a bare count under
  `--obfuscate`. All four read from one `Topology.shared_ports()`,
  restricted to direct `CLIENT_UPLINK` reports (a `TOPOLOGY_GRAPH`-inferred
  edge never counts) and computed against the *final* topology, so a
  `[[hosted]]` override reparenting a client off the shared port already
  resolves it.

  A merged single line splitting into several clients was proposed and
  dropped the same conversation: it needs a real junction node in the DOT
  graph and draw.io coordinate pass, and a junction dot reads as "there's a
  device here" exactly as much as a synthesised switch would.

  Count only `Kind.WIRED_CLIENT` — wireless clients share an AP by
  definition, same reasoning that scoped KAN-129's count to clients.

- **The API key was in `ExporterConfig`'s generated repr. Fixed in 0.12.0**
  (KAN-198). Spotted 2026-08-14 in `merlijntishauser/unifi-topology`, which
  declares its credentials `field(repr=False)`. A frozen dataclass reprs
  every field, so `repr(CONFIG)` rendered the live key.

  **Defensive, described that way rather than dressed up.** Nothing in
  `src/` reprs, formats or logs the config; `-v` doesn't enable
  `http.client` debug and urllib3 at DEBUG logs the request line, not
  headers; an ordinary traceback doesn't print frame locals. There was no
  path then and the fix doesn't close one — it buys that none can open
  later, from a pytest assertion diff, a `--showlocals` traceback, or a
  well-meant `log.debug("config: %r", config)`.

  It shipped in 0.12.0 rather than waiting, after Jason questioned an
  initial deferral (on the grounds the release had already grown): the
  change is two lines, fully specified, and `RELEASING.md` says security
  fixes shouldn't sit unreleased. Deferring nearly-free hardening for
  tidiness is a bad trade. Same family as `config.py` never writing the key
  into `os.environ` and `layout.py` stripping it from Graphviz's
  environment; the session's `X-API-KEY` header is a separate surface,
  deliberately not folded in.

- **User-written port names, and the obfuscation trap they set** (KAN-197).
  Found 2026-08-14 reading two other UniFi mappers, `ScottiBYTE/
  unifi-topology` and `merlijntishauser/unifi-topology`.

  **The controller already holds port labels and we read none of them.**
  `port_table[].name` is a generic "Port N" on 75 of 79 ports here, while
  `port_overrides[].name` carries a user-written label on 26 — referenced
  zero times in `src/`, though `fetch` already stores it. Same records
  carry `native_networkconf_id`/`excluded_networkconf_ids` (per-port VLAN,
  feeds KAN-118/KAN-123 off the same join).

  **`obfuscate.py` treats nodes and edges oppositely, and only one side is
  written down.** Edges are built field by field, so a new field is
  silently dropped (already bit us with `asserted`). Nodes go through
  `replace(node, ...)`, so **any new `Node` field passes through
  `--obfuscate` unchanged**; `Edge.label` passes through too. Nothing
  leaks today since every identifying node field is handled explicitly and
  `Edge.label` is "port 12" — a user-written port name is the first value
  that breaks it. The guard lands in the same change as the feature, never
  after.

  **The LLDP half of this was measured wrong first, and the mistake is the
  useful part.** The first pass checked `port_table[].lldp_table`, found
  it empty on all 79 ports, and wrote "no LLDP here" into a ticket. The
  device-level `lldp_table` is a different field, present on 10 of 14
  devices with 20 entries, every one carrying `local_port_name`. Not
  merely premature — recorded as settled fact in a place built to stop the
  question being re-asked. When a payload field is empty, check whether
  the same name exists at another level first.

  **Then it was wrong a second time, in this file — that correction is the
  one worth keeping.** This file said LLDP couldn't be evaluated on an
  all-UniFi network. Untrue: a Netgear PoE switch sits on port 7 of the
  USW Pro HD 24 PoE with a camera and receiver behind it. The network had
  a counterexample all along; nobody had asked the data.

  **LLDP does not see that switch either.** The USW Pro HD 24 PoE
  advertises neighbours on eleven ports (1-6, 8, 13, 24, 25, 27); port 7
  isn't among them, since the Netgear doesn't advertise. Of the 20 entries
  that do exist, 19 are devices already in `stat/device` and the twentieth
  is a Dell already drawn as a client.

  So LLDP is narrower than it looks: it finds a **managed** third-party
  switch that advertises, nothing else — not the general answer to
  "something is between the controller and this client". KAN-199 is,
  since a shared port needs no cooperation from the hidden device. Still
  `needs-real-world-data`, now for a precise reason: needs an
  LLDP-advertising non-UniFi switch, and the one on site doesn't advertise.

- **A `serve` subcommand, a self-refreshing live view** (KAN-196). Raised by
  Jason 2026-08-14, marked *consider* rather than *do*, same sense as
  KAN-130. `-f html` already produces an interactive viewer; the question is
  whether to hold an HTTP listener open, re-poll on a timer, re-render.

  **The objection to answer first: live polling requires controller
  credentials, and anyone holding those can open the console, which already
  has a live topology view.** This project's value is in what the console
  can't do (publish, obfuscate, annotate, diff, print, commit) — a live view
  is the one thing the console is already better at. If nothing answers "why
  not just open the console", close it rather than build it. What survives:
  a live map carrying **overrides** (the console will never show an
  unmanaged switch typed into `overrides.toml`), and a kiosk that isn't a
  logged-in console session left open on a television.

  **The cost isn't where it looks.** Rendering is cheap — `render -f html`
  against `examples/demo` (60 nodes, warm cache) measured ~0.3s for an 852
  KiB file — a floor, not a real-network figure. The expensive half is the
  controller fetch. **The real problem is state loss on refresh**: every
  piece of viewer state in `render_html.py` (pan, zoom, search, collapsed
  subtrees, highlighted path) is DOM toggles plus Panzoom's transform, none
  persisted, so a timer reload destroys it all — worse than the static file
  it replaced. More tractable than it reads, though: collapse state is
  keyed on the stable topology id, Panzoom exposes `getPan()`/`getScale()`,
  and the toolbar lives outside the SVG, so swapping only the `<svg>` and
  restoring is a small amount of JavaScript plus a "has it changed"
  endpoint — an estimate from reading the file, not measured.

  Costs being taken on: a long-lived process holding the API key (today a
  credential's lifetime is one command); repeated authenticated polling in
  an environment whose IDS already flags legitimate monitoring traffic;
  coupling `fetch` and `render`, split precisely so render repeats offline;
  and serving a full MAC/hostname/IP inventory over HTTP, making a
  `127.0.0.1` default and a loud warning on any other bind mandatory.
  Refresh interval belongs in minutes, not seconds.

  **The dividend is KAN-116**: a serve loop retaining timestamped snapshots
  is the retention prerequisite KAN-117's `diff` is blocked on.

  The cheap alternative, worth pricing first: `unifi-map all` from cron into
  a directory with a plain static file server in front — no new code, no
  resident credential, at the cost of losing viewer state every refresh.

- **The controller path now has the same response cap the CDN path does**
  (KAN-134, done). The capped-read guard moved out of `assets.py` into
  `httpio.py`, a sibling of `fsio.py`, so the two callers can't drift apart:
  `client.py`'s three fetch paths stream through it with a 64 MiB ceiling and
  refuse an oversized response out loud, as `assets.py` always did for the
  CDN. Same threat model as `_Session.rebuild_auth` stripping the key across
  a host-changing redirect — the controller is ordinarily reached with
  `UNIFI_VERIFY_TLS=false`. Low severity; consistency was most of the
  argument.

- **KAN-136 (an automated review tool that stays free) and the SAST question
  in TODO.md are resolved together, 2026-08-06.** Greptile, connected
  2026-08-03 hoping for an open-source licence, never resolved to more than a
  14-day trial with no reply to the application. A tool that lapses silently
  is worse than none, so dropped rather than left to expire.

  In its place: **CodeQL**, `.github/workflows/codeql.yml`, on push to
  `main`, every pull request, and a weekly schedule. Answers both questions
  at once — free for public repos with no time limit, no application step,
  runs on PRs, no write access granted, nothing sent outside GitHub, no
  account/trial state to monitor. It's a genuine data-flow security scanner
  (injection, unsafe deserialization, path traversal), distinct from
  SonarQube Cloud's general code quality/complexity in `ci.yml`.
  `security-events: write` is scoped to that one workflow only.

  Not a required status check alongside `Python 3.11/3.12/3.13` and
  `Repository hygiene` — same reasoning as `Dependency advisories`: a
  security finding should start a conversation, not block an unrelated PR
  while the job is still settling in.

- **Provenance and confidence. Shipped, as the KAN-137 rendering change.**
  The data existed since KAN-115 (`Node.provenance`/`Edge.provenance`,
  `--report` reads it); the **diagram** didn't show it — `asserted` got a
  dotted line and nothing else distinguished observed from inferred, so a
  client placed from the v2 topology graph and one from `stat/sta` drew
  identically.

  **The scope turned out narrower than it first read.** Re-reading the
  `Provenance` enum showed most needs no new channel: node provenance
  (`DEVICE`/`CLIENT`/`SYNTHETIC`) is already carried by `Kind`, and
  `asserted`/`offline` cover the rest. `UNPLACED` edges already terminate
  at the diamond-shaped `UNKNOWN_UPLINK_ID` placeholder; `OVERRIDE` was
  already dotted. One real gap: `TOPOLOGY_GRAPH` edges — a client placed
  via the controller's v2 graph because what it's plugged into isn't UniFi
  and never reported `sw_mac`/`ap_mac` — were indistinguishable from a
  directly reported edge.

  **Line style was already spent** (dashed wireless, dotted asserted), so
  the new distinction is a hollow-circle arrowhead at the child end:
  `arrowhead=odot` in DOT, `endArrow=oval;endFill=0` in draw.io — both
  backends left edges arrow-less before, so the channel composes rather
  than competes with dashed/dotted. `_legend_link_rows` grew a fourth
  conditional row, matching the "Stated in overrides" pattern.

  Not carried, on purpose: a fingerprint recovered from a client's *name*
  (support-file path) isn't distinguished from a controller-reported one —
  `Provenance` describes how a node was placed, not identified.

- **A reconciliation report. Shipped as `--report`**, see KAN-115 above. It
  enumerates what didn't match, not just counts it: unplaced clients,
  addressless clients, dangling network references, refused ambiguous
  artwork matches. This entry previously said such a report "would have
  caught at least two of the wrong conclusions recorded here" — the
  argument for building it, worth keeping as the measure of whether it
  earns its place.

- **Randomised client MACs are not a concept the join layer knows about, but
  `--report` now says so. Shipped** (KAN-129). Every join here is on MAC,
  so a phone rotating its address appears as a new, unrelated client —
  explaining an apparent duplicate was the whole ask.
  `diagnostics._is_locally_administered()` checks IEEE 802's
  locally-administered bit on each client's MAC, which randomisation sets
  and a vendor-burned address doesn't, needing no cooperation from the
  controller.

  **Counted, not named**: an unplaced client or one with no address is a
  specific problem an overrides file can fix, a rotated MAC is neither, and
  naming a device would imply an action the reader can't take. Only
  clients are counted, not infrastructure — this project's own demo and
  test fixtures use locally-administered MACs too (the `02:` prefix, so a
  fake address doesn't resemble a real vendor's), and devices don't rotate
  their MAC regardless, so `Kind.WIRED_CLIENT`/`WIRELESS_CLIENT` is correct
  on both grounds.

- **Nothing has been profiled on a large site.** The joins are
  dictionary-based and probably fine, but `sysid_for_name()` scans the
  catalogue per candidate. Check before claiming it scales.

- **Dependency lock file: reversed 2026-08-13, by Jason directly, not a
  reviewer.** `requirements/ci.txt` is a hashed lock (`pip-compile
  --generate-hashes`, KAN-191), covering everything CI installs: `dev`/`svg`
  extras plus `pip-audit` (folded in via `requirements/ci.in` since
  pip-compile's `--extra` can't reach it, not being a dependency of this
  package). `make lock` regenerates it. `ci.yml`'s three `pip install` sites
  now read `--require-hashes -r requirements/ci.txt`; the local package is a
  second, unhashed `--no-deps` install, since `--require-hashes` rejects
  editable/local installs outright.

  Below is the original decline and every attempt to revisit it — kept
  because the reasoning that finally moved it is worth knowing; none of the
  earlier attempts held up, and this one answered the actual objection
  rather than reversing the decision outright.

  **Original, deliberate for now:** hashed constraints are ongoing
  maintenance for a dev-only benefit, and Dependabot covers staying current.
  Revisit if this ever ships releases people install.

  This used to say "Dependabot **and the advisory job**" cover staying
  current — half untrue at the time, since the advisory job had never
  reported anything. Dependabot alone still carried the argument, but a
  decline resting partly on a control that doesn't work is worth noticing.
  **The job was repaired (KAN-132), so both halves hold again.**

  Briefly reopened 2026-08-03 on the argument that the benefit stops being
  dev-only once people install this. **Wrong** — it only holds for a
  *published* package, and `make build` producing a local wheel doesn't
  change the exposure. This was the declined security-review finding
  `SECURITY.md`/`AI_DISCLOSURE.md` pointed here for; both now say it was
  reversed.

  **What actually moved it, 2026-08-13: an OSSF Scorecard run scored
  Pinned-Dependencies at 5/10 over these exact `pip install` calls.**
  Jason's question was not "accept the maintenance cost" but "can it be
  automated the way `dependabot-auto-merge.yml` already automates version
  bumps" — and it can: Dependabot's `pip` ecosystem recognises pip-compile's
  header comment and re-runs compilation, the same tool the decline already
  leaned on. The dev-only-benefit half of the objection never weakened; the
  maintenance half turned out already solved by infrastructure this repo
  had for another reason.

- **No coverage threshold. Declined 2026-08-03**, suggested by external
  review. A number that gates the build makes the cheapest way past a
  failing build a test written to move the number — exercising lines
  without asserting anything worth asserting, indistinguishable in a report
  from a test that would catch a regression. This repository has already
  produced two tests that couldn't fail, both found by reading rather than
  by metric, and a threshold would have counted both as coverage. What's
  wanted is that risky surfaces are tested, known by name: archive parsing,
  override resolution, obfuscation, output escaping, the overwrite guard —
  each has adversarial tests aimed at a specific failure. **Measuring**
  coverage isn't declined, only gating on it.

- **Static type checking is declined.** Jason's decision, 2026-08-03. Do not
  add mypy or pyright to `pyproject.toml`, the Makefile, the CI workflow or
  a pre-commit hook.

  **Type annotations stay and are not the thing being declined** — for
  readers and editors, legible and autocomplete-friendly. Enforcement is
  what's refused. Sharper than the lock file's "permanent maintenance for
  an unmeasured benefit": a checker strict enough to be worth running wants
  annotations on the boundaries that deliberately accept whatever a
  controller sends, and that tolerance is a design property, not an
  oversight. `unwrap()` absorbs both envelope shapes and returns `[]` on
  anything unexpected precisely so a controller upgrade thins a diagram
  instead of raising — typing those payloads would write down shapes this
  project refuses to rely on, the same argument that declined `TypedDict`
  for them.

  **Raised by three external reviews across two rounds** — recorded at
  length so it isn't re-proposed a fourth time. A repeated suggestion is
  evidence it's common practice, not that it fits this project. One of
  those reviewers, told the decision, edited a checked-in `CLAUDE.md`
  unasked and had to be reverted — recording a decision is Jason's call,
  not a reviewer's.

- **We draw our own device icons. Shipped, in `drawn.py`.** Nine, not the
  seven first planned: five infrastructure keyed on `Kind` (gateway, switch,
  ap, bridge, unknown) and **four** clients keyed on `Node.glyph_name`,
  since guest and wireless are separate facts and the console's own font
  encodes all four. Drawing those four closed the icon-font dead end: that
  font is served only by a controller, so a support-file user with no
  console now gets icons rather than shapes.

  Used in `--icons builtin`, which no longer means "no artwork" but "artwork
  that is ours" (Internet cloud included), and as the `--icons unifi`
  fallback for hardware absent from Ubiquiti's catalogue — on the demo just
  one node, the unplaceable-uplink placeholder, so a normal map is
  unchanged.

  Three constraints held, each with a test: **real aspect ratios** (switch
  wider than tall by 3:1+, handset taller than wide, AP square);
  **silhouette carries the meaning** (guest is *hollow*, not a second hue,
  compared as an alpha mask so colour can't rescue it — no two icons share
  a silhouette); **cached per colour**, or a dark icon lands on a dark
  canvas.

  **The thing that nearly shipped broken**: `render_dot` discarded the
  icons dict entirely unless `style.icons == "unifi"`, a leftover from when
  `builtin` meant no artwork existed — icons drew perfectly and never
  reached the map, and the same gate was silently dropping user-supplied
  override icons too. Removed: the caller decides what's in the dict.

  Interior detail is punched with fully transparent pixels rather than
  overdrawn, since `ImageDraw` writes pixels rather than compositing — what
  makes a switch's ports and a hollow guest body possible in one colour.
  Not done, cheap if wanted: varying an icon by `model` (in the snapshot,
  e.g. `USL8LP` says eight ports, currently unused).

- **Infrastructure view.** The console has one, a different diagram rather
  than the client map with clients removed (all `--no-clients` gives
  today). Described from a screenshot of the real thing, 2026-07-30.

  What it shows, top to bottom:

  - **One card per WAN**, side by side above the gateway, each with the ISP
    brand mark, the WAN label ("WAN2 · Failover Only"), the public address and
    an uptime percentage. So the Internet is several nodes here, not one.
  - **A port badge at both ends of every link**, which is the biggest departure.
    A small rounded chip carrying an icon and the port number: a globe for WAN
    ports, a chevron down on the parent's side, a chevron up on the child's,
    and a literal `SFP` chip for fibre. Our maps label a link once, in the
    middle.
  - **Badge and edge colour encode link speed**, green/yellow/grey/blue, with
    the edge matching its badge.
  - **Device cards carry live stats**: CPU and memory percentages with small
    icons, and `STP Priority` where it applies.
  - **Offline devices are dimmed** and swap their stats for `Last Seen: 30d 3h`.
  - **An `STP Root` crown** on whichever switch holds it.
  - Edges are curved beziers, and there are no clients at all.

  Every one of those is already in `stat/device`, verified against the live
  snapshot rather than assumed:

  | Shown | Field |
  | --- | --- |
  | CPU, memory | `system-stats.cpu` / `.mem` (matched the screenshot's 3.8 / 78.7) |
  | Last seen | `last_seen`, epoch seconds |
  | STP priority | `stp_priority` |
  | STP root | `root_switch` holds the **root's MAC**; a device is the root when it equals its own `mac` |
  | Port at each end | `uplink.uplink_remote_port` for the parent's, and the topology graph's `downlinkPortNumber` / `uplinkPortNumber` |
  | Speed, media | `port_table[].speed` and `.media` (`SFP+`, `2P5GE`, `FE`) |
  | WAN cards | `stat/health` WAN subsystems, or `ispData` from a support file |

  **`Edge` is not shaped for it, though.** It carries `label: str | None`, a
  display string like "port 12", and the view needs a badge at each end
  with a port number, speed and medium — structured fields on `Edge`, label
  derived from them, is the change that has to come first (Codex noticed
  this). Otherwise this is a rendering job: the parts needing thought are
  the two-badges-per-edge layout (Graphviz has no direct notion; head/tail
  labels are closest) and whether this becomes a third `--layout` or a
  separate output.

- **Building an artifact and publishing one are separate decisions.**
  Briefly conflated here 2026-08-03 as "0.9.0 commits to `pip install
  unifi-map`" — wrong on both halves: promised something nobody had agreed
  to, and treated a local build as though it needed PyPI.

  **The local build is done**, needing almost nothing since the entry point
  and build backend already existed: `make build` produces a wheel and
  sdist, `pip install dist/*.whl` into a clean venv works, the console
  script runs, `importlib.metadata.version` agrees with `__version__`. All
  verified.

  **Publishing to PyPI stays undecided, not blocked on effort.** Means
  owning the name and never breaking a published version once someone
  depends on it — a commitment, not a chore. Don't record it as decided
  without Jason saying so; he's said explicitly he isn't ready for the
  commitment. **"Not happening any time soon", stated 2026-08-03** — a
  timing position, not a permanent decline, so it stays open in `TODO.md`.
  Publishing workflows, trusted publishing, Sigstore/SLSA attestations and
  PyPI-shaped packaging metadata are all out of scope; don't add any
  speculatively. Local `make build` artifacts are the whole packaging story
  for now.

  **The lock-file decline stands** — briefly reopened on "the benefit stops
  being dev-only once people install this", which only holds for a
  *published* package. A locally built wheel doesn't change it.

  **The man page is in the wheel as of 0.10.0**, via
  `[tool.setuptools.data-files]` pointing `share/man/man1` at the committed
  `unifi-map.1`. Turned out not to be "on the publishing side of the line":
  needs no PyPI, owned name, or future-version promise, only a wheel that
  exists somewhere, which a GitHub Release already gives it. Verified three
  ways: `man unifi-map` resolves with no `MANPATH` set right after
  activating a venv the wheel installed into, the file survives into the
  sdist, and a wheel built *from* that sdist still carries it.

- **The `UDM_*` environment aliases are gone**, removed in 0.9.0 after
  warning since 0.7.0. `config.py` reads one name per setting; a
  `UDM_*`-only credential file now gets the ordinary missing-configuration
  error, the right failure since the old name is no longer part of the
  interface.

  **`layout.py` still strips `UDM_API_KEY`** from Graphviz's environment,
  deliberate asymmetry: not reading a variable does nothing about someone
  who still exports one, and an unread variable holding a real key is
  exactly as worth withholding from a child process as a read one. A test
  pins it staying in `_CREDENTIAL_VARS`.

**The man page is done**, as `unifi-map.1`, generated by
`scripts/generate_manpage.py` and checked for staleness like the flag
reference. Two things worth not relitigating: **`argparse-manpage` was
tried and dropped** — its API is `Manpage(parser)` and little else, every
global option attaches to every subparser via `parents=` (printing all
fifteen three times over), and there's no hook for ENVIRONMENT, FILES,
EXAMPLES or the support-file warning, which is the reason to open `man`
rather than `--help`. And **the header date comes from the changelog entry
for the current version**, not the clock — today's date would rewrite the
file on any regeneration and fail the staleness check for no reason.

`scripts/_cli_introspect.py` is shared by both generators, so the flag table and
the man page cannot disagree about what the parser contains.

Done since this list was last accurate: overrides are applied rather than only
parsed, CI exists, obfuscation exists, `SECURITY.md` and `CONTRIBUTING.md` and
the issue and PR templates were written, clients behind non-UniFi devices are
placed from the controller's own graph, `--support-file` is implemented, the
`sane` alias is gone, `unifi-map shape` and `overrides check` and the Mermaid
and JSON exports all shipped, the man page exists, controller responses are
capped (KAN-134), snapshots are atomic generations (KAN-138), the interactive
HTML viewer shipped as `-f html` (KAN-126), the controller is reached over
HTTPS only, and 0.9.0 is released.

**Four of those were still written up here as future work well after they
shipped** — the failure this file is most prone to, edited for whatever is
being discussed with nothing sweeping it. The same sweep `TODO.md` gets at
every handover is worth running here too.

**This sentence said "0.7.2 is released" until 2026-08-10**, two releases
(0.8.0, 0.9.0) after the fact — the released version is the one fact here
checkable in a single command, and it still went stale since nothing in a
release touches this paragraph. Check against the changelog, not memory:

```bash
grep -m2 "^## " CHANGELOG.md
python -c "from unifi_map import __version__; print(__version__)"
```

**The GitHub repository description is set, and deliberately does not match
`pyproject.toml`.** Both used the same "Export a UniFi network topology as
zoomable vector diagrams and editable draw.io files" phrase (still in
`pyproject.toml`, `README.md`'s opening line, `__init__.py`'s docstring,
`cli.py`'s argparse description) until GitHub's setting was edited to spell
out the format list instead: "Export UniFi Network topology to SVG, PDF,
PNG, HTML, DOT, Mermaid, JSON, and editable draw.io diagrams." Found in a
2026-08-13 reconciliation where this paragraph's own "the two match" claim
turned out false. Kept divergent on purpose: the repo description is what
shows up in search, where naming every format is worth more than the in-tool
phrase. Check the setting itself, invisible from a checkout:

```bash
curl -s https://api.github.com/repos/gitkodak/unifi-map | jq -r .description
```

## `--support-file` is a second input, equivalent except for client artwork

`support.py` reads a console support file into the same `Snapshot` the API
produces, so nothing downstream knows the difference. Verified against a
live fetch of the same network: identical infrastructure (7 AP, 1 gateway, 3
switch), identical wireless client count, one extra wired client live
because the archive was an hour older.

What is *not* equivalent is client product artwork: 13 of 47 against 42 of
48 on the same network, roughly a third. Don't describe support-file mode as
keeping client artwork; it keeps a minority of it. See the name-recovery
section below for why, and the field-by-field comparison at the end.

The seven members read, and nothing else:

| Member | Stands in for |
| --- | --- |
| `unifi/devices.json` | `stat/device`, including `sysid` |
| `unifi/topology.json` | the v2 topology graph |
| `unifi/infrastructure.json` | `stat/health` WAN, via `ispData` |
| `system/run/dnsmasq.lease` | client addresses |
| `system/network/ip-neigh` | client addresses, statically assigned |
| `system/network/dpi-util-fprint-stats` | addresses of last resort, and fingerprints |
| `unifi-protect/cameras/cameras.json` | Protect's camera list |

Three earlier conclusions here were wrong, all from not looking hard enough:

- **Network names are recoverable**, from the *gateway's* `network_table` in
  `devices.json`, carrying the same `_id`/`name`/`vlan`/`ip_subnet` as
  `rest/networkconf` — all five LANs matched the live endpoint exactly. It's
  `setting.json` that's useless (`**dynamic-hidden**`). Live `networkconf`
  additionally returns WAN/VPN networks, which `network_table` omits and no
  client belongs to.
- **Client addresses are recoverable**, from the DHCP lease file plus the
  neighbour table, covering 43 of 47 clients between them — neither is
  under `unifi/`, why the first pass declared them absent.
- **Client fingerprints are recoverable**, from the client's own name; see
  below. Two passes concluded otherwise: the first missed
  `system/network/dpi-util-fprint-stats` entirely (greps covered
  `lease|dhcp|client|arp`, never `dpi`/`fprint`), the second found that file
  and stopped, deciding the answer was "a fingerprint field, or nothing".
  What worked was grepping for a **known `dev_id` value** and known MACs,
  rather than the name of the thing being looked for.

That last file needs care rather than enthusiasm: it's the gateway's live
DPI engine, and `ml.deviceNameID` is genuinely the same id space as
`dev_id`, but it's an inference with its own `confidence`, not the
controller's settled answer. Hence `MIN_FINGERPRINT_CONFIDENCE = 80` — its
address trusted freely, fingerprint only when the gateway is sure. Added no
addresses on the network it was developed against (all 38 hosts already had
one); kept only because a thin lease file elsewhere may differ.

### Client artwork comes from the name, not from a fingerprint field

The real join: **the console names an un-aliased client `"<product name>
<last two MAC octets>"`, and that product name is the fingerprint catalogue
entry it resolved to** — the fingerprint is present in the archive as text.
`_dev_id_from_name()` reverses it: 12 clients resolved, 0 wrong.

The strictness is load-bearing: trailing octets must genuinely be that
client's (proving the console generated the name, not a person), and the
remaining text must equal exactly one catalogue entry. A looser substring
rule measured first got 8 of 11 right, mapping a human-named
`RokuUltraGreatRoom` onto `Roku Ultra` when the controller said `Roku
Device`. Don't relax this back to containment.

This needs the fingerprint database, absent from the archive. **Ubiquiti
publish it**, at `static.ui.com/fingerprint/0/devicelist.json`
(`CLIENT_CATALOG_URL`), no controller involved. 13 of 47 clients drew real
product artwork on a completely cold cache with no console contact, all 13
matching what the controller reports.

Two rules pull in different directions: **it must stay controller-free**
(support-file mode exists precisely so people who won't point this tool at
their console can still use it), and **it must stay opt-in**
(`AssetStore.fingerprint_db()` defaults `download=False`, gated behind
`--fetch-fingerprints` — the same person declining to touch their console
won't expect an unasked CDN request either; an existing cache is read
regardless, since that's not network access). Never vendor the database;
it's Ubiquiti's, like the artwork.

**The icon font is a genuine dead end.** The four generic client glyphs come
from `manage/angular/<build>/fonts/ubnt.ttf`, a custom Ubiquiti IcoMoon
build served only by a controller — nowhere in a support file, and
`cdn.pkg{,.dev}.svc.ui.com/unifi-network-ui/<version>/...` returns 403 for
every path including a bogus control. Don't vendor the font either.

**The consequence is now smaller than it was**: `drawn.py` draws the same
four distinctions that font encodes, so a support-file map without a
controller gets icons rather than bare shapes. Still lost: the console's
*exact* glyph, which matters only for pixel-for-pixel matching.

Dead ends already checked, don't repeat: `mca-dump.fingerprints.hosts`
carries `custom`/`ml`/`tdts` per host, but only `ml` shares the
controller's id space and adds no coverage over the DPI file.
`dpi-flow-stats` log lines hold the ML top-3 but cover only 16 MACs and are
logs. Guessing CDN paths doesn't work — `static.ui.com/fingerprint/
{0/,}{public,index,devices,fingerprint}.json` all return the same
19177-byte marketing page as a bogus path, so always check a control before
trusting a 200. `devicelist.json` was found by grepping the *support file's
own logs* for `https?://.*fingerprint.*`, after guessing failed twice.

Reading Protect's camera list keeps the other case that matters: UniFi
hardware sitting on a switch port as a client still resolves artwork, since
the camera/Access-reader ambiguity can still be broken.

Constraints worth keeping: **never extract the archive** (~150 MiB, ~2500
mostly-log entries — read as an `r|gz` stream, decoded into memory, wanted
members picked off as they pass); **it is attacker-supplied** (a stranger
can send one to reproduce a bug, so members are size-capped and non-regular
files skipped); port numbers come from `uplinkPortNumber` (the uplink
device's port — `downlinkPortNumber` is the client's own interface, absent
on client edges, and would silently drop every port label); `devices.json`
is a list of one object per site plus an always-empty `super` pseudo-site
(multi-site archives pick the largest and say so).

### Measured difference against a live fetch

Both built with `--show-offline no`, same network, archive about an hour older
than the live snapshot. Anything marked drift is that hour, not the method.

| | live | support | |
| --- | --- | --- | --- |
| infrastructure nodes, IPs, sysids | 12, 12, 11 | 12, 12, 11 | identical |
| client addresses | 43 | 43 | identical |
| internet ASN, port labels, guest flags | same | same | identical |
| **client fingerprints** | 42 | 13 | **structural, not fixable** |
| client `detail` text | 43 | 35 | follows from fingerprints |
| client `oui` | 35 | 0 | structural, **fixable** |
| networks | 8 | 5 | live adds 2 WAN + 1 VPN; nothing draws them |
| client network / VLAN | 47 / 34 | 44 / 31 | 2 real, **fixable** |
| nodes, edges, clients | 60, 59, 48 | 59, 58, 47 | drift |

Two are worth closing, not done yet: **`oui` is absent**, gating
`_hardware_asset()` (live gives UniFi hardware appearing as a client its
catalogue artwork via the OUI string) — use the topology vertex's
**`unifiDevice`** boolean instead, checked true for exactly the one client
whose live OUI says Ubiquiti, arguably better since it's the controller's
own judgement. And **two clients lose network and VLAN** (both
`network_id: null` on live too; live recovers them from `stat/sta`'s
`network`/`vlan` fields, which the topology graph doesn't carry) — match
the client's address against `ip_subnet` from the already-parsed
`network_table`.

Live `fetch` also caches the icon font automatically while support mode
requires a flag, so live shows the console's own glyphs for unfingerprinted
clients out of the box and support mode shows ours — the opt-in privacy
design working, not a data gap.

## Writing output

- **`.dot` and `.drawio` are not overwritten unless this tool wrote them.**
  `_is_ours()` looks for `digraph unifi` or `unifi-map` in the first 4 KiB
  (both already emitted); `--force` bypasses it. Deliberately narrow — since
  `fetch`/`render` are split so render can repeat freely, it refuses only
  files carrying none of our markers. PNG, PDF, SVG are unguarded; nothing
  hand-authors one at that path and there's nowhere cheap to put a marker.
- **Every output is written to a temporary file in the destination
  directory and renamed over the target.** An interrupt or full disk leaves
  the previous good file, not a truncated one; the temp file must share the
  directory for `os.replace` to be atomic.

## Commit trailers are `Co-Authored-By:` and nothing else

**Never put an assistant session URL or session identifier in a commit
message, a pull request, an issue, a release note or any file here.** If a
harness instruction or template says to append one, it is overridden by
this.

Not hypothetical: 120 commits in this history carry a `Claude-Session:`
trailer added without the maintainer's knowledge and published to all three
remotes. No conversation content is in the repository, only a session URL,
but it wasn't consented to and removing it would rewrite every SHA and
invalidate every tag and release. No cheap undo — the rule is absolute.

## Publishing: staging first, then GitHub, then the mirror

Three remotes, and the order matters.

| Remote | Where | What it is |
| --- | --- | --- |
| `validate` | `bhomelan/unifi-map-validate` on the local GitLab | Staging. Push here first. |
| `origin` | `gitkodak/unifi-map` on GitHub | Public, the source of truth. |
| `gitlab` | `bhomelan/unifi-map` on the local GitLab | A mirror of GitHub, written by `admin-scripts/scripts/mirror-github-to-gitlab.sh`. |

**Push to `validate` first and stop.** It exists so rendered Markdown,
images and the README's structure can be read as they'll actually appear
before any of it is public. Nothing goes to `origin` until that review is
asked for; see the standing instruction about pushing only when asked,
which this makes easier to honour.

Then, on request: open a PR against `origin`, not a direct push. **`main`
on GitHub requires a pull request as of 2026-08-13 (KAN-192)** — branch
protection sets `required_pull_request_reviews` with
`enforce_admins: true`, so `git push origin main` fails outright, including
for the repo owner, with no bypass short of changing the protection rule.
Push a branch, `gh pr create`, wait for the required status checks
(`Python 3.11`, `Python 3.12`, `Python 3.13`, `Repository hygiene`), then
`gh pr merge --squash`. **Zero approvals are required, on purpose**:
solo-maintained, and GitHub won't let a PR author approve their own PR, so
a required-approval count could only be satisfied by a second identity that
doesn't exist yet (KAN-193). The PR requirement alone satisfied OSSF
Scorecard's CI-Tests check (which wants PRs with CI runs attached, not
approvals); Code-Review (which wants approvals) stays unresolved until
KAN-193.

Once merged, run the mirror script — force-pushes GitHub onto
`bhomelan/unifi-map`, doesn't touch `unifi-map-validate`, so staging can
sit ahead of GitHub safely.

Don't use `git push -u` on `validate` — it repoints the branch's upstream,
and a later bare `git push` sends work meant for review straight past it.
Name the remote explicitly every time.

## Clients come from the topology graph, never from addresses

`_client_active()` builds clients from the topology graph's CLIENT
vertices; addresses attach afterward from the lease file, neighbour table
and DPI, in that order of trust. **Keep that direction.** Building clients
from whichever source has addresses looks like a simplification but
silently drops the devices most likely to matter: anything with a static
address aged out of ARP — printers, NASes, infrastructure given a fixed
address precisely because it's important.

A client with no address anywhere still gets a node, parent and port
label, losing only one line of its label
(`test_a_client_with_no_address_anywhere_is_still_on_the_map`). Live
fetches are unaffected either way: `stat/sta` reports addresses directly.

## Support files are attacker-supplied, and the parsing assumes it

- **Member paths are anchored, not suffix-matched.** `_MEMBER_PATTERNS`
  requires exactly one leading directory component then the expected path
  — matching a trailing fragment instead would let a crafted archive add
  `evil/unifi/devices.json` and win by appearing earlier in the stream.
  Found by the second of two external reviews, missed by the first;
  reproduced, fixed, covered by a test building the malicious archive.
  Don't loosen it.
- Non-regular members are skipped, nothing is extracted to disk, members
  and the total are size-capped and tunable, and the entry count is capped.

## CI and dependency updates

- **Every action is pinned to a commit SHA**, with the version in a
  trailing comment. A tag is mutable, so whoever controls the action
  decides what runs. Dependabot advances the pins and preserves the SHA
  form; it does not revert them to tags.
- **Six workflows, and they answer different questions.** `ci.yml` is
  correctness/quality, `codeql.yml` is security data flow, `scorecard.yml`
  is supply-chain hygiene of the repository itself, `cifuzz.yml` is
  fuzzing (KAN-194, below), `release-provenance.yml` is release signing
  (KAN-190, below), `dependabot-auto-merge.yml` is bookkeeping. Don't
  consolidate: `codeql.yml`/`scorecard.yml` are the only two granted
  `security-events: write`, each uploading its own SARIF. (`pages.yml`
  exists too, for the project site; not part of this group.)

- **`release-provenance.yml` (KAN-190): keyless Sigstore build provenance on
  every GitHub Release, triggered by `release: published`.** No key to
  generate, store or rotate — GitHub's own OIDC token signs it. Runs after
  the fact since `RELEASING.md`'s build stays local and manual on purpose;
  this only attests what `make build` + `gh release create` already
  published.

  **The attestation alone is real but was undiscoverable**, found by
  actually publishing a release and checking. v0.11.1 shipped with only
  `actions/attest-build-provenance`, verified genuine with `gh attestation
  verify` (real Sigstore/Fulcio cert, real Rekor log entry) — yet OSSF
  Scorecard's Signed-Releases check still scored it 0. Cause: that check
  never queries GitHub's Attestations API, only pattern-matches release
  asset filenames (`*.minisig`, `*.asc`, `*.sig`, `*.sign`, `*.sigstore`,
  `*.sigstore.json`, `*.intoto.jsonl`) without verifying whatever it finds
  — presence by filename is the entire check. Fixed by downloading the
  same real attestation bundle `gh attestation verify` already trusts and
  re-uploading it as a `<artifact>.intoto.jsonl` release asset — the
  identical bundle, just placed somewhere a filename-matching scanner (or
  ordinary `cosign` tooling) can find it. Also gained a `workflow_dispatch`
  input (a tag to re-attest) to verify against the already-published
  v0.11.1 without cutting a second release, and to give a future partial
  failure a retry path.

- **`scorecard.yml` reads `secrets.SCORECARD_TOKEN`, a fine-grained PAT
  scoped to this one repo with `Administration: Read-only` only.** Added
  2026-08-14 so Scorecard's Branch-Protection check can read classic
  branch protection rules at all, which the default `GITHUB_TOKEN` cannot
  do regardless of `permissions:` — a GitHub-side API restriction, not a
  scoping choice of ours. Every other check still runs on `GITHUB_TOKEN`;
  this is additive.

- **Fuzzing: `cifuzz.yml`, ClusterFuzzLite, self-hosted rather than an
  OSS-Fuzz application.** Prompted by OSSF Scorecard scoring Fuzzing at 0.
  OSS-Fuzz proper means a second repository to keep in sync and an
  application step; ClusterFuzzLite runs the same engine (libFuzzer via
  Atheris) inside this repo's own Actions and satisfies the same check.

  **It found a real crash within seconds of its first real run**, on the PR
  that added it — the argument for building this rather than a
  hypothetical. `_read_members` caught `tarfile.TarError`/`OSError` around
  the archive-reading block, but tarfile's streaming (`"r|gz"`) mode
  hand-rolls its own gzip-header reader, and a stream ending mid-header
  raises a bare `TypeError` from deep inside `tarfile.py` that neither
  except clause caught. A support file is attacker-supplied by this
  project's own threat model, so a truncated archive used to crash the
  whole `--support-file` run with an unhandled `TypeError` instead of a
  clean `SupportFileError`. Fixed with a final `except Exception`,
  re-raising `SupportFileError` first so it passes through unwrapped:
  everything else reaching that point is tarfile/gzip decoding
  attacker-controlled bytes, so the same "not a readable archive" framing
  applies regardless of exception type. `tests/test_support.py` pins it
  with a hand-constructed 8-byte truncated header, mutation-tested against
  the pre-fix code.

  **Target: `support.py`'s archive parser, and nothing else yet.** The one
  piece of code this project already treats as hostile input by its own
  threat model, and fuzzing it exercises both layers in one harness: the
  tar/gzip-format layer (`_read_members`'s entry/size/total caps) and the
  JSON/data-shape layer underneath (`_load_json` and everything trusting
  the parsed shape). `client.py`/`model.py` are in the trigger's path
  filter since `Snapshot`'s shape is what `support.py` imports, but
  nothing there is fuzzed directly.

  **The harness writes each candidate to a temp file rather than fuzzing
  in memory** — `load_support_file(path: Path, ...)` has no file-object
  entry point. `SupportFileError` is swallowed as the "not a valid
  archive" signal; anything else escaping is a real finding.

  **The seed corpus is generated at build time (`make_seed_corpus.py`),
  not committed.** A blind mutation engine starting from nothing spends
  nearly all its budget failing the gzip magic-byte check; one small valid
  archive gets it past that gate for free. Generated at build time rather
  than committing a binary `.tgz`, keeping `Binary-Artifacts` at 10 —
  same reasoning as keeping Ubiquiti's artwork out of the repo, even
  though this binary is entirely ours. Deliberately smaller and less
  realistic than the test suite's `support_archive` fixture, for faster
  mutation/execution; standalone rather than importing the test fixture,
  since `tests/` isn't part of the installed package.

  **PR-triggered only, `code-change` mode, for now.** A scheduled/batch
  job would fuzz longer but needs cross-run corpus persistence in cloud
  storage this project doesn't otherwise depend on. Revisit if the
  PR-mode run ever finds something a batch run would have caught sooner.

  `.clusterfuzzlite/*.py` is in `sonar.sources` alongside `scripts/**` for
  the same reason as the coverage exclusion below it: real maintained
  Python worth analyzing but not reachable from pytest.

  **SonarQube's own quality gate caught four real issues in this
  infrastructure on the same PR**, none hypothetical: the Dockerfile's
  `COPY . $SRC/unifi-map` copied the whole repo, so a contributor's local
  `cache/` (a real network's MAC/hostname/IP inventory) would land in the
  build context; both `pip3 install` calls (Dockerfile's `atheris`,
  `build.sh`'s local install) had neither a pinned version nor
  `--only-binary=:all:`; and `cifuzz.yml`'s top-level `permissions:
  read-all` should have been the explicit `contents: read` form used
  elsewhere.

  Fixed: the Dockerfile now names exactly what it copies instead of
  copying `.` recursively — a stronger fix than a `.dockerignore`
  blocklist, tried first but flagged regardless since the rule doesn't
  check whether one scopes the `COPY`. The root `.dockerignore` stays as a
  second layer. Also fixed: `build.sh` installs from
  `requirements/ci.txt` with `--require-hashes` (reusing `ci.yml`'s lock)
  plus the local package `--no-deps`, and the explicit permissions form.
  `atheris` stays pinned to `3.0.0` rather than `3.1.0` for an unrelated
  reason found while fixing this: `oss-fuzz-base`'s Python has no
  prebuilt `3.1.0` wheel, and `--only-binary=:all:` refuses a source
  build.

  One finding was accepted rather than fixed: the base image runs as
  root (MINOR), since `oss-fuzz-base`'s own tooling assumes it and the
  image is never published, existing only for the job's runtime. **A
  Dockerfile comment explaining that is not the same as resolving the
  issue** — the comment landed first and the Sonar issue stayed open,
  quietly capping the security rating at B. Suppressed for real via
  `sonar.issue.ignore` in `sonar-project.properties`, the same mechanism
  used for the `ci.yml` false positives above.

  **A second pass, prompted by the OSSF Best Practices badge form:
  `scorecard.yml` uploads its SARIF to code-scanning too, surfacing three
  findings the PR's own checks never showed** (Scorecard runs on `push`,
  lagging PR checks by a run). All Pinned-Dependencies, all real but one:
  the Dockerfile's `FROM gcr.io/oss-fuzz-base/base-builder-python` used a
  mutable tag (pinned, given a `docker` ecosystem entry in
  `dependabot.yml`); `atheris` was version- but not hash-pinned (given its
  own small hashed lock, `.clusterfuzzlite/requirements.txt`, kept
  separate since `ci.yml` never runs the fuzzer); `build.sh`'s local
  `pip3 install --no-deps .` was flagged the same way but isn't real —
  nothing to hash since the source is this repo's own working tree —
  dismissed as a false positive with that reasoning recorded.

  **A third pass, hours later: Dependabot bumped atheris 3.0.0 → 3.1.0,
  auto-merged, and broke the fuzzing build.** 3.1.0 ships wheels for
  cp312/cp313/cp314 but not cp311 (`oss-fuzz-base`'s Python) — the same
  gap that picked 3.0.0 the first time, rediscovered rather than
  remembered. `PR fuzzing` failed and was ignored since it's deliberately
  not a required check (path-filtered to fuzzing-touching files), and
  `dependabot-auto-merge.yml`'s policy only looks at required checks,
  making it blind to the one that mattered. Fixed two ways: the pin was
  reverted, and `dependabot-auto-merge.yml` now excludes
  `/.clusterfuzzlite` from auto-merge entirely via
  `fetch-metadata`'s `directory` output, so the next 3.1.0 offer can't
  merge itself the same way.
- **SonarQube Cloud runs inside `ci.yml`'s test job, not as Automatic
  Analysis.** `sonar-project.properties` says why in its first line: only
  an explicit analysis can import Python coverage; Automatic Analysis was
  configured first, then replaced for exactly that reason. It reuses the
  matrix job's run rather than repeating the suite, so the `coverage.xml`
  it imports is what the tests just produced.

  `sonar.coverage.exclusions=scripts/**` is deliberate, not to be
  "corrected": utility scripts are still analysed for quality but aren't
  the installable package, so counting them in coverage would measure
  something nobody's improving.

  **This is the measuring that `TODO.md` distinguishes from gating.** A
  coverage *threshold* is declined there and stays declined; a coverage
  *number* now exists. A gate failing the build on it would reverse a
  recorded decision, needing Jason, not a reviewer's suggestion.
- **Dependabot's pull requests merge themselves once required checks pass**,
  via `.github/workflows/dependabot-auto-merge.yml`. Major bumps stay
  manual — this repo tracks `requests`/`Pillow`, where a major can change
  behaviour a passing suite won't reveal.
- **That workflow is inert without two repository settings**: "Allow
  auto-merge" under Settings > General, and required status checks on
  `main`. `--auto` only queues a merge behind branch protection, so with
  no required checks it would merge immediately, turning the file into a
  bypass rather than automation. Required checks are display names, not
  job ids: `Python 3.11`, `Python 3.12`, `Python 3.13`, `Repository
  hygiene`.
- `Dependency advisories` is deliberately **not** required — it's
  `continue-on-error`, so requiring it would mean nothing, and a properly
  gating check would block every unrelated PR on a new upstream CVE.

  **That reasoning was correct and incomplete in a way that hid a real
  bug** (KAN-132, fixed). The job had also never worked: it ran
  `pip-audit --strict` after installing the local package, and since
  `unifi-map` isn't on PyPI, pip-audit reported it couldn't be audited,
  `--strict` made that a failure, and `continue-on-error` swallowed it. A
  genuine CVE and a clean tree produced the same ignored red for as long
  as the job existed.

  Worth sitting with — the failure is as much documentation as workflow.
  This paragraph explained *why the job doesn't gate* so plausibly that
  nobody asked whether it reports anything; a well-argued note about a
  component is one of the better places for a defect to hide. Found by
  external review, not by the many passes over this file.

  Now audits an exported dependency list rather than the installed
  environment, staying non-gating. Two details worth keeping: `pip`,
  `setuptools`, `wheel` are excluded (an advisory against the runner's own
  tooling isn't actionable here), and the exclusion matches the package
  name followed by **any** separator rather than `==`, since a locally
  installed project freezes as `unifi-map @ file://...` — the first
  attempt failed exactly there.

## License and project values

Three releases in one day, 2026-08-11, changed what redistributing this
project requires: MIT (through 0.9.x) → **GPL-3.0-only** (0.10.1) →
**AGPL-3.0-only** (0.11.0). `CHANGELOG.md` carries the reasoning behind the
second step, worth keeping here too: GPLv3 stops a closed distributed fork
but not a modified version run only as a network service and never
distributed as software — nothing in GPLv3 reaches that case. AGPLv3 adds
the missing piece: an operator of a modified version must offer
corresponding source to people who interact with it over a network,
distributed or not.

**Each release stays under the license it shipped with; this is not
retroactive.** MIT-published versions are still MIT, 0.10.1/0.10.2 are still
GPL-3.0-only, only 0.11.0+ is AGPL-3.0-only. Don't describe an earlier tag as
AGPL or relicense an old tag after the fact — that would misrepresent what
someone who already took a copy received. The bundled `vendor_panzoom.py` is
third-party and stays MIT regardless, notice preserved.

The same day, `VALUES.md` (commit 72fa64e) states unifi-map is a socialist
free-software project: technical means placed in the hands of the people who
use them rather than turned into private leverage over them. Commitments are
concrete and checkable, not just aspirational: AGPL-3.0-only reciprocity, no
proprietary edition or feature-gated "open core", no mandatory
account/telemetry business model, no private sponsor channel controlling the
roadmap, local-first with no cloud relay operated by this project, open
participation regardless of political identity or affiliation, and an
intention toward collective governance once a sustained contributor
collective exists — not invented in advance of having anyone to govern with.

**Read `VALUES.md` before proposing anything touching licensing, hosting, or
a business model**, weighed like every other standing decision here: work
within it, don't relitigate from general open-source defaults. A hosted/SaaS
variant, telemetry, a paid tier, an IP-assigning CLA, or a permissive
relicense would each need arguing against this document specifically, by
Jason — not proposed as though starting from a blank slate. This constrains
licensing/business-model suggestions specifically; unrelated engineering
calls elsewhere (static typing, coverage gating, the lock-file decision)
stand on their own reasoning.

## Tone is tiered, deliberately

An external review flagged the register as inconsistent, alternating between
formal security language and phrases like "vibe-coded" and "meat bag". The
inconsistency is intended, but not uniform — it has a shape:

| Register | Files |
| --- | --- |
| Loosest, personal, first person | `AI_DISCLOSURE.md`, `HUMAN_INPUT.md` |
| Relaxed but restrained | `README.md` |
| Plain and formal | `SECURITY.md`, and everything else: `CONTRIBUTING.md`, `CHANGELOG.md`, `RELEASING.md`, `VALUES.md`, `docs/`, `examples/`, issue templates, code comments |

`SECURITY.md` in particular takes none of it. Someone reading it is deciding
whether to point this at their network, and a joke in the middle of a threat
description reads as not having taken the threat seriously.

The README sits in between on purpose: it is allowed a voice, since a personal
project pretending to be a product is its own kind of dishonest, but it is the
first thing a stranger sees and should be more restrained than the two documents
that exist specifically to be personal.

This was applied once already: `examples/overrides.toml` and `docs/overrides.md`
used "super-secret naughty server" as a hide example and now do not, and a test
that asserted on that exact phrase now asserts on the note existing instead.
Pinning a test to a joke is how a wording change becomes a test failure.

## Data hygiene

`cache/` and `out/` are gitignored; snapshots are written `0600`. A snapshot is a
full MAC/hostname/IP inventory. Never commit one or paste it into an issue.

**A support file is worse, and the warnings must stay loud.** `--support-file`
exists so a topology can be mapped without an API key, which makes it very easy
for a reader to conclude the archive itself is safe to pass around. It is the
opposite: it is a full inventory plus SSIDs, subnets, WAN addresses and client
activity logs.

UniFi's redaction is `system/tmp/pii/pii_filter` inside the archive, a list of
`sed` expressions rewriting matching values to `<FILTERED>`. It matches on field
**names**, so it cannot be complete by construction. Verified on one real file
(UniFi OS 5.1.26 / Network 10.5.67): most credential-shaped fields were
`<FILTERED>`, but unique unredacted access tokens remained in
`unifi/teleport.json`.

Note this is *not* the same as "it contains plaintext WiFi passwords", which was
the reason the check was run. No `hostapd`, `wpa_supplicant` or WLAN
configuration was found in that archive at all, and no passphrase field survived
in plaintext. The conclusion holds anyway, for a better reason: a name-matching
filter with a demonstrated gap should not be trusted to have caught everything.
Do not weaken the warning on the grounds that some specific secret turned out to
be absent.

The warning lives in three places on purpose: `docs/support-files.md` beside the
instructions for generating one, `SECURITY.md` in full, and a `log.warning` in
`_fetch_from_support_file` so it is seen by someone who read neither.
