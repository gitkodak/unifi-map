"""ClusterFuzzLite harness for support.py's archive parser.

Feeds candidate bytes through `load_support_file`, the same entry point
`--support-file` uses. A support file is attacker-supplied by this project's
own threat model (see CLAUDE.md's "Support files are attacker-supplied"
section), so this is the one parser that already assumes hostile input; the
harness exists to find the cases the handwritten adversarial tests in
tests/test_support.py did not think of, not to duplicate them.

`load_support_file` takes a path rather than a file object -- it opens the
archive itself via `tarfile.open(path, "r|gz")` -- so each iteration writes
the candidate bytes to a temporary file rather than fuzzing in memory.
`SupportFileError` is the library's own "this is not a valid archive" signal
and is swallowed; anything else propagating out of a real support-file path
is a bug this harness exists to catch, not something to suppress here.
"""

import contextlib
import sys
import tempfile
from pathlib import Path

import atheris

with atheris.instrument_imports():
    from unifi_map.support import SupportFileError, load_support_file


def TestOneInput(data: bytes) -> None:
    with tempfile.NamedTemporaryFile(suffix=".tgz") as handle:
        handle.write(data)
        handle.flush()
        with contextlib.suppress(SupportFileError):
            load_support_file(Path(handle.name))


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
