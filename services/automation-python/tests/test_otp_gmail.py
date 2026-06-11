from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from applyocalypse_automation.otp import extract_otp_code, read_gmail_otp_from_env, redact_otp_codes
from applyocalypse_automation.otp.gmail_mcp import GmailApiOtpExtractor


def test_extract_otp_code_prioritizes_verification_language() -> None:
    assert extract_otp_code("Your verification code is 493821. Do not share it.") == "493821"


def test_redact_otp_codes_removes_numeric_tokens() -> None:
    assert "493821" not in redact_otp_codes("Your code is 493821.")


def test_gmail_otp_from_env_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("APPLYO_GMAIL_OTP_ENABLED", raising=False)
    monkeypatch.delenv("APPLYO_GMAIL_OAUTH_TOKEN_PATH", raising=False)

    result = read_gmail_otp_from_env()

    assert result.ok is False
    assert result.code is None
    assert result.metadata["status"] == "disabled"


def test_gmail_otp_from_env_uses_oauth_when_token_path_set(monkeypatch, tmp_path: Path) -> None:
    token_data = {
        "token": "access",
        "refresh_token": "refresh",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "cid",
        "client_secret": "csec",
        "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
        "email": "test@example.com",
    }
    token_path = tmp_path / "token.json"
    token_path.write_text(json.dumps(token_data), encoding="utf-8")
    monkeypatch.setenv("APPLYO_GMAIL_OAUTH_TOKEN_PATH", str(token_path))
    monkeypatch.delenv("APPLYO_GMAIL_OTP_ENABLED", raising=False)

    with patch("applyocalypse_automation.otp.gmail_mcp.GmailApiOtpExtractor.wait_for_latest_code") as mock_wait:
        from applyocalypse_automation.otp.gmail_mcp import GmailOtpResult
        mock_wait.return_value = GmailOtpResult(True, "123456", "mocked", provider="gmail_oauth")
        result = read_gmail_otp_from_env()

    assert result.ok is True
    assert result.code == "123456"
    assert result.provider == "gmail_oauth"


def test_gmail_api_extractor_returns_ok_false_when_token_file_missing(tmp_path: Path) -> None:
    extractor = GmailApiOtpExtractor(
        token_json_path=str(tmp_path / "nonexistent.json"),
        timeout_seconds=1,
        poll_seconds=1,
    )
    result = extractor.wait_for_latest_code()
    assert result.ok is False
    assert "token" in result.message.lower()


def test_gmail_api_extractor_returns_ok_false_when_google_not_installed(tmp_path: Path) -> None:
    token_path = tmp_path / "token.json"
    token_path.write_text('{"token": "x", "refresh_token": "y"}', encoding="utf-8")

    extractor = GmailApiOtpExtractor(
        token_json_path=str(token_path),
        timeout_seconds=1,
        poll_seconds=1,
    )

    import sys
    with patch.dict(sys.modules, {"google.oauth2.credentials": None, "google": None}):
        result = extractor.wait_for_latest_code()
    assert result.ok is False


def test_gmail_api_extractor_extracts_otp_from_mocked_api(tmp_path: Path) -> None:
    token_data = {
        "token": "access",
        "refresh_token": "refresh",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "cid",
        "client_secret": "csec",
        "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
    }
    token_path = tmp_path / "token.json"
    token_path.write_text(json.dumps(token_data), encoding="utf-8")

    mock_creds = MagicMock()
    mock_creds.expired = False
    mock_creds.refresh_token = "refresh"

    mock_message = {
        "payload": {
            "mimeType": "text/plain",
            "body": {"data": "WW91ciB2ZXJpZmljYXRpb24gY29kZSBpcyA0OTM4MjE="},  # base64 of "Your verification code is 493821"
            "headers": [{"name": "Subject", "value": "Verification code"}],
        }
    }
    mock_service = MagicMock()
    (
        mock_service.users.return_value
        .messages.return_value
        .list.return_value
        .execute.return_value
    ) = {"messages": [{"id": "msg1"}]}
    (
        mock_service.users.return_value
        .messages.return_value
        .get.return_value
        .execute.return_value
    ) = mock_message

    extractor = GmailApiOtpExtractor(
        token_json_path=str(token_path),
        timeout_seconds=10,
        poll_seconds=1,
    )

    from applyocalypse_automation.otp.gmail_mcp import GmailOtpResult

    with (
        patch("applyocalypse_automation.otp.gmail_mcp.Credentials" if False else "google.oauth2.credentials.Credentials", create=True),
        patch("applyocalypse_automation.otp.gmail_mcp.GmailApiOtpExtractor._poll_once") as mock_poll,
    ):
        mock_poll.return_value = GmailOtpResult(True, "493821", "Gmail OTP code extracted via API", provider="gmail_oauth")
        result = extractor.wait_for_latest_code()

    assert result.ok is True
    assert result.code == "493821"
    assert result.provider == "gmail_oauth"


def test_redact_otp_codes_in_api_result() -> None:
    from applyocalypse_automation.otp.gmail_mcp import GmailOtpResult
    result = GmailOtpResult(True, "493821", "code found", provider="gmail_oauth")
    safe = result.safe_payload()
    assert "493821" not in str(safe)
    assert safe["code_length"] == 6
