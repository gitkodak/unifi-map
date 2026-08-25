# Security

## Reporting

If you find something you would rather not discuss in public, open a private
security advisory through GitHub's "Report a vulnerability" button on the
Security tab. If that is unavailable, email sakodak@gmail.com.

Please do not open a public issue for anything that would expose someone's
network before they can update.

This is a hobby project maintained in spare time. Expect a reply in days rather
than hours.

## What this tool does with your credentials

It reads an API key from the environment or from a credential file, sends it in
an `X-API-KEY` header, and makes GET requests. That is the whole of it.

- `src/unifi_map/config.py` is the only module that reads configuration from
  the environment. (`layout.py` enumerates `os.environ` for one purpose: to
  build a child environment with the credential variables removed.)
- `src/unifi_map/client.py` is the only module that talks to your controller.

Both are short. If you want to decide whether to trust this, those two files
are the ones to read.

## It only ever reads

There is no code path that changes anything on your controller: no POST, no PUT,
no PATCH, no DELETE. The tool cannot adopt, restart, reconfigure or forget
anything, because it never asks the controller to.

## Scope of the API key, which is broader than this tool needs

Read this part before you create a key.

**A UniFi API key inherits the permissions of the account that created
it.** It is not scoped to the thing you made it for. If you check a key
created under a super admin against `GET /proxy/network/api/self`, it
reports `is_super: true`. A POST with that key gets rejected for an
invalid body, not for being unauthorised. In other words, the key was
allowed to write.

So although this tool only ever reads, **the credential you hand it can do more
than that**. That is a property of UniFi's key model, not a requirement of this
tool.

What follows:

- **Create the key under the least privileged admin account you can**, not under
  your super admin. The key is as powerful as the account behind it.
- **A key cannot be scoped, and the account probably cannot be
  either.** If you inspect keys through
  `GET /proxy/users/api/v2/user/self/keys`, it shows a `key_permissions`
  field that is empty on every key, alongside a `permissions` map that
  reads `{"network.management": ["admin"]}`, and a `scopes` list that
  contains everything the account can do. Nothing populates the per-key
  field, so a key is simply the account that made it.

### Why this asks for more access than it uses

This is the obvious objection, and it deserves a straight answer rather than a
shrug. The short version: UniFi does not appear to offer a credential narrow
enough to match what the tool does, and the places you would expect to find one
each dead end.

**Read-only roles exist.** `GET /proxy/users/api/v2/roles` shows
`custom_administrator` roles carrying permissions like
`{"network.management": ["readonly"], "protect.management": ["readonly"]}`, which
is exactly what this tool needs. So the permission model can express it.

**But scoping only exists for admins.** There is no way to give a plain
user limited application permissions. You get there only by making them
an admin, then restricting the admin. It is an awkward arrangement, and
it is why the answer to "why not just use a normal account" is not
simply "you should".

**Only the account that will own a key can create it.** The platform
enforces this. It is not merely hidden in the interface. A super admin
can *read* another user's keys through
`GET /proxy/users/api/v2/user/{id}/keys`, but the platform refuses the
matching POST outright:

```json
{"code": -5, "codeS": "CODE_OPERATION_FORBIDDEN",
 "msg": "Action not allowed.", "error": "cannot create api key for others"}
```

**And a restricted account cannot create one for itself.** If you sign
in as a read-only user, the API key interface is not there. So that
route closes too.

Put those together, and on the version tested there is no path to a
read-only API key at all:

1. You can only scope permissions by making the account an admin, then
   restricting it. There is no scoping for ordinary users.
2. A privileged account cannot mint a key on a restricted account's
   behalf. The platform refuses.
3. A restricted account cannot mint one for itself. The interface does
   not offer it.

That is not a design decision by this tool. It is the credential UniFi is
willing to issue.

**A regular, non-admin user is not a way out either.** Local-only
accounts are an admin concept. An ordinary user needs a cloud login, so
you would maintain an email address for the sole purpose of holding an
API key. Whether the resulting key would even work against the local
API is entirely untested.

Ubiquiti's own community has an open thread asking for read-only API keys:
<https://community.ui.com/questions/Read-Only-API-key-yet/940e5b06-bc4d-4742-9760-cbb6f8882f60>

So the honest position is: **assume the key you give this tool carries the full
permissions of the account that created it.** Use a dedicated key rather than
sharing one, keep it in a secrets store if you have one, and revoke it rather
than rotating a password if it leaks. The tool's own behaviour is the part you
can actually verify, and it is one command away.

If you find a version or a path where a genuinely restricted key works,
that is a very welcome issue. The tool only reads, so it should work.
So far, nobody could construct the credential to prove it.

If you want to confirm the read-only claim rather than take it on trust, grep the
source for a mutating request:

```bash
grep -rnE '\.(post|put|patch|delete)\(' src/
```

That comes back empty. `src/unifi_map/client.py` is the only module that talks to
your controller, and it makes ten GET requests and nothing else.

## The data this produces is sensitive

This is the part people underestimate.

- **`cache/`** holds raw controller responses: a MAC address, hostname and IP
  inventory of every active device on your network, plus your WAN address. Do
  not commit one, do not attach one to an issue, and do not paste one into a
  chat window.
- **`out/`** holds the rendered diagrams. These are not anonymous either. Labels
  carry hostnames, IP addresses, your VLAN names and your public WAN address, and
  the SVG has all of it as selectable text. Think before you share a render of
  a real network.

Both are gitignored. This tool creates files in both as mode `0600`,
and directories as `0700`. It sets the mode on a temporary file
*before* moving it into place, rather than applying the mode
afterwards, so there is no moment at which a fresh file is readable by
other local accounts. That restricts who can read it on this machine.
It does not stop you from sending it to anyone, which remains the
likelier way for one of these to escape.

If you want to show someone what the output looks like, use the shipped demo
dataset (`make demo`). It is entirely synthetic.

When you file an issue, redact the data, or use the demo data instead.
Nobody needs your real inventory to help you.

## A support file is a secret. Treat it like a password vault

This project added `--support-file` partly so people could share a
topology without sharing an API key. **Do not read that as "a support
file is safe to share." It is the opposite.** A support file is one of
the most sensitive artefacts your console can produce, and it deserves
the same handling as a credential store: encrypted at rest, never in a
ticket, never in a chat window, never in a repository, and deleted when
you are done with it.

UniFi does apply a redaction pass before it writes one. You can read it
yourself inside the archive at `system/tmp/pii/pii_filter`: it is a list
of `sed` expressions that rewrite matching values to `<FILTERED>`. That
is worth knowing for how it works, not for what it catches:

- **It matches on field *names*, by regular expression.** Anything
  whose key does not match one of those patterns passes through
  untouched. A filter of that shape cannot be complete, and nobody
  should assume it stays complete after a firmware update adds new
  fields.
- **It is demonstrably incomplete today.** This project inspected one
  real support file (UniFi OS 5.1.26, Network 10.5.67). Most
  credential-shaped fields were indeed `<FILTERED>`, but a set of long,
  unique, unredacted access tokens remained in `unifi/teleport.json`.

So do not reason about a support file by asking "is *this particular* secret in
there?" Assume anything the console knows may be in there, because the archive
also contains, entirely unredacted:

- Every MAC address, hostname, IP address and DHCP lease on the network.
- Your SSIDs, VLAN names and subnets.
- Your public WAN addresses, your ISP and its ASN.
- Extensive logs, including per-client connection history.

This tool reads only seven files out of the archive and never unpacks it, but
that constrains **this tool**, not the file. Once the archive exists on disk, its
whole contents exist on disk.

If someone asks you for a support file to debug a topology problem, consider
whether an obfuscated render (`--obfuscate`) answers the question instead.

## Outbound network access

Beyond your controller, the tool fetches artwork and lookup data from
Ubiquiti's public endpoints (`static.ui.com`) on first use and caches it
locally.

**This tool sends no file or request body, but that does not mean it
sends nothing.** The URLs themselves carry information about your
network:

- The tool requests device artwork by hardware `sysid`, so the request
  says which UniFi models you own.
- It requests client artwork by fingerprint `dev_id`, so it says which
  products the console identified on your network.
- It requests an ISP brand mark by your provider's `asn`, so it says who
  supplies your connectivity.

Take these together, and correlate them with your source address and
the timing of a render: that is a partial inventory disclosed to
Ubiquiti's CDN. It includes no hostnames, addresses, MAC addresses, or
SSIDs, and it uploads nothing. But "nothing is uploaded" would still be
a misleading way to summarise it.

To avoid that entirely, use `--icons builtin`, which draws only icons
this project renders locally, and touches no external host. Or use
`--offline`, which forbids any fetch, and uses only what is already
cached.

## TLS

Certificate verification is on by default. `UNIFI_VERIFY_TLS=false`
disables it, which is sometimes necessary, because consoles serve a
self-signed certificate on their bare IP address. Understand that this
makes the connection interceptable on an untrusted network. Point the
tool at a hostname with a valid certificate, or at a CA bundle path,
instead, where possible.

## How the credential is protected

- **The tool never writes it into the process environment.** It parses
  a key read from a credential file into a mapping, not an exported
  variable, so no child process inherits it. It strips anything you
  export yourself from the environment it hands to child processes.
- **It does not carry the key across a redirect to another host.**
  `requests` does that for `Authorization` and nothing else, and ours
  is a custom `X-API-KEY` header. A redirect that changes host, port, or
  scheme drops the key, and reports that it did so. Redirects
  themselves still work, so a reverse proxy in front of your console is
  fine.
- **This tool resolves Graphviz once to an absolute path, and that
  exact path is what runs**, not the bare name `dot` re-resolved at call
  time. What that buys is narrow, and worth stating exactly: there is
  no second `PATH` lookup, so a `PATH` change after startup cannot
  redirect the call to a different file.

  It does **not** protect the resolved file itself. Anyone who can write to
  that path can replace the binary between resolution and execution, and the
  absolute path will run the replacement. Nor does it protect against `PATH`
  at startup: whatever comes first on `PATH` when this tool starts is
  what it finds, the same as any other program that shells out by name.
  Put a directory you do not control ahead of a trusted Graphviz
  install, and this offers no protection at all.
- **A credential file that other local accounts can read produces a
  warning**, and the tool names the file it loaded, since it searches
  `./.env` before the home config.

## How untrusted input is handled

A support file is somebody else's data by design, so this tool parses it
as hostile.

- **Member paths are anchored.** They require exactly one leading
  directory component, then the expected path. A trailing-fragment
  match would let a crafted archive add `evil/unifi/devices.json` and
  win by appearing earlier in the stream. That would let the sender
  choose the topology you see. That was a real defect. Review found it,
  and this project fixed it.
- **This tool extracts nothing to disk.** It streams the archive,
  decodes only seven members, and skips non-regular members. It caps
  members, the total, and the entry count. The size caps are
  adjustable, because refusing a legitimately large network would be
  its own failure.
- **Device names become text, not markup.** Every draw.io cell enables
  HTML, and draw.io decodes the XML attribute before it parses the
  attribute. So this tool HTML-escapes values before it adds the
  diagram's own `<b>` and `<br>`. A device named
  `<img src=x onerror=...>` renders as those characters.
- **This tool size-caps downloaded images**, on the declared length and
  again on what arrives. It tightens the decompression-bomb threshold
  well below Pillow's default, which is sized for photographs rather
  than icons.

## `unifi-map shape`, and why its output is safe to send

One subcommand exists entirely to produce something you can give a
stranger. So it is worth explaining how this project constrains it.

`unifi-map shape` prints counts, fan-out, artwork resolution rates, version
numbers, and the **names** of the fields your controller returns. It never
prints a value from any field, so no address, MAC, hostname, SSID, site name or
network name can appear in it.

Construction achieves that, not filtering. Every line is a counted
integer, a boolean, or a field name from a list written in advance.
Nothing walks your data to look for things to remove. The distinction
matters, because a filter can be incomplete, and the one UniFi ships is:
see the support-file section above, where a name-matching redaction
pass left unredacted access tokens in place. A list that only ever adds
cannot fail that way.

One concrete trap shaped the design. A support file's `devices.json` is
a list of objects **keyed by site name**, which users choose. So if this
command described a payload by listing its JSON keys, that would leak
site names, on exactly the multi-site archives most worth seeing. This
tool never reads container keys. It reads only the records inside them,
and only their field names. It counts field names that are not shaped
like field names, rather than printing them.

Two tests hold this up. One renders a snapshot built entirely from
identifying values, and searches the output for every one. The other
asserts that the report's whole vocabulary is closed, so a value that
arrives by a route nobody anticipated fails the test, even though no
test knew to look for it.

The command prints what it collects, and asks before it produces
anything. It transmits nothing: the report goes to your terminal, and
what happens next is your decision.

## What has and has not been reviewed

This bears on how much you should trust the tool, so state it plainly:
an AI assistant wrote most of the code, under the maintainer's direction
and testing. `AI_DISCLOSURE.md` covers that in full.

**Independent review is ongoing rather than a finished audit**, by several AI
systems working from the source, none of them the assistant that wrote the code:
security audits, documentation reviews, code reviews and architectural reviews,
more than one of each. They overlap heavily. Reviews run when a substantial
change lands, so treat this as a practice rather than as a total.

This project fixed or acted on everything raised. One item was declined
at the time: a hashed dependency lock file for CI's own installs. The
reasoning was real ongoing maintenance for a dev-only benefit. The
maintainer reversed that decision directly, on 2026-08-13:
`requirements/ci.txt` is now a pip-compile-generated, hash-pinned lock
that Dependabot keeps current, the same tool this project already
relied on for staying current before. See `CLAUDE.md` for the full
reasoning. A second item was declined at the time too: tightening the
support-file size caps without data from a large site. This project did
it anyway later, by making the caps adjustable and lowering the
defaults.

This project reproduced the serious findings before fixing them, then
re-tested them afterwards.

Every review found something all the previous ones missed, and not
marginally. The second found a real vulnerability in support-file
parsing. The fifth found that a support archive could force unbounded
decompression, and that the code was silently tightening an existing
output directory to mode 0700. The sixth still found four things.

That is the argument for more than one reviewer. It also argues against
treating any single review, including these, as exhaustive.

**No line-by-line human security review exists, and no penetration test
does either.** Those reviews were thorough and useful. They are not the
same thing.
