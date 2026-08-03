# Mapping from a support file

Reading a console support file instead of talking to a controller: what it
needs, what it costs, and why the file itself must be treated as a secret.

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
touching any controller. The flag governs the download, not the lookup: a
database already in the cache is read whether or not you pass it, since reading
a local file is not network access. So the flag is needed once, and leaving it
off on a cold cache is what leaves clients without product artwork. Note that `render` does reach the CDN for device artwork unless
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

## Choosing a site

**`--site NAME` is required for a support file holding more than one site.**
One site and it is picked automatically; several and the run stops, listing what
it found, so you can say which you meant.

Mapping the largest and warning was tried first and was wrong. The result is a
complete, entirely ordinary looking map, and if it is the wrong site nothing
about the diagram says so.

(`--support-site` was the original spelling and still works, but `--site` covers
both inputs and is preferred.)

## Limits on reading the archive

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

## Clients without artwork

Reading a support file is the case where unidentified clients most often draw as
plain shapes, because the generic glyphs come from an icon font only a
controller serves and a support file does not contain one. What that costs and
the three ways around it are on the artwork page:
[the generic client glyph](artwork.md#the-generic-client-glyph-and-why-it-is-awkward).

## What a support file cannot tell you

Two things a live fetch has and an archive does not, neither of which stops a
map being drawn:

- Client addresses come from the gateway's DHCP leases and neighbour table, so a
  client that never took a lease and had gone quiet may have no address shown.
- Only the LAN networks appear. The controller's live network list also includes
  WAN and VPN entries, which no client belongs to and which nothing draws.
