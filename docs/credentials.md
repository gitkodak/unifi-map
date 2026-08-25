# Credentials

[← Documentation index](../README.md#documentation)

This page covers how to give `unifi-map` access to a controller, and what
that access allows.

```bash
install -m 600 .env.example .env      # then edit
```

This uses `install -m 600` rather than `cp`, on purpose. A plain copy
inherits your umask, which on most systems leaves the file world-readable,
and the file is about to hold an API key with your account's permissions.
`unifi-map` warns if it reads a credential file that others can see.

Or set `UNIFI_MAP_ENV=/path/to/credentials` to keep them outside the
project. The tool searches files in this order: `--env-file`,
`$UNIFI_MAP_ENV`, `./.env`, `~/.config/unifi-map/env`. Real environment
variables always win.

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
| `UNIFI_SITE` | no | `default` | Which site to read. `--site` overrides it (see below) |
| `UNIFI_VERIFY_TLS` | no | `true` | `true`, `false`, or a path to a CA bundle |

`UNIFI_HOST` may include an `https://` prefix, but does not need one. The
tool upgrades an explicit `http://` prefix to HTTPS. It never contacts a
controller over plaintext HTTP.

### `UNIFI_API_KEY`

Create a key in the UniFi OS settings, under the integrations section
(the exact wording moves between versions). This tool only ever reads,
so read-only permission would be enough. On the version tested, UniFi
offers no way to issue a key that restricted. See
[`SECURITY.md`](../SECURITY.md) for what a key can do, before you decide
how much that matters to you.

A key is the only supported credential. There is no login and no
session, so nothing needs to stay alive or get refreshed.

A key inherits the permissions of the account that created it, and UniFi
does not appear to offer a narrower one. `SECURITY.md` explains why,
what this project tried, and what this tool actually requests: ten GET
requests and nothing else.

### `UNIFI_HOST`

Just the host, optionally with a port: `unifi.example.com`, `192.168.1.1`, or
`unifi.example.com:8443`. No path. A scheme is optional and `https://` is
assumed, so `unifi.example.com` and `https://unifi.example.com` are equivalent.

### `UNIFI_SITE`

A UniFi controller can manage several *sites* (separate networks under
one controller). If you never created a second one, yours is `default`,
and you can ignore this.

`--site NAME` does the same thing and takes precedence. Reach for this
when you script. It saves you from setting the variable again for each
invocation, and it works for support files too.

```bash
for site in default branch-office warehouse; do
  unifi-map --site "$site" all --name "map-$site"
done
```

The catch is that this wants the site's **internal name**, not the label
the UI shows. These are separate fields. On a single-site console, the
internal name is `default`, while the UI label is `Default`. On a
controller where you created and named sites yourself, the internal name
is usually an opaque short string that looks nothing like the name you
typed.

There are two ways to find the right value:

- **From the URL.** Open the site in the web UI and look at the address bar. The
  segment after `/site/` is the internal name.
- **Ask the controller.** `GET /proxy/network/api/self/sites` lists
  every site your account can see. Use the `name` field, not `desc`.
  `desc` is the UI label.

This project only tested a single-site controller. If you run several
sites, and something looks wrong or empty, check this variable first.

### `UNIFI_VERIFY_TLS`

`true` (the default) verifies the certificate normally. Use `false` when
you connect to a bare IP, because consoles serve a self-signed
certificate there, and verification fails. The tool treats any other
value as a path to a CA bundle. Use that if you terminate TLS with a
private CA.

If you connect to a bare IP, set this to `false`:

```bash
UNIFI_HOST=192.168.1.1
UNIFI_VERIFY_TLS=false
```

### `UDM_*` names were removed in 0.9.0

Every variable used to also answer to a `UDM_*` spelling: `UDM_HOST`,
`UDM_API_KEY`, `UDM_SITE`, `UDM_VERIFY_TLS`. They existed only because
the author called things that before this tool existed. They warned from
0.7.0 on. They are gone now.

If you are still on them, rename them to the `UNIFI_*` spellings above. Nothing
subtle happens if you do not: the tool reports the missing variable by name and
exits, the same as it would on a fresh install.

Two `UDM_*` variables were already dead before this: `UDM_USER` and
`UDM_PASS`. Delete them from any credential file that still carries
them. Nothing reads them, since this project removed password
authentication.

The tool does not read `UNIFI_MAP_ENV` from the credential file itself.
It is the environment variable that says *where* the credential file is.

## Preferences: the config file and `UNIFI_MAP_*`

Everything in this section is a preference rather than a credential. None of it
is required, and none of it needs the credential file.

`UNIFI_*` is the controller's namespace. So anything that belongs to
this tool, rather than to your console, uses the `UNIFI_MAP_*` spelling.

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
`XDG_CONFIG_HOME`. Keys are flat, and their names match the flags:

```toml
theme   = "dark"
layout  = "tree"
formats = ["svg", "png"]

cache_dir = "~/.local/share/unifi-map/cache"
overrides = "~/.config/unifi-map/overrides.toml"
```

An unrecognised key is an error, not a shrug. So a mistyped `them`
reports the error, rather than silently succeeding.

### Which one wins

**Flag, then environment, then config file, then the built-in default.**

Environment above config file is deliberate. It is the container case:
an image can carry a `config.toml`, and a deployment can override it
with `-e`, with no rebuild needed. That does not work the other way
round.

Every run says where a value it did not get from the command line came from:

```
Style: icons=unifi layout=tree theme=dark
Settings not from the command line: layout from config file /home/you/.config/unifi-map/config.toml, theme from environment (UNIFI_MAP_THEME)
```

That line exists for a reason. A preference that comes from a forgotten
file is exactly what makes the same command produce different pictures
on two machines.

### What is deliberately not configurable

**`--obfuscate` and `--force` are flags only.** There is no variable and no
config key, and this is not an oversight.

`--obfuscate` is a claim that the output is safe to hand to somebody
else. If that setting came from ambient state, somebody could publish a
map believing it was scrubbed, when in fact a variable was set in one
shell and not another. `--force` overwrites files. Both actions should
be visible in the command that caused them.

**In a container, this means you pass the flag. You do not set a
variable.** If your image has an entrypoint of `unifi-map`, append the
flag as you would any argument:

```bash
docker run --rm -v "$PWD/out:/out" your-image render --obfuscate
```

If the entrypoint is a wrapper script that does not forward arguments, override
it for the one run:

```bash
docker run --rm --entrypoint unifi-map -v "$PWD/out:/out" your-image render --obfuscate
```

`--entrypoint` replaces the program, but keeps the image, so everything
after the image name becomes that program's arguments. This project does
not publish a container image today. Both examples assume one you built
yourself.

**Set `UNIFI_MAP_CACHE_DIR`.** This is the one setting worth changing. A
snapshot is a complete inventory of your network: every MAC, hostname,
address, and lease, your SSIDs, and your subnets. By default, it goes in
the working directory, which for anyone who works on this tool is a git
checkout. A directory named `cache.bak`, made before a risky fetch, does
not fall under the `.gitignore` entry for `cache/`. Point it somewhere
outside any repository to remove the question:

```bash
UNIFI_MAP_CACHE_DIR=~/.local/share/unifi-map/cache
```

The settings are independent on purpose. If you set only the snapshot
cache, artwork still goes to `cache/assets`. This matters because
`--cache-dir examples/demo` must not let downloads land in the shipped
demo dataset.

### Renamed in this release

`UNIFI_CACHE_DIR`, `UNIFI_ASSET_CACHE`, and `UNIFI_OUT_DIR` are the old
spellings of the first three. They still work and warn. This project
will remove them eventually. Rename them in your credential file to the
`UNIFI_MAP_*` forms above.

This project tested all of this against UniFi Network 10.5.67 on a UDM
Pro Max, with a single site.
