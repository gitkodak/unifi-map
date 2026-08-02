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
        "cached snapshot support file live fetch",
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

    def test_a_hostile_field_name_is_counted_rather_than_printed(self):
        """A key that is not shaped like a field name is never echoed.

        Field names are reported so an unfamiliar controller version is
        visible. That is only safe while a *value* cannot arrive disguised as a
        key, so anything failing the shape filter is counted instead.
        """
        from unifi_map.report import _field_report

        secret = "Jasons iPhone 14 Pro"
        lines = "\n".join(_field_report("device", [{"mac": "x", secret: 1}]))
        assert secret not in lines
        assert "not schema-shaped" in lines

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
        from unifi_map.cli import build_parser, cmd_report

        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        args = build_parser().parse_args(["--cache-dir", "examples/demo", "report"])
        assert cmd_report(args) == 2
        assert "counts" in capsys.readouterr().err

    def test_declining_produces_nothing(self, monkeypatch, capsys):
        from unifi_map.cli import build_parser, cmd_report

        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda *_: "n")
        args = build_parser().parse_args(["--cache-dir", "examples/demo", "report"])
        assert cmd_report(args) == 2
        assert "SCALE" not in capsys.readouterr().out

    @pytest.mark.parametrize("answer", ["y", "yes", "Y", "  YES  "])
    def test_accepting_produces_the_report(self, monkeypatch, capsys, answer):
        from unifi_map.cli import build_parser, cmd_report

        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda *_: answer)
        args = build_parser().parse_args(["--cache-dir", "examples/demo", "report"])
        assert cmd_report(args) == 0
        assert "SCALE" in capsys.readouterr().out

    def test_yes_skips_the_prompt_entirely(self, monkeypatch, capsys):
        from unifi_map.cli import build_parser, cmd_report

        def refuse(*_):
            raise AssertionError("--yes should not prompt")

        monkeypatch.setattr("builtins.input", refuse)
        args = build_parser().parse_args(["--cache-dir", "examples/demo", "report", "--yes"])
        assert cmd_report(args) == 0
        assert "SCALE" in capsys.readouterr().out
