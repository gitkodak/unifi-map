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

## Pipeline

Each stage owns one concern; nothing downstream of `model.py` sees raw
controller JSON.

1. **`config.py`** is the only module that reads `os.environ`. Accepts `UNIFI_*`
   and `UDM_*` names. Keep it that way: it's what makes a future Vault/OpenBao
   backend a single-file change. Credentials are `UNIFI_HOST` plus
   `UNIFI_API_KEY`, and nothing else.
2. **`client.py`** is the only module that talks to the controller. Auth is an
   `X-API-KEY` header set once in the constructor; there is no login, session or
   CSRF token. Network application paths are prefixed `/proxy/network`. `unwrap()` absorbs both the v1 `{"data": [...]}`
   envelope and bare v2 lists, returning `[]` on anything unexpected so a
   controller upgrade thins the diagram instead of raising.
   **`support.py`** is the alternative source: it reads the same `Snapshot` out
   of a support file archive, with no credentials and no network. Keep the two
   interchangeable, so anything added to one is considered for the other.
   `_Session` overrides `rebuild_auth` so the `X-API-KEY` header is dropped on a
   redirect that changes host, which is what `requests` already does for
   `Authorization` and does for nothing else. Redirects stay enabled on purpose:
   no endpoint used here redirects today, but refusing them outright would break
   anyone fronting their controller with a proxy that normalises a path or a
   trailing slash. `UNIFI_VERIFY_TLS=false` is documented as ordinary for a bare
   IP, so without the strip, anyone in the path could redirect the tool and be
   handed a working admin key.
3. **`model.py`** normalizes into `Topology`. All schema quirks land here.
4. **`assets.py`** is the only module that fetches artwork. Cached under
   `--asset-cache` (default `cache/assets`), deliberately separate from the
   snapshot cache so `--cache-dir examples/demo` doesn't get downloads written
   into it.
5. **`layout.py`** is the only module that shells out to Graphviz (`dot`,
   `unflatten`). Both are executed by the absolute path `shutil.which` resolved,
   not by bare name, so what runs is what was found rather than whatever `PATH`
   resolves to at exec time. Both get `_child_env()`, the parent environment
   with any API key removed.

   That pairs with `config.py` never writing a credential into `os.environ`:
   `read_dotenv()` returns a mapping and `load_config()` merges it under the
   real environment. Keep it that way. An API key in the process environment is
   inherited by every child, and Graphviz comes off `PATH`.
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

  This was hunted through the web bundles for a long time and was never there.
  It was found in one grep of a **support file's own logs**: the speed-test
  daemon logs the URL it builds as `ispImg`. The bundle search is on the
  do-not-repeat list further down and should have been abandoned much earlier
  for a search of data the device had already written down.
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
  handful of unrecognised devices is ordinary on any network, and a warning per
  device would drown the output that matters. The detail lives behind `-v`,
  which logs every lookup including the empty ones; that is documented in the
  README and asked for by both issue templates. This was considered as a
  summary count at the end of the artwork pass and deliberately not built:
  documenting the existing flag was enough.

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
  for a long time: the placeholder node was blamed on the controller when the
  data was in an endpoint already being fetched and ignored. Check the console
  against the output before concluding the controller does not know something.
- **Never invent topology.** Clients whose uplink the controller doesn't report
  get anchored to `UNKNOWN_UPLINK_ID`. Don't guess a plausible parent switch.
- **`Topology.infrastructure` includes `Kind.UNKNOWN`** so that placeholder
  survives per-network filtering. Removing it re-orphans those clients.

## Defaults reproduce the UniFi web view

`--icons unifi --layout unifi --theme light` is chosen so the tool matches what
the console shows out of the box. Don't change a default to something "better
looking" without a reason; the point is fidelity first, with `tree` available
for readability.

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
ours, clients without a usable fingerprint fall back to shapes or a generic
glyph rather than the console's own icon, and the output is static. The README has a section spelling
this out. Keep improving fidelity if you like, but do not let the documentation
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

### Tracked in Jira as well

All of the below is also **epic KAN-114** in the `bhomelan` project, with a
ticket per item, so it is visible without reading this file. **This file stays
authoritative**: the tickets carry the summaries, this carries the reasoning,
and if they disagree this one is newer. Update both or neither.

### Proposals from two external reviews, with assessments

From agy and from Codex, both 2026-08-02, recorded with what was thought about
them so the thinking is not redone. They overlap heavily, which is itself
information: the same three ideas arrived independently. Merged rather than
listed twice, and ordered by fit rather than by arrival.

- **A `diff` subcommand**, comparing two cached snapshots and reporting what
  moved. The strongest of the set. Snapshots are already immutable, timestamped
  JSON, and `build_topology()` already turns one into a graph, so a diff is a
  pure function over two `Topology` objects and needs no new input path. It also
  makes the snapshot cache worth something beyond re-rendering: this file
  already calls each snapshot "a record of what the network looked like at that
  moment" and nothing currently reads one that way.

  **Two prerequisites, and the first was missed when this was first written
  here.** `Snapshot.write()` writes `cache_dir/<name>.json` every time, so each
  fetch overwrites the last and there is no history to diff against. Something
  has to retain snapshots first, as a timestamped mode rather than a changed
  default, since the current behaviour is documented and deliberate. Codex
  caught this; the entry originally named only the second blocker, which is a
  fair reminder that "fits the existing design" is not the same as "the data is
  there".

  The second is randomised client MACs, listed below as its own gap. Every join
  here is on MAC, so a phone rotating its address appears as one device leaving
  and another arriving. A diff would report that as churn every run and be
  ignored within a week.

- **A diagnostic report**, `--report` or `inspect`, saying how good the map it
  just drew actually is: how many nodes came from which endpoint, which clients
  were placed from `stat/sta` versus the topology graph versus an override,
  which could not be placed and why, artwork matches that were ambiguous and
  refused, networks referenced by a client but absent from `networkconf`.

  Codex picked this as the best near-term work and I agree, with one thing worth
  noticing: **it merges two gaps already listed below**, "no reconciliation
  report" and "provenance and confidence". They are the same feature seen from
  two ends, and the second is what makes the first worth reading. Most of the
  decisions are already made at runtime and thrown away as log lines.

- **A normalised JSON export** of `Topology` itself, not the raw controller
  responses. Cheap, because the model is already the stable thing and the raw
  payloads are the unstable ones, and it is the honest way to let somebody build
  an inventory check or a Home Assistant integration without learning UniFi's
  schemas. Must honour `--obfuscate`, overrides and per-network filtering, and
  should carry the provenance fields the report above would need, which is an
  argument for doing them together.

- **Generalised filters**: `--kind switch ap`, `--wireless-only`, `--guest-only`,
  and most usefully `--root "Rack Switch"` for a subtree of a large map.
  `--per-network` is a special case of this and already does the hard part,
  which is keeping the ancestor path back to the gateway so a slice still reads
  as part of one network.

- **Multi-site handling, and a `sites` command.** Worth pairing: a multi-site
  support file is now refused with a list of the sites in it, which is correct
  but leaves discovery to an error message. A `sites` subcommand would make it
  answerable before the failure. `--all-sites` is the natural companion, with a
  separate cache directory per site, and both want testing against a real
  multi-site console before the shape is fixed, since that is still untested.

- **Historical clients**, opt-in and visibly dated. Codex's caveat is the right
  one and matches the rules here: an old association is not evidence of where
  something is now, so a stale client must never be drawn as a current link. If
  it cannot be made obviously historical it should not be drawn at all.

- **`overrides check`**, validating selectors without rendering anything. Small
  and clearly useful: overrides fail loudly by design, and today the only way to
  find out is to render. Pairs with the candidates generator below.

- **`generate-overrides`**, emitting a skeleton `overrides.toml` seeded with the
  nodes the tool could not place. Closes a loop that is currently half open: the
  run already counts clients with no reported uplink and points at overrides,
  and the "no reconciliation report" gap below is asking for the same
  information from the other end. One command could answer both.

- **Mermaid export.** Cheap and a clean architectural fit: another pure function
  from `Topology` to text, beside `render_dot` and `render_drawio`. Worth
  documenting that it necessarily loses artwork, so it is the shape of the
  network and nothing else. Good for a README or a wiki page, which is a place
  this tool's output currently cannot go.

- **An interactive HTML viewer.** Collapsible client subtrees address the exact
  problem the tool exists for, and path highlighting is genuinely useful on a
  busy map. Two things to decide before starting: it wants JavaScript, and
  vendoring a pan/zoom library sits badly beside the rule against vendoring
  anything else, so either write the few hundred lines by hand or accept the
  dependency deliberately. It can still be a pure function from `Topology` to
  text, which is what keeps it in the existing shape rather than beside it.

- **Location and rack grouping via overrides.** Philosophically the best fit of
  all of them: a controller cannot know which rack something is in, which is
  precisely what `[[device]]` and friends are for. The unknown is rendering.
  Graphviz clusters interact badly with `--layout unifi` (`rankdir=LR` with
  ortho routing), there is already a legend cluster in `sane`, and the
  `unflatten` stagger pass has not been tried against nested clusters. Prototype
  the layout before committing to the schema.

- **Link and wireless metadata overlays.** Partly already specced: the
  infrastructure view below covers speed and media colouring, and
  `port_table[].speed`/`.media` were verified present on a live snapshot. Fold
  that half in there rather than tracking it twice.

  The wireless half (RSSI, band, channel width) is **not verified**. The demo
  dataset carries only `essid` and `radio_name`, but it is synthetic and
  `make_demo_snapshot.py` does not emit those fields at all, so its silence
  proves nothing either way. Check a live `stat/sta` before promising anything.

  **`--color-by vlan` conflicts with a standing rule.** Colour is never the only
  channel here, because the palette has to survive greyscale and deuteran
  vision. Grouping by VLAN needs a second channel (a cluster, a node shape, a
  border style) or it is the one feature that quietly breaks that promise.

- **OpenBao/Vault credential backend.** Already anticipated: `config.py` is the
  only module that reads the environment specifically so this stays a
  single-file change, and its docstring says so. The blocker is not the code,
  it is that `vault.bhomelan.com` does not exist yet.

- **NetBox/IPAM export.** Recorded and **not planned.** It means owning a schema
  mapping against another project's API versions, for a system this project does
  not use, with no second consumer to justify the abstraction. If somebody wants
  it, the Mermaid or JSON exports plus a script of their own is the honest
  answer. Revisit if a real user asks.

### Gaps worth considering

- **`RELEASING.md` step 9 says CI cannot be checked from here. That is now
  false.** `gh` 2.97.0 was installed and authenticated on 2026-08-02, and
  `gh run list` works. The note telling a releaser to look at the Actions tab
  and report CI as unconfirmed should become the command that actually checks
  it, something like `gh run watch --exit-status`. Worth doing sooner than the
  rest of this list, because it is a documented instruction that is wrong rather
  than a feature that is missing.


- **Provenance and confidence.** `Edge.asserted` marks an override-supplied link
  and nothing else distinguishes observed from inferred. A client placed from
  the v2 topology graph, one placed from `stat/sta`, and one whose fingerprint
  was recovered from its name are all drawn identically and with equal apparent
  authority. The tool refuses to invent; it does not yet say how sure it is.

- **No reconciliation report.** Counts are logged and unplaceable clients get a
  visible placeholder, but nothing enumerates what did not match: clients with
  no address, devices with no artwork, ambiguous name matches that were refused.
  A `--report` would turn "the map looks plausible" into something checkable,
  and would have caught at least two of the wrong conclusions recorded here.

- **Randomised client MACs are not a concept here.** Every join is on MAC, so a
  phone rotating its MAC appears as a new client with no relation to the old
  one. Worth documenting at minimum, since it explains apparent duplicates.

- **Nothing has been profiled on a large site.** The joins are dictionary-based
  and probably fine, but `sysid_for_name()` scans the catalogue per candidate.
  Check before claiming it scales.

- **No dependency lock file.** Deliberate for now: hashed constraints are real
  ongoing maintenance for a dev-only benefit, and Dependabot plus the advisory
  job cover staying current. Revisit if this ever ships releases people install.

  **This is the declined security-review finding** that `SECURITY.md` and
  `AI_DISCLOSURE.md` both point here for, so keep the reasoning legible if it
  moves. It is the only one left: the other decline, against tightening the
  support-file size caps without data from a large site, stopped being a
  decline when the caps became adjustable and the defaults dropped to 64M/128M.

- **Draw our own device icons instead of falling back to Graphviz shapes.**
  `KIND_SHAPE` currently maps each role to a primitive: `doubleoctagon` for a
  gateway, `box3d` for a switch, `trapezium` for an AP, `diamond` for unknown.
  Readable, but plainly geometric. `_render_cloud()` proved the approach: Pillow
  primitives, ours, so no network and no licensing question, and Pillow is
  already a hard dependency so nothing new is needed.

  Seven icons, `INTERNET` being done already: gateway, switch, AP, bridge, wired
  client, wireless client, unknown.

  **Decided: use them in `--icons builtin` *and* as the fallback inside
  `--icons unifi` when a device is not in Ubiquiti's catalogue.** Today that case
  drops to a bare shape, so this improves the default mode too. It is a small,
  deliberate step away from "`unifi` shows exactly what the console
  shows", taken because a drawn AP beats a trapezium either way.

  What is known offline, all from the snapshot rather than any lookup:

  - `Kind`, derived from the controller's `type` (`udm`/`usw`/`uap`).
  - `model`, the raw code (`UDMPROMAX`, `U7PRO`, `USL8LP`). Enough to vary an
    icon by port count or form factor if that ever seems worth it.
  - `is_guest` and `wireless` for clients, which is exactly the four-way split
    the console's own icon font encodes (`user-wired`, `user-wireless`,
    `guest-wired`, `guest-wireless`). **Drawing those four would close the icon
    font dead end recorded above**, and remove the only remaining reason a
    support-file user needs a controller.

  Three constraints, all learned the hard way already:

  - **Give each kind its real aspect ratio.** `IconAsset.display_size()` honours
    it; a wide short switch forced into a square cell letterboxes.
  - **Silhouette must keep carrying the meaning.** The existing shapes exist so
    the map survives greyscale and deuteran vision. Colour may not become the
    only channel.
  - **Cache per colour, like the cloud does**, or a dark icon lands on a dark
    canvas.

- **Infrastructure view.** The console has one, and it is a different diagram
  rather than the client map with clients removed, which is all `--no-clients`
  gives today. Described from a screenshot of the real thing, 2026-07-30.

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
  display string like "port 12", and the view needs a badge at each end with a
  port number, a speed and a medium. Structured fields on `Edge`, with the label
  derived from them rather than stored instead of them, is the change that has
  to come first. Codex noticed this and it is the one piece of the view that is
  not just drawing.

  Otherwise this is a rendering job, not a data-gathering one. The parts that need
  thought are the two-badges-per-edge layout, which Graphviz has no direct
  notion of (head and tail labels are the closest), and whether this becomes a
  third `--layout` or a separate output.

- **Decide whether a release should produce an artifact.** `RELEASING.md` now
  documents the process that exists, which is a tag plus a changelog entry, and
  says plainly that there is no published package. The open question is whether
  `pip install unifi-map` should work. That means owning a PyPI name and never
  breaking a published artifact, so it is a commitment rather than a chore. The
  entry point and build backend already exist; CI would need a `tags:` trigger.

- **Remove the `sane` layout alias in 0.5.0.** Renamed to `tree`; `sane` is
  accepted, hidden from `--help` by `metavar`, and warns naming the version.
  Delete `DEPRECATED_LAYOUTS` in `render_dot.py`, the warning in `cmd_render`,
  the `choices` widening, and the `sane` Makefile target.

  **Unlike `UDM_*`, this one has a promised version.** It is a single flag
  value, trivially changed by anyone using it, so an open-ended deprecation
  would just keep the word in `--help` forever.

- **Finish retiring the `UDM_*` environment aliases.** The warning is in:
  `config.py` collects legacy names as it resolves them and emits one line
  naming each replacement, and the README section is marked deprecated. What
  remains is deleting them.

  **No removal version is promised, on purpose.** Naming 1.0 would be a promise
  made to sound organised, and the versioning policy already says anything may
  change before then. Drop them whenever it suits.

  Before deleting: Jason's own credential file under `~/Development/envfiles/`
  uses `UDM_*` exclusively, so it has to be renamed first rather than have the
  breakage discovered by a failing fetch. It also still carries `UDM_USER` and
  `UDM_PASS`, dead since password auth was removed and read by nothing.

**The man page is done**, as `unifi-map.1`, generated by
`scripts/generate_manpage.py` and checked for staleness like the flag
reference. Two things about it worth not relitigating:

- **`argparse-manpage` was tried and dropped.** It works, but its API is
  `Manpage(parser)` and little else. Every global option is attached to every
  subparser via `parents=`, so it printed all fifteen three times over, and
  there is no hook for ENVIRONMENT, FILES, EXAMPLES or the support-file
  warning. Those are not derivable from a parser and are the reason to open
  `man` rather than `--help`. Post-processing its roff would have been worse
  than emitting our own.
- **The header date comes from the changelog entry for the current version**,
  not from the clock. Today's date would rewrite the file on any day it was
  regenerated and fail the staleness check for no reason.

`scripts/_cli_introspect.py` is shared by both generators, so the flag table and
the man page cannot disagree about what the parser contains.

Done since this list was last accurate: overrides are applied rather than only
parsed, CI exists, obfuscation exists, `SECURITY.md` and `CONTRIBUTING.md` and
the issue and PR templates were written, clients behind non-UniFi devices are
placed from the controller's own graph, `--support-file` is implemented, and
0.2.0 is released.

**The GitHub repository description is set**, and matches `pyproject.toml`.
Verified against the API rather than assumed, because it is a setting rather
than a file and so cannot be seen from a checkout. Check it the same way before
listing it as outstanding again:

```bash
curl -s https://api.github.com/repos/gitkodak/unifi-map | jq -r .description
```

## `--support-file` is a second input, equivalent except for client artwork

`support.py` reads a console support file into the same `Snapshot` the API
produces, so nothing downstream knows the difference. Verified against a live
fetch of the same network: identical infrastructure (7 AP, 1 gateway, 3 switch),
identical wireless client count, one extra wired client live because the archive
was an hour older.

What is *not* equivalent is client product artwork: 13 of 47 against 42 of 48 on
the same network, roughly a third. Do not describe support-file mode as keeping
client artwork; it keeps a minority of it. See the name-recovery section below
for why, and the full field-by-field comparison at the end of this section.

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
  `devices.json`, which carries the same `_id`/`name`/`vlan`/`ip_subnet` as
  `rest/networkconf`. All five LANs matched the live endpoint exactly. It is
  `setting.json` that is useless: its contents are `**dynamic-hidden**`. Live
  `networkconf` additionally returns the WAN and VPN networks, which
  `network_table` omits and no client belongs to.
- **Client addresses are recoverable**, from the DHCP lease file plus the
  neighbour table, which between them covered 43 of 47 clients. Neither is under
  `unifi/`, which is why the first pass declared them absent.
- **Client fingerprints are recoverable**, from the client's own name; see
  below. Two passes concluded otherwise. The first missed
  `system/network/dpi-util-fprint-stats` entirely, though it sat in a manifest
  already generated, because the greps covered `lease|dhcp|client|arp` and never
  `dpi` or `fprint`. The second found that file and stopped there, having
  decided the answer was "a fingerprint field, or nothing". The thing that
  worked was grepping for a **known `dev_id` value** and for known MACs, rather
  than for the name of the thing being looked for.

That last file needs care rather than enthusiasm. It is the gateway's live DPI
engine, and `ml.deviceNameID` is genuinely the same id space as `dev_id`, but it
is an inference with its own `confidence`, not the controller's settled answer.
Hence `MIN_FINGERPRINT_CONFIDENCE = 80`: its address is trusted freely, its
fingerprint only when the gateway is sure. It added no addresses at all on the
network it was developed against (all 38 of its hosts already had one), and it
is kept only because a network with a thin lease file may differ.

### Client artwork comes from the name, not from a fingerprint field

The real join is that **the console names an un-aliased client
`"<product name> <last two MAC octets>"`, and that product name is the
fingerprint catalogue entry it resolved to.** The fingerprint is therefore
present in the archive as text. `_dev_id_from_name()` reverses it: 12 clients
resolved, 0 wrong.

The strictness is load-bearing. The trailing octets must genuinely be that
client's, which is what proves the console generated the name rather than a
person, and the remaining text must equal exactly one catalogue entry. A looser
substring rule was measured first and got 8 of 11 right, mapping a human-named
`RokuUltraGreatRoom` onto `Roku Ultra` when the controller said `Roku Device`.
Do not relax this back to containment.

This needs the fingerprint database, which the archive lacks. **Ubiquiti publish
it**, at `static.ui.com/fingerprint/0/devicelist.json`
(`CLIENT_CATALOG_URL`), so no controller is involved. 13 of 47 clients drew real
product artwork on a completely cold cache with no console contact, and all 13
matched what the controller reports.

Two rules follow, and they pull in different directions:

- **It must stay controller-free.** Support-file mode exists precisely so people
  who will not point this tool at their console can still use it, so anything
  reintroducing an API dependency defeats it.
- **It must stay opt-in.** `AssetStore.fingerprint_db()` takes `download=False`
  by default and the CLI gates it behind `--fetch-fingerprints`, because the
  same person who declines to touch their console will not expect an unasked
  request to a CDN either. A cache that already exists is read regardless, since
  that is not network access. Never vendor the database; it is Ubiquiti's, like
  the artwork.

**The icon font is a genuine dead end.** The four generic client glyphs come
from `manage/angular/<build>/fonts/ubnt.ttf`, a custom Ubiquiti IcoMoon build
(note the `?6vxos8` cache-buster) served only by a controller. It is nowhere in
a support file, and `cdn.pkg{,.dev}.svc.ui.com/unifi-network-ui/<version>/...`
returns 403 for every path including a deliberately bogus control. So a
support-file map without a controller draws unfingerprinted clients as shapes,
which is the documented degradation and is fine. Do not vendor the font either.

Dead ends already checked, do not repeat: `mca-dump.fingerprints.hosts` carries
`custom`, `ml` and `tdts` per host, but only `ml` shares the controller's id
space (three Rokus show `tdts=292` where the controller says `27`), and it adds
no coverage over the DPI file. `dpi-flow-stats` log lines
(`fp ml for mac: ... [Name - id]@n%`) hold the ML top-3 but cover only 16 MACs
and are logs. Guessing CDN paths does not work:
`static.ui.com/fingerprint/{0/,}{public,index,devices,fingerprint}.json` all
return the same 19177-byte marketing page, as does a deliberately bogus path, so
always check a control before believing a 200. `devicelist.json` was found by
grepping the *support file's own logs* for `https?://.*fingerprint.*`, after
guessing had failed twice; `static.ubnt.com` serves it identically.

Reading Protect's camera list keeps the other case that matters: UniFi hardware
sitting on a switch port as a client still resolves its artwork, because the
camera/Access-reader ambiguity can still be broken.

Constraints worth keeping:

- **Never extract the archive.** It is ~150 MiB over ~2500 entries and mostly
  logs, including per-client remote logs. It is read as a `r|gz` stream, decoded
  into memory, and the wanted members are picked off as they go past.
- **It is attacker-supplied.** The whole point is that a stranger can send you
  one to reproduce a bug, so members are size-capped and anything that is not a
  regular file is skipped.
- Port numbers come from `uplinkPortNumber`, the port on the uplink device.
  `downlinkPortNumber` is the client's own interface and is absent on client
  edges; taking it would silently drop every port label.
- `devices.json` is a list of one object per site, plus a `super` pseudo-site
  that is always empty. Multi-site archives pick the largest and say so.

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

Two of those are worth closing and are not done yet:

- **`oui` is absent**, and it gates `_hardware_asset()`: live gives UniFi
  hardware appearing as a client its catalogue artwork because the OUI string
  says Ubiquiti. Use the topology vertex's **`unifiDevice`** boolean instead.
  Checked: it was true for exactly the one client whose live OUI says Ubiquiti,
  so it is a clean substitute and arguably better, being the controller's own
  judgement rather than a vendor-string match.
- **Two clients lose network and VLAN.** Both have `network_id: null` on live as
  well; live recovers them from `network`/`vlan` fields on `stat/sta` that the
  topology graph does not carry. Match the client's address against `ip_subnet`
  from `network_table`, which is already parsed.

Also note that live `fetch` caches the icon font automatically while support
mode requires a flag, so out of the box live shows generic glyphs for
unfingerprinted clients and support mode shows shapes. That is the opt-in
privacy design working, not a data gap.

## Writing output

- **`.dot` and `.drawio` are not overwritten unless this tool wrote them.**
  `_is_ours()` looks for `digraph unifi` or `unifi-map` in the first 4 KiB, both
  of which those formats already emit, and `--force` bypasses it. The guard is
  deliberately narrow: re-rendering must stay free of ceremony, since `fetch`
  and `render` are split precisely so render can be run repeatedly, so it
  refuses only files carrying none of our markers. PNG, PDF and SVG are not
  guarded; nothing hand-authors one at exactly that path and there is nowhere
  cheap to put a marker.
- **Every output is written to a temporary file in the destination directory
  and renamed over the target.** An interrupt or a full disk leaves the previous
  good file rather than a truncated one. The temporary must be in the same
  directory for `os.replace` to be atomic.

## Publishing: staging first, then GitHub, then the mirror

Three remotes, and the order matters.

| Remote | Where | What it is |
| --- | --- | --- |
| `validate` | `bhomelan/unifi-map-validate` on the local GitLab | Staging. Push here first. |
| `origin` | `gitkodak/unifi-map` on GitHub | Public, the source of truth. |
| `gitlab` | `bhomelan/unifi-map` on the local GitLab | A mirror of GitHub, written by `admin-scripts/scripts/mirror-github-to-gitlab.sh`. |

**Push to `validate` first and stop.** It exists so rendered Markdown, images
and the README's structure can be read as they will actually appear, before any
of it is public. Nothing goes to `origin` until that review happens and is
asked for; see the standing instruction about pushing only when asked, which
this makes easier to honour rather than replacing.

Then, on request: `git push origin main`, then run the mirror script. The
mirror force-pushes GitHub onto `bhomelan/unifi-map` and does not touch
`unifi-map-validate`, so staging can sit ahead of GitHub safely.

Do not use `git push -u` on `validate`. It repoints the branch's upstream, and a
later bare `git push` then sends work meant for review straight past it. Name
the remote explicitly every time.

## Clients come from the topology graph, never from addresses

`_client_active()` builds clients from the topology graph's CLIENT vertices.
Addresses are then attached from the lease file, the neighbour table and DPI, in
that order of trust. **Keep that direction.** Building clients from whichever
source happens to have addresses looks like a simplification and silently drops
exactly the devices most likely to matter: anything with a static address that
has aged out of ARP, which in practice means printers, NASes and infrastructure
given a fixed address precisely because it is important.

A client with no address anywhere still gets a node, a parent and a port label,
and loses only one line of its label. Covered by
`test_a_client_with_no_address_anywhere_is_still_on_the_map`.

Live fetches are unaffected either way: `stat/sta` reports addresses directly.

## Support files are attacker-supplied, and the parsing assumes it

- **Member paths are anchored, not suffix-matched.** `_MEMBER_PATTERNS` requires
  exactly one leading directory component and then the expected path. Matching
  a trailing fragment instead lets a crafted archive add
  `evil/unifi/devices.json`, which ends the same way, and win by appearing
  earlier in the stream. Found by the second of two external reviews and missed by the first, reproduced, fixed, and
  covered by a test that builds the malicious archive. Do not loosen it.
- Non-regular members are skipped, nothing is extracted to disk, members and
  the total are size-capped and tunable, and the entry count is capped.

## CI and dependency updates

- **Every action is pinned to a commit SHA**, with the version in a trailing
  comment. A tag is mutable, so whoever controls the action decides what runs.
  Dependabot advances the pins and preserves the SHA form; it does not revert
  them to tags.
- **Dependabot's pull requests merge themselves once the required checks pass**,
  via `.github/workflows/dependabot-auto-merge.yml`. Major bumps are excluded
  and stay manual, because this repository tracks `requests` and `Pillow`, where
  a major can change behaviour a passing suite will not reveal.
- **That workflow is inert without two repository settings**: "Allow auto-merge"
  under Settings > General, and required status checks on `main`. `--auto` only
  queues a merge behind branch protection, so with no required checks it would
  merge immediately, turning the file into a way to bypass review rather than a
  way to automate it. The required checks are the display names, not the job
  ids: `Python 3.11`, `Python 3.12`, `Python 3.13`, `Repository hygiene`.
- `Dependency advisories` is deliberately **not** required. It is
  `continue-on-error`, so requiring it would mean nothing, and if it ever gates
  properly a new CVE upstream would block every unrelated pull request.

## Tone is tiered, deliberately

An external review flagged the register as inconsistent, alternating between
formal security language and phrases like "vibe-coded" and "meat bag". The
inconsistency is intended, but it is not uniform, and it has a shape:

| Register | Files |
| --- | --- |
| Loosest, personal, first person | `AI_DISCLOSURE.md`, `HUMAN_INPUT.md` |
| Relaxed but restrained | `README.md` |
| Plain and formal | `SECURITY.md`, and everything else: `CONTRIBUTING.md`, `CHANGELOG.md`, `RELEASING.md`, `docs/`, `examples/`, issue templates, code comments |

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

The warning lives in three places on purpose: `README.md` beside the instructions
for generating one, `SECURITY.md` in full, and a `log.warning` in
`_fetch_from_support_file` so it is seen by someone who read neither.
