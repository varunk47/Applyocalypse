from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .browser.adapter import BrowserAdapter, BrowserBlocker, BrowserField, BrowserStepResult
from .browser.adapter_factory import adapter_candidates_for_workflow, create_browser_adapter
from .browser.portal_adapters import (
    COMMON_STEP_PROGRESSION_LABELS,
    PortalRuntimePolicy,
    final_submit_labels_for_workflow,
    portal_runtime_policy_for_workflow,
    progression_labels_for_workflow,
)
from .browser.portal_state import PortalPageState, classify_portal_page_state
from .browser.portal_workflows import PortalWorkflow, workflow_for_url
from .control import WorkerControl, read_worker_control
from .document_stage import _lazy_generate_cover_letter_for_portal, generate_application_documents
from .event_protocol import EventType, Severity, WorkerEvent, fail_process, utc_now
from .field_resolution import (
    MATCH_OUTCOME_AMBIGUOUS,
    MATCH_OUTCOME_MATCHED,
    is_otp_field,
    match_approved_answer,
    normalize_field_label,
    proposed_answer_for_browser_field,
    resolve_secret_reviewed_value,
)
from .otp import GmailOtpResult, read_gmail_otp_from_env, redact_link, select_trusted_verification_link
from .secret_env import apply_provider_secrets_to_env


@dataclass(frozen=True, slots=True)
class UrlObservationResult:
    should_stop: bool
    job_text_file: Path | None = None
    scraped_url: str | None = None


FINAL_SUBMIT_LABELS = (
    "Submit",
    "Submit application",
    "Send application",
    "Finish application",
    "Complete application",
)

SAFE_STEP_PROGRESSION_LABELS = COMMON_STEP_PROGRESSION_LABELS

MAX_BLOCKED_PROGRESSION_ATTEMPTS = 3
# Server-side resume parsing (Workday, iCIMS) repopulates the form well after
# the upload request returns, so the wait after an upload is generous.
RESUME_PARSE_SETTLE_S = 15.0

SUBMISSION_CONFIRMATION_PATTERNS = (
    "application submitted",
    "application has been submitted",
    "successfully submitted",
    "thank you for applying",
    "thanks for applying",
    "received your application",
    "we have received your application",
)


def wait_for_review_resume(
    work_dir: Path,
    *,
    poll_seconds: float = 0.75,
    run_id: str | None = None,
    current_step: str = "automation",
    context: str = "manual review",
) -> WorkerControl:
    while True:
        control = read_worker_control(work_dir)
        if control and control.command in {"RESUME", "CANCEL"}:
            return control
        if control and run_id is not None:
            WorkerEvent(
                event_type=EventType.USER_REVIEW_REQUIRED,
                run_id=run_id,
                step_id=control.step_id,
                severity=Severity.WARN,
                message=f"{control.command} cannot resolve {context}; resume or cancel is required",
                machine_state={"reason": "RESUME_OR_CANCEL_REQUIRED", "command": control.command, "context": context},
                ui_state={"requires_user_review": True, "current_step": current_step},
                payload={"expected_commands": ["RESUME", "CANCEL"], "received_command": control.command},
            ).emit()
        time.sleep(poll_seconds)


def is_final_submit_approval(control: WorkerControl) -> bool:
    approval_type = control.payload.get("approvalType") or control.payload.get("approval_type")
    return control.command == "RESUME" and str(approval_type or "").upper() == "FINAL_SUBMIT"


def is_document_approval(control: WorkerControl) -> bool:
    approval_type = control.payload.get("approvalType") or control.payload.get("approval_type")
    return control.command == "RESUME" and str(approval_type or "").upper() == "DOCUMENT_APPROVAL"


def control_auto_submit_enabled(control: WorkerControl) -> bool:
    raw_value = control.payload.get("autoSubmitEnabled")
    if raw_value is None:
        raw_value = control.payload.get("auto_submit_enabled")
    if isinstance(raw_value, bool):
        return raw_value
    if isinstance(raw_value, str):
        return raw_value.strip().lower() in {"1", "true", "yes"}
    return raw_value == 1


def submission_confirmation_detected(text: str) -> bool:
    normalized = " ".join(text.lower().split())
    return any(pattern in normalized for pattern in SUBMISSION_CONFIRMATION_PATTERNS)


def wait_for_final_submit_decision(work_dir: Path, run_id: str, *, poll_seconds: float = 0.75) -> WorkerControl | None:
    while True:
        control = read_worker_control(work_dir)
        if control is None:
            time.sleep(poll_seconds)
            continue
        if control.command == "CANCEL":
            emit_worker_cancelled(run_id, control, message="Final submission rejected or cancelled by local user")
            return None
        if is_final_submit_approval(control):
            WorkerEvent(
                event_type=EventType.RESUMED,
                run_id=run_id,
                step_id=control.step_id,
                severity=Severity.INFO,
                message="Final submission approved by local user",
                machine_state={"reason": control.reason or "local_user_approved_final_submit"},
                ui_state={"current_step": "final_submit"},
                payload={"approval_type": "FINAL_SUBMIT"},
            ).emit()
            return control
        WorkerEvent(
            event_type=EventType.USER_REVIEW_REQUIRED,
            run_id=run_id,
            step_id=control.step_id,
            severity=Severity.WARN,
            message="Final submission requires explicit FINAL_SUBMIT approval",
            machine_state={"reason": "FINAL_SUBMIT_APPROVAL_REQUIRED", "command": control.command},
            ui_state={"requires_user_review": True, "current_step": "final_submit"},
            payload={"expected_approval_type": "FINAL_SUBMIT"},
        ).emit()


def wait_for_document_approval(work_dir: Path, run_id: str, *, poll_seconds: float = 0.75) -> WorkerControl | None:
    while True:
        control = read_worker_control(work_dir)
        if control is None:
            time.sleep(poll_seconds)
            continue
        if control.command == "CANCEL":
            WorkerEvent(
                event_type=EventType.FAILED,
                run_id=run_id,
                step_id=control.step_id,
                severity=Severity.WARN,
                message="Worker cancelled by local user during review gate",
                machine_state={"reason": control.reason or "USER_CANCELLED"},
                ui_state={"cancelled": True},
                payload={"code": "USER_CANCELLED"},
            ).emit()
            return None
        if is_document_approval(control):
            WorkerEvent(
                event_type=EventType.RESUMED,
                run_id=run_id,
                step_id=control.step_id,
                severity=Severity.INFO,
                message="Document approval received, resuming controlled automation",
                machine_state={"gate": "USER_REVIEW_GATE", "approval_type": "DOCUMENT_APPROVAL"},
                ui_state={"current_step": "automation"},
                payload={},
            ).emit()
            return control
        WorkerEvent(
            event_type=EventType.USER_REVIEW_REQUIRED,
            run_id=run_id,
            step_id=control.step_id,
            severity=Severity.WARN,
            message="Document review gate requires explicit DOCUMENT_APPROVAL before browser execution",
            machine_state={"reason": "DOCUMENT_APPROVAL_REQUIRED", "command": control.command},
            ui_state={"requires_user_review": True, "current_step": "document_review"},
            payload={"expected_approval_type": "DOCUMENT_APPROVAL"},
        ).emit()


@dataclass(frozen=True, slots=True)
class FinalSubmitGate:
    """What the run decided at the last gate before a click that cannot be undone."""

    auto_submit_enabled: bool
    review_text_detected: bool | None
    withdrawn: bool
    message: str


def evaluate_final_submit_gate(
    *,
    policy: PortalRuntimePolicy,
    auto_submit_enabled: bool,
    visible_text: str | None,
) -> FinalSubmitGate:
    """Decide whether a standing auto-submit preapproval applies to THIS page.

    Portals whose plan declares a review step (Workday, iCIMS) always show a
    summary page before the submit button. The plan listed that as evidence and
    nothing ever checked it. A page with no review text is probably not the
    submit page, so the preapproval does not apply to it and a person looks
    first. ``visible_text`` is None when the page could not be read, which is
    not evidence that the review screen is there.
    """
    if not policy.review_evidence_required:
        return FinalSubmitGate(
            auto_submit_enabled=auto_submit_enabled,
            review_text_detected=None,
            withdrawn=False,
            message=(
                "Final submission is preapproved by the explicit auto-submit setting"
                if auto_submit_enabled
                else "Final submission is gated until explicit approval"
            ),
        )

    detected = policy.review_signal_observed(visible_text or "")
    if detected:
        return FinalSubmitGate(
            auto_submit_enabled=auto_submit_enabled,
            review_text_detected=True,
            withdrawn=False,
            message=(
                "Final submission is preapproved by the explicit auto-submit setting"
                if auto_submit_enabled
                else "Final submission is gated until explicit approval"
            ),
        )

    return FinalSubmitGate(
        auto_submit_enabled=False,
        review_text_detected=False,
        withdrawn=auto_submit_enabled,
        message=(
            f"Final submission needs approval: {policy.portal_id} always shows a review page "
            "and this one was not detected"
            if auto_submit_enabled
            else "Final submission is gated until explicit approval"
        ),
    )


def final_submit_labels_for(workflow: PortalWorkflow | None) -> list[str]:
    """Portal-specific submit labels first, then the generic ones.

    The click matcher demands an exact normalized match, so a portal whose button
    reads "Submit Profile" (iCIMS) is unreachable from the generic list alone.
    Order is preserved and duplicates dropped so the portal's own wording wins.
    """
    labels = list(final_submit_labels_for_workflow(workflow)) if workflow is not None else []
    labels.extend(FINAL_SUBMIT_LABELS)
    return list(dict.fromkeys(labels))


async def perform_final_submit_with_control(
    adapter: BrowserAdapter,
    work_dir: Path,
    run_id: str,
    final_submit_control: WorkerControl,
    *,
    workflow: PortalWorkflow | None = None,
) -> bool:
    blockers = await adapter.detect_blockers()
    if blockers:
        if await pause_for_blockers(adapter, work_dir, run_id, blockers, context="final submission"):
            return False

    labels = final_submit_labels_for(workflow)
    result = await adapter.click_final_submit(labels)
    if not result.ok:
        WorkerEvent(
            event_type=EventType.USER_REVIEW_REQUIRED,
            run_id=run_id,
            step_id=final_submit_control.step_id,
            severity=Severity.WARN,
            message="Final submit approval was received, but no exact final submit control could be clicked",
            machine_state={
                "reason": "FINAL_SUBMIT_CONTROL_NOT_FOUND",
                "portal_id": workflow.portal_id if workflow is not None else None,
                "attempted_labels": labels,
            },
            ui_state={"requires_user_review": True, "current_step": "final_submit"},
            payload={**result.payload, "attempted_labels": labels},
        ).emit()
        return False

    blockers = await adapter.detect_blockers()
    if blockers:
        if await pause_for_blockers(adapter, work_dir, run_id, blockers, context="post-submit verification"):
            return False

    visible_text = await adapter.extract_visible_text()
    text = str(visible_text.payload.get("text") or "") if visible_text.ok else ""
    if submission_confirmation_detected(text):
        WorkerEvent(
            event_type=EventType.SUBMITTED,
            run_id=run_id,
            step_id=final_submit_control.step_id,
            severity=Severity.INFO,
            message="Application submission confirmation detected after approved final submit",
            machine_state={"confirmation_detected": True},
            ui_state={"current_step": "submitted"},
            payload={
                "submit_action": result.payload,
                "confirmation": {
                    "url": visible_text.payload.get("url"),
                    "title": visible_text.payload.get("title"),
                    "text_length": visible_text.payload.get("text_length"),
                },
            },
        ).emit()
        return True

    WorkerEvent(
        event_type=EventType.PAUSED,
        run_id=run_id,
        step_id=final_submit_control.step_id,
        severity=Severity.WARN,
        message="Final submit was clicked, but Applyocalypse could not verify a submission confirmation",
        machine_state={"reason": "SUBMISSION_CONFIRMATION_UNVERIFIED"},
        ui_state={"requires_user_review": True, "current_step": "final_submit"},
        payload={
            "submit_action": result.payload,
            "confirmation": {
                "url": visible_text.payload.get("url") if visible_text.ok else None,
                "title": visible_text.payload.get("title") if visible_text.ok else None,
                "text_length": visible_text.payload.get("text_length") if visible_text.ok else None,
            },
        },
    ).emit()
    return False


async def perform_final_submit_after_approval(
    adapter: BrowserAdapter,
    work_dir: Path,
    run_id: str,
    *,
    workflow: PortalWorkflow | None = None,
) -> bool:
    final_submit_control = await asyncio.to_thread(wait_for_final_submit_decision, work_dir, run_id)
    if final_submit_control is None:
        return False
    return await perform_final_submit_with_control(adapter, work_dir, run_id, final_submit_control, workflow=workflow)


def emit_worker_cancelled(run_id: str, control: WorkerControl, *, message: str) -> None:
    WorkerEvent(
        event_type=EventType.FAILED,
        run_id=run_id,
        step_id=control.step_id,
        severity=Severity.WARN,
        message=message,
        machine_state={"reason": control.reason or "USER_CANCELLED"},
        ui_state={"cancelled": True},
        payload={"code": "USER_CANCELLED"},
    ).emit()


async def handle_runtime_control(work_dir: Path, run_id: str, *, context: str) -> bool:
    control = read_worker_control(work_dir, consume=False)
    if control is None:
        return False
    if control.command == "RESUME":
        return False
    control = read_worker_control(work_dir) or control
    if control.command == "CANCEL":
        emit_worker_cancelled(run_id, control, message=f"Worker cancelled by local user during {context}")
        return True
    if control.command == "PAUSE":
        WorkerEvent(
            event_type=EventType.PAUSED,
            run_id=run_id,
            step_id=control.step_id,
            severity=Severity.WARN,
            message=f"Automation paused by local user during {context}",
            machine_state={"reason": "USER_PAUSE", "context": context},
            ui_state={"requires_user_review": True, "current_step": "paused"},
            payload={},
        ).emit()
        resume_control = await asyncio.to_thread(wait_for_review_resume, work_dir, run_id=run_id, current_step="automation", context=context)
        if resume_control.command == "CANCEL":
            emit_worker_cancelled(run_id, resume_control, message=f"Worker cancelled by local user while paused during {context}")
            return True
        WorkerEvent(
            event_type=EventType.RESUMED,
            run_id=run_id,
            step_id=resume_control.step_id,
            severity=Severity.INFO,
            message=f"Automation resumed by local user during {context}",
            machine_state={"reason": resume_control.reason or "local_user_resume", "context": context},
            ui_state={"current_step": "automation"},
            payload={},
        ).emit()
        return False
    if control.command in {"RETRY_STEP", "SKIP_STEP"}:
        WorkerEvent(
            event_type=EventType.USER_REVIEW_REQUIRED,
            run_id=run_id,
            step_id=control.step_id,
            severity=Severity.WARN,
            message=f"{control.command} was requested outside a retryable paused step",
            machine_state={"reason": "RUNTIME_CONTROL_NOT_APPLIED", "command": control.command, "context": context},
            ui_state={"requires_user_review": True, "current_step": "automation"},
            payload={"command": control.command},
        ).emit()
    return False


def blocker_payload_from(blockers: list[BrowserBlocker]) -> list[dict[str, object]]:
    return [
        {
            "blocker_type": blocker.blocker_type,
            "message": blocker.message,
            "confidence": blocker.confidence,
            "metadata": blocker.metadata,
        }
        for blocker in blockers
    ]


async def apply_otp_code_to_detected_field(adapter: object, run_id: str, code: str) -> bool:
    fields = await adapter.detect_fields()  # type: ignore[attr-defined]
    otp_field = next((field for field in fields if is_otp_field(field)), None)
    if otp_field is None:
        WorkerEvent(
            event_type=EventType.OTP_RETRIEVAL_FAILED,
            run_id=run_id,
            step_id=None,
            severity=Severity.WARN,
            message="Gmail OTP was retrieved, but no OTP input field could be identified",
            machine_state={"reason": "OTP_FIELD_NOT_FOUND"},
            ui_state={"requires_user_review": True, "current_step": "otp"},
            payload={"field_count": len(fields)},
        ).emit()
        return False

    result = await adapter.apply_field_value(otp_field, code)  # type: ignore[attr-defined]
    if not result.ok:
        WorkerEvent(
            event_type=EventType.OTP_RETRIEVAL_FAILED,
            run_id=run_id,
            step_id=None,
            severity=Severity.WARN,
            message="Gmail OTP was retrieved, but the OTP field could not be filled",
            machine_state={"reason": "OTP_FIELD_FILL_FAILED", "selector": otp_field.selector},
            ui_state={"requires_user_review": True, "current_step": "otp"},
            payload={"field_label": otp_field.label, "field_type": otp_field.field_type, **result.payload},
        ).emit()
        return False

    WorkerEvent(
        event_type=EventType.FIELD_VALUE_APPLIED,
        run_id=run_id,
        step_id=None,
        severity=Severity.INFO,
        message=f"Applied Gmail OTP to {otp_field.label}",
        machine_state={"selector": otp_field.selector, "field_type": otp_field.field_type, "source": "GMAIL_OTP"},
        ui_state={"current_step": "otp"},
        payload={
            "field_label": otp_field.label,
            "field_type": otp_field.field_type,
            "selector": otp_field.selector,
            "value_length": None,
            "source": "GMAIL_OTP",
            "applied_action": result.payload.get("action"),
        },
    ).emit()
    return True


def gmail_inbox_reader_configured() -> bool:
    """True when either Gmail path is wired up for this run.

    The OAuth flow only ever sets the token path, so checking the legacy
    app-password flag alone would leave OAuth users with no automatic retrieval.
    """
    return bool(os.getenv("APPLYO_GMAIL_OAUTH_TOKEN_PATH")) or os.getenv("APPLYO_GMAIL_OTP_ENABLED") == "1"


# NAVIGATED: a code was applied or an approved link was opened, so page state
#   must be rechecked.
# CANCELLED: the user cancelled at the approval gate; the run is over.
# SKIPPED: nothing usable was found, so fall through to the normal manual pause.
EmailVerificationOutcome = Literal["NAVIGATED", "CANCELLED", "SKIPPED"]

# Blockers the inbox can answer, either with a code or with a confirmation link.
# LOGIN is excluded: that is a password prompt, which is the user's alone.
INBOX_RESOLVABLE_BLOCKER_TYPES = frozenset({"OTP", "MFA"})


async def _current_page_url(adapter: object) -> str | None:
    """Read the live URL, which is what a candidate link has to be trusted against."""
    try:
        result = await adapter.extract_visible_text()  # type: ignore[attr-defined]
    except Exception:
        return None
    return str(result.payload.get("url") or "") or None


async def _read_gmail_verification(run_id: str, *, context: str) -> GmailOtpResult | None:
    """Poll Gmail once for either a code or a confirmation link.

    One read serves both paths: polling twice would double the wait and re-read
    the same message.
    """
    WorkerEvent(
        event_type=EventType.OTP_RETRIEVAL_STARTED,
        run_id=run_id,
        step_id=None,
        severity=Severity.INFO,
        message="Gmail verification retrieval started",
        machine_state={"provider": "gmail", "context": context},
        ui_state={"current_step": "otp"},
        payload={"provider": "gmail"},
    ).emit()
    result = await asyncio.to_thread(read_gmail_otp_from_env, accept="code_or_link")
    if result.ok and (result.code or result.links):
        return result
    WorkerEvent(
        event_type=EventType.OTP_RETRIEVAL_FAILED,
        run_id=run_id,
        step_id=None,
        severity=Severity.WARN,
        message=result.message,
        machine_state={"provider": "gmail", "context": context},
        ui_state={"requires_user_review": True, "current_step": "otp"},
        payload=result.safe_payload(),
    ).emit()
    return None


async def try_resolve_verification_from_gmail(
    adapter: object, work_dir: Path, run_id: str, *, context: str
) -> EmailVerificationOutcome:
    """Answer an OTP or MFA challenge from the user's inbox.

    A numeric code is typed into the page as before. A confirmation link is
    treated as the credential it is: it stays in worker memory, only its redacted
    form reaches an event, and it is opened solely after the user approves at the
    existing review gate, rather than routing around that gate.
    """
    if not gmail_inbox_reader_configured():
        return "SKIPPED"

    result = await _read_gmail_verification(run_id, context=context)
    if result is None:
        return "SKIPPED"

    if result.code:
        WorkerEvent(
            event_type=EventType.OTP_RETRIEVAL_COMPLETED,
            run_id=run_id,
            step_id=None,
            severity=Severity.INFO,
            message="Gmail OTP retrieved without exposing the code",
            machine_state={"provider": "gmail", "otp_kind": "CODE", "context": context},
            ui_state={"current_step": "otp"},
            payload=result.safe_payload(),
        ).emit()
        applied = await apply_otp_code_to_detected_field(adapter, run_id, result.code)
        return "NAVIGATED" if applied else "SKIPPED"

    portal_url = await _current_page_url(adapter)
    target = select_trusted_verification_link(result.links, portal_url) if portal_url else None
    if target is None:
        # An inbox is untrusted input, so a link that cannot be tied to this
        # portal is never offered: approving an unknown destination mid-run is
        # exactly what an injected email would be angling for.
        WorkerEvent(
            event_type=EventType.OTP_RETRIEVAL_FAILED,
            run_id=run_id,
            step_id=None,
            severity=Severity.WARN,
            message="A verification email was found, but no link belonged to this portal, so none was offered",
            machine_state={
                "provider": "gmail",
                "otp_kind": "LINK",
                "reason": "LINK_NOT_TRUSTED_FOR_PORTAL",
                "context": context,
            },
            ui_state={"requires_user_review": True, "current_step": "otp"},
            payload=result.safe_payload(),
        ).emit()
        return "SKIPPED"

    approval_payload = {
        **result.safe_payload(),
        "otp_kind": "LINK",
        # The redacted form only: the query string is where the token lives.
        "redacted_target": redact_link(target),
    }
    WorkerEvent(
        event_type=EventType.PAUSED,
        run_id=run_id,
        step_id=None,
        severity=Severity.WARN,
        message=(
            f"A verification link for {redact_link(target)} arrived in Gmail during {context}. "
            "Approve to open it in the automation browser."
        ),
        machine_state={
            "reason": "EMAIL_VERIFICATION_LINK_APPROVAL_REQUIRED",
            "otp_kind": "LINK",
            "context": context,
        },
        ui_state={"requires_user_review": True, "current_step": "blocked"},
        payload=approval_payload,
    ).emit()

    control = await asyncio.to_thread(
        wait_for_review_resume,
        work_dir,
        run_id=run_id,
        current_step="email_verification_link_review",
        context=context,
    )
    if control.command == "CANCEL":
        emit_worker_cancelled(
            run_id, control, message=f"Worker cancelled by local user at the verification link approval during {context}"
        )
        return "CANCELLED"

    open_result = await adapter.open_url(target)  # type: ignore[attr-defined]
    if not open_result.ok:
        WorkerEvent(
            event_type=EventType.OTP_RETRIEVAL_FAILED,
            run_id=run_id,
            step_id=None,
            severity=Severity.WARN,
            message="The approved verification link could not be opened",
            machine_state={"provider": "gmail", "otp_kind": "LINK", "reason": "LINK_OPEN_FAILED", "context": context},
            ui_state={"requires_user_review": True, "current_step": "otp"},
            payload=approval_payload,
        ).emit()
        return "SKIPPED"

    WorkerEvent(
        event_type=EventType.OTP_RETRIEVAL_COMPLETED,
        run_id=run_id,
        step_id=control.step_id,
        severity=Severity.INFO,
        message="Opened the approved verification link without exposing it",
        machine_state={"provider": "gmail", "otp_kind": "LINK", "context": context},
        ui_state={"current_step": "automation"},
        payload=approval_payload,
    ).emit()
    return "NAVIGATED"


MAX_BLOCKER_PAUSE_CYCLES = 3


async def _surface_browser_for_human(adapter: object) -> None:
    """Best-effort: raise the automation browser window so the user can act on the challenge."""
    bring_to_front = getattr(adapter, "bring_to_front", None)
    if bring_to_front is None:
        return
    try:
        await bring_to_front()
    except Exception:
        pass


# Blockers that physically stop automation and require the user to act on the page.
# AMBIGUOUS_QUESTION (sensitive / EEO / work-authorization questions) is intentionally
# NOT here: those are normal on nearly every application form and are reviewed per-field
# during the fill flow (answers.py forces requires_review=True on them), so they must
# never halt the whole run at the observation stage.
HALTING_BLOCKER_TYPES = frozenset({"CAPTCHA", "LOGIN", "MFA", "OTP"})


def _halting_blockers(blockers: list[BrowserBlocker]) -> list[BrowserBlocker]:
    return [blocker for blocker in blockers if blocker.blocker_type in HALTING_BLOCKER_TYPES]


async def pause_for_blockers(adapter: object, work_dir: Path, run_id: str, blockers: list[BrowserBlocker], *, context: str) -> bool:
    active_blockers = _halting_blockers(blockers)
    pause_cycles = 0
    while active_blockers:
        blocker_payload = blocker_payload_from(active_blockers)
        primary_blocker = active_blockers[0]
        resolved_from_inbox = False
        if any(blocker.blocker_type in INBOX_RESOLVABLE_BLOCKER_TYPES for blocker in active_blockers):
            outcome = await try_resolve_verification_from_gmail(adapter, work_dir, run_id, context=context)
            if outcome == "CANCELLED":
                return True
            resolved_from_inbox = outcome == "NAVIGATED"
        if resolved_from_inbox:
            active_blockers = _halting_blockers(await adapter.detect_blockers())  # type: ignore[attr-defined]
            if not active_blockers:
                return False
            blocker_payload = blocker_payload_from(active_blockers)
            primary_blocker = active_blockers[0]
        pause_cycles += 1
        if pause_cycles > MAX_BLOCKER_PAUSE_CYCLES:
            # A real challenge clears within a cycle or two; a detection that survives
            # repeated resumes would otherwise pause forever. Fail the run cleanly (the
            # same terminal path as cancel) so it always stops instead of hanging; the
            # user finishes the challenge manually in the browser and starts a new run.
            WorkerEvent(
                event_type=EventType.FAILED,
                run_id=run_id,
                step_id=None,
                severity=Severity.ERROR,
                message=(
                    f"{primary_blocker.blocker_type} challenge was still detected after "
                    f"{MAX_BLOCKER_PAUSE_CYCLES} attempts during {context}. Stopping the run so you can "
                    "finish it manually in the browser window, then start it again."
                ),
                machine_state={
                    "reason": f"{primary_blocker.blocker_type}_UNRESOLVED",
                    "blockers": blocker_payload,
                    "context": context,
                    "pause_cycles": pause_cycles - 1,
                },
                ui_state={"requires_user_review": True, "current_step": "blocked"},
                payload={"code": f"{primary_blocker.blocker_type}_UNRESOLVED", "blockers": blocker_payload},
            ).emit()
            return True
        await _surface_browser_for_human(adapter)
        WorkerEvent(
            event_type=EventType.PAUSED,
            run_id=run_id,
            step_id=None,
            severity=Severity.WARN,
            message=f"{primary_blocker.blocker_type} challenge detected during {context}. User action is required before automation can continue.",
            machine_state={"reason": f"{primary_blocker.blocker_type}_DETECTED", "blockers": blocker_payload, "context": context},
            ui_state={"requires_user_review": True, "current_step": "blocked"},
            payload={"blockers": blocker_payload},
        ).emit()
        control = await asyncio.to_thread(wait_for_review_resume, work_dir, run_id=run_id, current_step="blocker_review", context=context)
        if control.command == "CANCEL":
            emit_worker_cancelled(run_id, control, message=f"Worker cancelled by local user while blocked during {context}")
            return True
        WorkerEvent(
            event_type=EventType.RESUMED,
            run_id=run_id,
            step_id=control.step_id,
            severity=Severity.INFO,
            message=f"User marked {primary_blocker.blocker_type} handled; rechecking page state",
            machine_state={"reason": control.reason or "local_user_resolved_blocker", "context": context},
            ui_state={"current_step": "automation"},
            payload={"blocker_type": primary_blocker.blocker_type},
        ).emit()
        active_blockers = _halting_blockers(await adapter.detect_blockers())  # type: ignore[attr-defined]
    return False


def portal_entry_requires_manual_action(
    workflow: PortalWorkflow, action_applied: bool, fields_already_present: bool = False
) -> bool:
    if fields_already_present:
        # The application form is already inline on the page (common on Greenhouse/Lever):
        # there is no "Apply" entry button to click, so do not pause for a manual entry action.
        return False
    return (
        bool(workflow.entry_action_labels)
        and not action_applied
        and workflow.workflow_kind in {"ATS_DIRECT_FORM", "JOB_BOARD_REDIRECT_OR_STEALTH"}
    )


async def pause_for_portal_entry_action(
    adapter: object,
    work_dir: Path,
    run_id: str,
    workflow: PortalWorkflow,
    *,
    context: str,
    action_payload: dict[str, object] | None = None,
) -> bool:
    attempted_labels = list(workflow.entry_action_labels)
    safe_action_payload = action_payload if isinstance(action_payload, dict) else {}
    WorkerEvent(
        event_type=EventType.PAUSED,
        run_id=run_id,
        step_id=None,
        severity=Severity.WARN,
        message=f"{workflow.display_name} requires a manual portal entry action before fields can be trusted.",
        machine_state={
            "reason": "PORTAL_ENTRY_ACTION_REQUIRED",
            "portal_id": workflow.portal_id,
            "workflow_kind": workflow.workflow_kind,
            "context": context,
        },
        ui_state={"requires_user_review": True, "current_step": "portal_entry"},
        payload={
            "portal_id": workflow.portal_id,
            "display_name": workflow.display_name,
            "workflow_kind": workflow.workflow_kind,
            "attempted_labels": attempted_labels,
            "ambiguity_code": safe_action_payload.get("ambiguity_code"),
            "candidate_count": safe_action_payload.get("candidate_count"),
            "candidate_labels": safe_action_payload.get("candidate_labels") if isinstance(safe_action_payload.get("candidate_labels"), list) else [],
            "instructions": "Click the portal apply or start action in the browser, then mark this review handled.",
        },
    ).emit()
    control = await asyncio.to_thread(wait_for_review_resume, work_dir, run_id=run_id, current_step="portal_entry", context=f"{workflow.display_name} portal entry")
    if control.command == "CANCEL":
        emit_worker_cancelled(run_id, control, message=f"Worker cancelled by local user during {workflow.display_name} portal entry")
        return True
    WorkerEvent(
        event_type=EventType.RESUMED,
        run_id=run_id,
        step_id=control.step_id,
        severity=Severity.INFO,
        message=f"User marked {workflow.display_name} portal entry handled; rechecking page state",
        machine_state={
            "reason": control.reason or "local_user_resolved_portal_entry",
            "portal_id": workflow.portal_id,
            "context": context,
        },
        ui_state={"current_step": "automation"},
        payload={"portal_id": workflow.portal_id, "attempted_labels": attempted_labels},
    ).emit()
    blockers = await adapter.detect_blockers()  # type: ignore[attr-defined]
    if blockers:
        return await pause_for_blockers(adapter, work_dir, run_id, blockers, context=f"{context} after manual portal entry")
    return False


async def observe_portal_page_state(
    *,
    adapter: object,
    run_id: str,
    workflow: PortalWorkflow,
    original_url: str,
    context: str,
    field_count: int | None = None,
) -> PortalPageState | None:
    extract_visible_text = adapter.extract_visible_text
    result = await extract_visible_text()
    if not result.ok:
        WorkerEvent(
            event_type=EventType.PORTAL_STATE_OBSERVED,
            run_id=run_id,
            step_id=None,
            severity=Severity.WARN,
            message=f"Could not observe portal state after {context}",
            machine_state={"portal_id": workflow.portal_id, "context": context, "ok": False},
            ui_state={"current_step": "portal_workflow", "requires_user_review": workflow.requires_external_redirect_watch},
            payload={"portal_id": workflow.portal_id, "context": context, **result.payload},
        ).emit()
        return None

    text = str(result.payload.get("text") or "")
    page_state = classify_portal_page_state(
        workflow=workflow,
        original_url=original_url,
        current_url=str(result.payload.get("url") or "") or None,
        title=str(result.payload.get("title") or "") or None,
        text=text[:12000],
        field_count=field_count,
    )
    WorkerEvent(
        event_type=EventType.PORTAL_STATE_OBSERVED,
        run_id=run_id,
        step_id=None,
        severity=Severity.WARN if page_state.requires_review else Severity.INFO,
        message=(
            f"{workflow.display_name} portal state requires user review"
            if page_state.requires_review
            else f"{workflow.display_name} portal state observed"
        ),
        machine_state={
            "portal_id": workflow.portal_id,
            "workflow_kind": workflow.workflow_kind,
            "context": context,
            "requires_review": page_state.requires_review,
        },
        ui_state={"current_step": "portal_workflow", "requires_user_review": page_state.requires_review},
        payload=page_state.to_event_payload(),
    ).emit()
    return page_state


async def capture_timeline_screenshot_if_available(
    *,
    adapter: object,
    work_dir: Path,
    run_id: str,
    screenshot_id: str,
    current_step: str,
) -> None:
    screenshot = getattr(adapter, "screenshot", None)
    if not callable(screenshot):
        return
    screenshot_path = work_dir / "screenshots" / f"{screenshot_id}.png"
    result = await screenshot(screenshot_path)
    if not result.ok or not screenshot_path.exists():
        return
    raw = screenshot_path.read_bytes()
    WorkerEvent(
        event_type=EventType.SCREENSHOT_CAPTURED,
        run_id=run_id,
        step_id=None,
        severity=Severity.INFO,
        message=f"Browser screenshot captured for {current_step}",
        machine_state={"adapter": getattr(adapter, "name", "unknown"), "current_step": current_step},
        ui_state={"current_step": current_step},
        payload={
            "screenshot_id": screenshot_id,
            "local_path": str(screenshot_path),
            "mime_type": str(result.payload.get("mime_type", "image/png")),
            "width": int(result.payload.get("width", 1280)),
            "height": int(result.payload.get("height", 800)),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "captured_at": utc_now(),
        },
    ).emit()


async def pause_for_portal_state_review(
    adapter: object,
    work_dir: Path,
    run_id: str,
    workflow: PortalWorkflow,
    page_state: PortalPageState,
    *,
    context: str,
) -> bool:
    WorkerEvent(
        event_type=EventType.PAUSED,
        run_id=run_id,
        step_id=None,
        severity=Severity.WARN,
        message=f"{workflow.display_name} did not move to a trusted application surface after portal entry.",
        machine_state={
            "reason": "PORTAL_REDIRECT_REVIEW_REQUIRED",
            "portal_id": workflow.portal_id,
            "workflow_kind": workflow.workflow_kind,
            "context": context,
        },
        ui_state={"requires_user_review": True, "current_step": "portal_entry"},
        payload=page_state.to_event_payload(),
    ).emit()
    control = await asyncio.to_thread(wait_for_review_resume, work_dir, run_id=run_id, current_step="portal_entry", context=f"{workflow.display_name} redirect review")
    if control.command == "CANCEL":
        emit_worker_cancelled(run_id, control, message=f"Worker cancelled by local user during {workflow.display_name} redirect review")
        return True
    WorkerEvent(
        event_type=EventType.RESUMED,
        run_id=run_id,
        step_id=control.step_id,
        severity=Severity.INFO,
        message=f"User confirmed {workflow.display_name} portal state; rechecking blockers",
        machine_state={"reason": control.reason or "local_user_confirmed_portal_state", "portal_id": workflow.portal_id, "context": context},
        ui_state={"current_step": "automation"},
        payload={"portal_id": workflow.portal_id},
    ).emit()
    blockers = await adapter.detect_blockers()  # type: ignore[attr-defined]
    if blockers:
        return await pause_for_blockers(adapter, work_dir, run_id, blockers, context=f"{context} after portal state review")
    return False


def required_answer_missing_payload(field: BrowserField) -> dict[str, object]:
    return {
        "field_label": field.label,
        "field_type": field.field_type,
        "selector": field.selector,
        "required": field.required,
        "confidence": field.confidence,
        "metadata": field.metadata,
    }


def upload_kind_for_field(field: BrowserField) -> str | None:
    searchable_parts = [
        field.label,
        str(field.metadata.get("name") or ""),
        str(field.metadata.get("id") or ""),
        str(field.metadata.get("placeholder") or ""),
    ]
    label = normalize_field_label(" ".join(searchable_parts))
    tokens = set(label.split())
    if "cover" in tokens and ("letter" in tokens or "cl" in tokens):
        return "COVER_LETTER"
    if "resume" in tokens or "cv" in tokens or ("curriculum" in tokens and "vitae" in tokens):
        return "RESUME"
    return None


def cover_letter_requirement_from_fields(fields: list[BrowserField]) -> dict[str, object] | None:
    cover_letter_fields: list[dict[str, object]] = []
    for field in fields:
        searchable_parts = [
            field.label,
            str(field.metadata.get("name") or ""),
            str(field.metadata.get("id") or ""),
            str(field.metadata.get("placeholder") or ""),
            str(field.metadata.get("aria_label") or ""),
        ]
        label = normalize_field_label(" ".join(searchable_parts))
        tokens = set(label.split())
        explicit_cover_letter = (
            upload_kind_for_field(field) == "COVER_LETTER"
            or ("covering" in tokens and "letter" in tokens)
            or ("letter" in tokens and "interest" in tokens)
        )
        if not explicit_cover_letter:
            continue
        cover_letter_fields.append(
            {
                "field_label": field.label,
                "field_type": field.field_type,
                "selector": field.selector,
                "required": field.required,
                "confidence": field.confidence,
            }
        )

    if not cover_letter_fields:
        return None

    return {
        "source": "APPLICATION_FORM",
        "required": any(bool(field["required"]) for field in cover_letter_fields),
        "field_count": len(cover_letter_fields),
        "fields": cover_letter_fields,
    }


def emit_cover_letter_requirement_from_fields(run_id: str, fields: list[BrowserField], *, context: str) -> dict[str, object] | None:
    requirement = cover_letter_requirement_from_fields(fields)
    if requirement is None:
        return None

    required = bool(requirement["required"])
    WorkerEvent(
        event_type=EventType.COVER_LETTER_REQUIRED,
        run_id=run_id,
        step_id=None,
        severity=Severity.WARN if required else Severity.INFO,
        message="Application form requires a cover letter" if required else "Application form exposes cover-letter fields",
        machine_state={"source": "APPLICATION_FORM", "required": required, "context": context},
        ui_state={"current_step": "field_review", "requires_user_review": required},
        payload=requirement,
    ).emit()
    return requirement


def accepted_upload_formats(field: BrowserField) -> list[str]:
    accept = str(field.metadata.get("accept") or "").lower()
    if not accept or accept.strip() in {"*", "*/*"}:
        return ["PDF", "DOCX"]
    formats: list[str] = []
    if "pdf" in accept:
        formats.append("PDF")
    if "docx" in accept or ".doc" in accept or "msword" in accept or "wordprocessingml" in accept:
        formats.append("DOCX")
    if "text/plain" in accept or ".txt" in accept:
        formats.append("TXT")
    return formats or ["PDF", "DOCX"]


def generated_file_value(generated_file: dict[str, object], key: str) -> object:
    camel_key = key[0].lower() + "".join(part.capitalize() for part in key.split("_"))[1:] if "_" in key else key
    return generated_file.get(key) or generated_file.get(camel_key)


def field_file_count(field: BrowserField) -> int:
    value = field.metadata.get("file_count")
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 0


def select_generated_file_for_upload(field: BrowserField, generated_files: object) -> dict[str, object] | None:
    if not isinstance(generated_files, list):
        return None
    file_kind = upload_kind_for_field(field)
    if file_kind is None:
        return None
    accepted_formats = accepted_upload_formats(field)
    preference = {format_name: index for index, format_name in enumerate(["PDF", "DOCX", "TXT"])}
    candidates: list[dict[str, object]] = []
    for generated_file in generated_files:
        if not isinstance(generated_file, dict):
            continue
        if str(generated_file_value(generated_file, "file_kind") or "").upper() != file_kind:
            continue
        format_name = str(generated_file_value(generated_file, "format") or "").upper()
        local_path = generated_file_value(generated_file, "local_path")
        upload_status = str(generated_file_value(generated_file, "upload_status") or "NOT_UPLOADED").upper()
        if format_name not in accepted_formats or upload_status == "UPLOADED":
            continue
        if not isinstance(local_path, str) or not local_path.strip():
            continue
        if not Path(local_path).is_file():
            continue
        candidates.append(generated_file)
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: preference.get(str(generated_file_value(item, "format") or "").upper(), 99))[0]


def required_document_missing_payload(field: BrowserField, generated_files: object) -> dict[str, object]:
    return {
        "field_label": field.label,
        "field_type": field.field_type,
        "selector": field.selector,
        "required": field.required,
        "file_kind": upload_kind_for_field(field),
        "existing_file_count": field_file_count(field),
        "accepted_formats": accepted_upload_formats(field),
        "generated_files": generated_files if isinstance(generated_files, list) else [],
    }


def emit_portal_workflow_selected(
    run_id: str,
    workflow: PortalWorkflow,
    *,
    adapter_name: str,
    adapter_candidates: tuple[str, ...] | None = None,
) -> None:
    WorkerEvent(
        event_type=EventType.PORTAL_WORKFLOW_SELECTED,
        run_id=run_id,
        step_id=None,
        severity=Severity.INFO,
        message=f"Portal workflow selected: {workflow.display_name}",
        machine_state={
            "portal_id": workflow.portal_id,
            "workflow_kind": workflow.workflow_kind,
            "adapter": adapter_name,
            "requires_high_stealth": workflow.requires_high_stealth,
            "adapter_candidates": list(adapter_candidates or (adapter_name,)),
        },
        ui_state={"current_step": "portal_workflow"},
        payload={**workflow.to_event_payload(), "adapter": adapter_name, "adapter_candidates": list(adapter_candidates or (adapter_name,))},
    ).emit()


async def launch_browser_for_workflow(
    *,
    run_id: str,
    workflow: PortalWorkflow,
    user_data_dir: Path,
    preferred_adapter_name: str | None,
) -> tuple[BrowserAdapter | None, BrowserStepResult | None, list[dict[str, object]]]:
    attempts: list[dict[str, object]] = []
    for adapter_name in adapter_candidates_for_workflow(workflow, preferred_adapter_name):
        adapter = create_browser_adapter(adapter_name)
        launch = await adapter.launch(run_id=run_id, user_data_dir=user_data_dir)
        attempts.append(
            {
                "adapter": adapter.name,
                "ok": bool(getattr(launch, "ok", False)),
                "message": str(getattr(launch, "message", "")),
                "payload": getattr(launch, "payload", {}),
            }
        )
        if getattr(launch, "ok", False):
            return adapter, launch, attempts
        await adapter.close()
    return None, None, attempts


async def execute_portal_entry_action(
    *,
    adapter: object,
    workflow: PortalWorkflow,
    run_id: str,
    context: str,
) -> BrowserStepResult:
    labels = list(workflow.entry_action_labels)
    if not labels:
        return BrowserStepResult(False, "no portal entry labels configured", {"attempted_labels": []})
    click_by_text = adapter.click_by_text
    result = await click_by_text(labels)
    WorkerEvent(
        event_type=EventType.PORTAL_ACTION_APPLIED,
        run_id=run_id,
        step_id=None,
        severity=Severity.INFO if result.ok else Severity.WARN,
        message=(
            f"{workflow.display_name} portal entry action applied"
            if result.ok
            else f"{workflow.display_name} portal entry action was not applied automatically"
        ),
        machine_state={
            "portal_id": workflow.portal_id,
            "workflow_kind": workflow.workflow_kind,
            "context": context,
            "ok": result.ok,
        },
        ui_state={"current_step": "portal_workflow", "requires_user_review": not result.ok and workflow.workflow_kind == "ATS_DIRECT_FORM"},
        payload={
            "portal_id": workflow.portal_id,
            "workflow_kind": workflow.workflow_kind,
            "context": context,
            "attempted_labels": labels,
            **result.payload,
        },
    ).emit()
    return result


@dataclass(frozen=True, slots=True)
class PortalPageFingerprint:
    """Enough page identity to tell "we moved on" from "the click did nothing"."""

    url: str
    title: str
    text: str
    text_digest: str
    selectors: frozenset[str]


async def capture_portal_page_fingerprint(adapter: object) -> PortalPageFingerprint | None:
    """Reads the current page identity, or None when the page cannot be read.

    None means "cannot tell" and must never be read as "unchanged" - a wrong
    blocked verdict would stall a run that is actually progressing fine.
    """
    try:
        result = await adapter.extract_visible_text()  # type: ignore[attr-defined]
        fields = await adapter.detect_fields()  # type: ignore[attr-defined]
    except Exception:
        return None
    if not result.ok:
        return None
    text = str(result.payload.get("text") or "")
    return PortalPageFingerprint(
        url=str(result.payload.get("url") or ""),
        title=str(result.payload.get("title") or ""),
        text=text,
        text_digest=hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest(),
        selectors=frozenset(str(field.selector or field.field_id) for field in fields),
    )


def portal_page_changed(before: PortalPageFingerprint | None, after: PortalPageFingerprint | None) -> bool:
    """True unless we can positively show the page stayed put.

    URL, title and the set of field selectors are the stable signals: a real
    wizard step carries different inputs. Visible text alone is too noisy to
    judge on (timers, toasts, character counters), so it only decides when the
    page has no fields at all to compare.
    """
    if before is None or after is None:
        return True
    if before.url != after.url or before.title != after.title:
        return True
    if before.selectors != after.selectors:
        return True
    if not before.selectors and not after.selectors:
        return before.text_digest != after.text_digest
    return False


PAGE_CHANGE_TIMEOUT_S = 8.0
PAGE_CHANGE_POLL_INTERVAL_S = 0.5


async def wait_for_portal_page_change(
    adapter: object,
    before: PortalPageFingerprint | None,
    *,
    timeout_s: float = PAGE_CHANGE_TIMEOUT_S,
    poll_interval_s: float = PAGE_CHANGE_POLL_INTERVAL_S,
    sleep: object = asyncio.sleep,
    clock: object = time.monotonic,
) -> PortalPageFingerprint | None:
    """Polls until the page differs from `before`, or the timeout elapses.

    Returns the last fingerprint read either way, so the caller can diff the
    text of a page that never moved and surface the portal's own error copy.
    """
    started = clock()
    after = await capture_portal_page_fingerprint(adapter)
    while portal_page_changed(before, after) is False and clock() - started < timeout_s:
        await sleep(poll_interval_s)
        after = await capture_portal_page_fingerprint(adapter)
    return after


MAX_VALIDATION_EXCERPT_LINES = 8
MAX_VALIDATION_EXCERPT_CHARS = 200


def new_visible_lines(before: PortalPageFingerprint | None, after: PortalPageFingerprint | None) -> list[str]:
    """Lines present after the click but not before - usually the validation copy."""
    if before is None or after is None:
        return []
    previous = {line.strip() for line in before.text.splitlines() if line.strip()}
    fresh = [line.strip() for line in after.text.splitlines() if line.strip() and line.strip() not in previous]
    return [line[:MAX_VALIDATION_EXCERPT_CHARS] for line in fresh[:MAX_VALIDATION_EXCERPT_LINES]]


async def attempt_safe_step_progression(
    *,
    adapter: object,
    work_dir: Path,
    run_id: str,
    workflow: PortalWorkflow,
    context: str,
    step_index: int,
    page_change_timeout_s: float = PAGE_CHANGE_TIMEOUT_S,
) -> str:
    click_by_text = adapter.click_by_text
    labels = list(progression_labels_for_workflow(workflow))
    before_click = await capture_portal_page_fingerprint(adapter)
    result = await click_by_text(labels)
    message = str(result.payload.get("message") or getattr(result, "message", ""))
    if not result.ok and message == "no matching safe portal action was found":
        return "not_found"
    if result.ok and result.payload.get("action") != "click_by_text":
        return "not_found"
    if result.ok:
        WorkerEvent(
            event_type=EventType.PORTAL_ACTION_APPLIED,
            run_id=run_id,
            step_id=None,
            severity=Severity.INFO,
            message="Application step progression action applied",
            machine_state={
                "portal_id": workflow.portal_id,
                "workflow_kind": workflow.workflow_kind,
                "context": context,
                "action_role": "STEP_PROGRESSION",
                "step_index": step_index,
                "ok": True,
            },
            ui_state={"current_step": "portal_step"},
            payload={
                "portal_id": workflow.portal_id,
                "workflow_kind": workflow.workflow_kind,
                "context": context,
                "action_role": "STEP_PROGRESSION",
                "step_index": step_index,
                "attempted_labels": labels,
                **result.payload,
            },
        ).emit()
        blockers = await adapter.detect_blockers()  # type: ignore[attr-defined]
        if blockers and await pause_for_blockers(adapter, work_dir, run_id, blockers, context=f"{context} step progression"):
            return "cancelled"

        # A successful click is not a successful step. Portals answer an invalid
        # form by re-rendering the same page with error copy, and treating that
        # as progress makes the worker march through phantom steps and then ask
        # for a submit button that was never there.
        after_click = await wait_for_portal_page_change(adapter, before_click, timeout_s=page_change_timeout_s)
        if not portal_page_changed(before_click, after_click):
            validation_lines = new_visible_lines(before_click, after_click)
            WorkerEvent(
                event_type=EventType.PAUSED,
                run_id=run_id,
                step_id=None,
                severity=Severity.WARN,
                message="The portal stayed on the same step after the progression click",
                machine_state={
                    "reason": "PORTAL_STEP_DID_NOT_ADVANCE",
                    "portal_id": workflow.portal_id,
                    "workflow_kind": workflow.workflow_kind,
                    "context": context,
                    "action_role": "STEP_PROGRESSION",
                    "step_index": step_index,
                    "validation_line_count": len(validation_lines),
                },
                ui_state={"requires_user_review": True, "current_step": "portal_step"},
                payload={
                    "portal_id": workflow.portal_id,
                    "workflow_kind": workflow.workflow_kind,
                    "action_role": "STEP_PROGRESSION",
                    "step_index": step_index,
                    "attempted_labels": labels,
                    "validation_messages": validation_lines,
                    "instructions": "The portal rejected this step. Resolve the highlighted fields in the browser, then resume.",
                },
            ).emit()
            return "blocked"
        return "advanced"

    WorkerEvent(
        event_type=EventType.PAUSED,
        run_id=run_id,
        step_id=None,
        severity=Severity.WARN,
        message="Application step progression needs manual review before automation can continue.",
        machine_state={
            "reason": "PORTAL_STEP_ACTION_REQUIRED",
            "portal_id": workflow.portal_id,
            "workflow_kind": workflow.workflow_kind,
            "context": context,
            "action_role": "STEP_PROGRESSION",
            "step_index": step_index,
        },
        ui_state={"requires_user_review": True, "current_step": "portal_step"},
        payload={
            "portal_id": workflow.portal_id,
            "workflow_kind": workflow.workflow_kind,
            "action_role": "STEP_PROGRESSION",
            "step_index": step_index,
            "attempted_labels": labels,
            "instructions": "Click the reviewed non-final Next, Continue, or Review action in the browser, then mark this review handled.",
            **result.payload,
        },
    ).emit()
    control = await asyncio.to_thread(wait_for_review_resume, work_dir, run_id=run_id, current_step="portal_step", context="portal step progression")
    if control.command == "CANCEL":
        emit_worker_cancelled(run_id, control, message="Worker cancelled by local user during portal step progression")
        return "cancelled"
    WorkerEvent(
        event_type=EventType.RESUMED,
        run_id=run_id,
        step_id=control.step_id,
        severity=Severity.INFO,
        message="User marked portal step progression handled; rechecking page state",
        machine_state={
            "reason": control.reason or "local_user_resolved_portal_step",
            "portal_id": workflow.portal_id,
            "context": context,
            "action_role": "STEP_PROGRESSION",
            "step_index": step_index,
        },
        ui_state={"current_step": "automation"},
        payload={"portal_id": workflow.portal_id, "action_role": "STEP_PROGRESSION", "step_index": step_index},
    ).emit()
    blockers = await adapter.detect_blockers()  # type: ignore[attr-defined]
    if blockers and await pause_for_blockers(adapter, work_dir, run_id, blockers, context=f"{context} after manual step progression"):
        return "cancelled"
    return "advanced"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="applyocalypse-worker")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--job-url")
    parser.add_argument("--job-text-file")
    parser.add_argument("--job-metadata-file")
    parser.add_argument("--profile-json-file")
    parser.add_argument("--cover-letter-sample-file")
    parser.add_argument("--output-dir")
    parser.add_argument("--work-dir", required=True)
    return parser


def page_text_ready(navigation: object) -> bool:
    """False when the adapter's readiness poll timed out before page text stabilized."""
    payload = getattr(navigation, "payload", None)
    readiness = payload.get("page_text") if isinstance(payload, dict) else None
    if isinstance(readiness, dict):
        return bool(readiness.get("ready", True))
    return True


async def run_url_observation_flow(
    *,
    run_id: str,
    job_url: str,
    work_dir: Path,
    canonical_profile: dict[str, object],
    adapter_name: str = "nodriver",
) -> UrlObservationResult:
    workflow = workflow_for_url(job_url)
    adapter_candidates = adapter_candidates_for_workflow(workflow, adapter_name)
    user_data_dir = work_dir / "browser-profile"
    screenshot_dir = work_dir / "screenshots"
    emit_portal_workflow_selected(run_id, workflow, adapter_name=adapter_candidates[0], adapter_candidates=adapter_candidates)
    adapter, launch, launch_attempts = await launch_browser_for_workflow(
        run_id=run_id,
        workflow=workflow,
        user_data_dir=user_data_dir,
        preferred_adapter_name=adapter_name,
    )
    if adapter is None or launch is None:
        WorkerEvent(
            event_type=EventType.PAUSED,
            run_id=run_id,
            step_id=None,
            severity=Severity.WARN,
            message="Browser automation paused because no configured browser engine is available",
            machine_state={"reason": "BROWSER_ENGINE_UNAVAILABLE", "adapter_candidates": list(adapter_candidates)},
            ui_state={"requires_user_review": True},
            payload={"attempted_adapters": launch_attempts},
        ).emit()
        return UrlObservationResult(should_stop=True)

    WorkerEvent(
        event_type=EventType.BROWSER_LAUNCHED,
        run_id=run_id,
        step_id=None,
        severity=Severity.INFO,
        message=f"{adapter.name} browser launched with run-scoped session isolation",
        machine_state={"adapter": adapter.name, "user_data_dir": str(user_data_dir)},
        ui_state={"current_step": "browser_launch"},
        payload={**launch.payload, "attempted_adapters": launch_attempts},
    ).emit()
    if await handle_runtime_control(work_dir, run_id, context="browser launch"):
        await adapter.close()
        return UrlObservationResult(should_stop=True)

    navigation = await adapter.open_url(job_url)
    if not navigation.ok:
        WorkerEvent(
            event_type=EventType.PAUSED,
            run_id=run_id,
            step_id=None,
            severity=Severity.WARN,
            message="Browser automation paused because the job page could not be opened",
            machine_state={"reason": "NAVIGATION_FAILED"},
            ui_state={"requires_user_review": True},
            payload=navigation.payload,
        ).emit()
        await adapter.close()
        return UrlObservationResult(should_stop=True)

    page_ready = page_text_ready(navigation)
    WorkerEvent(
        event_type=EventType.PAGE_NAVIGATED,
        run_id=run_id,
        step_id=None,
        severity=Severity.INFO if page_ready else Severity.WARN,
        message=(
            "Application page navigated"
            if page_ready
            else "Application page navigated, but its text did not stabilize; extracted content may be incomplete"
        ),
        machine_state={"url": job_url, "page_text_ready": page_ready},
        ui_state={"current_step": "page_review"},
        payload=navigation.payload,
    ).emit()
    if await handle_runtime_control(work_dir, run_id, context="page navigation"):
        await adapter.close()
        return UrlObservationResult(should_stop=True)

    artifact_dir = work_dir / "browser-artifacts"
    dom_snapshot_path = artifact_dir / "dom-snapshot.json"
    dom_snapshot = await adapter.capture_dom_snapshot(dom_snapshot_path)
    if dom_snapshot.ok and dom_snapshot_path.exists():
        WorkerEvent(
            event_type=EventType.BROWSER_ARTIFACT_CAPTURED,
            run_id=run_id,
            step_id=None,
            severity=Severity.INFO,
            message="DOM snapshot captured for automation diagnostics",
            machine_state={"adapter": adapter.name, "artifact_type": "DOM_SNAPSHOT"},
            ui_state={"current_step": "page_review"},
            payload={
                "artifact_id": f"{run_id}:dom-snapshot",
                "artifact_type": "DOM_SNAPSHOT",
                "local_path": str(dom_snapshot_path),
                "mime_type": str(dom_snapshot.payload.get("mime_type", "application/json")),
                "metadata": dom_snapshot.payload.get("metadata", {}),
                "captured_at": utc_now(),
            },
        ).emit()
    if await handle_runtime_control(work_dir, run_id, context="page diagnostics"):
        await adapter.close()
        return UrlObservationResult(should_stop=True)

    extracted_text = await adapter.extract_visible_text()
    if not extracted_text.ok:
        WorkerEvent(
            event_type=EventType.PAUSED,
            run_id=run_id,
            step_id=None,
            severity=Severity.WARN,
            message="Browser automation paused because the job description text could not be extracted",
            machine_state={"reason": "JD_SCRAPE_FAILED", "adapter": adapter.name},
            ui_state={"requires_user_review": True, "current_step": "scraping"},
            payload=extracted_text.payload,
        ).emit()
        await adapter.close()
        return UrlObservationResult(should_stop=True)

    job_text_file = work_dir / "job-description-scraped.txt"
    job_text = str(extracted_text.payload.get("text") or "")
    job_text_file.write_text(job_text, encoding="utf-8")
    scraped_url = str(extracted_text.payload.get("url") or job_url)
    WorkerEvent(
        event_type=EventType.JD_SCRAPE_COMPLETED,
        run_id=run_id,
        step_id=None,
        severity=Severity.INFO,
        message="Job description extracted from browser-visible page text",
        machine_state={"source": "SCRAPED", "adapter": adapter.name, "url": scraped_url},
        ui_state={"current_step": "analyzing"},
        payload={
            "text_length": int(extracted_text.payload.get("text_length") or len(job_text)),
            "source_text_path": str(job_text_file),
            "url": scraped_url,
            "title": extracted_text.payload.get("title"),
            "jd_source": "SCRAPED",
        },
    ).emit()
    if await handle_runtime_control(work_dir, run_id, context="job description extraction"):
        await adapter.close()
        return UrlObservationResult(should_stop=True)

    screenshot_path = screenshot_dir / "page-review.png"
    screenshot = await adapter.screenshot(screenshot_path)
    if screenshot.ok and screenshot_path.exists():
        raw = screenshot_path.read_bytes()
        WorkerEvent(
            event_type=EventType.SCREENSHOT_CAPTURED,
            run_id=run_id,
            step_id=None,
            severity=Severity.INFO,
            message="Browser screenshot captured for review timeline",
            machine_state={"adapter": adapter.name},
            ui_state={"current_step": "page_review"},
            payload={
                "screenshot_id": "page-review",
                "local_path": str(screenshot_path),
                "mime_type": str(screenshot.payload.get("mime_type", "image/png")),
                "width": int(screenshot.payload.get("width", 1280)),
                "height": int(screenshot.payload.get("height", 800)),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "captured_at": utc_now(),
            },
        ).emit()
    if await handle_runtime_control(work_dir, run_id, context="screenshot capture"):
        await adapter.close()
        return UrlObservationResult(should_stop=True)

    blockers = await adapter.detect_blockers()
    if blockers:
        if await pause_for_blockers(adapter, work_dir, run_id, blockers, context="page review"):
            await adapter.close()
            return UrlObservationResult(should_stop=True, job_text_file=job_text_file, scraped_url=scraped_url)

    portal_action = await execute_portal_entry_action(adapter=adapter, workflow=workflow, run_id=run_id, context="observation")
    if await handle_runtime_control(work_dir, run_id, context="portal entry action"):
        await adapter.close()
        return UrlObservationResult(should_stop=True, job_text_file=job_text_file, scraped_url=scraped_url)
    entry_fields = await adapter.detect_fields()  # type: ignore[attr-defined]
    if portal_entry_requires_manual_action(workflow, portal_action.ok, fields_already_present=len(entry_fields) > 0):
        if await pause_for_portal_entry_action(adapter, work_dir, run_id, workflow, context="observation", action_payload=portal_action.payload):
            await adapter.close()
            return UrlObservationResult(should_stop=True, job_text_file=job_text_file, scraped_url=scraped_url)
    blockers = await adapter.detect_blockers()
    if blockers:
        if await pause_for_blockers(adapter, work_dir, run_id, blockers, context="portal entry action"):
            await adapter.close()
            return UrlObservationResult(should_stop=True, job_text_file=job_text_file, scraped_url=scraped_url)

    if await handle_runtime_control(work_dir, run_id, context="field detection"):
        await adapter.close()
        return UrlObservationResult(should_stop=True, job_text_file=job_text_file, scraped_url=scraped_url)
    fields = await adapter.detect_fields()
    page_state = await observe_portal_page_state(
        adapter=adapter,
        run_id=run_id,
        workflow=workflow,
        original_url=job_url,
        context="post_entry_observation",
        field_count=len(fields),
    )
    if page_state and page_state.requires_review:
        if await pause_for_portal_state_review(adapter, work_dir, run_id, workflow, page_state, context="post_entry_observation"):
            await adapter.close()
            return UrlObservationResult(should_stop=True, job_text_file=job_text_file, scraped_url=scraped_url)
        fields = await adapter.detect_fields()
    emit_cover_letter_requirement_from_fields(run_id, fields, context="post_entry_observation")
    for field in fields:
        if await handle_runtime_control(work_dir, run_id, context="field proposal"):
            await adapter.close()
            return UrlObservationResult(should_stop=True, job_text_file=job_text_file, scraped_url=scraped_url)
        field_payload = {
            "field_label": field.label,
            "field_type": field.field_type,
            "selector": field.selector,
            "required": field.required,
            "confidence": field.confidence,
            "source": "DOM",
        }
        WorkerEvent(
            event_type=EventType.FIELD_DETECTED,
            run_id=run_id,
            step_id=None,
            severity=Severity.INFO,
            message=f"Detected application field: {field.label}",
            machine_state={"selector": field.selector, "required": field.required},
            ui_state={"current_step": "field_review"},
            payload=field_payload,
        ).emit()
        proposed_answer = proposed_answer_for_browser_field(field, canonical_profile, jd_text=job_text)
        WorkerEvent(
            event_type=EventType.FIELD_VALUE_PROPOSED,
            run_id=run_id,
            step_id=None,
            severity=Severity.WARN if proposed_answer.requires_review else Severity.INFO,
            message=f"Proposed answer for {field.label}",
            machine_state={"selector": field.selector, "required": field.required},
            ui_state={"current_step": "field_review", "requires_user_review": proposed_answer.requires_review},
            payload={
                **field_payload,
                "proposed_value": proposed_answer.proposed_value,
                "confidence": proposed_answer.confidence,
                "source": proposed_answer.source,
                "requires_review": proposed_answer.requires_review,
            },
        ).emit()

    WorkerEvent(
        event_type=EventType.PAUSED,
        run_id=run_id,
        step_id=None,
        severity=Severity.WARN,
        message="Browser automation paused for user review before filling fields",
        machine_state={"reason": "FIELD_REVIEW_REQUIRED", "detected_field_count": len(fields)},
        ui_state={"requires_user_review": True},
        payload={"detected_field_count": len(fields)},
    ).emit()
    if os.getenv("APPLYO_WORKER_WAIT_FOR_REVIEW") == "1":
        control = await asyncio.to_thread(wait_for_review_resume, work_dir, run_id=run_id, current_step="field_review", context="initial browser field review")
        if control.command == "CANCEL":
            emit_worker_cancelled(run_id, control, message="Worker cancelled by local user during initial browser field review")
            await adapter.close()
            return UrlObservationResult(should_stop=True, job_text_file=job_text_file, scraped_url=scraped_url)
        WorkerEvent(
            event_type=EventType.RESUMED,
            run_id=run_id,
            step_id=control.step_id,
            severity=Severity.INFO,
            message="Initial browser field review resolved; continuing document generation",
            machine_state={"reason": control.reason or "local_user_resolved_field_review"},
            ui_state={"current_step": "document_generation"},
            payload={"detected_field_count": len(fields)},
        ).emit()
    await adapter.close()
    return UrlObservationResult(should_stop=False, job_text_file=job_text_file, scraped_url=scraped_url)


async def run_browser_apply_after_review(
    *,
    run_id: str,
    job_url: str,
    work_dir: Path,
    adapter_name: str,
    control: WorkerControl,
) -> None:
    workflow = workflow_for_url(job_url)
    adapter_candidates = adapter_candidates_for_workflow(workflow, adapter_name)
    user_data_dir = work_dir / "browser-profile"
    emit_portal_workflow_selected(run_id, workflow, adapter_name=adapter_candidates[0], adapter_candidates=adapter_candidates)
    adapter, launch, launch_attempts = await launch_browser_for_workflow(
        run_id=run_id,
        workflow=workflow,
        user_data_dir=user_data_dir,
        preferred_adapter_name=adapter_name,
    )
    if adapter is None or launch is None:
        WorkerEvent(
            event_type=EventType.PAUSED,
            run_id=run_id,
            step_id=None,
            severity=Severity.WARN,
            message="Browser automation paused because no configured browser engine is available",
            machine_state={"reason": "BROWSER_ENGINE_UNAVAILABLE", "adapter_candidates": list(adapter_candidates)},
            ui_state={"requires_user_review": True},
            payload={"attempted_adapters": launch_attempts},
        ).emit()
        return

    WorkerEvent(
        event_type=EventType.BROWSER_LAUNCHED,
        run_id=run_id,
        step_id=None,
        severity=Severity.INFO,
        message=f"{adapter.name} browser relaunched for approved field application",
        machine_state={"adapter": adapter.name, "user_data_dir": str(user_data_dir)},
        ui_state={"current_step": "automation"},
        payload={**launch.payload, "attempted_adapters": launch_attempts},
    ).emit()
    if await handle_runtime_control(work_dir, run_id, context="approved automation browser launch"):
        await adapter.close()
        return

    navigation = await adapter.open_url(job_url)
    if not navigation.ok:
        WorkerEvent(
            event_type=EventType.PAUSED,
            run_id=run_id,
            step_id=None,
            severity=Severity.WARN,
            message="Browser automation paused because the application page could not be reopened",
            machine_state={"reason": "NAVIGATION_FAILED", "adapter": adapter.name},
            ui_state={"requires_user_review": True},
            payload=navigation.payload,
        ).emit()
        await adapter.close()
        return

    reopened_ready = page_text_ready(navigation)
    WorkerEvent(
        event_type=EventType.PAGE_NAVIGATED,
        run_id=run_id,
        step_id=None,
        severity=Severity.INFO if reopened_ready else Severity.WARN,
        message=(
            "Application page reopened for approved field application"
            if reopened_ready
            else "Application page reopened, but its text did not stabilize; field detection may be incomplete"
        ),
        machine_state={"url": job_url, "page_text_ready": reopened_ready},
        ui_state={"current_step": "automation"},
        payload=navigation.payload,
    ).emit()
    await capture_timeline_screenshot_if_available(
        adapter=adapter,
        work_dir=work_dir,
        run_id=run_id,
        screenshot_id="approved-application-reopened",
        current_step="automation",
    )
    if await handle_runtime_control(work_dir, run_id, context="approved automation navigation"):
        await adapter.close()
        return

    blockers = await adapter.detect_blockers()
    if blockers:
        if await pause_for_blockers(adapter, work_dir, run_id, blockers, context="approved field application"):
            await adapter.close()
            return

    if await handle_runtime_control(work_dir, run_id, context="pre-fill review"):
        await adapter.close()
        return
    portal_action = await execute_portal_entry_action(adapter=adapter, workflow=workflow, run_id=run_id, context="apply_after_review")
    if await handle_runtime_control(work_dir, run_id, context="approved portal entry action"):
        await adapter.close()
        return
    entry_fields = await adapter.detect_fields()  # type: ignore[attr-defined]
    if portal_entry_requires_manual_action(workflow, portal_action.ok, fields_already_present=len(entry_fields) > 0):
        if await pause_for_portal_entry_action(adapter, work_dir, run_id, workflow, context="apply_after_review", action_payload=portal_action.payload):
            await adapter.close()
            return
    blockers = await adapter.detect_blockers()
    if blockers:
        if await pause_for_blockers(adapter, work_dir, run_id, blockers, context="approved portal entry action"):
            await adapter.close()
            return

    approved_answers = control.payload.get("approvedAnswers") or control.payload.get("approved_answers")
    generated_files = control.payload.get("generatedFiles") or control.payload.get("generated_files")
    auto_submit_enabled = control_auto_submit_enabled(control)
    if await handle_runtime_control(work_dir, run_id, context="approved field detection"):
        await adapter.close()
        return
    fields = await adapter.detect_fields()
    page_state = await observe_portal_page_state(
        adapter=adapter,
        run_id=run_id,
        workflow=workflow,
        original_url=job_url,
        context="approved_field_detection",
        field_count=len(fields),
    )
    if page_state and page_state.requires_review:
        if await pause_for_portal_state_review(adapter, work_dir, run_id, workflow, page_state, context="approved_field_detection"):
            await adapter.close()
            return
        fields = await adapter.detect_fields()
    upload_attempt = 0
    progression_step_index = 0
    blocked_progression_attempts = 0
    uploads_settled = False
    # How many pages this particular portal is expected to have. One global cap of 20
    # was both too generous for a one-page Lever form and arbitrary for a Workday
    # wizard, so the number now comes from the portal's own adapter plan.
    runtime_policy = portal_runtime_policy_for_workflow(workflow)
    # (generated file id, selector) pairs already uploaded. Re-reading the page after the
    # portal parses the resume would otherwise attach the same file a second time, and
    # Workday's attachment list appends rather than replaces.
    uploaded_document_targets: set[tuple[str, str]] = set()
    # Track which required-but-unanswered fields the user has already been shown, so we
    # present them ONCE. If a resume surfaces no NEW missing field, we stop re-pausing and
    # try to advance the wizard instead; the user fills any leftover blanks in the visible
    # browser. This prevents the infinite FIELD_REVIEW loop on fields that have no profile
    # value (Country, LinkedIn, work-auth, EEO, ...).
    presented_missing_answer_keys: set[str] = set()
    while True:
        if upload_attempt > 0:
            if await handle_runtime_control(work_dir, run_id, context="required document retry field detection"):
                await adapter.close()
                return
            fields = await adapter.detect_fields()
        cl_requirement = emit_cover_letter_requirement_from_fields(run_id, fields, context="approved_field_detection")
        if (
            cl_requirement is not None
            and cl_requirement.get("required")
            and not any(
                str(generated_file_value(f, "file_kind") or "").upper() == "COVER_LETTER"
                for f in (generated_files if isinstance(generated_files, list) else [])
            )
        ):
            lazy_cl = await _lazy_generate_cover_letter_for_portal(
                run_id=run_id,
                work_dir=work_dir,
                output_dir=work_dir,
            )
            if lazy_cl is not None:
                generated_files = [*(generated_files if isinstance(generated_files, list) else []), lazy_cl]
        missing_required_documents: list[dict[str, object]] = []
        missing_required_answers: list[dict[str, object]] = []

        # Uploads run first, and once, before anything is typed. Workday and
        # several other portals parse the resume server-side and repopulate
        # name, email and experience seconds after the file lands, silently
        # overwriting whatever was written in the same pass. So upload, wait for
        # the form to react, and restart the pass against a freshly read form.
        upload_fields = [field for field in fields if field.field_type == "file"]
        value_fields = [field for field in fields if field.field_type != "file"]
        before_uploads = await capture_portal_page_fingerprint(adapter) if upload_fields and not uploads_settled else None
        restart_after_uploads = False

        for index, field in enumerate(upload_fields + value_fields):
            if index == len(upload_fields) and before_uploads is not None:
                uploads_settled = True
                await wait_for_portal_page_change(adapter, before_uploads, timeout_s=RESUME_PARSE_SETTLE_S)
                restart_after_uploads = True
                upload_attempt += 1
                break
            if await handle_runtime_control(work_dir, run_id, context=f"field application: {field.label}"):
                await adapter.close()
                return
            if field.field_type == "file":
                generated_file = select_generated_file_for_upload(field, generated_files)
                if generated_file is None:
                    existing_file_count = field_file_count(field)
                    if existing_file_count > 0:
                        WorkerEvent(
                            event_type=EventType.FILE_UPLOADED,
                            run_id=run_id,
                            step_id=None,
                            severity=Severity.INFO,
                            message=f"Detected user-selected upload for {field.label}",
                            machine_state={"selector": field.selector, "field_type": field.field_type, "source": "MANUAL_BROWSER_UPLOAD"},
                            ui_state={"current_step": "file_upload"},
                            payload={
                                "field_label": field.label,
                                "field_type": field.field_type,
                                "selector": field.selector,
                                "existing_file_count": existing_file_count,
                                "source": "MANUAL_BROWSER_UPLOAD",
                            },
                        ).emit()
                        continue
                    missing_payload = required_document_missing_payload(field, generated_files)
                    if field.required:
                        missing_required_documents.append(missing_payload)
                    WorkerEvent(
                        event_type=EventType.USER_REVIEW_REQUIRED,
                        run_id=run_id,
                        step_id=None,
                        severity=Severity.WARN,
                        message=f"File upload field requires user review: {field.label}",
                        machine_state={"selector": field.selector, "field_type": field.field_type},
                        ui_state={"requires_user_review": True, "current_step": "file_upload"},
                        payload=missing_payload,
                    ).emit()
                    continue

                upload_target = (
                    str(generated_file_value(generated_file, "id") or ""),
                    field.selector or field.field_id,
                )
                # Only skip when the field still reports the file we put there. If the
                # portal dropped it during a re-render, uploading again is the fix.
                if upload_target in uploaded_document_targets and field_file_count(field) > 0:
                    continue

                local_path = Path(str(generated_file_value(generated_file, "local_path")))
                result = await adapter.upload_file(field, local_path)
                if result.ok:
                    uploaded_document_targets.add(upload_target)
                    WorkerEvent(
                        event_type=EventType.FILE_UPLOADED,
                        run_id=run_id,
                        step_id=None,
                        severity=Severity.INFO,
                        message=f"Uploaded reviewed document to {field.label}",
                        machine_state={"selector": field.selector, "field_type": field.field_type},
                        ui_state={"current_step": "file_upload"},
                        payload={
                            "generated_file_id": generated_file_value(generated_file, "id"),
                            "file_kind": generated_file_value(generated_file, "file_kind"),
                            "format": generated_file_value(generated_file, "format"),
                            "filename": generated_file_value(generated_file, "filename"),
                            "local_path": str(local_path),
                            "field_label": field.label,
                            "field_type": field.field_type,
                            "selector": field.selector,
                        },
                    ).emit()
                else:
                    WorkerEvent(
                        event_type=EventType.USER_REVIEW_REQUIRED,
                        run_id=run_id,
                        step_id=None,
                        severity=Severity.WARN,
                        message=f"Could not upload reviewed document to {field.label}",
                        machine_state={"selector": field.selector, "field_type": field.field_type},
                        ui_state={"requires_user_review": True, "current_step": "file_upload"},
                        payload={
                            "field_label": field.label,
                            "field_type": field.field_type,
                            "local_path": str(local_path),
                            **result.payload,
                        },
                    ).emit()
                continue

            if field.metadata.get("requires_human_label_review"):
                # The page never gave this control a label; detection invented one
                # so the field would not silently vanish. Matching an approved
                # answer against an invented label is a guess, and a wrong guess
                # writes a real value into a box nobody has identified.
                WorkerEvent(
                    event_type=EventType.USER_REVIEW_REQUIRED,
                    run_id=run_id,
                    step_id=None,
                    severity=Severity.WARN,
                    message="A field on this page has no label the page provided; it needs a person to identify it",
                    machine_state={"selector": field.selector, "field_type": field.field_type},
                    ui_state={"requires_user_review": True, "current_step": "field_review"},
                    payload={
                        "field_label": field.label,
                        "field_type": field.field_type,
                        "selector": field.selector,
                        "reason": "SYNTHETIC_FIELD_LABEL",
                        "label_source": field.metadata.get("label_source"),
                    },
                ).emit()
                if field.required:
                    missing_required_answers.append(required_answer_missing_payload(field))
                continue

            answer_match = match_approved_answer(field, approved_answers)
            if answer_match.outcome == MATCH_OUTCOME_AMBIGUOUS:
                # Two approved answers claim this field equally well. Picking one
                # would write, say, the personal email into the work-email box and
                # report success, so the choice goes back to the person.
                WorkerEvent(
                    event_type=EventType.USER_REVIEW_REQUIRED,
                    run_id=run_id,
                    step_id=None,
                    severity=Severity.WARN,
                    message=f"More than one reviewed answer could fill {field.label}",
                    machine_state={"selector": field.selector, "field_type": field.field_type},
                    ui_state={"requires_user_review": True, "current_step": "field_review"},
                    payload={
                        "field_label": field.label,
                        "field_type": field.field_type,
                        "selector": field.selector,
                        "reason": "AMBIGUOUS_ANSWER_MATCH",
                        "competing_labels": list(answer_match.competing_labels),
                    },
                ).emit()
                if field.required:
                    missing_required_answers.append(required_answer_missing_payload(field))
                continue
            reviewed_value = (
                answer_match.match.value
                if answer_match.outcome == MATCH_OUTCOME_MATCHED and answer_match.match
                else None
            )
            value, secret_source = resolve_secret_reviewed_value(field, reviewed_value)
            if value is None:
                if field.required:
                    missing_required_answers.append(required_answer_missing_payload(field))
                continue
            result = await adapter.apply_field_value(field, value)
            if result.ok:
                is_secret_value = secret_source is not None
                WorkerEvent(
                    event_type=EventType.FIELD_VALUE_APPLIED,
                    run_id=run_id,
                    step_id=None,
                    severity=Severity.INFO,
                    message=f"Applied reviewed answer to {field.label}",
                    machine_state={"selector": field.selector, "field_type": field.field_type},
                    ui_state={"current_step": "automation"},
                    payload={
                        "field_label": field.label,
                        "field_type": field.field_type,
                        "selector": field.selector,
                        "value_length": None if is_secret_value else len(value),
                        "source": secret_source or "USER_EDIT",
                        "secret_ref": secret_source,
                        "applied_action": result.payload.get("action"),
                        "checked": result.payload.get("checked") if isinstance(result.payload.get("checked"), bool) else None,
                        "selected_label": result.payload.get("selected_label"),
                        "selected_value_length": result.payload.get("selected_value_length"),
                    },
                ).emit()
            else:
                WorkerEvent(
                    event_type=EventType.USER_REVIEW_REQUIRED,
                    run_id=run_id,
                    step_id=None,
                    severity=Severity.WARN,
                    message=f"Could not apply reviewed answer to {field.label}",
                    machine_state={"selector": field.selector, "field_type": field.field_type},
                    ui_state={"requires_user_review": True, "current_step": "field_review"},
                    payload={"field_label": field.label, "field_type": field.field_type, **result.payload},
                ).emit()

        if restart_after_uploads:
            continue

        current_missing_answer_keys = {
            str(missing.get("selector") or missing.get("field_label") or "") for missing in missing_required_answers
        }
        has_new_missing_answers = bool(current_missing_answer_keys - presented_missing_answer_keys)

        # Required answers that are still blank after being presented once have no
        # saved profile value, so pausing again would loop forever. At that point
        # the page is as complete as automation can make it and the wizard should
        # still be advanced: breaking straight to the submit gate instead, as this
        # used to, strands every page after the first on a multi-step portal and
        # then asks for a submit button that only exists on the last one.
        if not missing_required_documents and not (missing_required_answers and has_new_missing_answers):
            await capture_timeline_screenshot_if_available(
                adapter=adapter,
                work_dir=work_dir,
                run_id=run_id,
                screenshot_id=f"reviewed-fields-applied-{progression_step_index + 1}",
                current_step="field_application",
            )
            if progression_step_index >= runtime_policy.max_automated_steps:
                WorkerEvent(
                    event_type=EventType.PAUSED,
                    run_id=run_id,
                    step_id=None,
                    severity=Severity.WARN,
                    message="Automation paused after reaching the maximum reviewed portal step count",
                    machine_state={
                        "reason": "MAX_PORTAL_STEPS_REACHED",
                        "portal_id": workflow.portal_id,
                        "workflow_kind": workflow.workflow_kind,
                        "max_steps": runtime_policy.max_automated_steps,
                    },
                    ui_state={"requires_user_review": True, "current_step": "portal_step"},
                    payload={
                        "portal_id": workflow.portal_id,
                        "workflow_kind": workflow.workflow_kind,
                        "max_steps": runtime_policy.max_automated_steps,
                        "instructions": "Inspect the current portal page before continuing. Applyocalypse stopped to avoid an uncontrolled multi-page loop.",
                    },
                ).emit()
                await adapter.close()
                return
            if await handle_runtime_control(work_dir, run_id, context="safe step progression"):
                await adapter.close()
                return
            progression_result = await attempt_safe_step_progression(
                adapter=adapter,
                work_dir=work_dir,
                run_id=run_id,
                workflow=workflow,
                context="approved_field_application",
                step_index=progression_step_index + 1,
            )
            if progression_result == "cancelled":
                await adapter.close()
                return
            if progression_result == "blocked":
                # The portal rejected the step and already told the user why. Give the
                # human a bounded number of chances to clear it in the visible browser
                # rather than clicking the same rejected button until the step budget
                # runs out.
                blocked_progression_attempts += 1
                if blocked_progression_attempts > MAX_BLOCKED_PROGRESSION_ATTEMPTS:
                    await adapter.close()
                    return
                if os.getenv("APPLYO_WORKER_WAIT_FOR_REVIEW") != "1":
                    await adapter.close()
                    return
                control = await asyncio.to_thread(
                    wait_for_review_resume,
                    work_dir,
                    run_id=run_id,
                    current_step="portal_step",
                    context="blocked step progression review",
                )
                if control.command == "CANCEL":
                    WorkerEvent(
                        event_type=EventType.FAILED,
                        run_id=run_id,
                        step_id=control.step_id,
                        severity=Severity.WARN,
                        message="Worker cancelled while the portal step was blocked",
                        machine_state={"reason": control.reason or "USER_CANCELLED"},
                        ui_state={"cancelled": True},
                        payload={"code": "USER_CANCELLED"},
                    ).emit()
                    await adapter.close()
                    return
                fields = await adapter.detect_fields()
                upload_attempt += 1
                continue
            if progression_result == "advanced":
                progression_step_index += 1
                await capture_timeline_screenshot_if_available(
                    adapter=adapter,
                    work_dir=work_dir,
                    run_id=run_id,
                    screenshot_id=f"portal-step-{progression_step_index}",
                    current_step="portal_step",
                )
                if await handle_runtime_control(work_dir, run_id, context="post-step field detection"):
                    await adapter.close()
                    return
                fields = await adapter.detect_fields()
                page_state = await observe_portal_page_state(
                    adapter=adapter,
                    run_id=run_id,
                    workflow=workflow,
                    original_url=job_url,
                    context="post_step_progression",
                    field_count=len(fields),
                )
                if page_state and page_state.requires_review:
                    if await pause_for_portal_state_review(adapter, work_dir, run_id, workflow, page_state, context="post_step_progression"):
                        await adapter.close()
                        return
                    fields = await adapter.detect_fields()
                upload_attempt += 1
                continue
            break

        if missing_required_answers and has_new_missing_answers:
            presented_missing_answer_keys |= current_missing_answer_keys
            WorkerEvent(
                event_type=EventType.PAUSED,
                run_id=run_id,
                step_id=None,
                severity=Severity.WARN,
                message="Browser automation paused because required application fields need reviewed answers",
                machine_state={"reason": "FIELD_REVIEW_REQUIRED", "missing_answer_count": len(missing_required_answers)},
                ui_state={"requires_user_review": True, "current_step": "field_review"},
                payload={"missing_answers": missing_required_answers, "missing_documents": missing_required_documents},
            ).emit()
            if os.getenv("APPLYO_WORKER_WAIT_FOR_REVIEW") != "1":
                await adapter.close()
                return
            control = await asyncio.to_thread(wait_for_review_resume, work_dir, run_id=run_id, current_step="field_review", context="required answer review")
            if control.command == "CANCEL":
                WorkerEvent(
                    event_type=EventType.FAILED,
                    run_id=run_id,
                    step_id=control.step_id,
                    severity=Severity.WARN,
                    message="Worker cancelled while waiting for reviewed required answers",
                    machine_state={"reason": control.reason or "USER_CANCELLED"},
                    ui_state={"cancelled": True},
                    payload={"code": "USER_CANCELLED"},
                ).emit()
                await adapter.close()
                return
            WorkerEvent(
                event_type=EventType.RESUMED,
                run_id=run_id,
                step_id=control.step_id,
                severity=Severity.INFO,
                message="Required answer review resolved; retrying field application",
                machine_state={"gate": "FIELD_REVIEW_REQUIRED", "reason": control.reason},
                ui_state={"current_step": "field_review"},
                payload={},
            ).emit()
            approved_answers = control.payload.get("approvedAnswers") or control.payload.get("approved_answers") or approved_answers
            generated_files = control.payload.get("generatedFiles") or control.payload.get("generated_files") or generated_files
            auto_submit_enabled = control_auto_submit_enabled(control) or auto_submit_enabled
            upload_attempt += 1
            continue

        WorkerEvent(
            event_type=EventType.PAUSED,
            run_id=run_id,
            step_id=None,
            severity=Severity.WARN,
            message="Browser automation paused because required upload artifacts are missing",
            machine_state={"reason": "REQUIRED_DOCUMENT_MISSING", "missing_document_count": len(missing_required_documents)},
            ui_state={"requires_user_review": True, "current_step": "file_upload"},
            payload={"missing_documents": missing_required_documents},
        ).emit()
        if os.getenv("APPLYO_WORKER_WAIT_FOR_REVIEW") != "1":
            await adapter.close()
            return
        control = await asyncio.to_thread(wait_for_review_resume, work_dir, run_id=run_id, current_step="file_upload", context="required upload artifact review")
        if control.command == "CANCEL":
            WorkerEvent(
                event_type=EventType.FAILED,
                run_id=run_id,
                step_id=control.step_id,
                severity=Severity.WARN,
                message="Worker cancelled while waiting for required upload artifacts",
                machine_state={"reason": control.reason or "USER_CANCELLED"},
                ui_state={"cancelled": True},
                payload={"code": "USER_CANCELLED"},
            ).emit()
            await adapter.close()
            return
        WorkerEvent(
            event_type=EventType.RESUMED,
            run_id=run_id,
            step_id=control.step_id,
            severity=Severity.INFO,
            message="Required upload artifact review resolved; retrying field uploads",
            machine_state={"gate": "REQUIRED_DOCUMENT_MISSING", "reason": control.reason},
            ui_state={"current_step": "file_upload"},
            payload={},
        ).emit()
        approved_answers = control.payload.get("approvedAnswers") or control.payload.get("approved_answers") or approved_answers
        generated_files = control.payload.get("generatedFiles") or control.payload.get("generated_files") or generated_files
        auto_submit_enabled = control_auto_submit_enabled(control) or auto_submit_enabled
        upload_attempt += 1

    visible_before_submit: str | None = None
    if runtime_policy.review_evidence_required:
        visible = await adapter.extract_visible_text()
        visible_before_submit = str(visible.payload.get("text") or "") if visible.ok else None
    gate = evaluate_final_submit_gate(
        policy=runtime_policy,
        auto_submit_enabled=auto_submit_enabled,
        visible_text=visible_before_submit,
    )
    auto_submit_enabled = gate.auto_submit_enabled
    WorkerEvent(
        event_type=EventType.READY_TO_SUBMIT,
        run_id=run_id,
        step_id=None,
        severity=Severity.INFO if auto_submit_enabled else Severity.WARN,
        message=gate.message,
        machine_state={
            "gate": "FINAL_SUBMIT",
            "auto_submit_enabled": auto_submit_enabled,
            "portal_id": runtime_policy.portal_id,
            "review_evidence_required": runtime_policy.review_evidence_required,
            "review_text_detected": gate.review_text_detected,
            "auto_submit_withdrawn": gate.withdrawn,
        },
        ui_state={"requires_user_review": not auto_submit_enabled},
        payload={
            "auto_submit_enabled": auto_submit_enabled,
            "review_text_detected": gate.review_text_detected,
            "auto_submit_withdrawn": gate.withdrawn,
        },
    ).emit()
    if auto_submit_enabled:
        auto_submit_control = WorkerControl(
            command="RESUME",
            reason="local_user_preapproved_auto_submit",
            step_id=None,
            written_at=None,
            payload={"approvalType": "FINAL_SUBMIT", "autoSubmitEnabled": True},
        )
        WorkerEvent(
            event_type=EventType.RESUMED,
            run_id=run_id,
            step_id=None,
            severity=Severity.INFO,
            message="Final submit continuing under explicit auto-submit approval",
            machine_state={"reason": "AUTO_SUBMIT_PREAPPROVED"},
            ui_state={"current_step": "final_submit"},
            payload={"approval_type": "AUTO_SUBMIT"},
        ).emit()
        await perform_final_submit_with_control(adapter, work_dir, run_id, auto_submit_control, workflow=workflow)
    else:
        await perform_final_submit_after_approval(adapter, work_dir, run_id, workflow=workflow)
    await adapter.close()


def _run_id_from_argv(argv: list[str]) -> str | None:
    for index, arg in enumerate(argv):
        if arg == "--run-id" and index + 1 < len(argv):
            return argv[index + 1]
        if arg.startswith("--run-id="):
            return arg.split("=", 1)[1]
    return None


def main() -> None:
    try:
        _main_impl()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - Electron only learns of failure via a terminal event
        run_id = _run_id_from_argv(sys.argv)
        if run_id:
            fail_process(run_id, f"Automation worker crashed: {type(exc).__name__}: {exc}")
        raise


def _main_impl() -> None:
    # Provider API keys arrive via the 0600 worker-secrets file, never spawn env;
    # export them for LiteLLM/boto before any subcommand or pipeline work runs.
    apply_provider_secrets_to_env()

    if len(sys.argv) > 1 and sys.argv[1] == "pdf-ingestion":
        from .documents.pdf_ingestion_cli import main as pdf_ingestion_main

        sys.argv = [sys.argv[0], *sys.argv[2:]]
        pdf_ingestion_main()
        return

    if len(sys.argv) > 1 and sys.argv[1] == "pipeline":
        from .pipeline_cli import main as pipeline_main

        sys.argv = [sys.argv[0], *sys.argv[2:]]
        pipeline_main()
        return

    args = build_parser().parse_args()
    work_dir = Path(args.work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    output_dir = Path(args.output_dir) if args.output_dir else work_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    canonical_profile: dict[str, object] = {}
    if args.profile_json_file:
        canonical_profile = json.loads(Path(args.profile_json_file).read_text(encoding="utf-8"))
    cover_letter_sample_text: str | None = None
    if args.cover_letter_sample_file:
        cover_letter_sample_text = Path(args.cover_letter_sample_file).read_text(encoding="utf-8") or None
    job_metadata: dict[str, object] = {}
    if args.job_metadata_file:
        job_metadata = json.loads(Path(args.job_metadata_file).read_text(encoding="utf-8"))

    WorkerEvent(
        event_type=EventType.RUN_STARTED,
        run_id=args.run_id,
        step_id=None,
        severity=Severity.INFO,
        message="Python worker started",
        machine_state={"work_dir": str(work_dir)},
        ui_state={"current_step": "preparing"},
        payload={"job_url": args.job_url, "cover_letter_sample_available": cover_letter_sample_text is not None},
    ).emit()

    job_text = ""
    job_text_source_path: str | None = None
    job_text_source_url: str | None = None
    jd_source = "USER_TEXT"
    if args.job_text_file:
        job_text = Path(args.job_text_file).read_text(encoding="utf-8")
        job_text_source_path = str(args.job_text_file)
        WorkerEvent(
            event_type=EventType.JD_SCRAPE_COMPLETED,
            run_id=args.run_id,
            step_id=None,
            severity=Severity.INFO,
            message="Job description loaded from local intake text",
            machine_state={"source": "USER_TEXT"},
            ui_state={"current_step": "analyzing"},
            payload={"text_length": len(job_text)},
        ).emit()
    elif args.job_url:
        workflow = workflow_for_url(args.job_url)
        WorkerEvent(
            event_type=EventType.JD_SCRAPE_STARTED,
            run_id=args.run_id,
            step_id=None,
            severity=Severity.INFO,
            message="Job URL received for browser-backed scraping",
            machine_state={"portal": workflow.portal_id, "workflow_kind": workflow.workflow_kind},
            ui_state={"current_step": "scraping"},
            payload={
                "url": args.job_url,
                "adapter": workflow.default_adapter,
                "requires_high_stealth": workflow.requires_high_stealth,
                "workflow": workflow.to_event_payload(),
            },
        ).emit()
        observation = asyncio.run(
            run_url_observation_flow(
                run_id=args.run_id,
                job_url=args.job_url,
                work_dir=work_dir,
                canonical_profile=canonical_profile,
                adapter_name=workflow.default_adapter,
            )
        )
        if observation.should_stop or observation.job_text_file is None:
            return
        job_text_source_path = str(observation.job_text_file)
        job_text_source_url = observation.scraped_url
        job_text = observation.job_text_file.read_text(encoding="utf-8")
        jd_source = "SCRAPED"

    if job_text:
        control = read_worker_control(work_dir)
        if control and control.command == "CANCEL":
            WorkerEvent(
                event_type=EventType.FAILED,
                run_id=args.run_id,
                step_id=control.step_id,
                severity=Severity.WARN,
                message="Worker cancelled before job description analysis",
                machine_state={"reason": control.reason},
                ui_state={"cancelled": True},
                payload={"code": "USER_CANCELLED"},
            ).emit()
            return

        generate_application_documents(
            run_id=args.run_id,
            work_dir=work_dir,
            output_dir=output_dir,
            canonical_profile=canonical_profile,
            job_text=job_text,
            job_metadata=job_metadata,
            cover_letter_sample_text=cover_letter_sample_text,
            job_text_source_path=job_text_source_path,
            job_text_source_url=job_text_source_url,
            jd_source=jd_source,
        )

    WorkerEvent(
        event_type=EventType.PAUSED,
        run_id=args.run_id,
        step_id=None,
        severity=Severity.WARN,
        message="Run paused for user approval before browser execution",
        machine_state={"reason": "USER_REVIEW_GATE"},
        ui_state={"requires_user_review": True},
        payload={},
    ).emit()
    if os.getenv("APPLYO_WORKER_WAIT_FOR_REVIEW") != "1":
        return

    control = wait_for_document_approval(work_dir, args.run_id)
    if control is None:
        return

    if args.job_url:
        workflow = workflow_for_url(args.job_url)
        asyncio.run(
            run_browser_apply_after_review(
                run_id=args.run_id,
                job_url=args.job_url,
                work_dir=work_dir,
                adapter_name=workflow.default_adapter,
                control=control,
            )
        )
    else:
        auto_submit_enabled = control_auto_submit_enabled(control)
        ready_message = (
            "Final submission is preapproved by the explicit auto-submit setting"
            if auto_submit_enabled
            else "Final submission is gated until explicit approval"
        )
        WorkerEvent(
            event_type=EventType.READY_TO_SUBMIT,
            run_id=args.run_id,
            step_id=None,
            severity=Severity.INFO if auto_submit_enabled else Severity.WARN,
            message=ready_message,
            machine_state={"gate": "FINAL_SUBMIT", "auto_submit_enabled": auto_submit_enabled},
            ui_state={"requires_user_review": not auto_submit_enabled},
            payload={"auto_submit_enabled": auto_submit_enabled},
        ).emit()


if __name__ == "__main__":
    main()
