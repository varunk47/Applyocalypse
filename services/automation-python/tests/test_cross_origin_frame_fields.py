"""Portals that embed their form cross-origin (audit finding F9, second half).

Greenhouse serves ``grnhse_iframe`` from ``job-boards.greenhouse.io`` onto the
employer's own domain. The employer page is a wrapper: every question, the resume
input and the submit button live inside a document from a different origin. An
adapter that only ever talks to the top document sees an empty page, and a write
aimed at the top document lands nowhere while still looking like it worked.

So the adapter has to address frames directly. These cases pin the three things
that has to get right: find the fields, write them back to the frame they came
from, and refuse rather than guess when that frame is gone.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from applyocalypse_automation.browser.adapter import BrowserField
from applyocalypse_automation.browser.field_detection import (
    DOM_FIELD_DISCOVERY_SCRIPT,
    VERIFY_SCRIPT_MARKER,
    WRITE_SCRIPT_MARKER,
    frame_url_is_worth_scanning,
)
from applyocalypse_automation.browser.playwright_adapter import PlaywrightBrowserAdapter

_EMPLOYER_URL = "https://careers.employer.example/jobs/42"
_EMBED_URL = "https://job-boards.greenhouse.io/employer/jobs/42"


def _raw_field(
    label: str,
    selector: str,
    field_type: str = "text",
    dom_path: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "label": label,
        "label_source": "label",
        "field_type": field_type,
        "selector": selector,
        "required": True,
        "metadata": {"tag_name": "input"},
    }
    if dom_path is not None:
        # Set when discovery walked out of the frame's own document into a
        # same-origin iframe or an open shadow root nested inside it.
        raw["dom_path"] = dom_path
    return raw


class FakeLocator:
    def __init__(self, frame: FakeFrame, selector: str) -> None:
        self._frame = frame
        self._selector = selector

    async def fill(self, value: str, timeout: float | None = None) -> None:
        self._frame.filled.append((self._selector, value))

    async def set_input_files(self, path: str, timeout: float | None = None) -> None:
        self._frame.uploaded.append((self._selector, path))


class FakeFrame:
    """One document. The top frame and an embedded form differ only in URL."""

    def __init__(self, url: str, *, fields: list[dict[str, Any]] | None = None, click_ok: bool = False) -> None:
        self.url = url
        self._fields = fields or []
        self._click_ok = click_ok
        self.discovery_calls = 0
        self.write_scripts: list[str] = []
        self.click_scripts: list[str] = []
        self.filled: list[tuple[str, str]] = []
        self.uploaded: list[tuple[str, str]] = []

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self, selector)

    async def evaluate(self, script: str) -> str:
        if script == DOM_FIELD_DISCOVERY_SCRIPT:
            self.discovery_calls += 1
            return json.dumps(self._fields)
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
        if self._click_ok:
            return json.dumps({"ok": True, "message": "clicked", "clicked_label": "Submit application"})
        return json.dumps({"ok": False, "message": "no matching control was found"})


class FakePage:
    def __init__(self, frames: list[FakeFrame]) -> None:
        self.main_frame = frames[0]
        self.frames = list(frames)
        self._fingerprint_calls = 0

    async def evaluate(self, script: str) -> str:
        # Only _probe_page_fingerprint evaluates against the page itself. Moving off
        # the baseline once lets a click settle instead of burning the full timeout.
        self._fingerprint_calls += 1
        return "before" if self._fingerprint_calls == 1 else "after"


def _adapter(frames: list[FakeFrame]) -> tuple[PlaywrightBrowserAdapter, FakePage]:
    page = FakePage(frames)
    adapter = PlaywrightBrowserAdapter()
    adapter._page = page
    return adapter, page


def _greenhouse() -> tuple[PlaywrightBrowserAdapter, FakeFrame, FakeFrame]:
    """The employer wrapper holds nothing; the embedded Greenhouse form holds it all."""
    top = FakeFrame(_EMPLOYER_URL)
    embed = FakeFrame(_EMBED_URL, fields=[_raw_field("Email", "#email")])
    adapter, _ = _adapter([top, embed])
    return adapter, top, embed


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
    """A portal that hosts its own form must behave exactly as it did before.

    No frame metadata and an unqualified field_id, so nothing downstream that
    already stored an id has to change.
    """
    top = FakeFrame(_EMPLOYER_URL, fields=[_raw_field("Email", "#email")])
    adapter, _ = _adapter([top])

    fields = asyncio.run(adapter.detect_fields())

    assert "frame_url" not in fields[0].metadata
    assert fields[0].field_id.startswith("field:")


def test_field_ids_do_not_collide_between_frames() -> None:
    """Discovery restarts its index at zero in every frame.

    Two frames whose first field is the same question would otherwise produce the
    same field_id, and answering one would look like answering both.
    """
    top = FakeFrame(_EMPLOYER_URL, fields=[_raw_field("Email", "#email")])
    embed = FakeFrame(_EMBED_URL, fields=[_raw_field("Email", "#email")])
    adapter, _ = _adapter([top, embed])

    fields = asyncio.run(adapter.detect_fields())

    assert len({field.field_id for field in fields}) == 2


def test_captcha_frames_are_never_scanned() -> None:
    """A reCAPTCHA widget really does contain inputs.

    Scanning it would offer the model a challenge box to answer, which is the one
    thing this product refuses to do.
    """
    top = FakeFrame(_EMPLOYER_URL)
    captcha = FakeFrame("https://www.google.com/recaptcha/api2/anchor?k=abc")
    adapter, _ = _adapter([top, captcha])

    asyncio.run(adapter.detect_fields())

    assert captcha.discovery_calls == 0


def test_one_broken_frame_does_not_lose_the_others() -> None:
    class ExplodingFrame(FakeFrame):
        async def evaluate(self, script: str) -> str:
            raise RuntimeError("frame detached mid-sweep")

    top = ExplodingFrame(_EMPLOYER_URL)
    embed = FakeFrame(_EMBED_URL, fields=[_raw_field("Email", "#email")])
    adapter, _ = _adapter([top, embed])

    assert [field.label for field in asyncio.run(adapter.detect_fields())] == ["Email"]


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://job-boards.greenhouse.io/acme/jobs/1", True),
        ("https://boards.eu.lever.co/acme/apply", True),
        ("https://www.google.com/recaptcha/api2/anchor", False),
        ("https://challenges.cloudflare.com/turnstile/v0/api.js", False),
        ("https://www.googletagmanager.com/ns.html?id=GTM-1", False),
        ("https://widget.intercom.io/frame", False),
        ("about:blank", False),
        ("", False),
    ],
)
def test_frame_url_filter(url: str, expected: bool) -> None:
    assert frame_url_is_worth_scanning(url) is expected


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


def test_a_scripted_write_lands_in_the_frame_the_field_came_from() -> None:
    top = FakeFrame(_EMPLOYER_URL)
    embed = FakeFrame(_EMBED_URL, fields=[_raw_field("Work authorization", "#auth", "select")])
    adapter, _ = _adapter([top, embed])
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
    adapter, _ = _adapter([top, embed])
    field = asyncio.run(adapter.detect_fields())[0]

    result = asyncio.run(adapter.upload_file(field, resume))

    assert result.ok is True, result.message
    assert [selector for selector, _ in embed.uploaded] == ["#resume"]
    assert top.uploaded == []


_NESTED = [{"kind": "frame", "selector": "#inner", "index": 0}]


def test_a_field_below_the_frame_document_takes_the_scripted_write() -> None:
    """``locator`` resolves from the frame's own document and stops at a boundary.

    For a field discovered inside a nested root it matches either nothing or the
    same-named control in the parent, and ``fill`` would then put the user's answer
    in a form nobody chose. Those fields take the scripted write, which replays the
    path before it touches anything.
    """
    top = FakeFrame(_EMPLOYER_URL)
    embed = FakeFrame(_EMBED_URL, fields=[_raw_field("Email", "#email", dom_path=_NESTED)])
    adapter, _ = _adapter([top, embed])
    field = asyncio.run(adapter.detect_fields())[0]

    result = asyncio.run(adapter.apply_field_value(field, "alex@example.com"))

    assert result.ok is True, result.message
    assert len(embed.write_scripts) == 1
    assert embed.filled == []
    assert top.filled == []


def test_a_file_input_below_the_frame_document_refuses(tmp_path: Path) -> None:
    """``set_input_files`` has no scripted equivalent, so this one fails closed."""
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4")
    top = FakeFrame(_EMPLOYER_URL)
    embed = FakeFrame(_EMBED_URL, fields=[_raw_field("Resume", "#resume", "file", dom_path=_NESTED)])
    adapter, _ = _adapter([top, embed])
    field = asyncio.run(adapter.detect_fields())[0]

    result = asyncio.run(adapter.upload_file(field, resume))

    assert result.ok is False
    assert "the driver cannot address" in result.message
    assert embed.uploaded == []
    assert top.uploaded == []


def test_a_vanished_frame_refuses_instead_of_writing_to_the_top_document() -> None:
    """The failure that must never be silent.

    If the embedded form is gone and we fall back to the main frame, the write
    either does nothing or hits an unrelated control, and either way the run
    reports a success the portal never saw.
    """
    adapter, top, _ = _greenhouse()
    field = asyncio.run(adapter.detect_fields())[0]
    adapter._page.frames = [top]  # the embed detached between discovery and write

    result = asyncio.run(adapter.apply_field_value(field, "alex@example.com"))

    assert result.ok is False
    assert "no longer on the page" in result.message
    assert top.filled == []


def test_ambiguous_frames_refuse_rather_than_pick_one() -> None:
    top = FakeFrame(_EMPLOYER_URL)
    first = FakeFrame(_EMBED_URL, fields=[_raw_field("Email", "#email")])
    duplicate = FakeFrame(_EMBED_URL)
    adapter, _ = _adapter([top, first, duplicate])
    field = asyncio.run(adapter.detect_fields())[0]
    # Both embeds now answer to the same URL and the recorded index no longer
    # points at the one the field came from.
    adapter._page.frames = [top, duplicate, first]
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


# ---------------------------------------------------------------------------
# clicks
# ---------------------------------------------------------------------------


def test_submit_reaches_the_button_inside_the_embedded_form() -> None:
    """On an embedded portal the submit button is not in the top document."""
    top = FakeFrame(_EMPLOYER_URL)
    embed = FakeFrame(_EMBED_URL, click_ok=True)
    adapter, _ = _adapter([top, embed])

    result = asyncio.run(adapter.click_final_submit(["Submit application"]))

    assert result.ok is True, result.message
    assert result.payload["action"] == "final_submit"
    assert len(embed.click_scripts) == 1


def test_the_top_document_is_always_tried_first() -> None:
    """A portal that hosts its own form must not have its clicks go frame-hunting."""
    top = FakeFrame(_EMPLOYER_URL, click_ok=True)
    embed = FakeFrame(_EMBED_URL, click_ok=True)
    adapter, _ = _adapter([top, embed])

    asyncio.run(adapter.click_by_text(["Apply now"]))

    assert len(top.click_scripts) == 1
    assert embed.click_scripts == [], "the embedded frame was clicked as well"


def test_a_click_that_matches_nowhere_reports_the_refusal() -> None:
    top = FakeFrame(_EMPLOYER_URL)
    embed = FakeFrame(_EMBED_URL)
    adapter, _ = _adapter([top, embed])

    result = asyncio.run(adapter.click_final_submit(["Submit application"]))

    assert result.ok is False
    assert "no matching control" in result.message
