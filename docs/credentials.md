# Credentials

[← Documentation index](../README.md#documentation)

Everything about giving `unifi-map` access to a controller, and what that
access amounts to.

```bash
install -m 600 .env.example .env      # then edit
```

`install -m 600` rather than `cp` on purpose. A plain copy inherits your umask,
which on most systems leaves the file world-readable, and it is about to hold an
API key with your account's permissions. `unifi-map` warns if it reads a
credential file that others can see.

Or set `UNIFI_MAP_ENV=/path/to/credentials` to keep them outside the project.
Files are searched in order: `--env-file`, `$UNIFI_MAP_ENV`, `./.env`,
`~/.config/unifi-map/env`. Real environment variables always win.

```bash
UNIFI_HOST=unifi.example.com
UNIFI_API_KEY=...
UNIFI_SITE=default
UNIFI_VERIFY_TLS=true
```

| Variable | Required | Default | What it is |
| --- | --- | --- | --- |
| `UNIFI_HOST` | yes | | Hostname or IP of the console or controller |
| `UNIFI_API_KEY` | yes | | An API key (see below) |
| `UNIFI_SITE` | no | `default` | Which site to read; `--site` overrides it (see below) |
| `UNIFI_VERIFY_TLS` | no | `true` | `true`, `false`, or a path to a CA bundle |

### `UNIFI_API_KEY`

Create a key in the UniFi OS settings, under the integrations section (the exact
wording moves between versions). This tool only ever reads, so read-only
permission would be enough; on the version tested, UniFi offers no way to issue
a key that restricted. See [`SECURITY.md`](../SECURITY.md) on what a key can do before
deciding how much that matters to you.

A key is the only supported credential. There is no login and no session, so
nothing has to be kept alive or refreshed.

A key inherits the permissions of the account that created it, and UniFi does not
appear to offer a narrower one. `SECURITY.md` explains why, what was tried, and
what this tool actually requests, which is ten GET requests and nothing else.

### `UNIFI_HOST`

Just the host, optionally with a port: `unifi.example.com`, `192.168.1.1`, or
`unifi.example.com:8443`. No path. A scheme is optional and `https://` is
assumed, so `unifi.example.com` and `https://unifi.example.com` are equivalent.

### `UNIFI_SITE`

A UniFi controller can manage several *sites* (separate networks under one
controller). If you have never created a second one, yours is `default` and you
can ignore this.

`--site NAME` does the same thing and takes precedence, which is the one to
reach for when scripting: it saves re-exporting a variable per invocation, and
it works for support files too.

```bash
for site in default branch-office warehouse; do
  unifi-map --site "$site" all --name "map-$site"
done
```

The catch is that this wants the site's **internal name**, which is not the
label shown in the UI. They are separate fields: on a single-site console the
internal name is `default` while the UI label is `Default`. On a controller
where you created and named sites yourself, the internal name is usually an
opaque short string that looks nothing like the name you typed.

Two ways to find the right value:

- **From the URL.** Open the site in the web UI and look at the address bar. The
  segment after `/site/` is the internal name.
- **Ask the controller.** `GET /proxy/network/api/self/sites` lists every site
  your account can see. Use the `name` field, not `desc`; `desc` is the UI label.

Only a single-site controller has actually been tested, so if you run several
sites and something looks wrong or empty, this variable is the first thing to
check.

### `UNIFI_VERIFY_TLS`

`true` (the default) verifies the certificate normally. Use `false` when you are
connecting to a bare IP, because consoles serve a self-signed certificate there
and verification will fail. Any other value is treated as a path to a CA bundle,
which is what you want if you terminate TLS with a private CA.

If you connect to a bare IP, set this to `false`:

```bash
UNIFI_HOST=192.168.1.1
UNIFI_VERIFY_TLS=false
```

### Legacy variable names, deprecated

Every variable also answers to a `UDM_*` spelling: `UDM_HOST`, `UDM_API_KEY`,
`UDM_SITE`, `UDM_VERIFY_TLS`. If both are set, the `UNIFI_*` one wins.

These exist only because that is what the author had called things before this
tool did. **They still work and will be removed in a future version**, so rename
them when convenient. Using one prints a warning naming the replacement.

No removal version is promised. Everything about this interface may change
before 1.0.

`UNIFI_MAP_ENV` is not read from the credential file itself; it is the
environment variable that says *where* the credential file is.

## Where things are written

Three more variables, which are not credentials but are set the same way, in
the environment or in the credential file:

| Variable | Sets | Default |
| --- | --- | --- |
| `UNIFI_CACHE_DIR` | `--cache-dir`, where snapshots go | `cache/` |
| `UNIFI_ASSET_CACHE` | `--asset-cache`, where artwork is cached | `cache/assets/` |
| `UNIFI_OUT_DIR` | `--out-dir`, where diagrams are written | `out/` |

A flag always beats the variable, and the variable beats the default, so a
one-off run can still point somewhere else without editing anything.

**`UNIFI_CACHE_DIR` is the one worth setting.** A snapshot is a complete
inventory of your network: every MAC, hostname, address and lease, your SSIDs
and subnets. The default puts it in the working directory, which for anyone
working on this tool is a git checkout, and a directory named `cache.bak` made
before a risky fetch is not covered by a `.gitignore` entry for `cache/`.
Pointing it somewhere outside any repository removes the question:

```bash
UNIFI_CACHE_DIR=~/.local/share/unifi-map/cache
```

The three are independent on purpose. Setting only `UNIFI_CACHE_DIR` leaves
artwork in `cache/assets`, because `--cache-dir examples/demo` must not cause
downloads to be written into the shipped demo dataset.

Tested against UniFi Network 10.5.67 on a UDM Pro Max, with a single site.
