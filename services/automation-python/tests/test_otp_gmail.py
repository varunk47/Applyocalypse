from __future__ import annotations

from applyocalypse_automation.otp import extract_otp_code, read_gmail_otp_from_env, redact_otp_codes


def test_extract_otp_code_prioritizes_verification_language() -> None:
    assert extract_otp_code("Your verification code is 493821. Do not share it.") == "493821"


def test_redact_otp_codes_removes_numeric_tokens() -> None:
    assert "493821" not in redact_otp_codes("Your code is 493821.")


def test_gmail_otp_from_env_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("APPLYO_GMAIL_OTP_ENABLED", raising=False)

    result = read_gmail_otp_from_env()

    assert result.ok is False
    assert result.code is None
    assert result.metadata["status"] == "disabled"
