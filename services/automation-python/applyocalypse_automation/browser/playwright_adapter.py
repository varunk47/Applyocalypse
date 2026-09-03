from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .adapter import BrowserAdapter, BrowserBlocker, BrowserField, BrowserStepResult, screenshot_payload
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
from .page_readiness import (
    PAGE_TEXT_POLL_INTERVAL_S,
    PAGE_TEXT_TIMEOUT_S,
    POST_CLICK_POLL_INTERVAL_S,
    POST_CLICK_TIMEOUT_S,
    POST_CLICK_UNCHANGED_GRACE_S,
    wait_for_page_change,
    wait_for_page_text,
)

PAGE_TEXT_LENGTH_PROBE_FUNCTION = "() => (((document.body && document.body.innerText) || '').trim().length)"
PAGE_FINGERPRINT_PROBE_FUNCTION = (
    "() => (location.href + '|' + (document.title || '') + '|'"
    " + String(((document.body && document.body.innerText) || '').trim().length))"
)



class PlaywrightBrowserAdapter(BrowserAdapter):
    """The Playwright-protocol adapter, driven by Patchright rather than Playwright.

    Patchright is a drop-in fork of Playwright -- same package layout, same API,
    same two dependencies -- with the tells patched out of the driver rather than
    papered over from inside the page. It runs its own scripts in isolated
    execution contexts instead of enabling ``Runtime`` (the leak we hand-built
    ``isolated_world.py`` to avoid on nodriver), drops the ``--enable-automation``
    flag family, and reaches into closed shadow roots, which our own F9 traversal
    cannot. Vanilla Playwright is not kept as a fallback: an adapter that silently
    downgrades to the leaky driver would report a stealth posture it does not have.

    The adapter keeps the name "playwright" because that is what it speaks and what
    every persisted run record already says. ``driver_check`` reports the module it
    actually imports, so the build can still be asked which driver it carries.
    """

    name = "playwright"

    def __init__(self) -> None:
        self._playwright = None
        self._context = None
        self._page = None

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
        try:
            self._playwright = await async_playwright().start()
            # Patchright's documented configuration, and every part of it is load-bearing.
            # ``channel="chrome"`` drives the real Chrome the user already has, which is
            # also the browser nodriver drives, so no bundled Chromium has to be shipped
            # or downloaded and the fingerprint is a genuine one rather than Chromium's.
            # ``no_viewport`` leaves the window at its natural size instead of the fixed
            # 1280x720 that Playwright otherwise forces on every page. Nothing else is
            # passed: custom args, headers and user agents are what give the fork away,
            # and the defaults already include --no-first-run.
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir),
                channel="chrome",
                headless=False,
                no_viewport=True,
            )
            self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        except Exception as exc:
            if self._playwright is not None:
                await self._playwright.stop()
            self._playwright = None
            self._context = None
            self._page = None
            return BrowserStepResult(False, "playwright browser launch failed", {"run_id": run_id, "error": str(exc)})

        return BrowserStepResult(True, "browser launched", {"run_id": run_id})

    async def open_url(self, url: str) -> BrowserStepResult:
        if self._page is None:
            return BrowserStepResult(False, "browser page is not available", {"url": url})
        try:
            await self._page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        except Exception as exc:
            return BrowserStepResult(False, "page navigation failed", {"url": url, "error": str(exc)})
        readiness = await wait_for_page_text(
            self._probe_visible_text_length,
            timeout_s=PAGE_TEXT_TIMEOUT_S,
            poll_interval_s=PAGE_TEXT_POLL_INTERVAL_S,
        )
        return BrowserStepResult(True, "page navigated", {"url": url, "page_text": readiness})

    async def _probe_visible_text_length(self) -> int:
        if self._page is None:
            return 0
        raw = await self._page.evaluate(PAGE_TEXT_LENGTH_PROBE_FUNCTION)
        try:
            return int(raw or 0)
        except (TypeError, ValueError):
            return 0

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
        try:
            await frame.locator(field.selector).fill(value, timeout=10_000)
        except Exception as exc:
            return BrowserStepResult(False, "field value fill failed", {"field_id": field.field_id, "error": str(exc)})
        return BrowserStepResult(True, "field value applied", {"field_id": field.field_id})

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
            return await verify_or_repair_text_write(frame.evaluate, field, value, fill_payload=filled.payload)
        try:
            raw_result = await frame.evaluate(
                build_apply_field_value_script(field.selector, value, dom_path_for(field))
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
        for frame in self._form_frames():
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
        return BrowserStepResult(True, "browser closed")
