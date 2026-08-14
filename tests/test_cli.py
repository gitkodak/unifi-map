from __future__ import annotations

import argparse

from unifi_map.cli import _write_per_network_views
from unifi_map.model import build_topology
from unifi_map.render_dot import Style
from unifi_map.theme import LIGHT

TREE = Style(theme=LIGHT, icons="builtin", layout="tree")


class TestWritePerNetworkViews:
    """Extracted from cmd_render (KAN-114 maintainability pass); no behavior
    change intended, so this pins the same output `--per-network` produced
    when the loop lived inline.
    """

    def test_one_file_per_client_network(self, snapshot, tmp_path):
        topo = build_topology(snapshot)
        args = argparse.Namespace(out_dir=tmp_path, stagger=0, force=True, progress=False)

        _write_per_network_views(topo, "t", TREE, {}, ["dot"], "m", args)

        # conftest.py's networkconf fixture defines lan, servers and iot.
        assert (tmp_path / "m-lan.dot").is_file()
        assert (tmp_path / "m-servers.dot").is_file()
        assert (tmp_path / "m-iot.dot").is_file()

    def test_each_view_is_named_after_its_network_in_the_title(self, snapshot, tmp_path):
        topo = build_topology(snapshot)
        args = argparse.Namespace(out_dir=tmp_path, stagger=0, force=True, progress=False)

        _write_per_network_views(topo, "Network map", TREE, {}, ["dot"], "m", args)

        dot_source = (tmp_path / "m-lan.dot").read_text(encoding="utf-8")
        assert "Network map: lan" in dot_source

    def test_no_client_networks_warns_rather_than_erroring(self, snapshot, tmp_path, caplog):
        # Every client filtered out by include_clients=False, so
        # client_networks(topo) is empty and there is nothing to loop over.
        topo = build_topology(snapshot, include_clients=False)
        args = argparse.Namespace(out_dir=tmp_path, stagger=0, force=True, progress=False)

        _write_per_network_views(topo, "t", TREE, {}, ["dot"], "m", args)

        assert "skipping per-network views" in caplog.text
        assert list(tmp_path.iterdir()) == []
