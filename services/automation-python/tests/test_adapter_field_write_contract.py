"""Cross-adapter contract: a field write REPLACES the field's contents.

Real portals arrive prefilled. Workday repopulates the form from the parsed
resume before the user ever reaches it, iCIMS prefills from the account that was
just created, returning-candidate flows prefill everything, and the browser
itself autofills name/email/phone. An adapter that types without clearing turns
"Alex Rivera" into "Alex RiveraAlex Rivera" and "a@b.com" into "a@b.coma@b.com",
which fails the portal's own format validation.

Every adapter must satisfy the same contract, so each case is parametrized over
all three implementations driven by in-memory doubles.
"""
from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable

import pytest

from applyocalypse_automation.browser.adapter import BrowserField, BrowserStepResult
from applyocalypse_automation.browser.field_detection import (
    SCRIPTED_WRITE_FIELD_TYPES,
    VERIFY_SCRIPT_MARKER,
    WRITE_SCRIPT_MARKER,
)
from applyocalypse_automation.browser.nodriver_adapter import NodriverBrowserAdapter
from applyocalypse_automation.browser.playwright_adapter import PlaywrightBrowserAdapter
from applyocalypse_automation.browser.seleniumbase_adapter import SeleniumBaseBrowserAdapter

# ---------------------------------------------------------------------------
# Shared control double
# ---------------------------------------------------------------------------


class FakeControl:
    """Models a real form control: typing appends, clearing empties."""

    def __init__(self, value: str = "") -> None:
        self.value = value
        self.clear_calls = 0
        self.type_calls = 0
        self.native_writes = 0
        self.clear_error: Exception | None = None
        self.write_script_error: Exception | None = None
        # A React-controlled input re-renders from state and throws the typed
        # characters away. The keystrokes happened; the value did not stick.
        self.discards_typing = False

    def do_clear(self) -> None:
        if self.clear_error is not None:
            raise self.clear_error
        self.clear_calls += 1
        self.value = ""

    def do_type(self, text: str) -> None:
        self.type_calls += 1
        if self.discards_typing:
            return
        self.value += text


_REVIEWED_VALUE = re.compile(r"^  const reviewedValue = (.+);$", re.MULTILINE)


def evaluate_script(control: FakeControl, script: str) -> str:
    """Model what the page does with an injected script.

    The verify script only reads the control back. The write script assigns
    through the native setter, which is how a value React swallowed is repaired.
    """
    reviewed_value = json.loads(_REVIEWED_VALUE.search(script).group(1))

    if VERIFY_SCRIPT_MARKER in script:
        matched = control.value == reviewed_value
        return json.dumps(
            {
                "ok": matched,
                "action": "verify",
                "field_type": "text",
                "verified": True,
                "value_matched": matched,
                "message": "field value applied" if matched else "the field did not keep the typed value",
            }
        )

    assert WRITE_SCRIPT_MARKER in script, "an injected field script is neither a write nor a read-back"
    if control.write_script_error is not None:
        raise control.write_script_error
    control.native_writes += 1
    control.value = reviewed_value
    return json.dumps(
        {
            "ok": True,
            "action": "set_value",
            "field_type": "text",
            "verified": True,
            "value_matched": True,
            "message": "field value applied",
        }
    )


# ---------------------------------------------------------------------------
# nodriver doubles
# ---------------------------------------------------------------------------


class FakeNodriverElement:
    def __init__(self, control: FakeControl) -> None:
        self._control = control

    async def clear_input(self) -> None:
        self._control.do_clear()

    async def send_keys(self, value: str) -> None:
        self._control.do_type(value)


class FakeNodriverPage:
    def __init__(self, control: FakeControl) -> None:
        self._control = control
        self.evaluated_scripts: list[str] = []

    async def select(self, selector: str) -> FakeNodriverElement:
        return FakeNodriverElement(self._control)

    async def evaluate(self, script: str) -> str:
        self.evaluated_scripts.append(script)
        return evaluate_script(self._control, script)


# ---------------------------------------------------------------------------
# playwright doubles
# ---------------------------------------------------------------------------


class FakePlaywrightLocator:
    def __init__(self, control: FakeControl) -> None:
        self._control = control

    async def fill(self, value: str, timeout: int | None = None) -> None:
        # Playwright's fill() clears the control before typing; model that.
        self._control.do_clear()
        self._control.do_type(value)


class FakePlaywrightFrame:
    """Playwright addresses every document through a frame, including the top one.

    The adapter now does the same, so modelling the top document as a frame keeps
    these single-document cases honest and leaves room for an embedded form.
    """

    def __init__(self, control: FakeControl, url: str, evaluated_scripts: list[str]) -> None:
        self._control = control
        self.url = url
        self._evaluated_scripts = evaluated_scripts

    def locator(self, selector: str) -> FakePlaywrightLocator:
        return FakePlaywrightLocator(self._control)

    async def evaluate(self, script: str) -> str:
        self._evaluated_scripts.append(script)
        return evaluate_script(self._control, script)


class FakePlaywrightPage:
    def __init__(self, control: FakeControl) -> None:
        self._control = control
        self.evaluated_scripts: list[str] = []
        self.main_frame = FakePlaywrightFrame(control, "https://portal.example/apply", self.evaluated_scripts)
        self.frames = [self.main_frame]

    def locator(self, selector: str) -> FakePlaywrightLocator:
        return FakePlaywrightLocator(self._control)

    async def evaluate(self, script: str) -> str:
        self.evaluated_scripts.append(script)
        return evaluate_script(self._control, script)


# ---------------------------------------------------------------------------
# seleniumbase doubles
# ---------------------------------------------------------------------------


class FakeSeleniumElement:
    def __init__(self, control: FakeControl) -> None:
        self._control = control

    def clear(self) -> None:
        self._control.do_clear()

    def send_keys(self, value: str) -> None:
        self._control.do_type(value)


class FakeSeleniumDriver:
    def __init__(self, control: FakeControl) -> None:
        self._control = control
        self.evaluated_scripts: list[str] = []

    def find_element(self, by: str, selector: str) -> FakeSeleniumElement:
        return FakeSeleniumElement(self._control)

    def execute_script(self, script: str) -> str:
        # SeleniumBase wraps the expression in `return (...)`; unwrap so the
        # double sees the same script the other two engines receive.
        inner = script[len("return (") : -1] if script.startswith("return (") else script
        self.evaluated_scripts.append(inner)
        return evaluate_script(self._control, inner)


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


class AdapterHarness:
    def __init__(self, name: str, adapter: object, control: FakeControl, surface: object) -> None:
        self.name = name
        self.adapter = adapter
        self.control = control
        self.surface = surface

    @property
    def evaluated_scripts(self) -> list[str]:
        return self.surface.evaluated_scripts  # type: ignore[attr-defined]


def build_nodriver(prefilled: str) -> AdapterHarness:
    control = FakeControl(prefilled)
    page = FakeNodriverPage(control)
    adapter = NodriverBrowserAdapter()
    adapter._page = page
    return AdapterHarness("nodriver", adapter, control, page)


def build_playwright(prefilled: str) -> AdapterHarness:
    control = FakeControl(prefilled)
    page = FakePlaywrightPage(control)
    adapter = PlaywrightBrowserAdapter()
    adapter._page = page
    return AdapterHarness("playwright", adapter, control, page)


def build_seleniumbase(prefilled: str) -> AdapterHarness:
    control = FakeControl(prefilled)
    driver = FakeSeleniumDriver(control)
    adapter = SeleniumBaseBrowserAdapter()
    adapter._driver = driver
    return AdapterHarness("seleniumbase", adapter, control, driver)


ADAPTER_BUILDERS: tuple[tuple[str, Callable[[str], AdapterHarness]], ...] = (
    ("nodriver", build_nodriver),
    ("playwright", build_playwright),
    ("seleniumbase", build_seleniumbase),
)


def make_field(
    field_type: str = "text",
    selector: str = "#name",
    metadata: dict[str, object] | None = None,
) -> BrowserField:
    return BrowserField(
        field_id="f1",
        label="Full name",
        field_type=field_type,
        selector=selector,
        required=True,
        confidence=1.0,
        metadata=metadata or {},
    )


# A field discovery reached by walking out of the evaluated document into a
# same-origin iframe or an open shadow root nested inside it.
NESTED = {"dom_path": [{"kind": "frame", "selector": "#inner", "index": 0}]}


# ---------------------------------------------------------------------------
# The contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("adapter_name,builder", ADAPTER_BUILDERS)
@pytest.mark.parametrize(
    "prefilled,new_value",
    [
        ("old", "new"),
        ("", "new"),
        ("John Smith", "John Smith"),
        ("alex@old.example.com", "alex@new.example.com"),
        ("   ", "Alex Rivera"),
    ],
)
def test_fill_field_replaces_existing_contents(
    adapter_name: str,
    builder: Callable[[str], AdapterHarness],
    prefilled: str,
    new_value: str,
) -> None:
    harness = builder(prefilled)
    result: BrowserStepResult = asyncio.run(harness.adapter.fill_field(make_field(), new_value))

    assert result.ok is True, f"{adapter_name}: {result.message}"
    assert harness.control.value == new_value, f"{adapter_name} appended instead of replacing"
    assert harness.control.clear_calls == 1, f"{adapter_name} did not clear before typing"


@pytest.mark.parametrize("adapter_name,builder", ADAPTER_BUILDERS)
@pytest.mark.parametrize("field_type", ["text", "email", "tel", "textarea", "url"])
def test_apply_field_value_routes_text_like_types_through_replace(
    adapter_name: str,
    builder: Callable[[str], AdapterHarness],
    field_type: str,
) -> None:
    """A field that takes the text a person wrote goes through fill_field, which must replace.

    ``date`` and ``number`` used to be on this list and are deliberately not any
    more: neither accepts prose through keystrokes, so they moved to the scripted
    write that coerces first. ``tel`` stays, because a phone field does take free
    text. The companion test below parametrizes off ``SCRIPTED_WRITE_FIELD_TYPES``,
    so a type can never be absent from both lists.
    """
    harness = builder("prefilled-by-portal")
    result = asyncio.run(harness.adapter.apply_field_value(make_field(field_type=field_type), "typed"))

    assert result.ok is True, f"{adapter_name}: {result.message}"
    assert harness.control.value == "typed"
    assert harness.control.native_writes == 0, f"{adapter_name} used the JS set-value path for a text field"
    assert len(harness.evaluated_scripts) == 1, f"{adapter_name} did not read the typed value back"
    assert VERIFY_SCRIPT_MARKER in harness.evaluated_scripts[0]


@pytest.mark.parametrize("adapter_name,builder", ADAPTER_BUILDERS)
def test_apply_field_value_repairs_a_write_the_page_discarded(
    adapter_name: str,
    builder: Callable[[str], AdapterHarness],
) -> None:
    """A React input that swallows the keystrokes must not be reported as filled."""
    harness = builder("")
    harness.control.discards_typing = True

    result = asyncio.run(harness.adapter.apply_field_value(make_field(), "Alex Rivera"))

    assert result.ok is True, f"{adapter_name}: {result.message}"
    assert harness.control.value == "Alex Rivera", f"{adapter_name} left the field empty"
    assert harness.control.native_writes == 1, f"{adapter_name} never repaired through the native setter"
    assert result.payload.get("repaired_after_typing") is True


@pytest.mark.parametrize("adapter_name,builder", ADAPTER_BUILDERS)
def test_apply_field_value_reports_failure_when_the_repair_also_fails(
    adapter_name: str,
    builder: Callable[[str], AdapterHarness],
) -> None:
    """The run must reach the approval gate knowing the field is still empty."""
    harness = builder("")
    harness.control.discards_typing = True
    harness.control.write_script_error = RuntimeError("the element is managed and refuses assignment")

    result = asyncio.run(harness.adapter.apply_field_value(make_field(), "Alex Rivera"))

    assert result.ok is False, f"{adapter_name} reported a field it never filled as filled"
    assert harness.control.value == "", f"{adapter_name} claims a value the page never accepted"


@pytest.mark.parametrize("adapter_name,builder", ADAPTER_BUILDERS)
@pytest.mark.parametrize("field_type", sorted(SCRIPTED_WRITE_FIELD_TYPES))
def test_apply_field_value_routes_non_text_types_through_the_dom_script(
    adapter_name: str,
    builder: Callable[[str], AdapterHarness],
    field_type: str,
) -> None:
    """A choice control must not be typed into; it goes through the DOM script.

    Parametrized off the constant rather than a hand-written list, so a field type
    added to ``SCRIPTED_WRITE_FIELD_TYPES`` without a matching adapter route fails
    here instead of in a portal. That drift is exactly how the ARIA types shipped
    discoverable but unroutable: an ``<input role="combobox">`` has a ``value``
    property, so ``fill()`` writes into it and reads the same text back as proof,
    and the run reports a success the portal never saw.
    """
    harness = builder("Yes")
    result = asyncio.run(harness.adapter.apply_field_value(make_field(field_type=field_type), "No"))

    assert result.ok is True, f"{adapter_name}: {result.message}"
    assert harness.control.type_calls == 0, f"{adapter_name} typed into a {field_type}"
    assert len(harness.evaluated_scripts) == 1, f"{adapter_name} skipped the DOM apply script"


@pytest.mark.parametrize("adapter_name,builder", ADAPTER_BUILDERS)
@pytest.mark.parametrize("field_type", ["text", "email", "tel", "url", "textarea"])
def test_a_field_the_driver_cannot_reach_is_written_by_script_not_by_keystroke(
    adapter_name: str, builder: Callable[[str], AdapterHarness], field_type: str
) -> None:
    """Text-like types normally get real keystrokes; a nested field cannot.

    ``select``, ``locator`` and ``find_element`` all resolve from a document root
    and stop at an iframe or a shadow boundary. For a field below that boundary the
    lookup returns either nothing, and a required answer is silently lost, or the
    same-named control in the *parent*, which the keystroke path would then clear
    and type the user's answer into. An employer page wrapping an ATS embed while
    keeping its own ``#email`` newsletter box is an entirely ordinary shape, and it
    is the one where the damage is invisible.

    So these fields take the scripted write, which replays the path first. Losing a
    little stealth on them beats writing to a form nobody chose.
    """
    harness = builder("")
    field = make_field(field_type, metadata=dict(NESTED))

    result = asyncio.run(harness.adapter.apply_field_value(field, "Alex Rivera"))

    assert result.ok is True, result.message
    assert harness.control.type_calls == 0, f"{adapter_name} typed into an element it cannot address"
    assert harness.control.clear_calls == 0, f"{adapter_name} cleared an element it cannot address"
    assert harness.control.native_writes == 1
    assert harness.control.value == "Alex Rivera"


@pytest.mark.parametrize("adapter_name,builder", ADAPTER_BUILDERS)
def test_filling_a_field_the_driver_cannot_reach_refuses(
    adapter_name: str, builder: Callable[[str], AdapterHarness]
) -> None:
    """``fill_field`` is public, and the runner reaches it on the repair path too."""
    harness = builder("")

    result = asyncio.run(harness.adapter.fill_field(make_field(metadata=dict(NESTED)), "Alex Rivera"))

    assert result.ok is False
    assert "the driver cannot address" in result.message
    assert harness.control.type_calls == 0


@pytest.mark.parametrize("adapter_name,builder", ADAPTER_BUILDERS)
def test_fill_field_fails_loudly_when_the_control_cannot_be_cleared(
    adapter_name: str,
    builder: Callable[[str], AdapterHarness],
) -> None:
    """A failed clear must not silently degrade into an appending write."""
    harness = builder("prefilled")
    harness.control.clear_error = RuntimeError("element is read-only")

    result = asyncio.run(harness.adapter.fill_field(make_field(), "new"))

    assert result.ok is False, f"{adapter_name} reported success despite failing to clear"
    assert harness.control.value == "prefilled", f"{adapter_name} corrupted the field after a failed clear"
