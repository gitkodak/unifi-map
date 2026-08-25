# Artwork

[← Documentation index](../README.md#documentation)

This page covers where the pictures come from, what happens when there
are none, and the licensing position.

## Where the artwork comes from

This repository vendors nothing. This project fetches some artwork from
Ubiquiti and caches it, draws some locally, and lets you supply one
source yourself.

**There is no single precedence order**, because different code resolves
each of the three kinds of node. Each list below runs from first choice
to last. In all three, an icon you supply wins outright. That is a
decision, not a guess.

**Infrastructure** (gateways, switches, access points, bridges):

| Source | Key |
| --- | --- |
| `static.ui.com/fingerprint/ui/public.json` + `.../ui/images/...` | hardware `sysid` |
| [drawn here](#the-icons-we-draw-ourselves), by role | `Kind` |
| a file you supply, named by `icon` in an [overrides file](overrides.md) | whatever you point it at |

**Clients:**

| Source | Key |
| --- | --- |
| `static.ui.com/fingerprint/0/{dev_id}_257x257.png` | fingerprint `dev_id` from `stat/sta` |
| the hardware catalogue above, for UniFi gear appearing as a client | hostname, plus a device type from another app |
| the controller's own icon font (`fonts/ubnt-icon`) | user/guest x wired/wireless |
| [drawn here](#the-icons-we-draw-ourselves) | user/guest x wired/wireless |
| a file you supply, named by `icon` in an [overrides file](overrides.md) | whatever you point it at |

**The Internet node:**

| Source | Key |
| --- | --- |
| `static.ui.com/asn/{asn}_257x257.png`, the provider's brand mark | `asn` from `stat/health` |
| a cloud drawn here, which is why `--obfuscate` can drop the brand mark safely | none |
| a file you supply, named by `icon` in an [overrides file](overrides.md) | whatever you point it at |

The cloud is a separate code path from the role icons, and it is not
one of the nine below. The Internet node never uses them as a fallback.

The last row is the escape hatch for everything the others cannot do:
hardware Ubiquiti has no render of, a device they identify wrongly, or a
switch nothing reports at all. The tool loads this from disk and never
fetches it, so it also works with `--offline`. An override's icon wins
over anything the tool looks up for the same node.

The client artwork endpoint is `staticFingerprintOld` in the Network UI's own
config. The controller also serves the fingerprint database itself at
`/proxy/network/v2/api/fingerprint_devices/0` (5789 devices), which is what turns
an unnamed client into "Govee H61E1 / Smart Light Strip".

Note that the controller does **not** host device images: every path under its
web app's static assets returns the SPA's HTML 404. Only the icon font is local.

## UniFi hardware that appears as a client

A UniFi device on a switch port the Network app did not adopt (a Protect
camera, for example) is just a client. It has no fingerprint, so there
is nothing to look up. Its hostname is the only handle, and hostnames
are ambiguous. `g3-flex` matches both `UVC-G3-FLEX`, a Protect camera,
and `UA-G3-Flex`, an Access door reader.

So the tool matches the hostname against the hardware catalogue, and it
only uses a match when it is unique. To break ties, it asks other UniFi
apps what they know. If Protect reports that MAC as a camera, the tool
considers only camera entries, and `g3-flex` then resolves to exactly
one. If a name stays ambiguous, the tool uses the generic glyph, rather
than a coin flip.

This needs no extra configuration. The tool fetches
`/proxy/protect/integration/v1/cameras` when it is present, and ignores
it when Protect is not installed.

## Matching

This tool matches devices to Ubiquiti's device catalog on **sysid**, not
model name. The controller's `model` string does not reliably match the
catalog's shortnames. For example, a USW Pro HD 24 PoE reports
`USWED72`, while the catalog calls it `USPH24P`.

The tool builds the graph from `stat/device` uplinks plus `stat/sta` and
`networkconf`, then completes it with the controller's own
`v2/.../topology` graph, for clients the first two cannot place. It
reads that endpoint defensively, since it is a v2 API whose structure
changed before. Anything unexpected in it yields nothing, rather than
raising an error. So a controller upgrade degrades the map, instead of
breaking the run.

## The generic client glyph, and why it is awkward

Clients the console never identified get a generic person or laptop glyph in the
UniFi UI. That glyph is not an image: it is a character in a custom icon font
that **only a controller serves**. Ubiquiti publish the device artwork and the
fingerprint database, but not this font, so there is no route to it that avoids a
controller entirely. It is also their property, so this project will not ship a
copy.

Three options, with what each costs:

| | Needs an API key | Needs network | Result for unidentified clients |
| --- | --- | --- | --- |
| Do nothing (default) | No | No | [Our own client icons](#the-icons-we-draw-ourselves) |
| `--icon-font DIR` | No | No | Real UniFi glyphs |
| `--fetch-icon-font` | **Yes** | Yes | Real UniFi glyphs |

If you do nothing, you still get a perfectly readable diagram. This tool
draws the same four distinctions the font encodes, so an unidentified
client is still visibly a guest or not, wired or not. The font buys you
the console's exact glyph, instead of our version of it. That matters if
you want the map to match what somebody sees in the UI. This is
presentation, not information.

**`--fetch-icon-font`** asks a controller directly, so it needs
`UNIFI_HOST` and `UNIFI_API_KEY`, exactly as a live `fetch` does. If you
read a support file specifically to avoid a console connection, this
flag defeats that purpose. That is why it is off by default, and named
plainly. It is still useful when the support file is someone *else's*,
and you have a console of your own: any UniFi controller's font works,
since the glyphs are not site-specific.

**`--icon-font DIR`** reads a copy you obtained yourself, and touches nothing.
You need two files, the stylesheet and the `.ttf`, because the codepoints live in
the CSS rather than the font:

```bash
unifi-map all --support-file support-XXXX.tgz --icon-font ~/ubnt-icon
```

Point it at a directory that holds both, in any arrangement. To get
them, either copy them off a self-hosted controller, where a startup log
entry names the UI directory as `uiDir`. That directory is normally:

```text
/usr/lib/unifi/webapps/ROOT/app-unifi/angular/<build>/fonts/ubnt-icon/
```

(On a UniFi OS console such as a UDM or UNVR the Network application runs in a
container, so that path is inside it rather than on the host filesystem.)

Or download them over HTTP, which needs an API key once but then never again:

```bash
BUILD=$(curl -s -H "X-API-KEY: $UNIFI_API_KEY" \
  "https://$UNIFI_HOST/proxy/network/manage/" | grep -o 'angular/[A-Za-z0-9]*' | head -1)
mkdir -p ~/ubnt-icon/fonts
BASE="https://$UNIFI_HOST/proxy/network/manage/$BUILD/fonts/ubnt-icon"
curl -s -H "X-API-KEY: $UNIFI_API_KEY" "$BASE/style.css"      -o ~/ubnt-icon/style.css
curl -s -H "X-API-KEY: $UNIFI_API_KEY" "$BASE/fonts/ubnt.ttf" -o ~/ubnt-icon/fonts/ubnt.ttf
```

Either way, the tool caches the font under `--asset-cache` afterwards, so
you need the flag only once per cache.

## The icons we draw ourselves

Ubiquiti's artwork covers their hardware and the clients their
fingerprint database recognises. Everything else used to fall back to a
bare Graphviz primitive: a trapezium for an access point, a diamond for
something unplaceable. This was readable, but plainly geometric.

This project now draws nine icons instead, with Pillow, and uses them in
two places:

- **`--icons builtin`**, which fetches nothing at all. It previously
  meant "no artwork exists". It now means "artwork that is ours", which
  includes the Internet cloud. It gives a complete map with no network
  access whatsoever.
- **As the fallback inside `--icons unifi`**, for any node it could not
  resolve. That covers hardware absent from Ubiquiti's catalogue, and
  also any client with no fingerprint when no icon font is cached, the
  ordinary case for a support file. This is a small, deliberate step away
  from "`unifi` shows exactly what the console shows". This project took
  that step because a drawn access point beats a trapezium either way.
  Anything the catalogue or the font *does* cover stays unaffected, so a
  normal map against a live controller looks as it did before.

Five are infrastructure, keyed on the device's role: gateway, switch, access
point, bridge, and unknown. Four are clients, split on guest and wireless, which
is the same four-way split the console's own icon font encodes.

**Those four close a gap that had no other answer.** Only a controller
serves that font, and it appears nowhere in a support file. So before
this, reading an archive with no console contact left unidentified
clients drawn as shapes. They now draw as icons instead. This removes
the last reason a support-file user needs a controller at all.

Three things about how this project draws them, each a constraint
rather than a preference:

- **The silhouette carries the meaning.** Every icon is a single colour
  on transparency, and every outline stays distinguishable from the
  others with no colour at all. Guest is *hollow*, rather than a second
  hue, because colour is never the only channel here.
- **Aspect ratios are real.** A switch is wide and short, a handset is
  taller than it is wide, an access point is round.
- **Each theme colour caches separately.** Otherwise a dark icon would
  land on a dark canvas.

They are ours, so they need no network and raise no licensing question, which is
the same reasoning behind the Internet cloud.

## Fixing a wrong icon in the console instead

Before you reach for an overrides file, try the console. UniFi lets you
change a client's device fingerprint in its settings, and **this tool
already follows that**: it prefers a client's `dev_id_override` over the
fingerprint the controller guessed. Correct it once in the console, and
every render afterwards picks it up. There is nothing to configure here.

The catch is the console's own picker, which is small and only matches
from the start of a name. A search for "Apple iPhone" finds something. A
search for "iphone" finds nothing.

Two community tools make that searchable, both browser-side:
[hubaker/UniFi-Icon-Browser](https://github.com/hubaker/UniFi-Icon-Browser) and
the more actively extended fork
[CANTI-BOT/UniFi-Icon-Browser](https://github.com/CANTI-BOT/UniFi-Icon-Browser),
which adds partial-match search across roughly 5,500 icons and works with
self-hosted controllers. Neither is affiliated with this project.

Overrides are still the answer when you have no console access, when the device
you want is not in Ubiquiti's catalogue at all, or when you want artwork of your
own.

## Artwork, licensing and attribution

This repository contains **no** Ubiquiti artwork. Device images are
Ubiquiti's intellectual property. This project fetches them at runtime,
from Ubiquiti's public endpoints, and caches them under `cache/`, which
is gitignored. Nothing here is redistributed.

If you'd rather not fetch anything, use `--icons builtin`.

UniFi and Ubiquiti are trademarks of Ubiquiti Inc. This project is not
affiliated with or endorsed by Ubiquiti.

The code is AGPL-3.0-only. See [LICENSE](../LICENSE). The bundled
Panzoom library remains under its own MIT license. Its notice stays in
`src/unifi_map/vendor_panzoom.py`.
