"""The progress spinner.

Every test drives a fake terminal rather than the real one. A `StringIO`
accumulates everything ever written, where a terminal overwrites, so assertions
here are about what was *emitted*: the erase sequences are present, not that the
visible line is blank.
"""

from __future__ import annotations

import io
import logging
import time

import pytest

from unifi_map.progress import SpinnerAwareHandler, enabled_for, spinner

BRAILLE = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class FakeTty(io.StringIO):
    """A stream that claims to be a terminal."""

    encoding = "utf-8"

    def isatty(self) -> bool:
        return True


class NarrowTty(FakeTty):
    """A terminal that cannot encode braille, like a legacy Windows console."""

    encoding = "cp437"


def _frames(text: str) -> int:
    return sum(text.count(f) for f in BRAILLE)


class TestItStaysOutOfTheWayOfAutomation:
    """The spinner must never reach a stream nobody is watching.

    This is what keeps it out of piped output, CI logs and captured test output
    without anyone having to remember `--no-progress`.
    """

    def test_a_plain_stream_is_not_a_terminal(self):
        assert enabled_for(io.StringIO(), requested=True) is False

    def test_a_terminal_is(self):
        assert enabled_for(FakeTty(), requested=True) is True

    def test_the_flag_wins_over_a_terminal(self):
        assert enabled_for(FakeTty(), requested=False) is False

    def test_a_stream_that_cannot_answer_is_treated_as_not_a_terminal(self):
        class Awkward(io.StringIO):
            def isatty(self):
                raise ValueError("closed")

        assert enabled_for(Awkward(), requested=True) is False

    def test_nothing_is_written_when_disabled_even_for_slow_work(self):
        stream = io.StringIO()
        with spinner("Working", True, stream):
            time.sleep(0.25)
        assert stream.getvalue() == ""


class TestItDrawsWhenSomebodyIsWatching:
    def test_a_slow_step_draws_frames(self):
        stream = FakeTty()
        with spinner("Reading archive", True, stream):
            time.sleep(0.35)
        assert _frames(stream.getvalue()) >= 2
        assert "Reading archive" in stream.getvalue()

    def test_a_fast_step_draws_nothing(self):
        # The first frame waits one interval, so instant work does not flash a
        # spinner up and tear it down again. Deliberate: `render` on a small
        # network finishes every step inside that window and stays quiet.
        stream = FakeTty()
        with spinner("Quick", True, stream):
            pass
        assert stream.getvalue() == ""

    def test_the_line_is_erased_on_the_way_out(self):
        stream = FakeTty()
        with spinner("Working", True, stream):
            time.sleep(0.15)
        # Erase is carriage return, blanks, carriage return; the buffer must end
        # on one so a terminal is left with an empty line rather than a frame.
        assert stream.getvalue().endswith("\r")

    def test_an_exception_still_erases(self):
        stream = FakeTty()
        progress = spinner("Boom", True, stream)
        with pytest.raises(ValueError), progress:
            time.sleep(0.15)
            raise ValueError("x")
        assert stream.getvalue().endswith("\r")

    def test_a_terminal_that_cannot_encode_braille_gets_ascii(self):
        stream = NarrowTty()
        with spinner("Working", True, stream):
            time.sleep(0.25)
        text = stream.getvalue()
        assert _frames(text) == 0
        assert any(c in text for c in "|/-\\")


class TestLoggingAndTheSpinnerShareStderr:
    """Both write to the same line, so the handler erases before it emits.

    Without it the two interleave into `⠹ Working...Wrote snapshot`, which looks
    like corruption rather than progress.
    """

    def test_a_log_record_is_not_garbled_by_a_running_spinner(self):
        stream = FakeTty()
        log = logging.getLogger("test_progress")
        log.handlers = [SpinnerAwareHandler(stream)]
        log.setLevel(logging.INFO)
        log.propagate = False
        try:
            with spinner("Working", True, stream):
                time.sleep(0.2)
                log.info("a log line")
                time.sleep(0.2)
        finally:
            log.handlers = []

        # The record must appear on its own, not appended to a spinner frame.
        segments = [s for s in stream.getvalue().split("\r") if "a log line" in s]
        assert segments, "log record never appeared"
        assert all(_frames(s) == 0 for s in segments), f"record collided with a frame: {segments}"

    def test_the_handler_is_harmless_with_no_spinner_running(self):
        stream = FakeTty()
        log = logging.getLogger("test_progress_solo")
        log.handlers = [SpinnerAwareHandler(stream)]
        log.setLevel(logging.INFO)
        log.propagate = False
        try:
            log.info("alone")
        finally:
            log.handlers = []
        assert stream.getvalue().strip() == "alone"


class TestTheFlag:
    def test_no_progress_works_in_either_position(self):
        from unifi_map.cli import build_parser

        assert build_parser().parse_args(["--no-progress", "all"]).progress is False
        assert build_parser().parse_args(["all", "--no-progress"]).progress is False

    def test_progress_is_on_by_default(self):
        from unifi_map.cli import build_parser

        assert build_parser().parse_args(["all"]).progress is True
        assert build_parser().parse_args(["fetch"]).progress is True
