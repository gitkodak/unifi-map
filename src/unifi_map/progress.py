"""A spinner for the parts that take long enough to look like a hang.

Three steps here are slow with nothing to show for it: walking a support
archive, which streams 150 MiB past to read seven files; fetching artwork, which
is a request per device on a cold cache; and Graphviz, which on a large network
thinks for a while before writing anything. A silent terminal during any of them
reads as frozen, and the honest fix is to say what is happening.

Two rules shape everything below.

**It never writes unless a human is watching.** Not a TTY means piped,
redirected or running under a scheduler, so the spinner disables itself without
being asked. `--no-progress` is for the case the check cannot see, such as an
interactive terminal whose output somebody is scraping anyway.

**It never garbles the log.** Both write to stderr, so a log line arriving
mid-spin would interleave with the frame. `SpinnerAwareHandler` erases the
spinner's line before emitting and the spinner redraws on its next tick, which
keeps the two out of each other's way without either knowing about the other.

Deliberately no percentage. None of these steps can report one honestly: the
archive's entry count is unknown until it ends, and Graphviz reports nothing at
all. A bar that advances by guesswork is worse than a spinner that only claims
something is still happening.

This module reads no environment variables, which is why the TTY check is the
whole policy. `config.py` is the only module that touches `os.environ`, and
keeping it that way is what makes a future secrets backend a single-file change.
"""

from __future__ import annotations

import itertools
import logging
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TextIO

# Braille cycles smoothly and is one column wide, but it needs a stream that can
# encode it; a Windows console on a legacy code page cannot. ASCII is the
# fallback rather than a crash, chosen by asking the stream what it supports.
_BRAILLE = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_ASCII = "|/-\\"

# Fast enough to look alive, slow enough that it is not a strobe and costs
# nothing measurable against work taking whole seconds.
_INTERVAL = 0.1

# One lock covering both the spinner's redraw and the log handler's erase, so a
# record can never land between the two escape sequences that move the cursor.
_lock = threading.Lock()
_active: _Spinner | None = None


def _frames(stream: TextIO) -> str:
    encoding = getattr(stream, "encoding", None) or "ascii"
    try:
        _BRAILLE.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return _ASCII
    return _BRAILLE


class _Spinner:
    """One running spinner. Not used directly; see `spinner()`."""

    def __init__(self, message: str, stream: TextIO) -> None:
        self._message = message
        self._stream = stream
        self._frames = itertools.cycle(_frames(stream))
        self._stop = threading.Event()
        self._width = 0
        # Daemon, so an unhandled exception on the main thread cannot leave the
        # process alive spinning at a terminal nobody is reading.
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _write(self, text: str) -> None:
        try:
            self._stream.write(text)
            self._stream.flush()
        except (OSError, ValueError):
            # The terminal went away mid-run. A spinner is decoration; losing it
            # must never take the actual work down with it.
            self._stop.set()

    def erase(self) -> None:
        """Blank the current line. Caller must hold `_lock`."""
        if self._width:
            self._write("\r" + " " * self._width + "\r")
            self._width = 0

    def _draw(self) -> None:
        text = f"{next(self._frames)} {self._message}"
        with _lock:
            if self._stop.is_set():
                return
            # Pad to the previous width so a shorter frame cannot leave debris
            # from a longer one behind it.
            self._write("\r" + text.ljust(self._width))
            self._width = len(text)

    def _run(self) -> None:
        while not self._stop.wait(_INTERVAL):
            self._draw()

    def __enter__(self) -> _Spinner:
        global _active
        with _lock:
            _active = self
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        global _active
        self._stop.set()
        self._thread.join(timeout=1.0)
        with _lock:
            self.erase()
            _active = None


class SpinnerAwareHandler(logging.StreamHandler):
    """A stderr handler that clears the spinner before writing.

    Without this the spinner and the log both own the same line and produce
    something like `⠹ Reading archive...Wrote snapshot to cache/`. The spinner
    redraws on its next tick, so the only cost is that one frame is skipped.
    """

    def emit(self, record: logging.LogRecord) -> None:
        with _lock:
            if _active is not None:
                _active.erase()
            super().emit(record)


def enabled_for(stream: TextIO, requested: bool) -> bool:
    """Whether to actually spin.

    `requested` is the flag; everything else is the stream deciding it is not
    being watched by a person. A file, a pipe or a CI log all fail `isatty()`,
    which is what keeps a spinner out of captured output without anyone having
    to remember to pass `--no-progress`.
    """
    if not requested:
        return False
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        return False


@contextmanager
def spinner(message: str, requested: bool = True, stream: TextIO | None = None) -> Iterator[None]:
    """Show `message` with a spinner until the block exits.

    A no-op when the stream is not a terminal or `requested` is false, so
    callers can wrap a slow step unconditionally rather than testing first.
    """
    stream = stream if stream is not None else sys.stderr
    if not enabled_for(stream, requested):
        yield
        return
    with _Spinner(message, stream):
        yield
