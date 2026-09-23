from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .adapter import BrowserAdapter, BrowserBlocker, BrowserField, BrowserStepResult, screenshot_payload
from .cdp_input import CdpTarget
from .chrome_discovery import discover_chrome_executable
from .field_detection import (
    DOM_BLOCKER_DISCOVERY_SCRIPT,
    DOM_FIELD_DISCOVERY_SCRIPT,
    DOM_METADATA_CAPTURE_SCRIPT,
    DOM_REACHED_FRAME_URLS_JS,
    DOM_VISIBLE_TEXT_SCRIPT,
    SCRIPTED_WRITE_FIELD_TYPES,
    FrameRef,
    blockers_from_dom_snapshot,
    build_apply_field_value_script,
    build_click_by_text_script,
    build_final_submit_script,
    dom_path_for,
    driver_can_locate,
    fields_from_dom_snapshot,
    frame_url_is_worth_scanning,
    parse_apply_field_result,
    parse_click_by_text_result,
    parse_final_submit_result,
)
from .field_write import verify_or_repair_text_write
from .human_scroll import dispatch_wheel_scroll, parse_scroll_anchor
from .human_typing import clear_element, type_into_element
from .navigation_warmup import WARM_UP_TIMEOUT_S, dwell_seconds, origin_of, warm_up_target
from .page_readiness import (
    PAGE_TEXT_POLL_INTERVAL_S,
    PAGE_TEXT_TIMEOUT_S,
    POST_CLICK_POLL_INTERVAL_S,
    POST_CLICK_TIMEOUT_S,
    POST_CLICK_UNCHANGED_GRACE_S,
    wait_for_page_change,
    wait_for_page_text,
)
from .trusted_click import Point, aim_point, dispatch_trusted_click, parse_click_target

PAGE_TEXT_LENGTH_PROBE_FUNCTION = "() => (((document.body && document.body.innerText) || '').trim().length)"
PAGE_FINGERPRINT_PROBE_FUNCTION = (
    "() => (location.href + '|' + (document.title || '') + '|'"
    " + String(((document.body && document.body.innerText) || '').trim().length))"
)

# Asked of the *top* document, to check that a translated coordinate still
# lands on the embedded frame it was measured in.
_POINT_ON_FRAME_FUNCTION = """
([x, y]) => {
  const hit = document.elementFromPoint(x, y);
  return hit ? String(hit.tagName || '').toLowerCase() : 'nothing';
}
"""

# Border and padding sit between an iframe's box and the viewport its document
# measures from, so both are added to the box Patchright reports for it.
_FRAME_CONTENT_INSET_FUNCTION = """
(element) => {
  const style = getComputedStyle(element);
  return [
    element.clientLeft + (parseFloat(style.paddingLeft) || 0),
    element.clientTop + (parseFloat(style.paddingTop) || 0),
  ];
}
"""

# Working data for the click we are about to make, not something to persist:
# ``runner.py`` spreads these payloads straight into emitted run events.
_TRANSIENT_PAYLOAD_KEYS = ("click_target",)


def _without_coordinates(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key not in _TRANSIENT_PAYLOAD_KEYS}


def _finite_pair(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    pair: list[float] = []
    for item in value[:2]:
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item):
            return None
        pair.append(float(item))
    return (pair[0], pair[1])


class _FocusedField:
    """What ``human_typing`` expects of an element: ``focus()`` and a ``tab`` to send to.

    Keystrokes go to the page's CDP session and Chrome delivers them to whichever
    frame holds focus, so focusing through the locator is what aims them.
    """

    def __init__(self, locator: Any, tab: CdpTarget) -> None:
        self._locator = locator
        self.tab = tab

    async def focus(self) -> None:
        await self._locator.focus(timeout=10_000)


class PlaywrightBrowserAdapter(BrowserAdapter):
    """The Playwright-protocol adapter, driven by Patchright rather than Playwright.

    Patchright is a drop-in fork of Playwright -- same package layout, same API,
    same two dependencies -- with the tells patched out of the driver rather than
    papered over from inside the page. It runs its own scripts in isolated
    execution contexts instead of enabling ``Runtime``, drops the
    ``--enable-automation`` flag family, and reaches into closed shadow roots,
    which our own F9 traversal cannot. It ships native wheels for Windows and for
    both Intel and Apple Silicon Macs, which is why it is the default driver.
    Vanilla Playwright is not kept as a fallback: an adapter that silently
    downgrades to the leaky driver would report a stealth posture it does not have.

    Reads run in Patchright's isolated world, which shares the DOM and nothing
    else, so a site's own scripts can neither see the probe nor have replaced the
    builtins it relies on. Writes run in the main world on purpose: React's value
    tracker is an own-property override installed there, so a write has to happen
    there to be seen.

    The adapter keeps the name "playwright" because that is what it speaks and what
    every persisted run record already says. ``driver_check`` reports the module it
    actually imports, so the build can still be asked which driver it carries.
    """

    name = "playwright"

    def __init__(self) -> None:
        self._playwright = None
        self._context = None
        self._page = None
        self._input: CdpTarget | None = None
        self._visited_origins: set[str] = set()

    async def launch(self, *, run_id: str, user_data_dir: Path) -> BrowserStepResult:
        try:
            from patchright.async_api import async_playwright  # type: ignore
        except ImportError:
            return BrowserStepResult(
                False,
                "playwright is not installed",
                {"run_id": run_id, "user_data_dir": str(user_data_dir), "install_hint": "pip install patchright"},
            )

        user_data_dir.mkdir(parents=True, exist_ok=True)
        # Choose the browser rather than trusting a default, which can silently
        # drive Chrome Beta or Canary. See chrome_discovery. None means nothing
        # was found, which leaves Patchright to find stable Chrome by channel.
        executable = discover_chrome_executable()
        browser = {"executable_path": executable} if executable else {"channel": "chrome"}
        try:
            self._playwright = await async_playwright().start()
            # Patchright's documented configuration, and every part of it is load-bearing.
            # Driving the real Chrome the user already has means no bundled Chromium has
            # to be shipped or downloaded and the fingerprint is a genuine one rather
            # than Chromium's. ``no_viewport`` leaves the window at its natural size
            # instead of the fixed 1280x720 that Playwright otherwise forces on every
            # page. Nothing else is passed: custom args, headers and user agents are
            # what give the fork away, and the defaults already include --no-first-run.
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir),
                headless=False,
                no_viewport=True,
                **browser,
            )
            self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        except Exception as exc:
            if self._playwright is not None:
                await self._playwright.stop()
            self._playwright = None
            self._context = None
            self._page = None
            return BrowserStepResult(False, "playwright browser launch failed", {"run_id": run_id, "error": str(exc)})

        return BrowserStepResult(True, "browser launched", {"run_id": run_id, "browser_executable": executable})

    async def _input_target(self) -> CdpTarget:
        """The page's CDP session, opened on first use and kept for the page's life.

        Trusted keystrokes, clicks and wheel notches all go through it. Only the
        ``Input`` domain is ever sent, so opening it enables nothing a page can see.
        """
        if self._input is None:
            if self._context is None or self._page is None:
                raise RuntimeError("browser page is not available")
            self._input = CdpTarget(await self._context.new_cdp_session(self._page))
        return self._input

    async def open_url(self, url: str) -> BrowserStepResult:
        if self._page is None:
            return BrowserStepResult(False, "browser page is not available", {"url": url})
        landing = warm_up_target(url, self._visited_origins)
        origin = origin_of(url)
        if origin is not None:
            # Marked before the warm-up runs rather than after it succeeds, so a
            # site whose front door is broken costs one failed navigation for
            # the run instead of one on every page opened there.
            self._visited_origins.add(origin)
        warmed = await self._warm_up(landing) if landing is not None else False
        try:
            await self._page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        except Exception as exc:
            return BrowserStepResult(False, "page navigation failed", {"url": url, "error": str(exc)})
        readiness = await wait_for_page_text(
            self._probe_visible_text_length,
            timeout_s=PAGE_TEXT_TIMEOUT_S,
            poll_interval_s=PAGE_TEXT_POLL_INTERVAL_S,
        )
        return BrowserStepResult(True, "page navigated", {"url": url, "page_text": readiness, "warmed_up": warmed})

    async def _warm_up(self, url: str) -> bool:
        """Land on a site's front door before following a link into it.

        The navigation this precedes is the one that matters, so every part of
        this is best effort: a front door that will not load, will not render or
        does not exist leaves the run exactly where it would have been without
        the warm-up, one page later.
        """
        if self._page is None:
            return False
        try:
            await self._page.goto(url, wait_until="domcontentloaded", timeout=WARM_UP_TIMEOUT_S * 1000)
            await wait_for_page_text(
                self._probe_visible_text_length,
                timeout_s=WARM_UP_TIMEOUT_S,
                poll_interval_s=PAGE_TEXT_POLL_INTERVAL_S,
            )
            await asyncio.sleep(dwell_seconds())
        except Exception:
            return False
        return True

    async def _probe_visible_text_length(self) -> int:
        if self._page is None:
            return 0
        raw = await self._page.evaluate(PAGE_TEXT_LENGTH_PROBE_FUNCTION)
        try:
            return int(raw or 0)
        except (TypeError, ValueError):
            return 0

    async def bring_to_front(self) -> None:
        """Raise the browser window so the user can act on a challenge (best-effort)."""
        if self._page is not None:
            await self._page.bring_to_front()

    def _form_frames(self) -> list[Any]:
        """The top document, then any subframe that could hold part of the form.

        Greenhouse, Lever and Workable serve the real form from their own origin
        and embed it, so on those portals the top document is a wrapper with no
        questions in it at all.
        """
        if self._page is None:
            return []
        main_frame = self._page.main_frame
        return [main_frame] + [
            frame
            for frame in self._page.frames
            if frame is not main_frame and frame_url_is_worth_scanning(frame.url)
        ]

    async def _frame_urls_the_dom_walk_reached(self) -> set[str]:
        """Subframes discovery already covered from the top document, so we skip them.

        Playwright lists every frame in the page, same-origin ones included, and the
        discovery script descends into those by itself. Scanning both ways offers each
        embedded question twice. Asking the page which documents it could reach is the
        same test discovery makes, rather than a guess about origins made out here.
        """
        if self._page is None:
            return set()
        try:
            reached = await self._page.main_frame.evaluate(DOM_REACHED_FRAME_URLS_JS)
        except Exception:
            # Losing this leaves duplicates, which the reviewer can see and dismiss.
            # Losing detection outright because one probe failed is the worse trade.
            return set()
        if isinstance(reached, str):
            try:
                reached = json.loads(reached)
            except json.JSONDecodeError:
                return set()
        if not isinstance(reached, list):
            return set()
        return {url for url in reached if isinstance(url, str) and url}

    async def detect_fields(self) -> list[BrowserField]:
        if self._page is None:
            return []
        main_frame = self._page.main_frame
        frames = self._page.frames
        already_walked = await self._frame_urls_the_dom_walk_reached()
        fields: list[BrowserField] = []
        for frame in self._form_frames():
            if frame is not main_frame and frame.url in already_walked:
                continue
            try:
                raw_result = await frame.evaluate(DOM_FIELD_DISCOVERY_SCRIPT)
            except Exception:
                # A frame can navigate or detach mid-sweep. Whatever the other
                # frames found is still worth reporting, so skip just this one.
                continue
            if isinstance(raw_result, str):
                try:
                    raw_result = json.loads(raw_result)
                except json.JSONDecodeError:
                    continue
            # The top document keeps unqualified ids and no frame metadata, so a
            # portal that does not embed anything behaves exactly as it did before.
            ref = None
            if frame is not main_frame:
                index = frames.index(frame) if frame in frames else -1
                ref = FrameRef(url=frame.url, index=index)
            fields.extend(fields_from_dom_snapshot(raw_result, frame=ref))
        return fields

    def _frame_for(self, field: BrowserField) -> tuple[Any | None, str]:
        """Resolve the frame a field was discovered in.

        A field with no frame metadata belongs to the top document. When the
        recorded frame cannot be identified we return an error rather than falling
        back to the main frame: writing an answer into the wrong document would
        report success while leaving the real field empty.
        """
        if self._page is None:
            return None, "browser page is not available"
        frame_url = field.metadata.get("frame_url")
        if not frame_url:
            return self._page.main_frame, ""
        frames = self._page.frames
        matches = [frame for frame in frames if frame.url == frame_url]
        if len(matches) == 1:
            return matches[0], ""
        if not matches:
            return None, "the frame holding this field is no longer on the page"
        recorded_index = field.metadata.get("frame_index")
        if isinstance(recorded_index, int) and 0 <= recorded_index < len(frames):
            candidate = frames[recorded_index]
            if candidate.url == frame_url:
                return candidate, ""
        return None, "several frames share this URL, so the field's frame is ambiguous"

    async def detect_blockers(self) -> list[BrowserBlocker]:
        if self._page is None:
            return []
        try:
            raw_result = await self._page.evaluate(DOM_BLOCKER_DISCOVERY_SCRIPT)
        except Exception:
            return []
        if isinstance(raw_result, str):
            try:
                raw_result = json.loads(raw_result)
            except json.JSONDecodeError:
                return []
        return blockers_from_dom_snapshot(raw_result)

    async def capture_dom_snapshot(self, output_path: Path) -> BrowserStepResult:
        if self._page is None:
            return BrowserStepResult(False, "page is not available")
        try:
            raw_result = await self._page.evaluate(DOM_METADATA_CAPTURE_SCRIPT)
        except Exception as exc:
            return BrowserStepResult(False, "DOM snapshot capture failed", {"error": str(exc)})
        if isinstance(raw_result, str):
            try:
                payload = json.loads(raw_result)
            except json.JSONDecodeError:
                payload = {"raw": raw_result}
        else:
            payload = raw_result if isinstance(raw_result, dict) else {"raw": raw_result}
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return BrowserStepResult(
            True,
            "DOM snapshot captured",
            {
                "local_path": str(output_path),
                "mime_type": "application/json",
                "metadata": {
                    "url": payload.get("url") if isinstance(payload, dict) else None,
                    "title": payload.get("title") if isinstance(payload, dict) else None,
                    "field_count": payload.get("field_count") if isinstance(payload, dict) else None,
                },
            },
        )

    async def extract_visible_text(self) -> BrowserStepResult:
        if self._page is None:
            return BrowserStepResult(False, "page is not available")
        try:
            raw_result = await self._page.evaluate(DOM_VISIBLE_TEXT_SCRIPT)
        except Exception as exc:
            return BrowserStepResult(False, "visible text extraction failed", {"error": str(exc)})
        if isinstance(raw_result, str):
            try:
                payload = json.loads(raw_result)
            except json.JSONDecodeError:
                payload = {"text": raw_result, "text_length": len(raw_result)}
        else:
            payload = raw_result if isinstance(raw_result, dict) else {"text": str(raw_result), "text_length": len(str(raw_result))}
        text = str(payload.get("text") or "")
        if not text.strip():
            return BrowserStepResult(False, "visible page text was empty", {"url": payload.get("url"), "title": payload.get("title")})
        return BrowserStepResult(
            True,
            "visible page text extracted",
            {
                "url": payload.get("url"),
                "title": payload.get("title"),
                "text": text,
                "text_length": int(payload.get("text_length") or len(text)),
            },
        )

    async def _clear_field(self, locator: Any, target: _FocusedField) -> None:
        """Empty a control before typing so a write replaces rather than appends.

        A prefilled portal field (Workday's resume parse, an iCIMS account,
        browser autofill) otherwise turns "Alex Rivera" into "Alex RiveraAlex
        Rivera". Select-all-then-delete as keystrokes is preferred, because it is
        a real edit: the resulting ``input`` event is trusted and every
        framework's value tracker observes the reset. Playwright's own clear is
        the fallback. Raises when the field could not be emptied, because
        appending to a prefilled field corrupts the value.
        """
        try:
            await clear_element(target)
            return
        except Exception:
            # Detached frame, or a control that refuses focus. The value still
            # has to go somewhere, so fall through rather than fail.
            pass
        await locator.clear(timeout=10_000)

    async def fill_field(self, field: BrowserField, value: str) -> BrowserStepResult:
        if self._page is None or not field.selector:
            return BrowserStepResult(False, "field selector unavailable", {"field_id": field.field_id})
        if not driver_can_locate(field):
            return BrowserStepResult(
                False,
                "field is inside an embedded document the driver cannot address",
                {"field_id": field.field_id},
            )
        frame, frame_error = self._frame_for(field)
        if frame is None:
            return BrowserStepResult(False, frame_error, {"field_id": field.field_id})
        locator = frame.locator(field.selector)
        try:
            target = _FocusedField(locator, await self._input_target())
            await self._clear_field(locator, target)
        except Exception as exc:
            return BrowserStepResult(
                False,
                "field could not be cleared before typing",
                {"field_id": field.field_id, "error": str(exc)},
            )
        try:
            strategy = await type_into_element(target, value)
        except Exception:
            # Keystroke emission is the better path, not the only one. If it
            # fails we still owe the run a filled field, so fall back to
            # Playwright's own fill rather than abandoning the answer.
            try:
                await locator.fill(value, timeout=10_000)
            except Exception as exc:
                return BrowserStepResult(False, "field value fill failed", {"field_id": field.field_id, "error": str(exc)})
            strategy = "fill"
        return BrowserStepResult(
            True,
            "field value applied",
            {"field_id": field.field_id, "cleared_before_typing": True, "input_strategy": strategy},
        )

    async def apply_field_value(self, field: BrowserField, value: str) -> BrowserStepResult:
        if self._page is None or not field.selector:
            return BrowserStepResult(False, "field selector unavailable", {"field_id": field.field_id})
        frame, frame_error = self._frame_for(field)
        if frame is None:
            return BrowserStepResult(False, frame_error, {"field_id": field.field_id})
        if field.field_type not in SCRIPTED_WRITE_FIELD_TYPES and driver_can_locate(field):
            filled = await self.fill_field(field, value)
            if not filled.ok:
                return filled
            # Read the value back from the same frame we wrote it to. Verifying
            # against the top document would read a field that was never touched.
            # The main world, because a failed read-back is repaired by a write.
            async def evaluate(script: str) -> Any:
                return await frame.evaluate(script, isolated_context=False)

            return await verify_or_repair_text_write(evaluate, field, value, fill_payload=filled.payload)
        try:
            raw_result = await frame.evaluate(
                build_apply_field_value_script(field.selector, value, dom_path_for(field)),
                isolated_context=False,
            )
        except Exception as exc:
            return BrowserStepResult(False, "field value application failed", {"field_id": field.field_id, "error": str(exc)})
        return parse_apply_field_result(raw_result, field)

    async def _probe_page_fingerprint(self) -> str:
        if self._page is None:
            return ""
        try:
            return str(await self._page.evaluate(PAGE_FINGERPRINT_PROBE_FUNCTION) or "")
        except Exception:
            return ""

    async def _settle_after_click(self, baseline: str) -> dict[str, object]:
        return await wait_for_page_change(
            self._probe_page_fingerprint,
            baseline=baseline,
            timeout_s=POST_CLICK_TIMEOUT_S,
            poll_interval_s=POST_CLICK_POLL_INTERVAL_S,
            unchanged_grace_s=POST_CLICK_UNCHANGED_GRACE_S,
        )

    async def _evaluate_click_script(
        self,
        frame: Any,
        script: str,
        parse: Callable[[Any], BrowserStepResult],
        failure_message: str,
        *,
        read_only: bool = False,
    ) -> BrowserStepResult:
        """One click script in one frame, with a frame that broke reported as a refusal.

        A frame can navigate or detach mid-click. The refusal is marked as
        falling back so the caller retries with the injected click.

        ``read_only`` is for the script that measures the control instead of
        pressing it: measuring is a read, so it stays hidden from the page, while
        the injected press has to happen in the page's own world.
        """
        try:
            raw_result = await frame.evaluate(script, isolated_context=read_only)
        except Exception as exc:
            return BrowserStepResult(False, failure_message, {"error": str(exc), "fallback": "injected_js"})
        return parse(raw_result)

    async def _frame_viewport_origin(self, frame: Any) -> tuple[float, float] | None:
        """Where ``frame`` measures its own (0, 0) from, in top-level coordinates.

        An embedded document's ``getBoundingClientRect()`` is relative to its own
        viewport, but a mouse event is dispatched against the top-level page.
        Patchright reports the owning ``<iframe>``'s box relative to the main
        viewport, nested frames included; its border and padding are then added,
        because the embedded viewport starts inside them.

        ``None`` means we could not work it out, which costs a fallback to the
        injected click rather than a press at a guessed coordinate.
        """
        if self._page is None:
            return None
        if frame is self._page.main_frame:
            return (0.0, 0.0)
        try:
            owner = await frame.frame_element()
            box = await owner.bounding_box()
            inset = _finite_pair(await owner.evaluate(_FRAME_CONTENT_INSET_FUNCTION))
        except Exception:
            return None
        if not box or inset is None:
            return None
        corner = _finite_pair([box.get("x"), box.get("y")])
        if corner is None:
            return None
        return (corner[0] + inset[0], corner[1] + inset[1])

    async def _point_reaches_frame(self, point: Point) -> bool:
        """Whether the top document still shows the embedded frame at this point.

        ``scrollIntoView`` inside a cross-origin iframe scrolls that frame, not
        the page holding it. A form scrolled below the top-level fold therefore
        reports a perfectly good frame-local box whose translation lands on
        whatever the user can actually see instead. ``element.click()`` never had
        that problem, so this is the check that keeps the mouse path from being
        worse than the one it replaces.
        """
        if self._page is None:
            return False
        try:
            tag = await self._page.main_frame.evaluate(_POINT_ON_FRAME_FUNCTION, [point.x, point.y])
        except Exception:
            return False
        return str(tag) in {"iframe", "frame"}

    async def _scroll_toward(self, frame: Any, payload: dict[str, Any]) -> bool:
        """Wheel a control below the fold into view. ``False`` scrolled nothing.

        Aimed and guarded exactly like the click that follows, because it is the
        same kind of event against the same top-level page: a frame whose origin
        cannot be worked out, or that the top document is not showing at the
        point we would scroll at, is left alone rather than scrolled at a guess.
        """
        if self._page is None:
            return False
        origin = await self._frame_viewport_origin(frame)
        if origin is None:
            return False
        anchor = parse_scroll_anchor(payload, origin)
        if anchor is None:
            return False
        if frame is not self._page.main_frame and not await self._point_reaches_frame(anchor.point):
            return False
        try:
            return await dispatch_wheel_scroll(await self._input_target(), anchor)
        except Exception:
            return False

    async def _dispatch_located_click(self, frame: Any, payload: dict[str, Any]) -> bool:
        """Press the located control with the mouse. ``False`` means use the script."""
        if self._page is None:
            return False
        target = parse_click_target(payload)
        if target is None:
            return False
        origin = await self._frame_viewport_origin(frame)
        if origin is None:
            return False
        point = aim_point(target, origin)
        if frame is not self._page.main_frame and not await self._point_reaches_frame(point):
            return False
        try:
            await dispatch_trusted_click(await self._input_target(), point)
        except Exception:
            return False
        return True

    async def _click_in_frame(
        self,
        frame: Any,
        locate_script: str,
        press_script: str,
        parse: Callable[[Any], BrowserStepResult],
        failure_message: str,
    ) -> BrowserStepResult:
        """Find the control, then press it with the mouse if we safely can.

        The page is asked where the control is rather than to click it, because
        ``element.click()`` produces an event carrying ``isTrusted: false``. When
        the coordinate cannot be trusted, for any reason at all, the injected
        click runs in this same frame, so nothing here can do worse than the
        behaviour it replaces.
        """
        located = await self._evaluate_click_script(frame, locate_script, parse, failure_message, read_only=True)
        if not located.ok and "scroll_by" in located.payload:
            # The control sits outside the viewport, so the page could not
            # hit-test it. Wheeling it into view invalidates the box it just
            # reported, which is why the measurement is taken a second time.
            if await self._scroll_toward(frame, located.payload):
                located = await self._evaluate_click_script(
                    frame, locate_script, parse, failure_message, read_only=True
                )
        if located.ok:
            if await self._dispatch_located_click(frame, located.payload):
                payload = {**_without_coordinates(located.payload), "click_dispatch": "trusted_input"}
                return BrowserStepResult(True, located.message, payload)
        elif located.payload.get("fallback") != "injected_js":
            # Nothing matched, or too many things did. Pressing would find the
            # same nothing, and the refusal above explains it better.
            return located

        pressed = await self._evaluate_click_script(frame, press_script, parse, failure_message)
        if not pressed.ok:
            return pressed
        return BrowserStepResult(True, pressed.message, {**pressed.payload, "click_dispatch": "injected_js"})

    async def _click_across_frames(
        self,
        locate_script: str,
        press_script: str,
        parse: Callable[[Any], BrowserStepResult],
        failure_message: str,
    ) -> BrowserStepResult:
        """Run a click in the top document, then in each embedded form frame.

        The top document is always tried first, so a portal that hosts its own form
        behaves exactly as it did before. Only when nothing matched up there do we
        look inside the embedded form, where a cross-origin portal keeps its buttons.
        The first frame that reports success wins; otherwise the last refusal is
        returned, because that is the one that explains why nothing was clicked.
        """
        last_result: BrowserStepResult | None = None
        for frame in self._form_frames():
            result = await self._click_in_frame(frame, locate_script, press_script, parse, failure_message)
            if result.ok:
                return result
            last_result = result
        return last_result or BrowserStepResult(False, failure_message)

    async def click_by_text(self, labels: list[str]) -> BrowserStepResult:
        if self._page is None:
            return BrowserStepResult(False, "page is not available")
        baseline = await self._probe_page_fingerprint()
        result = await self._click_across_frames(
            build_click_by_text_script(labels, locate_only=True),
            build_click_by_text_script(labels),
            parse_click_by_text_result,
            "portal action click failed",
        )
        if not result.ok:
            return result
        settle = await self._settle_after_click(baseline)
        return BrowserStepResult(result.ok, result.message, {**result.payload, "page_settle": settle})

    async def click_final_submit(self, labels: list[str]) -> BrowserStepResult:
        if self._page is None:
            return BrowserStepResult(False, "page is not available")
        baseline = await self._probe_page_fingerprint()
        result = await self._click_across_frames(
            build_final_submit_script(labels, locate_only=True),
            build_final_submit_script(labels),
            parse_final_submit_result,
            "final submit click failed",
        )
        if not result.ok:
            return result
        settle = await self._settle_after_click(baseline)
        return BrowserStepResult(result.ok, result.message, {**result.payload, "page_settle": settle})

    async def upload_file(self, field: BrowserField, path: Path) -> BrowserStepResult:
        if not path.exists():
            return BrowserStepResult(False, "upload file does not exist", {"path": str(path)})
        if self._page is None or not field.selector:
            return BrowserStepResult(False, "field selector unavailable", {"field_id": field.field_id})
        if not driver_can_locate(field):
            # Uploading is the one write with no scripted equivalent: a file input
            # can only be set by the driver. Attaching the resume to whatever input
            # the parent page happens to expose is worse than handing this back.
            return BrowserStepResult(
                False,
                "file input is inside an embedded document the driver cannot address",
                {"field_id": field.field_id},
            )
        frame, frame_error = self._frame_for(field)
        if frame is None:
            return BrowserStepResult(False, frame_error, {"field_id": field.field_id})
        try:
            await frame.locator(field.selector).set_input_files(str(path), timeout=10_000)
        except Exception as exc:
            return BrowserStepResult(False, "file upload failed", {"field_id": field.field_id, "error": str(exc)})
        return BrowserStepResult(True, "file uploaded", {"field_id": field.field_id, "path": str(path)})

    async def screenshot(self, output_path: Path) -> BrowserStepResult:
        if self._page is None:
            return BrowserStepResult(False, "page is not available")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        await self._page.screenshot(path=str(output_path), full_page=True)
        return BrowserStepResult(True, "screenshot captured", screenshot_payload(output_path))

    async def pause(self, reason: str) -> BrowserStepResult:
        return BrowserStepResult(True, "automation paused", {"reason": reason})

    async def close(self) -> BrowserStepResult:
        if self._context is not None:
            await self._context.close()
        if self._playwright is not None:
            await self._playwright.stop()
        self._playwright = None
        self._context = None
        self._page = None
        self._input = None
        return BrowserStepResult(True, "browser closed")
