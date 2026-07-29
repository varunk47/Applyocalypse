"""Wait for client-rendered pages to produce stable visible text before scraping.

ATS portals (Workday, Greenhouse embeds, Ashby) are SPAs that paint their text
seconds after navigation completes. Reading the DOM immediately yields an empty
page and a spurious JD-scrape pause, so adapters poll with this helper first.

The same problem appears after a click: a fixed sleep is simultaneously too short
for a cold-cache SPA route transition and wasteful for a click that changes
nothing. `wait_for_page_change` replaces those sleeps with a bounded poll.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

PAGE_TEXT_TIMEOUT_S = 15.0
PAGE_TEXT_POLL_INTERVAL_S = 0.5
PAGE_TEXT_STABLE_POLLS = 2
PAGE_TEXT_MIN_LENGTH = 200

# Post-click settling. The ceiling is what keeps a stuck portal from hanging the
# run: on expiry the wait returns timed_out=True instead of blocking forever.
POST_CLICK_TIMEOUT_S = 8.0
POST_CLICK_POLL_INTERVAL_S = 0.25
POST_CLICK_UNCHANGED_GRACE_S = 2.0
POST_CLICK_STABLE_POLLS = 2


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
    least `min_text_length` (defaulted high enough to skip header-only loading
    skeletons; real postings run thousands of characters). Probe exceptions count as an empty page (the page
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


async def wait_for_page_change(
    probe_fingerprint: Callable[[], Awaitable[str]],
    *,
    baseline: str,
    timeout_s: float = POST_CLICK_TIMEOUT_S,
    poll_interval_s: float = POST_CLICK_POLL_INTERVAL_S,
    unchanged_grace_s: float = POST_CLICK_UNCHANGED_GRACE_S,
    stable_polls: int = POST_CLICK_STABLE_POLLS,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, object]:
    """Poll a page fingerprint after a click until the page settles, or give up.

    Returns as soon as the fingerprint differs from `baseline` and has repeated
    `stable_polls` times, so a fast navigation costs one poll interval instead of
    a flat sleep. A fingerprint that stays equal to `baseline` is only accepted
    once `unchanged_grace_s` has elapsed, so an in-flight request still gets a
    settling window. A page that never stops changing is abandoned at `timeout_s`
    with `timed_out=True` — the wait is always bounded and never hangs the run.

    Probe exceptions are treated as "nothing observed" (empty fingerprint) rather
    than propagated: a detached target must not fail an otherwise good click.
    Always probes at least once, even with timeout_s=0.
    """
    started = clock()
    last_fingerprint: str | None = None
    streak = 0
    polls = 0
    while True:
        try:
            current = str(await probe_fingerprint())
        except Exception:
            current = ""
        polls += 1
        streak = streak + 1 if current == last_fingerprint else 1
        last_fingerprint = current
        changed = bool(current) and current != baseline
        elapsed = clock() - started
        settled = streak >= stable_polls and (changed or elapsed >= unchanged_grace_s)
        timed_out = not settled and elapsed >= timeout_s
        if settled or timed_out:
            return {
                "changed": changed,
                "timed_out": timed_out,
                "fingerprint": current,
                "waited_ms": int(max(elapsed, 0.0) * 1000),
                "polls": polls,
            }
        await sleep(poll_interval_s)
