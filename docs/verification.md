# What has been checked

For anybody deciding how much to trust this. What was verified directly, what
was not, and the limits worth knowing before you rely on a diagram.

## What has been checked, and what has not

Some of this is observed behaviour and some of it is reasonable inference. The
difference matters if you hit a problem, so:

**Checked directly**, against UniFi Network 10.5.67 on a UDM Pro Max:
authentication, every endpoint used, artwork lookup for both UniFi hardware and
clients, the icon font fallback, both layouts, both themes, all five output
formats, the offline and no-artwork paths, and opening the generated `.drawio`
in draw.io.

**Not checked:**

- **More than one site.** The test console has a single site. The advice above
  about internal site names comes from how UniFi behaves generally, not from
  something observed here, which is why it points you at the URL and the API
  rather than telling you what the value will look like.
- **Importing into Lucid.** Lucid documents `.drawio` import; that has not been
  tried with a file from this tool.
- **Any controller other than a UDM Pro Max**, or any Network version other than
  10.5.67. Older or newer controllers may move or reshape these endpoints.

If any of these turn out to be broken, that is a bug worth reporting rather than
a known limitation.

## Which UniFi applications this has seen

UniFi is several products sharing a console. This has only ever run against two
of them.

| Application | Status |
| --- | --- |
| **Network** | Everything here comes from it. Verified against 10.5.67. |
| **Protect** | One endpoint, `integration/v1/cameras`, read only to settle whether a MAC is a camera. |
| **Access** | Never seen. Readers appear as ordinary clients. |
| **Talk** | Never seen. Phones appear as ordinary clients. |
| **Drive / UNAS** | Never seen. A UNAS should draw as ordinary UniFi hardware, since it has a `sysid` like anything else, but that is inference. |
| **Identity, Connect, LED** | Never seen, and no reason yet to think they add anything. |

Protect is read for one reason, which is the shape of the problem generally: the
hardware catalogue has both a `UVC-G3-FLEX` camera and a `UA-G3-Flex` Access
reader, so a device calling itself `g3-flex` is ambiguous and the match is
refused rather than guessed. Protect's camera list settles it in one direction.
**Nothing settles it in the other**, because there is no Access installation
here to ask.

So the gap is narrower than "no Access support". Devices from the other
applications already draw: they are clients or UniFi hardware like anything
else, matched on fingerprint or `sysid`. What is missing is the extra source
that would let an ambiguous match resolve, and a role for a node beyond what
Network reports.

**Installing an application without owning its devices is worth less than it
sounds, but not nothing.** An empty `/proxy/access/...` still answers whether
the endpoint exists, what path it lives at, whether the same API key reaches it,
and what envelope it returns, which is the question `unwrap()` exists for. It
cannot show what a populated record looks like, and that is the part matching
needs. Half an answer, cheaply.

## Caveats

- Only **active** clients appear. A powered-off device isn't in `stat/sta` and
  won't be on the map.
- Wireless client counts drift between runs as devices roam and sleep. Two
  snapshots minutes apart won't match exactly; that's the network, not a bug.
- `cache/` holds a MAC, hostname and IP inventory of every device on your
  network. It's gitignored and written `0600`. Don't commit it or paste it into
  an issue.

<!-- BEGIN GENERATED FLAGS -->
