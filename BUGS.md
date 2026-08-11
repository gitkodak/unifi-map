# Bugs found in a review pass, 2026-08-10

Found by a targeted bug-hunt (three parallel audits over artwork resolution,
overrides/support-file parsing, and render/report/model), not from a user
report. KAN-176 through KAN-180 are fixed in the working tree. Each has a
matching Jira ticket (project KAN) with more detail; this file is so a fresh
agent session can pick one up without re-deriving the findings.

Ordered by confidence/severity, most urgent first.

## KAN-176: `--obfuscate` drops `Edge.provenance` (confirmed, reproduced)

`obfuscate()` in `src/unifi_map/obfuscate.py` (~line 179) rebuilds every edge
field-by-field:

```python
edges = [
    Edge(src=ids[e.src], dst=ids[e.dst], label=e.label, wireless=e.wireless, asserted=e.asserted)
    for e in topo.edges
    if e.src in ids and e.dst in ids
]
```

`provenance` is never carried across, so every obfuscated edge resets to
`Provenance.UNSPECIFIED`. Three call sites key off
`edge.provenance is Provenance.TOPOLOGY_GRAPH`:

- `render_dot.py` (~line 293/429) — the hollow-circle arrowhead marker and its
  legend row (KAN-137)
- `render_drawio.py` (~line 193) — same marker in draw.io output
- `diagnostics.py` (~line 374) — `--report`'s edge tally, which by design runs
  *after* `--obfuscate`

All three go silently blind to this provenance whenever `--obfuscate` is
combined with rendering or `--report`. Same failure class CLAUDE.md documents
as already fixed once for `asserted` in this exact function — `provenance`
was added later (KAN-137) and fell into the same trap.

**The guard test that should catch this cannot fail.**
`tests/test_obfuscate.py::test_obfuscation_keeps_every_model_field_it_does_not_deliberately_change`
iterates dataclass fields to catch dropped ones, but its fixture
`Edge(src="a", dst="b", label="port 1", wireless=True, asserted=True)` never
sets `provenance`, so both sides compare `UNSPECIFIED == UNSPECIFIED` and pass
despite the bug.

**Fix:** carry `provenance=e.provenance` through the edge rebuild, and fix the
test fixture to set a non-default provenance so it would actually catch a
regression. Mutation-test the fix per CLAUDE.md's own rule before trusting it.

## KAN-177: Mermaid draws an asserted/offline node identically to a real one (fixed)

`render_mermaid.py`'s edge function checks `edge.asserted`/`edge.wireless` and
picks a dotted/dashed/solid arrow — the asserted-vs-observed distinction IS
honored for edges. But the node-emission loop and `_label()` only reference
`node.kind` and `node.ip`. `node.asserted` and `node.offline` are never
referenced anywhere in the file (confirmed by grep).

Every other backend draws the distinction: `render_dot.py` (dotted
outline/border for asserted, dashed + "OFFLINE" label for offline),
`render_drawio.py` (`dashed=1;dashPattern=1 3;` / `<b>OFFLINE</b>`),
`render_json.py` (exports both booleans).

Failure scenario: a device declared purely via `[[device]]` in an overrides
file (never confirmed by the controller, `Node.asserted = True`) or an
offline device, rendered with `unifi-map -f mermaid`, is visually and
textually identical to a real, live, controller-observed device — exactly
what `Node.asserted`'s own docstring in `model.py` says must never happen:
"the map must never present a claim and an observation as though they were
the same thing."

No test protects this: `tests/test_mermaid.py` only tests the edge-level
distinction; no node-level test exists, and no fixture there uses
`asserted=True` or `offline=True` on a `Node`. Same fixture-defaults-mask-
the-bug shape as KAN-176.

**Fixed:** Mermaid labels now append `OFFLINE` and/or `ASSERTED` markers.
Mermaid's node shapes already encode the device kind, and the link styles are
already used for wired/wireless/asserted edges, so the plain-text markers keep
the node state visible without sacrificing either of those distinctions.

## KAN-178: A corrupt cached icon PNG returns `None` forever, for 5 of 6 lookups (fixed)

`assets.py`'s `icon()` (UniFi-hardware artwork lookup) self-heals a corrupt
cached PNG: on a measurement failure it unlinks the bad cache file and
refetches. The five structurally identical siblings — `isp_logo()`,
`internet_icon()`, `drawn_icon()`, `client_icon()`, `client_glyph()` — do
not: they just do `if cached.is_file(): return _measure(cached)` and give up,
returning `None`, on a corrupt file.

Reproduced: writing garbage bytes to a `drawn-*.png` cache entry makes
`drawn_icon()` return `None` forever, even though that specific path needs no
network access at all and would trivially succeed on a retry.

**Fixed:** the self-heal-on-corrupt-cache logic is now a shared helper used by
all six icon lookups. An unreadable cache entry is deleted and regenerated or
refetched during the same run.

## KAN-179: Two latent traps in `assets.py` (not live bugs, but real; fixed)

1. `fingerprint_db()` bypasses `self._fetch()` and its `_unreachable` circuit
   breaker, using a raw `requests.get()` instead. No current call site
   combines it with other CDN calls on the same `AssetStore`, so it's latent
   rather than observably broken today. It now uses the shared fetch path,
   with the fingerprint database's larger size limit, so a network outage
   degrades consistently.

2. `data_uri()` hardcodes `image/png` — the exact bug `render_drawio.py`'s
   `_drawio_data_uri()` documents having fixed for the same purpose (an SVG
   override icon needs its real media type or draw.io can't draw it).
   `data_uri()` is currently dead code, unreferenced anywhere in the
   codebase, so this is a trap for whoever next reuses it rather than a live
   bug. It was removed because it was truly unused.

---

All findings from this audit are fixed.
