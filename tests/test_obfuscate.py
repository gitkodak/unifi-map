"""Obfuscation.

The load-bearing test here is `test_nothing_leaks_into_any_output_format`. A mode
that cleans one format and leaves another readable is worse than no mode at all,
because it creates false confidence, so the check renders everything and looks
for every original value in all of it.
"""

from __future__ import annotations

import re
import shutil

import pytest

from unifi_map.client import Snapshot
from unifi_map.layout import run_dot
from unifi_map.model import UNKNOWN_UPLINK_ID, Kind, build_topology
from unifi_map.obfuscate import PLACEHOLDER_WAN_IP, obfuscate
from unifi_map.render_dot import Style, render_dot
from unifi_map.theme import LIGHT

from .conftest import AP_MAC, GATEWAY_MAC, SWITCH_MAC

needs_graphviz = pytest.mark.skipif(
    shutil.which("dot") is None, reason="graphviz `dot` not installed"
)

STYLE = Style(theme=LIGHT, icons="builtin", layout="tree")


def _without_embedded_images(text: str) -> str:
    """Drop base64 image payloads, keeping everything a reader could see."""
    return re.sub(r"data:image/[a-z+]+;?base64,[A-Za-z0-9+/=]+", "", text)


@pytest.fixture
def identifying(devices: dict, clients: dict, networkconf: dict) -> dict:
    """A snapshot plus the list of values that must never reach the output."""
    health = {
        "data": [
            {
                "subsystem": "wan",
                "isp_name": "Carls Discount Internet",
                "wan_ip": "198.51.100.42",
                # Names the provider as squarely as the name does, and is the
                # key to their brand mark.
                "asn": 64500,
            }
        ]
    }
    clients["data"].append(
        {
            "mac": "dd:ee:ff:00:00:55",
            "hostname": "secret-laptop",
            "is_wired": False,
            "ap_mac": AP_MAC,
            "essid": "MySecretSSID",
            "network_id": "net1",
        }
    )
    snapshot = Snapshot(
        payloads={
            "device": devices,
            "client_active": clients,
            "networkconf": networkconf,
            "health": health,
        }
    )
    secrets = [
        "Carls Discount Internet",
        "198.51.100.42",
        "64500",
        "secret-laptop",
        "MySecretSSID",
        "nas",
        "tuner",
        "phone",
        "10.0.20.10",
        "10.0.30.12",
        "10.0.0.51",
        GATEWAY_MAC,
        SWITCH_MAC,
        AP_MAC,
        "dd:ee:ff:00:00:55",
        # MACs also appear stripped of colons in Graphviz identifiers.
        GATEWAY_MAC.replace(":", ""),
        SWITCH_MAC.replace(":", ""),
        "ddeeff000055",
        "lan",
        "servers",
        "iot",
        "test-wifi",
        "test-iot",
    ]
    return {"snapshot": snapshot, "secrets": secrets}


@needs_graphviz
def test_nothing_leaks_into_any_output_format(identifying):
    from unifi_map.layout import compute_layout
    from unifi_map.render_drawio import render_drawio

    topo = obfuscate(build_topology(identifying["snapshot"]))
    dot_source = render_dot(topo, "Network map", STYLE, subtitle="a subtitle")

    outputs = {
        "dot": dot_source.encode(),
        "svg": run_dot(dot_source, "svg"),
        "drawio": render_drawio(topo, compute_layout(dot_source), "map", LIGHT).encode(),
    }

    failures = []
    for fmt, blob in outputs.items():
        # Strip embedded artwork first. Base64 is dense enough that a short
        # needle turns up in it by chance, which makes the check cry wolf: a
        # real render matched "Dell" inside an encoded PNG. What matters is
        # readable text, not the bytes of a picture.
        text = _without_embedded_images(blob.decode("utf-8", errors="replace")).lower()
        for secret in identifying["secrets"]:
            # Whole-word-ish: "lan" would otherwise match "vlan" or "planned".
            needle = secret.lower()
            if len(needle) <= 4:
                found = any(
                    text[max(0, i - 1) : i + len(needle) + 1].strip("abcdefghijklmnopqrstuvwxyz")
                    == needle
                    for i in range(len(text))
                    if text.startswith(needle, i)
                )
            else:
                found = needle in text
            if found:
                failures.append(f"{fmt}: {secret!r}")
    assert not failures, "identifying values reached the output: " + ", ".join(failures)


class TestStructureSurvives:
    def test_counts_and_shape_are_unchanged(self, snapshot: Snapshot):
        before = build_topology(snapshot)
        after = obfuscate(before)
        assert len(after.nodes) == len(before.nodes)
        assert len(after.edges) == len(before.edges)
        assert after.counts() == before.counts()

    def test_every_edge_still_points_at_real_nodes(self, snapshot: Snapshot):
        after = obfuscate(build_topology(snapshot))
        for edge in after.edges:
            assert edge.src in after.nodes
            assert edge.dst in after.nodes

    def test_parent_child_relationships_are_preserved(self, snapshot: Snapshot):
        before = build_topology(snapshot)
        after = obfuscate(before)
        # The switch hangs off the gateway in both, whatever they are called.
        gateway = next(n.id for n in after.nodes.values() if n.kind is Kind.GATEWAY)
        switch_parents = {e.dst for e in after.edges if after.nodes[e.src].kind is Kind.SWITCH}
        assert gateway in switch_parents

    def test_port_labels_survive(self, snapshot: Snapshot):
        after = obfuscate(build_topology(snapshot))
        assert any(e.label and "port" in e.label for e in after.edges)

    def test_clients_keep_their_network_grouping(self, snapshot: Snapshot):
        before = build_topology(snapshot)
        after = obfuscate(before)

        # Two clients shared a network before, so two must share one after.
        def grouping(topo):
            counts: dict[str, int] = {}
            for n in topo.nodes.values():
                if n.network:
                    counts[n.network] = counts.get(n.network, 0) + 1
            return sorted(counts.values())

        assert grouping(after) == grouping(before)

    def test_artwork_keys_are_kept(self, snapshot: Snapshot):
        before = build_topology(snapshot)
        after = obfuscate(before)
        assert sorted(n.sysid for n in before.nodes.values() if n.sysid) == sorted(
            n.sysid for n in after.nodes.values() if n.sysid
        )

    def test_the_uplink_placeholder_keeps_its_explanatory_label(
        self, devices: dict, clients: dict, networkconf: dict
    ):
        clients["data"].append(
            {"mac": "dd:ee:ff:00:00:99", "hostname": "vm", "is_wired": True, "network_id": "net1"}
        )
        topo = obfuscate(
            build_topology(
                Snapshot(
                    payloads={
                        "device": devices,
                        "client_active": clients,
                        "networkconf": networkconf,
                    }
                )
            )
        )
        # Renaming this to "device-01" would destroy the only thing it explains.
        assert "not reported" in topo.nodes[UNKNOWN_UPLINK_ID].label


class TestStability:
    def test_the_same_topology_maps_the_same_way_twice(self, snapshot: Snapshot):
        topo = build_topology(snapshot)
        first = obfuscate(topo)
        second = obfuscate(topo)
        assert sorted(first.nodes) == sorted(second.nodes)
        assert {n.id: n.label for n in first.nodes.values()} == {
            n.id: n.label for n in second.nodes.values()
        }

    def test_labels_are_not_derived_from_the_real_name(
        self, devices: dict, clients: dict, networkconf: dict
    ):
        # A hash of a short hostname is trivially reversible, so the pseudonym
        # must not vary with the name it replaces.
        def build(name):
            payload = {"data": list(clients["data"])}
            payload["data"].append(
                {
                    "mac": "dd:ee:ff:00:00:aa",
                    "hostname": name,
                    "is_wired": True,
                    "sw_mac": SWITCH_MAC,
                    "sw_port": 3,
                    "network_id": "net1",
                }
            )
            return obfuscate(
                build_topology(
                    Snapshot(
                        payloads={
                            "device": devices,
                            "client_active": payload,
                            "networkconf": networkconf,
                        }
                    )
                )
            )

        a = build("alice-laptop")
        b = build("bob-desktop")
        assert sorted(a.nodes) == sorted(b.nodes)


class TestScrubbing:
    def test_addresses_are_renumbered_but_still_grouped(self, snapshot: Snapshot):
        after = obfuscate(build_topology(snapshot))
        by_net: dict[str, set[str]] = {}
        for n in after.nodes.values():
            if n.network and n.ip:
                by_net.setdefault(n.network, set()).add(n.ip.rsplit(".", 1)[0])
        # Each network occupies one prefix, so the VLAN structure stays visible.
        for network, prefixes in by_net.items():
            assert len(prefixes) == 1, f"{network} spread across {prefixes}"

    def test_the_asn_is_dropped_so_no_isp_brand_mark_can_be_drawn(
        self, devices: dict, networkconf: dict
    ):
        health = {
            "data": [
                {"subsystem": "wan", "isp_name": "Some ISP", "wan_ip": "9.9.9.9", "asn": 64500}
            ]
        }
        topo = obfuscate(
            build_topology(
                Snapshot(payloads={"device": devices, "networkconf": networkconf, "health": health})
            )
        )
        # Artwork keys are normally kept, because they say what hardware is
        # rather than whose it is. This one is the exception: it would redraw
        # the provider's logo onto a map meant for publishing.
        assert topo.nodes["internet"].asn is None

    def test_the_wan_address_becomes_a_documentation_address(
        self, devices: dict, networkconf: dict
    ):
        health = {"data": [{"subsystem": "wan", "isp_name": "Some ISP", "wan_ip": "9.9.9.9"}]}
        topo = obfuscate(
            build_topology(
                Snapshot(payloads={"device": devices, "networkconf": networkconf, "health": health})
            )
        )
        internet = topo.nodes["internet"]
        assert internet.ip == PLACEHOLDER_WAN_IP
        assert internet.label == "Internet"
        assert "Some ISP" not in (internet.label or "")

    def test_an_ssid_is_dropped_when_there_is_no_fingerprint(
        self, devices: dict, clients: dict, networkconf: dict
    ):
        clients["data"].append(
            {
                "mac": "dd:ee:ff:00:00:bb",
                "is_wired": False,
                "ap_mac": AP_MAC,
                "essid": "PrivateSSID",
                "network_id": "net1",
            }
        )
        topo = obfuscate(
            build_topology(
                Snapshot(
                    payloads={
                        "device": devices,
                        "client_active": clients,
                        "networkconf": networkconf,
                    }
                )
            )
        )
        assert all((n.detail or "") != "PrivateSSID" for n in topo.nodes.values())

    def test_a_fingerprint_product_name_is_kept(
        self, devices: dict, clients: dict, networkconf: dict
    ):
        fingerprint = {
            "dev_ids": {"4425": {"name": "Nest Audio", "dev_type_id": "2"}},
            "dev_type_ids": {"2": "Soundbar"},
        }
        clients["data"].append(
            {
                "mac": "dd:ee:ff:00:00:cc",
                "is_wired": False,
                "ap_mac": AP_MAC,
                "network_id": "net1",
                "dev_id": 4425,
            }
        )
        topo = obfuscate(
            build_topology(
                Snapshot(
                    payloads={
                        "device": devices,
                        "client_active": clients,
                        "networkconf": networkconf,
                        "fingerprint": fingerprint,
                    }
                )
            )
        )
        # The artwork shows a soundbar regardless, so hiding the word is theatre.
        assert any(n.detail == "Soundbar" for n in topo.nodes.values())

    def test_network_names_are_replaced_but_vlan_ids_kept(self, snapshot: Snapshot):
        before = build_topology(snapshot)
        after = obfuscate(before)
        names = {n.network for n in after.nodes.values() if n.network}
        assert names
        assert all(n.startswith("network-") for n in names)
        assert {n.vlan for n in after.nodes.values() if n.vlan} == {
            n.vlan for n in before.nodes.values() if n.vlan
        }


@needs_graphviz
def test_nothing_identifying_reaches_the_log_either(identifying, tmp_path, caplog):
    """A scrubbed diagram beside a terminal full of real names is no use.

    The render is what `--obfuscate` promises, but the log is what ends up in a
    CI job, a scrollback buffer or a pasted transcript. Checked at the default
    level, which is what an ordinary run produces; `-v` turns on DEBUG detail
    that is deliberately not covered and is documented as such.
    """
    import logging

    from unifi_map.cli import main

    cache = tmp_path / "cache"
    Snapshot(payloads=identifying["snapshot"].payloads).write(cache)

    with caplog.at_level(logging.INFO):
        code = main(
            [
                "--cache-dir",
                str(cache),
                "--out-dir",
                str(tmp_path / "out"),
                "--asset-cache",
                str(tmp_path / "assets"),
                "render",
                "--obfuscate",
                "--icons",
                "builtin",
                "--offline",
                "-f",
                "svg",
                "--name",
                "t",
            ]
        )
    assert code == 0

    text = caplog.text.lower()
    leaked = [s for s in identifying["secrets"] if len(s) > 5 and s.lower() in text]
    assert not leaked, f"identifying values reached the log: {leaked}"


@needs_graphviz
def test_an_override_warning_does_not_leak_under_obfuscate(identifying, tmp_path, caplog):
    """The same promise, on the one path that renders *with* an overrides file.

    The test above renders without overrides, so it never reached the code that
    reports a displaced link, and that code named the node and its old parent
    unconditionally. An ordinary obfuscated run therefore scrubbed the diagram
    and printed real labels into the terminal beside it.

    Kept separate rather than folded in: this needs a valid overrides file
    against this fixture, and the point of the other test is that a plain run
    leaks nothing.
    """
    import logging

    from unifi_map.cli import main

    cache = tmp_path / "cache"
    Snapshot(payloads=identifying["snapshot"].payloads).write(cache)

    # Reparents a client the controller reported under a switch, which is what
    # produces the warning.
    overrides = tmp_path / "overrides.toml"
    overrides.write_text(
        '[[hosted]]\nguest = "secret-laptop"\nhost = "Core Switch"\n', encoding="utf-8"
    )

    with caplog.at_level(logging.INFO):
        code = main(
            [
                "--cache-dir",
                str(cache),
                "--out-dir",
                str(tmp_path / "out"),
                "--asset-cache",
                str(tmp_path / "assets"),
                "render",
                "--obfuscate",
                "--icons",
                "builtin",
                "--offline",
                "-f",
                "svg",
                "--name",
                "t",
                "--overrides",
                str(overrides),
            ]
        )
    assert code == 0

    # The warning must still happen; it is the names that must not.
    assert "replaced by overrides" in caplog.text
    text = caplog.text.lower()
    leaked = [s for s in identifying["secrets"] if len(s) > 5 and s.lower() in text]
    assert not leaked, f"identifying values reached the log: {leaked}"


def test_obfuscation_keeps_every_model_field_it_does_not_deliberately_change():
    """Rebuilt objects lose fields silently; `replace()`d ones do not.

    `Edge` and `Network` are constructed field by field in `obfuscate()`, so
    anything added to those dataclasses is dropped unless somebody remembers.
    Something was: `asserted` was lost, which redrew every override-asserted
    link as though a controller had reported it, in the one mode where the
    reader has no way to check. Nodes were fine, because they go through
    `replace()`.

    Written against the dataclass rather than against a list of fields, so a
    new field fails here until it is either carried or deliberately exempted.
    """
    import dataclasses

    from unifi_map.model import Edge, Kind, Network, Node, Topology
    from unifi_map.obfuscate import obfuscate

    # Fields obfuscation is *supposed* to change, with why.
    exempt = {
        "Edge": {"src", "dst"},  # ids are remapped, that is the point
        "Network": {"id", "name", "subnet"},  # renamed and renumbered
    }

    topo = Topology(
        nodes={
            "a": Node(id="a", label="A", kind=Kind.SWITCH, asserted=True),
            "b": Node(id="b", label="B", kind=Kind.SWITCH),
        },
        edges=[Edge(src="a", dst="b", label="port 1", wireless=True, asserted=True)],
        networks={"n1": Network(id="n1", name="lan", vlan=7, subnet="10.0.0.0/24", is_guest=True)},
    )
    after = obfuscate(topo)

    for name, before_obj, after_obj in (
        ("Edge", topo.edges[0], after.edges[0]),
        ("Network", topo.networks["n1"], next(iter(after.networks.values()))),
    ):
        for field in dataclasses.fields(before_obj):
            if field.name in exempt[name]:
                continue
            assert getattr(after_obj, field.name) == getattr(before_obj, field.name), (
                f"obfuscate() dropped {name}.{field.name}; carry it or exempt it here"
            )
