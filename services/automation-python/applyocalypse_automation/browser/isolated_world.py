"""Runs read-only page probes where the page cannot watch or answer them.

Every question this worker asks a page -- which fields exist, what is blocking
the form, how much text has rendered, where a button is -- is asked by
evaluating JavaScript in the page's own main world. That world belongs to the
site. Anything the page loaded first has already had the chance to redefine
``document.querySelectorAll``, ``Element.prototype.getBoundingClientRect`` or
``JSON.stringify``, so an anti-bot script can both notice a probe happening and
decide what it reads back. The same instrumentation that watches for scripted
clicks watches for scripted reads, and a probe run through hooked builtins is
worse than no probe: it returns a plausible answer that is not true.

An isolated world is Chrome's own answer to this. It shares the DOM with the
page but keeps its own globals and its own prototype chain, so a probe sees the
real document through untouched builtins and leaves no trace in the world the
page can inspect. It is where Chrome extensions' content scripts run, and where
Puppeteer and Playwright run their internals, for exactly this reason.
``instanceof HTMLInputElement`` and friends still work, because Blink hands the
isolated world its own wrappers around the same nodes.

Writes deliberately stay in the main world. They exist to satisfy the page's
own framework -- React installs its value tracker as an own-property override
on the element, in the main world -- so moving them would break form filling
rather than hide it. This module is for reads only.

A context belongs to one document, so navigating away destroys it. Rather than
subscribing to lifecycle events, a dead context surfaces as a failed evaluate
and the next call builds a new one. If any part of that fails the caller runs
the probe the old way, in the main world: this is a better way to read, not a
new requirement to read at all.
"""

from __future__ import annotations

from typing import Any

# Chrome shows the world name in DevTools and nowhere the page can reach, so
# this is for whoever is debugging a run, not for hiding.
DEFAULT_WORLD_NAME = "applyocalypse"


class NoIsolatedWorld(Exception):
    """Chrome would not give us a context for this frame.

    Raised only inside this module, where it means "fall back", never surfaced
    to a caller: a caller sees a refusal, not an exception.
    """


def _cdp_module(override: Any = None) -> Any:
    """The ``nodriver.cdp`` package, imported only when a browser is live.

    Deferred for the same reason ``human_typing`` and ``trusted_click`` defer
    it: the document pipeline runs where no browser stack exists, and a
    top-level import would make importing this module fail there.
    """
    if override is not None:
        return override
    from nodriver import cdp  # type: ignore[import-not-found]

    return cdp


def _frame_key(frame: Any) -> str:
    """A stable identity for a frame, for as long as the frame is alive.

    Chrome gives an out-of-process frame its own target, so the target id is
    both stable and distinct per frame. Falling back to the object's identity
    keeps a driver that reports no target from sharing one cached context
    across every frame on the page, which would send probes to the wrong
    document rather than merely failing.
    """
    target_id = getattr(getattr(frame, "target", None), "target_id", None)
    if target_id:
        return str(target_id)
    return f"object:{id(frame)}"


class IsolatedWorlds:
    """One isolated execution context per frame, made on demand and reused.

    Creating a world costs a round trip and Chrome keeps it for the life of the
    document, so it is worth caching. It is not worth tracking: a context that
    has gone away shows up as a failed evaluate, and the retry that follows
    replaces it.
    """

    __slots__ = ("_cdp", "_contexts", "_world_name")

    def __init__(self, *, cdp_module: Any = None, world_name: str = DEFAULT_WORLD_NAME) -> None:
        self._cdp = cdp_module
        self._world_name = world_name
        self._contexts: dict[str, Any] = {}

    def forget_all(self) -> None:
        """Drop every cached context, because the documents holding them are gone.

        Chrome may reuse an execution context id once the context it named has
        been destroyed. Self-healing catches that a beat late, after one probe
        has already read from whatever now holds the id, so a navigation says so
        up front instead.
        """
        self._contexts.clear()

    async def evaluate(self, frame: Any, script: str) -> tuple[bool, Any]:
        """Run ``script`` in this frame's isolated world.

        Returns ``(True, value)`` when the probe ran, and ``(False, None)`` for
        every way it might not have. A refusal is not an error: the caller runs
        the same script in the main world, which is where it ran before this
        module existed.
        """
        key = _frame_key(frame)
        try:
            return await self._attempt(frame, key, script)
        except Exception:
            self._contexts.pop(key, None)

        # One retry with a fresh world. Far and away the likeliest reason the
        # first try failed is that the page navigated and took the context with
        # it, and a probe is usually asked for right after a navigation.
        try:
            return await self._attempt(frame, key, script)
        except Exception:
            self._contexts.pop(key, None)
            return (False, None)

    async def _attempt(self, frame: Any, key: str, script: str) -> tuple[bool, Any]:
        context_id = self._contexts.get(key)
        if context_id is None:
            context_id = await self._create_context(frame)
            self._contexts[key] = context_id
        return await self._evaluate_in(frame, context_id, script)

    async def _create_context(self, frame: Any) -> Any:
        """Ask Chrome for a world in this frame's document.

        ``Page.getFrameTree`` is sent to the frame itself rather than to the
        page above it, so an out-of-process apply frame reports its own id as
        the root and the same two calls work for the top document and for an
        embedded one.
        """
        cdp = _cdp_module(self._cdp)
        tree = await frame.send(cdp.page.get_frame_tree())
        frame_id = getattr(getattr(tree, "frame", None), "id_", None)
        if frame_id is None:
            raise NoIsolatedWorld("the frame did not report an id")

        context_id = await frame.send(
            cdp.page.create_isolated_world(frame_id=frame_id, world_name=self._world_name)
        )
        if context_id is None:
            raise NoIsolatedWorld("chrome returned no execution context")
        return context_id

    async def _evaluate_in(self, frame: Any, context_id: Any, script: str) -> tuple[bool, Any]:
        """Evaluate in a known context, telling a dead world from a bad script.

        A destroyed context makes the command itself fail, which is worth one
        retry in a new world. A script that threw comes back as a normal
        response carrying exception details, and would throw again just the
        same, so that one goes straight to the caller's fallback.
        """
        cdp = _cdp_module(self._cdp)
        response = await frame.send(
            cdp.runtime.evaluate(
                expression=script,
                context_id=context_id,
                return_by_value=True,
                await_promise=True,
            )
        )
        remote, exception_details = response if isinstance(response, tuple) else (response, None)
        if remote is None or exception_details is not None:
            return (False, None)
        return (True, getattr(remote, "value", None))
