"""Presses a control with the mouse instead of calling ``element.click()``.

Every click this worker has made so far was injected JavaScript: the discovery
script finds the button and then calls ``.click()`` on it from inside the page.
The search that precedes it is careful, but the event it produces carries
``isTrusted: false``, and that is the cheapest question a bot detector can ask.
No amount of care about *which* button we press hides an event the browser
itself labels as synthetic.

The replacement splits the work. The page still decides which control matches,
because only the page can read the DOM; but it reports coordinates instead of
clicking, and the press is dispatched from outside as ``Input.dispatchMouseEvent``,
which Chrome delivers through the same path as a real mouse.

Two things make this less trivial than it sounds.

**Coordinates cross a frame boundary.** ``getBoundingClientRect()`` inside a
cross-origin apply frame is measured from that frame's own viewport, while the
input event is dispatched against the top-level document. Sending the frame's
number would click a point up and to the left of the button, and on an
application form the control underneath is not always harmless. So an embedded
frame's origin is translated first, via the content box of its owner element,
and a frame we cannot locate falls back to the injected click rather than
guessing.

**A coordinate can be occluded.** A cookie banner or a sticky header sitting
over the button means the point reaches the banner, not the control. So the page
hit-tests the point before reporting it, and jitter is confined to a box whose
extremes were hit-tested too.

The seams here mirror ``human_typing``: injected ``rng`` and ``sleep`` so the
timing is testable, and a deferred ``nodriver.cdp`` import so the document
pipeline can import this module in an environment with no browser stack.
"""

from __future__ import annotations

import asyncio
import math
import random
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

# The cursor arrives from somewhere off the control rather than materialising on
# it. Far enough that the page sees a genuine approach, near enough that the
# whole gesture stays inside a viewport.
APPROACH_MIN_DISTANCE_PX = 40.0
APPROACH_MAX_DISTANCE_PX = 120.0

# Between two and four waypoints before the one that lands on the target, at
# randomly spaced fractions of the way in, so no two approaches share a rhythm.
APPROACH_MIN_STEPS = 2
APPROACH_MAX_STEPS = 4
APPROACH_MIN_FRACTION = 0.15
APPROACH_MAX_FRACTION = 0.95

# A shallow arc, since a hand does not move in a straight line. Kept well under
# the minimum approach distance so the path still closes on the target at every
# step: the bow peaks mid-path and is zero at both ends.
APPROACH_MAX_BOW_PX = 8.0

MIN_MOVE_DELAY_S = 0.010
MAX_MOVE_DELAY_S = 0.025
MIN_SETTLE_DELAY_S = 0.030
MAX_SETTLE_DELAY_S = 0.090
MIN_HOLD_DELAY_S = 0.050
MAX_HOLD_DELAY_S = 0.110


@dataclass(frozen=True, slots=True)
class Point:
    """A viewport coordinate in the top-level document."""

    x: float
    y: float


@dataclass(frozen=True, slots=True)
class ClickTarget:
    """A region of a control that the page confirmed the cursor can reach.

    ``x`` and ``y`` are the centre in the reporting frame's own viewport. The
    jitter half-extents bound a box whose centre and four corners were all
    hit-tested, so any point inside it lands on the intended control.
    """

    x: float
    y: float
    jitter_x: float
    jitter_y: float


@dataclass(frozen=True, slots=True)
class MouseEvent:
    """One ``Input.dispatchMouseEvent`` call, as plain data.

    ``button`` stays a string here so the sequence can be built and asserted on
    without a browser; the CDP enum is applied at dispatch, where the real
    module is in hand.
    """

    type_: str
    x: float
    y: float
    button: str = "none"
    buttons: int = 0
    click_count: int = 0

    def as_cdp_kwargs(self) -> dict[str, Any]:
        return {
            "x": self.x,
            "y": self.y,
            "button": self.button,
            "buttons": self.buttons,
            "click_count": self.click_count,
        }


def _cdp_input_module(override: Any = None) -> Any:
    """The ``nodriver.cdp.input_`` module, imported only when a browser is live.

    Deferred for the same reason ``human_typing`` defers it: the document
    pipeline runs where no browser stack exists, and a top-level import would
    make importing this module fail there.
    """
    if override is not None:
        return override
    from nodriver import cdp  # type: ignore[import-not-found]

    return cdp.input_


def _finite_float(value: Any) -> float | None:
    """A coordinate we are willing to click at, or ``None``.

    Booleans are rejected despite being integers, and so are NaN and the
    infinities: every one of them would otherwise reach ``dispatchMouseEvent``
    as a position.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def parse_click_target(payload: Mapping[str, Any]) -> ClickTarget | None:
    """The reachable box the locate script reported, if it reported a usable one.

    Returning ``None`` costs a fallback to the injected click, which still
    works. Accepting a half-read box costs a click at the wrong coordinate, so
    anything short of four finite numbers is refused.
    """
    if not isinstance(payload, Mapping):
        return None
    raw = payload.get("click_target")
    if not isinstance(raw, Mapping):
        return None

    x = _finite_float(raw.get("x"))
    y = _finite_float(raw.get("y"))
    jitter_x = _finite_float(raw.get("jx"))
    jitter_y = _finite_float(raw.get("jy"))
    if x is None or y is None or jitter_x is None or jitter_y is None:
        return None

    return ClickTarget(x=x, y=y, jitter_x=abs(jitter_x), jitter_y=abs(jitter_y))


def content_box_origin(quad: Any) -> tuple[float, float] | None:
    """Where an embedded frame's own (0, 0) sits in the top-level viewport.

    ``DOM.getBoxModel`` reports the iframe element's content box as eight
    numbers, four corners clockwise from the top-left. Border and padding on the
    iframe lie outside that box, so its first corner is exactly the origin the
    embedded document measures its own rectangles from.
    """
    if isinstance(quad, (str, bytes)) or not isinstance(quad, Sequence) or len(quad) < 8:
        return None

    x = _finite_float(quad[0])
    y = _finite_float(quad[1])
    if x is None or y is None:
        return None

    return (x, y)


def aim_point(
    target: ClickTarget,
    origin: tuple[float, float] = (0.0, 0.0),
    rng: random.Random | None = None,
) -> Point:
    """Where to press, in top-level viewport coordinates.

    ``origin`` is the reporting frame's offset, zero for the top document. The
    draw is confined to the box the page verified, so varying the point costs
    nothing in accuracy: a control too small to have any slack is simply clicked
    dead centre.
    """
    generator = rng if rng is not None else random.Random()
    offset_x = generator.uniform(-target.jitter_x, target.jitter_x) if target.jitter_x else 0.0
    offset_y = generator.uniform(-target.jitter_y, target.jitter_y) if target.jitter_y else 0.0
    return Point(x=origin[0] + target.x + offset_x, y=origin[1] + target.y + offset_y)


def _approach(point: Point, rng: random.Random) -> list[Point]:
    """Waypoints leading in to ``point``, the last one exactly on it.

    Each waypoint sits at a fraction of the way along a bowed path from a random
    starting offset. Because the bow is zero at both ends and peaks in the
    middle, and because the fractions increase, every step is strictly closer to
    the target than the one before: an approach that overshoots and comes back
    would be a worse imitation of a hand, not a better one.
    """
    angle = rng.uniform(0.0, 2.0 * math.pi)
    distance = rng.uniform(APPROACH_MIN_DISTANCE_PX, APPROACH_MAX_DISTANCE_PX)
    toward_x, toward_y = math.cos(angle), math.sin(angle)
    bow = rng.uniform(-APPROACH_MAX_BOW_PX, APPROACH_MAX_BOW_PX)

    steps = rng.randint(APPROACH_MIN_STEPS, APPROACH_MAX_STEPS)
    fractions = sorted(rng.uniform(APPROACH_MIN_FRACTION, APPROACH_MAX_FRACTION) for _ in range(steps))

    waypoints: list[Point] = []
    for fraction in [*fractions, 1.0]:
        remaining = (1.0 - fraction) * distance
        sideways = bow * 4.0 * fraction * (1.0 - fraction)
        waypoints.append(
            Point(
                x=point.x - remaining * toward_x - sideways * toward_y,
                y=point.y - remaining * toward_y + sideways * toward_x,
            )
        )
    return waypoints


def mouse_event_sequence(point: Point, rng: random.Random | None = None) -> tuple[MouseEvent, ...]:
    """The moves, press and release that make up one click.

    The moves matter beyond appearances: a control that only becomes clickable
    on hover never opens for a press that arrives with no pointer motion in
    front of it.
    """
    generator = rng if rng is not None else random.Random()
    events = [MouseEvent("mouseMoved", waypoint.x, waypoint.y) for waypoint in _approach(point, generator)]
    events.append(MouseEvent("mousePressed", point.x, point.y, button="left", buttons=1, click_count=1))
    events.append(MouseEvent("mouseReleased", point.x, point.y, button="left", buttons=0, click_count=1))
    return tuple(events)


def _mouse_command(input_domain: Any, event: MouseEvent) -> Any:
    kwargs = event.as_cdp_kwargs()
    kwargs["button"] = input_domain.MouseButton(kwargs["button"])
    return input_domain.dispatch_mouse_event(event.type_, **kwargs)


async def dispatch_trusted_click(
    tab: Any,
    point: Point,
    *,
    cdp_input: Any = None,
    rng: random.Random | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Move to ``point`` and click it, as input events rather than page script.

    ``tab`` is the top-level page: mouse input is routed by the browser process
    through hit-testing on the root widget, so an embedded frame's own target is
    the wrong place to send it even when the control lives there. Keyboard input
    is the opposite case, which is why ``human_typing`` sends to the element's
    own tab and this does not.
    """
    input_domain = _cdp_input_module(cdp_input)
    generator = rng if rng is not None else random.Random()
    *moves, press, release = mouse_event_sequence(point, generator)

    for move in moves[:-1]:
        await tab.send(_mouse_command(input_domain, move))
        await sleep(generator.uniform(MIN_MOVE_DELAY_S, MAX_MOVE_DELAY_S))

    await tab.send(_mouse_command(input_domain, moves[-1]))
    await sleep(generator.uniform(MIN_SETTLE_DELAY_S, MAX_SETTLE_DELAY_S))
    await tab.send(_mouse_command(input_domain, press))
    await sleep(generator.uniform(MIN_HOLD_DELAY_S, MAX_HOLD_DELAY_S))
    await tab.send(_mouse_command(input_domain, release))
