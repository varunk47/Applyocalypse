"""Keystrokes that produce the events portal widgets actually listen for.

nodriver's ``Element.send_keys`` dispatches one CDP ``char`` event per character
with no delay between them (nodriver 0.50.3, ``core/element.py:708``). Chrome
turns a ``char`` event into the text insertion and the ``input`` event that
follows it, but it never synthesises ``keydown`` or ``keyup``. That gap is the
difference between a value appearing in a plain text box and a typeahead
actually working: Workday, Ashby, iCIMS and every react-select / downshift
combobox open their listbox from an ``onKeyDown`` handler, so a char-only stream
types into a control whose dropdown never opens and whose answer is therefore
never committed. The field looks filled and the application is missing it.

Emitting ``keyDown`` (carrying the text) then ``keyUp`` per character is what
Puppeteer and Playwright both do. It produces the whole
``keydown -> beforeinput -> input -> keyup`` chain from below the JS layer, so
every event carries ``isTrusted: true``.

Long prose does not get typed. Nothing runs a typeahead on a cover letter, and
character-by-character emission would spend a minute on one textarea, so values
past ``BULK_INSERT_THRESHOLD`` go through a single ``Input.insertText``, which is
still a trusted, below-JS insertion that fires ``beforeinput`` and ``input``.

The gap between keys is drawn from a log-normal distribution rather than being a
constant. The first reason is functional: portals debounce their typeahead
queries, commonly 150-300ms, and a zero-delay burst collapses into one query
fired against a half-written prefix. The second is that a perfectly uniform
inter-key interval is a behavioural signal in its own right.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

# Bit field CDP uses for pressed modifiers.
SHIFT_MODIFIER = 8
CTRL_MODIFIER = 2

# Past this length a value is prose, not a lookup term, so it is inserted in one
# call instead of typed. 120 characters is comfortably longer than any job title,
# employer, school, city or degree that a typeahead would want to match on.
BULK_INSERT_THRESHOLD = 120

# Log-normal parameters for the gap between keystrokes, in seconds. The median
# sits at e**MU, and the clamp keeps the tail from stalling a run on one field.
KEYSTROKE_DELAY_MU = -3.10
KEYSTROKE_DELAY_SIGMA = 0.45
MIN_KEYSTROKE_DELAY_S = 0.012
MAX_KEYSTROKE_DELAY_S = 0.40
# Humans rest fractionally longer at a word boundary than mid-word.
WORD_BOUNDARY_DELAY_FACTOR = 1.6


@dataclass(frozen=True)
class KeyEvent:
    """One CDP ``Input.dispatchKeyEvent`` call, as keyword arguments."""

    type_: str
    key: str
    code: str
    windows_virtual_key_code: int
    text: str | None = None
    modifiers: int = 0
    commands: tuple[str, ...] = field(default_factory=tuple)

    def as_cdp_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "type_": self.type_,
            "key": self.key,
            "code": self.code,
            "windows_virtual_key_code": self.windows_virtual_key_code,
            "native_virtual_key_code": self.windows_virtual_key_code,
        }
        if self.modifiers:
            kwargs["modifiers"] = self.modifiers
        if self.text is not None:
            kwargs["text"] = self.text
            kwargs["unmodified_text"] = self.text
        if self.commands:
            kwargs["commands"] = list(self.commands)
        return kwargs


def _build_key_descriptors() -> dict[str, tuple[str, int, bool]]:
    """char -> (DOM code, Windows virtual key code, needs shift), US layout."""
    descriptors: dict[str, tuple[str, int, bool]] = {}
    for letter in "abcdefghijklmnopqrstuvwxyz":
        descriptors[letter] = (f"Key{letter.upper()}", ord(letter.upper()), False)
        descriptors[letter.upper()] = (f"Key{letter.upper()}", ord(letter.upper()), True)
    for digit in "0123456789":
        descriptors[digit] = (f"Digit{digit}", ord(digit), False)
    for shifted, digit in zip("!@#$%^&*()", "1234567890", strict=True):
        descriptors[shifted] = (f"Digit{digit}", ord(digit), True)
    punctuation = {
        "`": ("Backquote", 192),
        "~": ("Backquote", 192),
        "-": ("Minus", 189),
        "_": ("Minus", 189),
        "=": ("Equal", 187),
        "+": ("Equal", 187),
        "[": ("BracketLeft", 219),
        "{": ("BracketLeft", 219),
        "]": ("BracketRight", 221),
        "}": ("BracketRight", 221),
        "\\": ("Backslash", 220),
        "|": ("Backslash", 220),
        ";": ("Semicolon", 186),
        ":": ("Semicolon", 186),
        "'": ("Quote", 222),
        '"': ("Quote", 222),
        ",": ("Comma", 188),
        "<": ("Comma", 188),
        ".": ("Period", 190),
        ">": ("Period", 190),
        "/": ("Slash", 191),
        "?": ("Slash", 191),
    }
    shifted_punctuation = set('~_+{}|:"<>?')
    for char, (code, virtual_key) in punctuation.items():
        descriptors[char] = (code, virtual_key, char in shifted_punctuation)
    descriptors[" "] = ("Space", 32, False)
    return descriptors


KEY_DESCRIPTORS = _build_key_descriptors()

# Characters that carry a name rather than themselves. \r and \n are folded onto
# Enter because a portal that submits on Enter must see the same event a person
# would produce, and because CDP wants \r as Enter's text.
NAMED_KEYS: dict[str, tuple[str, str, int, str | None]] = {
    "\n": ("Enter", "Enter", 13, "\r"),
    "\r": ("Enter", "Enter", 13, "\r"),
    "\t": ("Tab", "Tab", 9, "\t"),
}


def key_events_for_char(char: str) -> tuple[KeyEvent, ...]:
    """The keyDown/keyUp pair for one character.

    A character outside the US-layout table (an accented name, CJK, an emoji) is
    still typed rather than skipped: it keeps ``text`` so Chrome inserts it, and
    reports itself as its own ``key`` with no physical code. Handlers that read
    ``event.key`` see the right thing; the few that switch on ``keyCode`` see 0,
    which is what a real IME composition gives them anyway.
    """
    if char in NAMED_KEYS:
        key, code, virtual_key, text = NAMED_KEYS[char]
        return (
            KeyEvent("keyDown", key, code, virtual_key, text=text),
            KeyEvent("keyUp", key, code, virtual_key),
        )
    descriptor = KEY_DESCRIPTORS.get(char)
    if descriptor is None:
        return (
            KeyEvent("keyDown", char, "", 0, text=char),
            KeyEvent("keyUp", char, "", 0),
        )
    code, virtual_key, needs_shift = descriptor
    modifiers = SHIFT_MODIFIER if needs_shift else 0
    return (
        KeyEvent("keyDown", char, code, virtual_key, text=char, modifiers=modifiers),
        KeyEvent("keyUp", char, code, virtual_key, modifiers=modifiers),
    )


def key_events_for_text(text: str) -> tuple[KeyEvent, ...]:
    """Every keyDown/keyUp for a value, in order."""
    return tuple(event for char in text for event in key_events_for_char(char))


def keystroke_delay(previous_char: str | None, rng: random.Random) -> float:
    """Seconds to wait before the next key, drawn from a clamped log-normal."""
    delay = rng.lognormvariate(KEYSTROKE_DELAY_MU, KEYSTROKE_DELAY_SIGMA)
    if previous_char is not None and previous_char.isspace():
        delay *= WORD_BOUNDARY_DELAY_FACTOR
    return min(max(delay, MIN_KEYSTROKE_DELAY_S), MAX_KEYSTROKE_DELAY_S)


def should_bulk_insert(value: str) -> bool:
    """True when a value is prose and typing it key by key would only cost time."""
    return len(value) > BULK_INSERT_THRESHOLD


# Select-all then delete, as keystrokes. ``commands`` hands Chrome the editing
# command by name, which is how Puppeteer and Playwright reach selectAll without
# caring whether the platform modifier is Ctrl or Meta. This replaces a
# main-world ``element.value = ''``: the deletion is a real edit, so the
# ``input`` event it raises is trusted and every framework's value tracker sees
# the reset instead of silently keeping the old value.
CLEAR_FIELD_EVENTS: tuple[KeyEvent, ...] = (
    KeyEvent("keyDown", "a", "KeyA", 65, modifiers=CTRL_MODIFIER, commands=("selectAll",)),
    KeyEvent("keyUp", "a", "KeyA", 65, modifiers=CTRL_MODIFIER),
    KeyEvent("keyDown", "Delete", "Delete", 46),
    KeyEvent("keyUp", "Delete", "Delete", 46),
)


def _cdp_input_module(override: Any = None) -> Any:
    """The ``nodriver.cdp.input_`` module, imported only when a browser is live.

    Deferred for the same reason the adapter defers ``import nodriver``: the
    document pipeline runs in environments with no browser stack, and a
    top-level import would make importing this module fail there.
    """
    if override is not None:
        return override
    from nodriver import cdp  # type: ignore[import-not-found]

    return cdp.input_


async def clear_element(
    element: Any,
    *,
    cdp_input: Any = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Empty a control with keystrokes, so the clear is a trusted edit."""
    input_domain = _cdp_input_module(cdp_input)
    await element.focus()
    for event in CLEAR_FIELD_EVENTS:
        await element.tab.send(input_domain.dispatch_key_event(**event.as_cdp_kwargs()))
    await sleep(MIN_KEYSTROKE_DELAY_S)


async def type_into_element(
    element: Any,
    value: str,
    *,
    cdp_input: Any = None,
    rng: random.Random | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> str:
    """Type a value into a control. Returns which strategy was used.

    The element's own tab is the send target rather than the top document, so a
    field inside a cross-origin apply frame receives the keystrokes in the frame
    that owns it.
    """
    input_domain = _cdp_input_module(cdp_input)
    await element.focus()
    if should_bulk_insert(value):
        await element.tab.send(input_domain.insert_text(value))
        return "insert_text"
    generator = rng if rng is not None else random.Random()
    previous_char: str | None = None
    for char in value:
        for event in key_events_for_char(char):
            await element.tab.send(input_domain.dispatch_key_event(**event.as_cdp_kwargs()))
        await sleep(keystroke_delay(previous_char, generator))
        previous_char = char
    return "keystrokes"
