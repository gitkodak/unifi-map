# Mapping from a support file

Reading a console support file instead of talking to a controller: what it
needs, what it costs, and why the file itself must be treated as a secret.

## Mapping from a support file

If you would rather not hand this tool an API key, or you want to map a network
you cannot reach, point it at a console support file instead. No credentials are
involved and no controller is contacted:

```bash
unifi-map all --support-file support-XXXX-1234567890.tgz
```

Generate one in the console under **Settings > System > Support File**. It is a
large archive, typically around 150 MiB.

> **Treat a support file as a secret.** It is one of the most sensitive things
> your console can produce. It contains every MAC address, hostname, IP and DHCP
> lease on your network, your SSIDs, VLANs and subnets, your public WAN
> addresses and ISP, and extensive logs including per-client connection history.
>
> UniFi does redact *some* credentials on the way out, but the filter matches on
> field **names** with regular expressions, so anything it does not recognise
> passes through. On one real support file, most credential fields were indeed
> filtered while a set of unredacted access tokens remained.
>
> So do not ask whether one particular secret is in there. Assume anything the
> console knows may be. Keep it encrypted, do not attach it to a ticket or paste
> it into a chat, and delete it when you are done. `SECURITY.md` goes into more
> detail.
>
> This tool reads only seven files out of the archive and never unpacks it, but
> that limits *this tool*, not the file.

Sending one to someone else is therefore a bigger favour than it looks. If the
question is really about topology, an obfuscated render is usually a better
thing to hand over:

```bash
unifi-map all --support-file support-XXXX.tgz --obfuscate
```

**Reading a support file contacts nothing.** No controller, no credentials, and
no outbound requests of any kind. If you want client product artwork, that needs
Ubiquiti's fingerprint database, which the archive does not contain, so it is a
separate opt-in:

```bash
unifi-map fetch --support-file support-XXXX.tgz --fetch-fingerprints
```

That downloads about 1 MB from Ubiquiti's CDN and caches it, still without
touching any controller. Leave the flag off and clients simply draw without
product artwork. Note that `render` does reach the CDN for device artwork unless
you pass `--offline`, so for a completely network-free run use both:

```bash
unifi-map all --support-file support-XXXX.tgz --offline --icons builtin
```

What you get is very close to a live fetch. Verified against the same network
read both ways, the infrastructure and the wireless client list came out
identical, and VLAN names, subnets, switch port numbers, SSIDs, client addresses,
the ISP name and Protect camera artwork all survive.

**Client artwork is much reduced.** This is the one place a support file is
clearly worse, and it is worth being concrete: on the network this was developed
against, an API key resolved product artwork for **42 of 48** clients, and a
support file managed **13 of 47**. Roughly a third.

A support file does not store the fingerprint id that client artwork is matched
on. Some of it can be reconstructed, because a client the console named *itself*
is named after the product it identified, and that name can be looked back up.
But the console only does that for a client that sent no DHCP hostname and that
you never renamed, which on a real network is a minority. Everything else draws
without product artwork.

So expect a support-file map to have correct names, addresses and connections
throughout, and product icons on a minority of clients. UniFi hardware appearing
as a client is unaffected and still draws properly.

The product lookup needs Ubiquiti's published fingerprint database, which is why
it is behind `--fetch-fingerprints` as described above. Clients with no
fingerprint draw as plain shapes unless you also supply the glyph font, below.

### The generic client glyph, and why it is awkward

Clients the console never identified get a generic person or laptop glyph in the
UniFi UI. That glyph is not an image: it is a character in a custom icon font
that **only a controller serves**. Ubiquiti publish the device artwork and the
fingerprint database, but not this font, so there is no route to it that avoids a
controller entirely. It is also their property, so this project will not ship a
copy.

Three options, with what each costs:

| | Needs an API key | Needs network | Result for unidentified clients |
| --- | --- | --- | --- |
| Do nothing (default) | No | No | Plain shapes |
| `--icon-font DIR` | No | No | Real UniFi glyphs |
| `--fetch-icon-font` | **Yes** | Yes | Real UniFi glyphs |

Plain shapes are a perfectly readable diagram; they are colour and shape coded
like everything else. This is presentation, not information.

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

Two smaller caveats:

- Client addresses come from the gateway's DHCP leases and neighbour table, so a
  client that never took a lease and had gone quiet may have no address shown.
- Only the LAN networks appear. The controller's live network list also includes
  WAN and VPN entries, which no client belongs to and which nothing draws.

**`--site NAME` is required for a support file holding more than one site.**
One site and it is picked automatically; several and the run stops, listing what
it found, so you can say which you meant.

Mapping the largest and warning was tried first and was wrong. The result is a
complete, entirely ordinary looking map, and if it is the wrong site nothing
about the diagram says so.

(`--support-site` was the original spelling and still works, but `--site` covers
both inputs and is preferred.)

Only seven files are ever read out of the archive, as a stream. It is never
unpacked, which matters because a support file also contains extensive logs.

Reading one is capped four ways, since the whole point is that somebody else can
send you one. Two cap what is decoded into memory; the others cap how much of
the archive is walked, in entries and in uncompressed bytes, because neither
follows from the bytes decoded.

The last one is the only defence against a compression bomb. Streaming tar has
to read through a member to reach the next header, so a file this tool skips
still costs its full decompressed size, and the size caps never see it.

| Flag | Default | Guards against |
| --- | --- | --- |
| `--support-max-member` | 64M | one huge member decompressed on trust |
| `--support-max-total` | 128M | many members that are individually fine |
| `--support-max-entries` | 100,000 | an archive that is cheap to decompress and enormous to iterate |
| `--support-max-archive` | 4G | a small archive that expands enormously |

```bash
unifi-map all --support-file support-XXXX.tgz \
  --support-max-member 256M --support-max-total 512M
```

The sizes accept a plain byte count or a `K`, `M` or `G` suffix, and every one
of the three errors names the flag to raise.

The defaults come from a single 154M archive off a UDM Pro Max, whose largest
relevant member was 400K and which held about 2,500 entries. That is one sample
of one small network, so treat the headroom as a guess rather than a measured
safety margin: it says nothing about how any of these numbers grow with site
size. All three are therefore adjustable. If you hit one legitimately, please
open an issue saying so, because a second data point would be worth more than
the reasoning that picked these.

Raising `--support-max-entries` prints a warning first, because the cost is
easy to miss. With the spinner running you can at least see the step is still
going; with `--no-progress`, or piped to a file, walking a much larger archive
produces no output at all until it finishes, so a slow run and a hung one look
identical.
