# Sharing a map, and helping upstream

[← Documentation index](../README.md#documentation)

This page covers two things you might want to send somebody: a diagram
of your network with the identifying parts removed, and a description
of its shape that carries none of them in the first place.

## Sharing a map: `--obfuscate`

A rendered map is not anonymous. Labels carry hostnames, addresses, VLAN names
and your WAN address, and an SVG holds all of it as selectable text. That makes
it awkward to ask for help with a layout problem.

```bash
unifi-map render --obfuscate --theme dark
```

![The same real network, obfuscated](images/example-obfuscated-dark.png)

*A real network, obfuscated. Every device is a pseudonym, and the tool
renumbers addresses, but the connections, roles, and port numbers stay
untouched. Product artwork stays too, because it says what a device is,
not whose it is. The one exception is the ISP: the generic cloud
replaces its brand mark on the Internet node. Note `client-11`, with
four clients attached to it, rather than to a switch. Those are VMs
behind a NAS, which `stat/sta` cannot place, but the controller's own
graph can.*

**Replaced:** hostnames and device names, IP addresses, MAC addresses
(including the node identifiers in the DOT and draw.io output, which
come from them), network and VLAN names, SSIDs, the ISP name and the WAN
address.

**Kept**, because otherwise the result is useless for the purpose: how
everything connects, device roles, models and artwork, port numbers,
counts, and which clients sit on which network. Addresses get new
numbers but stay grouped, so the VLAN structure is still visible.

Pseudonyms are stable. The same device is `client-07` in every render of
the same snapshot, so a follow-up screenshot lines up with the first. A
fixed ordering assigns them, rather than a hash of the real name, since
a hash of a short hostname is trivially reversible.

### Logs, and what `-v` reveals

`--obfuscate` covers the diagram *and* the ordinary log output, so a
scrubbed render does not come with a terminal full of real names. A test
renders an identifying fixture and checks the captured log for every
value it knows about.

`-v` is the exception, deliberately. Verbose mode exists to explain why
an individual device did not match, and that means it names the device.
Do not paste `-v` output from a real network into a public issue.

### What it does not hide

Understand two things before you post a map publicly:

- **The artwork still shows what your devices are.** A TV, a thermostat,
  a NAS, and a games console are all recognisable from their pictures,
  and some carry brand marks. If that matters, add `--icons builtin`,
  which draws only our own generic role icons. A device still reads as a
  switch or a phone, but nothing says whose or which model.
- **`--title` is yours.** If you pass a title that contains your name or
  your network's name, the tool renders it exactly as given. The default
  is a neutral "Network map".

This runs on the model before the tool draws anything, so no renderer
can leak a value the model already removed. A test renders SVG, DOT, and
draw.io, and asserts that not one original hostname, address, MAC,
network name, or SSID appears in any of them. A mode that cleans one
format and leaves another readable would be worse than none at all.

## Helping: `unifi-map shape`

Several things this tool cannot do are stuck on evidence, not effort.
Multi-site handling only ever saw one site. This project never profiled
anything at scale. The four support-file limits come from a single
archive. This project verified every endpoint shape against exactly one
controller version.

None of that improves with more thinking. And the one thing you should
never have to give is your data. So:

```bash
unifi-map shape                              # from a cached snapshot
unifi-map shape --support-file support.tgz    # or straight from an archive
unifi-map shape --yes                         # skip the prompt, once read
```

It prints a short plain-text description of the *shape* of your
network: counts, how many things attach to the busiest device, which
field **names** your controller returns, and version numbers. This
project builds it from a list written in advance, rather than by
removing identifying values. A filter that removes values can be
incomplete. A list that only ever adds cannot.

No addresses, MACs, hostnames, SSIDs, site names, or network names
appear in it, and no value from any field, only whether that field
exists. It is short enough to read in full before you send it. The tool
transmits nothing: the report goes to your terminal, and what happens
next is your decision.

If you point it at an archive, it also reports how much there is to
walk, and how many sites it contains, counted and never named. Those
are the numbers behind the support-file limits and the untested
multi-site handling.

The most useful part is the schema section, which says which fields your
controller returns and which it does not. That is the question we cannot answer
from here and cannot guess.
