"""Wait for client-rendered pages to produce stable visible text before scraping.

ATS portals (Workday, Greenhouse embeds, Ashby) are SPAs that paint their text
seconds after navigation completes. Reading the DOM immediately yields an empty
page and a spurious JD-scrape pause, so adapters poll with this helper first.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

PAGE_TEXT_TIMEOUT_S = 15.0
PAGE_TEXT_POLL_INTERVAL_S = 0.5
PAGE_TEXT_STABLE_POLLS = 2
PAGE_TEXT_MIN_LENGTH = 1


async def wait_for_page_text(
    probe_text_length: Callable[[], Awaitable[int]],
    *,
    timeout_s: float = PAGE_TEXT_TIMEOUT_S,
    poll_interval_s: float = PAGE_TEXT_POLL_INTERVAL_S,
    min_text_length: int = PAGE_TEXT_MIN_LENGTH,
    stable_polls: int = PAGE_TEXT_STABLE_POLLS,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, object]:
    """Poll until visible text is non-empty and stable, or the timeout elapses.

    Ready means `stable_polls` consecutive probes returned the same length of at
    least `min_text_length`. Probe exceptions count as an empty page (the page
    may still be booting). Always probes at least once, even with timeout_s=0.
    """
    started = clock()
    last_length = -1
    streak = 0
    polls = 0
    while True:
        try:
            length = int(await probe_text_length())
        except Exception:
            length = 0
        polls += 1
        if length >= min_text_length:
            streak = streak + 1 if length == last_length else 1
        else:
            streak = 0
        last_length = length
        ready = streak >= stable_polls
        if ready or clock() - started >= timeout_s:
            return {
                "ready": ready,
                "text_length": max(length, 0),
                "waited_ms": int((clock() - started) * 1000),
                "polls": polls,
            }
        await sleep(poll_interval_s)
