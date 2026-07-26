"""SeleniumBase UC Mode adapter — third browser engine.

Implements the BrowserAdapter protocol using SeleniumBase with UC Mode enabled
(uc=True). Because SeleniumBase exposes a synchronous driver API, every driver
call is dispatched via asyncio.to_thread so the rest of the async pipeline is
never blocked.

Cloudflare challenge handling: after detect_blockers finds a CF challenge, call
uc_gui_click_captcha() once via to_thread, then re-detect blockers. If the
challenge persists it is returned unchanged for the runner to handle as a CAPTCHA
review event.

Candidate order (from adapter_factory):
  high-stealth boards : nodriver -> seleniumbase
  ATS portals         : playwright -> nodriver -> seleniumbase

Fail-safe: when seleniumbase is not installed the launch() call returns
BrowserStepResult(ok=False) exactly like the Playwright adapter does.
"""
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
    blockers_from_dom_snapshot,
    build_apply_field_value_script,
    build_click_by_text_script,
    build_final_submit_script,
    fields_from_dom_snapshot,
    parse_apply_field_result,
    parse_click_by_text_result,
    parse_final_submit_result,
)
from .page_readiness import PAGE_TEXT_POLL_INTERVAL_S, PAGE_TEXT_TIMEOUT_S, wait_for_page_text

_CLOUDFLARE_BLOCKER_TYPE = "CLOUDFLARE_CHALLENGE"


def _is_cloudflare_blocker(blockers: list[BrowserBlocker]) -> bool:
    return any(b.blocker_type == _CLOUDFLARE_BLOCKER_TYPE for b in blockers)


class SeleniumBaseBrowserAdapter(BrowserAdapter):
    name = "seleniumbase"

    def __init__(self) -> None:
        self._driver: Any = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _evaluate_sync(self, script: str) -> Any:
        """Execute JavaScript synchronously and return the result."""
        if self._driver is None:
            return None
        return self._driver.execute_script(f"return ({script})")

    async def _evaluate(self, script: str) -> Any:
        return await asyncio.to_thread(self._evaluate_sync, script)

    # ------------------------------------------------------------------
    # BrowserAdapter interface
    # ------------------------------------------------------------------

    async def launch(self, *, run_id: str, user_data_dir: Path) -> BrowserStepResult:
        try:
            from seleniumbase import SB  # type: ignore
        except ImportError:
            return BrowserStepResult(
                False,
                "seleniumbase is not installed",
                {
                    "run_id": run_id,
                    "install_hint": "pip install seleniumbase",
                },
            )

        user_data_dir.mkdir(parents=True, exist_ok=True)

        def _launch() -> None:
            sb_context = SB(uc=True, headless=False, user_data_dir=str(user_data_dir))
            self._driver = sb_context.__enter__()
            # Keep reference so we can call __exit__ on close
            self._sb_context = sb_context  # type: ignore[attr-defined]

        try:
            await asyncio.to_thread(_launch)
        except Exception as exc:
            self._driver = None
            return BrowserStepResult(
                False,
                "seleniumbase browser launch failed",
                {"run_id": run_id, "error": str(exc)},
            )

        return BrowserStepResult(True, "browser launched", {"run_id": run_id})

    async def open_url(self, url: str) -> BrowserStepResult:
        if self._driver is None:
            return BrowserStepResult(False, "browser is not launched", {"url": url})
        try:
            await asyncio.to_thread(self._driver.get, url)
        except Exception as exc:
            return BrowserStepResult(False, "page navigation failed", {"url": url, "error": str(exc)})
        # Same readiness poll as the nodriver/playwright adapters; without it this
        # fallback engine scraped SPA shells before real content had rendered.
        readiness = await wait_for_page_text(
            self._probe_visible_text_length,
            timeout_s=PAGE_TEXT_TIMEOUT_S,
            poll_interval_s=PAGE_TEXT_POLL_INTERVAL_S,
        )
        return BrowserStepResult(True, "page navigated", {"url": url, "page_text": readiness})

    async def _probe_visible_text_length(self) -> int:
        if self._driver is None:
            return 0
        try:
            raw_result = await self._evaluate(DOM_VISIBLE_TEXT_SCRIPT)
        except Exception:
            return 0
        return len(str(raw_result or "").strip())

    async def detect_fields(self) -> list[BrowserField]:
        if self._driver is None:
            return []
        try:
            raw_result = await self._evaluate(DOM_FIELD_DISCOVERY_SCRIPT)
        except Exception:
            return []
        if isinstance(raw_result, str):
            try:
                raw_result = json.loads(raw_result)
            except json.JSONDecodeError:
                return []
        return fields_from_dom_snapshot(raw_result)

    async def detect_blockers(self) -> list[BrowserBlocker]:
        if self._driver is None:
            return []
        try:
            raw_result = await self._evaluate(DOM_BLOCKER_DISCOVERY_SCRIPT)
        except Exception:
            return []
        if isinstance(raw_result, str):
            try:
                raw_result = json.loads(raw_result)
            except json.JSONDecodeError:
                return []
        blockers = blockers_from_dom_snapshot(raw_result)

        # Attempt Cloudflare challenge bypass once if detected
        if _is_cloudflare_blocker(blockers):
            try:
                await asyncio.to_thread(self._driver.uc_gui_click_captcha)
            except Exception:
                pass
            # Re-evaluate after bypass attempt
            try:
                raw_result = await self._evaluate(DOM_BLOCKER_DISCOVERY_SCRIPT)
                if isinstance(raw_result, str):
                    raw_result = json.loads(raw_result)
                blockers = blockers_from_dom_snapshot(raw_result)
            except Exception:
                pass

        return blockers

    async def capture_dom_snapshot(self, output_path: Path) -> BrowserStepResult:
        if self._driver is None:
            return BrowserStepResult(False, "browser is not launched")
        try:
            raw_result = await self._evaluate(DOM_METADATA_CAPTURE_SCRIPT)
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
        if self._driver is None:
            return BrowserStepResult(False, "browser is not launched")
        try:
            raw_result = await self._evaluate(DOM_VISIBLE_TEXT_SCRIPT)
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
        if self._driver is None or not field.selector:
            return BrowserStepResult(False, "field selector unavailable", {"field_id": field.field_id})
        try:
            def _fill() -> None:
                el = self._driver.find_element("css selector", field.selector)
                el.clear()
                el.send_keys(value)
            await asyncio.to_thread(_fill)
        except Exception as exc:
            return BrowserStepResult(False, "field value fill failed", {"field_id": field.field_id, "error": str(exc)})
        return BrowserStepResult(True, "field value applied", {"field_id": field.field_id})

    async def apply_field_value(self, field: BrowserField, value: str) -> BrowserStepResult:
        if field.field_type not in {"select", "checkbox", "radio"}:
            return await self.fill_field(field, value)
        if self._driver is None or not field.selector:
            return BrowserStepResult(False, "field selector unavailable", {"field_id": field.field_id})
        try:
            raw_result = await self._evaluate(build_apply_field_value_script(field.selector, value))
        except Exception as exc:
            return BrowserStepResult(False, "field value application failed", {"field_id": field.field_id, "error": str(exc)})
        return parse_apply_field_result(raw_result, field)

    async def click_by_text(self, labels: list[str]) -> BrowserStepResult:
        if self._driver is None:
            return BrowserStepResult(False, "browser is not launched")
        try:
            raw_result = await self._evaluate(build_click_by_text_script(labels))
            await asyncio.to_thread(self._driver.sleep, 1.5)
        except Exception as exc:
            return BrowserStepResult(False, "portal action click failed", {"error": str(exc)})
        return parse_click_by_text_result(raw_result)

    async def click_final_submit(self, labels: list[str]) -> BrowserStepResult:
        if self._driver is None:
            return BrowserStepResult(False, "browser is not launched")
        try:
            raw_result = await self._evaluate(build_final_submit_script(labels))
            await asyncio.to_thread(self._driver.sleep, 2.0)
        except Exception as exc:
            return BrowserStepResult(False, "final submit click failed", {"error": str(exc)})
        return parse_final_submit_result(raw_result)

    async def upload_file(self, field: BrowserField, path: Path) -> BrowserStepResult:
        if not path.exists():
            return BrowserStepResult(False, "upload file does not exist", {"path": str(path)})
        if self._driver is None or not field.selector:
            return BrowserStepResult(False, "field selector unavailable", {"field_id": field.field_id})
        try:
            def _upload() -> None:
                el = self._driver.find_element("css selector", field.selector)
                el.send_keys(str(path))
            await asyncio.to_thread(_upload)
        except Exception as exc:
            return BrowserStepResult(False, "file upload failed", {"field_id": field.field_id, "error": str(exc)})
        return BrowserStepResult(True, "file uploaded", {"field_id": field.field_id, "path": str(path)})

    async def screenshot(self, output_path: Path) -> BrowserStepResult:
        if self._driver is None:
            return BrowserStepResult(False, "browser is not launched")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            await asyncio.to_thread(self._driver.save_screenshot, str(output_path))
        except Exception as exc:
            return BrowserStepResult(False, "screenshot failed", {"error": str(exc)})
        return BrowserStepResult(True, "screenshot captured", screenshot_payload(output_path))

    async def pause(self, reason: str) -> BrowserStepResult:
        return BrowserStepResult(True, "automation paused", {"reason": reason})

    async def close(self) -> BrowserStepResult:
        if self._driver is not None:
            try:
                sb_ctx = getattr(self, "_sb_context", None)
                if sb_ctx is not None:
                    await asyncio.to_thread(sb_ctx.__exit__, None, None, None)
                else:
                    await asyncio.to_thread(self._driver.quit)
            except Exception:
                pass
            self._driver = None
        return BrowserStepResult(True, "browser closed")
