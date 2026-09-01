"""Typing a value into a text field, then proving it stayed there.

Every adapter fills text fields natively: Playwright's `fill`, nodriver's
`send_keys`, SeleniumBase's `clear` plus `send_keys`. That is the right
mechanism, because it fires the key events autocomplete widgets listen for. It
is also unverified. All three then return a hardcoded success, so a React input
that quietly discarded the keystrokes was reported to the user as filled, and
the run walked to the submit gate with an empty required field.

This adds the missing half: read the value back, and repair through the
React-safe native setter only when it genuinely did not land.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from .adapter import BrowserField, BrowserStepResult
from .field_detection import (
    build_apply_field_value_script,
    build_verify_field_value_script,
    dom_path_for,
    parse_apply_field_result,
)

EvaluateScript = Callable[[str], Awaitable[Any]]


async def verify_or_repair_text_write(
    evaluate: EvaluateScript,
    field: BrowserField,
    value: str,
    *,
    fill_payload: dict[str, Any],
) -> BrowserStepResult:
    """Confirm a typed value survived, repairing it once if it did not."""
    if not field.selector:
        return BrowserStepResult(True, "field value applied", {**fill_payload, "verified": False})

    try:
        raw_verdict = await evaluate(
            build_verify_field_value_script(field.selector, value, dom_path_for(field))
        )
    except Exception as exc:
        # A page that refuses script evaluation is not evidence the write failed,
        # so the typed value stands and the payload says it went unchecked.
        return BrowserStepResult(
            True,
            "field value applied",
            {**fill_payload, "verified": False, "verification_error": str(exc)[:200]},
        )

    verified = parse_apply_field_result(raw_verdict, field)
    if verified.ok:
        return BrowserStepResult(True, "field value applied", {**fill_payload, **verified.payload})

    try:
        raw_repair = await evaluate(
            build_apply_field_value_script(field.selector, value, dom_path_for(field))
        )
    except Exception as exc:
        return BrowserStepResult(
            False,
            "the field did not keep the typed value",
            {**fill_payload, **verified.payload, "repair_error": str(exc)[:200]},
        )

    repaired = parse_apply_field_result(raw_repair, field)
    return BrowserStepResult(
        repaired.ok,
        repaired.message,
        {**fill_payload, **repaired.payload, "repaired_after_typing": True},
    )
