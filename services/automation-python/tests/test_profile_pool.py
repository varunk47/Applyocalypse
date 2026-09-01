from __future__ import annotations

import contextlib
import subprocess
import sys
import time
from pathlib import Path

import pytest

from applyocalypse_automation.browser.profile_pool import (
    DEFAULT_PROFILE_SLOTS,
    lease_profile,
    slot_directory,
    slot_lock_path,
)


def test_the_pool_is_as_deep_as_the_concurrency_cap() -> None:
    """HARD_MAX_CONCURRENT_APPLICATIONS in packages/config. Keep them together."""
    assert DEFAULT_PROFILE_SLOTS == 3


def test_a_lease_yields_a_directory_that_exists(tmp_path: Path) -> None:
    root = tmp_path / "browser-profiles"

    with lease_profile(root, fallback=tmp_path / "unused") as profile:
        assert profile == slot_directory(root, 0)
        assert profile.is_dir()


def test_a_profile_survives_the_run_that_created_it(tmp_path: Path) -> None:
    """The regression this module exists for.

    A run-scoped profile means every application arrives as a browser with no
    cookies, no history and a cold cache. Leasing the same directory back is the
    whole point.
    """
    root = tmp_path / "browser-profiles"

    with lease_profile(root, fallback=tmp_path / "unused") as first:
        (first / "Cookies").write_text("session", encoding="utf-8")

    with lease_profile(root, fallback=tmp_path / "unused") as second:
        assert second == first
        assert (second / "Cookies").read_text(encoding="utf-8") == "session"


def test_concurrent_runs_never_share_a_profile(tmp_path: Path) -> None:
    """Chrome takes an exclusive SingletonLock, so two runs on one directory is
    not merely untidy, the second browser refuses to start."""
    root = tmp_path / "browser-profiles"
    fallback = tmp_path / "unused"

    with lease_profile(root, fallback=fallback) as first:
        with lease_profile(root, fallback=fallback) as second:
            with lease_profile(root, fallback=fallback) as third:
                assert len({first, second, third}) == 3
                assert {first, second, third} == {slot_directory(root, i) for i in range(3)}


def test_a_released_slot_is_handed_to_the_next_run(tmp_path: Path) -> None:
    root = tmp_path / "browser-profiles"
    fallback = tmp_path / "unused"

    with lease_profile(root, fallback=fallback) as first:
        with lease_profile(root, fallback=fallback) as second:
            assert second != first
    # Both released. The next run should be back at the front of the pool.
    with lease_profile(root, fallback=fallback) as third:
        assert third == first


def test_a_run_still_gets_a_browser_when_the_pool_is_full(tmp_path: Path) -> None:
    """Better a cold profile than a run that cannot open a browser at all."""
    root = tmp_path / "browser-profiles"
    fallback = tmp_path / "run-scoped-profile"

    with contextlib.ExitStack() as stack:
        leased = [stack.enter_context(lease_profile(root, fallback=fallback, slots=2)) for _ in range(2)]
        with lease_profile(root, fallback=fallback, slots=2) as overflow:
            assert overflow == fallback
            assert overflow not in leased


@pytest.mark.parametrize("slots", [0, -1])
def test_a_pool_with_no_slots_falls_back(tmp_path: Path, slots: int) -> None:
    fallback = tmp_path / "run-scoped-profile"

    with lease_profile(tmp_path / "browser-profiles", fallback=fallback, slots=slots) as profile:
        assert profile == fallback


def test_no_configured_pool_keeps_the_old_run_scoped_behaviour(tmp_path: Path) -> None:
    fallback = tmp_path / "run-scoped-profile"

    with lease_profile(None, fallback=fallback) as profile:
        assert profile == fallback
    assert not (tmp_path / "browser-profiles").exists()


def test_the_lock_file_sits_beside_the_profile_not_inside_it(tmp_path: Path) -> None:
    """Nothing this module writes should land in a directory Chrome owns."""
    root = tmp_path / "browser-profiles"

    with lease_profile(root, fallback=tmp_path / "unused") as profile:
        assert slot_lock_path(root, 0).parent == root
        assert list(profile.iterdir()) == []


_HOLD_A_SLOT = """
import sys, time
from pathlib import Path
from applyocalypse_automation.browser.profile_pool import lease_profile

root = Path(sys.argv[1])
with lease_profile(root, fallback=root / "fallback") as profile:
    Path(sys.argv[2]).write_text(str(profile), encoding="utf-8")
    time.sleep(120)
"""


def test_a_killed_run_releases_its_slot(tmp_path: Path) -> None:
    """Why the lease is an OS lock rather than a state file.

    Electron kills a stopped run's process tree with taskkill /T /F, so the
    worker never runs cleanup on the way out. The kernel has to be the thing
    that frees the slot.
    """
    root = tmp_path / "browser-profiles"
    ready = tmp_path / "held.txt"

    child = subprocess.Popen([sys.executable, "-c", _HOLD_A_SLOT, str(root), str(ready)])
    try:
        deadline = time.monotonic() + 30
        while not ready.exists():
            if time.monotonic() > deadline:
                pytest.fail("child never acquired a slot")
            if child.poll() is not None:
                pytest.fail(f"child exited early with {child.returncode}")
            time.sleep(0.05)

        held = Path(ready.read_text(encoding="utf-8"))
        assert held == slot_directory(root, 0)

        # While it is alive the slot is genuinely unavailable.
        with lease_profile(root, fallback=tmp_path / "unused") as other:
            assert other != held

        child.kill()
        child.wait(timeout=30)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=30)

    with lease_profile(root, fallback=tmp_path / "unused") as reclaimed:
        assert reclaimed == held
