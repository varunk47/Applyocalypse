"""Executable tests for probes that run outside the page's own JavaScript world.

Every read this worker performs used to run in the main world, where the site's
own scripts live. A page that has replaced ``document.querySelectorAll`` or
``Element.prototype.getBoundingClientRect`` can both watch a probe happen and
decide what it returns, and an answer that is quietly wrong is worse than no
answer: the run carries on and fills nothing.

An isolated world shares the DOM and nothing else. These pin the two halves of
that: the probe really does go to a separate context, and every way that can
fail lands back in the main world instead of losing the read.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from applyocalypse_automation.browser.adapter import BrowserField
from applyocalypse_automation.browser.isolated_world import DEFAULT_WORLD_NAME, IsolatedWorlds
from applyocalypse_automation.browser.nodriver_adapter import NodriverBrowserAdapter

PROBE = "document.querySelectorAll('input').length"


def fake_cdp() -> SimpleNamespace:
    """Enough of ``nodriver.cdp`` to record what was asked for.

    The real commands are generators a Tab drives onto a socket; these are
    plain dicts, because what matters here is which command was built and with
    which arguments.
    """
    return SimpleNamespace(
        page=SimpleNamespace(
            get_frame_tree=lambda: {"command": "Page.getFrameTree"},
            create_isolated_world=lambda frame_id, world_name=None: {
                "command": "Page.createIsolatedWorld",
                "frameId": frame_id,
                "worldName": world_name,
            },
        ),
        runtime=SimpleNamespace(
            evaluate=lambda expression, context_id=None, return_by_value=None, await_promise=None: {
                "command": "Runtime.evaluate",
                "expression": expression,
                "contextId": context_id,
                "returnByValue": return_by_value,
                "awaitPromise": await_promise,
            },
        ),
    )


class FakeFrame:
    """A frame that answers CDP commands, and can be told to stop answering."""

    def __init__(
        self,
        *,
        frame_id: str | None = "FRAME-1",
        target_id: str | None = "TARGET-1",
        value: Any = 7,
        threw_in_page: bool = False,
        evaluate_failures: int = 0,
        empty_response: bool = False,
        context_ids: list[int] | None = None,
    ) -> None:
        self.target = SimpleNamespace(target_id=target_id) if target_id else None
        self._frame_id = frame_id
        self._value = value
        self._threw_in_page = threw_in_page
        self._evaluate_failures = evaluate_failures
        self._empty_response = empty_response
        self._context_ids = list(context_ids or [11, 22, 33])
        self.commands: list[dict[str, Any]] = []
        self.main_world_scripts: list[str] = []

    async def send(self, command: dict[str, Any]) -> Any:
        self.commands.append(command)
        name = command["command"]
        if name == "Page.getFrameTree":
            return SimpleNamespace(frame=SimpleNamespace(id_=self._frame_id))
        if name == "Page.createIsolatedWorld":
            return self._context_ids.pop(0)
        if name == "Runtime.evaluate":
            if self._evaluate_failures > 0:
                self._evaluate_failures -= 1
                raise RuntimeError("Cannot find context with specified id")
            if self._empty_response:
                return None
            details = SimpleNamespace(text="ReferenceError: x is not defined") if self._threw_in_page else None
            return (SimpleNamespace(value=self._value), details)
        raise AssertionError(f"unexpected command {name}")

    async def evaluate(self, script: str) -> str:
        self.main_world_scripts.append(script)
        return "answered by the page"


class MuteFrame:
    """A driver object with no CDP channel at all, which some frames really are."""

    def __init__(self) -> None:
        self.main_world_scripts: list[str] = []

    async def evaluate(self, script: str) -> str:
        self.main_world_scripts.append(script)
        return "answered by the page"


def sent(frame: FakeFrame, name: str) -> list[dict[str, Any]]:
    return [command for command in frame.commands if command["command"] == name]


def probe(frame: Any, pool: IsolatedWorlds | None = None, script: str = PROBE) -> tuple[bool, Any]:
    return asyncio.run((pool or IsolatedWorlds(cdp_module=fake_cdp())).evaluate(frame, script))


# ---------------------------------------------------------------------------
# reading from somewhere the page cannot reach
# ---------------------------------------------------------------------------


def test_a_probe_runs_in_a_context_the_page_does_not_own() -> None:
    frame = FakeFrame()

    ok, value = probe(frame)

    assert (ok, value) == (True, 7)
    assert sent(frame, "Page.createIsolatedWorld")[0]["frameId"] == "FRAME-1"
    assert sent(frame, "Runtime.evaluate")[0]["contextId"] == 11
    assert sent(frame, "Runtime.evaluate")[0]["expression"] == PROBE
    assert frame.main_world_scripts == [], "the page was asked after all"


def test_the_answer_comes_back_as_a_value_not_a_handle() -> None:
    """Callers parse these directly, exactly as they parsed ``frame.evaluate``."""
    frame = FakeFrame(value={"fields": []})

    ok, value = probe(frame)

    assert (ok, value) == (True, {"fields": []})
    assert sent(frame, "Runtime.evaluate")[0]["returnByValue"] is True
    assert sent(frame, "Runtime.evaluate")[0]["awaitPromise"] is True


def test_the_world_is_named_so_a_live_run_can_be_read_in_devtools() -> None:
    frame = FakeFrame()

    probe(frame)

    assert sent(frame, "Page.createIsolatedWorld")[0]["worldName"] == DEFAULT_WORLD_NAME


def test_the_frame_is_asked_for_its_own_id_rather_than_the_page_above_it() -> None:
    """An embedded apply frame is its own target, so its tree root is itself."""
    frame = FakeFrame(frame_id="EMBEDDED-FRAME")

    probe(frame)

    assert sent(frame, "Page.createIsolatedWorld")[0]["frameId"] == "EMBEDDED-FRAME"


# ---------------------------------------------------------------------------
# one world per document, kept for as long as the document lasts
# ---------------------------------------------------------------------------


def test_the_world_is_built_once_and_reused() -> None:
    """Discovery, blockers and the fingerprint all probe the same document."""
    frame = FakeFrame()
    pool = IsolatedWorlds(cdp_module=fake_cdp())

    probe(frame, pool)
    probe(frame, pool)

    assert len(sent(frame, "Page.createIsolatedWorld")) == 1
    assert len(sent(frame, "Runtime.evaluate")) == 2


def test_each_frame_gets_its_own_world() -> None:
    """A context belongs to one document. Sharing one would read the wrong page."""
    top = FakeFrame(target_id="TOP", context_ids=[11])
    embedded = FakeFrame(target_id="EMBEDDED", context_ids=[99])
    pool = IsolatedWorlds(cdp_module=fake_cdp())

    probe(top, pool)
    probe(embedded, pool)

    assert sent(top, "Runtime.evaluate")[0]["contextId"] == 11
    assert sent(embedded, "Runtime.evaluate")[0]["contextId"] == 99


def test_frames_a_driver_cannot_name_are_still_kept_apart() -> None:
    """Without a target id, identity is all there is, and it has to be enough."""
    first = FakeFrame(target_id=None, context_ids=[11])
    second = FakeFrame(target_id=None, context_ids=[99])
    pool = IsolatedWorlds(cdp_module=fake_cdp())

    probe(first, pool)
    probe(second, pool)

    assert sent(second, "Runtime.evaluate")[0]["contextId"] == 99


def test_a_navigation_drops_the_cache_before_the_next_probe_uses_it() -> None:
    """Chrome can hand a retired context id back out, so waiting to find out is a risk."""
    frame = FakeFrame()
    pool = IsolatedWorlds(cdp_module=fake_cdp())

    probe(frame, pool)
    pool.forget_all()
    probe(frame, pool)

    assert len(sent(frame, "Page.createIsolatedWorld")) == 2


# ---------------------------------------------------------------------------
# every way this can fail, which all end in the main world
# ---------------------------------------------------------------------------


def test_a_context_lost_to_a_navigation_is_replaced_not_reported() -> None:
    """Probes are usually asked for right after a navigation, so this is the common case."""
    frame = FakeFrame(evaluate_failures=1)

    ok, value = probe(frame)

    assert (ok, value) == (True, 7)
    assert len(sent(frame, "Page.createIsolatedWorld")) == 2
    assert sent(frame, "Runtime.evaluate")[1]["contextId"] == 22
    assert frame.main_world_scripts == []


def test_a_second_failure_gives_up_rather_than_looping() -> None:
    """A frame mid-detach fails every time, and a probe must not become a spin."""
    frame = FakeFrame(evaluate_failures=5)

    assert probe(frame) == (False, None)
    assert len(sent(frame, "Page.createIsolatedWorld")) == 2
    assert len(sent(frame, "Runtime.evaluate")) == 2


def test_a_probe_that_threw_inside_the_page_is_not_retried() -> None:
    """A fresh world runs the same script into the same error, so retrying buys nothing."""
    frame = FakeFrame(threw_in_page=True)

    assert probe(frame) == (False, None)
    assert len(sent(frame, "Page.createIsolatedWorld")) == 1


def test_a_frame_with_no_id_is_a_refusal_not_a_guess() -> None:
    """Creating a world for the wrong frame would read a document we did not mean to."""
    frame = FakeFrame(frame_id=None)

    assert probe(frame) == (False, None)
    assert sent(frame, "Runtime.evaluate") == []


def test_a_send_that_answers_with_nothing_is_a_refusal() -> None:
    """An empty response is not an empty page, and reporting it as one loses the form."""
    frame = FakeFrame(empty_response=True)

    assert probe(frame) == (False, None)


def test_a_driver_with_no_cdp_channel_is_a_refusal_not_a_crash() -> None:
    """Not every object a driver calls a frame can be sent commands."""
    assert probe(MuteFrame()) == (False, None)


# ---------------------------------------------------------------------------
# what the adapter does with a refusal
# ---------------------------------------------------------------------------


def test_a_refused_world_falls_back_to_the_page_own_world() -> None:
    """This is what makes the change strictly no worse: stealth is lost, not the read."""
    adapter = NodriverBrowserAdapter()
    frame = MuteFrame()

    value = asyncio.run(adapter._read(frame, PROBE))

    assert value == "answered by the page"
    assert frame.main_world_scripts == [PROBE]


def test_a_working_world_keeps_the_read_away_from_the_page() -> None:
    adapter = NodriverBrowserAdapter()
    adapter._worlds = IsolatedWorlds(cdp_module=fake_cdp())
    frame = FakeFrame()

    value = asyncio.run(adapter._read(frame, PROBE))

    assert value == 7
    assert frame.main_world_scripts == []


def test_a_write_is_never_offered_an_isolated_world() -> None:
    """React installs its value tracker in the main world, so a hidden write is a lost one.

    ``select`` is one of the field types written by script rather than typed,
    which makes it the shortest path to the write branch.
    """
    adapter = NodriverBrowserAdapter()
    adapter._worlds = IsolatedWorlds(cdp_module=fake_cdp())
    frame = FakeFrame()
    adapter._page = frame

    asyncio.run(
        adapter.apply_field_value(
            BrowserField(
                field_id="country",
                label="Country",
                field_type="select",
                selector="#country",
                required=True,
                confidence=1.0,
            ),
            "India",
        )
    )

    assert len(frame.main_world_scripts) == 1
    assert "#country" in frame.main_world_scripts[0]
    assert sent(frame, "Runtime.evaluate") == []
