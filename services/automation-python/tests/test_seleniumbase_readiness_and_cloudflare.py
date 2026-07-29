"""SeleniumBase adapter: readiness probing and Cloudflare interstitial detection.

Two independent defects are pinned here.

1. The readiness probe measured the length of the JSON envelope returned by
   DOM_VISIBLE_TEXT_SCRIPT rather than the page's visible text. The envelope's
   URL and title alone routinely exceed PAGE_TEXT_MIN_LENGTH, so a blank or
   still-loading page was declared ready and field detection then ran against an
   empty DOM.

2. The Cloudflare branch keyed off a blocker type nothing ever emits, so it was
   unreachable. Detection is now keyed off what the DOM probe actually reports
   (a CAPTCHA blocker with metadata.vendor == "cloudflare"). Detection only: the
   adapter never attempts to clear or solve a challenge, it flags the blocker for
   human handoff so the run pauses.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from applyocalypse_automation.browser.adapter import BrowserBlocker
from applyocalypse_automation.browser.field_detection import blockers_from_dom_snapshot
from applyocalypse_automation.browser.page_readiness import PAGE_TEXT_MIN_LENGTH
from applyocalypse_automation.browser.seleniumbase_adapter import (
    CLOUDFLARE_HANDOFF_REASON,
    SeleniumBaseBrowserAdapter,
    _is_cloudflare_blocker,
)

LONG_URL = "https://acme.wd5.myworkdayjobs.com/en-US/acme_careers/job/Remote/Senior-Engineer_R-01234567/apply"
LONG_TITLE = "Senior Engineer - Acme Corporation Careers - Application - Step 1 of 5 - My Information"


def envelope(text: str, *, url: str = LONG_URL, title: str = LONG_TITLE) -> str:
    return json.dumps({"url": url, "title": title, "text": text, "text_length": len(text)})


class FakeDriver:
    """Returns a canned result for every execute_script call."""

    def __init__(self, result: Any) -> None:
        self.result = result
        self.scripts: list[str] = []
        self.uc_gui_click_captcha_calls = 0

    def execute_script(self, script: str) -> Any:
        self.scripts.append(script)
        return self.result

    def uc_gui_click_captcha(self) -> None:  # pragma: no cover - must never run
        self.uc_gui_click_captcha_calls += 1

    def get(self, url: str) -> None:
        return None

    def sleep(self, seconds: float) -> None:
        return None


def make_adapter(result: Any) -> tuple[SeleniumBaseBrowserAdapter, FakeDriver]:
    driver = FakeDriver(result)
    adapter = SeleniumBaseBrowserAdapter()
    adapter._driver = driver
    return adapter, driver


# ---------------------------------------------------------------------------
# F15 — the readiness probe must measure visible text, not the envelope
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "case,visible_text,expected_length",
    [
        ("still loading", "Loading...", 10),
        ("blank page", "", 0),
        ("real posting", "x" * 9239, 9239),
        ("just under the threshold", "y" * (PAGE_TEXT_MIN_LENGTH - 1), PAGE_TEXT_MIN_LENGTH - 1),
    ],
)
def test_probe_measures_visible_text_length(case: str, visible_text: str, expected_length: int) -> None:
    payload = envelope(visible_text)
    # The envelope alone is long enough to fool a naive len() check.
    assert len(payload) > PAGE_TEXT_MIN_LENGTH, case

    adapter, _driver = make_adapter(payload)
    assert asyncio.run(adapter._probe_visible_text_length()) == expected_length, case


def test_ten_character_page_is_not_declared_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    """A page with 10 characters of visible text must not satisfy the readiness gate."""
    from applyocalypse_automation.browser import seleniumbase_adapter as module

    monkeypatch.setattr(module, "PAGE_TEXT_POLL_INTERVAL_S", 0.0)
    monkeypatch.setattr(module, "PAGE_TEXT_TIMEOUT_S", 0.0)

    adapter, _driver = make_adapter(envelope("Loading..."))
    result = asyncio.run(adapter.open_url(LONG_URL))

    assert result.ok is True
    readiness = result.payload["page_text"]
    assert readiness["ready"] is False
    assert readiness["text_length"] == 10


def test_probe_falls_back_to_raw_text_when_the_result_is_not_json() -> None:
    adapter, _driver = make_adapter("  plain text  ")
    assert asyncio.run(adapter._probe_visible_text_length()) == len("plain text")


def test_probe_returns_zero_without_a_driver() -> None:
    adapter = SeleniumBaseBrowserAdapter()
    assert asyncio.run(adapter._probe_visible_text_length()) == 0


# ---------------------------------------------------------------------------
# F14 — the Cloudflare predicate must match what field detection emits
# ---------------------------------------------------------------------------

CLOUDFLARE_DOM_BLOCKER = {
    "blocker_type": "CAPTCHA",
    "message": "Interactive CAPTCHA or bot challenge detected",
    "confidence": 0.95,
    "metadata": {"vendor": "cloudflare"},
}


@pytest.mark.parametrize(
    "case,blockers,expected",
    [
        ("cloudflare vendor", [BrowserBlocker("CAPTCHA", "challenge", 0.95, {"vendor": "cloudflare"})], True),
        ("vendor casing", [BrowserBlocker("CAPTCHA", "challenge", 0.95, {"vendor": "CloudFlare"})], True),
        ("recaptcha vendor", [BrowserBlocker("CAPTCHA", "challenge", 0.95, {"vendor": "recaptcha"})], False),
        ("hcaptcha vendor", [BrowserBlocker("CAPTCHA", "challenge", 0.95, {"vendor": "hcaptcha"})], False),
        ("no metadata", [BrowserBlocker("CAPTCHA", "challenge", 0.95, {})], False),
        ("login blocker", [BrowserBlocker("LOGIN", "sign in", 0.9, {})], False),
        ("nothing detected", [], False),
    ],
)
def test_is_cloudflare_blocker(case: str, blockers: list[BrowserBlocker], expected: bool) -> None:
    assert _is_cloudflare_blocker(blockers) is expected, case


def test_emitted_dom_blocker_reaches_the_adapter_predicate() -> None:
    """The blocker the DOM probe actually emits must satisfy the adapter's predicate."""
    blockers = blockers_from_dom_snapshot([CLOUDFLARE_DOM_BLOCKER])

    assert len(blockers) == 1
    assert _is_cloudflare_blocker(blockers) is True


def test_detect_blockers_flags_cloudflare_for_human_handoff_without_solving_it() -> None:
    adapter, driver = make_adapter(json.dumps([CLOUDFLARE_DOM_BLOCKER]))

    blockers = asyncio.run(adapter.detect_blockers())

    assert len(blockers) == 1
    blocker = blockers[0]
    assert blocker.blocker_type == "CAPTCHA"
    assert blocker.metadata["vendor"] == "cloudflare"
    assert blocker.metadata["requires_human_handoff"] is True
    assert blocker.metadata["handoff_reason"] == CLOUDFLARE_HANDOFF_REASON
    # Hard requirement: we never attempt to clear or solve a bot challenge.
    assert driver.uc_gui_click_captcha_calls == 0
    assert not hasattr(adapter, "uc_gui_click_captcha")


def test_detect_blockers_leaves_other_challenges_untouched() -> None:
    recaptcha = {**CLOUDFLARE_DOM_BLOCKER, "metadata": {"vendor": "recaptcha"}}
    adapter, driver = make_adapter(json.dumps([recaptcha]))

    blockers = asyncio.run(adapter.detect_blockers())

    assert len(blockers) == 1
    assert "requires_human_handoff" not in blockers[0].metadata
    assert driver.uc_gui_click_captcha_calls == 0


def test_adapter_module_has_no_captcha_solving_capability() -> None:
    """The Cloudflare bypass call was removed, not repaired."""
    from applyocalypse_automation.browser import seleniumbase_adapter as module

    source = __import__("pathlib").Path(module.__file__).read_text(encoding="utf-8")
    assert "uc_gui_click_captcha" not in source
    assert "uc_gui_handle_captcha" not in source
