"""nodriver is the adapter that actually runs, so it needs the frame support too.

``test_cross_origin_frame_fields.py`` pins this behaviour for Playwright. That
work never ran for a user: Playwright is not a dependency of this project, so
every ATS run fell back to nodriver, which addressed only the top document.
On Greenhouse, Workable, Ashby or iCIMS embedded onto an employer's careers page
that means discovery saw an empty wrapper, and a write aimed at the top document
landed nowhere while still reporting success.

The two adapters reach frames by different routes. Playwright hands back every
frame including same-origin ones; nodriver goes through Chrome's site isolation,
where a cross-origin iframe gets its own CDP target and comes back as a
connectable ``IFrame``. Same contract either way: find the fields, write them
back to the frame they came from, and refuse rather than guess when it is gone.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from applyocalypse_automation.browser.adapter import BrowserField
from applyocalypse_automation.browser.field_detection import (
    DOM_FIELD_DISCOVERY_SCRIPT,
    LOCATE_SCRIPT_MARKER,
    VERIFY_SCRIPT_MARKER,
    WRITE_SCRIPT_MARKER,
)
from applyocalypse_automation.browser.nodriver_adapter import (
    PAGE_FINGERPRINT_PROBE_SCRIPT,
    NodriverBrowserAdapter,
)

_EMPLOYER_URL = "https://careers.employer.example/jobs/42"
_EMBED_URL = "https://job-boards.greenhouse.io/employer/jobs/42"


def _raw_field(label: str, selector: str, field_type: str = "text") -> dict[str, Any]:
    return {
        "label": label,
        "label_source": "label",
        "field_type": field_type,
        "selector": selector,
        "required": True,
        "metadata": {"tag_name": "input"},
    }


class _FakeTargetInfo:
    """nodriver reads a frame's URL off the CDP target it is attached to."""

    def __init__(self, url: str) -> None:
        self.url = url


class FakeElement:
    def __init__(self, frame: FakeFrame, selector: str) -> None:
        self._frame = frame
        self._selector = selector

    async def clear_input(self) -> None:
        self._frame.cleared.append(self._selector)

    async def send_keys(self, value: str) -> None:
        self._frame.filled.append((self._selector, value))

    async def send_file(self, path: Path) -> None:
        self._frame.uploaded.append((self._selector, str(path)))


class FakeFrame:
    """One document. The top tab and an embedded IFrame differ only in URL."""

    def __init__(
        self,
        url: str,
        *,
        fields: list[dict[str, Any]] | None = None,
        click_ok: bool = False,
        click_target: dict[str, float] | None = None,
        covered: bool = False,
    ) -> None:
        self.target = _FakeTargetInfo(url)
        self._fields = fields or []
        self._click_ok = click_ok
        self._click_target = click_target
        self._covered = covered
        self.discovery_calls = 0
        self.write_scripts: list[str] = []
        self.click_scripts: list[str] = []
        self.locate_scripts: list[str] = []
        self.press_scripts: list[str] = []
        self.sent: list[dict[str, Any]] = []
        self.cleared: list[str] = []
        self.filled: list[tuple[str, str]] = []
        self.uploaded: list[tuple[str, str]] = []
        self.frames: list[FakeFrame] = []
        self.fingerprints = 0

    async def get_frames(self) -> list[FakeFrame]:
        return list(self.frames)

    async def select(self, selector: str) -> FakeElement:
        return FakeElement(self, selector)

    async def evaluate(self, script: str) -> str:
        if script == DOM_FIELD_DISCOVERY_SCRIPT:
            self.discovery_calls += 1
            return json.dumps(self._fields)
        if script == PAGE_FINGERPRINT_PROBE_SCRIPT:
            # A click is followed by a settle poll on the top document. Reporting a
            # changed page lets that finish immediately instead of timing out.
            self.fingerprints += 1
            return "before" if self.fingerprints == 1 else "after"
        if VERIFY_SCRIPT_MARKER in script:
            return json.dumps(
                {
                    "ok": True,
                    "action": "verify",
                    "field_type": "text",
                    "verified": True,
                    "value_matched": True,
                    "message": "field value applied",
                }
            )
        if WRITE_SCRIPT_MARKER in script:
            self.write_scripts.append(script)
            return json.dumps(
                {
                    "ok": True,
                    "action": "set_value",
                    "field_type": "select",
                    "verified": True,
                    "value_matched": True,
                    "message": "field value applied",
                }
            )
        self.click_scripts.append(script)
        if LOCATE_SCRIPT_MARKER in script:
            self.locate_scripts.append(script)
            return self._locate_result()
        self.press_scripts.append(script)
        if self._click_ok:
            return json.dumps({"ok": True, "message": "clicked", "clicked_label": "Submit application"})
        return json.dumps({"ok": False, "message": "no matching control was found"})

    def _locate_result(self) -> str:
        """What the page says when asked where the control is rather than to click it."""
        if not self._click_ok:
            return json.dumps({"ok": False, "message": "no matching control was found"})
        if self._covered:
            return json.dumps(
                {
                    "ok": False,
                    "message": "the matched control is covered by something else",
                    "fallback": "injected_js",
                }
            )
        payload: dict[str, Any] = {"ok": True, "message": "clicked", "clicked_label": "Submit application"}
        if self._click_target is not None:
            payload["click_target"] = self._click_target
        return json.dumps(payload)

    async def send(self, command: Any) -> None:
        """Drive a CDP command generator far enough to see what it asked for.

        nodriver's commands are generators that yield a request dict, so this is
        the whole of what a real ``Tab.send`` does before it waits on a socket.
        Returning ``None`` for the response is what makes the frame-translation
        lookups fail, which is deliberate: an embedded frame has to keep working
        by falling back, and this pins that it does.
        """
        try:
            self.sent.append(next(command))
        except (TypeError, StopIteration):
            return None
        return None


def _adapter(top: FakeFrame, embedded: list[FakeFrame] | None = None) -> NodriverBrowserAdapter:
    top.frames = list(embedded or [])
    adapter = NodriverBrowserAdapter()
    adapter._page = top
    return adapter


def _greenhouse() -> tuple[NodriverBrowserAdapter, FakeFrame, FakeFrame]:
    """The employer wrapper holds nothing; the embedded Greenhouse form holds it all."""
    top = FakeFrame(_EMPLOYER_URL)
    embed = FakeFrame(_EMBED_URL, fields=[_raw_field("Email", "#email")])
    return _adapter(top, [embed]), top, embed


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------


def test_fields_inside_an_embedded_form_are_discovered() -> None:
    adapter, _, _ = _greenhouse()

    fields = asyncio.run(adapter.detect_fields())

    assert [field.label for field in fields] == ["Email"]
    assert fields[0].metadata["frame_url"] == _EMBED_URL
    assert fields[0].metadata["frame_index"] == 1


def test_top_level_forms_carry_no_frame_metadata() -> None:
    """A portal that hosts its own form must behave exactly as it did before."""
    adapter = _adapter(FakeFrame(_EMPLOYER_URL, fields=[_raw_field("Email", "#email")]))

    fields = asyncio.run(adapter.detect_fields())

    assert "frame_url" not in fields[0].metadata
    assert fields[0].field_id.startswith("field:")


def test_field_ids_do_not_collide_between_frames() -> None:
    """Two frames whose first question is the same would otherwise share a field_id."""
    top = FakeFrame(_EMPLOYER_URL, fields=[_raw_field("Email", "#email")])
    embed = FakeFrame(_EMBED_URL, fields=[_raw_field("Email", "#email")])
    adapter = _adapter(top, [embed])

    fields = asyncio.run(adapter.detect_fields())

    assert len({field.field_id for field in fields}) == 2


def test_captcha_frames_are_never_scanned() -> None:
    """Scanning a reCAPTCHA frame would offer the model a challenge box to answer."""
    top = FakeFrame(_EMPLOYER_URL)
    captcha = FakeFrame("https://www.google.com/recaptcha/api2/anchor?k=abc")
    adapter = _adapter(top, [captcha])

    asyncio.run(adapter.detect_fields())

    assert captcha.discovery_calls == 0


def test_one_broken_frame_does_not_lose_the_others() -> None:
    class ExplodingFrame(FakeFrame):
        async def evaluate(self, script: str) -> str:
            raise RuntimeError("frame detached mid-sweep")

    top = ExplodingFrame(_EMPLOYER_URL)
    embed = FakeFrame(_EMBED_URL, fields=[_raw_field("Email", "#email")])
    adapter = _adapter(top, [embed])

    assert [field.label for field in asyncio.run(adapter.detect_fields())] == ["Email"]


def test_a_driver_without_frame_support_still_reads_the_top_document() -> None:
    """get_frames is best-effort. Losing it must not cost us the ordinary case."""

    class NoFrameSupport(FakeFrame):
        async def get_frames(self) -> list[FakeFrame]:
            raise RuntimeError("Target.getTargets not available")

    adapter = _adapter(NoFrameSupport(_EMPLOYER_URL, fields=[_raw_field("Email", "#email")]))

    assert [field.label for field in asyncio.run(adapter.detect_fields())] == ["Email"]


# ---------------------------------------------------------------------------
# writes
# ---------------------------------------------------------------------------


def test_a_write_lands_in_the_frame_the_field_came_from() -> None:
    adapter, top, embed = _greenhouse()
    field = asyncio.run(adapter.detect_fields())[0]

    result = asyncio.run(adapter.apply_field_value(field, "alex@example.com"))

    assert result.ok is True, result.message
    assert embed.filled == [("#email", "alex@example.com")]
    assert top.filled == [], "the answer was typed into the wrapper page"


def test_a_field_is_cleared_in_its_own_frame_before_typing() -> None:
    """Clearing the top document would leave the real field's prefill in place."""
    adapter, top, embed = _greenhouse()
    field = asyncio.run(adapter.detect_fields())[0]

    asyncio.run(adapter.apply_field_value(field, "alex@example.com"))

    assert embed.cleared == ["#email"]
    assert top.cleared == []


def test_a_scripted_write_lands_in_the_frame_the_field_came_from() -> None:
    top = FakeFrame(_EMPLOYER_URL)
    embed = FakeFrame(_EMBED_URL, fields=[_raw_field("Work authorization", "#auth", "select")])
    adapter = _adapter(top, [embed])
    field = asyncio.run(adapter.detect_fields())[0]

    result = asyncio.run(adapter.apply_field_value(field, "Yes"))

    assert result.ok is True, result.message
    assert len(embed.write_scripts) == 1
    assert top.write_scripts == []


def test_an_upload_lands_in_the_frame_the_field_came_from(tmp_path: Path) -> None:
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4")
    top = FakeFrame(_EMPLOYER_URL)
    embed = FakeFrame(_EMBED_URL, fields=[_raw_field("Resume", "#resume", "file")])
    adapter = _adapter(top, [embed])
    field = asyncio.run(adapter.detect_fields())[0]

    result = asyncio.run(adapter.upload_file(field, resume))

    assert result.ok is True, result.message
    assert [selector for selector, _ in embed.uploaded] == ["#resume"]
    assert top.uploaded == [], "the resume was attached to the wrapper page"


def test_a_vanished_frame_refuses_instead_of_writing_to_the_top_document() -> None:
    """The failure that must never be silent.

    If the embedded form is gone and we fall back to the top document, the write
    either does nothing or hits an unrelated control, and either way the run
    reports a success the portal never saw.
    """
    adapter, top, _ = _greenhouse()
    field = asyncio.run(adapter.detect_fields())[0]
    top.frames = []  # the embed detached between discovery and write

    result = asyncio.run(adapter.apply_field_value(field, "alex@example.com"))

    assert result.ok is False
    assert "no longer on the page" in result.message
    assert top.filled == []


def test_a_vanished_frame_also_refuses_an_upload(tmp_path: Path) -> None:
    """A resume silently attached to the wrapper is the worst shape of this bug."""
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4")
    top = FakeFrame(_EMPLOYER_URL)
    embed = FakeFrame(_EMBED_URL, fields=[_raw_field("Resume", "#resume", "file")])
    adapter = _adapter(top, [embed])
    field = asyncio.run(adapter.detect_fields())[0]
    top.frames = []

    result = asyncio.run(adapter.upload_file(field, resume))

    assert result.ok is False
    assert "no longer on the page" in result.message
    assert top.uploaded == []


def test_ambiguous_frames_refuse_rather_than_pick_one() -> None:
    top = FakeFrame(_EMPLOYER_URL)
    first = FakeFrame(_EMBED_URL, fields=[_raw_field("Email", "#email")])
    duplicate = FakeFrame(_EMBED_URL)
    adapter = _adapter(top, [first, duplicate])
    field = asyncio.run(adapter.detect_fields())[0]
    field = BrowserField(
        field_id=field.field_id,
        label=field.label,
        field_type=field.field_type,
        selector=field.selector,
        required=field.required,
        confidence=field.confidence,
        metadata={**field.metadata, "frame_index": 99},
    )

    result = asyncio.run(adapter.apply_field_value(field, "alex@example.com"))

    assert result.ok is False
    assert "ambiguous" in result.message


def test_duplicate_urls_are_resolved_by_the_recorded_index() -> None:
    """Two embeds of the same form is legal, and the index still disambiguates."""
    top = FakeFrame(_EMPLOYER_URL)
    first = FakeFrame(_EMBED_URL, fields=[_raw_field("Email", "#email")])
    duplicate = FakeFrame(_EMBED_URL)
    adapter = _adapter(top, [first, duplicate])
    field = asyncio.run(adapter.detect_fields())[0]

    result = asyncio.run(adapter.apply_field_value(field, "alex@example.com"))

    assert result.ok is True, result.message
    assert first.filled == [("#email", "alex@example.com")]
    assert duplicate.filled == []


# ---------------------------------------------------------------------------
# clicks
# ---------------------------------------------------------------------------


def test_submit_reaches_the_button_inside_the_embedded_form() -> None:
    """On an embedded portal the submit button is not in the top document.

    The frame is asked twice: once for coordinates, and once to click, because
    this fake cannot answer the CDP lookup that translates an embedded frame's
    box into the top document. That is the fallback working, and it is the
    behaviour that matters most here: the button still gets pressed.
    """
    top = FakeFrame(_EMPLOYER_URL)
    embed = FakeFrame(_EMBED_URL, click_ok=True)
    adapter = _adapter(top, [embed])

    result = asyncio.run(adapter.click_final_submit(["Submit application"]))

    assert result.ok is True, result.message
    assert result.payload["action"] == "final_submit"
    assert result.payload["click_dispatch"] == "injected_js"
    assert len(embed.locate_scripts) == 1
    assert len(embed.press_scripts) == 1


def test_the_top_document_is_always_tried_first() -> None:
    """A portal that hosts its own form must not have its clicks go frame-hunting."""
    top = FakeFrame(_EMPLOYER_URL, click_ok=True)
    embed = FakeFrame(_EMBED_URL, click_ok=True)
    adapter = _adapter(top, [embed])

    asyncio.run(adapter.click_by_text(["Apply now"]))

    assert len(top.locate_scripts) == 1
    assert embed.click_scripts == [], "the embedded frame was clicked as well"


# ---------------------------------------------------------------------------
# clicks the page cannot tell were ours
# ---------------------------------------------------------------------------


def _mouse_events(frame: FakeFrame) -> list[dict[str, Any]]:
    return [call["params"] for call in frame.sent if call.get("method") == "Input.dispatchMouseEvent"]


def test_a_button_we_can_reach_is_pressed_with_the_mouse() -> None:
    """The point of all of this: no ``element.click()``, so no ``isTrusted: false``.

    A detector reads that property first because it costs nothing and cannot be
    forged from inside the page. Every button this worker pressed used to fail it.
    """
    top = FakeFrame(_EMPLOYER_URL, click_ok=True, click_target={"x": 300.0, "y": 200.0, "jx": 12.0, "jy": 8.0})
    adapter = _adapter(top)

    result = asyncio.run(adapter.click_by_text(["Apply now"]))

    events = _mouse_events(top)
    assert result.ok is True, result.message
    assert result.payload["click_dispatch"] == "trusted_input"
    assert top.press_scripts == [], "the page was asked to click after we already had"
    assert [event["type"] for event in events][-2:] == ["mousePressed", "mouseReleased"]
    assert abs(events[-1]["x"] - 300.0) <= 12.0
    assert abs(events[-1]["y"] - 200.0) <= 8.0


def test_the_coordinates_do_not_follow_the_click_into_the_run_record() -> None:
    """``runner.py`` spreads these payloads into emitted events. They are scratch."""
    top = FakeFrame(_EMPLOYER_URL, click_ok=True, click_target={"x": 300.0, "y": 200.0, "jx": 12.0, "jy": 8.0})

    result = asyncio.run(_adapter(top).click_by_text(["Apply now"]))

    assert "click_target" not in result.payload


def test_a_button_we_cannot_locate_is_still_clicked_the_old_way() -> None:
    """Every reason the mouse path can refuse ends here, so none of them lose a click."""
    top = FakeFrame(_EMPLOYER_URL, click_ok=True)
    adapter = _adapter(top)

    result = asyncio.run(adapter.click_by_text(["Apply now"]))

    assert result.ok is True, result.message
    assert result.payload["click_dispatch"] == "injected_js"
    assert _mouse_events(top) == []
    assert len(top.press_scripts) == 1


def test_a_button_under_a_cookie_banner_is_clicked_by_script_not_by_coordinate() -> None:
    """Pressing a covered point would click the banner, and on a form that is not safe.

    The page refuses to hand over a coordinate it hit-tested to something else,
    and the injected click takes over, which reaches the element directly.
    """
    top = FakeFrame(_EMPLOYER_URL, click_ok=True, covered=True)
    adapter = _adapter(top)

    result = asyncio.run(adapter.click_by_text(["Apply now"]))

    assert result.ok is True, result.message
    assert result.payload["click_dispatch"] == "injected_js"
    assert _mouse_events(top) == []


def test_a_control_that_matched_nothing_is_not_asked_twice() -> None:
    """Nothing matched is not a coordinate problem, so pressing would find the same nothing."""
    top = FakeFrame(_EMPLOYER_URL)
    adapter = _adapter(top)

    result = asyncio.run(adapter.click_by_text(["Apply now"]))

    assert result.ok is False
    assert top.press_scripts == []
    assert len(top.locate_scripts) == 1


def test_a_click_that_matches_nowhere_reports_the_refusal() -> None:
    top = FakeFrame(_EMPLOYER_URL)
    embed = FakeFrame(_EMBED_URL)
    adapter = _adapter(top, [embed])

    result = asyncio.run(adapter.click_final_submit(["Submit application"]))

    assert result.ok is False
    assert "no matching control" in result.message
