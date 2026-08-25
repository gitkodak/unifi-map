# Mapping from a support file

[← Documentation index](../README.md#documentation)

This page covers how to map from a console support file instead of a
controller: what it needs, what it costs, and why you must treat the file
itself as a secret.

If you would rather not hand this tool an API key, or you want to map a
network you cannot reach, point it at a console support file instead.
This needs no credentials, and it contacts no controller:

```bash
unifi-map all --support-file support-XXXX-1234567890.tgz
```

Generate one in the console under **Settings > System > Support File**. It is a
large archive, typically around 150 MiB.

> **Treat a support file as a secret.** It is one of the most sensitive
> things your console can produce. It contains every MAC address,
> hostname, IP, and DHCP lease on your network, your SSIDs, VLANs, and
> subnets, your public WAN addresses and ISP, and extensive logs,
> including per-client connection history.
>
> UniFi redacts *some* credentials on the way out, but the filter
> matches on field **names**, with regular expressions. So anything it
> does not recognise passes through. On one real support file, the
> filter redacted most credential fields, but a set of unredacted access
> tokens remained.
>
> So do not ask whether one particular secret is in there. Assume
> anything the console knows may be. Keep it encrypted. Do not attach it
> to a ticket, and do not paste it into a chat. Delete it when you are
> done. `SECURITY.md` goes into more detail.
>
> This tool reads only seven files out of the archive, and it never
> unpacks the archive. But that limits *this tool*, not the file.

So sending one to someone else is a bigger favour than it looks. If the
question is really about topology, an obfuscated render is usually the
better thing to hand over:

```bash
unifi-map all --support-file support-XXXX.tgz --obfuscate
```

**Reading a support file contacts nothing:** no controller, no
credentials, and no outbound requests of any kind. If you want client
product artwork, that needs Ubiquiti's fingerprint database, which the
archive does not contain. So this is a separate opt-in:

```bash
unifi-map fetch --support-file support-XXXX.tgz --fetch-fingerprints
```

That downloads about 1 MB from Ubiquiti's CDN and caches it, still with
no contact to any controller. The flag governs the download, not the
lookup. The tool reads a database already in the cache whether or not
you pass the flag, since a local file read is not network access. So you
need the flag only once. If you leave it off on a cold cache, clients
draw with no product artwork. Note that `render` still reaches the CDN
for device artwork, unless you pass `--offline`. For a completely
network-free run, use both:

```bash
unifi-map all --support-file support-XXXX.tgz --offline --icons builtin
```

What you get is very close to a live fetch. This project verified the
same network both ways. The infrastructure and the wireless client list
came out identical. VLAN names, subnets, switch port numbers, SSIDs,
client addresses, the ISP name, and Protect camera artwork all survive.

**Client artwork is much reduced.** This is the one place a support file
is clearly worse. Here are the concrete numbers: on the network this
project used for development, an API key resolved product artwork for
**42 of 48** clients, and a support file managed **13 of 47**. That is
roughly a third.

A support file does not store the fingerprint id that client artwork
matches on. You can reconstruct some of it, because the console names a
client after the product it identified, when the client sent no name of
its own. You can look that name back up. But the console only does this
for a client that sent no DHCP hostname and that you never renamed,
which on a real network is a minority. Everything else draws with no
product artwork.

So expect a support-file map to have correct names, addresses, and
connections throughout, with product icons on only a minority of
clients. UniFi hardware that appears as a client is not affected. It
still draws correctly.

The product lookup needs Ubiquiti's published fingerprint database.
That is why it sits behind `--fetch-fingerprints`, described above.
Clients with no fingerprint draw with our own generic client icons,
which need nothing fetched. If you supply the glyph font, it swaps those
for the console's own.

## Choosing a site

**`--site NAME` is required for a support file that holds more than one
site.** With one site, the tool picks it automatically. With several,
the run stops. It lists what it found, so you can say which one you
meant.

This project first tried picking the largest site and warning about it.
That was wrong. The result is a complete, entirely ordinary-looking map,
and if it is the wrong site, nothing about the diagram says so.

(`--support-site` was the original spelling and still works, but `--site` covers
both inputs and is preferred.)

## Limits on reading the archive

The tool reads only seven files out of the archive, as a stream. It
never unpacks the archive. That matters, because a support file also
contains extensive logs.

Reading one has four caps, since the whole point is that somebody else
can send you one. Two caps limit what the tool decodes into memory. The
others limit how much of the archive it walks, in entries and in
uncompressed bytes, because neither follows from the bytes it decodes.

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
of the four errors names the flag to raise.

The defaults come from a single 154M archive off a UDM Pro Max. Its
largest relevant member was 400K, and it held about 2,500 entries. That
is one sample of one small network. So treat the headroom as a guess,
not a measured safety margin: it says nothing about how these numbers
grow with site size. All four are therefore adjustable. If you hit one
legitimately, please open an issue that says so. A second data point
would be worth more than the reasoning that picked these defaults.

If you raise `--support-max-entries`, the tool prints a warning first,
because the cost is easy to miss. With the spinner running, you can at
least see that the step is still going. With `--no-progress`, or output
piped to a file, walking a much larger archive produces no output at all
until it finishes. So a slow run and a hung one look identical.

## Clients without product artwork

Unidentified clients are most common when you read a support file,
because the console's own generic glyphs come from an icon font only a
controller serves, and a support file does not contain one.

They do not stay bare. [Icons we draw
ourselves](artwork.md#the-icons-we-draw-ourselves) cover the same four
distinctions that font encodes: guest and wired against wireless. They
need nothing fetched, so a support-file map is complete, with no console
contact at all. If you want the console's exact glyphs instead, the
artwork page lists the three routes to that font:
[the generic client glyph](artwork.md#the-generic-client-glyph-and-why-it-is-awkward).

## What a support file cannot tell you

A live fetch has two things an archive does not. Neither one stops the
tool from drawing a map:

- Client addresses come from the gateway's DHCP leases and neighbour
  table. So a client that never took a lease, and that went quiet, may
  show no address at all.
- Only the LAN networks appear. The controller's live network list also
  includes WAN and VPN entries. No client belongs to these, and nothing
  draws them.
