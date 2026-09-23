from __future__ import annotations

import pytest

from applyocalypse_automation.browser.chrome_discovery import (
    STABLE_CHANNEL_RANK,
    channel_rank,
    chrome_candidates,
    discover_chrome_executable,
    preferred_chrome_executable,
)

STABLE_PER_USER = r"C:\Users\varun\AppData\Local\Google\Chrome\Application\chrome.exe"
STABLE_MACHINE_WIDE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
BETA = r"C:\Program Files\Google\Chrome Beta\Application\chrome.exe"
CANARY = r"C:\Users\varun\AppData\Local\Google\Chrome SxS\Application\chrome.exe"
FOR_TESTING = r"C:\chrome-for-testing\chrome.exe"
LINUX_STABLE = "/usr/bin/google-chrome-stable"

WINDOWS_ENV = {
    "LOCALAPPDATA": r"C:\Users\varun\AppData\Local",
    "PROGRAMFILES": r"C:\Program Files",
    "PROGRAMFILES(X86)": r"C:\Program Files (x86)",
}
MAC_STABLE = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
MAC_CANARY = "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary"
MAC_PER_USER = "/Users/varun/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


@pytest.mark.parametrize(
    ("path", "expected_rank"),
    [
        (STABLE_PER_USER, STABLE_CHANNEL_RANK),
        (STABLE_MACHINE_WIDE, STABLE_CHANNEL_RANK),
        (LINUX_STABLE, STABLE_CHANNEL_RANK),
        (MAC_STABLE, STABLE_CHANNEL_RANK),
        (BETA, 1),
        (r"C:\Program Files\Google\Chrome Dev\Application\chrome.exe", 2),
        (r"C:\Program Files\Google\Chrome Canary\Application\chrome.exe", 3),
        (CANARY, 3),
        (MAC_CANARY, 3),
        (FOR_TESTING, 4),
        ("/usr/bin/chromium-browser", 5),
    ],
)
def test_a_path_is_ranked_by_its_release_channel(path: str, expected_rank: int) -> None:
    assert channel_rank(path) == expected_rank


def test_the_users_real_chrome_wins_even_when_its_path_is_longer() -> None:
    """The regression this module exists for.

    A per-user Chrome install sits under AppData and a machine-wide Chrome Beta
    sits under Program Files, so the stable binary has the longer path. nodriver
    broke that tie with min(rv, key=len) and therefore drove Beta.
    """
    assert len(STABLE_PER_USER) > len(BETA), "the premise of the bug"

    assert preferred_chrome_executable([BETA, STABLE_PER_USER]) == STABLE_PER_USER
    assert preferred_chrome_executable([STABLE_PER_USER, BETA]) == STABLE_PER_USER


def test_a_less_ordinary_channel_is_only_used_when_nothing_better_exists() -> None:
    assert preferred_chrome_executable([FOR_TESTING, CANARY, BETA]) == BETA
    assert preferred_chrome_executable([FOR_TESTING, CANARY]) == CANARY
    assert preferred_chrome_executable([FOR_TESTING]) == FOR_TESTING


def test_two_installs_of_the_same_channel_keep_discovery_order() -> None:
    """Deterministic, and unlike path length it means something."""
    assert (
        preferred_chrome_executable([STABLE_MACHINE_WIDE, STABLE_PER_USER]) == STABLE_MACHINE_WIDE
    )
    assert preferred_chrome_executable([STABLE_PER_USER, STABLE_MACHINE_WIDE]) == STABLE_PER_USER


def test_no_installed_browser_is_not_an_error() -> None:
    assert preferred_chrome_executable([]) is None


def _discover(platform: str, installed: set[str], on_path: dict[str, str] | None = None) -> str | None:
    return discover_chrome_executable(
        platform=platform,
        env=WINDOWS_ENV if platform == "win32" else {},
        home="/Users/varun",
        exists=installed.__contains__,
        which=(on_path or {}).get,
    )


def test_windows_looks_in_the_per_user_and_machine_wide_install_roots() -> None:
    candidates = chrome_candidates("win32", WINDOWS_ENV, "unused")

    assert STABLE_PER_USER in candidates
    assert STABLE_MACHINE_WIDE in candidates
    assert BETA in candidates
    assert CANARY in candidates


def test_windows_picks_stable_over_a_shorter_beta_path() -> None:
    assert _discover("win32", {BETA, STABLE_PER_USER}) == STABLE_PER_USER


def test_windows_skips_roots_the_environment_does_not_define() -> None:
    candidates = chrome_candidates("win32", {"PROGRAMFILES": r"C:\Program Files"}, "unused")

    assert candidates
    assert all(candidate.startswith("C:\\Program Files\\") for candidate in candidates)


def test_macos_looks_inside_the_app_bundles() -> None:
    candidates = chrome_candidates("darwin", {}, "/Users/varun")

    assert MAC_STABLE in candidates
    assert MAC_CANARY in candidates
    assert MAC_PER_USER in candidates


@pytest.mark.parametrize(
    ("installed", "expected"),
    [
        ({MAC_CANARY, MAC_STABLE}, MAC_STABLE),
        ({MAC_CANARY}, MAC_CANARY),
        ({MAC_PER_USER}, MAC_PER_USER),
    ],
)
def test_macos_picks_the_most_ordinary_installed_channel(installed: set[str], expected: str) -> None:
    assert _discover("darwin", installed) == expected


def test_linux_asks_path() -> None:
    on_path = {"chromium": "/usr/bin/chromium", "google-chrome-stable": LINUX_STABLE}

    assert _discover("linux", set(), on_path) == LINUX_STABLE


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
def test_nothing_installed_leaves_the_choice_to_the_launch(platform: str) -> None:
    """None makes the adapter launch by channel name instead of by path."""
    assert _discover(platform, set()) is None
