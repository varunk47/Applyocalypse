"""Post-click waits must be bounded readiness waits, not fixed sleeps.

SPA route transitions on Workday and Ashby regularly exceed the old hardcoded
1.5s/2s sleeps on a cold cache, so `detect_fields` ran against the previous page
or an empty shell. Symmetrically, a click that changes nothing should not cost a
flat 2s. The replacement polls a cheap page fingerprint until the page settles,
with a hard ceiling that reports a timeout instead of hanging the run.

Follows the injected-clock harness from tests/test_page_readiness.py.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

import pytest

from applyocalypse_automation.browser import nodriver_adapter as nodriver_adapter_module
from applyocalypse_automation.browser import playwright_adapter as playwright_adapter_module
from applyocalypse_automation.browser import seleniumbase_adapter as seleniumbase_adapter_module
from applyocalypse_automation.browser.nodriver_adapter import NodriverBrowserAdapter
from applyocalypse_automation.browser.page_readiness import (
    POST_CLICK_POLL_INTERVAL_S,
    POST_CLICK_TIMEOUT_S,
    POST_CLICK_UNCHANGED_GRACE_S,
    wait_for_page_change,
)
from applyocalypse_automation.browser.playwright_adapter import PlaywrightBrowserAdapter
from applyocalypse_automation.browser.seleniumbase_adapter import SeleniumBaseBrowserAdapter


class FingerprintTimeline:
    """Deterministic fingerprint/sleep/clock harness: one probe result per poll."""

    def __init__(self, fingerprints: list[object]) -> None:
        self.fingerprints = list(fingerprints)
        self.now = 0.0
        self.polls = 0

    async def probe(self) -> str:
        index = min(self.polls, len(self.fingerprints) - 1)
        self.polls += 1
        value = self.fingerprints[index]
        if isinstance(value, Exception):
            raise value
        return str(value)

    async def sleep(self, seconds: float) -> None:
        self.now += seconds

    def clock(self) -> float:
        return self.now


def run_wait(
    timeline: FingerprintTimeline,
    baseline: str,
    *,
    timeout_s: float = 8.0,
    poll_interval_s: float = 0.5,
    unchanged_grace_s: float = 2.0,
) -> dict[str, object]:
    return asyncio.run(
        wait_for_page_change(
            timeline.probe,
            baseline=baseline,
            timeout_s=timeout_s,
            poll_interval_s=poll_interval_s,
            unchanged_grace_s=unchanged_grace_s,
            sleep=timeline.sleep,
            clock=timeline.clock,
        )
    )


# ---------------------------------------------------------------------------
# wait_for_page_change semantics
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "case,fingerprints,expected_changed,expected_timed_out",
    [
        # Navigation lands instantly and holds: two matching polls settle it.
        ("instant navigation", ["page-b", "page-b"], True, False),
        # Workday-style SPA transition: the old page lingers, then swaps and settles.
        ("slow spa swap", ["page-a", "page-a", "page-b|300", "page-b|9000", "page-b|9000"], True, False),
        # The click changed nothing (in-place toggle, or the portal rejected it).
        ("no change at all", ["page-a"], False, False),
        # The page never stops churning: bounded by the ceiling, reported as a timeout.
        ("never settles", ["page-b", "page-c"] * 200, True, True),
        # A broken probe must not hang the run.
        ("probe raises", [RuntimeError("target detached")], False, False),
    ],
)
def test_wait_for_page_change_reports_bounded_outcomes(
    case: str,
    fingerprints: list[object],
    expected_changed: bool,
    expected_timed_out: bool,
) -> None:
    timeline = FingerprintTimeline(fingerprints)
    payload = run_wait(timeline, "page-a")

    assert payload["changed"] is expected_changed, case
    assert payload["timed_out"] is expected_timed_out, case
    assert int(payload["waited_ms"]) <= 8000, case
    assert int(payload["polls"]) >= 1, case


def test_wait_for_page_change_returns_before_the_grace_window_when_the_page_moved() -> None:
    """A settled navigation must not pay the unchanged-grace cost."""
    payload = run_wait(FingerprintTimeline(["page-b", "page-b"]), "page-a")

    assert payload["changed"] is True
    assert int(payload["waited_ms"]) < 2000


def test_wait_for_page_change_holds_for_the_grace_window_when_nothing_moved() -> None:
    """An unchanged page still gets a settling window before we call it done."""
    payload = run_wait(FingerprintTimeline(["page-a"]), "page-a")

    assert payload["changed"] is False
    assert payload["timed_out"] is False
    assert int(payload["waited_ms"]) >= 2000


def test_wait_for_page_change_always_probes_at_least_once() -> None:
    payload = run_wait(
        FingerprintTimeline(["page-b"]),
        "page-a",
        timeout_s=0.0,
        poll_interval_s=0.5,
        unchanged_grace_s=0.0,
    )

    assert int(payload["polls"]) == 1


def test_post_click_defaults_are_bounded() -> None:
    assert 0 < POST_CLICK_POLL_INTERVAL_S < POST_CLICK_UNCHANGED_GRACE_S < POST_CLICK_TIMEOUT_S
    assert POST_CLICK_TIMEOUT_S <= 30.0


# ---------------------------------------------------------------------------
# Adapter wiring: the click paths poll instead of sleeping
# ---------------------------------------------------------------------------

CLICK_OK = json.dumps({"ok": True, "action": "click_by_text", "clicked_label": "Next", "clicked_tag": "button"})
SUBMIT_OK = json.dumps({"ok": True, "action": "final_submit", "clicked_label": "Submit Application"})
CLICK_MISS = json.dumps({"ok": False, "action": "click_by_text", "message": "no matching safe portal action was found"})


class ScriptedSurface:
    """Answers click scripts with a canned result and everything else with a fingerprint."""

    def __init__(self, click_result: str, fingerprints: list[str]) -> None:
        self.click_result = click_result
        self.fingerprints = list(fingerprints)
        self.fingerprint_calls = 0
        self.sleep_calls: list[float] = []

    def _result_for(self, script: str) -> str:
        # Every generated click/submit script serialises its answer; the
        # fingerprint probe is a bare expression.
        if "JSON.stringify" in script:
            return self.click_result
        index = min(self.fingerprint_calls, len(self.fingerprints) - 1)
        self.fingerprint_calls += 1
        return self.fingerprints[index]


class ScriptedNodriverPage(ScriptedSurface):
    async def evaluate(self, script: str) -> str:
        return self._result_for(script)


class ScriptedPlaywrightPage(ScriptedSurface):
    async def evaluate(self, script: str) -> str:
        return self._result_for(script)

    async def wait_for_timeout(self, milliseconds: float) -> None:
        self.sleep_calls.append(milliseconds)


class ScriptedSeleniumDriver(ScriptedSurface):
    def execute_script(self, script: str) -> str:
        return self._result_for(script)

    def sleep(self, seconds: float) -> None:
        self.sleep_calls.append(seconds)


AdapterBuilder = Callable[[str, list[str]], tuple[object, ScriptedSurface]]


def build_nodriver(click_result: str, fingerprints: list[str]) -> tuple[object, ScriptedSurface]:
    page = ScriptedNodriverPage(click_result, fingerprints)
    adapter = NodriverBrowserAdapter()
    adapter._page = page
    return adapter, page


def build_playwright(click_result: str, fingerprints: list[str]) -> tuple[object, ScriptedSurface]:
    page = ScriptedPlaywrightPage(click_result, fingerprints)
    adapter = PlaywrightBrowserAdapter()
    adapter._page = page
    return adapter, page


def build_seleniumbase(click_result: str, fingerprints: list[str]) -> tuple[object, ScriptedSurface]:
    driver = ScriptedSeleniumDriver(click_result, fingerprints)
    adapter = SeleniumBaseBrowserAdapter()
    adapter._driver = driver
    return adapter, driver


ADAPTER_BUILDERS: tuple[tuple[str, AdapterBuilder, object], ...] = (
    ("nodriver", build_nodriver, nodriver_adapter_module),
    ("playwright", build_playwright, playwright_adapter_module),
    ("seleniumbase", build_seleniumbase, seleniumbase_adapter_module),
)


def _zero_out_post_click_timing(monkeypatch: pytest.MonkeyPatch, module: object) -> None:
    monkeypatch.setattr(module, "POST_CLICK_POLL_INTERVAL_S", 0.0)
    monkeypatch.setattr(module, "POST_CLICK_UNCHANGED_GRACE_S", 0.0)


@pytest.mark.parametrize("adapter_name,builder,module", ADAPTER_BUILDERS)
@pytest.mark.parametrize(
    "method_name,click_result",
    [("click_by_text", CLICK_OK), ("click_final_submit", SUBMIT_OK)],
)
def test_click_waits_for_the_page_to_settle(
    monkeypatch: pytest.MonkeyPatch,
    adapter_name: str,
    builder: AdapterBuilder,
    module: object,
    method_name: str,
    click_result: str,
) -> None:
    _zero_out_post_click_timing(monkeypatch, module)
    adapter, surface = builder(click_result, ["before", "after", "after"])

    result = asyncio.run(getattr(adapter, method_name)(["Next", "Submit Application"]))

    assert result.ok is True, f"{adapter_name}: {result.message}"
    settle = result.payload.get("page_settle")
    assert isinstance(settle, dict), f"{adapter_name} did not report a post-click settle"
    assert settle["changed"] is True
    assert settle["timed_out"] is False
    # The fingerprint is captured before the click and then polled after it.
    assert surface.fingerprint_calls >= 3, f"{adapter_name} did not poll the page after clicking"
    assert surface.sleep_calls == [], f"{adapter_name} still uses a fixed post-click sleep"


@pytest.mark.parametrize("adapter_name,builder,module", ADAPTER_BUILDERS)
def test_failed_click_does_not_pay_the_settle_wait(
    monkeypatch: pytest.MonkeyPatch,
    adapter_name: str,
    builder: AdapterBuilder,
    module: object,
) -> None:
    """Nothing was clicked, so there is nothing to wait for."""
    _zero_out_post_click_timing(monkeypatch, module)
    adapter, surface = builder(CLICK_MISS, ["before"])

    result = asyncio.run(adapter.click_by_text(["Next"]))  # type: ignore[attr-defined]

    assert result.ok is False, adapter_name
    assert "page_settle" not in result.payload, f"{adapter_name} waited after a click that never landed"
    assert surface.sleep_calls == [], adapter_name


@pytest.mark.parametrize("adapter_name,builder,module", ADAPTER_BUILDERS)
def test_click_reports_a_timeout_instead_of_hanging(
    monkeypatch: pytest.MonkeyPatch,
    adapter_name: str,
    builder: AdapterBuilder,
    module: object,
) -> None:
    _zero_out_post_click_timing(monkeypatch, module)
    monkeypatch.setattr(module, "POST_CLICK_TIMEOUT_S", 0.0)
    adapter, _surface = builder(CLICK_OK, ["churn-1", "churn-2"] * 50)

    result = asyncio.run(adapter.click_by_text(["Next"]))  # type: ignore[attr-defined]

    settle = result.payload["page_settle"]
    assert settle["timed_out"] is True, adapter_name
