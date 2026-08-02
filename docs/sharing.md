# Sharing a map, and helping upstream

Two things you might want to send somebody: a diagram of your network with
the identifying parts removed, and a description of its shape that carries
none of them in the first place.

## Sharing a map: `--obfuscate`

A rendered map is not anonymous. Labels carry hostnames, addresses, VLAN names
and your WAN address, and an SVG holds all of it as selectable text. That makes
it awkward to ask for help with a layout problem.

```bash
unifi-map render --obfuscate --theme dark
```

![The same real network, obfuscated](images/example-obfuscated-dark.png)

*A real network, obfuscated. Every device is a pseudonym, addresses are
renumbered, and the connections, roles and port numbers are untouched. Product
artwork stays, because it says what a device is rather than whose it is; the one
exception is the ISP, whose brand mark is replaced by the generic cloud on the
Internet node. Note `client-11`, with four clients hanging off it rather than off
a switch: those are VMs behind a NAS, which `stat/sta` cannot place and the
controller's own graph can.*

**Replaced:** hostnames and device names, IP addresses, MAC addresses (including
the node identifiers in the DOT and draw.io output, which are derived from them),
network and VLAN names, SSIDs, the ISP name and the WAN address.

**Kept**, because otherwise the result is useless for the purpose: how everything
is connected, device roles, models and artwork, port numbers, counts, and which
clients sit on which network. Addresses are renumbered but stay grouped, so the
VLAN structure is still visible.

Pseudonyms are stable. The same device is `client-07` in every render of the same
snapshot, so a follow-up screenshot lines up with the first. They are assigned by
a fixed ordering rather than derived from the real name, since a hash of a short
hostname is trivially reversible.

### Logs, and what `-v` reveals

`--obfuscate` covers the diagram *and* the ordinary log output, so a scrubbed
render is not accompanied by a terminal full of real names. There is a test that
renders an identifying fixture and checks the captured log for every value it
knows about.

`-v` is the exception, deliberately. Verbose mode exists to explain why an
individual device did not match, which means naming it. Do not paste `-v` output
from a real network into a public issue.

### What it does not hide

Two things worth understanding before you post a map publicly:

- **The artwork still shows what your devices are.** A TV, a thermostat, a NAS
  and a games console are all recognisable from their pictures, and some carry
  brand marks. If that matters, add `--icons builtin` for geometric shapes and no
  artwork at all.
- **`--title` is yours.** If you pass a title containing your name or your
  network's name, it will be rendered exactly as given. The default is a neutral
  "Network map".

This runs on the model before anything is drawn, so no renderer can leak a value
that has already been removed. A test renders SVG, DOT and draw.io and asserts
that not one original hostname, address, MAC, network name or SSID appears in any
of them, because a mode that cleans one format and leaves another readable would
be worse than none at all.

## Helping: `unifi-map shape`

Several things this tool cannot do are stuck on evidence rather than effort.
Multi-site handling has only ever seen one site. Nothing has been profiled at
scale. The four support-file limits come from a single archive. Every endpoint
shape is verified against exactly one controller version.

None of that is fixable by thinking harder, and the one thing you should never
be asked for is your data. So:

```bash
unifi-map shape                              # from a cached snapshot
unifi-map shape --support-file support.tgz    # or straight from an archive
unifi-map shape --yes                         # skip the prompt, once read
```

It prints a short plain-text description of the *shape* of your network: counts,
how many things hang off the busiest device, which field **names** your
controller returns, and version numbers. It is built from a list written in
advance rather than by stripping identifying values out, because a filter that
strips can be incomplete and a list that only ever adds cannot.

No addresses, MACs, hostnames, SSIDs, site names or network names appear in it,
and no value from any field, only whether that field exists. It is short enough
to read in full before you send it, and nothing is transmitted by the tool: the
report goes to your terminal and what happens next is your decision.

Pointed at an archive it also reports how much there is to walk and how many
sites it contains, counted and never named. Those are the numbers behind the
support-file limits and the untested multi-site handling.

The most useful part is the schema section, which says which fields your
controller returns and which it does not. That is the question we cannot answer
from here and cannot guess.
