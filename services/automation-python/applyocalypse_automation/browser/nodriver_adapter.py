from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .adapter import BrowserAdapter, BrowserBlocker, BrowserField, BrowserStepResult, screenshot_payload
from .chrome_discovery import discover_chrome_executable
from .field_detection import (
    DOM_BLOCKER_DISCOVERY_SCRIPT,
    DOM_FIELD_DISCOVERY_SCRIPT,
    DOM_METADATA_CAPTURE_SCRIPT,
    DOM_VISIBLE_TEXT_SCRIPT,
    SCRIPTED_WRITE_FIELD_TYPES,
    FrameRef,
    blockers_from_dom_snapshot,
    build_apply_field_value_script,
    build_click_by_text_script,
    build_final_submit_script,
    fields_from_dom_snapshot,
    frame_url_is_worth_scanning,
    parse_apply_field_result,
    parse_click_by_text_result,
    parse_final_submit_result,
)
from .field_write import verify_or_repair_text_write
from .human_typing import clear_element, type_into_element
from .isolated_world import IsolatedWorlds
from .page_readiness import (
    PAGE_TEXT_POLL_INTERVAL_S,
    PAGE_TEXT_TIMEOUT_S,
    POST_CLICK_POLL_INTERVAL_S,
    POST_CLICK_TIMEOUT_S,
    POST_CLICK_UNCHANGED_GRACE_S,
    wait_for_page_change,
    wait_for_page_text,
)
from .trusted_click import (
    Point,
    aim_point,
    content_box_origin,
    dispatch_trusted_click,
    parse_click_target,
)

PAGE_TEXT_LENGTH_PROBE_SCRIPT = "String(((document.body && document.body.innerText) || '').trim().length)"
PAGE_FINGERPRINT_PROBE_SCRIPT = (
    "(location.href + '|' + (document.title || '') + '|'"
    " + String(((document.body && document.body.innerText) || '').trim().length))"
)
# Empty the control before typing. A prefilled portal field (Workday's resume
# parse, an iCIMS account, browser autofill) otherwise turns "Alex Rivera" into
# "Alex RiveraAlex Rivera". The native setter keeps React's value tracker in
# sync so the framework observes the reset instead of replaying the old value.
FIELD_CLEAR_SCRIPT_TEMPLATE = """
(() => {{
  const element = document.querySelector({selector_json});
  if (!element) {{ return 'missing'; }}
  const prototype = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(prototype, 'value');
  element.focus();
  if (setter && setter.set) {{ setter.set.call(element, ''); }} else {{ element.value = ''; }}
  element.dispatchEvent(new Event('input', {{ bubbles: true }}));
  return String(element.value || '').length === 0 ? 'cleared' : 'not_cleared';
}})()
"""


# Asked of the *top* document, to check that a translated coordinate still
# lands on the embedded frame it was measured in.
_POINT_ON_FRAME_SCRIPT = """
(() => {{
  const hit = document.elementFromPoint({x}, {y});
  return hit ? String(hit.tagName || '').toLowerCase() : 'nothing';
}})()
"""

# Working data for the click we are about to make, not something to persist:
# ``runner.py`` spreads these payloads straight into emitted run events.
_TRANSIENT_PAYLOAD_KEYS = ("click_target",)


def _without_coordinates(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key not in _TRANSIENT_PAYLOAD_KEYS}


def _frame_url(frame: Any) -> str:
    """The URL of a nodriver tab or iframe, via the CDP target it is attached to."""
    target = getattr(frame, "target", None)
    return str(getattr(target, "url", "") or "")


class NodriverBrowserAdapter(BrowserAdapter):
    name = "nodriver"

    def __init__(self) -> None:
        self._browser = None
        self._page = None
        self._worlds = IsolatedWorlds()

    async def launch(self, *, run_id: str, user_data_dir: Path) -> BrowserStepResult:
        try:
            import nodriver as uc  # type: ignore
        except ImportError:
            return BrowserStepResult(False, "nodriver is not installed")

        user_data_dir.mkdir(parents=True, exist_ok=True)
        # Choose the browser rather than letting nodriver pick the shortest path
        # on disk, which can silently drive Chrome Beta or Canary. See
        # chrome_discovery for why that heuristic misfires on Windows. None means
        # nothing was found, which leaves nodriver to autodetect as it always has.
        executable = discover_chrome_executable()
        self._browser = await uc.start(
            user_data_dir=str(user_data_dir),
            browser_args=["--no-first-run"],
            browser_executable_path=executable,
        )
        self._page = await self._browser.get("about:blank")
        return BrowserStepResult(
            True, "browser launched", {"run_id": run_id, "browser_executable": executable}
        )

    async def open_url(self, url: str) -> BrowserStepResult:
        if self._browser is None:
            return BrowserStepResult(False, "browser is not launched")
        self._page = await self._browser.get(url)
        # The old documents are gone and so are their contexts. Chrome can hand
        # a retired context id back out, so the cache is dropped here rather
        # than one probe later.
        self._worlds.forget_all()
        readiness = await wait_for_page_text(
            self._probe_visible_text_length,
            timeout_s=PAGE_TEXT_TIMEOUT_S,
            poll_interval_s=PAGE_TEXT_POLL_INTERVAL_S,
        )
        return BrowserStepResult(True, "page navigated", {"url": url, "page_text": readiness})

    async def _read(self, frame: Any, script: str) -> Any:
        """Run a read-only probe, preferring a world the page cannot see.

        Everything this worker asks a page used to be asked in the page's own
        main world, where a script the site loaded first can have replaced the
        builtins the probe relies on and can watch it run. An isolated world
        shares the DOM and nothing else, so the same question gets an honest
        answer and leaves no trace.

        Falling back to the main world on any failure is what keeps this from
        being a new way to fail: a browser or a frame that will not give us a
        context loses the stealth and keeps the answer.

        Writes never come through here. React's value tracker is an
        own-property override installed in the main world, so a write has to
        happen there to be seen.
        """
        ok, value = await self._worlds.evaluate(frame, script)
        if ok:
            return value
        return await frame.evaluate(script)

    async def _probe_visible_text_length(self) -> int:
        if self._page is None:
            return 0
        raw = await self._read(self._page, PAGE_TEXT_LENGTH_PROBE_SCRIPT)
        try:
            return int(str(raw).strip() or "0")
        except ValueError:
            return 0

    async def bring_to_front(self) -> None:
        """Raise the browser window so the user can act on a challenge (best-effort)."""
        if self._page is not None:
            await self._page.bring_to_front()

    async def _embedded_form_frames(self) -> list[Any]:
        """Out-of-process frames that could hold part of the application form.

        Chrome's site isolation gives a cross-origin iframe its own renderer and
        its own CDP target, and nodriver hands those back as connectable IFrames.
        That is the only way in: injected JS cannot walk into a document from
        another origin, so a write aimed at the top document lands nowhere while
        still looking like it worked. Greenhouse, Workable, Ashby and iCIMS all
        embed this way onto an employer's careers page.
        """
        if self._page is None:
            return []
        try:
            frames = await self._page.get_frames()
        except Exception:
            # No frame support from the driver is not a reason to lose the top
            # document, which is where most portals keep their form anyway.
            return []
        return [frame for frame in frames if frame_url_is_worth_scanning(_frame_url(frame))]

    async def _form_frames(self) -> list[Any]:
        """The top document first, then any embedded form frame."""
        if self._page is None:
            return []
        return [self._page, *await self._embedded_form_frames()]

    async def _discover_in(self, frame: Any) -> Any:
        raw_result = await self._read(frame, DOM_FIELD_DISCOVERY_SCRIPT)
        if isinstance(raw_result, str):
            return json.loads(raw_result)
        return raw_result

    async def detect_fields(self) -> list[BrowserField]:
        if self._page is None:
            return []
        frames = await self._form_frames()
        fields: list[BrowserField] = []
        for index, frame in enumerate(frames):
            try:
                raw_result = await self._discover_in(frame)
            except Exception:
                # A frame can navigate or detach mid-sweep. Whatever the other
                # frames found is still worth reporting, so skip just this one.
                continue
            # The top document keeps unqualified ids and no frame metadata, so a
            # portal that does not embed anything behaves exactly as it did before.
            ref = None if index == 0 else FrameRef(url=_frame_url(frame), index=index)
            fields.extend(fields_from_dom_snapshot(raw_result, frame=ref))
        return fields

    async def _frame_for(self, field: BrowserField) -> tuple[Any | None, str]:
        """Resolve the frame a field was discovered in.

        A field with no frame metadata belongs to the top document. When the
        recorded frame cannot be identified we return an error rather than falling
        back to the main frame: writing an answer into the wrong document would
        report success while leaving the real field empty.

        The URL is the key, not the index. nodriver rebuilds this list from
        ``Target.getTargets`` on every call and does not promise a stable order,
        so the index is only ever a tiebreaker between same-URL frames, and only
        when it agrees with the URL.
        """
        if self._page is None:
            return None, "browser page is not available"
        frame_url = field.metadata.get("frame_url")
        if not frame_url:
            return self._page, ""
        frames = await self._form_frames()
        matches = [frame for frame in frames if _frame_url(frame) == frame_url]
        if len(matches) == 1:
            return matches[0], ""
        if not matches:
            return None, "the frame holding this field is no longer on the page"
        recorded_index = field.metadata.get("frame_index")
        if isinstance(recorded_index, int) and 0 <= recorded_index < len(frames):
            candidate = frames[recorded_index]
            if _frame_url(candidate) == frame_url:
                return candidate, ""
        return None, "several frames share this URL, so the field's frame is ambiguous"

    async def detect_blockers(self) -> list[BrowserBlocker]:
        if self._page is None:
            return []
        try:
            raw_result = await self._read(self._page, DOM_BLOCKER_DISCOVERY_SCRIPT)
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
            raw_result = await self._read(self._page, DOM_METADATA_CAPTURE_SCRIPT)
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
            raw_result = await self._read(self._page, DOM_VISIBLE_TEXT_SCRIPT)
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

    async def _clear_element(self, element: object, selector: str, frame: Any = None) -> None:
        """Empty a control before typing so a write replaces rather than appends.

        Select-all-then-delete as keystrokes is preferred, because it is a real
        edit: the resulting `input` event is trusted and every framework's value
        tracker observes the reset. nodriver's own clear_input() assigns
        `element.value = ""` from page script and raises no event at all, so a
        React-controlled field keeps the state it had and replays it. Both the
        driver call and the native-setter script remain as fallbacks. Raises when
        the field could not be emptied, because appending to a prefilled portal
        field corrupts the value.
        """
        try:
            await clear_element(element)
            return
        except Exception:
            # Older driver, detached frame, or a control that refuses focus. The
            # value still has to go somewhere, so fall through rather than fail.
            pass
        clear_input = getattr(element, "clear_input", None)
        if callable(clear_input):
            await clear_input()
            return
        # The reset has to run in the document that holds the field, or it clears
        # nothing and the value we type is appended to whatever was already there.
        outcome = await (frame or self._page).evaluate(  # type: ignore[union-attr]
            FIELD_CLEAR_SCRIPT_TEMPLATE.format(selector_json=json.dumps(selector))
        )
        if str(outcome).strip().strip('"') != "cleared":
            raise RuntimeError(f"field could not be emptied (result: {outcome})")

    async def fill_field(self, field: BrowserField, value: str) -> BrowserStepResult:
        if self._page is None or not field.selector:
            return BrowserStepResult(False, "field selector unavailable", {"field_id": field.field_id})
        frame, frame_error = await self._frame_for(field)
        if frame is None:
            return BrowserStepResult(False, frame_error, {"field_id": field.field_id})
        element = await frame.select(field.selector)
        if element is None:
            return BrowserStepResult(False, "field not found", {"field_id": field.field_id})
        try:
            await self._clear_element(element, field.selector, frame)
        except Exception as exc:
            return BrowserStepResult(
                False,
                "field could not be cleared before typing",
                {"field_id": field.field_id, "error": str(exc)},
            )
        try:
            strategy = await type_into_element(element, value)
        except Exception:
            # Keystroke emission is the better path, not the only one. If it
            # fails we still owe the run a filled field, so fall back to the
            # driver's own char-only typing rather than abandoning the answer.
            try:
                await element.send_keys(value)
            except Exception as exc:
                return BrowserStepResult(
                    False, "field value fill failed", {"field_id": field.field_id, "error": str(exc)}
                )
            strategy = "send_keys"
        return BrowserStepResult(
            True,
            "field value applied",
            {"field_id": field.field_id, "cleared_before_typing": True, "input_strategy": strategy},
        )

    async def _evaluate(self, script: str) -> Any:
        if self._page is None:
            raise RuntimeError("browser page is not available")
        return await self._page.evaluate(script)

    def _evaluator_for(self, frame: Any) -> Any:
        """An evaluate callable bound to one document.

        Read-back verification has to run where the field lives. Verifying in the
        top document would read a control that was never written and report the
        answer as lost, or worse, find a same-named control up there and pass.
        """

        async def evaluate(script: str) -> Any:
            return await frame.evaluate(script)

        return evaluate

    async def apply_field_value(self, field: BrowserField, value: str) -> BrowserStepResult:
        if field.field_type not in SCRIPTED_WRITE_FIELD_TYPES:
            filled = await self.fill_field(field, value)
            if not filled.ok:
                return filled
            # Re-resolved rather than carried over from the fill: if the frame
            # detached in between, verification must fail closed, not evaluate
            # against a connection that no longer backs a live document.
            frame, frame_error = await self._frame_for(field)
            if frame is None:
                return BrowserStepResult(False, frame_error, {"field_id": field.field_id})
            return await verify_or_repair_text_write(
                self._evaluator_for(frame), field, value, fill_payload=filled.payload
            )
        if self._page is None or not field.selector:
            return BrowserStepResult(False, "field selector unavailable", {"field_id": field.field_id})
        frame, frame_error = await self._frame_for(field)
        if frame is None:
            return BrowserStepResult(False, frame_error, {"field_id": field.field_id})
        try:
            raw_result = await frame.evaluate(build_apply_field_value_script(field.selector, value))
        except Exception as exc:
            return BrowserStepResult(False, "field value application failed", {"field_id": field.field_id, "error": str(exc)})
        return parse_apply_field_result(raw_result, field)

    async def _probe_page_fingerprint(self) -> str:
        if self._page is None:
            return ""
        try:
            return str(await self._read(self._page, PAGE_FINGERPRINT_PROBE_SCRIPT) or "")
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
        falling back so the caller retries with the injected click, which is what
        this code did before the mouse path existed.

        ``read_only`` is for the script that measures the control instead of
        pressing it: measuring is a read, so it can be hidden from the page,
        while the injected press has to happen in the page's own world to reach
        the element at all.
        """
        try:
            if read_only:
                raw_result = await self._read(frame, script)
            else:
                raw_result = await frame.evaluate(script)
        except Exception as exc:
            return BrowserStepResult(False, failure_message, {"error": str(exc), "fallback": "injected_js"})
        return parse(raw_result)

    async def _frame_viewport_origin(self, frame: Any) -> tuple[float, float] | None:
        """Where ``frame`` measures its own (0, 0) from, in top-level coordinates.

        An embedded document's ``getBoundingClientRect()`` is relative to its own
        viewport, but a mouse event is dispatched against the top-level target.
        Chrome gives an out-of-process frame a target id equal to its frame id,
        so the owning ``<iframe>`` can be looked up from the page above it and
        its content box read: that box is exactly the embedded viewport.

        ``None`` means we could not work it out, which costs a fallback to the
        injected click rather than a press at a guessed coordinate.
        """
        if self._page is None:
            return None
        if frame is self._page:
            return (0.0, 0.0)
        target_id = getattr(getattr(frame, "target", None), "target_id", None)
        if not target_id:
            return None
        try:
            from nodriver import cdp  # type: ignore[import-not-found]

            # The DOM agent needs a document before it will resolve nodes.
            await self._page.send(cdp.dom.get_document(depth=0))
            owner = await self._page.send(cdp.dom.get_frame_owner(cdp.page.FrameId(str(target_id))))
            backend_node_id = owner[0] if isinstance(owner, tuple) else owner
            box = await self._page.send(cdp.dom.get_box_model(backend_node_id=backend_node_id))
        except Exception:
            return None
        return content_box_origin(getattr(box, "content", None))

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
            tag = await self._read(self._page, _POINT_ON_FRAME_SCRIPT.format(x=point.x, y=point.y))
        except Exception:
            return False
        return str(tag) in {"iframe", "frame"}

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
        if frame is not self._page and not await self._point_reaches_frame(point):
            return False
        try:
            await dispatch_trusted_click(self._page, point)
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
        the coordinate cannot be trusted, for any reason at all, the original
        injected click runs in this same frame, so nothing here can do worse than
        the behaviour it replaces.
        """
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
        for frame in await self._form_frames():
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
        frame, frame_error = await self._frame_for(field)
        if frame is None:
            return BrowserStepResult(False, frame_error, {"field_id": field.field_id})
        try:
            element = await frame.select(field.selector)
            if element is None:
                return BrowserStepResult(False, "file input not found", {"field_id": field.field_id})
            await element.send_file(path)
        except Exception as exc:
            return BrowserStepResult(False, "file upload failed", {"field_id": field.field_id, "error": str(exc)})
        return BrowserStepResult(True, "file uploaded", {"field_id": field.field_id, "path": str(path)})

    async def screenshot(self, output_path: Path) -> BrowserStepResult:
        if self._page is None:
            return BrowserStepResult(False, "page is not available")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        await self._page.save_screenshot(str(output_path))
        return BrowserStepResult(True, "screenshot captured", screenshot_payload(output_path))

    async def pause(self, reason: str) -> BrowserStepResult:
        return BrowserStepResult(True, "automation paused", {"reason": reason})

    async def close(self) -> BrowserStepResult:
        if self._browser is not None:
            result = self._browser.stop()
            if asyncio.iscoroutine(result):
                await result
        self._browser = None
        self._page = None
        return BrowserStepResult(True, "browser closed")
