"""Every click a portal receives from us should look like a click from a mouse.

The gate a detector reaches for first is ``event.isTrusted``. It costs one
property read, it cannot be forged from inside the page, and until now every
button we pressed failed it: the click scripts end in ``element.click()``, which
is a synthetic event no matter how carefully the surrounding search behaved.

These tests pin the replacement. The page is asked where the control is and
whether that point actually reaches it; the press itself is dispatched from
outside as a real input event. What matters most here is not the stealth but the
safety: a translated coordinate that lands a few pixels off clicks whatever is
underneath, and on an application form the thing underneath might submit it. So
the reachability check, the frame translation, and the refusal to guess when
either is unavailable all get pinned harder than the timing does.
"""

from __future__ import annotations

import asyncio
import math
import random
from typing import Any

import pytest

from applyocalypse_automation.browser.trusted_click import (
    ClickTarget,
    MouseEvent,
    Point,
    aim_point,
    content_box_origin,
    dispatch_trusted_click,
    mouse_event_sequence,
    parse_click_target,
)

_TARGET = ClickTarget(x=300.0, y=200.0, jitter_x=12.0, jitter_y=8.0)


# ---------------------------------------------------------------------------
# where the click lands
# ---------------------------------------------------------------------------


def test_the_click_never_leaves_the_box_the_page_verified() -> None:
    """Jitter is only safe inside the region the page confirmed is reachable.

    The page hit-tests the centre and the four extremes of this box before
    reporting it. Drawing outside them would aim at a point nothing checked.
    """
    rng = random.Random(7)

    for _ in range(500):
        point = aim_point(_TARGET, origin=(0.0, 0.0), rng=rng)
        assert abs(point.x - _TARGET.x) <= _TARGET.jitter_x
        assert abs(point.y - _TARGET.y) <= _TARGET.jitter_y


def test_the_same_control_is_not_clicked_in_the_same_pixel_every_time() -> None:
    """A run of clicks landing on one exact pixel is a signature of its own."""
    rng = random.Random(11)

    points = {(round(p.x, 3), round(p.y, 3)) for p in (aim_point(_TARGET, (0.0, 0.0), rng) for _ in range(40))}

    assert len(points) > 30


def test_a_control_too_small_to_jitter_is_still_clicked_dead_centre() -> None:
    """A 1px checkbox has no room to vary, and the centre is the only safe point."""
    tiny = ClickTarget(x=50.0, y=60.0, jitter_x=0.0, jitter_y=0.0)

    point = aim_point(tiny, origin=(0.0, 0.0), rng=random.Random(3))

    assert (point.x, point.y) == (50.0, 60.0)


def test_a_box_inside_an_embedded_form_is_translated_into_the_top_document() -> None:
    """The whole reason this is hard.

    ``getBoundingClientRect()`` inside a cross-origin iframe is measured from
    that frame's own viewport, but the input event is dispatched against the top
    document. Sending the frame-local number would click a point that far above
    and to the left of the button, which on an application form is not a
    harmless miss.
    """
    centred = ClickTarget(x=300.0, y=200.0, jitter_x=0.0, jitter_y=0.0)

    point = aim_point(centred, origin=(64.0, 410.0), rng=random.Random(1))

    assert (point.x, point.y) == (364.0, 610.0)


# ---------------------------------------------------------------------------
# reading the page's answer
# ---------------------------------------------------------------------------


def test_a_reachable_box_is_read_off_the_locate_result() -> None:
    target = parse_click_target({"ok": True, "click_target": {"x": 120.5, "y": 44.0, "jx": 10.0, "jy": 6.0}})

    assert target == ClickTarget(x=120.5, y=44.0, jitter_x=10.0, jitter_y=6.0)


@pytest.mark.parametrize(
    "payload",
    [
        {"ok": True},
        {"ok": True, "click_target": None},
        {"ok": True, "click_target": {"x": 10.0}},
        {"ok": True, "click_target": {"x": "left", "y": 5.0, "jx": 0.0, "jy": 0.0}},
        {"ok": True, "click_target": {"x": float("nan"), "y": 5.0, "jx": 0.0, "jy": 0.0}},
    ],
)
def test_a_box_we_cannot_read_is_no_box_at_all(payload: dict[str, Any]) -> None:
    """Refusing here costs a fallback to the old click. Guessing costs a misclick."""
    assert parse_click_target(payload) is None


def test_the_frame_origin_is_the_first_corner_of_the_content_quad() -> None:
    """``DOM.getBoxModel`` reports the content box, which is the frame's viewport.

    Border and padding on the iframe element sit outside it, so the content
    quad's top-left is exactly where the embedded document's own (0, 0) is.
    """
    quad = [64.0, 410.0, 664.0, 410.0, 664.0, 1210.0, 64.0, 1210.0]

    assert content_box_origin(quad) == (64.0, 410.0)


@pytest.mark.parametrize("quad", [[], [1.0], [1.0, 2.0, 3.0], None, "64,410", [float("inf"), 410.0]])
def test_a_quad_we_cannot_read_leaves_the_frame_unlocated(quad: Any) -> None:
    assert content_box_origin(quad) is None


# ---------------------------------------------------------------------------
# the event sequence
# ---------------------------------------------------------------------------


def _types(events: tuple[MouseEvent, ...]) -> list[str]:
    return [event.type_ for event in events]


def _moves_toward(point: Point, *, seed: int) -> list[MouseEvent]:
    events = mouse_event_sequence(point, rng=random.Random(seed))
    return [event for event in events if event.type_ == "mouseMoved"]


def test_a_click_is_an_approach_then_a_press_then_a_release() -> None:
    events = mouse_event_sequence(Point(300.0, 200.0), rng=random.Random(5))

    assert _types(events)[-2:] == ["mousePressed", "mouseReleased"]
    assert set(_types(events)[:-2]) == {"mouseMoved"}
    assert len(events) > 3


def test_the_cursor_arrives_on_the_control_before_it_presses() -> None:
    """The last move has to land exactly on the point, or the press hits elsewhere."""
    point = Point(300.0, 200.0)

    events = mouse_event_sequence(point, rng=random.Random(5))
    moves = [event for event in events if event.type_ == "mouseMoved"]

    assert (moves[-1].x, moves[-1].y) == (point.x, point.y)


def test_the_press_and_the_release_happen_without_the_mouse_drifting() -> None:
    """A press and release at different points is a drag, and can miss the control."""
    events = mouse_event_sequence(Point(300.0, 200.0), rng=random.Random(5))
    press, release = events[-2], events[-1]

    assert (press.x, press.y) == (release.x, release.y) == (300.0, 200.0)


def test_the_mouse_is_somewhere_else_before_it_is_on_the_control() -> None:
    """A press with no approach means the page never saw a pointer arrive.

    Hover-gated controls need the mousemove anyway, so this is as much about the
    click working as about how it looks.
    """
    point = Point(300.0, 200.0)

    first = mouse_event_sequence(point, rng=random.Random(5))[0]

    assert (first.x, first.y) != (point.x, point.y)


def test_the_approach_closes_on_the_control_rather_than_wandering() -> None:
    """The path may bow, but it may not overshoot and come back.

    A cursor that passes the button and returns is not a better imitation of a
    hand, and it drags the pointer across whatever else is on the way.
    """
    point = Point(300.0, 200.0)
    moves = _moves_toward(point, seed=5)

    distances = [math.hypot(move.x - point.x, move.y - point.y) for move in moves]

    assert distances == sorted(distances, reverse=True)


def test_the_press_is_the_left_button_held_and_then_let_go() -> None:
    events = mouse_event_sequence(Point(1.0, 1.0), rng=random.Random(5))
    press, release = events[-2], events[-1]

    assert (press.button, press.buttons, press.click_count) == ("left", 1, 1)
    assert (release.button, release.buttons, release.click_count) == ("left", 0, 1)


def test_the_approach_presses_nothing() -> None:
    moves = _moves_toward(Point(1.0, 1.0), seed=5)

    assert {(move.button, move.buttons) for move in moves} == {("none", 0)}


@pytest.mark.parametrize("seed", range(25))
def test_the_approach_holds_up_whatever_the_draw(seed: int) -> None:
    """The shape of the path is randomised, so one seed proves very little."""
    point = Point(640.0, 480.0)
    moves = _moves_toward(point, seed=seed)

    distances = [math.hypot(move.x - point.x, move.y - point.y) for move in moves]

    assert len(moves) >= 3
    assert distances == sorted(distances, reverse=True)
    assert distances[-1] == 0.0
    assert distances[0] > 0.0


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------


class _FakeInputDomain:
    """Stands in for ``nodriver.cdp.input_``, recording the calls made through it."""

    class MouseButton(str):
        pass

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def dispatch_mouse_event(self, type_: str, **kwargs: Any) -> dict[str, Any]:
        call = {"type": type_, **kwargs}
        self.calls.append(call)
        return call


class _FakeTab:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(self, command: dict[str, Any]) -> None:
        self.sent.append(command)


_PRESS_POINT = Point(300.0, 200.0)


def _dispatch() -> tuple[_FakeTab, _FakeInputDomain, list[float]]:
    tab, domain, waits = _FakeTab(), _FakeInputDomain(), []

    async def _sleep(seconds: float) -> None:
        waits.append(seconds)

    asyncio.run(dispatch_trusted_click(tab, _PRESS_POINT, cdp_input=domain, rng=random.Random(5), sleep=_sleep))
    return tab, domain, waits


def test_every_event_reaches_the_page_in_order() -> None:
    tab, domain, _ = _dispatch()

    assert tab.sent == domain.calls
    assert [call["type"] for call in tab.sent][-2:] == ["mousePressed", "mouseReleased"]


def test_the_button_is_handed_over_as_the_type_chrome_expects() -> None:
    """``dispatch_mouse_event`` takes a ``MouseButton``, not the bare string."""
    _, domain, _ = _dispatch()

    press = domain.calls[-2]
    assert isinstance(press["button"], _FakeInputDomain.MouseButton)
    assert str(press["button"]) == "left"


def test_the_click_is_held_for_about_as_long_as_a_finger_holds_it() -> None:
    """Press and release in the same millisecond is not a thing a hand does."""
    _, domain, waits = _dispatch()
    hold = waits[-1]

    assert 0.03 <= hold <= 0.20


def test_the_whole_click_stays_fast_enough_to_run_hundreds_of_times() -> None:
    _, _, waits = _dispatch()

    assert sum(waits) < 0.6
