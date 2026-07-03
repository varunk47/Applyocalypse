"""Tests for page_readiness.wait_for_page_text and its nodriver adapter wiring.

Client-rendered ATS pages (Workday, Greenhouse embeds, Ashby) paint their text
seconds after navigation. The adapter must poll until visible text is non-empty
and stable before the runner scrapes it, instead of reading the DOM immediately.
"""
from __future__ import annotations

import asyncio

import pytest

from applyocalypse_automation.browser import nodriver_adapter as nodriver_adapter_module
from applyocalypse_automation.browser.nodriver_adapter import NodriverBrowserAdapter
from applyocalypse_automation.browser.page_readiness import wait_for_page_text


class FakeTimeline:
    """Deterministic probe/sleep/clock harness: one probe result per poll."""

    def __init__(self, lengths: list[object]) -> None:
        self.lengths = list(lengths)
        self.now = 0.0
        self.polls = 0

    async def probe(self) -> int:
        index = min(self.polls, len(self.lengths) - 1)
        self.polls += 1
        value = self.lengths[index]
        if isinstance(value, Exception):
            raise value
        return int(value)  # type: ignore[arg-type]

    async def sleep(self, seconds: float) -> None:
        self.now += seconds

    def clock(self) -> float:
        return self.now


@pytest.mark.parametrize(
    ("lengths", "expected_ready", "expected_polls"),
    [
        # Text present and stable immediately: two matching polls suffice.
        ([500, 500], True, 2),
        # Workday-style hydration: empty, empty, partial, grows, stabilizes.
        ([0, 0, 273, 9239, 9239], True, 5),
        # Exceptions while the page boots count as empty, then recovery.
        ([RuntimeError("target detached"), 500, 500], True, 3),
    ],
)
def test_wait_for_page_text_reaches_ready(
    lengths: list[object], expected_ready: bool, expected_polls: int
) -> None:
    timeline = FakeTimeline(lengths)
    payload = asyncio.run(
        wait_for_page_text(
            timeline.probe,
            timeout_s=15.0,
            poll_interval_s=0.5,
            sleep=timeline.sleep,
            clock=timeline.clock,
        )
    )
    assert payload["ready"] is expected_ready
    assert payload["polls"] == expected_polls
    assert payload["text_length"] == int(lengths[-1])  # type: ignore[call-overload]


def test_wait_for_page_text_times_out_on_blank_page() -> None:
    timeline = FakeTimeline([0])
    payload = asyncio.run(
        wait_for_page_text(
            timeline.probe,
            timeout_s=15.0,
            poll_interval_s=0.5,
            sleep=timeline.sleep,
            clock=timeline.clock,
        )
    )
    assert payload["ready"] is False
    assert payload["text_length"] == 0
    # Probes at t=0.0 through t=15.0 inclusive, every 0.5s.
    assert payload["polls"] == 31
    assert payload["waited_ms"] == 15000


def test_wait_for_page_text_times_out_when_text_never_stabilizes() -> None:
    timeline = FakeTimeline([10, 20] * 100)
    payload = asyncio.run(
        wait_for_page_text(
            timeline.probe,
            timeout_s=3.0,
            poll_interval_s=0.5,
            sleep=timeline.sleep,
            clock=timeline.clock,
        )
    )
    assert payload["ready"] is False


def test_wait_for_page_text_respects_min_text_length() -> None:
    timeline = FakeTimeline([5, 5, 5])
    payload = asyncio.run(
        wait_for_page_text(
            timeline.probe,
            timeout_s=1.0,
            poll_interval_s=0.5,
            min_text_length=40,
            sleep=timeline.sleep,
            clock=timeline.clock,
        )
    )
    assert payload["ready"] is False
    assert payload["text_length"] == 5


class FakePage:
    """Fake nodriver page whose visible-text length grows across evaluates."""

    def __init__(self, lengths: list[int]) -> None:
        self.lengths = list(lengths)
        self.evaluations = 0

    async def evaluate(self, script: str) -> str:
        index = min(self.evaluations, len(self.lengths) - 1)
        self.evaluations += 1
        return str(self.lengths[index])


class FakeBrowser:
    def __init__(self, page: FakePage) -> None:
        self.page = page
        self.requested_urls: list[str] = []

    async def get(self, url: str) -> FakePage:
        self.requested_urls.append(url)
        return self.page


def test_open_url_waits_for_rendered_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """open_url must poll the page until text renders, not return immediately."""
    monkeypatch.setattr(nodriver_adapter_module, "PAGE_TEXT_POLL_INTERVAL_S", 0.0)
    page = FakePage([0, 0, 9239, 9239])
    adapter = NodriverBrowserAdapter()
    adapter._browser = FakeBrowser(page)  # noqa: SLF001 - unit wiring test

    result = asyncio.run(adapter.open_url("https://example.wd1.myworkdayjobs.com/job/1"))

    assert result.ok is True
    readiness = result.payload["page_text"]
    assert readiness["ready"] is True
    assert readiness["text_length"] == 9239
    assert page.evaluations >= 4


def test_open_url_reports_not_ready_after_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """A page that never renders still navigates, but reports ready=False."""
    monkeypatch.setattr(nodriver_adapter_module, "PAGE_TEXT_POLL_INTERVAL_S", 0.0)
    monkeypatch.setattr(nodriver_adapter_module, "PAGE_TEXT_TIMEOUT_S", 0.0)
    page = FakePage([0])
    adapter = NodriverBrowserAdapter()
    adapter._browser = FakeBrowser(page)  # noqa: SLF001 - unit wiring test

    result = asyncio.run(adapter.open_url("https://example.wd1.myworkdayjobs.com/job/1"))

    assert result.ok is True
    assert result.payload["page_text"]["ready"] is False
