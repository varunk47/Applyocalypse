from __future__ import annotations

import asyncio
import random
from typing import Any

import pytest

from applyocalypse_automation.browser.human_typing import (
    BULK_INSERT_THRESHOLD,
    CTRL_MODIFIER,
    MAX_KEYSTROKE_DELAY_S,
    MIN_KEYSTROKE_DELAY_S,
    SHIFT_MODIFIER,
    clear_element,
    key_events_for_char,
    key_events_for_text,
    keystroke_delay,
    should_bulk_insert,
    type_into_element,
)


class _RecordingInputDomain:
    """Stands in for ``nodriver.cdp.input_``, recording the calls it is handed."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def dispatch_key_event(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("dispatch_key_event", kwargs))
        return kwargs

    def insert_text(self, text: str) -> dict[str, Any]:
        self.calls.append(("insert_text", {"text": text}))
        return {"text": text}


class _FakeTab:
    def __init__(self) -> None:
        self.sent: list[Any] = []

    async def send(self, command: Any) -> None:
        self.sent.append(command)


class _FakeElement:
    def __init__(self) -> None:
        self.tab = _FakeTab()
        self.focus_calls = 0

    async def focus(self) -> None:
        self.focus_calls += 1


async def _no_sleep(_seconds: float) -> None:
    return None


@pytest.mark.parametrize(
    ("char", "expected_code", "expected_virtual_key", "expected_modifiers"),
    [
        ("a", "KeyA", 65, 0),
        ("z", "KeyZ", 90, 0),
        ("A", "KeyA", 65, SHIFT_MODIFIER),
        ("5", "Digit5", 53, 0),
        ("%", "Digit5", 53, SHIFT_MODIFIER),
        ("@", "Digit2", 50, SHIFT_MODIFIER),
        (".", "Period", 190, 0),
        (">", "Period", 190, SHIFT_MODIFIER),
        ("-", "Minus", 189, 0),
        ("_", "Minus", 189, SHIFT_MODIFIER),
        ("/", "Slash", 191, 0),
        (" ", "Space", 32, 0),
        ("\n", "Enter", 13, 0),
        ("\t", "Tab", 9, 0),
    ],
)
def test_each_character_maps_to_its_physical_key(
    char: str, expected_code: str, expected_virtual_key: int, expected_modifiers: int
) -> None:
    down, up = key_events_for_char(char)

    assert (down.type_, up.type_) == ("keyDown", "keyUp")
    assert down.code == up.code == expected_code
    assert down.windows_virtual_key_code == up.windows_virtual_key_code == expected_virtual_key
    assert down.modifiers == expected_modifiers


def test_a_character_outside_the_us_layout_is_still_typed() -> None:
    """An accented name must not be dropped just because it has no physical key."""
    down, up = key_events_for_char("é"[0])
    accented_down, _ = key_events_for_char("é")

    assert down.type_ == "keyDown" and up.type_ == "keyUp"
    assert accented_down.text == "é"
    assert accented_down.code == ""
    assert accented_down.windows_virtual_key_code == 0


def test_every_keystroke_carries_a_keydown_and_a_keyup() -> None:
    """The regression this module exists for.

    nodriver's send_keys dispatched a single CDP ``char`` event per character and
    nothing else, so no ``keydown`` ever reached the page. Every typeahead on
    Workday, Ashby and iCIMS opens its listbox from an onKeyDown handler, which
    means the dropdown never opened and the answer was never committed.
    """
    events = key_events_for_text("Ab1")

    assert [event.type_ for event in events] == [
        "keyDown",
        "keyUp",
        "keyDown",
        "keyUp",
        "keyDown",
        "keyUp",
    ]
    assert [event.text for event in events if event.type_ == "keyDown"] == ["A", "b", "1"]
    # keyUp carries no text: CDP would otherwise insert the character twice.
    assert all(event.text is None for event in events if event.type_ == "keyUp")


def test_cdp_kwargs_name_every_field_chrome_needs() -> None:
    down, up = key_events_for_char("A")

    assert down.as_cdp_kwargs() == {
        "type_": "keyDown",
        "key": "A",
        "code": "KeyA",
        "windows_virtual_key_code": 65,
        "native_virtual_key_code": 65,
        "modifiers": SHIFT_MODIFIER,
        "text": "A",
        "unmodified_text": "A",
    }
    assert "text" not in up.as_cdp_kwargs()


@pytest.mark.parametrize("seed", list(range(25)))
def test_keystroke_delay_stays_inside_its_clamp(seed: int) -> None:
    """The tail of a log-normal is unbounded; a run must not stall on one field."""
    generator = random.Random(seed)

    for previous in (None, "a", " "):
        delay = keystroke_delay(previous, generator)
        assert MIN_KEYSTROKE_DELAY_S <= delay <= MAX_KEYSTROKE_DELAY_S


def test_keystroke_delays_are_not_all_identical() -> None:
    """A uniform inter-key interval is both a detection signal and unrealistic."""
    generator = random.Random(7)
    delays = {keystroke_delay(None, generator) for _ in range(50)}

    assert len(delays) > 40


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Senior Software Engineer", False),
        ("a" * BULK_INSERT_THRESHOLD, False),
        ("a" * (BULK_INSERT_THRESHOLD + 1), True),
    ],
)
def test_prose_is_inserted_and_lookup_terms_are_typed(value: str, expected: bool) -> None:
    assert should_bulk_insert(value) is expected


def test_typing_a_short_value_emits_real_keystrokes() -> None:
    element = _FakeElement()
    input_domain = _RecordingInputDomain()

    strategy = asyncio.run(
        type_into_element(element, "ab", cdp_input=input_domain, rng=random.Random(1), sleep=_no_sleep)
    )

    assert strategy == "keystrokes"
    assert element.focus_calls == 1
    assert [name for name, _ in input_domain.calls] == ["dispatch_key_event"] * 4
    assert [payload["type_"] for _, payload in input_domain.calls] == [
        "keyDown",
        "keyUp",
        "keyDown",
        "keyUp",
    ]
    assert len(element.tab.sent) == 4


def test_a_cover_letter_is_inserted_in_one_call() -> None:
    """Typing prose key by key would spend a minute on a single textarea."""
    element = _FakeElement()
    input_domain = _RecordingInputDomain()
    letter = "I would be glad to join the team. " * 10

    strategy = asyncio.run(type_into_element(element, letter, cdp_input=input_domain, sleep=_no_sleep))

    assert strategy == "insert_text"
    assert input_domain.calls == [("insert_text", {"text": letter})]


def test_clearing_a_field_selects_all_then_deletes() -> None:
    """A trusted edit, so the framework's value tracker sees the reset."""
    element = _FakeElement()
    input_domain = _RecordingInputDomain()

    asyncio.run(clear_element(element, cdp_input=input_domain, sleep=_no_sleep))

    payloads = [payload for _, payload in input_domain.calls]
    assert [payload["type_"] for payload in payloads] == ["keyDown", "keyUp", "keyDown", "keyUp"]
    assert payloads[0]["commands"] == ["selectAll"]
    assert payloads[0]["modifiers"] == CTRL_MODIFIER
    assert payloads[2]["key"] == "Delete"


def test_keystrokes_are_sent_to_the_frame_that_owns_the_field() -> None:
    """A field inside a cross-origin apply frame must not receive them elsewhere."""
    element = _FakeElement()
    input_domain = _RecordingInputDomain()

    asyncio.run(type_into_element(element, "hi", cdp_input=input_domain, sleep=_no_sleep))

    assert len(element.tab.sent) == 4
