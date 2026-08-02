"""Reading `build_parser()`, for the two things generated from it.

The README's flag table and the man page describe the same parser and were
going to walk it twice. Two walks drift: one learns that a shared option is
attached to every subparser and the other does not, and the documents disagree
without either being obviously wrong.

Nothing here is imported by the package itself. It exists so the generators
agree, and lives beside them rather than in `src/` for that reason.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from unifi_map.cli import GLOBAL_DEFAULTS, _bytes_arg, build_parser  # noqa: E402

# Accepted, deliberately undocumented: advertising a deprecated spelling teaches
# it to people who do not know it yet.
SKIP = {"--support-site", "--help"}


@dataclass(frozen=True)
class Option:
    """One flag, as both generators want to render it."""

    # A tuple, so Option stays hashable: command_groups() groups on it.
    names: tuple[str, ...]
    argument: str
    help: str
    default: str

    @property
    def key(self) -> str:
        """Stable identity, for telling shared options from per-command ones."""
        return self.names[-1]


def _default_for(action: argparse.Action) -> str:
    """A default a person would recognise, or empty.

    Raw repr is worse than nothing here: `67108864` for a size written as 64M
    everywhere else, `['svg', 'drawio']` for what is typed `svg drawio`.
    """
    value = action.default
    if value is argparse.SUPPRESS:
        # Shared options suppress so subparsers cannot clobber a value given
        # before the subcommand; their real defaults live in GLOBAL_DEFAULTS.
        value = GLOBAL_DEFAULTS.get(action.dest)
    if value is None or value is argparse.SUPPRESS or isinstance(value, bool):
        # A store_true's False is just "off", and a store_false's True describes
        # the behaviour rather than the flag. Neither tells a reader anything.
        return ""
    if action.type is _bytes_arg and isinstance(value, int):
        for unit, scale in (("G", 1024**3), ("M", 1024**2), ("K", 1024)):
            if value >= scale and value % scale == 0:
                return f"{value // scale}{unit}"
    if isinstance(value, (list, tuple)):
        return " ".join(str(v) for v in value)
    return str(value)


def positionals(parser: argparse.ArgumentParser) -> list[Option]:
    """Arguments with no leading dash, which `options()` cannot see.

    `unifi-map overrides check` needs `check`, and a reference built only from
    `option_strings` documented the flags beside it while never mentioning the
    word you have to type.
    """
    found = []
    for action in parser._actions:
        if action.option_strings or isinstance(action, argparse._SubParsersAction):
            continue
        if action.help is argparse.SUPPRESS or not action.help:
            continue
        choices = ""
        if action.choices:
            choices = "{" + ",".join(str(c) for c in action.choices) + "}"
        found.append(
            Option(
                names=(str(action.dest),),
                argument=choices,
                help=" ".join(str(action.help).split()),
                default="",
            )
        )
    return found


def options(parser: argparse.ArgumentParser) -> list[Option]:
    found = []
    for action in parser._actions:
        long = [o for o in action.option_strings if o.startswith("--")]
        short = [o for o in action.option_strings if not o.startswith("--")]
        if not long or long[0] in SKIP:
            continue
        if action.help is argparse.SUPPRESS or not action.help:
            continue

        argument = ""
        if action.metavar:
            argument = str(action.metavar)
        elif action.choices:
            argument = "{" + ",".join(str(c) for c in action.choices) + "}"

        found.append(
            Option(
                names=tuple(short + long),
                argument=argument,
                help=" ".join(str(action.help).split()),
                default=_default_for(action),
            )
        )
    return found


def subcommands(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    return dict(action.choices)


def command_groups(parser: argparse.ArgumentParser) -> list[tuple[list[str], list[Option]]]:
    """Subcommands grouped by the options unique to them.

    `render` and `all` share every option, so describing both separately prints
    the same seventeen entries twice.
    """
    shared = {o.key for o in options(parser)}
    grouped: dict[tuple, list[str]] = {}
    for name, sub in subcommands(parser).items():
        unique = tuple(o for o in options(sub) if o.key not in shared)
        grouped.setdefault(unique, []).append(name)
    return [(names, list(unique)) for unique, names in grouped.items()]


def release_date(version: str) -> str:
    """The date the changelog gives for *version*.

    Taken from the changelog rather than from the clock, so regenerating does
    not rewrite the file and trip the staleness check on a day nothing changed.
    """
    import re

    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(rf"^## {re.escape(version)} - (\d{{4}}-\d{{2}}-\d{{2}})$", text, re.M)
    return match.group(1) if match else ""


__all__ = [
    "Option",
    "build_parser",
    "command_groups",
    "options",
    "positionals",
    "release_date",
    "subcommands",
]
