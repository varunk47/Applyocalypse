from __future__ import annotations

import os

from .answers import ProposedApplicationAnswer, propose_answer_for_detected_field
from .browser.adapter import BrowserField
from .secret_env import get_secret

APPLICATION_PASSWORD_SENTINEL = "Use stored application password"

OTP_FIELD_HINTS = (
    "otp",
    "one-time code",
    "one time code",
    "verification code",
    "security code",
    "passcode",
)


def normalize_field_label(value: str) -> str:
    return " ".join("".join(character.lower() if character.isalnum() else " " for character in value).split())


def is_password_field(field: BrowserField) -> bool:
    label = normalize_field_label(field.label)
    return field.field_type == "password" or "password" in label


def is_otp_field(field: BrowserField) -> bool:
    label = normalize_field_label(field.label)
    return any(hint in label for hint in OTP_FIELD_HINTS)


def proposed_answer_for_browser_field(field: BrowserField, canonical_profile: dict[str, object]) -> ProposedApplicationAnswer:
    if is_password_field(field) and get_secret("APPLYO_APPLICATION_PASSWORD"):
        return ProposedApplicationAnswer(
            field_label=field.label,
            field_type=field.field_type,
            proposed_value=APPLICATION_PASSWORD_SENTINEL,
            confidence=0.84,
            source="PROFILE",
            requires_review=True,
        )
    return propose_answer_for_detected_field(
        field_label=field.label,
        field_type=field.field_type,
        canonical_profile=canonical_profile,
        autofill_approved_defaults=os.getenv("APPLYO_AUTOFILL_APPROVED_DEFAULTS") == "1",
    )


def resolve_secret_reviewed_value(field: BrowserField, reviewed_value: str | None) -> tuple[str | None, str | None]:
    if reviewed_value == APPLICATION_PASSWORD_SENTINEL and is_password_field(field):
        password = get_secret("APPLYO_APPLICATION_PASSWORD")
        return (password if password else None, "APPLICATION_PASSWORD_SECRET")
    return reviewed_value, None
