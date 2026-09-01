from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .adapter import BrowserAdapter, BrowserBlocker, BrowserField, BrowserStepResult, screenshot_payload
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
from .page_readiness import (
    PAGE_TEXT_POLL_INTERVAL_S,
    PAGE_TEXT_TIMEOUT_S,
    POST_CLICK_POLL_INTERVAL_S,
    POST_CLICK_TIMEOUT_S,
    POST_CLICK_UNCHANGED_GRACE_S,
    wait_for_page_change,
    wait_for_page_text,
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


def _frame_url(frame: Any) -> str:
    """The URL of a nodriver tab or iframe, via the CDP target it is attached to."""
    target = getattr(frame, "target", None)
    return str(getattr(target, "url", "") or "")


class NodriverBrowserAdapter(BrowserAdapter):
    name = "nodriver"

    def __init__(self) -> None:
        self._browser = None
        self._page = None

    async def launch(self, *, run_id: str, user_data_dir: Path) -> BrowserStepResult:
        try:
            import nodriver as uc  # type: ignore
        except ImportError:
            return BrowserStepResult(False, "nodriver is not installed")

        user_data_dir.mkdir(parents=True, exist_ok=True)
        self._browser = await uc.start(user_data_dir=str(user_data_dir), browser_args=["--no-first-run"])
        self._page = await self._browser.get("about:blank")
        return BrowserStepResult(True, "browser launched", {"run_id": run_id})

    async def open_url(self, url: str) -> BrowserStepResult:
        if self._browser is None:
            return BrowserStepResult(False, "browser is not launched")
        self._page = await self._browser.get(url)
        readiness = await wait_for_page_text(
            self._probe_visible_text_length,
            timeout_s=PAGE_TEXT_TIMEOUT_S,
            poll_interval_s=PAGE_TEXT_POLL_INTERVAL_S,
        )
        return BrowserStepResult(True, "page navigated", {"url": url, "page_text": readiness})

    async def _probe_visible_text_length(self) -> int:
        if self._page is None:
            return 0
        raw = await self._page.evaluate(PAGE_TEXT_LENGTH_PROBE_SCRIPT)
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
        raw_result = await frame.evaluate(DOM_FIELD_DISCOVERY_SCRIPT)
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
            return str(await self._page.evaluate(PAGE_FINGERPRINT_PROBE_SCRIPT) or "")
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

    async def _click_across_frames(
        self,
        script: str,
        parse: Callable[[Any], BrowserStepResult],
        failure_message: str,
    ) -> BrowserStepResult:
        """Run a click script in the top document, then in each embedded form frame.

        The top document is always tried first, so a portal that hosts its own form
        behaves exactly as it did before. Only when nothing matched up there do we
        look inside the embedded form, where a cross-origin portal keeps its buttons.
        The first frame that reports success wins; otherwise the last refusal is
        returned, because that is the one that explains why nothing was clicked.
        """
        last_result: BrowserStepResult | None = None
        for frame in await self._form_frames():
            try:
                raw_result = await frame.evaluate(script)
            except Exception as exc:
                last_result = BrowserStepResult(False, failure_message, {"error": str(exc)})
                continue
            result = parse(raw_result)
            if result.ok:
                return result
            last_result = result
        return last_result or BrowserStepResult(False, failure_message)

    async def click_by_text(self, labels: list[str]) -> BrowserStepResult:
        if self._page is None:
            return BrowserStepResult(False, "page is not available")
        baseline = await self._probe_page_fingerprint()
        result = await self._click_across_frames(
            build_click_by_text_script(labels), parse_click_by_text_result, "portal action click failed"
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
            build_final_submit_script(labels), parse_final_submit_result, "final submit click failed"
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
