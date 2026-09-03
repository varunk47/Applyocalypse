"""Choosing which installed Chrome to drive.

nodriver finds every Chrome-family binary on the machine and then picks between
them with ``min(rv, key=lambda x: len(x))`` -- literally the shortest file path
(nodriver 0.50.3, ``core/config.py``, comment: "assuming the shortest path
wins"). That is arbitrary, and on Windows it is arbitrary in a way that bites: a
per-user install lands in ``%LOCALAPPDATA%\\Google\\Chrome\\Application`` (64
characters here) while Chrome Beta installs machine-wide under
``%PROGRAMFILES%\\Google\\Chrome Beta\\Application`` (55), so a user who has both
gets Beta driven on their behalf.

That matters for two reasons that pull the same way. The run should happen in
the browser the person actually uses, because that is the one whose profile,
cookies and logged-in sessions the portal already recognises. And the release
channel a visitor is on is itself observable: a beta or canary user-agent string
is a small population, whereas current stable is the overwhelming majority.

So: rank by release channel, stable first, and fall back to discovery order
rather than to path length.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

# Lower rank wins. Ordered by how ordinary the channel is for a real person to be
# browsing in day to day.
_CHANNEL_RANKS: Sequence[tuple[int, tuple[str, ...]]] = (
    (1, ("chrome beta",)),
    (2, ("chrome dev",)),
    (3, ("chrome canary", "chrome sxs")),
    # Chrome for Testing ships with automation defaults and is never somebody's
    # everyday browser, so it is the last thing to fall back to.
    (4, ("chrome for testing", "chrome-for-testing", "chromedriver")),
    (5, ("chromium",)),
)
STABLE_CHANNEL_RANK = 0


def channel_rank(executable_path: str) -> int:
    """How ordinary a browser this path points at. 0 is stable Google Chrome."""
    haystack = executable_path.replace("\\", "/").lower()
    for rank, markers in _CHANNEL_RANKS:
        if any(marker in haystack for marker in markers):
            return rank
    return STABLE_CHANNEL_RANK


def preferred_chrome_executable(candidates: Iterable[str]) -> str | None:
    """The best Chrome to drive, or None when nothing was found.

    Ties keep the order they were discovered in, which is at least deterministic
    and meaningful, unlike sorting on the length of the string.
    """
    ranked = sorted(
        ((channel_rank(candidate), index, candidate) for index, candidate in enumerate(candidates)),
        key=lambda entry: (entry[0], entry[1]),
    )
    return ranked[0][2] if ranked else None


def discover_chrome_executable() -> str | None:
    """Ask nodriver what is installed, then choose between the results ourselves.

    Returns None when nodriver cannot enumerate anything, or when its discovery
    helper has moved. Launching with None simply leaves nodriver to find a
    browser the way it always has, so a driver upgrade degrades to the old
    behaviour instead of failing to start a browser at all.
    """
    try:
        from nodriver.core.config import find_chrome_executable  # type: ignore[import-not-found]

        candidates = find_chrome_executable(return_all=True)
    except Exception:
        return None
    if isinstance(candidates, str):
        return candidates
    if not candidates:
        return None
    return preferred_chrome_executable(candidates)
