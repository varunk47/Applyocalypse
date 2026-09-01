"""Brings a control into view with the wheel instead of teleporting to it.

``Element.scrollIntoView()`` is how the locate script used to reach an apply
button below the fold, and it is a tell twice over. It teleports: the viewport
goes from one offset to another in a single frame with no positions in between,
which nothing a hand does produces. And it arrives with nothing behind it -- a
``scroll`` event fires, but no ``wheel``, no pointer motion, nothing the browser
marks as trusted. A page that watches for wheel input before deciding whether a
session is a person sees a viewport that moved on its own.

The replacement has the same shape as ``trusted_click``. The page still
measures, because only the page can read layout, but it reports how far it needs
to move instead of moving, and the scrolling is dispatched from outside as
``Input.dispatchMouseEvent`` with ``type: 'mouseWheel'``. Chrome routes that
through the same path as a real wheel, hit-testing which scroller sits under the
cursor, which is why the anchor point matters and why an embedded frame's has to
be translated the same way a click's is.

Notches, not one large delta. A wheel reports in discrete steps of roughly a
hundred pixels, so a thousand-pixel scroll is about ten events; the gaps between
them are log-normal for the reason ``human_typing``'s inter-key gaps are, in
that a hand moves in bursts with pauses in them and an even cadence is its own
signature.

None of this is load-bearing. A scroll that cannot be planned, cannot be aimed,
or fails part way through leaves the caller exactly where it already was, which
is the injected ``element.click()`` that worked before any of this existed.
"""

from __future__ import annotations

import asyncio
import math
import random
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .trusted_click import Point

# One notch of a wheel is about a hundred pixels in Chrome, and no two devices
# agree on the number. Drawing around it keeps a run from reporting the same
# delta every time, which a fixed constant would.
MIN_NOTCH_PX = 90.0
MAX_NOTCH_PX = 130.0

# Log-normal seconds between notches. The median sits at e**MU, and the clamp
# keeps a long page from spending the tail of the distribution on every step.
GAP_MU = -2.8
GAP_SIGMA = 0.6
MIN_GAP_S = 0.015
MAX_GAP_S = 0.6

# Under this, the control is close enough to press and a scroll would be motion
# for its own sake.
MIN_TRAVEL_PX = 8.0

# Past this the page either grew under us or reported something that is not a
# distance. Refusing costs the injected click, which does not care where the
# control is.
MAX_TRAVEL_PX = 15000.0


@dataclass(frozen=True, slots=True)
class ScrollAnchor:
    """Where to put the cursor to scroll, and how far to scroll it.

    ``point`` is in top-level viewport coordinates, already translated out of the
    reporting frame, because the wheel is dispatched against the top-level
    target and Chrome decides from that point which scroller moves.
    """

    point: Point
    travel_px: float


def _cdp_input_module(override: Any = None) -> Any:
    """The ``nodriver.cdp.input_`` module, imported only when a browser is live.

    Deferred for the same reason ``trusted_click`` defers it: the document
    pipeline runs where no browser stack exists, and a top-level import would
    make importing this module fail there.
    """
    if override is not None:
        return override
    from nodriver import cdp  # type: ignore[import-not-found]

    return cdp.input_


def _number(value: Any) -> float | None:
    """A distance we are willing to act on, or ``None``.

    Booleans are rejected despite being integers, and so are NaN and the
    infinities, every one of which would otherwise reach a wheel event.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def parse_scroll_anchor(
    payload: Mapping[str, Any],
    origin: tuple[float, float] = (0.0, 0.0),
) -> ScrollAnchor | None:
    """The scroll the locate script asked for, if it asked for a usable one.

    ``origin`` is the reporting frame's offset, zero for the top document.
    Returning ``None`` means no wheel is sent, which costs the fallback the
    caller already had rather than a scroll of a guessed distance.
    """
    if not isinstance(payload, Mapping):
        return None
    raw = payload.get("scroll_by")
    if not isinstance(raw, Mapping):
        return None

    travel = _number(raw.get("y"))
    anchor_x = _number(raw.get("ax"))
    anchor_y = _number(raw.get("ay"))
    if travel is None or anchor_x is None or anchor_y is None:
        return None

    return ScrollAnchor(point=Point(x=origin[0] + anchor_x, y=origin[1] + anchor_y), travel_px=travel)


def scroll_notches(travel_px: float, rng: random.Random | None = None) -> tuple[float, ...]:
    """The wheel deltas that add up to ``travel_px``, in order.

    Empty means the distance is not one to scroll: too small to be worth a
    gesture, too large to be a real page, or not a number at all. The last notch
    is whatever is left over rather than a whole one, because overshooting would
    put the control back outside the viewport it was being brought into.
    """
    distance = _number(travel_px)
    if distance is None or not MIN_TRAVEL_PX <= abs(distance) <= MAX_TRAVEL_PX:
        return ()

    generator = rng if rng is not None else random.Random()
    direction = 1.0 if distance > 0 else -1.0
    remaining = abs(distance)
    notches: list[float] = []
    while remaining > 0.0:
        notch = min(remaining, generator.uniform(MIN_NOTCH_PX, MAX_NOTCH_PX))
        notches.append(direction * notch)
        remaining -= notch
    return tuple(notches)


def gap_seconds(rng: random.Random | None = None) -> float:
    """How long to wait before the next notch."""
    generator = rng if rng is not None else random.Random()
    return min(MAX_GAP_S, max(MIN_GAP_S, generator.lognormvariate(GAP_MU, GAP_SIGMA)))


async def dispatch_wheel_scroll(
    tab: Any,
    anchor: ScrollAnchor,
    *,
    cdp_input: Any = None,
    rng: random.Random | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> bool:
    """Wheel the scroller under ``anchor`` by its travel. ``False`` sent nothing.

    ``tab`` is the top-level page, for the reason ``dispatch_trusted_click``
    takes the top-level page: wheel input is routed by the browser process by
    hit-testing the root widget, so an embedded frame's own target is the wrong
    place to send it even when the control lives inside that frame.
    """
    notches = scroll_notches(anchor.travel_px, rng)
    if not notches:
        return False

    input_domain = _cdp_input_module(cdp_input)
    generator = rng if rng is not None else random.Random()
    for notch in notches:
        await tab.send(
            input_domain.dispatch_mouse_event(
                "mouseWheel",
                x=anchor.point.x,
                y=anchor.point.y,
                delta_x=0.0,
                delta_y=notch,
            )
        )
        # After the last notch too: the page has just been scrolled and is about
        # to be measured again, and a measurement taken in the same tick as the
        # event that moved the page is a measurement of where it used to be.
        await sleep(gap_seconds(generator))
    return True
