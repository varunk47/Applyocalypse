"""Executable tests for arriving at a site before arriving at its apply form.

A run used to open an apply URL cold, which makes the first request a portal
ever sees from this profile a deep link, with no referrer, no cookie for the
origin and no session behind it. That shape is legible to bot management before
any script has run, so a navigation into a site the profile has not been on now
lands on the front door first.

Two things have to hold for that to be worth doing. It has to happen once per
site rather than once per navigation, or a run pays for it on every page. And it
has to be free to fail, because the page that matters is the one after it.
"""
from __future__ import annotations

import asyncio
import random
import statistics

import pytest

from applyocalypse_automation.browser import nodriver_adapter as nodriver_adapter_module
from applyocalypse_automation.browser.navigation_warmup import (
    MAX_DWELL_S,
    MIN_DWELL_S,
    dwell_seconds,
    origin_of,
    warm_up_target,
)
from applyocalypse_automation.browser.nodriver_adapter import NodriverBrowserAdapter

APPLY_URL = "https://boards.greenhouse.io/acme/jobs/4155832007"
FRONT_DOOR = "https://boards.greenhouse.io/"


# ---------------------------------------------------------------------------
# which page gets landed on first
# ---------------------------------------------------------------------------


def test_a_deep_apply_link_is_warmed_at_the_front_door() -> None:
    assert warm_up_target(APPLY_URL, set()) == FRONT_DOOR


def test_the_front_door_itself_is_not_warmed_with_itself() -> None:
    """Warming it would be one request for the page about to be requested."""
    assert warm_up_target(FRONT_DOOR, set()) is None
    assert warm_up_target("https://boards.greenhouse.io", set()) is None


def test_a_query_string_alone_is_still_the_front_door() -> None:
    """A tracking parameter does not make a landing page a deep link."""
    assert warm_up_target("https://jobs.example.com/?gh_src=linkedin", set()) is None


def test_a_site_the_run_has_already_been_on_is_left_alone() -> None:
    """The profile has its cookies and its cache; landing again is just slow."""
    assert warm_up_target(APPLY_URL, {"https://boards.greenhouse.io"}) is None


def test_a_second_ats_on_the_same_run_is_warmed_separately() -> None:
    """Having been on Greenhouse says nothing to Workday, which has never seen us."""
    visited = {"https://boards.greenhouse.io"}

    target = warm_up_target("https://acme.wd5.myworkdayjobs.com/en-US/External/job/x", visited)

    assert target == "https://acme.wd5.myworkdayjobs.com/"


def test_the_host_is_matched_however_it_is_spelled() -> None:
    """Hostnames are case insensitive, and a second spelling is not a second site."""
    assert origin_of("https://Boards.Greenhouse.IO/acme/jobs/1") == "https://boards.greenhouse.io"
    assert warm_up_target("https://BOARDS.greenhouse.io/acme/jobs/1", {"https://boards.greenhouse.io"}) is None


def test_a_port_belongs_to_the_origin() -> None:
    """Two ports on one host are two origins to a browser, and to a cookie jar."""
    assert origin_of("http://localhost:3000/apply") == "http://localhost:3000"
    assert warm_up_target("http://localhost:3000/apply", {"http://localhost:4000"}) == "http://localhost:3000/"


@pytest.mark.parametrize(
    "url",
    [
        "about:blank",
        "file:///C:/tmp/form.html",
        "data:text/html,<form></form>",
        "chrome://settings",
        "",
    ],
)
def test_a_page_that_is_not_on_the_web_has_no_front_door(url: str) -> None:
    """There is no server here to form an impression of the session."""
    assert origin_of(url) is None
    assert warm_up_target(url, set()) is None


def test_a_url_that_will_not_parse_is_a_refusal_not_a_crash() -> None:
    """A malformed URL still has to reach the navigation that will report it."""
    assert origin_of("https://example.com:notaport/apply") is None
    assert warm_up_target("https://example.com:notaport/apply", set()) is None


# ---------------------------------------------------------------------------
# how long a person stays on the page they landed on
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(12))
def test_a_dwell_is_never_instant_and_never_endless(seed: int) -> None:
    """The floor is what makes it a visit; the ceiling is what keeps a run moving."""
    assert MIN_DWELL_S <= dwell_seconds(random.Random(seed)) <= MAX_DWELL_S


def test_two_landings_do_not_take_the_same_time() -> None:
    """A constant delay is a pattern, which is the thing this is avoiding."""
    rng = random.Random(7)

    assert len({dwell_seconds(rng) for _ in range(20)}) > 1


def test_most_landings_are_a_second_or_two_and_some_are_much_longer() -> None:
    """Log-normal, not uniform: reading time has a long tail and no negative half."""
    rng = random.Random(11)
    dwells = [dwell_seconds(rng) for _ in range(2000)]

    assert 1.2 < statistics.median(dwells) < 1.9
    assert sum(1 for dwell in dwells if dwell > 2.5) / len(dwells) > 0.05


# ---------------------------------------------------------------------------
# what a navigation actually does with it
# ---------------------------------------------------------------------------


class FakePage:
    """A page with enough text to be called rendered on the first probe."""

    async def evaluate(self, script: str) -> str:
        return "9239"


class FakeBrowser:
    def __init__(self, *, broken: str | None = None) -> None:
        self.requested_urls: list[str] = []
        self._broken = broken

    async def get(self, url: str) -> FakePage:
        self.requested_urls.append(url)
        if self._broken is not None and url == self._broken:
            raise RuntimeError("net::ERR_NAME_NOT_RESOLVED")
        return FakePage()


class CountingWorlds:
    """Refuses every probe, so reads fall back, and counts what it was told to forget."""

    def __init__(self) -> None:
        self.forgotten = 0

    def forget_all(self) -> None:
        self.forgotten += 1

    async def evaluate(self, frame: object, script: str) -> tuple[bool, None]:
        return (False, None)


def adapter_for(browser: FakeBrowser, monkeypatch: pytest.MonkeyPatch) -> NodriverBrowserAdapter:
    """An adapter wired to a fake browser, with the waiting taken out."""
    monkeypatch.setattr(nodriver_adapter_module, "PAGE_TEXT_POLL_INTERVAL_S", 0.0)
    monkeypatch.setattr(nodriver_adapter_module, "WARM_UP_TIMEOUT_S", 0.0)
    monkeypatch.setattr(nodriver_adapter_module, "dwell_seconds", lambda: 0.0)
    adapter = NodriverBrowserAdapter()
    adapter._browser = browser  # noqa: SLF001 - unit wiring test
    return adapter


def test_the_front_door_is_opened_before_the_apply_page(monkeypatch: pytest.MonkeyPatch) -> None:
    browser = FakeBrowser()
    adapter = adapter_for(browser, monkeypatch)

    result = asyncio.run(adapter.open_url(APPLY_URL))

    assert browser.requested_urls == [FRONT_DOOR, APPLY_URL]
    assert result.payload["warmed_up"] is True


def test_the_apply_page_is_still_what_the_result_describes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The warm-up is a detour, and a caller reading the payload must not see it."""
    adapter = adapter_for(FakeBrowser(), monkeypatch)

    result = asyncio.run(adapter.open_url(APPLY_URL))

    assert result.ok is True
    assert result.payload["url"] == APPLY_URL
    assert result.payload["page_text"]["ready"] is True


def test_a_site_is_warmed_once_however_many_pages_are_opened_there(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run opens the posting, the form, then the posting again."""
    browser = FakeBrowser()
    adapter = adapter_for(browser, monkeypatch)

    asyncio.run(adapter.open_url(APPLY_URL))
    asyncio.run(adapter.open_url("https://boards.greenhouse.io/acme/jobs/4155832007/application"))
    asyncio.run(adapter.open_url(APPLY_URL))

    assert browser.requested_urls.count(FRONT_DOOR) == 1


def test_a_new_site_mid_run_is_warmed_too(monkeypatch: pytest.MonkeyPatch) -> None:
    """Portals hand off between origins, and the next one has never seen this profile."""
    browser = FakeBrowser()
    adapter = adapter_for(browser, monkeypatch)

    asyncio.run(adapter.open_url(APPLY_URL))
    asyncio.run(adapter.open_url("https://acme.wd5.myworkdayjobs.com/en-US/External/job/x"))

    assert browser.requested_urls[-2:] == [
        "https://acme.wd5.myworkdayjobs.com/",
        "https://acme.wd5.myworkdayjobs.com/en-US/External/job/x",
    ]


def test_a_front_door_that_will_not_load_does_not_cost_the_navigation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """This is what makes the change safe: the run ends up where it would have been."""
    browser = FakeBrowser(broken=FRONT_DOOR)
    adapter = adapter_for(browser, monkeypatch)

    result = asyncio.run(adapter.open_url(APPLY_URL))

    assert result.ok is True
    assert result.payload["url"] == APPLY_URL
    assert result.payload["warmed_up"] is False


def test_a_broken_front_door_is_not_tried_again_on_every_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One failed navigation for the run, not one per page opened on the site."""
    browser = FakeBrowser(broken=FRONT_DOOR)
    adapter = adapter_for(browser, monkeypatch)

    asyncio.run(adapter.open_url(APPLY_URL))
    asyncio.run(adapter.open_url("https://boards.greenhouse.io/acme/jobs/9"))

    assert browser.requested_urls.count(FRONT_DOOR) == 1


def test_the_front_door_context_is_not_carried_onto_the_apply_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two documents, two navigations, and no cached world may outlive either."""
    adapter = adapter_for(FakeBrowser(), monkeypatch)
    worlds = CountingWorlds()
    adapter._worlds = worlds  # noqa: SLF001 - unit wiring test

    asyncio.run(adapter.open_url(APPLY_URL))

    assert worlds.forgotten == 2


def test_a_launch_that_never_happened_is_still_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """The warm-up must not be the thing that reaches for a browser that is not there."""
    monkeypatch.setattr(nodriver_adapter_module, "dwell_seconds", lambda: 0.0)

    result = asyncio.run(NodriverBrowserAdapter().open_url(APPLY_URL))

    assert result.ok is False
    assert "not launched" in result.message
