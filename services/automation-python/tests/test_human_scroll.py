"""Executable tests for reaching a control below the fold.

The locate script used to call ``scrollIntoView`` before measuring, which moves
the viewport in a single frame with no wheel, no pointer motion and nothing the
browser marks as trusted behind it. That is the same class of signal as the
``isTrusted: false`` click it sits next to, and it is measured the same way: by
what the page is asked to do, not by what the worker meant.

So the page now reports how far it needs to move and the worker moves it, in
wheel notches, at a pace that is not a metronome. Three things have to hold.
A control already in view must not be scrolled at all, because motion nobody
needed is its own tell. The measurement has to be taken again afterwards, since
the box the page reported is stale the moment the page moves. And a scroll that
cannot happen must cost nothing, because the injected ``element.click()`` behind
it reaches a control wherever it sits.

The script tests run the REAL locate script against the DOM stub, because
whether a control is inside a viewport is a question about geometry.
"""
from __future__ import annotations

import asyncio
import json
import random
import statistics
from typing import Any

import pytest
from js_bridge import run_browser_script

from applyocalypse_automation.browser import nodriver_adapter as nodriver_adapter_module
from applyocalypse_automation.browser.field_detection import (
    LOCATE_SCRIPT_MARKER,
    build_click_by_text_script,
    parse_click_by_text_result,
)
from applyocalypse_automation.browser.human_scroll import (
    MAX_GAP_S,
    MAX_NOTCH_PX,
    MIN_GAP_S,
    MIN_NOTCH_PX,
    ScrollAnchor,
    dispatch_wheel_scroll,
    gap_seconds,
    parse_scroll_anchor,
    scroll_notches,
)
from applyocalypse_automation.browser.nodriver_adapter import NodriverBrowserAdapter
from applyocalypse_automation.browser.trusted_click import Point

VIEWPORT = {"width": 1280, "height": 800}


# ---------------------------------------------------------------------------
# what a scroll is made of
# ---------------------------------------------------------------------------


def test_the_notches_add_up_to_exactly_the_distance_asked_for() -> None:
    """Undershooting leaves the control out of view; overshooting puts it back out."""
    notches = scroll_notches(1015.0, random.Random(3))

    assert sum(notches) == pytest.approx(1015.0)


def test_a_scroll_arrives_as_wheel_notches_rather_than_one_jump() -> None:
    """One delta the height of a page is not a gesture any wheel produces."""
    notches = scroll_notches(1015.0, random.Random(3))

    assert len(notches) >= 8
    assert all(0 < notch <= MAX_NOTCH_PX for notch in notches)
    assert all(notch >= MIN_NOTCH_PX for notch in notches[:-1])


def test_a_control_above_the_fold_is_scrolled_back_up() -> None:
    """A form the run has already moved past has a negative distance to travel."""
    notches = scroll_notches(-620.0, random.Random(4))

    assert sum(notches) == pytest.approx(-620.0)
    assert all(notch < 0 for notch in notches)


def test_two_scrolls_of_the_same_distance_are_not_the_same_events() -> None:
    """A fixed notch size is a fingerprint, and every device reports a different one."""
    rng = random.Random(9)

    assert scroll_notches(1000.0, rng) != scroll_notches(1000.0, rng)


@pytest.mark.parametrize("travel", [0.0, 4.0, -7.9, 40000.0, float("nan"), float("inf"), None, True])
def test_a_distance_not_worth_scrolling_produces_no_events(travel: Any) -> None:
    """Too small to matter, too large to be a page, or not a number at all."""
    assert scroll_notches(travel, random.Random(1)) == ()


@pytest.mark.parametrize("seed", range(12))
def test_a_gap_between_notches_is_never_zero_and_never_endless(seed: int) -> None:
    assert MIN_GAP_S <= gap_seconds(random.Random(seed)) <= MAX_GAP_S


def test_the_pace_of_a_scroll_is_not_a_metronome() -> None:
    """Log-normal, like the gap between keystrokes: bursts, with pauses in them."""
    rng = random.Random(13)
    gaps = [gap_seconds(rng) for _ in range(2000)]

    assert 0.04 < statistics.median(gaps) < 0.09
    assert sum(1 for gap in gaps if gap > 0.15) / len(gaps) > 0.02


def test_a_long_scroll_still_finishes_in_about_a_second() -> None:
    """Realism that stalls a run is not a trade worth making."""
    rng = random.Random(21)
    notches = scroll_notches(1500.0, rng)

    assert sum(gap_seconds(rng) for _ in notches) < 2.5


# ---------------------------------------------------------------------------
# what the page reports
# ---------------------------------------------------------------------------


def page(*elements: dict, viewport: dict | None = None) -> dict:
    return {
        "origin": "https://jobs.example.com",
        "viewport": viewport or VIEWPORT,
        "elements": [{"tag": "form", "children": list(elements)}],
    }


def button(top: float, *, height: float = 30.0) -> dict:
    return {"tag": "button", "text": "Apply now", "rect": {"left": 100, "top": top, "width": 200, "height": height}}


def locate(spec: dict) -> dict:
    """Run the real locate script and return what the adapter would actually see."""
    script = build_click_by_text_script(["Apply now"], locate_only=True)
    return parse_click_by_text_result(json.dumps(run_browser_script(script, spec)["result"])).payload


def test_the_page_is_never_asked_to_scroll_itself() -> None:
    """The whole point: a viewport that moves with no input behind it is the tell.

    The call, not the word: the script still carries a comment saying why it is
    gone, and a test that fails on the explanation is a test nobody can read.
    """
    assert "scrollIntoView(" not in build_click_by_text_script(["Apply now"], locate_only=True)
    assert "scrollIntoView(" not in build_click_by_text_script(["Apply now"])


def test_a_control_already_in_view_is_measured_and_not_moved() -> None:
    payload = locate(page(button(top=200)))

    assert "scroll_by" not in payload
    assert payload["click_target"]["y"] == pytest.approx(215.0)


def test_a_control_below_the_fold_asks_to_be_brought_to_the_middle() -> None:
    """1415 down the page, 400 down the viewport, so the page moves by the difference."""
    payload = locate(page(button(top=1400)))

    assert payload["scroll_by"]["y"] == pytest.approx(1015.0)
    assert "click_target" not in payload


def test_a_control_scrolled_past_asks_to_come_back_up() -> None:
    payload = locate(page(button(top=-120)))

    assert payload["scroll_by"]["y"] == pytest.approx(-505.0)


def test_the_cursor_is_aimed_at_the_middle_of_whatever_viewport_this_is() -> None:
    """A wheel scrolls the scroller under the cursor, so where it points decides what moves."""
    payload = locate(page(button(top=1400), viewport={"width": 1000, "height": 600}))

    assert (payload["scroll_by"]["ax"], payload["scroll_by"]["ay"]) == (500.0, 300.0)


def test_a_control_taller_than_the_screen_is_measured_by_the_part_being_pressed() -> None:
    """Its edges are off both ends of the viewport, but its middle is right there."""
    payload = locate(page(button(top=-600, height=2000)))

    assert "scroll_by" not in payload
    assert payload["click_target"]["y"] == pytest.approx(400.0)


def test_a_control_out_of_view_is_still_a_refusal_that_falls_back() -> None:
    """If the scroll never happens, the injected click has to remain reachable."""
    payload = locate(page(button(top=1400)))

    assert payload["fallback"] == "injected_js"


def test_a_scroll_the_page_did_not_ask_for_is_not_invented() -> None:
    """A control covered by a banner is in view; moving the page would not uncover it."""
    covered = page(
        {
            "tag": "div",
            "text": "We use cookies",
            "rect": {"left": 0, "top": 0, "width": 1280, "height": 400},
            "style": {"z-index": "10"},
        },
        button(top=200),
    )

    payload = locate(covered)

    assert payload["fallback"] == "injected_js"
    assert "scroll_by" not in payload


# ---------------------------------------------------------------------------
# where the wheel gets aimed
# ---------------------------------------------------------------------------


def test_an_embedded_frame_reports_its_own_middle_and_gets_the_pages() -> None:
    """A frame measures from its own corner, but the wheel is sent to the top document."""
    anchor = parse_scroll_anchor({"scroll_by": {"y": 300.0, "ax": 200.0, "ay": 150.0}}, (40.0, 260.0))

    assert anchor == ScrollAnchor(point=Point(x=240.0, y=410.0), travel_px=300.0)


@pytest.mark.parametrize(
    "scroll_by",
    [
        {"y": 300.0, "ax": 200.0},
        {"y": None, "ax": 200.0, "ay": 150.0},
        {"y": "300", "ax": 200.0, "ay": 150.0},
        {"y": float("inf"), "ax": 200.0, "ay": 150.0},
        "300",
    ],
)
def test_a_half_read_scroll_is_refused_rather_than_guessed(scroll_by: Any) -> None:
    """Scrolling at a made-up coordinate moves something nobody looked at."""
    assert parse_scroll_anchor({"scroll_by": scroll_by}) is None


class FakeInputDomain:
    """Stands in for ``nodriver.cdp.input_``, recording the calls made through it."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def dispatch_mouse_event(self, type_: str, **kwargs: Any) -> dict[str, Any]:
        call = {"type": type_, **kwargs}
        self.calls.append(call)
        return call


class FakeTab:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(self, command: dict[str, Any]) -> None:
        self.sent.append(command)


def wheel(travel: float) -> tuple[FakeTab, FakeInputDomain, list[float]]:
    tab, domain, waits = FakeTab(), FakeInputDomain(), []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    anchor = ScrollAnchor(point=Point(640.0, 400.0), travel_px=travel)
    asyncio.run(dispatch_wheel_scroll(tab, anchor, cdp_input=domain, rng=random.Random(5), sleep=sleep))
    return tab, domain, waits


def test_every_notch_reaches_the_page_as_a_wheel_event() -> None:
    tab, domain, _ = wheel(1015.0)

    assert tab.sent == domain.calls
    assert {call["type"] for call in domain.calls} == {"mouseWheel"}
    assert sum(call["delta_y"] for call in domain.calls) == pytest.approx(1015.0)


def test_the_wheel_stays_where_the_page_pointed_it() -> None:
    """Moving the cursor between notches would scroll a different scroller half way."""
    _, domain, _ = wheel(1015.0)

    assert {(call["x"], call["y"]) for call in domain.calls} == {(640.0, 400.0)}
    assert {call["delta_x"] for call in domain.calls} == {0.0}


def test_the_page_is_given_a_moment_after_the_last_notch() -> None:
    """It is measured again straight after this, and a scroll takes a frame to land."""
    _, domain, waits = wheel(1015.0)

    assert len(waits) == len(domain.calls)


def test_a_distance_not_worth_scrolling_sends_nothing_at_all() -> None:
    tab, domain, waits = wheel(3.0)

    assert (tab.sent, domain.calls, waits) == ([], [], [])


# ---------------------------------------------------------------------------
# what a click actually does with it
# ---------------------------------------------------------------------------

BELOW_FOLD = {
    "ok": False,
    "action": "click_by_text",
    "message": "the matched control is outside the viewport",
    "fallback": "injected_js",
    "scroll_by": {"y": 1015.0, "ax": 640.0, "ay": 400.0},
}

COVERED = {
    "ok": False,
    "action": "click_by_text",
    "message": "the matched control is covered by something else",
    "fallback": "injected_js",
}

IN_VIEW = {
    "ok": True,
    "action": "click_by_text",
    "clicked_label": "Apply now",
    "clicked_tag": "button",
    "click_target": {"x": 200.0, "y": 400.0, "jx": 20.0, "jy": 6.0},
}


class ScriptedFrame:
    """Answers each locate with the next queued payload, and every press the same way."""

    def __init__(self, *located: dict) -> None:
        self.located = list(located)
        self.scripts: list[str] = []

    async def evaluate(self, script: str) -> str:
        self.scripts.append(script)
        if LOCATE_SCRIPT_MARKER not in script:
            return json.dumps({"ok": True, "action": "click_by_text", "clicked_label": "Apply now"})
        answer = self.located.pop(0) if len(self.located) > 1 else self.located[0]
        return json.dumps(answer)

    @property
    def locates(self) -> int:
        return sum(1 for script in self.scripts if LOCATE_SCRIPT_MARKER in script)


class RefusingWorlds:
    """No isolated world, so every read falls through to the frame itself."""

    def forget_all(self) -> None:
        return None

    async def evaluate(self, frame: object, script: str) -> tuple[bool, None]:
        return (False, None)


def clicking(frame: ScriptedFrame, monkeypatch: pytest.MonkeyPatch, *, scrolls: bool = True) -> dict[str, Any]:
    """Run one click against ``frame`` and report what the worker sent out."""
    wheels: list[ScrollAnchor] = []
    presses: list[Point] = []

    async def fake_wheel(tab: Any, anchor: ScrollAnchor) -> bool:
        wheels.append(anchor)
        return scrolls

    async def fake_press(tab: Any, point: Point) -> None:
        presses.append(point)

    monkeypatch.setattr(nodriver_adapter_module, "dispatch_wheel_scroll", fake_wheel)
    monkeypatch.setattr(nodriver_adapter_module, "dispatch_trusted_click", fake_press)

    adapter = NodriverBrowserAdapter()
    adapter._page = frame  # noqa: SLF001 - unit wiring test
    adapter._worlds = RefusingWorlds()  # noqa: SLF001 - unit wiring test
    result = asyncio.run(
        adapter._click_in_frame(  # noqa: SLF001 - unit wiring test
            frame,
            build_click_by_text_script(["Apply now"], locate_only=True),
            build_click_by_text_script(["Apply now"]),
            parse_click_by_text_result,
            "portal action click failed",
        )
    )
    return {"result": result, "wheels": wheels, "presses": presses}


def test_a_button_below_the_fold_is_wheeled_over_and_then_pressed(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = ScriptedFrame(BELOW_FOLD, IN_VIEW)

    sent = clicking(frame, monkeypatch)

    assert [anchor.travel_px for anchor in sent["wheels"]] == [1015.0]
    assert sent["wheels"][0].point == Point(640.0, 400.0)
    assert sent["result"].ok is True
    assert sent["result"].payload["click_dispatch"] == "trusted_input"
    assert len(sent["presses"]) == 1


def test_the_control_is_measured_again_once_the_page_has_moved(monkeypatch: pytest.MonkeyPatch) -> None:
    """The box reported before the scroll describes where the button used to be."""
    frame = ScriptedFrame(BELOW_FOLD, IN_VIEW)

    clicking(frame, monkeypatch)

    assert frame.locates == 2


def test_a_button_already_in_view_is_never_scrolled_to(monkeypatch: pytest.MonkeyPatch) -> None:
    """Motion nobody needed is as visible as motion nobody made."""
    frame = ScriptedFrame(IN_VIEW)

    sent = clicking(frame, monkeypatch)

    assert sent["wheels"] == []
    assert frame.locates == 1
    assert sent["result"].payload["click_dispatch"] == "trusted_input"


def test_a_refusal_with_no_scroll_in_it_is_not_scrolled(monkeypatch: pytest.MonkeyPatch) -> None:
    """A covered control is already in view; moving the page would not uncover it."""
    frame = ScriptedFrame(COVERED)

    sent = clicking(frame, monkeypatch)

    assert sent["wheels"] == []
    assert sent["result"].payload["click_dispatch"] == "injected_js"


def test_a_scroll_that_does_not_happen_leaves_the_click_to_the_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """This is what makes the change safe: the fallback is the click that always worked."""
    frame = ScriptedFrame(BELOW_FOLD)

    sent = clicking(frame, monkeypatch, scrolls=False)

    assert len(sent["wheels"]) == 1
    assert frame.locates == 1
    assert sent["result"].ok is True
    assert sent["result"].payload["click_dispatch"] == "injected_js"


def test_a_control_that_stays_out_of_view_is_still_clicked(monkeypatch: pytest.MonkeyPatch) -> None:
    """The scroll landed somewhere else. One retry, then the press the page can do itself."""
    frame = ScriptedFrame(BELOW_FOLD, BELOW_FOLD)

    sent = clicking(frame, monkeypatch)

    assert frame.locates == 2
    assert len(sent["wheels"]) == 1
    assert sent["result"].ok is True
    assert sent["result"].payload["click_dispatch"] == "injected_js"


def test_the_worker_does_not_carry_the_scroll_into_a_run_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """Coordinates are working data. What gets persisted is what happened."""
    sent = clicking(ScriptedFrame(BELOW_FOLD, IN_VIEW), monkeypatch)

    assert "scroll_by" not in sent["result"].payload
    assert "click_target" not in sent["result"].payload
