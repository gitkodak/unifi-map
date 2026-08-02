#!/usr/bin/env python3
"""Regenerate the flag reference at the bottom of `docs/usage.md`.

The flags are introduced throughout the documentation, next to whatever they
are for, which is the right place to explain one and a poor place to look one
up. This adds the lookup table without duplicating the explanations.

Generated rather than written, for the same reason the man page will be: two
copies of a help string means one of them is wrong, and nothing would fail. The
source of truth is `build_parser()` in `cli.py`, so a flag added there appears
here and cannot be forgotten.

`make docs` rewrites the section; `make check` fails if it is stale, which is
the pattern that keeps it honest. Everything between the markers is replaced, so
do not hand-edit it: change the `help=` text in `cli.py` instead.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs" / "usage.md"

BEGIN = "<!-- BEGIN GENERATED FLAGS -->"
END = "<!-- END GENERATED FLAGS -->"

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _cli_introspect import build_parser, command_groups, options  # noqa: E402


def _cell(text: str) -> str:
    """Markdown-safe table cell: no raw pipes, no newlines."""
    return " ".join(text.split()).replace("|", r"\|")


def _rows(items) -> list[tuple[str, str, str]]:
    rows = []
    for option in items:
        name = ", ".join(f"`{n}`" for n in option.names)
        if option.argument:
            # Escaped: a raw pipe ends the table cell and mangles the row.
            name += " `" + option.argument.replace("|", r"\|") + "`"
        rows.append((name, _cell(option.help), f"`{option.default}`" if option.default else ""))
    return rows


def _table(rows: list[tuple[str, str, str]]) -> str:
    lines = ["| Flag | What it does | Default |", "| --- | --- | --- |"]
    lines += [f"| {name} | {help_text} | {default} |" for name, help_text, default in rows]
    return "\n".join(lines)


def render() -> str:
    parser = build_parser()

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
        _table(_rows(options(parser))),
    ]

    for names, unique in command_groups(parser):
        listed = " and ".join(f"`{n}`" for n in names)
        if not unique:
            out += ["", f"{listed} takes only the global options above.", ""]
            continue
        out += ["", f"### {listed} options", "", _table(_rows(unique))]

    out += ["", END]
    return "\n".join(out)


def main() -> int:
    text = PAGE.read_text(encoding="utf-8")
    section = render()

    if BEGIN in text and END in text:
        pattern = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)
        updated = pattern.sub(lambda _: section, text)
    else:
        updated = text.rstrip("\n") + "\n\n" + section + "\n"

    if updated == text:
        print("docs/usage.md flag reference is current.")
        return 0
    PAGE.write_text(updated, encoding="utf-8")
    print("docs/usage.md flag reference updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
