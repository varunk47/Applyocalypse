"""Stop a run that has no resume it is allowed to tailor.

Format-preserving tailoring writes into a *confirmed* editable master and
nothing else, because writing into an unconfirmed conversion means every
application carries a layout the user has never seen. When there is no confirmed
master the correct behaviour is to stop and ask, but the branch that does the
work simply did not run, and the run went on to render a generic Markdown resume
and report success. The user finished onboarding, pasted links, watched runs
succeed, and their resume was never tailored, with no error anywhere.

So the reason has to be worked out and said. Which of the three reasons it is
decides what the user has to go and do, so they are not collapsed into one
message.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..event_protocol import EventType, Severity, WorkerEvent

# The formats the mutation paths in document_stage can actually write into.
MUTABLE_FORMATS = frozenset({"DOCX", "TEX"})


@dataclass(frozen=True, slots=True)
class MissingMaster:
    code: str
    message: str
    # The file the user has to confirm, when there is one to point at.
    candidate_path: str | None = None


def _resumes(canonical_profile: dict[str, Any]) -> list[dict[str, Any]]:
    uploaded_files = canonical_profile.get("uploadedFiles")
    if not isinstance(uploaded_files, list):
        return []
    return [
        uploaded_file
        for uploaded_file in uploaded_files
        if isinstance(uploaded_file, dict) and uploaded_file.get("fileKind") == "RESUME"
    ]


def explain_missing_resume_master(canonical_profile: dict[str, Any]) -> MissingMaster | None:
    """Say why this profile has no resume that can be tailored, or None if it has one."""
    resumes = _resumes(canonical_profile)

    for resume in resumes:
        if (
            resume.get("status") == "VERIFIED_EDITABLE_MASTER"
            and resume.get("sourceFormat") in MUTABLE_FORMATS
            and resume.get("localPath")
        ):
            return None

    # Checked before the general case: when a PDF is uploaded both it and its
    # conversion are present, and the conversion is the one the user can act on.
    for resume in resumes:
        if resume.get("status") == "UNVERIFIED_EDITABLE_MASTER" and resume.get("localPath"):
            return MissingMaster(
                code="EDITABLE_MASTER_NOT_CONFIRMED",
                message=(
                    "Your resume was converted into an editable copy that you have not confirmed yet. "
                    "Open it, check the layout survived, and confirm it as your master. Until then nothing "
                    "can be tailored from it."
                ),
                candidate_path=str(resume["localPath"]),
            )

    if resumes:
        return MissingMaster(
            code="RESUME_NOT_CONVERTED",
            message=(
                "Your resume is not in a form this can tailor. Upload the Word or LaTeX original, or a PDF "
                "exported from one, so an editable copy can be built from it."
            ),
        )

    return MissingMaster(
        code="NO_RESUME_UPLOADED",
        message="No resume has been uploaded yet, so there is nothing to tailor for this job.",
    )


def emit_missing_master_gate(*, run_id: str, finding: MissingMaster) -> None:
    """Block the run on the missing master.

    USER_REVIEW_REQUIRED is what the event ingest turns into WAITING_FOR_USER, so
    this is the difference between the run stopping in front of the user and the
    run sailing past with a warning nobody reads.
    """
    WorkerEvent(
        event_type=EventType.USER_REVIEW_REQUIRED,
        run_id=run_id,
        step_id=None,
        severity=Severity.ERROR,
        message="No confirmed resume master, so this resume cannot be tailored",
        machine_state={"gate": "EDITABLE_MASTER", "code": finding.code},
        ui_state={"current_step": "document_review", "requires_user_review": True},
        payload={
            "artifact_kind": "resume",
            "code": finding.code,
            "detail": finding.message,
            "candidate_path": finding.candidate_path,
        },
    ).emit()
