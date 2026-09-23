"""Choosing which installed Chrome to drive.

A machine often has more than one Chrome-family browser on it, and which one a
driver picks by default is arbitrary. nodriver, the driver this replaced, took
literally the shortest file path, and on Windows that bites: a per-user install
lands in ``%LOCALAPPDATA%\\Google\\Chrome\\Application`` (64 characters here)
while Chrome Beta installs machine-wide under
``%PROGRAMFILES%\\Google\\Chrome Beta\\Application`` (55), so a user who has both
got Beta driven on their behalf.

That matters for two reasons that pull the same way. The run should happen in
the browser the person actually uses, because that is the one whose profile,
cookies and logged-in sessions the portal already recognises. And the release
channel a visitor is on is itself observable: a beta or canary user-agent string
is a small population, whereas current stable is the overwhelming majority.

So: look in the places Chrome installs to on Windows and macOS, rank what is
there by release channel, stable first, and fall back to discovery order rather
than to path length.
"""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import PurePath, PurePosixPath, PureWindowsPath

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


# Where Chrome's installers put the binary on Windows, relative to each of the
# per-user and machine-wide roots. Stable is listed first in each root, but it is
# the rank, not this order, that decides.
_WINDOWS_ROOT_VARS = ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)")
_WINDOWS_INSTALLS = (
    ("Google", "Chrome", "Application", "chrome.exe"),
    ("Google", "Chrome Beta", "Application", "chrome.exe"),
    ("Google", "Chrome Dev", "Application", "chrome.exe"),
    ("Google", "Chrome SxS", "Application", "chrome.exe"),
    ("Chromium", "Application", "chrome.exe"),
)

# A macOS app is a bundle; the binary sits inside it and is named after the app.
_MAC_APPS = ("Google Chrome", "Google Chrome Beta", "Google Chrome Dev", "Google Chrome Canary", "Chromium")

# Anything else is a Linux desktop, where browsers are on PATH.
_PATH_NAMES = ("google-chrome", "google-chrome-stable", "google-chrome-beta", "chromium", "chromium-browser")


def chrome_candidates(platform: str, env: Mapping[str, str], home: str) -> list[str]:
    """Every place a Chrome-family browser could be installed on this platform."""
    if platform == "win32":
        roots = [env[name] for name in _WINDOWS_ROOT_VARS if env.get(name)]
        return [str(PureWindowsPath(root, *install)) for root in roots for install in _WINDOWS_INSTALLS]
    if platform == "darwin":
        folders: list[PurePath] = [PurePosixPath("/Applications"), PurePosixPath(home, "Applications")]
        return [
            str(folder / f"{app}.app" / "Contents" / "MacOS" / app) for folder in folders for app in _MAC_APPS
        ]
    return []


def discover_chrome_executable(
    *,
    platform: str = sys.platform,
    env: Mapping[str, str] | None = None,
    home: str | None = None,
    exists: Callable[[str], bool] = os.path.isfile,
    which: Callable[[str], str | None] = shutil.which,
) -> str | None:
    """The installed Chrome to drive, or None when none was found.

    None is not an error: the launch then asks the driver for stable Chrome by
    channel name, which is how it behaved before this module chose for it.
    """
    environment = os.environ if env is None else env
    found = [
        candidate
        for candidate in chrome_candidates(platform, environment, home or os.path.expanduser("~"))
        if exists(candidate)
    ]
    if platform not in {"win32", "darwin"}:
        found.extend(path for path in (which(name) for name in _PATH_NAMES) if path)
    return preferred_chrome_executable(found)
