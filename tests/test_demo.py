"""The shipped demo dataset.

Guards the thing a new user hits first: `make demo` must work offline, with no
credentials and no controller.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from unifi_map.client import Snapshot
from unifi_map.model import UNKNOWN_UPLINK_ID, Kind, build_topology, client_networks
from unifi_map.render_dot import Style, render_dot
from unifi_map.theme import LIGHT

DEMO = Path(__file__).resolve().parent.parent / "examples" / "demo"

needs_graphviz = pytest.mark.skipif(
    shutil.which("dot") is None, reason="graphviz `dot` not installed"
)


@pytest.fixture
def demo_topology():
    return build_topology(Snapshot.read(DEMO))


def test_demo_snapshot_is_present_and_loadable():
    snapshot = Snapshot.read(DEMO)
    assert snapshot.get("device")
    assert snapshot.get("client_active")
    assert snapshot.get("networkconf")


def test_demo_contains_no_real_addresses_or_macs():
    # Everything must be invented: locally-administered MACs, RFC 1918 space.
    for record in Snapshot.read(DEMO).get("device")["data"]:
        assert record["mac"].startswith("02:"), record["mac"]
        if record.get("ip"):
            assert record["ip"].startswith("10."), record["ip"]
    for record in Snapshot.read(DEMO).get("client_active")["data"]:
        assert record["mac"].startswith("02:"), record["mac"]
        assert record["ip"].startswith("10."), record["ip"]


def test_demo_covers_the_features_worth_demonstrating(demo_topology):
    kinds = {n.kind for n in demo_topology.nodes.values()}
    assert Kind.GATEWAY in kinds
    assert Kind.SWITCH in kinds
    assert Kind.AP in kinds
    assert Kind.WIRED_CLIENT in kinds
    assert Kind.WIRELESS_CLIENT in kinds

    # An offline device, so its treatment is visible.
    assert any(n.offline for n in demo_topology.nodes.values())
    # A client the controller cannot place, which is what overrides will fix.
    assert UNKNOWN_UPLINK_ID in demo_topology.nodes
    # Several VLANs, so per-network views and border colours mean something.
    assert len(client_networks(demo_topology)) >= 3


def test_demo_devices_carry_real_sysids_so_artwork_can_resolve(demo_topology):
    # Fake sysids would leave the demo unable to show any icons.
    infra = [n for n in demo_topology.infrastructure if n.kind is not Kind.INTERNET]
    infra = [n for n in infra if n.id != UNKNOWN_UPLINK_ID]
    assert infra
    for node in infra:
        assert node.sysid is not None, node.label
        assert 0x1000 <= node.sysid <= 0xFFFF, (node.label, node.sysid)


@needs_graphviz
def test_demo_renders_without_network_access(demo_topology):
    # icons="builtin" must need nothing external at all.
    style = Style(theme=LIGHT, icons="builtin", layout="tree")
    dot_source = render_dot(demo_topology, "Demo network", style)
    assert "digraph unifi {" in dot_source
    assert "Core Switch" in dot_source


class TestShippedOverridesExample:
    """`examples/demo/overrides.toml` has to keep working against the demo data.

    An example that no longer applies is worse than no example: it is the first
    thing someone copies, and a selector that silently stops matching would
    teach them the wrong shape. The loader raises on an unmatched selector, so
    simply applying the file is most of the test.
    """

    @pytest.fixture
    def applied(self):
        from unifi_map.client import Snapshot
        from unifi_map.model import build_topology
        from unifi_map.overrides import apply, load

        path = Path(__file__).resolve().parents[1] / "examples" / "demo" / "overrides.toml"
        topo = build_topology(Snapshot.read(path.parent))
        return apply(topo, load(path))

    def test_every_block_still_does_something(self, applied):
        # If any of these drops to zero the example has stopped demonstrating
        # the feature it claims to.
        assert applied.devices_added == 1
        assert applied.links_added == 1
        assert applied.hosted_applied == 1
        assert applied.renamed == 1
        assert applied.hidden

    def test_the_declared_device_is_marked_as_a_claim(self, applied):
        declared = [n for n in applied.topology.nodes.values() if n.asserted]
        assert len(declared) == 1
        assert declared[0].label == "Bench switch"

    def test_it_rescues_the_client_the_controller_could_not_place(self, applied):
        # The demo ships one deliberately unplaceable client. The example's
        # [[link]] block exists to show that being fixed, so if the placeholder
        # survives, the example is no longer demonstrating anything.
        assert UNKNOWN_UPLINK_ID not in {e.dst for e in applied.topology.edges}
