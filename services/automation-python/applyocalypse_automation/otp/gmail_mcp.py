from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from email import policy
from email.parser import BytesParser
import hashlib
import imaplib
import os
import re
import time
from typing import Any


OTP_PATTERN = re.compile(r"(?<!\d)(\d{4,8})(?!\d)")


@dataclass(frozen=True, slots=True)
class GmailOtpResult:
    ok: bool
    code: str | None
    message: str
    provider: str = "gmail"
    metadata: dict[str, Any] = field(default_factory=dict)

    def safe_payload(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "ok": self.ok,
            "code_length": len(self.code) if self.code else None,
            "metadata": self.metadata,
        }


def extract_otp_code(text: str) -> str | None:
    normalized = " ".join(text.split())
    priority_patterns = [
        re.compile(r"(?:code|otp|passcode|verification)[^\d]{0,40}(\d{4,8})", re.IGNORECASE),
        OTP_PATTERN,
    ]
    for pattern in priority_patterns:
        match = pattern.search(normalized)
        if match:
            return match.group(1)
    return None


def redact_otp_codes(text: str) -> str:
    return OTP_PATTERN.sub("[OTP_REDACTED]", text)


def _message_text(message: Any) -> str:
    parts: list[str] = []
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_maintype() == "multipart":
                continue
            if part.get_content_type() not in {"text/plain", "text/html"}:
                continue
            try:
                parts.append(str(part.get_content()))
            except Exception:
                continue
    else:
        try:
            parts.append(str(message.get_content()))
        except Exception:
            return ""
    return "\n".join(parts)


def _safe_message_metadata(message: Any) -> dict[str, Any]:
    message_id = str(message.get("Message-ID") or "")
    subject = str(message.get("Subject") or "")
    from_header = str(message.get("From") or "")
    date_header = str(message.get("Date") or "")
    return {
        "message_id_sha256": hashlib.sha256(message_id.encode("utf-8")).hexdigest() if message_id else None,
        "subject_sha256": hashlib.sha256(subject.encode("utf-8")).hexdigest() if subject else None,
        "from_domain": from_header.split("@")[-1].split(">")[0].strip().lower() if "@" in from_header else None,
        "date": date_header or None,
    }


class GmailMcpOtpExtractor:
    def __init__(self, *, email_address: str, password: str, timeout_seconds: float = 45, poll_seconds: float = 5) -> None:
        self.email_address = email_address
        self.password = password
        self.timeout_seconds = timeout_seconds
        self.poll_seconds = poll_seconds

    def wait_for_latest_code(self) -> GmailOtpResult:
        if not self.email_address or not self.password:
            return GmailOtpResult(False, None, "Gmail OTP credentials are not configured")

        deadline = time.monotonic() + self.timeout_seconds
        last_message = "No Gmail OTP message matched yet"
        while time.monotonic() <= deadline:
            result = self._poll_once()
            if result.ok or result.message != "No Gmail OTP message matched":
                return result
            last_message = result.message
            time.sleep(self.poll_seconds)
        return GmailOtpResult(False, None, last_message, metadata={"status": "timeout"})

    def _poll_once(self) -> GmailOtpResult:
        try:
            with imaplib.IMAP4_SSL("imap.gmail.com") as client:
                client.login(self.email_address, self.password)
                client.select("INBOX", readonly=True)
                for search_query in ("UNSEEN", "ALL"):
                    status, data = client.search(None, search_query)
                    if status != "OK" or not data or not data[0]:
                        continue
                    ids = data[0].split()[-10:]
                    for message_id in reversed(ids):
                        fetch_status, message_data = client.fetch(message_id, "(BODY.PEEK[])")
                        if fetch_status != "OK" or not message_data:
                            continue
                        raw_payload = next((item[1] for item in message_data if isinstance(item, tuple)), None)
                        if not isinstance(raw_payload, bytes):
                            continue
                        message = BytesParser(policy=policy.default).parsebytes(raw_payload)
                        searchable = f"{message.get('Subject') or ''}\n{_message_text(message)}"
                        code = extract_otp_code(searchable)
                        if code:
                            return GmailOtpResult(
                                True,
                                code,
                                "Gmail OTP code extracted",
                                metadata={
                                    **_safe_message_metadata(message),
                                    "searched_at": datetime.now(UTC).isoformat(),
                                    "search_query": search_query,
                                },
                            )
                return GmailOtpResult(False, None, "No Gmail OTP message matched")
        except imaplib.IMAP4.error:
            return GmailOtpResult(False, None, "Gmail authentication failed", metadata={"status": "auth_failed"})
        except OSError:
            return GmailOtpResult(False, None, "Gmail network access failed", metadata={"status": "network_failed"})


def read_gmail_otp_from_env() -> GmailOtpResult:
    if os.getenv("APPLYO_GMAIL_OTP_ENABLED") != "1":
        return GmailOtpResult(False, None, "Gmail OTP extraction is disabled", metadata={"status": "disabled"})
    timeout = float(os.getenv("APPLYO_GMAIL_OTP_TIMEOUT_SECONDS", "45"))
    poll = float(os.getenv("APPLYO_GMAIL_OTP_POLL_SECONDS", "5"))
    return GmailMcpOtpExtractor(
        email_address=os.getenv("APPLYO_GMAIL_OTP_EMAIL", ""),
        password=os.getenv("APPLYO_GMAIL_OTP_PASSWORD", ""),
        timeout_seconds=timeout,
        poll_seconds=poll,
    ).wait_for_latest_code()
