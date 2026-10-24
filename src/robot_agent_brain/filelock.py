"""Advisory file locks and durability hints that work on POSIX and Windows."""
from __future__ import annotations

import os

try:
    import fcntl
except ImportError:
    fcntl = None
    import msvcrt


def lock_exclusive(descriptor: int) -> None:
    """Take a whole-file, non-blocking lock; raise BlockingIOError when another process holds it."""
    if fcntl is not None:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return
    if os.lseek(descriptor, 0, os.SEEK_END) == 0:
        # Locking a zero-byte range is not meaningful here, so give the region one byte.
        os.write(descriptor, b" ")
    os.lseek(descriptor, 0, os.SEEK_SET)
    try:
        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
    except OSError as exc:
        raise BlockingIOError(exc.errno, "file is already locked") from exc


def sync_directory(path) -> None:
    """Persist a rename into its directory; Windows offers no directory handle to flush."""
    if os.name != "posix":
        return
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
