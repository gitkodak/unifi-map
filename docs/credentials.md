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

`UNIFI_HOST` may include an `https://` prefix, but does not need one. An
explicit `http://` prefix is upgraded to HTTPS; the tool never contacts a
controller over plaintext HTTP.

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

### `UDM_*` names were removed in 0.9.0

Every variable used to answer to a `UDM_*` spelling as well: `UDM_HOST`,
`UDM_API_KEY`, `UDM_SITE`, `UDM_VERIFY_TLS`. They existed only because that is
what the author had called things before this tool did, they warned from 0.7.0,
and they are gone.

If you are still on them, rename them to the `UNIFI_*` spellings above. Nothing
subtle happens if you do not: the tool reports the missing variable by name and
exits, the same as it would on a fresh install.

Two `UDM_*` variables were already dead before this and are worth deleting from
any credential file that still carries them: `UDM_USER` and `UDM_PASS`, unread
since password authentication was removed.

`UNIFI_MAP_ENV` is not read from the credential file itself; it is the
environment variable that says *where* the credential file is.

## Preferences: the config file and `UNIFI_MAP_*`

Everything in this section is a preference rather than a credential. None of it
is required, and none of it needs the credential file.

`UNIFI_*` is the controller's namespace, so anything belonging to this tool
rather than to your console is spelled `UNIFI_MAP_*`.

| Variable | Config key | Sets | Default |
| --- | --- | --- | --- |
| `UNIFI_MAP_CACHE_DIR` | `cache_dir` | `--cache-dir`, where snapshots go | `cache/` |
| `UNIFI_MAP_ASSET_CACHE` | `asset_cache` | `--asset-cache`, where artwork is cached | `cache/assets/` |
| `UNIFI_MAP_OUT_DIR` | `out_dir` | `--out-dir`, where diagrams are written | `out/` |
| `UNIFI_MAP_OVERRIDES` | `overrides` | `--overrides`, your corrections file | `./overrides.toml` if present |
| `UNIFI_MAP_THEME` | `theme` | `--theme` | `light` |
| `UNIFI_MAP_LAYOUT` | `layout` | `--layout` | `unifi` |
| `UNIFI_MAP_ICONS` | `icons` | `--icons` | `unifi` |
| `UNIFI_MAP_FORMATS` | `formats` | `--formats` | `svg drawio` |

The config file lives at `~/.config/unifi-map/config.toml`, beside the
credential file, or wherever `UNIFI_MAP_CONFIG` points. It honours
`XDG_CONFIG_HOME`. Keys are flat and named after the flags:

```toml
theme   = "dark"
layout  = "tree"
formats = ["svg", "png"]

cache_dir = "~/.local/share/unifi-map/cache"
overrides = "~/.config/unifi-map/overrides.toml"
```

An unrecognised key is an error rather than a shrug, so a mistyped `them` says
so instead of quietly doing nothing.

### Which one wins

**Flag, then environment, then config file, then the built-in default.**

Environment above config file is deliberate, and it is the container case: an
image can carry a `config.toml` that a deployment overrides with `-e` without
rebuilding. That does not work the other way round.

Every run says where a value it did not get from the command line came from:

```
Style: icons=unifi layout=tree theme=dark
Settings not from the command line: layout from config file /home/you/.config/unifi-map/config.toml, theme from environment (UNIFI_MAP_THEME)
```

That line exists because a preference arriving from a file you have forgotten
about is exactly what makes the same command produce different pictures on two
machines.

### What is deliberately not configurable

**`--obfuscate` and `--force` are flags only.** There is no variable and no
config key, and this is not an oversight.

`--obfuscate` is a claim that the output is safe to hand to somebody else.
Sourcing that from ambient state means a map can be published in the belief it
was scrubbed, because a variable was set in one shell and not another.
`--force` overwrites files. Both should be visible in the command that caused
them.

**In a container this means passing the flag, not setting a variable.** If your
image has an entrypoint of `unifi-map`, append the flag as you would any
argument:

```bash
docker run --rm -v "$PWD/out:/out" your-image render --obfuscate
```

If the entrypoint is a wrapper script that does not forward arguments, override
it for the one run:

```bash
docker run --rm --entrypoint unifi-map -v "$PWD/out:/out" your-image render --obfuscate
```

`--entrypoint` replaces the program while keeping the image, so everything after
the image name becomes that program's arguments. There is no container image
published for this project today; both examples assume one you have built.

**`UNIFI_MAP_CACHE_DIR` is the one worth setting.** A snapshot is a complete
inventory of your network: every MAC, hostname, address and lease, your SSIDs
and subnets. The default puts it in the working directory, which for anyone
working on this tool is a git checkout, and a directory named `cache.bak` made
before a risky fetch is not covered by a `.gitignore` entry for `cache/`.
Pointing it somewhere outside any repository removes the question:

```bash
UNIFI_MAP_CACHE_DIR=~/.local/share/unifi-map/cache
```

The settings are independent on purpose. Setting only the snapshot cache leaves
artwork in `cache/assets`, because `--cache-dir examples/demo` must not cause
downloads to be written into the shipped demo dataset.

### Renamed in this release

`UNIFI_CACHE_DIR`, `UNIFI_ASSET_CACHE` and `UNIFI_OUT_DIR` are the old spellings
of the first three. They still work and warn, and they will be removed. Rename
them in your credential file to the `UNIFI_MAP_*` forms above.

Tested against UniFi Network 10.5.67 on a UDM Pro Max, with a single site.
