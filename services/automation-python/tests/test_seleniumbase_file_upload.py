"""SeleniumBase must still upload into a dropzone's hidden file input (audit row 15).

Playwright and nodriver set files through a driver API that ignores visibility, so
the discovery fix was enough for them. Selenium's ``send_keys`` refuses an element
it considers non-interactable, and SeleniumBase is a live fallback for ATS portals
(``adapter_factory.py`` walks playwright then nodriver then seleniumbase). Without
the reveal, the run reaches the submit gate reporting a filled application whose
resume never attached.

The reveal has to be temporary: the whole point of this app is that a human looks
at the page before anything is submitted, and they should see the form the portal
renders, not one this adapter left forced open.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from applyocalypse_automation.browser.adapter import BrowserField
from applyocalypse_automation.browser.seleniumbase_adapter import (
    _RESTORE_INLINE_STYLE_JS,
    _REVEAL_FILE_INPUT_JS,
    SeleniumBaseBrowserAdapter,
)

HIDDEN_STYLE = "display:none"


class _FakeElement:
    """A file input that refuses send_keys until something makes it visible."""

    def __init__(self, *, interactable: bool, style: str | None) -> None:
        self.interactable = interactable
        self.style = style
        self.written: list[str] = []

    def send_keys(self, value: str) -> None:
        if not self.interactable:
            raise RuntimeError("element not interactable")
        self.written.append(value)


class _FakeDriver:
    def __init__(self, element: _FakeElement, *, reveal_works: bool = True) -> None:
        self.element = element
        self.reveal_works = reveal_works
        self.scripts: list[tuple[str, tuple]] = []
        self.selectors: list[str] = []

    def find_element(self, by: str, selector: str) -> _FakeElement:
        self.selectors.append(selector)
        return self.element

    def execute_script(self, script: str, *args: object) -> object:
        self.scripts.append((script, args))
        if script == _REVEAL_FILE_INPUT_JS:
            previous = self.element.style
            self.element.style = "display:block !important"
            # An ancestor set to display:none cannot be fixed from the input itself.
            self.element.interactable = self.reveal_works
            return previous
        if script == _RESTORE_INLINE_STYLE_JS:
            self.element.style = args[1]
        return None


def _adapter_with(driver: _FakeDriver) -> SeleniumBaseBrowserAdapter:
    adapter = SeleniumBaseBrowserAdapter()
    adapter._driver = driver
    return adapter


def _resume_field() -> BrowserField:
    return BrowserField(
        field_id="resume",
        label="Resume",
        field_type="file",
        selector="#resume",
        required=True,
        confidence=1.0,
    )


def _resume_on_disk(tmp_path: Path) -> Path:
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.7\n")
    return resume


def test_a_visible_file_input_uploads_without_touching_the_page(tmp_path: Path) -> None:
    element = _FakeElement(interactable=True, style=None)
    driver = _FakeDriver(element)
    resume = _resume_on_disk(tmp_path)

    result = asyncio.run(_adapter_with(driver).upload_file(_resume_field(), resume))

    assert result.ok is True
    assert element.written == [str(resume)]
    assert driver.scripts == [], "an ordinary picker must not be restyled"
    assert result.payload["revealed_hidden_input"] is False


def test_a_hidden_dropzone_input_is_revealed_then_restored(tmp_path: Path) -> None:
    element = _FakeElement(interactable=False, style=HIDDEN_STYLE)
    driver = _FakeDriver(element)
    resume = _resume_on_disk(tmp_path)

    result = asyncio.run(_adapter_with(driver).upload_file(_resume_field(), resume))

    assert result.ok is True
    assert element.written == [str(resume)], "the resume never reached the input"
    assert result.payload["revealed_hidden_input"] is True
    assert [script for script, _ in driver.scripts] == [_REVEAL_FILE_INPUT_JS, _RESTORE_INLINE_STYLE_JS]
    assert element.style == HIDDEN_STYLE, "the dropzone was left forced open"


def test_an_input_with_no_inline_style_is_restored_to_having_none(tmp_path: Path) -> None:
    """Restoring ``None`` has to clear the attribute, not write the string "None"."""
    element = _FakeElement(interactable=False, style=None)
    driver = _FakeDriver(element)

    result = asyncio.run(_adapter_with(driver).upload_file(_resume_field(), _resume_on_disk(tmp_path)))

    assert result.ok is True
    restore_args = [args for script, args in driver.scripts if script == _RESTORE_INLINE_STYLE_JS]
    assert restore_args == [(element, None)]
    assert element.style is None


def test_an_upload_that_fails_even_after_the_reveal_still_restores_the_page(tmp_path: Path) -> None:
    """A display:none ancestor cannot be undone from the input, and that is honest."""
    element = _FakeElement(interactable=False, style=HIDDEN_STYLE)
    driver = _FakeDriver(element, reveal_works=False)

    result = asyncio.run(_adapter_with(driver).upload_file(_resume_field(), _resume_on_disk(tmp_path)))

    assert result.ok is False, "reporting success with nothing attached is the failure this fixes"
    assert "not interactable" in result.payload["error"]
    assert element.written == []
    assert element.style == HIDDEN_STYLE, "a failed upload must not leave the form altered"


def test_a_missing_file_is_reported_before_the_page_is_touched(tmp_path: Path) -> None:
    element = _FakeElement(interactable=True, style=None)
    driver = _FakeDriver(element)

    result = asyncio.run(_adapter_with(driver).upload_file(_resume_field(), tmp_path / "gone.pdf"))

    assert result.ok is False
    assert driver.scripts == []
    assert driver.selectors == []
