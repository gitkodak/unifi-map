"""Documentation checks.

Links break silently: renaming a heading does not fail anything, the anchor just
stops resolving and quietly sends the reader to the top of the page. That is the
failure this file exists to catch.

**The documentation is several files, so these checks are too.** When the README
was one long file every link was same-file and `#anchor` was the only shape that
existed. Splitting it turned most of them into `docs/artwork.md#something`, which
is a target in another file and a new way to be wrong. The guards were widened
before the split rather than after, because a split that quietly reduced link
safety would have been a poor trade for a shorter file.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import ClassVar

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Named rather than positional. Several checks are about the README
# specifically, and they used to reach it as DOCS[0], which stopped being true
# the moment the list was sorted.
README = ROOT / "README.md"

# Everything a reader might follow a link into. Discovered rather than listed:
# a new file under docs/ should be checked without anybody remembering to add
# it here, which is the mistake this file exists to prevent elsewhere.
DOCS = sorted(
    [
        ROOT / name
        for name in (
            "README.md",
            "SECURITY.md",
            "CONTRIBUTING.md",
            "CHANGELOG.md",
            "AI_DISCLOSURE.md",
            "HUMAN_INPUT.md",
            "RELEASING.md",
            "TODO.md",
        )
        if (ROOT / name).is_file()
    ]
    + sorted((ROOT / "docs").glob("*.md"))
)

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$", re.M)
# Same-file `#anchor`, and cross-file `path.md` or `path.md#anchor`. Anything
# with a scheme is somebody else's problem.
_LINK = re.compile(r"\]\((?!https?:|mailto:)([^)\s]+)\)")


def _anchor(title: str) -> str:
    """GitHub's slug for a heading: lowercased, punctuation dropped, spaces hyphenated."""
    slug = title.lower().replace("`", "")
    slug = re.sub(r"[^\w\s-]", "", slug)
    return re.sub(r"\s+", "-", slug.strip())


def _anchors(path: Path) -> set[str]:
    return {_anchor(m.group(2)) for m in _HEADING.finditer(path.read_text(encoding="utf-8"))}


@pytest.mark.parametrize("path", DOCS, ids=lambda p: p.name)
def test_every_link_resolves(path: Path):
    """Both shapes: an anchor in this file, and a path to another one.

    A cross-file link can fail two ways a same-file link cannot: the file may
    not exist, and it may exist without the heading. Both are silent in a
    browser, which renders the link and lands the reader somewhere unhelpful.
    """
    broken: list[str] = []
    for target in _LINK.findall(path.read_text(encoding="utf-8")):
        file_part, _, anchor = target.partition("#")

        if not file_part:
            if anchor not in _anchors(path):
                broken.append(f"#{anchor} (no such heading here)")
            continue

        destination = (path.parent / file_part).resolve()
        if not destination.is_file():
            broken.append(f"{target} (no such file)")
        elif destination.suffix == ".md" and anchor and anchor not in _anchors(destination):
            broken.append(f"{target} (file exists, heading does not)")

    assert not broken, f"{path.name} has broken links: {sorted(broken)}"


def test_the_feature_list_is_the_first_section():
    """It exists so nobody has to read the whole file to decide whether to try it.

    Directly below the screenshots and above everything else, which is where it
    was asked to be. Anything that pushes it further down defeats the point.
    """
    lines = README.read_text(encoding="utf-8").splitlines()
    headings = [(i, line) for i, line in enumerate(lines) if line.startswith("## ")]
    assert headings, "README has no sections at all"
    index, first = headings[0]
    assert first == "## Features", f"first section is {first!r}, not the feature list"
    assert index < 60, f"feature list has drifted to line {index}; it should stay above the fold"


# `--help` and `--version` are self-describing; `--formats` and `--verbose` are
# long forms of `-f` and `-v`, both of which the README uses.
_FLAGS_NOT_NEEDING_PROSE = {"--help", "--version", "--formats", "--verbose"}


def _prose() -> str:
    """Every document, with the generated flag table removed.

    The table lists every flag by construction, so leaving it in would make
    `test_every_flag_is_mentioned_in_the_readme` pass no matter what. That test
    is about a flag being *explained*, which only the prose does.

    All of them rather than the README alone: the documentation is several files
    now, and a flag explained in `docs/usage.md` is explained.
    """
    out = []
    for path in DOCS:
        text = path.read_text(encoding="utf-8")
        start = text.find("<!-- BEGIN GENERATED FLAGS -->")
        out.append(text if start == -1 else text[:start])
    return "\n".join(out)


def test_every_flag_is_explained_somewhere():
    """A flag nobody documents is a flag nobody finds.

    Three flags were added in one sitting and none reached the README until a
    drift audit went looking, which is exactly the kind of thing that should not
    depend on somebody remembering.

    Checked against the prose only. The generated reference at the bottom
    contains every flag automatically, so counting it would retire this test
    without anyone noticing.
    """
    import argparse

    from unifi_map.cli import build_parser

    flags: set[str] = set()

    def collect(parser: argparse.ArgumentParser) -> None:
        for action in parser._actions:
            flags.update(o for o in action.option_strings if o.startswith("--"))
            if isinstance(action, argparse._SubParsersAction):
                for sub in action.choices.values():
                    collect(sub)

    collect(build_parser())
    readme = _prose()
    missing = sorted(f for f in flags - _FLAGS_NOT_NEEDING_PROSE if f not in readme)
    assert not missing, f"flags explained in no document: {missing}"


class TestDocumentedCommandsActuallyRun:
    """Every `unifi-map ...` any document prints must parse.

    `test_every_flag_is_mentioned_in_the_readme` checks the docs use the right
    vocabulary; nothing checked the grammar. So all seven documented
    `--support-file` invocations put the flag after the subcommand, argparse
    rejected every one of them, and the feature's entire documented usage was
    unrunnable without a single test noticing.
    """

    # Continuation lines, comments and placeholder paths are stripped; nothing
    # is executed, only parsed.
    _COMMAND = re.compile(r"^\s*(unifi-map .+?)(?:\s+#.*)?$", re.M)

    # A synopsis such as `unifi-map [global options] {fetch,render,all}` is not
    # a command; the brackets and braces are metasyntax, not arguments.
    _SYNOPSIS = re.compile(r"[\[\]{}]")

    def _commands(self) -> list[str]:
        found = []
        for path in DOCS:
            text = path.read_text(encoding="utf-8").replace("\\\n", " ")
            found += [
                m.group(1).strip()
                for m in self._COMMAND.finditer(text)
                if not self._SYNOPSIS.search(m.group(1))
            ]
        assert len(found) > 15, f"only found {len(found)} commands; did the regex rot?"
        return found

    # Redirection and pipes belong to the shell, not to argparse, so a command
    # is only checked up to the first one.
    _SHELL = re.compile(r"\s(?:[|><]|&&|2>&1)")

    def test_every_readme_command_parses(self):
        import shlex

        from unifi_map.cli import build_parser

        broken = []
        for command in self._commands():
            command = self._SHELL.split(command)[0]
            argv = shlex.split(command)[1:]
            try:
                build_parser().parse_args(argv)
            except SystemExit:
                broken.append(command)
        assert not broken, "README commands that do not parse:\n  " + "\n  ".join(broken)


def test_every_output_format_is_documented():
    """Both places a reader meets the format list must name all of them.

    The README answers "what does this produce" in a sentence; `docs/output.md`
    is the reference and its title promises every format. Each fell behind once:
    the README table listed five of seven after mermaid and json were added, and
    the reference page covered two of seven after the split, because it was
    carved from the sections that happened to need prose.
    """
    from unifi_map.cli import ALL_FORMATS

    readme = README.read_text(encoding="utf-8")
    start = readme.index("## Output")
    summary = readme[start : readme.index("\n## ", start + 1)]
    missing = [f for f in ALL_FORMATS if f"`{f}`" not in summary]
    assert not missing, f"formats absent from the README summary: {missing}"

    reference = (ROOT / "docs" / "output.md").read_text(encoding="utf-8")
    missing = [f for f in ALL_FORMATS if f"| `{f}` |" not in reference]
    assert not missing, f"formats absent from the docs/output.md table: {missing}"


class TestEveryOverrideBlockIsDocumented:
    """Each `[[block]]` the loader accepts must appear in both override docs.

    `[[device]]` was implemented, tested, described in `README.md` and
    `CLAUDE.md`, and used in the demo overrides, while `docs/overrides.md` and
    `examples/overrides.toml` never mentioned it. Nothing failed, because
    nothing tied the loader's vocabulary to the documents describing it. An
    external review found it; this finds the next one.
    """

    # The loader reads exactly these top-level tables.
    BLOCKS: ClassVar = ["device", "link", "hosted", "node"]

    def test_the_block_list_still_matches_the_loader(self):
        # Guards the list above: a new block type must fail here rather than
        # silently narrow every assertion below it.
        source = (
            Path(__file__).resolve().parents[1] / "src" / "unifi_map" / "overrides.py"
        ).read_text(encoding="utf-8")
        found = set(re.findall(r'payload\.get\("(\w+)"\)', source))
        assert found == set(self.BLOCKS), f"loader reads {sorted(found)}, list says {self.BLOCKS}"

    @pytest.mark.parametrize("block", BLOCKS)
    def test_the_reference_doc_has_a_section(self, block):
        text = (Path(__file__).resolve().parents[1] / "docs" / "overrides.md").read_text(
            encoding="utf-8"
        )
        assert f"### `[[{block}]]`" in text, f"docs/overrides.md has no [[{block}]] section"

    @pytest.mark.parametrize("block", BLOCKS)
    def test_the_example_file_shows_one(self, block):
        text = (Path(__file__).resolve().parents[1] / "examples" / "overrides.toml").read_text(
            encoding="utf-8"
        )
        assert f"[[{block}]]" in text, f"examples/overrides.toml has no [[{block}]] example"

    def test_the_example_file_actually_parses(self):
        # A template nobody runs is a template that has quietly stopped working.
        from unifi_map.overrides import load

        path = Path(__file__).resolve().parents[1] / "examples" / "overrides.toml"
        result = load(path)
        assert result.devices and result.links and result.hosted and result.nodes


def test_the_generated_flag_reference_is_current():
    """`make docs` must have been run. Same pattern as the metrics docs in the
    sibling exporter repo: generate, then fail if the tree changed.

    Without this the reference rots exactly like a hand-written one, except it
    also *claims* to be generated, which is worse than not having it.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "generate_cli_docs",
        Path(__file__).resolve().parents[1] / "scripts" / "generate_cli_docs.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    text = module.PAGE.read_text(encoding="utf-8")
    start = text.find(module.BEGIN)
    end = text.find(module.END)
    assert start != -1 and end != -1, f"{module.PAGE.name} has no flag reference; run `make docs`"
    assert text[start : end + len(module.END)] == module.render(), (
        f"{module.PAGE.name} flag reference is out of date. Run `make docs`."
    )


def test_the_generated_man_page_is_current():
    """`unifi-map.1` is committed, so it can go stale like any other file.

    Same regenerate-then-compare check as the flag reference. The page is
    committed rather than built on install so a clone has one, which is the
    whole reason it needs guarding.
    """
    import importlib.util

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "generate_manpage", root / "scripts" / "generate_manpage.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    page = root / "unifi-map.1"
    assert page.is_file(), "unifi-map.1 is missing; run `make docs`"
    assert page.read_text(encoding="utf-8") == module.render(), (
        "unifi-map.1 is out of date. Run `make docs`."
    )


def test_the_man_page_header_carries_a_date():
    """`.TH` must have a real date, which the staleness check cannot see.

    The date comes from the changelog entry for the current version, so bumping
    `__version__` before dating that section yields an empty one. The
    regenerate-and-compare test cannot catch it: both sides would be generated
    the same wrong way and agree. This is what makes the release order in
    `RELEASING.md` load-bearing rather than a preference.
    """
    page = (Path(__file__).resolve().parents[1] / "unifi-map.1").read_text(encoding="utf-8")
    header = page.splitlines()[0]
    assert re.search(r'"\d{4}-\d{2}-\d{2}"', header), (
        f"man page has no date; date the CHANGELOG section for this version, then `make docs`. "
        f"Header was: {header}"
    )


def test_the_man_page_documents_every_flag():
    """A flag absent from the man page is a flag `man` cannot answer about."""
    import importlib.util

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "cli_introspect", root / "scripts" / "_cli_introspect.py"
    )
    module = importlib.util.module_from_spec(spec)
    # Registered before executing: the dataclass in there resolves its own
    # annotations through sys.modules, and fails if its module is not there.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    parser = module.build_parser()
    expected = {o.names[-1] for o in module.options(parser)}
    for sub in module.subcommands(parser).values():
        expected |= {o.names[-1] for o in module.options(sub)}

    page = (root / "unifi-map.1").read_text(encoding="utf-8")
    # Hyphens are escaped in roff, so compare against the escaped spelling.
    missing = sorted(f for f in expected if f.replace("-", r"\-") not in page)
    assert not missing, f"flags absent from unifi-map.1: {missing}"


class TestSharedOptionsWorkInEitherPosition:
    """Global options are accepted before *and* after the subcommand.

    `unifi-map all --support-file X` is the form every comparable tool uses and
    the form the README reaches for unprompted, so both are supported. The
    machinery is fragile in a specific way, hence the third test.
    """

    OPTIONS: ClassVar = [
        ("--support-file", "x.tgz", "support_file", "x.tgz"),
        ("--support-max-entries", "7", "support_max_entries", 7),
        ("--support-max-member", "1M", "support_max_member", 1024 * 1024),
        ("--cache-dir", "somewhere", "cache_dir", "somewhere"),
        ("--out-dir", "elsewhere", "out_dir", "elsewhere"),
    ]

    @pytest.mark.parametrize("flag,value,attr,want", OPTIONS, ids=[o[0] for o in OPTIONS])
    def test_before_and_after_the_subcommand_agree(self, flag, value, attr, want):
        from unifi_map.cli import build_parser

        before = build_parser().parse_args([flag, value, "all"])
        after = build_parser().parse_args(["all", flag, value])
        assert str(getattr(before, attr)) == str(want)
        assert str(getattr(after, attr)) == str(want)

    def test_an_option_given_before_the_subcommand_is_not_reset_by_it(self):
        # The failure this guards is silent: the value parses, then the
        # subparser writes its own default over it and the tool runs against
        # the wrong input rather than reporting anything.
        from unifi_map.cli import build_parser

        args = build_parser().parse_args(["--cache-dir", "examples/demo", "render"])
        assert str(args.cache_dir) == "examples/demo"

    def test_no_shared_option_carries_a_real_default(self):
        """They must all use SUPPRESS, or the post-parse fill-in skips them.

        `parents=` shares action *objects* rather than copying them, so a real
        default on one of these is a default on every parser at once, and the
        last one to apply it wins. That is precisely how the first attempt at
        this broke the pre-subcommand form while the tests still passed.
        """
        import argparse

        from unifi_map.cli import GLOBAL_DEFAULTS, build_parser

        parser = build_parser()
        subparsers = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
        leaky = {
            (name, action.dest)
            for name, sub in subparsers.choices.items()
            for action in sub._actions
            if action.dest in GLOBAL_DEFAULTS and action.default is not argparse.SUPPRESS
        }
        assert not leaky, f"shared options with a non-SUPPRESS default: {sorted(leaky)}"

    def test_every_shared_option_has_a_default_to_fall_back_on(self):
        import argparse

        from unifi_map.cli import GLOBAL_DEFAULTS, build_parser

        # `help` and `version` are argparse's own actions; they suppress because
        # they exit rather than because they need a value.
        suppressed = {
            a.dest
            for a in build_parser()._actions
            if a.default is argparse.SUPPRESS and a.dest not in ("help", "version")
        }
        assert suppressed <= set(GLOBAL_DEFAULTS), (
            f"suppressed with no default: {sorted(suppressed - set(GLOBAL_DEFAULTS))}"
        )


def test_the_advertised_test_count_is_true(request):
    """`AI_DISCLOSURE.md` cites a number of tests. Numbers in prose go stale.

    It drifted within an hour of being written, which is the argument for
    checking it rather than trusting it. Skipped when the suite is filtered,
    since the collected count is then meaningless.
    """
    if request.config.option.keyword or request.config.option.markexpr:
        pytest.skip("suite is filtered; collected count is not the total")

    text = (Path(__file__).resolve().parents[1] / "AI_DISCLOSURE.md").read_text(encoding="utf-8")
    match = re.search(r"\*\*(\d+) automated tests\*\*", text)
    assert match, "AI_DISCLOSURE.md no longer states a test count"
    claimed = int(match.group(1))
    actual = request.session.testscollected
    assert claimed == actual, (
        f"AI_DISCLOSURE.md claims {claimed} tests; the suite collects {actual}. Update the number."
    )


def test_the_changelog_documents_the_current_version():
    """A version bump without a changelog entry is the likely release mistake.

    Deliberately not "the newest heading must equal `__version__`": mid-cycle
    the newest heading is `Unreleased` while `__version__` still names the last
    release, which is the correct state. What must always hold is that the
    version the package reports has a section describing it.
    """
    from unifi_map import __version__

    root = Path(__file__).resolve().parents[1]
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    headings = re.findall(r"^## (\d+\.\d+\.\d+)", changelog, re.M)
    assert __version__ in headings, (
        f"__version__ is {__version__} but CHANGELOG.md has no section for it. "
        f"Sections found: {headings}. See RELEASING.md."
    )


def test_no_changelog_section_is_declared_twice():
    """Repeated `### Added` inside one version means entries were misfiled.

    It has happened twice, both times from anchoring an edit on text that
    appears in more than one place, and both times it hid an entry landing in an
    already-released section.
    """
    changelog = (Path(__file__).resolve().parents[1] / "CHANGELOG.md").read_text(encoding="utf-8")
    # Split on version headings, ignoring the preamble before the first one.
    for block in re.split(r"^## ", changelog, flags=re.M)[1:]:
        name = block.splitlines()[0].strip()
        subs = re.findall(r"^### (.+)$", block, re.M)
        assert len(subs) == len(set(subs)), f"section {name!r} repeats a heading: {subs}"
