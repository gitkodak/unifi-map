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

import json
import re
import sys
from pathlib import Path
from typing import ClassVar

import pytest

from unifi_map.client import Snapshot
from unifi_map.model import build_topology
from unifi_map.render_json import render_json
from unifi_map.render_mermaid import render_mermaid

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
        assert result.devices
        assert result.links
        assert result.hosted
        assert result.nodes


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
    assert start != -1, f"{module.PAGE.name} has no generated flag reference; run `make docs`"
    assert end != -1, f"{module.PAGE.name} has no generated flag reference; run `make docs`"
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


def _introspect():
    """The generators' shared introspection helper, loaded by path.

    `scripts/` is not a package and is not on the path, so this is how the tests
    reach the same code the generators use rather than a second implementation
    that could disagree with it.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "cli_introspect", ROOT / "scripts" / "_cli_introspect.py"
    )
    module = importlib.util.module_from_spec(spec)
    # Registered before executing: the dataclass in there resolves its own
    # annotations through sys.modules, and fails if its module is not there.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_man_page_documents_every_flag():
    """A flag absent from the man page is a flag `man` cannot answer about."""
    module = _introspect()

    parser = module.build_parser()
    expected = {o.names[-1] for o in module.options(parser)}
    for sub in module.subcommands(parser).values():
        expected |= {o.names[-1] for o in module.options(sub)}

    page = (ROOT / "unifi-map.1").read_text(encoding="utf-8")
    # Hyphens are escaped in roff, so compare against the escaped spelling.
    missing = sorted(f for f in expected if f.replace("-", r"\-") not in page)
    assert not missing, f"flags absent from unifi-map.1: {missing}"


def test_both_references_name_every_subcommand_and_positional():
    """The generated references must list what a generated reference implies.

    Not covered by the two staleness checks above, and that gap is the whole
    reason for this test: those regenerate and compare, so a generator carrying
    a hardcoded list passes them forever by producing the same wrong file every
    time. Both generators did. `docs/usage.md` and the man page each printed a
    synopsis reading `{fetch,render,all}` long after `shape` and `overrides`
    shipped, and neither mentioned that `unifi-map overrides` requires `check`,
    because the introspection walked `option_strings` and positionals have none.

    A document that promises it "cannot drift from --help" is worse than a
    hand-written one when it drifts, so the promise gets a test.
    """
    module = _introspect()
    parser = module.build_parser()
    subs = module.subcommands(parser)

    usage = (ROOT / "docs" / "usage.md").read_text(encoding="utf-8")
    page = (ROOT / "unifi-map.1").read_text(encoding="utf-8")

    missing = [n for n in subs if n not in usage]
    assert not missing, f"subcommands absent from docs/usage.md: {missing}"
    missing = [n for n in subs if n not in page]
    assert not missing, f"subcommands absent from unifi-map.1: {missing}"

    for name, sub in subs.items():
        for positional in module.positionals(sub):
            label = positional.names[0]
            assert label in usage, f"{name} positional {label!r} absent from docs/usage.md"
            assert label in page, f"{name} positional {label!r} absent from unifi-map.1"


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


def test_no_release_describes_the_same_subject_twice():
    """Two entries opening on the same thing are usually one change, twice.

    Not a style rule. In 0.7.0 `unifi-map shape` was described in two entries
    written days apart, and in 0.6.0 the two `RELEASING.md` entries actively
    contradicted each other: one said a fix had been claimed and never made,
    the other made that same claim. A reader got both and could not tell which
    was true.

    Genuinely separate changes to one thing are allowed and do happen, so the
    exceptions are listed rather than the rule loosened.
    """
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    # Two distinct improvements to the same flag in one release, not a repeat.
    allowed = {("0.3.0", "--obfuscate")}

    offenders = []
    for match in re.finditer(r"^## (\d+\.\d+\.\d+)", text, re.M):
        body = text[match.end() :]
        following = re.search(r"^## ", body, re.M)
        body = body[: following.start()] if following else body
        subjects = re.findall(r"^- `([^`]+)`", body, re.M)
        for subject in set(subjects):
            if subjects.count(subject) > 1 and (match.group(1), subject) not in allowed:
                offenders.append(f"{match.group(1)}: {subject}")
    assert not offenders, f"one change described more than once: {sorted(offenders)}"


def _fenced(path: Path, language: str) -> list[str]:
    """Every fenced block of *language* in *path*, fence-aware.

    Line-based rather than a regex over the whole file: a `#` heading inside a
    shell block already fooled one regex here into extracting the wrong range.
    """
    out, current = [], None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            tag = line[3:].strip()
            if current is None and tag == language:
                current = []
            elif current is not None:
                out.append("\n".join(current) + "\n")
                current = None
            continue
        if current is not None:
            current.append(line)
    return out


def test_the_documented_json_example_is_current():
    """The JSON example in `docs/output.md` must be output this tool produces.

    It went stale at 0.6.0 while claiming to show the export, and had lost a
    top-level key the surrounding prose promises. An example of a *stable
    schema* is exactly the thing a reader will copy assumptions from, so it
    gets checked rather than proof-read.
    """
    from unifi_map import __version__

    blocks = _fenced(ROOT / "docs" / "output.md", "json")
    assert blocks, "docs/output.md has no JSON example"
    example = json.loads(blocks[0])

    assert example["generator"] == f"unifi-map {__version__}", (
        "the JSON example names a stale version; regenerate it from real output"
    )

    real = json.loads(
        render_json(
            build_topology(Snapshot.read(ROOT / "examples" / "demo")),
            title="Network map",
        )
    )
    assert set(example) == set(real), (
        "the JSON example's top-level keys differ from real output: "
        f"missing {sorted(set(real) - set(example))}, extra {sorted(set(example) - set(real))}"
    )


def test_the_documented_mermaid_example_is_real_output():
    """The Mermaid block in `docs/output.md` is verbatim, and says so.

    It claimed to be "the shipped demo" while showing a direction and a header
    no documented command produced: the example was TB with no front matter,
    the command beside it emits LR with it. Since the page tells the reader
    exactly which command and which single edit, both are reproduced here.
    """
    blocks = _fenced(ROOT / "docs" / "output.md", "mermaid")
    assert blocks, "docs/output.md has no Mermaid example"

    # `include_offline=False` because the CLI defaults `--show-offline no` while
    # `build_topology` defaults to keeping them: a library should not drop data
    # silently. Without it this test rebuilt a topology the documented command
    # does not produce, and blamed the document.
    topo = build_topology(
        Snapshot.read(ROOT / "examples" / "demo"),
        include_clients=False,
        include_offline=False,
    )
    # `--layout tree` is TB, and the page states the front matter was removed.
    real = render_mermaid(topo, title=None, direction="TB")
    assert blocks[0] == real, "the Mermaid example is not what `--layout tree` produces"


def test_no_document_carries_an_orphaned_generated_marker():
    """A `BEGIN` with no `END` is a generator pointed somewhere it no longer writes.

    `docs/verification.md` ended with a bare `BEGIN GENERATED FLAGS` after the
    split moved the flag reference to `docs/usage.md`, so the file advertised
    generated content it did not contain. Invisible to the staleness checks,
    which only ever look at the file the generator currently targets.
    """
    for path in DOCS:
        text = path.read_text(encoding="utf-8")
        for marker in ("GENERATED FLAGS",):
            # The full comment syntax, not the bare words. The changelog entry
            # for this very fix names the marker in prose, and matching a
            # substring counted that as a marker: a test that fails when a
            # document *mentions* the thing it checks is a test that has to be
            # worked around rather than one that holds.
            begins = text.count(f"<!-- BEGIN {marker} -->")
            ends = text.count(f"<!-- END {marker} -->")
            assert begins == ends, (
                f"{path.name} has {begins} BEGIN and {ends} END for {marker}; "
                "a marker without its pair means generated content is missing"
            )


def test_every_docs_page_links_back_to_the_index():
    """A reader can land on any of these directly and needs a way back.

    Search results and deep links go straight to `docs/whatever.md`, which
    carries no indication that it is one page of a set or where the set is
    listed. Cheap to add and easy to forget on the ninth page, so it is checked
    rather than remembered.
    """
    crumb = "[← Documentation index](../README.md#documentation)"
    missing = [p.name for p in sorted(ROOT.glob("docs/*.md")) if crumb not in p.read_text("utf-8")]
    assert not missing, f"docs pages with no link back to the index: {missing}"


class TestDirectoriesFromTheEnvironment:
    """`UNIFI_CACHE_DIR` and friends, and the order they lose in.

    The motivating case is concrete: a snapshot is a full inventory of a
    network, the default cache is inside the working directory, and for anyone
    working on this tool that directory is a git repository. One such backup sat
    untracked in this repo, one `git add -A` from being published.
    """

    def _parsed(self, argv, env, monkeypatch, tmp_path):
        from unifi_map import config
        from unifi_map.cli import build_parser

        # Isolated from any real credential file, which can set these too.
        # Pointing `UNIFI_MAP_ENV` at a nonexistent file is *not* enough: the
        # search continues past a missing candidate to `./.env` and then
        # `~/.config/unifi-map/env`, so a developer who had actually set
        # `UNIFI_CACHE_DIR` in their own credential file failed this test. The
        # search path itself has to be emptied.
        monkeypatch.setattr(config, "default_env_files", lambda: [])
        for name in ("UNIFI_CACHE_DIR", "UNIFI_ASSET_CACHE", "UNIFI_OUT_DIR"):
            monkeypatch.delenv(name, raising=False)
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        return build_parser().parse_args(argv)

    def test_the_environment_sets_the_cache(self, monkeypatch, tmp_path):
        args = self._parsed(["render"], {"UNIFI_CACHE_DIR": "/tmp/snaps"}, monkeypatch, tmp_path)
        assert args.cache_dir == Path("/tmp/snaps")

    def test_a_flag_beats_the_environment(self, monkeypatch, tmp_path):
        args = self._parsed(
            ["render", "--cache-dir", "/tmp/flag"],
            {"UNIFI_CACHE_DIR": "/tmp/env"},
            monkeypatch,
            tmp_path,
        )
        assert args.cache_dir == Path("/tmp/flag")

    def test_the_default_still_applies_with_neither(self, monkeypatch, tmp_path):
        from unifi_map.cli import DEFAULT_CACHE

        args = self._parsed(["render"], {}, monkeypatch, tmp_path)
        assert args.cache_dir == DEFAULT_CACHE

    def test_a_leading_tilde_is_expanded(self, monkeypatch, tmp_path):
        """`~` is the shell's job and there is no shell here, so an unexpanded
        one would create a directory literally named `~`."""
        args = self._parsed(["render"], {"UNIFI_CACHE_DIR": "~/snaps"}, monkeypatch, tmp_path)
        assert str(args.cache_dir).startswith(str(Path.home()))

    def test_all_three_directories_are_settable(self, monkeypatch, tmp_path):
        args = self._parsed(
            ["render"],
            {
                "UNIFI_CACHE_DIR": "/tmp/a",
                "UNIFI_ASSET_CACHE": "/tmp/b",
                "UNIFI_OUT_DIR": "/tmp/c",
            },
            monkeypatch,
            tmp_path,
        )
        assert (args.cache_dir, args.asset_cache, args.out_dir) == (
            Path("/tmp/a"),
            Path("/tmp/b"),
            Path("/tmp/c"),
        )

    def test_they_can_live_in_the_credential_file(self, monkeypatch, tmp_path):
        """The natural place to put it: the file already kept outside the repo."""
        env_file = tmp_path / "env"
        env_file.write_text("UNIFI_CACHE_DIR=/tmp/from-file\n", encoding="utf-8")
        monkeypatch.delenv("UNIFI_CACHE_DIR", raising=False)
        monkeypatch.setenv("UNIFI_MAP_ENV", str(env_file))

        from unifi_map.cli import build_parser

        args = build_parser().parse_args(["render"])
        assert args.cache_dir == Path("/tmp/from-file")


class TestConfigFileAndEnvironment:
    """`config.toml`, `UNIFI_MAP_*`, and the order they lose in.

    Precedence is flag > environment > config file > default. Environment above
    file is the container case: a config file baked into an image has to be
    overridable with `-e` at deploy time, which does not work the other way
    round.
    """

    def _parsed(self, argv, env=None, config_toml=None, *, monkeypatch, tmp_path):
        from unifi_map.cli import build_parser

        if config_toml is not None:
            path = tmp_path / "config.toml"
            path.write_text(config_toml, encoding="utf-8")
            monkeypatch.setenv("UNIFI_MAP_CONFIG", str(path))
        for name, value in (env or {}).items():
            monkeypatch.setenv(name, value)
        return build_parser().parse_args(argv)

    def test_the_config_file_sets_a_render_preference(self, monkeypatch, tmp_path):
        args = self._parsed(
            ["render"], config_toml='theme = "dark"\n', monkeypatch=monkeypatch, tmp_path=tmp_path
        )
        assert args.theme == "dark"

    def test_a_flag_beats_the_config_file(self, monkeypatch, tmp_path):
        args = self._parsed(
            ["render", "--theme", "light"],
            config_toml='theme = "dark"\n',
            monkeypatch=monkeypatch,
            tmp_path=tmp_path,
        )
        assert args.theme == "light"

    def test_the_environment_beats_the_config_file(self, monkeypatch, tmp_path):
        """The container case: a baked-in file, overridden per deployment."""
        args = self._parsed(
            ["render"],
            env={"UNIFI_MAP_THEME": "light"},
            config_toml='theme = "dark"\n',
            monkeypatch=monkeypatch,
            tmp_path=tmp_path,
        )
        assert args.theme == "light"

    def test_a_flag_beats_the_environment(self, monkeypatch, tmp_path):
        args = self._parsed(
            ["render", "--theme", "dark"],
            env={"UNIFI_MAP_THEME": "light"},
            monkeypatch=monkeypatch,
            tmp_path=tmp_path,
        )
        assert args.theme == "dark"

    def test_the_default_still_applies_with_none_of_them(self, monkeypatch, tmp_path):
        args = self._parsed(["render"], monkeypatch=monkeypatch, tmp_path=tmp_path)
        assert args.theme == "light"
        assert args.layout == "unifi"
        assert args.icons == "unifi"
        assert args.formats == ["svg", "drawio"]

    def test_formats_is_a_list_from_either_source(self, monkeypatch, tmp_path):
        """Space-separated in the environment, matching `-f svg pdf png`; a real
        array in TOML, because TOML has arrays and pretending otherwise would be
        perverse."""
        from_env = self._parsed(
            ["render"],
            env={"UNIFI_MAP_FORMATS": "svg png"},
            monkeypatch=monkeypatch,
            tmp_path=tmp_path,
        )
        assert from_env.formats == ["svg", "png"]

    def test_formats_from_a_toml_array(self, monkeypatch, tmp_path):
        args = self._parsed(
            ["render"],
            config_toml='formats = ["mermaid", "json"]\n',
            monkeypatch=monkeypatch,
            tmp_path=tmp_path,
        )
        assert args.formats == ["mermaid", "json"]

    def test_a_bad_value_is_refused_and_names_its_source(self, monkeypatch, tmp_path, capsys):
        """A value from a file never passes argparse's own `choices` check, so
        without an explicit one a typo would sail through to the renderer."""
        with pytest.raises(SystemExit):
            self._parsed(
                ["render"],
                env={"UNIFI_MAP_THEME": "chartreuse"},
                monkeypatch=monkeypatch,
                tmp_path=tmp_path,
            )
        message = capsys.readouterr().err
        assert "chartreuse" in message
        assert "UNIFI_MAP_THEME" in message

    def test_an_unknown_config_key_is_refused(self, monkeypatch, tmp_path):
        """Loud, like the overrides loader. A silently ignored `them = "dark"`
        is indistinguishable from the setting having no effect."""
        from unifi_map.config import ConfigError, read_config_file

        path = tmp_path / "config.toml"
        path.write_text('them = "dark"\n', encoding="utf-8")
        with pytest.raises(ConfigError) as excinfo:
            read_config_file(path)
        assert "them" in str(excinfo.value)
        assert "theme" in str(excinfo.value)

    def test_the_legacy_directory_names_still_work_and_warn(self, monkeypatch, tmp_path, caplog):
        """Documented in docs/credentials.md and present in real credential
        files, so dropping them outright would break a working setup."""
        with caplog.at_level("WARNING"):
            args = self._parsed(
                ["render"],
                env={"UNIFI_CACHE_DIR": "/tmp/legacy"},
                monkeypatch=monkeypatch,
                tmp_path=tmp_path,
            )
        assert args.cache_dir == Path("/tmp/legacy")
        assert any("UNIFI_MAP_CACHE_DIR" in r.getMessage() for r in caplog.records)

    def test_the_new_name_wins_over_the_legacy_one(self, monkeypatch, tmp_path):
        args = self._parsed(
            ["render"],
            env={"UNIFI_CACHE_DIR": "/tmp/old", "UNIFI_MAP_CACHE_DIR": "/tmp/new"},
            monkeypatch=monkeypatch,
            tmp_path=tmp_path,
        )
        assert args.cache_dir == Path("/tmp/new")

    def test_obfuscate_and_force_are_not_configurable(self):
        """Deliberate. One is a claim that the output is safe to share and the
        other overwrites files; neither should be answerable by ambient state
        that is invisible at the call site."""
        from unifi_map.config import _SETTING_VARS

        assert "obfuscate" not in _SETTING_VARS
        assert "force" not in _SETTING_VARS

    def test_the_source_of_every_injected_setting_is_recorded(self, monkeypatch, tmp_path):
        """What `cmd_render` prints, and the whole answer to "why does it look
        different on your machine"."""
        args = self._parsed(
            ["render", "--layout", "tree"],
            env={"UNIFI_MAP_THEME": "dark"},
            config_toml='icons = "builtin"\n',
            monkeypatch=monkeypatch,
            tmp_path=tmp_path,
        )
        assert "UNIFI_MAP_THEME" in args.setting_sources["theme"]
        assert "config file" in args.setting_sources["icons"]
        # A flag is already visible in the command that was typed.
        assert "layout" not in args.setting_sources


class TestTheDocumentedConfigExamples:
    """Every TOML config block in the docs must be real.

    A config file is the kind of thing people copy verbatim out of a page, so an
    example naming a key that does not exist is worse than no example: the
    loader refuses unknown keys, so a stale one fails the reader's whole run.
    """

    def _config_blocks(self, page: str) -> list[str]:
        text = (ROOT / page).read_text(encoding="utf-8")
        blocks = re.findall(r"```toml\n(.*?)```", text, re.DOTALL)
        # Only the ones that look like a config file, not an overrides file,
        # which shares the language and has entirely different keys.
        return [b for b in blocks if "[[" not in b]

    @pytest.mark.parametrize("page", ["docs/credentials.md", "docs/usage.md"])
    def test_they_parse_and_use_only_real_keys(self, page):
        import tomllib

        from unifi_map.config import _SETTING_VARS

        blocks = self._config_blocks(page)
        assert blocks, f"{page} has no config example; this test is guarding nothing"
        for block in blocks:
            payload = tomllib.loads(block)
            unknown = sorted(set(payload) - set(_SETTING_VARS))
            assert not unknown, f"{page} documents unknown config key(s): {unknown}"

    def test_the_loader_accepts_the_documented_example(self, tmp_path):
        """Parsing is not enough: run it through the real loader, which is what
        rejects an unknown key."""
        from unifi_map.config import read_config_file

        blocks = self._config_blocks("docs/credentials.md")
        path = tmp_path / "config.toml"
        path.write_text("\n".join(blocks), encoding="utf-8")
        assert read_config_file(path)

    def test_every_setting_is_documented(self):
        """A new setting that nobody can discover is not a feature."""
        from unifi_map.config import _SETTING_VARS

        text = (ROOT / "docs/credentials.md").read_text(encoding="utf-8")
        missing = [
            f"{key}/{var}"
            for key, var in _SETTING_VARS.items()
            if var not in text or f"`{key}`" not in text
        ]
        assert not missing, f"settings absent from docs/credentials.md: {missing}"

    def test_the_man_page_lists_them_too(self):
        """`man` is where someone looks when they are offline or in a terminal,
        and its ENVIRONMENT and FILES sections are hand-written, so nothing
        regenerates them when a setting is added."""
        from unifi_map.config import _SETTING_VARS

        page = (ROOT / "unifi-map.1").read_text(encoding="utf-8")
        missing = [var for var in _SETTING_VARS.values() if var not in page]
        assert not missing, f"settings absent from unifi-map.1: {missing}"
        assert "config.toml" in page


class TestBadConfigurationFailsCleanly:
    """A broken config file must not produce a traceback.

    Found by external review of 83f6ab6. Parsing reads the config file, so a
    `ConfigError` escapes from inside `parse_args`, which ran before `main`'s
    try block. These go through `main()` rather than the loader, because the
    loader was already tested and was never where the bug was.

    The friendly message goes through `log.error`, so it is asserted on caplog;
    `parser.error` writes to stderr directly, so that one is asserted on
    capsys. Asserting only "no traceback" would pass whether or not anything
    useful was printed.
    """

    def _run_main(self, argv, toml, monkeypatch, tmp_path):
        from unifi_map.cli import main

        path = tmp_path / "config.toml"
        path.write_text(toml, encoding="utf-8")
        monkeypatch.setenv("UNIFI_MAP_CONFIG", str(path))
        try:
            return main(argv)
        except SystemExit as exc:  # parser.error
            return exc.code

    def test_malformed_toml_is_reported_not_raised(self, monkeypatch, tmp_path, caplog):
        with caplog.at_level("ERROR"):
            code = self._run_main(["shape"], 'theme = "dark\n', monkeypatch, tmp_path)
        assert code == 2
        assert any("Configuration error" in r.getMessage() for r in caplog.records)
        assert any("not valid TOML" in r.getMessage() for r in caplog.records)

    def test_an_unknown_key_is_reported_not_raised(self, monkeypatch, tmp_path, caplog):
        with caplog.at_level("ERROR"):
            code = self._run_main(["shape"], 'them = "dark"\n', monkeypatch, tmp_path)
        assert code == 2
        assert any("unknown key(s) 'them'" in r.getMessage() for r in caplog.records)

    def test_it_raises_nothing_out_of_main(self, monkeypatch, tmp_path, caplog):
        """The defect was an uncaught exception, so the return is the assertion:
        reaching this line at all means nothing propagated."""
        with caplog.at_level("ERROR"):
            code = self._run_main(["shape"], "= broken\n", monkeypatch, tmp_path)
        assert code == 2
        assert caplog.records, "failed silently, which is worse than a traceback"

    def test_an_empty_format_list_is_refused(self, monkeypatch, tmp_path, capsys):
        """`-f` is nargs="+" so argparse refuses an empty list on the command
        line. Via a config file it used to pass validation, do all the work,
        print "Full map:" with nothing under it, write nothing and exit 0."""
        code = self._run_main(["render"], "formats = []\n", monkeypatch, tmp_path)
        assert code == 2
        err = capsys.readouterr().err
        assert "is empty" in err
        assert "config file" in err

    def test_a_populated_format_list_still_works(self, monkeypatch, tmp_path):
        """The guard must not reject the ordinary case."""
        from unifi_map.cli import build_parser

        path = tmp_path / "config.toml"
        path.write_text('formats = ["svg"]\n', encoding="utf-8")
        monkeypatch.setenv("UNIFI_MAP_CONFIG", str(path))
        assert build_parser().parse_args(["render"]).formats == ["svg"]
