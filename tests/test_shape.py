"""The shareable network-shape report.

The load-bearing test is `test_nothing_identifying_reaches_the_report`. The
whole premise is that somebody can paste the output into a public issue without
reading it line by line first, so a leak here is worse than no feature: it would
be a promise of safety that turned out to be false.

It reuses the `identifying` fixture from the obfuscation tests, which is a
snapshot built entirely out of values that must never appear in output, plus the
list of them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from unifi_map.model import build_topology
from unifi_map.report import CONSENT, KNOWN_FIELDS, Extras, build_report

from .test_obfuscate import identifying  # noqa: F401  (pytest fixture)

# Every literal this module can emit, so the vocabulary check knows what is ours.
_PROSE = " ".join(
    [
        "unifi-map network shape report source controller version python on",
        "SCALE infrastructure gateway switch ap bridge clients wireless wired guest",
        "client networks sites in source SHAPE edges children per parent min median max",
        "unplaced no uplink reported for these from overrides node link SUPPORT FILE",
        "uncompressed walked bytes entries members read of SCHEMA field names only",
        "values are or shown record s present absent unknown further key not",
        "schema-shaped NOTES Counts and versions No addresses MACs hostnames SSIDs",
        "site network names appear above by construction not Linux Darwin Windows",
        "cached snapshot support file live fetch graphviz depth offline devices",
        "ARTWORK how often the joins onto Ubiquiti catalogues succeed by sysid",
        "resolved product UniFi hardware generic glyph found configured",
        "Keys this tool does not recognise are counted but never printed",
        "because a key can hold a value chosen in advance see the note below",
    ]
)


class TestNothingIdentifyingEscapes:
    def test_nothing_identifying_reaches_the_report(self, identifying):  # noqa: F811
        report = build_report(
            build_topology(identifying["snapshot"]), identifying["snapshot"].payloads
        )
        # Word boundaries, not substrings: a network genuinely named "lan"
        # otherwise "leaks" by appearing inside the field name `vlan`, which is
        # our own vocabulary rather than theirs.
        leaked = [
            s
            for s in identifying["secrets"]
            if s and re.search(rf"(?<![\w.-]){re.escape(str(s))}(?![\w.-])", report)
        ]
        assert not leaked, f"the report leaked: {leaked}"

    def test_the_reports_whole_vocabulary_is_ours(self, identifying):  # noqa: F811
        """Stronger than searching for known secrets: nothing unexpected at all.

        The design is an allowlist, so the right assertion is that the output
        vocabulary is closed. Every word is a number, a field name we chose in
        advance, or a literal from this module. A value arriving by a route
        nobody predicted fails here even though no test knew to look for it.
        """
        report = build_report(
            build_topology(identifying["snapshot"]), identifying["snapshot"].payloads
        )
        # Payload names are ours too: they are the keys this tool chose for the
        # endpoints it fetches, not anything the controller supplied.
        allowed = {w for names in KNOWN_FIELDS.values() for w in names}
        allowed |= set(KNOWN_FIELDS) | set(identifying["snapshot"].payloads)
        allowed |= set(re.findall(r"[A-Za-z_][\w.-]*", CONSENT))
        allowed |= set(re.findall(r"[A-Za-z_][\w.-]*", _PROSE))
        stray = {
            w
            for w in (t.strip(".,") for t in re.findall(r"[A-Za-z_][\w.-]*", report))
            if w not in allowed and not w.replace(".", "").isdigit()
        }
        assert not stray, f"words in the report from no known source: {sorted(stray)}"

    @pytest.mark.parametrize(
        "secret",
        [
            "Jasons iPhone 14 Pro",  # obviously not a field name
            "10.0.0.5",  # an address
            "nas",  # a hostname
            "secretssid",  # an SSID
            "branch-office",  # a site name
        ],
    )
    def test_no_unrecognised_key_is_ever_echoed(self, secret):
        """Not "no key that *looks* like a value". No unrecognised key at all.

        The earlier version printed unrecognised keys that passed a shape
        filter, so that an unfamiliar controller's new fields would be visible.
        Every example below satisfied that filter: a short lowercase token is
        exactly what an address, a hostname, an SSID and a site name look like.
        A payload keyed by one of those would have been reproduced under a
        heading promising it could not be.
        """
        from unifi_map.report import _field_report

        lines = "\n".join(_field_report("device", [{"mac": "x", secret: 1}]))
        assert secret not in lines
        assert "1 further key(s), not named" in lines

    def test_container_keys_are_never_read(self):
        """A support file's devices.json is keyed by site name, which users pick.

        Describing a payload by enumerating its keys would leak those names on
        exactly the multi-site archives most worth seeing.
        """
        from unifi_map.report import _records

        assert _records({"branch-office": [{"mac": "x"}]}) == []
        assert _records({"data": [{"mac": "x"}]}) == [{"mac": "x"}]

    def test_the_report_is_short_enough_to_read(self, snapshot):
        report = build_report(build_topology(snapshot), snapshot.payloads)
        assert len(report.splitlines()) < 60, "too long to read before sending"
        assert max(len(line) for line in report.splitlines()) <= 100


class TestItSaysSomethingUseful:
    def test_it_reports_absent_fields_not_only_present_ones(self, snapshot):
        # The point of the schema section: a controller that moved something is
        # only visible as an absence.
        report = build_report(build_topology(snapshot), snapshot.payloads)
        assert "absent" in report
        assert "port_table" in report

    def test_counts_match_the_topology(self, snapshot):
        topo = build_topology(snapshot)
        report = build_report(topo, snapshot.payloads)
        assert f"edges               {len(topo.edges)}" in report

    def test_support_file_stats_appear_only_when_supplied(self, snapshot):
        topo = build_topology(snapshot)
        assert "SUPPORT FILE" not in build_report(topo, snapshot.payloads)
        extras = Extras(archive_bytes=1234, archive_entries=99, members_found=7)
        assert "SUPPORT FILE" in build_report(topo, snapshot.payloads, extras)

    def test_every_known_payload_has_a_field_list(self):
        # A payload with no entry here still reports, but says nothing useful,
        # so a new endpoint should not be forgotten.
        assert set(KNOWN_FIELDS) >= {"device", "client_active", "networkconf", "health"}


class TestConsent:
    def test_the_prompt_says_what_is_and_is_not_collected(self):
        for promised in ("counts", "field NAMES", "versions"):
            assert promised in CONSENT
        for refused in ("MAC addresses", "SSIDs", "hostnames"):
            assert refused in CONSENT

    def test_a_non_interactive_run_refuses_rather_than_assuming(self, monkeypatch, capsys):
        """Nobody to ask means no, not yes.

        A cron job or a piped run has no human to consent, and consenting on
        somebody else's behalf is the one answer this must never give.
        """
        from unifi_map.cli import build_parser, cmd_shape

        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        args = build_parser().parse_args(["--cache-dir", "examples/demo", "shape"])
        assert cmd_shape(args) == 2
        assert "counts" in capsys.readouterr().err

    def test_declining_produces_nothing(self, monkeypatch, capsys):
        from unifi_map.cli import build_parser, cmd_shape

        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda *_: "n")
        args = build_parser().parse_args(["--cache-dir", "examples/demo", "shape"])
        assert cmd_shape(args) == 2
        assert "SCALE" not in capsys.readouterr().out

    @pytest.mark.parametrize("answer", ["y", "yes", "Y", "  YES  "])
    def test_accepting_produces_the_report(self, monkeypatch, capsys, answer):
        from unifi_map.cli import build_parser, cmd_shape

        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda *_: answer)
        args = build_parser().parse_args(["--cache-dir", "examples/demo", "shape"])
        assert cmd_shape(args) == 0
        assert "SCALE" in capsys.readouterr().out

    def test_yes_skips_the_prompt_entirely(self, monkeypatch, capsys):
        from unifi_map.cli import build_parser, cmd_shape

        def refuse(*_):
            raise AssertionError("--yes should not prompt")

        monkeypatch.setattr("builtins.input", refuse)
        args = build_parser().parse_args(["--cache-dir", "examples/demo", "shape", "--yes"])
        assert cmd_shape(args) == 0
        assert "SCALE" in capsys.readouterr().out


class TestSupportFileStats:
    """The archive numbers are the ones nobody here can guess.

    All four support-file limits were set from a single 154 MiB archive, and
    multi-site handling has never seen a second site. These lines exist so that
    somebody else's archive can answer both without sending it.
    """

    def _archive(self, tmp_path, sites: int = 1):
        import json

        from .test_support import _default_members, _devices, _write_archive

        members = _default_members()
        devices = _devices()
        for n in range(1, sites):
            devices.append(
                {f"site-{n}": [dict(devices[0]["default"][0], mac=f"aa:bb:cc:00:00:{n:02d}")]}
            )
        members["unifi/devices.json"] = json.dumps(devices).encode()
        path = tmp_path / "s.tgz"
        _write_archive(path, members)
        return path

    def test_the_stats_are_collected(self, tmp_path):
        from unifi_map.support import load_support_file

        stats: dict[str, int] = {}
        load_support_file(self._archive(tmp_path), stats=stats)
        assert stats["archive_entries"] > 0
        assert stats["archive_bytes"] > 0
        assert stats["members_found"] >= 2
        assert stats["sites_seen"] == 1

    def test_sites_are_counted_not_named(self, tmp_path):
        """The count is the whole point, and the names are the whole danger."""
        from unifi_map.support import load_support_file

        stats: dict[str, int] = {}
        load_support_file(self._archive(tmp_path, sites=3), site="default", stats=stats)
        assert stats["sites_seen"] == 3
        assert all(isinstance(v, int) for v in stats.values()), "a name reached the stats"

    def test_the_report_shows_them(self, snapshot):
        from unifi_map.model import build_topology

        extras = Extras(
            source="support file",
            sites_seen=3,
            archive_bytes=1234,
            archive_entries=99,
            members_found=7,
        )
        report = build_report(build_topology(snapshot), snapshot.payloads, extras)
        assert "sites in source     3" in report
        assert "1,234 bytes" in report
        assert "members read        7 of 7" in report


class TestTheNewSections:
    def test_depth_counts_the_longest_chain(self):
        from unifi_map.model import Edge, Kind, Node, Topology
        from unifi_map.report import _depth

        topo = Topology()
        for name in "abcd":
            topo.add(Node(id=name, label=name, kind=Kind.SWITCH))
        topo.edges += [Edge(src="b", dst="a"), Edge(src="c", dst="b"), Edge(src="d", dst="c")]
        assert _depth(topo) == 3

    def test_depth_terminates_on_a_cycle(self):
        # Overrides refuse cycles, but _depth must not hang if one reaches it.
        from unifi_map.model import Edge, Kind, Node, Topology
        from unifi_map.report import _depth

        topo = Topology()
        for name in "ab":
            topo.add(Node(id=name, label=name, kind=Kind.SWITCH))
        topo.edges += [Edge(src="a", dst="b"), Edge(src="b", dst="a")]
        assert _depth(topo) <= len(topo.nodes)

    def test_artwork_appears_only_when_measured(self, snapshot):
        from unifi_map.model import build_topology

        topo = build_topology(snapshot)
        assert "ARTWORK" not in build_report(topo, snapshot.payloads)
        extras = Extras(artwork={"device_found": 7, "device_total": 7})
        assert "ARTWORK" in build_report(topo, snapshot.payloads, extras)

    def test_graphviz_version_is_reported_or_said_missing(self, snapshot):
        from unifi_map.model import build_topology

        topo = build_topology(snapshot)
        assert "not found" in build_report(topo, snapshot.payloads)
        extras = Extras(graphviz_version="2.43.0")
        assert "2.43.0" in build_report(topo, snapshot.payloads, extras)


class TestOverridesCheck:
    def test_a_clean_file_passes(self):
        from unifi_map.cli import build_parser, cmd_overrides

        args = build_parser().parse_args(
            [
                "--cache-dir",
                "examples/demo",
                "overrides",
                "check",
                "--overrides",
                "examples/demo/overrides.toml",
            ]
        )
        assert cmd_overrides(args) == 0

    def test_a_selector_matching_nothing_fails(self, tmp_path):
        """Overrides fail loudly by design; this is how you find out cheaply."""
        from unifi_map.cli import build_parser, cmd_overrides
        from unifi_map.overrides import OverrideError

        bad = tmp_path / "bad.toml"
        bad.write_text('[[node]]\nmatch = "no-such-device"\nname = "x"\n')
        args = build_parser().parse_args(
            ["--cache-dir", "examples/demo", "overrides", "check", "--overrides", str(bad)]
        )
        with pytest.raises(OverrideError, match="matches nothing"):
            cmd_overrides(args)

    def test_no_file_at_all_is_an_error_not_a_pass(self, tmp_path, monkeypatch):
        # Silently passing when there is nothing to check would be the worst
        # outcome: a green check that verified nothing.
        from unifi_map.cli import build_parser, cmd_overrides

        monkeypatch.chdir(tmp_path)
        args = build_parser().parse_args(["--cache-dir", str(Path.cwd()), "overrides", "check"])
        assert cmd_overrides(args) == 2


class TestOverridesGenerate:
    """KAN-120: `unifi-map overrides generate` prints a commented skeleton."""

    def test_it_prints_a_commented_skeleton_to_stdout(self, tmp_path, capsys):
        from unifi_map.cli import build_parser, cmd_overrides

        # A warm asset cache, so this test exercises the ordinary path rather
        # than the cold-cache NOTE (covered separately below) and is not at
        # the mercy of whatever cache/assets/ happens to hold on the machine
        # running it -- it previously read the real default cache path and
        # only ever passed here because of a stale local catalogue file left
        # over from manual testing; a clean checkout or CI would fail it.
        asset_cache = tmp_path / "warm-cache"
        asset_cache.mkdir()
        (asset_cache / "ui-device-catalog.json").write_text("{}", encoding="utf-8")
        args = build_parser().parse_args(
            [
                "--cache-dir",
                "examples/demo",
                "--asset-cache",
                str(asset_cache),
                "overrides",
                "generate",
            ]
        )
        assert cmd_overrides(args) == 0
        out, _err = capsys.readouterr()
        # The demo dataset ships an unplaceable client on purpose.
        assert "[[link]]" in out
        assert 'to = ""' in out
        # Every candidate line is commented out, so the file is inert as-is.
        for line in out.splitlines():
            if line.strip():
                assert line.startswith("#"), f"uncommented line in the skeleton: {line!r}"
        # Log noise (artwork resolution) must not land in the printed file.
        assert "Artwork" not in out

    def test_no_overrides_file_is_needed(self, tmp_path, monkeypatch):
        """Unlike `check`, `generate` never reads an overrides file at all, so
        an empty directory with no overrides.toml anywhere near it is fine."""
        from unifi_map.cli import build_parser, cmd_overrides

        demo = (Path.cwd() / "examples" / "demo").resolve()
        monkeypatch.chdir(tmp_path)
        args = build_parser().parse_args(["--cache-dir", str(demo), "overrides", "generate"])
        assert cmd_overrides(args) == 0

    def test_a_cold_asset_cache_gets_a_note_not_silence(self, tmp_path, capsys):
        """This command never fetches, so on a cold cache the ambiguous-artwork
        check did not merely find nothing, it never ran -- and that has to be
        said, not left to read as a clean bill of health."""
        from unifi_map.cli import build_parser, cmd_overrides

        args = build_parser().parse_args(
            [
                "--cache-dir",
                "examples/demo",
                "--asset-cache",
                str(tmp_path / "empty-cache"),
                "overrides",
                "generate",
            ]
        )
        assert cmd_overrides(args) == 0
        out, _err = capsys.readouterr()
        assert "NOTE" in out
        assert "catalogue is not cached" in out

    def test_a_warm_asset_cache_gets_no_note(self, tmp_path, capsys):
        from unifi_map.cli import build_parser, cmd_overrides

        asset_cache = tmp_path / "warm-cache"
        asset_cache.mkdir()
        (asset_cache / "ui-device-catalog.json").write_text("{}", encoding="utf-8")
        args = build_parser().parse_args(
            [
                "--cache-dir",
                "examples/demo",
                "--asset-cache",
                str(asset_cache),
                "overrides",
                "generate",
            ]
        )
        assert cmd_overrides(args) == 0
        out, _err = capsys.readouterr()
        assert "NOTE" not in out


class TestArtworkCountsSayWhatTheyMeasure:
    """`0 of 19` means something different with a cold cache than a warm one.

    The section exists so somebody else's network can tell us how well the
    fingerprint joins work. Resolved against an empty asset cache it reports
    zero for every network, which would read as "these joins fail here" when it
    means "nothing has been fetched yet". Same snapshot, opposite conclusion.
    """

    def _report(self, snapshot, **artwork):
        from unifi_map.model import build_topology

        base = {"device_found": 0, "device_total": 7, "client_total": 19, "client_found": 0}
        return build_report(
            build_topology(snapshot), snapshot.payloads, Extras(artwork={**base, **artwork})
        )

    def test_a_cold_cache_is_called_out(self, snapshot):
        report = self._report(snapshot, catalogue_cached=False, font_cached=False)
        assert "count the cache and not the network" in report

    def test_a_missing_font_alone_is_called_out(self, snapshot):
        # Product artwork comes from a CDN, glyphs only from a controller, so
        # this is the ordinary case for anybody without an API key.
        report = self._report(snapshot, catalogue_cached=True, font_cached=False)
        assert "generic glyph count is always 0" in report

    def test_a_warm_cache_says_nothing(self, snapshot):
        report = self._report(snapshot, catalogue_cached=True, font_cached=True)
        assert "NOTE:" not in report


class TestRepeatedFormatsFlagIsRefused:
    """`-f` is `nargs="+"`, so a repeat overwrote rather than appended.

    `-f svg -f png` wrote png only and said nothing, which reads as a format
    that failed to render. Both spellings look equally reasonable to somebody
    who has not read the flag table.

    Refused rather than appended: an error states what happened, whereas
    appending would quietly change what an existing invocation produces.
    """

    def _parse(self, argv):
        from unifi_map.cli import build_parser

        return build_parser().parse_args(argv)

    def test_formats_given_together_are_kept(self):
        assert self._parse(["render", "-f", "svg", "png"]).formats == ["svg", "png"]

    def test_the_default_is_unchanged(self):
        assert self._parse(["render"]).formats == ["svg", "drawio"]

    def test_a_repeat_is_refused(self):
        import pytest

        with pytest.raises(SystemExit):
            self._parse(["render", "-f", "svg", "-f", "png"])

    def test_the_long_spelling_is_refused_too(self):
        import pytest

        with pytest.raises(SystemExit):
            self._parse(["render", "--formats", "svg", "--formats", "png"])

    def test_the_bookkeeping_marker_does_not_survive_parsing(self):
        """It lives on the namespace during parsing and is not a parsed value."""
        args = self._parse(["render", "-f", "svg"])
        assert not hasattr(args, "_formats_given")
