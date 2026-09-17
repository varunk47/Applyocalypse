"""The run must stop when it has no resume it is allowed to tailor.

Format-preserving tailoring only ever writes into a confirmed editable master.
When there is not one, the whole branch used to be skipped: the run still
rendered a generic Markdown resume, still reported success, and the user's own
document was never touched. Nothing anywhere said so. These tests hold the
replacement to the rule that a stage which cannot do its job has to say it
cannot, in terms that name the next action.
"""

from __future__ import annotations

from typing import Any

import pytest

from applyocalypse_automation import event_protocol
from applyocalypse_automation.documents.resume_master_gate import (
    emit_missing_master_gate,
    explain_missing_resume_master,
)
from applyocalypse_automation.event_protocol import EventType, Severity, WorkerEvent


@pytest.fixture
def captured_events(monkeypatch: pytest.MonkeyPatch) -> list[WorkerEvent]:
    events: list[WorkerEvent] = []
    monkeypatch.setattr(event_protocol.WorkerEvent, "emit", lambda self: events.append(self))
    return events


def _profile(*files: dict[str, Any]) -> dict[str, Any]:
    return {"uploadedFiles": list(files)}


def _resume(status: str, source_format: str = "DOCX", local_path: str = "C:/resumes/master.docx") -> dict[str, Any]:
    return {
        "fileKind": "RESUME",
        "status": status,
        "sourceFormat": source_format,
        "localPath": local_path,
    }


def test_a_confirmed_master_is_not_a_finding() -> None:
    assert explain_missing_resume_master(_profile(_resume("VERIFIED_EDITABLE_MASTER"))) is None


# (what the profile holds, the code the user should be told)
CASES: tuple[tuple[str, dict[str, Any], str], ...] = (
    (
        "a converted PDF nobody confirmed",
        _profile(
            _resume("IMMUTABLE_SOURCE", "PDF", "C:/resumes/master.pdf"),
            _resume("UNVERIFIED_EDITABLE_MASTER"),
        ),
        "EDITABLE_MASTER_NOT_CONFIRMED",
    ),
    (
        "a PDF whose conversion never produced a candidate",
        _profile(_resume("IMMUTABLE_SOURCE", "PDF", "C:/resumes/master.pdf")),
        "RESUME_NOT_CONVERTED",
    ),
    (
        "a resume in a format nothing can mutate",
        _profile(_resume("VERIFIED_EDITABLE_MASTER", "MD", "C:/resumes/master.md")),
        "RESUME_NOT_CONVERTED",
    ),
    ("no resume at all", _profile(), "NO_RESUME_UPLOADED"),
    ("only a cover letter", _profile({"fileKind": "COVER_LETTER", "status": "UPLOADED"}), "NO_RESUME_UPLOADED"),
    ("a profile with no uploads key", {}, "NO_RESUME_UPLOADED"),
)


@pytest.mark.parametrize("description,profile,code", CASES, ids=[case[0] for case in CASES])
def test_the_reason_is_specific_enough_to_act_on(description: str, profile: dict[str, Any], code: str) -> None:
    """A single 'no resume' code would leave the user guessing which of three
    different things they have to go and do."""
    finding = explain_missing_resume_master(profile)
    assert finding is not None, description
    assert finding.code == code, description


def test_a_confirmable_candidate_is_preferred_over_the_unconverted_reading() -> None:
    """Both a raw PDF and its candidate are present in the normal PDF flow. The
    actionable one is the candidate, so that is what the user is pointed at."""
    finding = explain_missing_resume_master(
        _profile(
            _resume("IMMUTABLE_SOURCE", "PDF", "C:/resumes/master.pdf"),
            _resume("UNVERIFIED_EDITABLE_MASTER", "DOCX", "C:/resumes/candidate.docx"),
        )
    )
    assert finding is not None
    assert finding.candidate_path == "C:/resumes/candidate.docx"


@pytest.mark.parametrize("description,profile,code", CASES, ids=[case[0] for case in CASES])
def test_every_reason_names_what_to_do_next(description: str, profile: dict[str, Any], code: str) -> None:
    finding = explain_missing_resume_master(profile)
    assert finding is not None
    assert finding.message.strip(), description
    # The banned-word gate applies to anything the user reads.
    assert "—" not in finding.message, description


def test_the_gate_blocks_the_run_rather_than_logging_a_warning(captured_events: list[WorkerEvent]) -> None:
    """USER_REVIEW_REQUIRED is what the ingest maps to WAITING_FOR_USER. An INFO
    event here would reproduce the exact bug this gate exists to remove."""
    finding = explain_missing_resume_master(_profile())
    assert finding is not None
    emit_missing_master_gate(run_id="run-1", finding=finding)

    assert len(captured_events) == 1
    event = captured_events[0]
    assert event.event_type is EventType.USER_REVIEW_REQUIRED
    assert event.severity is Severity.ERROR
    assert event.ui_state["requires_user_review"] is True
    assert event.payload["code"] == "NO_RESUME_UPLOADED"
    assert event.payload["artifact_kind"] == "resume"


def test_the_gate_reports_the_candidate_the_user_has_to_confirm(captured_events: list[WorkerEvent]) -> None:
    finding = explain_missing_resume_master(
        _profile(_resume("UNVERIFIED_EDITABLE_MASTER", "DOCX", "C:/resumes/candidate.docx"))
    )
    assert finding is not None
    emit_missing_master_gate(run_id="run-1", finding=finding)

    payload = captured_events[0].payload
    assert payload["code"] == "EDITABLE_MASTER_NOT_CONFIRMED"
    assert payload["candidate_path"] == "C:/resumes/candidate.docx"
