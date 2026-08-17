from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

from unifi_map.client import Snapshot
from unifi_map.config import ConfigError, ExporterConfig, load_config
from unifi_map.layout import compute_layout, parse_plain, run_dot
from unifi_map.model import build_topology
from unifi_map.render_dot import Style, render_dot
from unifi_map.theme import LIGHT, get_theme

needs_graphviz = pytest.mark.skipif(
    shutil.which("dot") is None, reason="graphviz `dot` not installed"
)

TREE = Style(theme=LIGHT, icons="builtin", layout="tree")
UNIFI = Style(theme=LIGHT, icons="builtin", layout="unifi")


def test_dot_output_is_syntactically_parseable_by_graphviz(snapshot: Snapshot):
    dot_source = render_dot(build_topology(snapshot), "test map", TREE)
    assert dot_source.startswith("digraph unifi {")
    assert dot_source.rstrip().endswith("}")


def test_style_rejects_unknown_options():
    with pytest.raises(ValueError, match="icons must be one of"):
        Style(theme=LIGHT, icons="nope")
    with pytest.raises(ValueError, match="layout must be one of"):
        Style(theme=LIGHT, layout="nope")


def test_get_theme_rejects_unknown_name():
    with pytest.raises(ValueError, match="Unknown theme"):
        get_theme("chartreuse")


def test_dot_escapes_quotes_in_labels(networkconf: dict, devices: dict):
    devices["data"][0]["name"] = 'Weird "quoted" name'
    topo = build_topology(Snapshot(payloads={"device": devices, "networkconf": networkconf}))
    dot_source = render_dot(topo, "t", TREE)
    # The quote must be escaped, not terminate the DOT string early.
    assert r"Weird \"quoted\" name" in dot_source


def test_wireless_edges_are_dashed_for_greyscale_readability(snapshot: Snapshot):
    dot_source = render_dot(build_topology(snapshot), "t", TREE)
    assert [line for line in dot_source.splitlines() if "style=dashed" in line]


def _topo_with_topology_graph_edge(also_wireless: bool = False):
    from unifi_map.model import Edge, Kind, Node, Provenance, Topology

    topo = Topology()
    topo.add(Node(id="gw", label="gateway", kind=Kind.GATEWAY, provenance=Provenance.DEVICE))
    topo.add(Node(id="c1", label="direct", kind=Kind.WIRED_CLIENT, provenance=Provenance.CLIENT))
    topo.add(Node(id="c2", label="inferred", kind=Kind.WIRED_CLIENT, provenance=Provenance.CLIENT))
    topo.edges.append(Edge(src="c1", dst="gw", provenance=Provenance.CLIENT_UPLINK))
    topo.edges.append(
        Edge(
            src="c2",
            dst="c1",
            provenance=Provenance.TOPOLOGY_GRAPH,
            wireless=also_wireless,
        )
    )
    return topo


def test_topology_graph_edges_get_a_hollow_circle_arrowhead():
    """A client placed via the v2 graph, not its own uplink report, is real but
    a step removed from what the device itself said — see CLAUDE.md's KAN-137
    notes. Nothing distinguished it from a directly reported edge before this.
    """
    dot_source = render_dot(_topo_with_topology_graph_edge(), "t", TREE)
    lines = dot_source.splitlines()
    # Edges render dst -> src (parent -> child), the reverse of how they're
    # stored, so the topology-graph edge c2->c1 (dst=c1, src=c2) prints as
    # n_c1 -> n_c2.
    inferred = [line for line in lines if '"n_c1" -> "n_c2"' in line]
    direct = [line for line in lines if '"n_gw" -> "n_c1"' in line]
    assert inferred
    assert "arrowhead=odot" in inferred[0]
    assert direct
    assert "arrowhead=odot" not in direct[0]


def test_topology_graph_marker_composes_with_wireless_dashing():
    dot_source = render_dot(_topo_with_topology_graph_edge(also_wireless=True), "t", TREE)
    inferred = next(line for line in dot_source.splitlines() if '"n_c1" -> "n_c2"' in line)
    assert "arrowhead=odot" in inferred
    assert "style=dashed" in inferred


def _topo_with_shared_port(shared: bool = True):
    from unifi_map.model import Edge, Kind, Node, Provenance, Topology

    topo = Topology()
    topo.add(Node(id="sw", label="switch", kind=Kind.SWITCH, provenance=Provenance.DEVICE))
    topo.add(Node(id="c1", label="c1", kind=Kind.WIRED_CLIENT, provenance=Provenance.CLIENT))
    topo.edges.append(Edge(src="c1", dst="sw", label="port 7", provenance=Provenance.CLIENT_UPLINK))
    if shared:
        topo.add(Node(id="c2", label="c2", kind=Kind.WIRED_CLIENT, provenance=Provenance.CLIENT))
        topo.edges.append(
            Edge(src="c2", dst="sw", label="port 7", provenance=Provenance.CLIENT_UPLINK)
        )
    return topo


def test_a_shared_port_gets_an_asterisk_on_both_edges():
    """KAN-199: several clients on one port is flagged, never drawn as a node."""
    dot_source = render_dot(_topo_with_shared_port(), "t", TREE)
    lines = [line for line in dot_source.splitlines() if '"n_sw" -> "n_c' in line]
    assert len(lines) == 2
    assert all('label="port 7 *"' in line for line in lines)


def test_an_unshared_port_gets_no_asterisk():
    dot_source = render_dot(_topo_with_shared_port(shared=False), "t", TREE)
    line = next(line for line in dot_source.splitlines() if '"n_sw" -> "n_c1"' in line)
    assert 'label="port 7"' in line
    assert "*" not in line


def test_mac_colons_are_stripped_from_dot_identifiers(snapshot: Snapshot):
    dot_source = render_dot(build_topology(snapshot), "t", TREE)
    # A raw colon in an identifier would parse as a DOT port specifier.
    assert '"n_aabbcc000001"' in dot_source


class TestLayouts:
    def test_tree_is_top_down_with_port_labels(self, snapshot: Snapshot):
        dot_source = render_dot(build_topology(snapshot), "t", TREE)
        assert "rankdir=TB;" in dot_source
        assert "port 12" in dot_source

    def test_unifi_is_left_right_without_port_labels(self, snapshot: Snapshot):
        dot_source = render_dot(build_topology(snapshot), "t", UNIFI)
        assert "rankdir=LR;" in dot_source
        # The UniFi UI does not label links, and ortho routing misplaces labels.
        assert "port 12" not in dot_source

    def test_unifi_omits_title_and_legend_to_avoid_dead_space(self, snapshot: Snapshot):
        # A graph label sets a minimum canvas width, padding a narrow map.
        dot_source = render_dot(build_topology(snapshot), "My Map", UNIFI, subtitle="sub")
        assert "labelloc=t;" not in dot_source
        assert "cluster_legend" not in dot_source

    def test_tree_includes_title_and_legend(self, snapshot: Snapshot):
        dot_source = render_dot(build_topology(snapshot), "My Map", TREE, subtitle="sub")
        assert "labelloc=t;" in dot_source
        assert "My Map" in dot_source
        assert "cluster_legend" in dot_source

    def test_explicit_flags_override_layout_defaults(self, snapshot: Snapshot):
        style = Style(theme=LIGHT, icons="builtin", layout="unifi", legend=True, title_block=True)
        dot_source = render_dot(build_topology(snapshot), "T", style, subtitle="s")
        assert "cluster_legend" in dot_source
        assert "labelloc=t;" in dot_source

    def test_unifi_layout_trims_canvas_padding(self, snapshot: Snapshot):
        # Whether `unifi` ends up narrower than `tree` depends on the shape of
        # the network (it does on a real one with many sibling clients, but not
        # on a small fixture where tree depth dominates), so assert the thing
        # that is actually guaranteed: no framing whitespace.
        topo = build_topology(snapshot)
        assert "pad=0.08;" in render_dot(topo, "t", UNIFI)
        assert "pad=0.4;" in render_dot(topo, "t", TREE)

    @needs_graphviz
    def test_both_layouts_place_every_node(self, snapshot: Snapshot):
        # Through `compute_layout` rather than run_dot plus parse_plain by hand,
        # so the wrapper callers actually use is on this path too.
        topo = build_topology(snapshot)
        for style in (TREE, UNIFI):
            layout = compute_layout(render_dot(topo, "t", style))
            for node_id in topo.nodes:
                assert "n_" + node_id.replace(":", "") in layout.nodes


@needs_graphviz
def test_graphviz_renders_svg(snapshot: Snapshot):
    svg = run_dot(render_dot(build_topology(snapshot), "test map", TREE), "svg").decode()
    assert "<svg" in svg
    assert "Core Switch" in svg


@needs_graphviz
def test_svg_scales_without_a_fixed_pixel_ceiling(snapshot: Snapshot):
    svg = run_dot(render_dot(build_topology(snapshot), "t", TREE), "svg").decode()
    # viewBox is what lets the SVG zoom to any size with crisp labels.
    assert "viewBox" in svg


def test_parse_plain_flips_y_axis_into_screen_space():
    plain = 'graph 1.0 10.0 8.0\nnode n_a 1.0 7.0 2.0 1.0 "A" solid box black white\nstop\n'
    placed = parse_plain(plain).nodes["n_a"]
    # Graphviz y=7 of an 8-inch-tall graph is near the top, so screen y is small.
    assert placed.y == pytest.approx((8.0 - 7.0) * 72 - (1.0 * 72) / 2)
    assert placed.x == pytest.approx(1.0 * 72 - (2.0 * 72) / 2)
    # 2.0 inches wide at 72 points per inch.
    assert placed.width == pytest.approx(144.0)
    assert placed.height == pytest.approx(72.0)


def test_parse_plain_handles_quoted_labels_with_spaces():
    plain = 'graph 1.0 10.0 8.0\nnode n_a 1.0 7.0 2.0 1.0 "A B C" solid box black white\nstop\n'
    assert "n_a" in parse_plain(plain).nodes


class TestCredentials:
    """API key only. Username and password support was removed deliberately."""

    KEYS = (
        "UNIFI_HOST",
        "UNIFI_API_KEY",
        "UDM_HOST",
        "UDM_API_KEY",
        "UNIFI_SITE",
        "UDM_SITE",
        "UNIFI_VERIFY_TLS",
        "UDM_VERIFY_TLS",
        "UNIFI_USERNAME",
        "UNIFI_PASSWORD",
        "UDM_USER",
        "UDM_PASS",
    )

    def _clear(self, monkeypatch):
        for key in self.KEYS:
            monkeypatch.delenv(key, raising=False)

    def _env(self, tmp_path, text):
        path = tmp_path / "creds.env"
        path.write_text(text)
        return path

    def test_host_and_key_are_enough(self, monkeypatch, tmp_path):
        self._clear(monkeypatch)
        config = load_config(self._env(tmp_path, "UNIFI_HOST=h\nUNIFI_API_KEY=secret\n"))
        assert config.host == "h"
        assert config.api_key == "secret"
        assert config.site == "default"
        assert config.verify_tls is True

    def test_udm_names_are_no_longer_read(self, monkeypatch, tmp_path):
        """Removed in 0.9.0, after warning since 0.7.0.

        The failure has to be the ordinary missing-configuration error naming
        the variable to set, not something that mentions the old name, because
        by this point the old name is not part of the interface.
        """
        self._clear(monkeypatch)
        env = self._env(tmp_path, "UDM_HOST=h\nUDM_API_KEY=secret\nUDM_SITE=s\n")
        with pytest.raises(ConfigError) as excinfo:
            load_config(env)
        assert "UNIFI_HOST" in str(excinfo.value)
        assert "UNIFI_API_KEY" in str(excinfo.value)

    def test_an_empty_assignment_reads_as_unset(self, monkeypatch, tmp_path):
        """`UNIFI_SITE=` is somebody commenting a line out halfway."""
        self._clear(monkeypatch)
        config = load_config(self._env(tmp_path, "UNIFI_HOST=h\nUNIFI_API_KEY=k\nUNIFI_SITE=\n"))
        assert config.site == "default"

    def test_real_environment_beats_the_file(self, monkeypatch, tmp_path):
        self._clear(monkeypatch)
        monkeypatch.setenv("UNIFI_HOST", "from-env")
        config = load_config(self._env(tmp_path, "UNIFI_HOST=from-file\nUNIFI_API_KEY=k\n"))
        assert config.host == "from-env"

    def test_a_username_and_password_are_not_credentials_any_more(self, monkeypatch, tmp_path):
        self._clear(monkeypatch)
        env = self._env(tmp_path, "UNIFI_HOST=h\nUNIFI_USERNAME=u\nUNIFI_PASSWORD=p\n")
        with pytest.raises(ConfigError, match="API key"):
            load_config(env)

    def test_missing_key_names_what_is_missing(self, monkeypatch, tmp_path):
        self._clear(monkeypatch)
        env = self._env(tmp_path, "UNIFI_HOST=h\n")
        with pytest.raises(ConfigError, match=r"API key \(UNIFI_API_KEY\)"):
            load_config(env)

    def test_missing_host_names_what_is_missing(self, monkeypatch, tmp_path):
        self._clear(monkeypatch)
        env = self._env(tmp_path, "UNIFI_API_KEY=k\n")
        with pytest.raises(ConfigError, match=r"host \(UNIFI_HOST\)"):
            load_config(env)

    def test_placeholder_key_is_rejected(self, monkeypatch, tmp_path):
        self._clear(monkeypatch)
        env = self._env(tmp_path, "UNIFI_HOST=h\nUNIFI_API_KEY=CHANGE_ME\n")
        with pytest.raises(ConfigError, match="CHANGE_ME"):
            load_config(env)

    def test_host_may_carry_a_port_and_assumes_https(self):
        assert ExporterConfig("unifi.example.com:8443", "k").base_url == (
            "https://unifi.example.com:8443"
        )
        assert ExporterConfig("http://1.2.3.4", "k").base_url == "https://1.2.3.4"
        assert ExporterConfig("unifi.example.com/", "k").base_url == "https://unifi.example.com"

    def test_verify_tls_accepts_words_and_a_ca_bundle_path(self, monkeypatch, tmp_path):
        self._clear(monkeypatch)
        base = "UNIFI_HOST=h\nUNIFI_API_KEY=k\n"
        assert (
            load_config(self._env(tmp_path, base + "UNIFI_VERIFY_TLS=false\n")).verify_tls is False
        )
        monkeypatch.delenv("UNIFI_VERIFY_TLS", raising=False)
        bundle = "/etc/ssl/certs/private-ca.pem"
        assert (
            load_config(self._env(tmp_path, base + f"UNIFI_VERIFY_TLS={bundle}\n")).verify_tls
            == bundle
        )


def test_client_sets_the_api_key_header_and_makes_no_request(tmp_path):
    from unifi_map.client import UniFiClient
    from unifi_map.config import ExporterConfig

    client = UniFiClient(ExporterConfig("h", "secret"))
    assert client.session.headers["X-API-KEY"] == "secret"
    # No login/logout exist any more: nothing to call, nothing to expire.
    assert not hasattr(client, "login")
    assert not hasattr(client, "logout")


class TestUnplacedClientsAreExplained:
    """The placeholder must say it is fixable, where somebody will see it.

    "Uplink not reported by controller" on a diagram gives no hint that the
    tool is refusing to guess rather than failing, or that the reader can place
    it themselves. The README section says so now; this says it at the moment
    the map is produced, which reaches whoever never read that section.
    """

    def _topo(self, stranded: int):
        from unifi_map.model import UNKNOWN_UPLINK_ID, Edge, Kind, Node, Topology

        topo = Topology()
        topo.add(Node(id="sw", label="switch", kind=Kind.SWITCH))
        if stranded:
            topo.add(Node(id=UNKNOWN_UPLINK_ID, label="Uplink not reported", kind=Kind.UNKNOWN))
            for i in range(stranded):
                topo.add(Node(id=f"c{i}", label=f"c{i}", kind=Kind.WIRED_CLIENT))
                topo.edges.append(Edge(src=f"c{i}", dst=UNKNOWN_UPLINK_ID))
        return topo

    def test_it_counts_them_and_points_at_overrides(self, caplog):
        from unifi_map.cli import _hint_about_unplaced

        with caplog.at_level("INFO"):
            _hint_about_unplaced(self._topo(3), None)
        message = " ".join(r.getMessage() for r in caplog.records)
        assert "3 client(s)" in message
        assert "overrides" in message.lower()

    def test_it_says_nothing_when_everything_is_placed(self, caplog):
        from unifi_map.cli import _hint_about_unplaced

        with caplog.at_level("INFO"):
            _hint_about_unplaced(self._topo(0), None)
        assert not caplog.records

    def test_with_an_overrides_file_it_reports_what_is_left(self, caplog):
        # Still counted, because somebody who wrote overrides and has stranded
        # clients remaining is exactly who benefits from the number. Only the
        # pointer is dropped, since they have plainly found it.
        from unifi_map.cli import _hint_about_unplaced

        with caplog.at_level("INFO"):
            _hint_about_unplaced(self._topo(2), Path("overrides.toml"))
        message = " ".join(r.getMessage() for r in caplog.records)
        assert "2 client(s) still" in message
        assert "README" not in message

    def test_the_count_is_of_stranded_clients_not_all_edges(self, caplog):
        from unifi_map.cli import _hint_about_unplaced
        from unifi_map.model import Edge

        topo = self._topo(2)
        # An unrelated link must not inflate the number.
        topo.edges.append(Edge(src="c0", dst="sw"))
        with caplog.at_level("INFO"):
            _hint_about_unplaced(topo, None)
        assert "2 client(s)" in " ".join(r.getMessage() for r in caplog.records)


class TestSharedPortsAreExplained:
    """The console half of KAN-199: `_hint_about_shared_ports`."""

    def test_it_names_the_switch_port_and_clients(self, caplog):
        from unifi_map.cli import _hint_about_shared_ports

        with caplog.at_level("WARNING"):
            _hint_about_shared_ports(_topo_with_shared_port(), obfuscated=False)
        message = " ".join(r.getMessage() for r in caplog.records)
        assert "switch" in message
        assert "port 7" in message
        assert "c1" in message and "c2" in message
        assert "hosted" in message

    def test_it_says_nothing_when_no_port_is_shared(self, caplog):
        from unifi_map.cli import _hint_about_shared_ports

        with caplog.at_level("WARNING"):
            _hint_about_shared_ports(_topo_with_shared_port(shared=False), obfuscated=False)
        assert not caplog.records

    def test_obfuscated_runs_get_a_count_without_names(self, caplog):
        from unifi_map.cli import _hint_about_shared_ports

        with caplog.at_level("WARNING"):
            _hint_about_shared_ports(_topo_with_shared_port(), obfuscated=True)
        message = " ".join(r.getMessage() for r in caplog.records)
        assert "1 switch port" in message
        assert "c1" not in message
        assert "c2" not in message
        assert "--obfuscate" in message


class TestSiteSelection:
    """`--site` exists so a script can loop over sites without re-exporting.

    It covers both inputs. `--support-site` did the same job for support files
    only and predates it; it still works because 0.3.0 shipped it.
    """

    def test_site_works_in_either_position(self):
        from unifi_map.cli import build_parser

        assert build_parser().parse_args(["--site", "branch", "all"]).site == "branch"
        assert build_parser().parse_args(["all", "--site", "branch"]).site == "branch"

    def test_no_site_means_no_opinion(self):
        # None rather than "default", so the environment still gets a say.
        from unifi_map.cli import build_parser

        assert build_parser().parse_args(["all"]).site is None

    def test_the_flag_beats_the_environment(self, tmp_path, monkeypatch):
        from unifi_map.config import load_config

        for name in ("UNIFI_SITE", "UDM_SITE", "UNIFI_HOST", "UNIFI_API_KEY"):
            monkeypatch.delenv(name, raising=False)
        env = tmp_path / "creds.env"
        env.write_text("UNIFI_HOST=h\nUNIFI_API_KEY=k\nUNIFI_SITE=from-env\n")
        assert load_config(env).site == "from-env"
        assert load_config(env, site="from-flag").site == "from-flag"

    def test_the_environment_still_wins_over_the_built_in_default(self, tmp_path, monkeypatch):
        from unifi_map.config import load_config

        for name in ("UNIFI_SITE", "UDM_SITE", "UNIFI_HOST", "UNIFI_API_KEY"):
            monkeypatch.delenv(name, raising=False)
        env = tmp_path / "creds.env"
        env.write_text("UNIFI_HOST=h\nUNIFI_API_KEY=k\n")
        assert load_config(env).site == "default"

    def test_support_site_still_works_and_says_it_is_deprecated(self, caplog):
        from unifi_map.cli import _requested_site, build_parser

        args = build_parser().parse_args(["fetch", "--support-site", "old"])
        with caplog.at_level("WARNING"):
            assert _requested_site(args) == "old"
        assert any("deprecated" in r.getMessage() for r in caplog.records)

    def test_site_wins_when_both_are_given(self, caplog):
        from unifi_map.cli import _requested_site, build_parser

        args = build_parser().parse_args(["fetch", "--site", "new", "--support-site", "old"])
        with caplog.at_level("WARNING"):
            assert _requested_site(args) == "new"
        # No warning: the caller is already using the flag being recommended.
        assert not any("deprecated" in r.getMessage() for r in caplog.records)


class TestLegendHonesty:
    """The legend must describe only what the diagram actually encodes."""

    def _legend_text(self, topo, style, icons=None):
        dot = render_dot(topo, "t", style, icons)
        start = dot.index("cluster_legend")
        return dot[start:]

    def test_shapes_only_render_lists_every_role(self, snapshot: Snapshot):
        topo = build_topology(snapshot)
        legend = self._legend_text(topo, TREE)
        # Nothing has artwork, so every role really is a coloured shape.
        assert "Switch" in legend
        assert "Gateway" in legend
        assert "shown by its artwork" not in legend

    def test_roles_drawn_as_artwork_get_no_swatch(self, snapshot: Snapshot, fake_icon):
        topo = build_topology(snapshot)
        style = Style(theme=LIGHT, icons="unifi", layout="tree")
        # Give every node artwork: no role swatch may remain, because artwork
        # nodes have no border or fill to carry an accent colour.
        icons = dict.fromkeys(topo.nodes, fake_icon)
        legend = self._legend_text(topo, style, icons)
        assert "shown by its artwork" in legend
        assert "Without artwork" not in legend
        for role in ("Gateway", "Switch", "Access point"):
            assert role not in legend, f"{role} swatch is a lie when it has artwork"

    def test_mixed_render_separates_the_two(self, snapshot: Snapshot, fake_icon):
        topo = build_topology(snapshot)
        style = Style(theme=LIGHT, icons="unifi", layout="tree")
        # The access point is the only node of its role in the fixture, so
        # covering it removes that role entirely. The fixture has two switches,
        # one of them offline, which is why picking a switch here would not.
        legend = self._legend_text(topo, style, {"aa:bb:cc:00:00:03": fake_icon})
        assert "shown by its artwork" in legend
        assert "Without artwork" in legend
        assert "Access point" not in legend, "role with artwork must lose its swatch"
        # Roles still drawn as shapes keep theirs.
        assert "Gateway" in legend
        assert "Switch" in legend

    def test_client_network_swatch_is_labelled_by_how_it_appears(
        self, snapshot: Snapshot, fake_icon
    ):
        topo = build_topology(snapshot)
        style = Style(theme=LIGHT, icons="unifi", layout="tree")
        icons = dict.fromkeys(topo.nodes, fake_icon)
        # With artwork the VLAN colour is the label text, not a border.
        assert "Client network (label colour)" in self._legend_text(topo, style, icons)
        assert "Client network (label colour)" not in self._legend_text(topo, TREE)

    def test_topology_graph_row_appears_only_when_such_an_edge_exists(self, snapshot: Snapshot):
        topo = build_topology(snapshot)
        # The fixture's edges are all direct reports, so the row must be absent.
        assert "Inferred from the topology graph" not in self._legend_text(topo, TREE)

        topo = _topo_with_topology_graph_edge()
        assert "Inferred from the topology graph" in self._legend_text(topo, TREE)

    def test_shared_port_note_appears_only_when_a_port_is_shared(self, snapshot: Snapshot):
        topo = build_topology(snapshot)
        assert "hidden switch" not in self._legend_text(topo, TREE)

        assert "hidden switch" in self._legend_text(_topo_with_shared_port(), TREE)


class TestApiKeyIsNotCarriedAcrossHosts:
    """`requests` strips `Authorization` on a cross-host redirect and nothing else.

    Ours is a custom header, so without help it would be handed to whatever host
    a redirect names. That is not hypothetical: the README documents
    `UNIFI_VERIFY_TLS=false` for bare IPs, and with verification off anyone in
    the path can supply the redirect.
    """

    def _prepared(self, url):
        import requests

        request = requests.Request("GET", url, headers={"X-API-KEY": "secret"})
        return request.prepare()

    def _redirect(self, from_url, to_url):
        import requests

        from unifi_map.client import _Session

        session = _Session()
        original = self._prepared(from_url)
        response = requests.Response()
        response.request = original
        following = self._prepared(to_url)
        following.headers["X-API-KEY"] = "secret"
        session.rebuild_auth(following, response)
        return following.headers

    def test_the_key_is_dropped_when_the_host_changes(self):
        headers = self._redirect("https://console.example.com/a", "https://elsewhere.example.net/a")
        assert "X-API-KEY" not in headers

    def test_the_key_survives_a_redirect_on_the_same_host(self):
        # A reverse proxy normalising a path or trailing slash must keep working.
        headers = self._redirect("https://console.example.com/a", "https://console.example.com/a/")
        assert headers["X-API-KEY"] == "secret"


class TestOutputIsNotClobbered:
    """Writing a diagram must not eat one somebody edited by hand.

    `.drawio` is advertised as editable, so opening it and rearranging it is the
    intended workflow rather than an unusual one. Re-rendering our own output,
    by contrast, has to stay free of ceremony: `fetch` and `render` are split
    precisely so render can be run over and over.
    """

    def _write(self, tmp_path, name, body, **kwargs):
        from unifi_map.output import write_output

        path = tmp_path / name
        path.write_text(body, encoding="utf-8")
        write_output(path, "replacement", **kwargs)
        return path

    def test_a_foreign_file_is_refused(self, tmp_path):
        from unifi_map.output import OutputExistsError, write_output

        path = tmp_path / "network-map.drawio"
        path.write_text("MY HAND EDITED DIAGRAM", encoding="utf-8")
        with pytest.raises(OutputExistsError, match="not written by unifi-map"):
            write_output(path, "replacement", force=False, guard=True)
        assert path.read_text(encoding="utf-8") == "MY HAND EDITED DIAGRAM"

    def test_force_overrides_the_refusal(self, tmp_path):
        path = self._write(tmp_path, "a.drawio", "MY HAND EDITED DIAGRAM", force=True, guard=True)
        assert path.read_text(encoding="utf-8") == "replacement"

    def test_our_own_drawio_is_replaced_without_ceremony(self, tmp_path):
        path = self._write(
            tmp_path, "b.drawio", '<mxfile host="unifi-map">', force=False, guard=True
        )
        assert path.read_text(encoding="utf-8") == "replacement"

    def test_our_own_dot_is_replaced_without_ceremony(self, tmp_path):
        path = self._write(tmp_path, "c.dot", "digraph unifi {\n}\n", force=False, guard=True)
        assert path.read_text(encoding="utf-8") == "replacement"

    def test_unguarded_formats_are_overwritten(self, tmp_path):
        # Nobody hand-authors a PNG at exactly this path, and there is nowhere
        # convenient to put a marker in one.
        path = self._write(tmp_path, "d.png", "whatever", force=False, guard=False)
        assert path.read_text(encoding="utf-8") == "replacement"

    def test_an_unreadable_existing_path_is_refused_rather_than_trusted(self, tmp_path):
        # `_is_ours()` cannot read it, so it must not conclude it is ours. A
        # directory at the target path is a portable way to make `open()` fail
        # without relying on permission bits, which root and some CI runners
        # ignore.
        from unifi_map.output import OutputExistsError, write_output

        path = tmp_path / "f.drawio"
        path.mkdir()
        with pytest.raises(OutputExistsError, match="not written by unifi-map"):
            write_output(path, "replacement", force=False, guard=True)


class TestWritesAreAtomic:
    def test_a_failed_write_leaves_the_previous_file_intact(self, tmp_path, monkeypatch):
        from unifi_map.output import write_output

        path = tmp_path / "e.svg"
        path.write_text("the good previous render", encoding="utf-8")

        real = os.replace

        def fail(*args, **kwargs):
            raise OSError("disk full")

        # Patched in `fsio`, which is where the rename now happens: the three
        # copies of this logic were merged into one helper.
        monkeypatch.setattr("unifi_map.fsio.os.replace", fail)
        with pytest.raises(OSError):
            write_output(path, "half a file", force=False, guard=False)
        monkeypatch.setattr("unifi_map.fsio.os.replace", real)

        # Not truncated, not replaced, and no debris beside it.
        assert path.read_text(encoding="utf-8") == "the good previous render"
        assert [p.name for p in tmp_path.iterdir()] == ["e.svg"]


class TestDrawioLabelsAreNotMarkup:
    """Device names are attacker-controlled and every cell sets `html=1`.

    ElementTree XML-escapes the attribute, but draw.io decodes it back and then
    parses it as HTML, so XML escaping alone is not enough. Whoever named the
    device decides what the string is.
    """

    def _render(self, label):
        from unifi_map.layout import Layout, Placed
        from unifi_map.model import Kind, Node, Topology
        from unifi_map.render_drawio import render_drawio
        from unifi_map.theme import LIGHT

        topo = Topology()
        topo.add(Node(id="a", label=label, kind=Kind.SWITCH, ip="10.0.0.1"))
        layout = Layout(
            nodes={"a": Placed(x=0.0, y=0.0, width=10.0, height=10.0)}, width=10.0, height=10.0
        )
        return render_drawio(topo, layout, "t", LIGHT)

    def test_an_img_tag_in_a_device_name_stays_text(self):
        # Double-escaped: HTML-escaped by us, then XML-escaped on serialisation.
        # draw.io undoes the XML layer and is left with literal `&lt;img`.
        xml = self._render('<img src=x onerror="alert(1)">')
        assert "&amp;lt;img" in xml
        assert "&lt;img" not in xml.replace("&amp;lt;img", "")

    def test_an_anchor_in_a_device_name_stays_text(self):
        assert "&amp;lt;a href" in self._render('<a href="http://evil.example">x</a>')

    def test_an_injected_tag_in_an_edge_label_stays_text(self):
        from unifi_map.layout import Layout, Placed
        from unifi_map.model import Edge, Kind, Node, Topology
        from unifi_map.render_drawio import render_drawio
        from unifi_map.theme import LIGHT

        topo = Topology()
        topo.add(Node(id="a", label="a", kind=Kind.SWITCH))
        topo.add(Node(id="b", label="b", kind=Kind.AP))
        topo.edges.append(Edge(src="b", dst="a", label="<img src=x>"))
        layout = Layout(
            nodes={
                "a": Placed(x=0.0, y=0.0, width=10.0, height=10.0),
                "b": Placed(x=0.0, y=20.0, width=10.0, height=10.0),
            },
            width=10.0,
            height=30.0,
        )
        assert "&amp;lt;img" in render_drawio(topo, layout, "t", LIGHT)

    def test_our_own_markup_is_still_markup(self):
        # Single-escaped, so draw.io renders real bold rather than showing tags.
        assert "&lt;b&gt;switch&lt;/b&gt;" in self._render("switch")


class TestDrawioProvenanceMarker:
    """The draw.io twin of the DOT `arrowhead=odot` marker: KAN-137."""

    def _render(self, provenance, wireless=False):
        from unifi_map.layout import Layout, Placed
        from unifi_map.model import Edge, Kind, Node, Topology
        from unifi_map.render_drawio import render_drawio
        from unifi_map.theme import LIGHT

        topo = Topology()
        topo.add(Node(id="a", label="a", kind=Kind.SWITCH))
        topo.add(Node(id="b", label="b", kind=Kind.WIRED_CLIENT))
        topo.edges.append(Edge(src="b", dst="a", provenance=provenance, wireless=wireless))
        layout = Layout(
            nodes={
                "a": Placed(x=0.0, y=0.0, width=10.0, height=10.0),
                "b": Placed(x=0.0, y=20.0, width=10.0, height=10.0),
            },
            width=10.0,
            height=30.0,
        )
        return render_drawio(topo, layout, "t", LIGHT)

    def test_topology_graph_edge_gets_a_hollow_oval_arrow(self):
        from unifi_map.model import Provenance

        assert "endArrow=oval;endFill=0" in self._render(Provenance.TOPOLOGY_GRAPH)

    def test_a_direct_report_gets_no_arrow(self):
        from unifi_map.model import Provenance

        xml = self._render(Provenance.CLIENT_UPLINK)
        assert "endArrow=oval" not in xml
        assert "endArrow=none" in xml

    def test_marker_composes_with_the_wireless_dash(self):
        from unifi_map.model import Provenance

        xml = self._render(Provenance.TOPOLOGY_GRAPH, wireless=True)
        assert "endArrow=oval;endFill=0" in xml
        assert "dashed=1" in xml


class TestDrawioSharedPortMarker:
    """The draw.io twin of the DOT `* ` port-label marker: KAN-199."""

    def _render(self, shared: bool):
        from unifi_map.layout import Layout, Placed
        from unifi_map.model import Edge, Kind, Node, Provenance, Topology
        from unifi_map.render_drawio import render_drawio
        from unifi_map.theme import LIGHT

        topo = Topology()
        topo.add(Node(id="sw", label="switch", kind=Kind.SWITCH))
        topo.add(Node(id="c1", label="c1", kind=Kind.WIRED_CLIENT))
        topo.edges.append(
            Edge(src="c1", dst="sw", label="port 7", provenance=Provenance.CLIENT_UPLINK)
        )
        nodes = {
            "sw": Placed(x=0.0, y=0.0, width=10.0, height=10.0),
            "c1": Placed(x=0.0, y=20.0, width=10.0, height=10.0),
        }
        if shared:
            topo.add(Node(id="c2", label="c2", kind=Kind.WIRED_CLIENT))
            topo.edges.append(
                Edge(src="c2", dst="sw", label="port 7", provenance=Provenance.CLIENT_UPLINK)
            )
            nodes["c2"] = Placed(x=20.0, y=20.0, width=10.0, height=10.0)
        layout = Layout(nodes=nodes, width=30.0, height=30.0)
        return render_drawio(topo, layout, "t", LIGHT)

    def test_a_shared_port_gets_an_asterisk(self):
        xml = self._render(shared=True)
        assert xml.count("port 7 *") == 2

    def test_an_unshared_port_gets_no_asterisk(self):
        xml = self._render(shared=False)
        assert "port 7" in xml
        assert "port 7 *" not in xml


class TestDrawioGeometryIsAddressable:
    """Every `mxGeometry` must carry `as="geometry"` or draw.io ignores it.

    `as` is a Python keyword and cannot be a `SubElement` kwarg, so it is set
    afterwards by `_geometry()` and is easy to lose in a refactor. Losing it is
    silent: the XML stays well-formed, every other test still passes, and
    draw.io piles every shape on top of itself at the origin. Nothing else
    catches that, so this asserts it on the emitted document.
    """

    def _render(self):
        from unifi_map.layout import Layout, Placed
        from unifi_map.model import Edge, Kind, Node, Topology
        from unifi_map.render_drawio import render_drawio
        from unifi_map.theme import LIGHT

        topo = Topology()
        topo.add(Node(id="a", label="a", kind=Kind.SWITCH, ip="10.0.0.1"))
        topo.add(Node(id="b", label="b", kind=Kind.AP))
        topo.edges.append(Edge(src="b", dst="a", label="1"))
        layout = Layout(
            nodes={
                "a": Placed(x=0.0, y=0.0, width=10.0, height=10.0),
                "b": Placed(x=0.0, y=20.0, width=10.0, height=10.0),
            },
            width=10.0,
            height=30.0,
        )
        return render_drawio(topo, layout, "t", LIGHT)

    def test_every_geometry_element_is_marked_as_geometry(self):
        import xml.etree.ElementTree as ET

        root = ET.fromstring(self._render())
        geometries = root.iter("mxGeometry")
        unmarked = [g for g in geometries if g.get("as") != "geometry"]
        assert not unmarked, f'{len(unmarked)} mxGeometry element(s) missing as="geometry"'

    def test_the_document_contains_geometry_at_all(self):
        # Guards the assertion above from passing vacuously if cells stop
        # carrying geometry entirely.
        import xml.etree.ElementTree as ET

        assert list(ET.fromstring(self._render()).iter("mxGeometry"))


class TestDrawioEdgesCarryGraphvizsRoute:
    """An edge must ship the waypoints Graphviz computed, not just its ends.

    With only `source` and `target`, draw.io routes the edge itself and draws a
    long run straight through whatever the layout placed in between. On a real
    map that is connection lines crossing unrelated devices. Graphviz already
    solved it and the answer was being discarded.

    Safe to pass straight through because both layouts set `splines` to `ortho`
    or `polyline`, never a bezier, so the reported points are corners on the
    route rather than control points.
    """

    def _layout_and_topo(self):
        from unifi_map.layout import Layout, Placed
        from unifi_map.model import Edge, Kind, Node, Topology
        from unifi_map.render_drawio import _cell_id

        topo = Topology()
        topo.add(Node(id="a", label="a", kind=Kind.SWITCH))
        topo.add(Node(id="b", label="b", kind=Kind.AP))
        topo.edges.append(Edge(src="b", dst="a", label="1"))
        layout = Layout(
            nodes={
                _cell_id("a"): Placed(x=0.0, y=0.0, width=10.0, height=10.0),
                _cell_id("b"): Placed(x=0.0, y=200.0, width=10.0, height=10.0),
            },
            width=10.0,
            height=210.0,
            # Endpoints plus two corners; only the corners should be emitted.
            edges={
                (_cell_id("a"), _cell_id("b")): [
                    [(5.0, 10.0), (60.0, 60.0), (60.0, 150.0), (5.0, 200.0)]
                ]
            },
        )
        return topo, layout

    def _render(self):
        from unifi_map.render_drawio import render_drawio
        from unifi_map.theme import LIGHT

        topo, layout = self._layout_and_topo()
        return render_drawio(topo, layout, "t", LIGHT)

    def test_the_interior_waypoints_are_emitted(self):
        import xml.etree.ElementTree as ET

        root = ET.fromstring(self._render())
        arrays = [a for a in root.iter("Array") if a.get("as") == "points"]
        assert arrays, "edge carries no waypoint array"
        pts = [(m.get("x"), m.get("y")) for m in arrays[0]]
        assert pts == [("60.0", "60.0"), ("60.0", "150.0")]

    def test_the_endpoints_are_not_repeated_as_waypoints(self):
        """draw.io derives those from the shapes; passing them bends the ends."""
        import xml.etree.ElementTree as ET

        root = ET.fromstring(self._render())
        array = next(a for a in root.iter("Array") if a.get("as") == "points")
        xs = {m.get("x") for m in array}
        assert "5.0" not in xs

    def test_an_edge_with_no_reported_route_still_renders(self):
        """A route we could not read means draw.io routes it, as it used to."""
        import xml.etree.ElementTree as ET

        from unifi_map.layout import Layout
        from unifi_map.render_drawio import render_drawio
        from unifi_map.theme import LIGHT

        topo, layout = self._layout_and_topo()
        bare = Layout(nodes=layout.nodes, width=layout.width, height=layout.height)
        root = ET.fromstring(render_drawio(topo, bare, "t", LIGHT))
        assert [c for c in root.iter("mxCell") if c.get("edge")]
        assert not [a for a in root.iter("Array") if a.get("as") == "points"]


class TestDrawioLabelsStayInsideTheirCell:
    """A node's caption must render within the box Graphviz sized for it.

    Graphviz measures each node to hold the artwork *and* the text, which is
    what the SVG draws. `verticalLabelPosition=bottom` puts draw.io's label
    below the cell bounds instead, so the box carries dead space and the
    caption lands on whatever the layout placed underneath. On a dense map that
    is every icon in a column wearing its neighbour's caption, which is what it
    did until it was reported from a real network.

    Only reproducible by opening the file, so the style string is asserted
    directly. That is pinning an implementation detail on purpose: it is the
    detail, and nothing else here would notice it changing.
    """

    def _render(self, tmp_path):
        from unifi_map.assets import IconAsset
        from unifi_map.layout import Layout, Placed
        from unifi_map.model import Kind, Node, Topology
        from unifi_map.render_drawio import _cell_id, render_drawio
        from unifi_map.theme import LIGHT

        png = tmp_path / "icon.png"
        png.write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00"
            b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        topo = Topology()
        topo.add(Node(id="a", label="a", kind=Kind.SWITCH, ip="10.0.0.1"))
        # Keyed by cell id, not node id: `render_drawio` looks the layout up by
        # `_cell_id()`, so a raw id here silently takes the unplaced-node
        # fallback and the test stops exercising a positioned cell.
        layout = Layout(
            nodes={_cell_id("a"): Placed(x=0.0, y=0.0, width=174.0, height=69.0)},
            width=174.0,
            height=69.0,
        )
        icons = {"a": IconAsset(path=png, width=64, height=64)}
        return render_drawio(topo, layout, "t", LIGHT, icons)

    def test_the_label_is_not_pushed_outside_the_cell(self, tmp_path):
        xml = self._render(tmp_path)
        assert "verticalLabelPosition=middle" in xml
        assert "verticalLabelPosition=bottom" not in xml

    def test_the_icon_cell_really_was_produced(self, tmp_path):
        # Guards the assertion above from passing vacuously: with no icon the
        # style is never emitted and "bottom" is absent for the wrong reason.
        xml = self._render(tmp_path)
        assert "imageVerticalAlign=top" in xml


class TestStaggerIsAppliedOnceToBothRenderers:
    """The SVG and the draw.io coordinates must come from byte-identical DOT.

    `write_outputs()` staggers up front and feeds the result to both paths. If
    a change routes unstaggered DOT to one of them, or writes the `.dot` from
    before the stagger, the diagram still renders and the draw.io shapes land
    somewhere plausible but no longer where the SVG drew them. Comparing the
    written `.dot` against the positions in the written `.drawio` catches that
    without mocking Graphviz: on this fixture the stagger moves nodes by some
    790pt, so a path that skipped it cannot coincidentally agree.

    It does not prove the stagger is applied only *once*, because `unflatten`
    turns out to be idempotent here (measured: a second pass moves nothing).
    Double-staggering is therefore harmless rather than untested.
    """

    @needs_graphviz
    def test_drawio_positions_match_the_dot_that_was_written(self, snapshot, tmp_path):
        import xml.etree.ElementTree as ET

        from unifi_map.layout import compute_layout
        from unifi_map.output import write_outputs

        topo = build_topology(snapshot)
        write_outputs(
            render_dot(topo, "t", TREE),
            topo,
            tmp_path,
            "m",
            ["dot", "drawio"],
            TREE,
            {},
            stagger_depth=2,
        )

        # The .dot on disk is the post-stagger source, by contract.
        expected = compute_layout((tmp_path / "m.dot").read_text(encoding="utf-8"))
        root = ET.fromstring((tmp_path / "m.drawio").read_text(encoding="utf-8"))

        placed = {
            cell.get("id"): cell.find("mxGeometry")
            for cell in root.iter("mxCell")
            if cell.find("mxGeometry") is not None
        }
        # Layout keys are already DOT node ids, which is what the cells use.
        compared = 0
        for node_id, want in expected.nodes.items():
            geometry = placed.get(node_id)
            if geometry is None or geometry.get("x") is None:
                continue
            # Same DOT means the same Graphviz answer, so these agree to the
            # one decimal place the renderer writes rather than approximately.
            assert abs(float(geometry.get("x")) - want.x) < 0.5, node_id
            assert abs(float(geometry.get("y")) - want.y) < 0.5, node_id
            compared += 1
        assert compared > 1, "compared too few nodes to prove anything"


class TestCredentialFilePermissions:
    """The file holds a key with the account's full permissions.

    A plain `cp` of the example inherits the umask, which on most systems leaves
    it world-readable, so this is the likely state rather than an exotic one.
    """

    def test_a_world_readable_credential_file_is_flagged(self, tmp_path, caplog):
        from unifi_map.config import read_dotenv

        env = tmp_path / "env"
        env.write_text("UNIFI_HOST=example.com\n", encoding="utf-8")
        env.chmod(0o644)
        with caplog.at_level("WARNING"):
            read_dotenv(env)
        assert "readable by other users" in caplog.text

    def test_a_private_credential_file_is_silent(self, tmp_path, caplog):
        from unifi_map.config import read_dotenv

        env = tmp_path / "env"
        env.write_text("UNIFI_HOST=example.com\n", encoding="utf-8")
        env.chmod(0o600)
        with caplog.at_level("WARNING"):
            read_dotenv(env)
        assert "readable by other users" not in caplog.text


class TestCredentialsDoNotReachChildProcesses:
    """Graphviz is resolved from PATH and inherits whatever we hand it.

    Two defences, tested separately: a key read from a credential file never
    enters `os.environ` at all, and a key the user exported themselves is
    stripped from the environment passed to any child.
    """

    def test_a_key_from_a_file_never_enters_the_environment(self, tmp_path, monkeypatch):
        from unifi_map.config import load_config

        monkeypatch.delenv("UNIFI_API_KEY", raising=False)
        monkeypatch.delenv("UDM_API_KEY", raising=False)
        monkeypatch.delenv("UNIFI_HOST", raising=False)
        monkeypatch.delenv("UDM_HOST", raising=False)
        env = tmp_path / "env"
        env.write_text("UNIFI_HOST=console.example.com\nUNIFI_API_KEY=super-secret\n")
        env.chmod(0o600)

        config = load_config(env)
        assert config.api_key == "super-secret"
        # Read, used, and not left anywhere a subprocess could find it.
        assert "UNIFI_API_KEY" not in os.environ

    def test_an_exported_key_is_stripped_from_child_environments(self, monkeypatch):
        from unifi_map.layout import child_env

        monkeypatch.setenv("UNIFI_API_KEY", "super-secret")
        monkeypatch.setenv("UDM_API_KEY", "also-secret")
        monkeypatch.setenv("PATH", os.environ.get("PATH", ""))

        env = child_env()
        assert "UNIFI_API_KEY" not in env
        assert "UDM_API_KEY" not in env
        # Still a usable environment, not an empty one.
        assert "PATH" in env

    def test_graphviz_really_does_not_see_the_key(self, monkeypatch, tmp_path):
        """End to end: run a stand-in for `dot` that reports its environment."""
        import subprocess

        from unifi_map.layout import child_env

        monkeypatch.setenv("UNIFI_API_KEY", "super-secret")
        probe = tmp_path / "probe.py"
        probe.write_text("import os,sys; sys.stdout.write(os.environ.get('UNIFI_API_KEY',''))")
        result = subprocess.run(
            [sys.executable, str(probe)], capture_output=True, env=child_env(), check=False
        )
        assert result.stdout == b""

    def test_the_graphviz_version_probe_also_does_not_see_the_key(self, monkeypatch, tmp_path):
        """`cmd_shape` calls `_graphviz_version()` to run `dot -V`, a second
        Graphviz child process separate from `run_dot`/`unflatten` above. It was
        missed when `child_env()` scrubbing was added to those, and inherited
        the full environment -- including an exported key -- until fixed.
        `unifi-map shape` is specifically the command meant to be safe to paste
        into a bug report, which is what makes this one worth its own test
        rather than trusting that "it's the same kind of subprocess" generalises.
        """
        from unifi_map.cli import _graphviz_version

        marker = tmp_path / "seen.txt"
        fake_dot = tmp_path / "dot"
        fake_dot.write_text(
            f"#!{sys.executable}\n"
            "import os\n"
            f"open({str(marker)!r}, 'w').write(os.environ.get('UNIFI_API_KEY', ''))\n"
            "import sys; sys.stderr.write('dot - graphviz version 9.9.9 (test)\\n')\n"
        )
        fake_dot.chmod(0o755)
        monkeypatch.setenv("UNIFI_API_KEY", "super-secret")
        monkeypatch.setenv("PATH", str(tmp_path))

        _graphviz_version()

        assert marker.read_text() == "", "UNIFI_API_KEY leaked into the `dot -V` child process"


class TestTheUdmNamesAreGone:
    """Removed in 0.9.0, after warning since 0.7.0.

    Kept as a test rather than simply deleted with the code, because "we stopped
    reading it" is a behaviour somebody could undo by reintroducing an alias
    without noticing. The failure mode that matters is a `UDM_*`-only credential
    file appearing to work.
    """

    def _load(self, monkeypatch, env):
        from unifi_map.config import load_config

        for name in (
            "UNIFI_HOST",
            "UNIFI_API_KEY",
            "UNIFI_SITE",
            "UNIFI_VERIFY_TLS",
            "UDM_HOST",
            "UDM_API_KEY",
            "UDM_SITE",
            "UDM_VERIFY_TLS",
        ):
            monkeypatch.delenv(name, raising=False)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        return load_config(Path("/dev/null"))

    def test_a_udm_only_environment_does_not_configure_anything(self, monkeypatch):
        with pytest.raises(ConfigError):
            self._load(monkeypatch, {"UDM_HOST": "c.example.com", "UDM_API_KEY": "k"})

    def test_a_udm_value_never_reaches_the_config(self, monkeypatch):
        """Set both, with different values. The UDM one must not appear at all."""
        config = self._load(
            monkeypatch,
            {
                "UNIFI_HOST": "right.example.com",
                "UDM_HOST": "wrong.example.com",
                "UNIFI_API_KEY": "k",
                "UDM_SITE": "wrong-site",
            },
        )
        assert config.host == "right.example.com"
        assert config.site == "default"

    def test_the_current_spelling_is_silent(self, monkeypatch, caplog):
        """Nothing warns any more, since there is no deprecation left to warn about."""
        with caplog.at_level("WARNING"):
            self._load(monkeypatch, {"UNIFI_HOST": "c.example.com", "UNIFI_API_KEY": "k"})
        assert "deprecated" not in caplog.text

    def test_a_key_exported_under_the_old_name_is_still_kept_from_graphviz(self):
        """Retiring the alias must not narrow what `layout.py` withholds.

        We stopped reading `UDM_API_KEY`; somebody who still exports one has a
        real key in their environment either way.
        """
        from unifi_map.layout import _CREDENTIAL_VARS

        assert "UDM_API_KEY" in _CREDENTIAL_VARS


class TestAnExistingOutputDirectoryIsLeftAlone:
    """Only a directory this tool created may be tightened to 0700.

    `_restrict` said exactly that in its own docstring while the caller ran it
    unconditionally after `mkdir(exist_ok=True)`. Pointing `--out-dir` at a
    shared directory silently took it from 0775 to 0700 and locked out everyone
    else, which is a hard failure to attribute to a diagram tool.
    """

    def test_a_directory_we_created_is_private(self, tmp_path):
        from unifi_map.fsio import mkdir_private

        target = tmp_path / "fresh"
        mkdir_private(target)
        assert target.is_dir()
        assert oct(target.stat().st_mode)[-3:] == "700"

    def test_an_existing_directory_keeps_its_mode(self, tmp_path):
        from unifi_map.fsio import mkdir_private

        target = tmp_path / "shared"
        target.mkdir()
        target.chmod(0o775)
        mkdir_private(target)
        assert oct(target.stat().st_mode)[-3:] == "775", "somebody else's directory was tightened"

    def test_every_level_we_create_is_private_not_just_the_leaf(self, tmp_path):
        # `mkdir(parents=True)` creates three directories; restricting only the
        # last left the other two at the umask. Output filenames are derived
        # from network names, so a listable parent discloses the network layout
        # even though the files themselves are 0600.
        from unifi_map.fsio import mkdir_private

        target = tmp_path / "a" / "b" / "c"
        mkdir_private(target)
        assert target.is_dir()
        for level in (tmp_path / "a", tmp_path / "a" / "b", target):
            assert oct(level.stat().st_mode)[-3:] == "700", f"{level} left at the umask"

    def test_a_new_child_of_an_existing_directory_is_still_private(self, tmp_path):
        from unifi_map.fsio import mkdir_private

        parent = tmp_path / "shared"
        parent.mkdir()
        parent.chmod(0o775)
        mkdir_private(parent / "ours")
        assert oct(parent.stat().st_mode)[-3:] == "775"
        assert oct((parent / "ours").stat().st_mode)[-3:] == "700"


class TestPerNetworkFilenamesAreUnique:
    """Distinct networks must not land on the same file.

    `safe_name` maps "IoT A", "IoT-A" and "IoT/A" all to "iot-a". The second
    diagram overwrote the first, and quietly: the file it replaced carried this
    tool's own provenance marker, so the overwrite guard let it through.
    """

    def test_names_differing_only_in_punctuation_get_distinct_stems(self):
        from unifi_map.output import unique_names

        stems = unique_names(["IoT A", "IoT-A", "IoT/A"])
        assert len(set(stems.values())) == 3, f"collision remains: {stems}"

    def test_an_uncontested_name_keeps_the_plain_slug(self):
        from unifi_map.output import unique_names

        assert unique_names(["Servers", "IoT A"])["Servers"] == "servers"

    def test_a_stem_does_not_depend_on_the_order_networks_arrive_in(self):
        # A counter would renumber diagrams whenever the controller reordered
        # its networks, so the suffix is derived from the name itself.
        from unifi_map.output import unique_names

        forward = unique_names(["IoT A", "IoT-A", "Servers"])
        reverse = unique_names(["Servers", "IoT-A", "IoT A"])
        assert forward == reverse


class TestTransparentBackground:
    """`--transparent` draws no canvas, so the map sits on the page beneath it.

    The theme still applies, and matters more than it appears to. Node labels
    have no card behind them: a light render has exactly one filled shape, the
    canvas itself. Remove it and every label, edge label and title is drawn
    straight onto whatever the map is placed on, so the theme has to match the
    destination or the text is invisible.
    """

    def test_dot_asks_graphviz_for_no_background(self, snapshot: Snapshot):
        style = Style(theme=LIGHT, icons="builtin", layout="unifi", transparent=True)
        assert 'bgcolor="transparent";' in render_dot(build_topology(snapshot), "t", style)

    def test_without_the_flag_the_theme_paints_the_canvas(self, snapshot: Snapshot):
        dot = render_dot(build_topology(snapshot), "t", UNIFI)
        assert f'bgcolor="{LIGHT.background}";' in dot
        assert "transparent" not in dot

    def test_drawio_omits_the_background_attribute(self):
        from unifi_map.layout import Layout, Placed
        from unifi_map.model import Kind, Node, Topology
        from unifi_map.render_drawio import render_drawio

        topo = Topology()
        topo.add(Node(id="a", label="a", kind=Kind.SWITCH))
        layout = Layout(
            nodes={"a": Placed(x=0.0, y=0.0, width=10.0, height=10.0)}, width=10.0, height=10.0
        )
        opaque = render_drawio(topo, layout, "t", LIGHT)
        clear = render_drawio(topo, layout, "t", LIGHT, None, True)
        # Absent rather than the literal string "none", which is not portable
        # across draw.io versions.
        assert f'background="{LIGHT.background}"' in opaque
        assert "background=" not in clear

    def test_the_theme_still_colours_everything_else(self, snapshot: Snapshot):
        # The point of keeping --theme meaningful under --transparent.
        topo = build_topology(snapshot)
        light = render_dot(topo, "t", Style(theme=LIGHT, icons="builtin", transparent=True))
        dark = render_dot(
            topo, "t", Style(theme=get_theme("dark"), icons="builtin", transparent=True)
        )
        assert light != dark
        assert LIGHT.text in light
        assert LIGHT.text not in dark

    @needs_graphviz
    def test_the_rendered_svg_paints_no_canvas(self, snapshot: Snapshot):
        # The canvas goes; node shapes keep their own fill, which is the point.
        # `--icons builtin` draws filled shapes and they must survive, so the
        # assertion is about the background colour specifically rather than
        # about there being no fills at all.
        style = Style(theme=LIGHT, icons="builtin", layout="unifi", transparent=True)
        svg = run_dot(render_dot(build_topology(snapshot), "t", style), "svg").decode()
        assert LIGHT.background.lower() not in svg.lower(), "the canvas was still painted"

    @needs_graphviz
    def test_node_shapes_keep_their_fill(self, snapshot: Snapshot):
        style = Style(theme=LIGHT, icons="builtin", layout="unifi", transparent=True)
        svg = run_dot(render_dot(build_topology(snapshot), "t", style), "svg").decode()
        assert LIGHT.card.lower() in svg.lower(), "transparency ate the node shapes too"


class TestTheEnvironmentCanAskForAFlourish:
    """A cosmetic addition, off unless the environment asks.

    Deliberately not described in the README or in `--help`. What matters for
    correctness is only that it changes nothing else: it is emitted into the DOT
    directly rather than added to the topology, so it cannot reach counts,
    filtering, obfuscation or the report.
    """

    def test_it_is_off_by_default(self, snapshot: Snapshot, monkeypatch):
        monkeypatch.delenv("HOOPY_FROOD", raising=False)
        assert "PANIC" not in render_dot(build_topology(snapshot), "t", UNIFI)

    def test_an_unrecognised_value_does_nothing(self, snapshot: Snapshot, monkeypatch):
        monkeypatch.setenv("HOOPY_FROOD", "yes")
        assert "PANIC" not in render_dot(build_topology(snapshot), "t", UNIFI)

    def test_the_expected_value_adds_it(self, snapshot: Snapshot, monkeypatch):
        monkeypatch.setenv("HOOPY_FROOD", "map")
        assert "PANIC" in render_dot(build_topology(snapshot), "t", UNIFI)

    def test_it_changes_nothing_that_is_counted(self, snapshot: Snapshot, monkeypatch):
        # The load-bearing assertion. Decoration must stay decoration.
        topo = build_topology(snapshot)
        before = (len(topo.nodes), len(topo.edges), topo.counts())
        monkeypatch.setenv("HOOPY_FROOD", "map")
        render_dot(topo, "t", UNIFI)
        assert before == (len(topo.nodes), len(topo.edges), topo.counts())

    @needs_graphviz
    def test_the_svg_still_renders(self, snapshot: Snapshot, monkeypatch):
        monkeypatch.setenv("HOOPY_FROOD", "map")
        svg = run_dot(render_dot(build_topology(snapshot), "t", UNIFI), "svg").decode()
        assert "<svg" in svg


class TestTheRenderedStampCanBeFixed:
    """`SOURCE_DATE_EPOCH` pins the time in the title block.

    A real map should say when it was drawn. A map committed to a repository
    should not, because regenerating it then produces a diff on every run from
    the clock alone, and a genuine rendering change becomes indistinguishable
    from a tick. That is not hypothetical: two committed screenshots differed by
    exactly the thirty pixels of their timestamp.
    """

    def test_the_stamp_moves_without_it(self, snapshot: Snapshot, monkeypatch):
        monkeypatch.delenv("SOURCE_DATE_EPOCH", raising=False)
        from unifi_map.cli import _subtitle

        assert "generated" in _subtitle(build_topology(snapshot).counts())

    def test_it_is_honoured_when_set(self, snapshot: Snapshot, monkeypatch):
        monkeypatch.setenv("SOURCE_DATE_EPOCH", "1785715200")
        from unifi_map.cli import _subtitle

        assert "2026-08-03 00:00 UTC" in _subtitle(build_topology(snapshot).counts())

    def test_nonsense_is_ignored_rather_than_fatal(self, snapshot: Snapshot, monkeypatch):
        from unifi_map.cli import _subtitle

        for bad in ("", "yesterday", "-1", "12.5"):
            monkeypatch.setenv("SOURCE_DATE_EPOCH", bad)
            assert "generated" in _subtitle(build_topology(snapshot).counts())
