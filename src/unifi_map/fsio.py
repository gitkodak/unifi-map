"""Filesystem writes that survive an interrupt, in one place.

Three modules grew their own copy of write-to-temp-then-rename, and they had
drifted: snapshots and rendered output fsync before the rename, the asset cache
did not, and only two of the three set the mode before putting the file in
place. None of that was deliberate, and a reader had no way to tell which
version was the intended one.

Two rules the callers rely on:

**The temporary file lives in the destination directory.** `os.replace` is only
atomic within a filesystem, so a temporary in `/tmp` would silently become a
copy-then-delete across a mount boundary, which is the exact failure mode this
is meant to prevent.

**The mode is set before the rename, not after.** Setting it afterwards leaves a
window at whatever the umask allows, and on an existing file it leaves the old
permissions in force for the whole write. That matters here because a snapshot
is a full inventory of somebody's network.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)


def atomic_write(path: Path, data: bytes | str, *, mode: int = 0o600, fsync: bool = True) -> None:
    """Write *data* to *path* via a temporary file in the same directory.

    An interrupt, a full disk or a crash leaves the previous file intact rather
    than a truncated one.

    `fsync` forces the bytes to disk before the rename. It is on by default,
    which is right for anything a later run depends on, and worth turning off
    only for a cache that can simply be refetched.
    """
    payload = data.encode("utf-8") if isinstance(data, str) else data
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as handle:
            tmp = Path(handle.name)
            handle.write(payload)
            handle.flush()
            if fsync:
                os.fsync(handle.fileno())
        # Before the rename, so the file is never briefly world-readable.
        os.chmod(tmp, mode)
        os.replace(tmp, path)
        tmp = None
    finally:
        if tmp is not None and tmp.exists():
            tmp.unlink(missing_ok=True)


def mkdir_private(directory: Path) -> None:
    """Create *directory*, restricting every level this call creates.

    Only what we create is touched. Somebody who points `--out-dir` at an
    existing shared directory has made a choice, and silently taking it from
    0775 to 0700 locks their collaborators out of it.

    Every level matters, not just the last. `mkdir(parents=True)` on
    `out/private/maps` creates three directories and previously restricted one,
    leaving the other two at the umask default. The filenames inside are derived
    from network names, so a listable parent discloses the network layout even
    though the files themselves are 0600.
    """
    missing: list[Path] = []
    probe = directory
    while not probe.exists():
        missing.append(probe)
        if probe.parent == probe:
            break
        probe = probe.parent

    if not missing:
        return

    try:
        # Top-down, each level created 0700 rather than created at the umask
        # default and tightened a moment later. The old order left a window in
        # which a directory whose filenames are derived from network names was
        # world-readable. `mkdir(mode=...)` is still subject to the umask, which
        # can only clear bits, so the chmod below stays as the backstop.
        for level in reversed(missing):
            level.mkdir(mode=0o700)
    except FileExistsError:
        # Created by somebody else between the check and here. Not ours, so not
        # ours to tighten.
        return
    except OSError:
        # Let the caller's own write fail with something more informative.
        log.debug("Could not create %s", directory, exc_info=True)
        return

    for created in missing:
        try:
            created.chmod(0o700)
        except OSError:
            # A mount without POSIX modes is not a reason to fail the run.
            log.debug("Could not restrict %s", created, exc_info=True)
