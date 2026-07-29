"""Runner-level behaviour of the email verification link flow.

The properties pinned here are the security ones: the link is a credential, so it
must never reach an event, and it must never be opened before the user approves.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path

import pytest

from applyocalypse_automation import runner as runner_module
from applyocalypse_automation.browser.adapter import BrowserBlocker, BrowserField, BrowserStepResult
from applyocalypse_automation.otp import GmailOtpResult
from applyocalypse_automation.runner import pause_for_blockers

WORKDAY_PAGE_URL = "https://acme.wd5.myworkdayjobs.com/en-US/careers/job/123/apply"
VERIFICATION_LINK = "https://wd5.myworkday.com/wday/authgwy/acme/login?token=SECRETTOKEN123"
ATTACKER_LINK = "https://verify-workday.attacker.example/confirm?token=SECRETTOKEN123"


class FakeAdapter:
    """Minimal adapter: records navigation, reports the live URL, never self-clears."""

    def __init__(self, *, page_url: str = WORKDAY_PAGE_URL) -> None:
        self.page_url = page_url
        self.opened_urls: list[str] = []
        self.applied_values: list[str] = []
        self.blocker_checks = 0

    async def extract_visible_text(self) -> BrowserStepResult:
        return BrowserStepResult(True, "visible text extracted", {"url": self.page_url, "text": "Check your email"})

    async def open_url(self, url: str) -> BrowserStepResult:
        self.opened_urls.append(url)
        return BrowserStepResult(True, "navigated", {"url": url})

    async def detect_fields(self) -> list[BrowserField]:
        return [
            BrowserField(
                field_id="otp-1",
                selector="#otp",
                label="Verification code",
                field_type="text",
                required=True,
                confidence=0.91,
            )
        ]

    async def apply_field_value(self, field: BrowserField, value: str) -> BrowserStepResult:
        self.applied_values.append(value)
        return BrowserStepResult(True, "applied", {"field_id": field.field_id})

    async def detect_blockers(self) -> list[BrowserBlocker]:
        self.blocker_checks += 1
        return []


def _link_only_result(*links: str) -> GmailOtpResult:
    return GmailOtpResult(
        True,
        None,
        "Gmail verification link extracted",
        metadata={"message_id_sha256": "hash", "from_domain": "myworkday.com"},
        links=links,
    )


@pytest.fixture(name="gmail_enabled")
def _gmail_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APPLYO_GMAIL_OTP_ENABLED", "1")


def _write_control_after_delay(work_dir: Path, command: str) -> threading.Thread:
    def write() -> None:
        time.sleep(0.05)
        (work_dir / "control.json").write_text(
            json.dumps({"command": command, "reason": "user_reviewed_link"}), encoding="utf-8"
        )

    thread = threading.Thread(target=write, daemon=True)
    thread.start()
    return thread


def _run_blocker_pause(adapter: FakeAdapter, work_dir: Path, run_id: str) -> bool:
    return asyncio.run(
        pause_for_blockers(
            adapter,
            work_dir,
            run_id,
            [BrowserBlocker(blocker_type="OTP", message="Check your email to continue", confidence=0.9)],
            context="portal sign-in",
        )
    )


def test_approved_link_is_opened_and_never_appears_in_any_event(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, gmail_enabled: None
) -> None:
    monkeypatch.setattr(runner_module, "read_gmail_otp_from_env", lambda **_: _link_only_result(VERIFICATION_LINK))
    adapter = FakeAdapter()
    thread = _write_control_after_delay(tmp_path, "RESUME")

    should_stop = _run_blocker_pause(adapter, tmp_path, "run-link")
    thread.join(timeout=2)

    output = capsys.readouterr().out
    events = [json.loads(line) for line in output.splitlines()]

    assert should_stop is False
    assert adapter.opened_urls == [VERIFICATION_LINK]
    assert [event["event_type"] for event in events] == [
        "OTP_RETRIEVAL_STARTED",
        "PAUSED",
        "OTP_RETRIEVAL_COMPLETED",
    ]
    # The whole point: a magic link is a credential, so no event may carry it.
    assert "SECRETTOKEN123" not in output
    assert VERIFICATION_LINK not in output
    # The user still gets enough to judge the destination.
    assert events[1]["payload"]["redacted_target"] == "https://wd5.myworkday.com/wday/authgwy/acme/login"


def test_link_is_not_opened_until_the_user_approves(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, gmail_enabled: None
) -> None:
    """The approval gate is the whole safety story, so navigation must block on it."""
    monkeypatch.setattr(runner_module, "read_gmail_otp_from_env", lambda **_: _link_only_result(VERIFICATION_LINK))
    adapter = FakeAdapter()
    observed_at_approval: list[list[str]] = []

    def write_after_observing() -> None:
        time.sleep(0.15)
        observed_at_approval.append(list(adapter.opened_urls))
        (tmp_path / "control.json").write_text(json.dumps({"command": "RESUME"}), encoding="utf-8")

    thread = threading.Thread(target=write_after_observing, daemon=True)
    thread.start()

    _run_blocker_pause(adapter, tmp_path, "run-link-wait")
    thread.join(timeout=2)
    capsys.readouterr()

    assert observed_at_approval == [[]]
    assert adapter.opened_urls == [VERIFICATION_LINK]


def test_cancelling_at_the_approval_gate_stops_the_run_without_navigating(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, gmail_enabled: None
) -> None:
    monkeypatch.setattr(runner_module, "read_gmail_otp_from_env", lambda **_: _link_only_result(VERIFICATION_LINK))
    adapter = FakeAdapter()
    thread = _write_control_after_delay(tmp_path, "CANCEL")

    should_stop = _run_blocker_pause(adapter, tmp_path, "run-link-cancel")
    thread.join(timeout=2)

    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]

    assert should_stop is True
    assert adapter.opened_urls == []
    assert [event["event_type"] for event in events] == ["OTP_RETRIEVAL_STARTED", "PAUSED", "FAILED"]
    assert events[-1]["payload"]["code"] == "USER_CANCELLED"


def test_untrusted_link_is_never_offered_for_approval(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, gmail_enabled: None
) -> None:
    """An attacker's email must not become a redirect primitive for the run."""
    monkeypatch.setattr(runner_module, "read_gmail_otp_from_env", lambda **_: _link_only_result(ATTACKER_LINK))
    adapter = FakeAdapter()
    thread = _write_control_after_delay(tmp_path, "CANCEL")

    _run_blocker_pause(adapter, tmp_path, "run-link-untrusted")
    thread.join(timeout=2)

    output = capsys.readouterr().out
    events = [json.loads(line) for line in output.splitlines()]
    failures = [event for event in events if event["event_type"] == "OTP_RETRIEVAL_FAILED"]

    assert adapter.opened_urls == []
    assert failures and failures[0]["machine_state"]["reason"] == "LINK_NOT_TRUSTED_FOR_PORTAL"
    # A rejected candidate came from an untrusted inbox, so not even its host is
    # written into the run record; the count is all the diagnostics that is owed.
    assert "attacker.example" not in output
    assert failures[0]["payload"]["link_count"] == 1
    # It falls through to the ordinary manual pause rather than failing the run.
    assert "PAUSED" in [event["event_type"] for event in events]


def test_a_numeric_code_still_wins_over_a_link_in_the_same_email(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, gmail_enabled: None
) -> None:
    """Typing the code is less intrusive than navigating, so it stays the default."""
    monkeypatch.setattr(
        runner_module,
        "read_gmail_otp_from_env",
        lambda **_: GmailOtpResult(True, "493821", "Gmail OTP code extracted", links=(VERIFICATION_LINK,)),
    )
    adapter = FakeAdapter()

    _run_blocker_pause(adapter, tmp_path, "run-code-wins")

    output = capsys.readouterr().out
    event_types = [json.loads(line)["event_type"] for line in output.splitlines()]

    assert adapter.applied_values == ["493821"]
    assert adapter.opened_urls == []
    assert "PAUSED" not in event_types
    assert "493821" not in output
    assert "SECRETTOKEN123" not in output


def test_gmail_is_not_polled_when_no_inbox_reader_is_configured(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("APPLYO_GMAIL_OTP_ENABLED", raising=False)
    monkeypatch.delenv("APPLYO_GMAIL_OAUTH_TOKEN_PATH", raising=False)
    polled = []
    monkeypatch.setattr(
        runner_module,
        "read_gmail_otp_from_env",
        lambda **_: polled.append(1) or _link_only_result(VERIFICATION_LINK),
    )
    adapter = FakeAdapter()
    thread = _write_control_after_delay(tmp_path, "CANCEL")

    _run_blocker_pause(adapter, tmp_path, "run-no-gmail")
    thread.join(timeout=2)
    capsys.readouterr()

    assert polled == []
    assert adapter.opened_urls == []


def test_oauth_token_path_alone_enables_inbox_retrieval(monkeypatch: pytest.MonkeyPatch) -> None:
    """The OAuth flow only sets the token path, so the gate must accept it on its own."""
    monkeypatch.delenv("APPLYO_GMAIL_OTP_ENABLED", raising=False)
    monkeypatch.setenv("APPLYO_GMAIL_OAUTH_TOKEN_PATH", "C:/tmp/token.json")

    assert runner_module.gmail_inbox_reader_configured() is True
