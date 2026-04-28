from __future__ import annotations

import asyncio
from pathlib import Path
import json

from .adapter import BrowserAdapter, BrowserBlocker, BrowserField, BrowserStepResult, screenshot_payload
from .field_detection import (
    DOM_BLOCKER_DISCOVERY_SCRIPT,
    DOM_FIELD_DISCOVERY_SCRIPT,
    DOM_METADATA_CAPTURE_SCRIPT,
    DOM_VISIBLE_TEXT_SCRIPT,
    blockers_from_dom_snapshot,
    build_apply_field_value_script,
    build_click_by_text_script,
    build_final_submit_script,
    fields_from_dom_snapshot,
    parse_apply_field_result,
    parse_click_by_text_result,
    parse_final_submit_result,
)


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
        return BrowserStepResult(True, "page navigated", {"url": url})

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

    async def fill_field(self, field: BrowserField, value: str) -> BrowserStepResult:
        if self._page is None or not field.selector:
            return BrowserStepResult(False, "field selector unavailable", {"field_id": field.field_id})
        element = await self._page.select(field.selector)
        if element is None:
            return BrowserStepResult(False, "field not found", {"field_id": field.field_id})
        await element.send_keys(value)
        return BrowserStepResult(True, "field value applied", {"field_id": field.field_id})

    async def apply_field_value(self, field: BrowserField, value: str) -> BrowserStepResult:
        if field.field_type not in {"select", "checkbox", "radio"}:
            return await self.fill_field(field, value)
        if self._page is None or not field.selector:
            return BrowserStepResult(False, "field selector unavailable", {"field_id": field.field_id})
        try:
            raw_result = await self._page.evaluate(build_apply_field_value_script(field.selector, value))
        except Exception as exc:
            return BrowserStepResult(False, "field value application failed", {"field_id": field.field_id, "error": str(exc)})
        return parse_apply_field_result(raw_result, field)

    async def click_by_text(self, labels: list[str]) -> BrowserStepResult:
        if self._page is None:
            return BrowserStepResult(False, "page is not available")
        try:
            raw_result = await self._page.evaluate(build_click_by_text_script(labels))
            await asyncio.sleep(1.5)
        except Exception as exc:
            return BrowserStepResult(False, "portal action click failed", {"error": str(exc)})
        return parse_click_by_text_result(raw_result)

    async def click_final_submit(self, labels: list[str]) -> BrowserStepResult:
        if self._page is None:
            return BrowserStepResult(False, "page is not available")
        try:
            raw_result = await self._page.evaluate(build_final_submit_script(labels))
            await asyncio.sleep(2)
        except Exception as exc:
            return BrowserStepResult(False, "final submit click failed", {"error": str(exc)})
        return parse_final_submit_result(raw_result)

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
            await self._browser.stop()
        self._browser = None
        self._page = None
        return BrowserStepResult(True, "browser closed")
