from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class Severity(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class EventType(StrEnum):
    RUN_STARTED = "RUN_STARTED"
    JD_SCRAPE_STARTED = "JD_SCRAPE_STARTED"
    JD_SCRAPE_COMPLETED = "JD_SCRAPE_COMPLETED"
    JD_ANALYSIS_COMPLETED = "JD_ANALYSIS_COMPLETED"
    RESUME_TAILORING_STARTED = "RESUME_TAILORING_STARTED"
    RESUME_MUTATION_COMPLETED = "RESUME_MUTATION_COMPLETED"
    RESUME_RENDERED = "RESUME_RENDERED"
    COVER_LETTER_REQUIRED = "COVER_LETTER_REQUIRED"
    COVER_LETTER_RENDERED = "COVER_LETTER_RENDERED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    BROWSER_LAUNCHED = "BROWSER_LAUNCHED"
    PAGE_NAVIGATED = "PAGE_NAVIGATED"
    PORTAL_WORKFLOW_SELECTED = "PORTAL_WORKFLOW_SELECTED"
    PORTAL_ACTION_APPLIED = "PORTAL_ACTION_APPLIED"
    PORTAL_STATE_OBSERVED = "PORTAL_STATE_OBSERVED"
    BROWSER_ARTIFACT_CAPTURED = "BROWSER_ARTIFACT_CAPTURED"
    FIELD_DETECTED = "FIELD_DETECTED"
    FIELD_VALUE_PROPOSED = "FIELD_VALUE_PROPOSED"
    FIELD_VALUE_APPLIED = "FIELD_VALUE_APPLIED"
    FILE_UPLOADED = "FILE_UPLOADED"
    SCREENSHOT_CAPTURED = "SCREENSHOT_CAPTURED"
    OTP_RETRIEVAL_STARTED = "OTP_RETRIEVAL_STARTED"
    OTP_RETRIEVAL_COMPLETED = "OTP_RETRIEVAL_COMPLETED"
    OTP_RETRIEVAL_FAILED = "OTP_RETRIEVAL_FAILED"
    USER_REVIEW_REQUIRED = "USER_REVIEW_REQUIRED"
    PAUSED = "PAUSED"
    RESUMED = "RESUMED"
    READY_TO_SUBMIT = "READY_TO_SUBMIT"
    SUBMITTED = "SUBMITTED"
    FAILED = "FAILED"
    CLEANUP_COMPLETED = "CLEANUP_COMPLETED"
    LLM_USAGE_REPORTED = "LLM_USAGE_REPORTED"
    RESUME_PARSE_RISK_DETECTED = "RESUME_PARSE_RISK_DETECTED"


JsonObject = dict[str, Any]


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class WorkerEvent:
    event_type: EventType
    run_id: str
    step_id: str | None
    severity: Severity
    message: str
    machine_state: JsonObject = field(default_factory=dict)
    ui_state: JsonObject = field(default_factory=dict)
    payload: JsonObject = field(default_factory=dict)
    timestamp: str = field(default_factory=utc_now)

    def to_dict(self) -> JsonObject:
        self._validate()
        return {
            "event_type": self.event_type.value,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "timestamp": self.timestamp,
            "severity": self.severity.value,
            "message": self.message,
            "machine_state": self.machine_state,
            "ui_state": self.ui_state,
            "payload": self.payload,
        }

    def to_json_line(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"), ensure_ascii=False)

    def emit(self) -> None:
        sys.stdout.buffer.write((self.to_json_line() + "\n").encode("utf-8"))
        sys.stdout.buffer.flush()

    def _validate(self) -> None:
        if not self.run_id:
            raise ValueError("run_id is required")
        if not self.message:
            raise ValueError("message is required")
        if self.event_type == EventType.SCREENSHOT_CAPTURED:
            assert_screenshot_payload(self.payload)


def assert_screenshot_payload(payload: JsonObject) -> None:
    required = {"screenshot_id", "local_path", "mime_type", "width", "height", "captured_at"}
    missing = sorted(required - payload.keys())
    if missing:
        raise ValueError(f"screenshot payload missing fields: {', '.join(missing)}")
    if "base64" in payload or "blob" in payload:
        raise ValueError("screenshot payload must contain metadata only")


def parse_event_line(line: str) -> WorkerEvent:
    raw = json.loads(line)
    if not isinstance(raw, dict):
        raise ValueError("event line must decode to an object")

    event = WorkerEvent(
        event_type=EventType(raw["event_type"]),
        run_id=str(raw["run_id"]),
        step_id=raw.get("step_id"),
        timestamp=str(raw["timestamp"]),
        severity=Severity(raw["severity"]),
        message=str(raw["message"]),
        machine_state=dict(raw.get("machine_state") or {}),
        ui_state=dict(raw.get("ui_state") or {}),
        payload=dict(raw.get("payload") or {}),
    )
    event._validate()
    return event


def emit_failure(run_id: str, message: str, *, step_id: str | None = None, payload: JsonObject | None = None) -> None:
    WorkerEvent(
        event_type=EventType.FAILED,
        run_id=run_id,
        step_id=step_id,
        severity=Severity.ERROR,
        message=message,
        payload=payload or {},
    ).emit()


def fail_process(run_id: str, message: str, exit_code: int = 1) -> None:
    emit_failure(run_id, message)
    sys.exit(exit_code)
