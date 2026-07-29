"""A dropzone's file input is hidden by design and must still be discovered (audit row 15).

Greenhouse, Lever, Workable, Ashby and everything built on react-dropzone render a
real ``<input type="file">`` at zero size behind a styled drop target. The visibility
gate that keeps the ``display:none`` g-recaptcha-response textarea out was dropping
those too, and the failure was silent in the worst direction: no upload field means
nothing to upload to, so the run would reach the submit gate reporting a filled
application with no resume attached.

These execute the real injected script against the Node DOM stub. Asserting on the
text of the JS constant would prove nothing.
"""
from __future__ import annotations

import pytest
from js_bridge import run_browser_script

from applyocalypse_automation.browser.field_detection import DOM_FIELD_DISCOVERY_SCRIPT

HIDDEN_STYLES: tuple[tuple[str, dict], ...] = (
    ("zero_size", {"rect": {"width": 0, "height": 0}}),
    ("display_none", {"style": {"display": "none"}}),
    ("visibility_hidden", {"style": {"visibility": "hidden"}}),
)


def _discover(*elements: dict) -> list[dict]:
    outcome = run_browser_script(DOM_FIELD_DISCOVERY_SCRIPT, {"elements": [{"tag": "form", "children": list(elements)}]})
    return outcome["result"]


def _by_id(fields: list[dict], element_id: str) -> dict | None:
    for field in fields:
        if field["metadata"].get("id") == element_id:
            return field
    return None


@pytest.mark.parametrize(("case", "hiding"), HIDDEN_STYLES, ids=[case for case, _ in HIDDEN_STYLES])
def test_a_dropzone_file_input_survives_the_visibility_gate(case: str, hiding: dict) -> None:
    fields = _discover(
        {
            "tag": "input",
            "attrs": {"id": "resume", "name": "resume", "type": "file", "aria-label": "Resume"},
            "required": True,
            **hiding,
        }
    )

    resume = _by_id(fields, "resume")
    assert resume is not None, f"the {case} resume input was dropped; got {[f['label'] for f in fields]}"
    assert resume["field_type"] == "file"
    assert resume["required"] is True
    assert resume["metadata"]["visually_hidden"] is True


def test_a_visible_file_input_is_not_marked_hidden() -> None:
    """The flag has to distinguish a dropzone from an on-screen picker to be worth anything."""
    fields = _discover(
        {"tag": "input", "attrs": {"id": "resume", "name": "resume", "type": "file", "aria-label": "Resume"}}
    )

    resume = _by_id(fields, "resume")
    assert resume is not None
    assert resume["metadata"]["visually_hidden"] is False


def test_a_disabled_hidden_file_input_is_still_dropped() -> None:
    """Nothing can write to it, so surfacing it would only invent a field to pause on."""
    fields = _discover(
        {
            "tag": "input",
            "attrs": {"id": "resume", "name": "resume", "type": "file", "aria-label": "Resume"},
            "style": {"display": "none"},
            "disabled": True,
        }
    )

    assert _by_id(fields, "resume") is None


@pytest.mark.parametrize(("case", "hiding"), HIDDEN_STYLES, ids=[case for case, _ in HIDDEN_STYLES])
def test_the_gate_did_not_open_for_everything_else(case: str, hiding: dict) -> None:
    """Only file inputs are exempt. A hidden text field is still a collapsed field."""
    fields = _discover(
        {
            "tag": "input",
            "attrs": {"id": "conditional", "name": "conditional", "aria-label": "Visa expiry"},
            **hiding,
        }
    )

    assert _by_id(fields, "conditional") is None


def test_the_recaptcha_textarea_is_still_excluded() -> None:
    """The exclusion this gate was originally written for must survive the exemption."""
    fields = _discover(
        {
            "tag": "textarea",
            "attrs": {"id": "g-recaptcha-response", "name": "g-recaptcha-response"},
            "style": {"display": "none"},
        }
    )

    assert fields == []


def test_a_hidden_file_input_named_like_a_challenge_is_still_excluded() -> None:
    """The file exemption must not become a hole in the bot-challenge filter."""
    fields = _discover(
        {
            "tag": "input",
            "attrs": {"id": "captcha-upload", "name": "captcha-upload", "type": "file"},
            "style": {"display": "none"},
        }
    )

    assert fields == []
