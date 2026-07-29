from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from .adapter import BrowserAdapter, BrowserBlocker, BrowserField, BrowserStepResult, screenshot_payload
from .field_detection import (
    DOM_BLOCKER_DISCOVERY_SCRIPT,
    DOM_FIELD_DISCOVERY_SCRIPT,
    DOM_METADATA_CAPTURE_SCRIPT,
    DOM_VISIBLE_TEXT_SCRIPT,
    SCRIPTED_WRITE_FIELD_TYPES,
    blockers_from_dom_snapshot,
    build_apply_field_value_script,
    build_click_by_text_script,
    build_final_submit_script,
    fields_from_dom_snapshot,
    parse_apply_field_result,
    parse_click_by_text_result,
    parse_final_submit_result,
)
from .field_write import verify_or_repair_text_write
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

    async def detect_fields(self) -> list[BrowserField]:
        if self._page is None:
            return []
        try:
            raw_result = await self._page.evaluate(DOM_FIELD_DISCOVERY_SCRIPT)
        except Exception:
            return []
        if isinstance(raw_result, str):
            try:
                raw_result = json.loads(raw_result)
            except json.JSONDecodeError:
                return []
        return fields_from_dom_snapshot(raw_result)

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

    async def _clear_element(self, element: object, selector: str) -> None:
        """Empty a control before typing so a write replaces rather than appends.

        Prefers nodriver's own clear_input(); falls back to a native-setter reset
        via the page when the element does not expose it. Raises when the field
        could not be emptied, because appending to a prefilled portal field
        corrupts the value.
        """
        clear_input = getattr(element, "clear_input", None)
        if callable(clear_input):
            await clear_input()
            return
        outcome = await self._page.evaluate(  # type: ignore[union-attr]
            FIELD_CLEAR_SCRIPT_TEMPLATE.format(selector_json=json.dumps(selector))
        )
        if str(outcome).strip().strip('"') != "cleared":
            raise RuntimeError(f"field could not be emptied (result: {outcome})")

    async def fill_field(self, field: BrowserField, value: str) -> BrowserStepResult:
        if self._page is None or not field.selector:
            return BrowserStepResult(False, "field selector unavailable", {"field_id": field.field_id})
        element = await self._page.select(field.selector)
        if element is None:
            return BrowserStepResult(False, "field not found", {"field_id": field.field_id})
        try:
            await self._clear_element(element, field.selector)
        except Exception as exc:
            return BrowserStepResult(
                False,
                "field could not be cleared before typing",
                {"field_id": field.field_id, "error": str(exc)},
            )
        try:
            await element.send_keys(value)
        except Exception as exc:
            return BrowserStepResult(False, "field value fill failed", {"field_id": field.field_id, "error": str(exc)})
        return BrowserStepResult(True, "field value applied", {"field_id": field.field_id, "cleared_before_typing": True})

    async def _evaluate(self, script: str) -> Any:
        if self._page is None:
            raise RuntimeError("browser page is not available")
        return await self._page.evaluate(script)

    async def apply_field_value(self, field: BrowserField, value: str) -> BrowserStepResult:
        if field.field_type not in SCRIPTED_WRITE_FIELD_TYPES:
            filled = await self.fill_field(field, value)
            if not filled.ok:
                return filled
            return await verify_or_repair_text_write(self._evaluate, field, value, fill_payload=filled.payload)
        if self._page is None or not field.selector:
            return BrowserStepResult(False, "field selector unavailable", {"field_id": field.field_id})
        try:
            raw_result = await self._page.evaluate(build_apply_field_value_script(field.selector, value))
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

    async def click_by_text(self, labels: list[str]) -> BrowserStepResult:
        if self._page is None:
            return BrowserStepResult(False, "page is not available")
        baseline = await self._probe_page_fingerprint()
        try:
            raw_result = await self._page.evaluate(build_click_by_text_script(labels))
        except Exception as exc:
            return BrowserStepResult(False, "portal action click failed", {"error": str(exc)})
        result = parse_click_by_text_result(raw_result)
        if not result.ok:
            return result
        settle = await self._settle_after_click(baseline)
        return BrowserStepResult(result.ok, result.message, {**result.payload, "page_settle": settle})

    async def click_final_submit(self, labels: list[str]) -> BrowserStepResult:
        if self._page is None:
            return BrowserStepResult(False, "page is not available")
        baseline = await self._probe_page_fingerprint()
        try:
            raw_result = await self._page.evaluate(build_final_submit_script(labels))
        except Exception as exc:
            return BrowserStepResult(False, "final submit click failed", {"error": str(exc)})
        result = parse_final_submit_result(raw_result)
        if not result.ok:
            return result
        settle = await self._settle_after_click(baseline)
        return BrowserStepResult(result.ok, result.message, {**result.payload, "page_settle": settle})

    async def upload_file(self, field: BrowserField, path: Path) -> BrowserStepResult:
        if not path.exists():
            return BrowserStepResult(False, "upload file does not exist", {"path": str(path)})
        if self._page is None or not field.selector:
            return BrowserStepResult(False, "field selector unavailable", {"field_id": field.field_id})
        try:
            element = await self._page.select(field.selector)
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
