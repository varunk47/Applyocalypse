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

from applyocalypse_automation.browser import human_typing
from applyocalypse_automation.browser.adapter import BrowserField
from applyocalypse_automation.browser.field_detection import (
    DOM_FIELD_DISCOVERY_SCRIPT,
    DOM_REACHED_FRAME_URLS_JS,
    LOCATE_SCRIPT_MARKER,
    VERIFY_SCRIPT_MARKER,
    WRITE_SCRIPT_MARKER,
    frame_url_is_worth_scanning,
)
from applyocalypse_automation.browser.playwright_adapter import _POINT_ON_FRAME_FUNCTION, PlaywrightBrowserAdapter

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

    async def focus(self, timeout: float | None = None) -> None:
        # Keys go to the page, and Chrome hands them to whatever holds focus.
        self._frame.page.focused = (self._frame, self._selector)

    async def clear(self, timeout: float | None = None) -> None:
        self._frame.cleared.append(self._selector)

    async def fill(self, value: str, timeout: float | None = None) -> None:
        self._frame.fill_calls.append((self._selector, value))

    async def set_input_files(self, path: str, timeout: float | None = None) -> None:
        self._frame.uploaded.append((self._selector, path))


class FakeOwner:
    """The ``<iframe>`` element an embedded document sits in."""

    def __init__(self, box: dict[str, float], inset: list[float]) -> None:
        self._box = box
        self._inset = inset

    async def bounding_box(self) -> dict[str, float]:
        return self._box

    async def evaluate(self, script: str, arg: Any = None, isolated_context: bool = True) -> list[float]:
        return self._inset


class FakeFrame:
    """One document. The top frame and an embedded form differ only in URL."""

    page: FakePage

    def __init__(
        self,
        url: str,
        *,
        fields: list[dict[str, Any]] | None = None,
        click_ok: bool = False,
        reached_frames: list[str] | None = None,
        click_target: dict[str, float] | None = None,
        covered: bool = False,
        box: dict[str, float] | None = None,
        inset: tuple[float, float] = (0.0, 0.0),
        tag_at_point: str = "iframe",
    ) -> None:
        self.url = url
        self._fields = fields or []
        self._click_ok = click_ok
        self._click_target = click_target
        self._covered = covered
        self._box = box
        self._inset = list(inset)
        # What the top document reports under a point when asked with elementFromPoint.
        self._tag_at_point = tag_at_point
        # The frames this document's own DOM walk got into, which is what separates a
        # same-origin embed from a cross-origin one. Empty is the cross-origin default.
        self._reached_frames = reached_frames or []
        self.discovery_calls = 0
        self.write_scripts: list[str] = []
        self.locate_scripts: list[str] = []
        self.click_scripts: list[str] = []
        # (kind of script, whether it ran in the isolated world)
        self.worlds: list[tuple[str, bool]] = []
        self.cleared: list[str] = []
        self.typed: dict[str, str] = {}
        self.fill_calls: list[tuple[str, str]] = []
        self.uploaded: list[tuple[str, str]] = []

    @property
    def filled(self) -> list[tuple[str, str]]:
        """Every value that reached a control, typed key by key or filled in one go."""
        return [*self.typed.items(), *self.fill_calls]

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self, selector)

    async def frame_element(self) -> FakeOwner:
        if self._box is None:
            raise RuntimeError("frame is detached")
        return FakeOwner(self._box, self._inset)

    async def evaluate(self, script: str, arg: Any = None, isolated_context: bool = True) -> Any:
        if script == DOM_REACHED_FRAME_URLS_JS:
            return json.dumps(self._reached_frames)
        if script == DOM_FIELD_DISCOVERY_SCRIPT:
            self.discovery_calls += 1
            return json.dumps(self._fields)
        if script == _POINT_ON_FRAME_FUNCTION:
            return self._tag_at_point
        if LOCATE_SCRIPT_MARKER in script:
            self.worlds.append(("locate", isolated_context))
            self.locate_scripts.append(script)
            return self._locate_result()
        if VERIFY_SCRIPT_MARKER in script:
            self.worlds.append(("verify", isolated_context))
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
            self.worlds.append(("write", isolated_context))
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
        self.worlds.append(("press", isolated_context))
        self.click_scripts.append(script)
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


class FakePage:
    def __init__(self, frames: list[FakeFrame]) -> None:
        self.main_frame = frames[0]
        self.frames = list(frames)
        for frame in frames:
            frame.page = self
        self.focused: tuple[FakeFrame, str] | None = None
        self.sent: list[tuple[str, dict[str, Any]]] = []
        self._fingerprint_calls = 0

    async def evaluate(self, script: str, arg: Any = None, isolated_context: bool = True) -> str:
        # Only _probe_page_fingerprint evaluates against the page itself. Moving off
        # the baseline once lets a click settle instead of burning the full timeout.
        self._fingerprint_calls += 1
        return "before" if self._fingerprint_calls == 1 else "after"


class FakeSession:
    """The page's CDP session. Key events land in whichever control holds focus."""

    def __init__(self, page: FakePage, *, broken: bool) -> None:
        self._page = page
        self._broken = broken

    async def send(self, method: str, params: dict[str, Any]) -> None:
        if self._broken:
            raise RuntimeError("target closed")
        self._page.sent.append((method, params))
        if self._page.focused is None:
            return
        frame, selector = self._page.focused
        if method == "Input.insertText":
            frame.typed[selector] = frame.typed.get(selector, "") + params["text"]
        elif method == "Input.dispatchKeyEvent" and params["type"] == "keyDown":
            if "selectAll" in params.get("commands", []):
                frame.cleared.append(selector)
            elif "text" in params:
                frame.typed[selector] = frame.typed.get(selector, "") + params["text"]


class FakeContext:
    def __init__(self, *, broken_input: bool) -> None:
        self._broken_input = broken_input

    async def new_cdp_session(self, page: FakePage) -> FakeSession:
        return FakeSession(page, broken=self._broken_input)


@pytest.fixture(autouse=True)
def _no_typing_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(human_typing, "keystroke_delay", lambda *_args: 0.0)


def _adapter(frames: list[FakeFrame], *, broken_input: bool = False) -> tuple[PlaywrightBrowserAdapter, FakePage]:
    page = FakePage(frames)
    adapter = PlaywrightBrowserAdapter()
    adapter._page = page
    adapter._context = FakeContext(broken_input=broken_input)
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


def test_a_same_origin_embed_the_dom_walk_entered_is_not_scanned_again() -> None:
    """The other half of the division of labour, and the one Playwright can break.

    Cross-origin frames belong to the adapter's frame enumeration; same-origin ones
    belong to the DOM walk, which reaches them through contentDocument. Playwright
    lists frames regardless of origin, so an embed the walk already went into gets
    offered a second time unless discovery says where the boundary fell. Two copies
    of one question is not cosmetic: the second write lands on a control the first
    already answered, and the reviewer is asked the same thing twice with no way to
    tell it is the same thing.
    """
    top = FakeFrame(
        _EMPLOYER_URL,
        fields=[_raw_field("Email", "#email", dom_path=_NESTED)],
        reached_frames=[_EMBED_URL],
    )
    embed = FakeFrame(_EMBED_URL, fields=[_raw_field("Email", "#email")])
    adapter, _ = _adapter([top, embed])

    fields = asyncio.run(adapter.detect_fields())

    assert [field.label for field in fields] == ["Email"]
    assert embed.discovery_calls == 0, "the frame was harvested a second time"
    # The surviving copy is the one that knows how to get back to the control.
    assert fields[0].metadata["dom_path"] == _NESTED


def test_one_broken_frame_does_not_lose_the_others() -> None:
    class ExplodingFrame(FakeFrame):
        async def evaluate(self, script: str, arg: Any = None, isolated_context: bool = True) -> Any:
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


def test_a_field_is_cleared_in_its_own_frame_before_typing() -> None:
    """Clearing the top document would leave the real field's prefill in place."""
    adapter, top, embed = _greenhouse()
    field = asyncio.run(adapter.detect_fields())[0]

    asyncio.run(adapter.apply_field_value(field, "alex@example.com"))

    assert embed.cleared == ["#email"]
    assert top.cleared == []


def test_a_reachable_field_is_typed_with_trusted_keystrokes() -> None:
    adapter, _, embed = _greenhouse()
    field = asyncio.run(adapter.detect_fields())[0]

    result = asyncio.run(adapter.apply_field_value(field, "alex@example.com"))

    assert result.payload["input_strategy"] == "keystrokes"
    assert embed.typed == {"#email": "alex@example.com"}
    assert embed.fill_calls == []
    assert embed.write_scripts == []


def test_a_broken_input_session_still_fills_the_field() -> None:
    """Keystrokes are the better path, not the only one."""
    top = FakeFrame(_EMPLOYER_URL)
    embed = FakeFrame(_EMBED_URL, fields=[_raw_field("Email", "#email")])
    adapter, _ = _adapter([top, embed], broken_input=True)
    field = asyncio.run(adapter.detect_fields())[0]

    result = asyncio.run(adapter.apply_field_value(field, "alex@example.com"))

    assert result.ok is True, result.message
    assert result.payload["input_strategy"] == "fill"
    assert embed.cleared == ["#email"], "Playwright's own clear should have run instead"
    assert embed.fill_calls == [("#email", "alex@example.com")]


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


# ---------------------------------------------------------------------------
# clicks the page cannot tell were ours
# ---------------------------------------------------------------------------

_TARGET = {"x": 300.0, "y": 200.0, "jx": 12.0, "jy": 8.0}


def _mouse_events(page: FakePage) -> list[dict[str, Any]]:
    return [params for method, params in page.sent if method == "Input.dispatchMouseEvent"]


def test_a_button_we_can_reach_is_pressed_with_the_mouse() -> None:
    """The point of all of this: no ``element.click()``, so no ``isTrusted: false``."""
    top = FakeFrame(_EMPLOYER_URL, click_ok=True, click_target=_TARGET)
    adapter, page = _adapter([top])

    result = asyncio.run(adapter.click_by_text(["Apply now"]))

    events = _mouse_events(page)
    assert result.ok is True, result.message
    assert result.payload["click_dispatch"] == "trusted_input"
    assert top.click_scripts == [], "the page was asked to click after we already had"
    assert [event["type"] for event in events][-2:] == ["mousePressed", "mouseReleased"]
    assert abs(events[-1]["x"] - 300.0) <= 12.0
    assert abs(events[-1]["y"] - 200.0) <= 8.0


def test_the_coordinates_do_not_follow_the_click_into_the_run_record() -> None:
    """``runner.py`` spreads these payloads into emitted events. They are scratch."""
    top = FakeFrame(_EMPLOYER_URL, click_ok=True, click_target=_TARGET)
    adapter, _ = _adapter([top])

    result = asyncio.run(adapter.click_by_text(["Apply now"]))

    assert "click_target" not in result.payload


def test_a_button_we_cannot_locate_is_still_clicked_the_old_way() -> None:
    top = FakeFrame(_EMPLOYER_URL, click_ok=True)
    adapter, page = _adapter([top])

    result = asyncio.run(adapter.click_by_text(["Apply now"]))

    assert result.ok is True, result.message
    assert result.payload["click_dispatch"] == "injected_js"
    assert _mouse_events(page) == []
    assert len(top.click_scripts) == 1


def test_a_button_under_a_cookie_banner_is_clicked_by_script_not_by_coordinate() -> None:
    """Pressing a covered point would click the banner, and on a form that is not safe."""
    top = FakeFrame(_EMPLOYER_URL, click_ok=True, covered=True)
    adapter, page = _adapter([top])

    result = asyncio.run(adapter.click_by_text(["Apply now"]))

    assert result.ok is True, result.message
    assert result.payload["click_dispatch"] == "injected_js"
    assert _mouse_events(page) == []


def test_a_control_that_matched_nothing_is_not_asked_twice() -> None:
    top = FakeFrame(_EMPLOYER_URL)
    adapter, _ = _adapter([top])

    result = asyncio.run(adapter.click_by_text(["Apply now"]))

    assert result.ok is False
    assert top.click_scripts == []
    assert len(top.locate_scripts) == 1


def test_a_click_inside_an_embedded_form_is_moved_into_top_level_coordinates() -> None:
    """The frame measures from its own corner, and the mouse is aimed at the page.

    The iframe's box plus its border and padding is where that corner sits.
    """
    top = FakeFrame(_EMPLOYER_URL)
    embed = FakeFrame(
        _EMBED_URL,
        click_ok=True,
        click_target={"x": 10.0, "y": 20.0, "jx": 0.0, "jy": 0.0},
        box={"x": 100.0, "y": 50.0, "width": 600.0, "height": 800.0},
        inset=(2.0, 2.0),
    )
    adapter, page = _adapter([top, embed])

    result = asyncio.run(adapter.click_final_submit(["Submit application"]))

    events = _mouse_events(page)
    assert result.payload["click_dispatch"] == "trusted_input"
    assert (events[-1]["x"], events[-1]["y"]) == (112.0, 72.0)
    assert embed.click_scripts == []


def test_an_embedded_form_the_page_is_not_showing_is_clicked_by_script() -> None:
    """A frame scrolled below the fold reports a box the translation would miss."""
    top = FakeFrame(_EMPLOYER_URL, tag_at_point="div")
    embed = FakeFrame(
        _EMBED_URL,
        click_ok=True,
        click_target={"x": 10.0, "y": 20.0, "jx": 0.0, "jy": 0.0},
        box={"x": 100.0, "y": 50.0, "width": 600.0, "height": 800.0},
    )
    adapter, page = _adapter([top, embed])

    result = asyncio.run(adapter.click_final_submit(["Submit application"]))

    assert result.payload["click_dispatch"] == "injected_js"
    assert _mouse_events(page) == []
    assert len(embed.click_scripts) == 1


def test_reads_stay_hidden_and_writes_happen_where_the_page_can_see_them() -> None:
    """Measuring is a read, so it runs in the isolated world.

    A press or a write has to reach the page's own listeners, so those run in the
    main world.
    """
    top = FakeFrame(_EMPLOYER_URL, click_ok=True)
    embed = FakeFrame(_EMBED_URL, fields=[_raw_field("Work authorization", "#auth", "select")])
    adapter, _ = _adapter([top, embed])
    field = asyncio.run(adapter.detect_fields())[0]

    asyncio.run(adapter.apply_field_value(field, "Yes"))
    asyncio.run(adapter.click_by_text(["Apply now"]))

    assert embed.worlds == [("write", False)]
    assert top.worlds == [("locate", True), ("press", False)]
