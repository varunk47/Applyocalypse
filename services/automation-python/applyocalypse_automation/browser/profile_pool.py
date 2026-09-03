"""A small pool of persistent Chrome profiles, leased one per run.

Every run currently gets ``runs/{run_id}/browser-profile``, a directory that has
never existed before, so every run arrives at a portal as a browser that has
never been anywhere: no history, no cookies, no cached fonts or scripts, and a
first-visit fingerprint. That is the loudest signal a bot detector gets for
free, and it is also why the person has to sign in to the same job board again
on every single application.

It costs time as well. A cold profile means an empty HTTP cache and an empty
compiled-script cache, so a Workday or Greenhouse single-page app is fetched and
compiled from scratch each run rather than resumed.

The obvious fix, one shared profile directory, does not work: Chrome takes an
exclusive ``SingletonLock`` on a user data directory and a second browser
pointed at the same one either refuses to start or hands the request to the
running instance. So instead there is a small pool, sized to the concurrency cap
(``HARD_MAX_CONCURRENT_APPLICATIONS`` is 3), and a run leases one slot for as
long as it holds a browser open.

The lease is an exclusive lock on a file, taken by the operating system rather
than tracked in a state file, because the worker is not always shut down
politely. Electron kills a stopped run's process tree with ``taskkill /T /F`` on
Windows, and nothing gets to run cleanup code on the way out. An OS file lock is
released by the kernel when the holding process dies, so a killed run frees its
slot immediately and there is no stale-lock table to reap.

When no root is configured, or when every slot is somehow busy, this falls back
to a run-scoped directory. That is exactly the old behaviour, so a run always
gets a browser even if the pool is unavailable.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from pathlib import Path
from typing import IO

# Matches HARD_MAX_CONCURRENT_APPLICATIONS in packages/config. A run holds one
# slot for as long as its browser is open, so the pool only has to be as deep as
# the number of runs allowed to hold a browser at once.
DEFAULT_PROFILE_SLOTS = 3

SLOT_DIRECTORY_TEMPLATE = "slot-{index}"
SLOT_LOCK_TEMPLATE = "slot-{index}.lock"


def slot_directory(root: Path, index: int) -> Path:
    """Where the profile for one slot lives."""
    return root / SLOT_DIRECTORY_TEMPLATE.format(index=index)


def slot_lock_path(root: Path, index: int) -> Path:
    """The lock file for one slot.

    A sibling of the profile rather than a file inside it, so nothing this
    module writes ever appears inside a directory Chrome owns.
    """
    return root / SLOT_LOCK_TEMPLATE.format(index=index)


def _try_acquire(handle: IO[bytes]) -> bool:
    """Take an exclusive, non-blocking lock on an open file. False if held."""
    try:
        import msvcrt  # type: ignore[import-not-found]
    except ImportError:
        import fcntl

        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        return True

    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        return False
    return True


def _release(handle: IO[bytes]) -> None:
    """Drop the lock. Closing the handle would do it too; this is explicit."""
    try:
        import msvcrt  # type: ignore[import-not-found]
    except ImportError:
        import fcntl

        with contextlib.suppress(OSError):
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return

    with contextlib.suppress(OSError):
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


@contextlib.contextmanager
def lease_profile(
    root: Path | None,
    *,
    fallback: Path,
    slots: int = DEFAULT_PROFILE_SLOTS,
) -> Iterator[Path]:
    """Hold one pooled profile directory for the duration of the block.

    Yields ``fallback`` when there is no pool configured or every slot is taken,
    which keeps a run working rather than failing it over a profile directory.
    """
    if root is None or slots < 1:
        yield fallback
        return

    root.mkdir(parents=True, exist_ok=True)
    for index in range(slots):
        lock_path = slot_lock_path(root, index)
        # Opened r+b after touch rather than w+b: truncating would rewrite a file
        # another process currently holds a lock on.
        lock_path.touch(exist_ok=True)
        handle = lock_path.open("r+b")
        if not _try_acquire(handle):
            handle.close()
            continue
        try:
            profile = slot_directory(root, index)
            profile.mkdir(parents=True, exist_ok=True)
            yield profile
        finally:
            _release(handle)
            handle.close()
        return

    yield fallback
