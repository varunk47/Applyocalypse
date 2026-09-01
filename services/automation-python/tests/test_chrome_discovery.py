from __future__ import annotations

import pytest

from applyocalypse_automation.browser.chrome_discovery import (
    STABLE_CHANNEL_RANK,
    channel_rank,
    discover_chrome_executable,
    preferred_chrome_executable,
)

STABLE_PER_USER = r"C:\Users\varun\AppData\Local\Google\Chrome\Application\chrome.exe"
STABLE_MACHINE_WIDE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
BETA = r"C:\Program Files\Google\Chrome Beta\Application\chrome.exe"
CANARY = r"C:\Users\varun\AppData\Local\Google\Chrome SxS\Application\chrome.exe"
FOR_TESTING = r"C:\chrome-for-testing\chrome.exe"
LINUX_STABLE = "/usr/bin/google-chrome-stable"


@pytest.mark.parametrize(
    ("path", "expected_rank"),
    [
        (STABLE_PER_USER, STABLE_CHANNEL_RANK),
        (STABLE_MACHINE_WIDE, STABLE_CHANNEL_RANK),
        (LINUX_STABLE, STABLE_CHANNEL_RANK),
        (BETA, 1),
        (r"C:\Program Files\Google\Chrome Dev\Application\chrome.exe", 2),
        (r"C:\Program Files\Google\Chrome Canary\Application\chrome.exe", 3),
        (CANARY, 3),
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
    breaks that tie with min(rv, key=len) and therefore drives Beta.
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


def test_discovery_falls_back_to_nodriver_rather_than_failing_to_launch() -> None:
    """A driver upgrade that moves or breaks the helper must not stop a run."""
    config = pytest.importorskip("nodriver.core.config")

    def _raise(**_kwargs: object) -> list[str]:
        raise FileNotFoundError("no chrome installed")

    original = config.find_chrome_executable
    config.find_chrome_executable = _raise
    try:
        assert discover_chrome_executable() is None
    finally:
        config.find_chrome_executable = original


def test_discovery_accepts_a_single_path_as_well_as_a_list() -> None:
    """find_chrome_executable returns a bare string unless asked for all of them."""
    config = pytest.importorskip("nodriver.core.config")

    original = config.find_chrome_executable
    config.find_chrome_executable = lambda **_kwargs: STABLE_MACHINE_WIDE
    try:
        assert discover_chrome_executable() == STABLE_MACHINE_WIDE
    finally:
        config.find_chrome_executable = original


def test_discovery_picks_stable_out_of_what_nodriver_enumerates() -> None:
    config = pytest.importorskip("nodriver.core.config")

    original = config.find_chrome_executable
    config.find_chrome_executable = lambda **_kwargs: [BETA, STABLE_PER_USER, CANARY]
    try:
        assert discover_chrome_executable() == STABLE_PER_USER
    finally:
        config.find_chrome_executable = original
