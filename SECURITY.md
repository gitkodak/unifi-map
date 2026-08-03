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

Both are short. If you are evaluating whether to trust this, those two files are
the ones to read.

## It only ever reads

There is no code path that changes anything on your controller: no POST, no PUT,
no PATCH, no DELETE. The tool cannot adopt, restart, reconfigure or forget
anything, because it never asks the controller to.

## Scope of the API key, which is broader than this tool needs

Read this part before you create a key.

**A UniFi API key inherits the permissions of the account that created it.** It is
not scoped to the thing you made it for. Checking a key created under a super
admin against `GET /proxy/network/api/self` reports `is_super: true`, and a POST
with that key is rejected for having an invalid body rather than for being
unauthorised. In other words the key was allowed to write.

So although this tool only ever reads, **the credential you hand it can do more
than that**. That is a property of UniFi's key model, not a requirement of this
tool.

What follows:

- **Create the key under the least privileged admin account you can**, not under
  your super admin. The key is as powerful as the account behind it.
- **A key cannot be scoped, and the account probably cannot be either.**
  Inspecting keys through `GET /proxy/users/api/v2/user/self/keys` shows a
  `key_permissions` field that is empty on every key, alongside a `permissions`
  map reading `{"network.management": ["admin"]}` and a `scopes` list containing
  everything the account can do. Nothing populates the per-key field, so a key is
  simply the account that made it.

### Why this asks for more access than it uses

This is the obvious objection, and it deserves a straight answer rather than a
shrug. The short version: UniFi does not appear to offer a credential narrow
enough to match what the tool does, and the places you would expect to find one
each dead end.

**Read-only roles exist.** `GET /proxy/users/api/v2/roles` shows
`custom_administrator` roles carrying permissions like
`{"network.management": ["readonly"], "protect.management": ["readonly"]}`, which
is exactly what this tool needs. So the permission model can express it.

**But scoping only exists for admins.** There is no way to give a plain user
limited application permissions; you get there by making them an admin and then
restricting the admin. It is an awkward arrangement, and it is why the answer to
"why not just use a normal account" is not simply "you should".

**A key can only be created by the account that will own it.** This is enforced
by the platform, not merely hidden in the interface. A super admin can *read*
another user's keys through `GET /proxy/users/api/v2/user/{id}/keys`, but the
matching POST is refused outright:

```json
{"code": -5, "codeS": "CODE_OPERATION_FORBIDDEN",
 "msg": "Action not allowed.", "error": "cannot create api key for others"}
```

**And a restricted account cannot create one for itself.** Signed in as a
read-only user, the API key interface is not available. So that route closes too.

Putting those together, on the version tested there is no path to a read-only
API key at all:

1. Permissions can only be scoped by making the account an admin and then
   restricting it. There is no scoping for ordinary users.
2. A privileged account cannot mint a key on a restricted account's behalf. The
   platform refuses.
3. A restricted account cannot mint one for itself. The interface does not offer
   it.

That is not a design decision by this tool. It is the credential UniFi is
willing to issue.

**A regular, non-admin user is not a way out either.** Local-only accounts are an
admin concept. Creating an ordinary user means a cloud login, so you would be
maintaining an email address for the sole purpose of holding an API key, and it
is entirely untested whether the resulting key would even work against the local
API.

Ubiquiti's own community has an open thread asking for read-only API keys:
<https://community.ui.com/questions/Read-Only-API-key-yet/940e5b06-bc4d-4742-9760-cbb6f8882f60>

So the honest position is: **assume the key you give this tool carries the full
permissions of the account that created it.** Use a dedicated key rather than
sharing one, keep it in a secrets store if you have one, and revoke it rather
than rotating a password if it leaks. The tool's own behaviour is the part you
can actually verify, and it is one command away.

If you find a version or a path where a genuinely restricted key works, that is a
very welcome issue. The tool only reads, so it should work; nobody has been able
to construct the credential to prove it.

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
  the SVG has all of it as selectable text. Think before sharing a render of a
  real network.

Both are gitignored. Files in both are created mode `0600`, and directories this
tool creates are `0700`. The mode is set on a temporary file *before* it is moved
into place, rather than applied afterwards, so there is no moment at which a
fresh file is readable by other local accounts. That restricts who can read it on
this machine; it does not stop you sending it to anyone, which remains the
likelier way for one of these to escape.

If you want to show someone what the output looks like, use the shipped demo
dataset (`make demo`). It is entirely synthetic.

When filing an issue, redact or use the demo data. Nobody needs your real
inventory to help you.

## A support file is a secret. Treat it like a password vault

`--support-file` was added partly so people could share a topology without
sharing an API key. **Do not read that as "a support file is safe to share."
It is the opposite.** A support file is one of the most sensitive artefacts your
console can produce, and it deserves the same handling as a credential store:
encrypted at rest, never in a ticket, never in a chat window, never in a
repository, and deleted when you are done with it.

UniFi does apply a redaction pass before writing one. You can read it yourself
inside the archive at `system/tmp/pii/pii_filter`: it is a list of `sed`
expressions that rewrite matching values to `<FILTERED>`. That is worth knowing
because of how it works, not because of what it catches:

- **It matches on field *names*, by regular expression.** Anything whose key does
  not match one of those patterns passes through untouched. A filter of that
  shape cannot be complete, and cannot be assumed complete after a firmware
  update adds new fields.
- **It is demonstrably incomplete today.** Inspecting one real support file
  (UniFi OS 5.1.26, Network 10.5.67), most credential-shaped fields were indeed
  `<FILTERED>`, but a set of long, unique, unredacted access tokens remained in
  `unifi/teleport.json`.

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

**No file or request body is sent, but that is not the same as sending
nothing.** The URLs themselves carry information about your network:

- Device artwork is requested by hardware `sysid`, so the request says which
  UniFi models you own.
- Client artwork is requested by fingerprint `dev_id`, so it says which
  products the console has identified on your network.
- An ISP brand mark is requested by your provider's `asn`, so it says who
  supplies your connectivity.

Taken together, and correlated with your source address and the timing of a
render, that is a partial inventory disclosed to Ubiquiti's CDN. No hostnames,
addresses, MAC addresses or SSIDs are included, and nothing is uploaded, but
"nothing is uploaded" would be a misleading way to summarise it.

To avoid that entirely, use `--icons builtin`, which draws only icons this
project renders locally and touches no external host, or `--offline`, which
forbids fetching and uses only what is already cached.

## TLS

Certificate verification is on by default. `UNIFI_VERIFY_TLS=false` disables it,
which is sometimes necessary because consoles serve a self-signed certificate on
their bare IP address. Understand that this makes the connection
interceptable on an untrusted network. Pointing the tool at a hostname with a
valid certificate, or at a CA bundle path, is better where possible.

## How the credential is protected

- **It is never written into the process environment.** A key read from a
  credential file is parsed into a mapping, not exported, so no child process
  inherits it. Anything you export yourself is stripped from the environment
  handed to child processes.
- **It is not carried across a redirect to another host.** `requests` does that
  for `Authorization` and nothing else, and ours is a custom `X-API-KEY` header.
  A redirect that changes host, port or scheme drops it and says so. Redirects
  themselves still work, so a reverse proxy in front of your console is fine.
- **Graphviz is executed by resolved absolute path**, not by name, so a binary
  earlier on `PATH` cannot stand in for it.
- **A credential file that other local accounts can read produces a warning**,
  and the file that was loaded is named, since `./.env` is searched before the
  home config.

## How untrusted input is handled

A support file is somebody else's data by design, so it is parsed as hostile.

- **Member paths are anchored**, requiring exactly one leading directory
  component and then the expected path. A trailing-fragment match would let a
  crafted archive add `evil/unifi/devices.json` and win by appearing earlier in
  the stream, which would let the sender choose the topology you see. That was a
  real defect, found by review and fixed.
- **Nothing is extracted to disk.** The archive is streamed, only seven members
  are decoded, non-regular members are skipped, and members, the total and the
  entry count are all capped. The size caps are adjustable, because refusing a
  legitimately large network would be its own failure.
- **Device names become text, not markup.** Every draw.io cell enables HTML, and
  draw.io decodes the XML attribute before parsing it, so values are HTML-escaped
  before the diagram's own `<b>` and `<br>` are added. A device named
  `<img src=x onerror=...>` renders as those characters.
- **Downloaded images are size-capped** on the declared length and again on what
  arrives, and the decompression-bomb threshold is tightened well below Pillow's
  default, which is sized for photographs rather than icons.

## `unifi-map shape`, and why its output is safe to send

There is a subcommand whose entire purpose is producing something to give to a
stranger, so it is worth saying how it is constrained.

`unifi-map shape` prints counts, fan-out, artwork resolution rates, version
numbers, and the **names** of the fields your controller returns. It never
prints a value from any field, so no address, MAC, hostname, SSID, site name or
network name can appear in it.

That is achieved by construction rather than by filtering. Every line is a
counted integer, a boolean, or a field name from a list written in advance;
nothing walks your data looking for things to remove. The distinction matters
because a filter can be incomplete, and the one shipped by UniFi is: see the
support-file section above, where a name-matching redaction pass left
unredacted access tokens in place. A list that only ever adds cannot fail that
way.

One concrete trap shaped the design. A support file's `devices.json` is a list
of objects **keyed by site name**, which users choose, so describing a payload
by enumerating its JSON keys would leak site names on exactly the multi-site
archives most worth seeing. Container keys are never read; only records inside
them, and only their field names. Field names that are not shaped like field
names are counted rather than printed.

Two tests hold this up. One renders a snapshot built entirely from identifying
values and searches the output for every one. The other asserts the report's
whole vocabulary is closed, so a value arriving by a route nobody anticipated
fails even though no test knew to look for it.

The command prints what it collects and asks before producing anything, and it
transmits nothing: the report goes to your terminal, and what happens next is
your decision.

## What has and has not been reviewed

Stated plainly, since it bears on how much you should trust this: most of the
code was written by an AI assistant under the maintainer's direction and testing.
`AI_DISCLOSURE.md` covers that in full.

**Independent review is ongoing rather than a finished audit**, by several AI
systems working from the source, none of them the assistant that wrote the code:
security audits, documentation reviews, code reviews and architectural reviews,
more than one of each. They overlap heavily. Reviews run when a substantial
change lands, so treat this as a practice rather than as a total.
Everything raised is fixed except one item declined with its reason recorded
in `CLAUDE.md`: no hashed dependency lock file, on the grounds that it is real
ongoing maintenance for a dev-only benefit while Dependabot and the advisory
job cover staying current. A second item was declined at the time (tightening
the support-file size caps without data from a large site) and was then done
anyway, by making the caps adjustable and lowering the defaults.

The serious findings were reproduced before being fixed and re-tested
afterwards.

Every review found something all the previous ones had missed, and not
marginally. The second found a real vulnerability in support-file parsing. The
fifth found that a support archive could force unbounded decompression, and that
an existing output directory was being silently tightened to mode 0700. The
sixth still found four things.

That is the argument for more than one reviewer, and against reading any single
review, including these, as exhaustive.

**There has been no line-by-line human security review, and no penetration
test.** Those reviews were thorough and useful; they are not the same thing.
