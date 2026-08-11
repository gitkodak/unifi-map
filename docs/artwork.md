# Artwork

[← Documentation index](../README.md#documentation)

Where the pictures come from, what happens when there are none, and the
licensing position.

## Where the artwork comes from

Nothing here is vendored into this repository. Some is fetched from Ubiquiti and
cached, some is drawn locally, and one source is yours.

**There is no single precedence order**, because the three kinds of node are
resolved by different code. Each list below runs from first choice to last, and
in all three an icon you supply wins outright: that is a decision, not a guess.

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

The cloud is a separate code path from the role icons and is not one of the nine
below; the Internet node never falls through to them.

The last row is the escape hatch for everything the others cannot do: hardware
Ubiquiti has no render of, a device they identify wrongly, or a switch nothing
reports at all. It is loaded from disk and never fetched, so it also works with
`--offline`, and an override's icon wins over anything looked up for the same
node.

The client artwork endpoint is `staticFingerprintOld` in the Network UI's own
config. The controller also serves the fingerprint database itself at
`/proxy/network/v2/api/fingerprint_devices/0` (5789 devices), which is what turns
an unnamed client into "Govee H61E1 / Smart Light Strip".

Note that the controller does **not** host device images: every path under its
web app's static assets returns the SPA's HTML 404. Only the icon font is local.

## UniFi hardware that appears as a client

A UniFi device on a switch port that the Network app has not adopted (a Protect
camera, for example) is just a client: no fingerprint, so nothing to look up. Its
hostname is the only handle, and hostnames are ambiguous. `g3-flex` matches both
`UVC-G3-FLEX`, a Protect camera, and `UA-G3-Flex`, an Access door reader.

So the hostname is matched against the hardware catalogue, and a match is only
used when it is unique. To break ties, other UniFi apps are asked what they know:
if Protect reports that MAC as a camera, only camera entries are considered, and
`g3-flex` then resolves to exactly one. If a name stays ambiguous, the generic
glyph is used rather than a coin flip.

This needs no extra configuration. `/proxy/protect/integration/v1/cameras` is
fetched when present and ignored when Protect is not installed.

## Matching

Devices are matched to Ubiquiti's device catalog on **sysid**, not model name:
the controller's `model` string doesn't reliably match the catalog's shortnames
(a USW Pro HD 24 PoE reports `USWED72` while the catalog calls it `USPH24P`).

The graph is built from `stat/device` uplinks plus `stat/sta` and `networkconf`,
then completed with the controller's own `v2/.../topology` graph for clients the
first two cannot place. That endpoint is read defensively, since it is a v2 API
whose structure has changed before: anything unexpected in it yields nothing
rather than raising, so a controller upgrade degrades the map instead of breaking
the run.

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

Doing nothing is a perfectly readable diagram. We draw the same four
distinctions the font encodes, so an unidentified client is still visibly a
guest or not, wired or not. What the font buys is the console's exact glyph
rather than our version of it, which matters if you want the map to match what
somebody sees in the UI. This is presentation, not information.

**`--fetch-icon-font`** asks a controller directly, so it needs `UNIFI_HOST` and
`UNIFI_API_KEY` exactly as a live `fetch` does. If you are reading a support file
specifically to avoid connecting to a console, this defeats that, which is why it
is off by default and named plainly. It is still useful when the support file is
someone *else's* and you have a console of your own: any UniFi controller's font
works, since the glyphs are not site-specific.

**`--icon-font DIR`** reads a copy you obtained yourself, and touches nothing.
You need two files, the stylesheet and the `.ttf`, because the codepoints live in
the CSS rather than the font:

```bash
unifi-map all --support-file support-XXXX.tgz --icon-font ~/ubnt-icon
```

Point it at a directory containing both, in any arrangement. To get them, either
copy them off a self-hosted controller, where the UI directory is logged at
startup as `uiDir` and is normally:

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

Either way the font is cached under `--asset-cache` afterwards, so the flag is
only needed once per cache.

## The icons we draw ourselves

Ubiquiti's artwork covers their hardware and the clients their fingerprint
database recognises. Everything else used to fall through to a bare Graphviz
primitive: a trapezium for an access point, a diamond for something unplaceable.
Readable, but plainly geometric.

Nine icons are now drawn here instead, with Pillow, and used in two places:

- **`--icons builtin`**, which fetches nothing at all. It previously meant "no
  artwork exists"; it now means "artwork that is ours", which includes the
  Internet cloud. It is a complete map with no network access whatsoever.
- **As the fallback inside `--icons unifi`**, for any node it could not
  resolve. That is hardware absent from Ubiquiti's catalogue, and also any
  client with no fingerprint when no icon font is cached, which is the ordinary
  case for a support file. This is a small, deliberate step away from "`unifi`
  shows exactly what the console shows", taken because a drawn access point
  beats a trapezium either way. Anything the catalogue or the font *does* cover
  is unaffected, so a normal map against a live controller looks as it did.

Five are infrastructure, keyed on the device's role: gateway, switch, access
point, bridge, and unknown. Four are clients, split on guest and wireless, which
is the same four-way split the console's own icon font encodes.

**Those four close a gap that had no other answer.** That font is served only by
a controller and appears nowhere in a support file, so mapping from an archive
without ever touching a console meant unidentified clients drew as shapes. They
now draw as icons, which removes the last reason a support-file user needs a
controller at all.

Three things about how they are drawn, each of which is a constraint rather than
a preference:

- **The silhouette carries the meaning.** Every icon is a single colour on
  transparency and every outline is distinguishable from the others with colour
  discarded. Guest is *hollow* rather than a second hue, because colour is never
  the only channel here.
- **Aspect ratios are real.** A switch is wide and short, a handset is taller
  than it is wide, an access point is round.
- **Each theme colour caches separately**, or a dark icon lands on a dark
  canvas.

They are ours, so they need no network and raise no licensing question, which is
the same reasoning behind the Internet cloud.

## Fixing a wrong icon in the console instead

Before reaching for an overrides file, try the console. UniFi lets you change a
client's device fingerprint in its settings, and **this tool already follows
that**: a client's `dev_id_override` is preferred over the fingerprint the
controller guessed. Correct it once in the console and every render afterwards
picks it up, with nothing to configure here.

The catch is the console's own picker, which is small and only matches from the
start of a name. Searching "Apple iPhone" finds something; "iphone" finds
nothing.

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

This repository contains **no** Ubiquiti artwork. Device images are Ubiquiti's
intellectual property; they are fetched at runtime from Ubiquiti's public
endpoints and cached under `cache/`, which is gitignored. Nothing is
redistributed here.

If you'd rather not fetch anything, use `--icons builtin`.

UniFi and Ubiquiti are trademarks of Ubiquiti Inc. This project is not
affiliated with or endorsed by Ubiquiti.

The code is GPL-3.0-only; see [LICENSE](../LICENSE). The bundled Panzoom
library remains under its own MIT license, whose notice is preserved in
`src/unifi_map/vendor_panzoom.py`.
