#!/usr/bin/env python3
"""Regenerate the flag reference at the bottom of `README.md`.

The flags are introduced throughout the README, next to whatever they are for,
which is the right place to explain one and a poor place to look one up. This
adds the lookup table without duplicating the explanations.

Generated rather than written, for the same reason the man page will be: two
copies of a help string means one of them is wrong, and nothing would fail. The
source of truth is `build_parser()` in `cli.py`, so a flag added there appears
here and cannot be forgotten.

`make docs` rewrites the section; `make check` fails if it is stale, which is
the pattern that keeps it honest. Everything between the markers is replaced, so
do not hand-edit it: change the `help=` text in `cli.py` instead.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"

BEGIN = "<!-- BEGIN GENERATED FLAGS -->"
END = "<!-- END GENERATED FLAGS -->"

sys.path.insert(0, str(ROOT / "src"))

from unifi_map.cli import GLOBAL_DEFAULTS, _bytes_arg, build_parser  # noqa: E402

# Flags whose help text is deliberately hidden from `--help`, and why. Listing
# them anyway would advertise what the CLI is trying to retire.
SKIP = {"--support-site"}

# `--help` says nothing a reader of this table does not already know.
SKIP_ALWAYS = {"--help"}


def _cell(text: str) -> str:
    """Markdown-safe table cell: no raw pipes, no newlines."""
    return " ".join(text.split()).replace("|", r"\|")


def _rows(parser: argparse.ArgumentParser) -> list[tuple[str, str, str]]:
    rows = []
    for action in parser._actions:
        options = [o for o in action.option_strings if o.startswith("--")]
        short = [o for o in action.option_strings if not o.startswith("--")]
        if not options or options[0] in SKIP or options[0] in SKIP_ALWAYS:
            continue
        if action.help is argparse.SUPPRESS or not action.help:
            continue
        name = ", ".join(f"`{o}`" for o in short + options)
        if action.metavar:
            name += f" `{action.metavar}`"
        elif action.choices:
            # Escaped: a raw pipe ends the table cell and silently mangles the row.
            name += " `" + r"\|".join(str(c) for c in action.choices) + "`"

        # Shared options carry SUPPRESS so the subparsers cannot clobber them;
        # their real defaults live in GLOBAL_DEFAULTS.
        value = action.default
        if value is argparse.SUPPRESS:
            value = GLOBAL_DEFAULTS.get(action.dest)
        default = _format_default(action, value)

        rows.append((name, _cell(action.help), default))
    return rows


def _format_default(action: argparse.Action, value: object) -> str:
    """A default a human would recognise, or nothing.

    Raw repr is worse than useless here: `67108864` for a size documented
    everywhere else as 64M, and `['svg', 'drawio']` for what is typed as
    `svg drawio`.
    """
    if value is None or value is argparse.SUPPRESS:
        return ""
    if isinstance(value, bool):
        # A store_true default of False is just "off", and a store_false flag's
        # True describes the behaviour rather than the flag. Neither helps.
        return ""
    if action.type is _bytes_arg and isinstance(value, int):
        for unit, size in (("G", 1024**3), ("M", 1024**2), ("K", 1024)):
            if value >= size and value % size == 0:
                return f"`{value // size}{unit}`"
    if isinstance(value, (list, tuple)):
        return "`" + " ".join(str(v) for v in value) + "`"
    return f"`{value}`"


def _table(rows: list[tuple[str, str, str]]) -> str:
    lines = ["| Flag | What it does | Default |", "| --- | --- | --- |"]
    lines += [f"| {name} | {help_text} | {default} |" for name, help_text, default in rows]
    return "\n".join(lines)


def render() -> str:
    parser = build_parser()
    subparsers = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    # Shared options appear on every subparser too; list them once.
    shared = {name for name, _, _ in _rows(parser)}

    out = [
        BEGIN,
        "",
        "## Flag reference",
        "",
        "Generated from the argument parser by `scripts/generate_cli_docs.py`, so it",
        "cannot drift from `--help`. Each flag is explained in context further up;",
        "this is for looking one up. Run `unifi-map --help` for the same thing in a",
        "terminal.",
        "",
        "```",
        "unifi-map [global options] {fetch,render,all} [command options]",
        "```",
        "",
        "Global options are accepted on either side of the subcommand, so",
        "`unifi-map all --support-file X` and `unifi-map --support-file X all` are",
        "equivalent. Command options must follow the subcommand.",
        "",
        "### Global options",
        "",
        _table(_rows(parser)),
    ]

    # `render` and `all` share every option, so listing both produces the same
    # seventeen rows twice. Group subcommands by the options they actually have.
    groups: dict[tuple, list[str]] = {}
    for name, sub in subparsers.choices.items():
        rows = tuple(row for row in _rows(sub) if row[0] not in shared)
        groups.setdefault(rows, []).append(name)

    for rows, names in groups.items():
        listed = " and ".join(f"`{n}`" for n in names)
        if not rows:
            out += ["", f"{listed} takes only the global options above.", ""]
            continue
        out += ["", f"### {listed} options", "", _table(list(rows))]

    out += ["", END]
    return "\n".join(out)


def main() -> int:
    text = README.read_text(encoding="utf-8")
    section = render()

    if BEGIN in text and END in text:
        pattern = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)
        updated = pattern.sub(lambda _: section, text)
    else:
        updated = text.rstrip("\n") + "\n\n" + section + "\n"

    if updated == text:
        print("README.md flag reference is current.")
        return 0
    README.write_text(updated, encoding="utf-8")
    print("README.md flag reference updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
