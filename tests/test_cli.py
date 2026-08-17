from __future__ import annotations

import argparse
import logging

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


class TestQuiet:
    """-q/--quiet: ERROR-only logging, mutually exclusive with -v/--verbose."""

    def test_quiet_maps_to_error_level(self):
        from unifi_map.cli import _log_level

        assert _log_level(["-q"]) == logging.ERROR
        assert _log_level(["--quiet"]) == logging.ERROR

    def test_verbose_maps_to_debug_level(self):
        from unifi_map.cli import _log_level

        assert _log_level(["-v"]) == logging.DEBUG

    def test_neither_flag_maps_to_info_level(self):
        from unifi_map.cli import _log_level

        assert _log_level([]) == logging.INFO
        assert _log_level(["render", "--out-dir", "x"]) == logging.INFO

    def test_both_flags_together_is_refused(self):
        from unifi_map.cli import _log_level

        assert _log_level(["-v", "-q"]) is None
        assert _log_level(["--verbose", "--quiet"]) is None

    def test_main_refuses_both_flags_with_a_clean_error_not_a_traceback(self, capsys):
        from unifi_map.cli import main

        code = main(["-v", "-q", "render"])
        assert code == 2
        err = capsys.readouterr().err
        assert "-q/--quiet" in err
        assert "-v/--verbose" in err

    def test_quiet_implies_no_progress(self):
        from unifi_map.cli import _apply_quiet, build_parser

        args = build_parser().parse_args(["--cache-dir", "examples/demo", "--quiet", "render"])
        assert args.progress is True  # not yet applied
        _apply_quiet(args)
        assert args.progress is False

    def test_without_quiet_progress_is_untouched(self):
        from unifi_map.cli import _apply_quiet, build_parser

        args = build_parser().parse_args(["--cache-dir", "examples/demo", "render"])
        _apply_quiet(args)
        assert args.progress is True

    def test_explicit_no_progress_survives_without_quiet(self):
        from unifi_map.cli import _apply_quiet, build_parser

        args = build_parser().parse_args(
            ["--cache-dir", "examples/demo", "--no-progress", "render"]
        )
        _apply_quiet(args)
        assert args.progress is False
