from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

from .answers import ProposedApplicationAnswer, propose_answer_for_detected_field, propose_profile_answers
from .browser.adapter import BrowserAdapter, BrowserBlocker, BrowserField, BrowserStepResult
from .browser.adapter_factory import adapter_candidates_for_workflow, create_browser_adapter
from .browser.portal_adapters import COMMON_STEP_PROGRESSION_LABELS, progression_labels_for_workflow
from .browser.portal_state import PortalPageState, classify_portal_page_state
from .browser.portal_workflows import PortalWorkflow, workflow_for_url
from .control import WorkerControl, read_worker_control
from .cover_letter_tailoring import generate_cover_letter
from .documents.artifact_generation import (
    build_cover_letter_text,
    build_placeholder_replacements,
    build_resume_markdown,
    find_anchored_resume_candidate,
    find_verified_resume_master,
    metadata_for_existing_file,
    split_legal_name,
    write_text_artifact,
)
from .documents.docx_builder import build_cover_letter_docx, build_resume_docx
from .documents.docx_mutation import extract_docx_text, mutate_docx_bullet_anchors, mutate_docx_placeholders
from .documents.file_generation import GeneratedNameInput, build_generated_filename, choose_collision_safe_path
from .documents.pdf_export import export_docx_to_pdf
from .documents.tex_mutation import compile_tex_with_tectonic, mutate_tex_placeholders
from .event_protocol import EventType, Severity, WorkerEvent, utc_now
from .jd_analysis import analyze_with_optional_llm
from .llm.litellm_client import LiteLlmClient
from .otp import read_gmail_otp_from_env
from .resume_tailoring import tailor_resume_sections
from .secret_env import get_secret
from .tailoring.engine import TailoringEngine
from .validation import TextArtifactValidator, ValidationReport


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

MAX_AUTOMATED_PORTAL_STEPS = 20

SUBMISSION_CONFIRMATION_PATTERNS = (
    "application submitted",
    "application has been submitted",
    "successfully submitted",
    "thank you for applying",
    "thanks for applying",
    "received your application",
    "we have received your application",
)

APPLICATION_PASSWORD_SENTINEL = "Use stored application password"

OTP_FIELD_HINTS = (
    "otp",
    "one-time code",
    "one time code",
    "verification code",
    "security code",
    "passcode",
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


async def perform_final_submit_with_control(adapter: BrowserAdapter, work_dir: Path, run_id: str, final_submit_control: WorkerControl) -> bool:
    blockers = await adapter.detect_blockers()
    if blockers:
        if await pause_for_blockers(adapter, work_dir, run_id, blockers, context="final submission"):
            return False

    result = await adapter.click_final_submit(list(FINAL_SUBMIT_LABELS))
    if not result.ok:
        WorkerEvent(
            event_type=EventType.USER_REVIEW_REQUIRED,
            run_id=run_id,
            step_id=final_submit_control.step_id,
            severity=Severity.WARN,
            message="Final submit approval was received, but no exact final submit control could be clicked",
            machine_state={"reason": "FINAL_SUBMIT_CONTROL_NOT_FOUND"},
            ui_state={"requires_user_review": True, "current_step": "final_submit"},
            payload=result.payload,
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


async def perform_final_submit_after_approval(adapter: BrowserAdapter, work_dir: Path, run_id: str) -> bool:
    final_submit_control = wait_for_final_submit_decision(work_dir, run_id)
    if final_submit_control is None:
        return False
    return await perform_final_submit_with_control(adapter, work_dir, run_id, final_submit_control)


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


def handle_runtime_control(work_dir: Path, run_id: str, *, context: str) -> bool:
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
        resume_control = wait_for_review_resume(work_dir, run_id=run_id, current_step="automation", context=context)
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


async def try_resolve_otp_with_gmail(adapter: object, run_id: str, *, context: str) -> bool:
    if os.getenv("APPLYO_GMAIL_OTP_ENABLED") != "1":
        return False

    WorkerEvent(
        event_type=EventType.OTP_RETRIEVAL_STARTED,
        run_id=run_id,
        step_id=None,
        severity=Severity.INFO,
        message="Gmail OTP retrieval started",
        machine_state={"provider": "gmail", "context": context},
        ui_state={"current_step": "otp"},
        payload={"provider": "gmail"},
    ).emit()
    result = await asyncio.to_thread(read_gmail_otp_from_env)
    if not result.ok or not result.code:
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
        return False

    WorkerEvent(
        event_type=EventType.OTP_RETRIEVAL_COMPLETED,
        run_id=run_id,
        step_id=None,
        severity=Severity.INFO,
        message="Gmail OTP retrieved without exposing the code",
        machine_state={"provider": "gmail", "context": context},
        ui_state={"current_step": "otp"},
        payload=result.safe_payload(),
    ).emit()
    return await apply_otp_code_to_detected_field(adapter, run_id, result.code)


async def pause_for_blockers(adapter: object, work_dir: Path, run_id: str, blockers: list[BrowserBlocker], *, context: str) -> bool:
    active_blockers = blockers
    while active_blockers:
        blocker_payload = blocker_payload_from(active_blockers)
        primary_blocker = active_blockers[0]
        if any(blocker.blocker_type == "OTP" for blocker in active_blockers) and await try_resolve_otp_with_gmail(
            adapter, run_id, context=context
        ):
            active_blockers = await adapter.detect_blockers()  # type: ignore[attr-defined]
            if not active_blockers:
                return False
            blocker_payload = blocker_payload_from(active_blockers)
            primary_blocker = active_blockers[0]
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
        control = wait_for_review_resume(work_dir, run_id=run_id, current_step="blocker_review", context=context)
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
        active_blockers = await adapter.detect_blockers()  # type: ignore[attr-defined]
    return False


def portal_entry_requires_manual_action(workflow: PortalWorkflow, action_applied: bool) -> bool:
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
    control = wait_for_review_resume(work_dir, run_id=run_id, current_step="portal_entry", context=f"{workflow.display_name} portal entry")
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
    control = wait_for_review_resume(work_dir, run_id=run_id, current_step="portal_entry", context=f"{workflow.display_name} redirect review")
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


def normalize_field_label(value: str) -> str:
    return " ".join("".join(character.lower() if character.isalnum() else " " for character in value).split())


def approved_value_for_field(field: BrowserField, approved_answers: object) -> str | None:
    if not isinstance(approved_answers, list):
        return None
    field_label = normalize_field_label(field.label)
    for answer in approved_answers:
        if not isinstance(answer, dict):
            continue
        value = answer.get("value")
        if not isinstance(value, str) or not value.strip():
            continue
        answer_label = normalize_field_label(str(answer.get("fieldLabel") or ""))
        answer_type = normalize_field_label(str(answer.get("fieldType") or ""))
        if not answer_label:
            continue
        if field_label == answer_label or answer_label in field_label or field_label in answer_label:
            return value
        if field.field_type in {"email", "tel", "url"} and field.field_type == answer_type:
            return value
    return None


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


async def _lazy_generate_cover_letter_for_portal(
    *,
    run_id: str,
    work_dir: Path,
    output_dir: Path,
) -> dict[str, object] | None:
    """Lazily generate a cover letter DOCX when a portal upload field requires one.

    Only runs when APPLYO_LAZY_COVER_LETTER=1. Reads canonical_profile, job text,
    sample text, and job metadata from well-known work_dir paths written by the
    scheduler before the run starts.

    Emits COVER_LETTER_RENDERED and USER_REVIEW_REQUIRED(DOCUMENT) on success.
    Returns a generated-file metadata dict (same shape as ArtifactMetadata.to_payload)
    suitable for appending to generated_files, or None on failure.
    """
    if os.getenv("APPLYO_LAZY_COVER_LETTER") != "1":
        return None

    canonical_profile: dict[str, object] = {}
    profile_path = work_dir / "canonical-profile.json"
    if profile_path.exists():
        try:
            canonical_profile = json.loads(profile_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    job_text = ""
    for _job_name in ("job-description.txt", "job-description-scraped.txt"):
        _p = work_dir / _job_name
        if _p.exists():
            job_text = _p.read_text(encoding="utf-8")
            break

    cover_letter_sample: str | None = None
    sample_path = work_dir / "cover-letter-sample.txt"
    if sample_path.exists():
        cover_letter_sample = sample_path.read_text(encoding="utf-8") or None

    job_metadata: dict[str, object] = {}
    metadata_path = work_dir / "job-target.json"
    if metadata_path.exists():
        try:
            job_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    cover_letter_content: str | None = None
    cl_generation_mode = "DETERMINISTIC"
    cl_llm_model = os.getenv("LITELLM_MODEL_STRONG") or os.getenv("LITELLM_MODEL")
    if cl_llm_model and job_text:
        try:
            generated = await generate_cover_letter(
                job_description=job_text,
                canonical_profile=canonical_profile,
                cover_letter_sample=cover_letter_sample,
                llm_client=LiteLlmClient(model=cl_llm_model),
            )
            if generated:
                cover_letter_content = generated.text
                cl_generation_mode = "LLM"
        except Exception:
            pass

    if cover_letter_content is None:
        tailoring_plan: dict[str, object] = {}
        plan_path = work_dir / "tailoring-plan.json"
        if plan_path.exists():
            try:
                tailoring_plan = json.loads(plan_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        cover_letter_content = build_cover_letter_text(
            canonical_profile=canonical_profile,
            job_metadata=job_metadata,
            tailoring_plan=tailoring_plan,
        )
        cl_generation_mode = "DETERMINISTIC"

    if not cover_letter_content:
        return None

    report = TextArtifactValidator().validate(cover_letter_content, artifact_kind="cover_letter")
    report_path = work_dir / "cover-letter-lazy-validation-report.json"
    report_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")

    if not report.passed:
        WorkerEvent(
            event_type=EventType.VALIDATION_FAILED,
            run_id=run_id,
            step_id=None,
            severity=Severity.ERROR,
            message="Lazily generated cover letter failed validation",
            machine_state={"generation_mode": cl_generation_mode},
            ui_state={"current_step": "document_review", "requires_user_review": True},
            payload={"artifact_kind": "cover_letter", "validation_report_path": str(report_path), **report.to_dict()},
        ).emit()
        return None

    profile = canonical_profile.get("profile") if isinstance(canonical_profile.get("profile"), dict) else {}
    first_name, last_name = split_legal_name(str(profile.get("legalName") or profile.get("displayName") or "Candidate Profile"))
    company = str(job_metadata.get("company") or "")
    role = str(job_metadata.get("role") or "")
    cl_filename_input = GeneratedNameInput(
        first_name=first_name,
        last_name=last_name,
        company=company,
        role=role,
        kind="Cover Letter",
        extension="docx",
    )
    cl_docx_path = choose_collision_safe_path(output_dir, build_generated_filename(cl_filename_input))
    build_cover_letter_docx(cover_letter_content, canonical_profile, cl_docx_path)

    cl_artifact = metadata_for_existing_file(
        path=cl_docx_path,
        file_kind="COVER_LETTER",
        format_name="DOCX",
        review_only=True,
    )

    WorkerEvent(
        event_type=EventType.COVER_LETTER_RENDERED,
        run_id=run_id,
        step_id=None,
        severity=Severity.INFO,
        message="Cover letter generated lazily for portal upload field",
        machine_state={"format": "DOCX", "review_only": True, "generation_mode": cl_generation_mode},
        ui_state={"current_step": "document_review"},
        payload={**cl_artifact.to_payload(), "validation_report_path": str(report_path)},
    ).emit()

    WorkerEvent(
        event_type=EventType.USER_REVIEW_REQUIRED,
        run_id=run_id,
        step_id=None,
        severity=Severity.WARN,
        message="Lazily generated cover letter awaits review before upload",
        machine_state={"artifact_kind": "DOCUMENT", "generation_mode": cl_generation_mode},
        ui_state={"requires_user_review": True, "current_step": "document_review", "artifact_kind": "DOCUMENT"},
        payload={"artifact_kind": "DOCUMENT", **cl_artifact.to_payload()},
    ).emit()

    return cl_artifact.to_payload()


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


async def attempt_safe_step_progression(
    *,
    adapter: object,
    work_dir: Path,
    run_id: str,
    workflow: PortalWorkflow,
    context: str,
    step_index: int,
) -> str:
    click_by_text = adapter.click_by_text
    labels = list(progression_labels_for_workflow(workflow))
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
    control = wait_for_review_resume(work_dir, run_id=run_id, current_step="portal_step", context="portal step progression")
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


def tex_escape(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
    }
    return "".join(replacements.get(character, character) for character in value)


def _company_from_url(url: str) -> str | None:
    try:
        host = urlparse(url).hostname or ""
        if "myworkdayjobs.com" in host or "workdayjobs.com" in host:
            return host.split(".")[0].replace("-", " ").title()
        parts = host.replace("www.", "").split(".")
        if parts:
            return parts[0].replace("-", " ").title()
    except Exception:
        pass
    return None


def _role_from_url(url: str) -> str | None:
    try:
        path = unquote(urlparse(url).path)
        segments = [s for s in path.split("/") if s]
        # Workday: /en-US/External_Careers/job/<location>/<title>_<id>
        if "job" in segments:
            idx = segments.index("job")
            if idx + 2 <= len(segments):
                slug = segments[idx + 2] if idx + 2 < len(segments) else segments[idx + 1]
                slug = re.sub(r"_[A-Z0-9]{6,}$", "", slug)
                return re.sub(r"[-_]+", " ", slug).strip().title()
        if segments:
            slug = re.sub(r"_[A-Z0-9]{6,}$", "", segments[-1])
            return re.sub(r"[-_]+", " ", slug).strip().title()
    except Exception:
        pass
    return None


def _build_bullet_retry_jd(job_text: str, report: ValidationReport) -> str:
    """Return a modified job description string that appends violation guidance for a retry."""
    violation_codes = ", ".join(issue.code for issue in report.blocking_issues)
    return job_text + (
        "\n\nIMPORTANT: The previous bullet set failed validation ("
        + violation_codes
        + "). No em dashes. No banned words. Plain text bullets only."
    )


def _build_overflow_jd(job_text: str, pages: int) -> str:
    """Return a modified job description string that instructs the LLM to reduce resume length."""
    return job_text + (
        "\n\nIMPORTANT: The tailored resume overflowed to "
        + str(pages)
        + " pages. Cut the weakest bullets and tighten wording so the resume fits ONE page."
    )


def _remutate_and_export(master_path, output_path, replacements, bullet_map, output_dir):
    """Re-run placeholder + bullet mutation from the master and export PDF. Returns the export result."""
    mutate_docx_placeholders(master_path, output_path, replacements)
    if bullet_map:
        mutate_docx_bullet_anchors(output_path, output_path, bullet_map)
    return export_docx_to_pdf(output_path, output_dir)


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
    if handle_runtime_control(work_dir, run_id, context="browser launch"):
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

    WorkerEvent(
        event_type=EventType.PAGE_NAVIGATED,
        run_id=run_id,
        step_id=None,
        severity=Severity.INFO,
        message="Application page navigated",
        machine_state={"url": job_url},
        ui_state={"current_step": "page_review"},
        payload=navigation.payload,
    ).emit()
    if handle_runtime_control(work_dir, run_id, context="page navigation"):
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
    if handle_runtime_control(work_dir, run_id, context="page diagnostics"):
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
    if handle_runtime_control(work_dir, run_id, context="job description extraction"):
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
    if handle_runtime_control(work_dir, run_id, context="screenshot capture"):
        await adapter.close()
        return UrlObservationResult(should_stop=True)

    blockers = await adapter.detect_blockers()
    if blockers:
        if await pause_for_blockers(adapter, work_dir, run_id, blockers, context="page review"):
            await adapter.close()
            return UrlObservationResult(should_stop=True, job_text_file=job_text_file, scraped_url=scraped_url)

    portal_action = await execute_portal_entry_action(adapter=adapter, workflow=workflow, run_id=run_id, context="observation")
    if handle_runtime_control(work_dir, run_id, context="portal entry action"):
        await adapter.close()
        return UrlObservationResult(should_stop=True, job_text_file=job_text_file, scraped_url=scraped_url)
    if portal_entry_requires_manual_action(workflow, portal_action.ok):
        if await pause_for_portal_entry_action(adapter, work_dir, run_id, workflow, context="observation", action_payload=portal_action.payload):
            await adapter.close()
            return UrlObservationResult(should_stop=True, job_text_file=job_text_file, scraped_url=scraped_url)
    blockers = await adapter.detect_blockers()
    if blockers:
        if await pause_for_blockers(adapter, work_dir, run_id, blockers, context="portal entry action"):
            await adapter.close()
            return UrlObservationResult(should_stop=True, job_text_file=job_text_file, scraped_url=scraped_url)

    if handle_runtime_control(work_dir, run_id, context="field detection"):
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
        if handle_runtime_control(work_dir, run_id, context="field proposal"):
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
        proposed_answer = proposed_answer_for_browser_field(field, canonical_profile)
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
        control = wait_for_review_resume(work_dir, run_id=run_id, current_step="field_review", context="initial browser field review")
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
    if handle_runtime_control(work_dir, run_id, context="approved automation browser launch"):
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

    WorkerEvent(
        event_type=EventType.PAGE_NAVIGATED,
        run_id=run_id,
        step_id=None,
        severity=Severity.INFO,
        message="Application page reopened for approved field application",
        machine_state={"url": job_url},
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
    if handle_runtime_control(work_dir, run_id, context="approved automation navigation"):
        await adapter.close()
        return

    blockers = await adapter.detect_blockers()
    if blockers:
        if await pause_for_blockers(adapter, work_dir, run_id, blockers, context="approved field application"):
            await adapter.close()
            return

    if handle_runtime_control(work_dir, run_id, context="pre-fill review"):
        await adapter.close()
        return
    portal_action = await execute_portal_entry_action(adapter=adapter, workflow=workflow, run_id=run_id, context="apply_after_review")
    if handle_runtime_control(work_dir, run_id, context="approved portal entry action"):
        await adapter.close()
        return
    if portal_entry_requires_manual_action(workflow, portal_action.ok):
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
    if handle_runtime_control(work_dir, run_id, context="approved field detection"):
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
    while True:
        if upload_attempt > 0:
            if handle_runtime_control(work_dir, run_id, context="required document retry field detection"):
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
        for field in fields:
            if handle_runtime_control(work_dir, run_id, context=f"field application: {field.label}"):
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

                local_path = Path(str(generated_file_value(generated_file, "local_path")))
                result = await adapter.upload_file(field, local_path)
                if result.ok:
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

            reviewed_value = approved_value_for_field(field, approved_answers)
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

        if not missing_required_documents and not missing_required_answers:
            await capture_timeline_screenshot_if_available(
                adapter=adapter,
                work_dir=work_dir,
                run_id=run_id,
                screenshot_id=f"reviewed-fields-applied-{progression_step_index + 1}",
                current_step="field_application",
            )
            if progression_step_index >= MAX_AUTOMATED_PORTAL_STEPS:
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
                        "max_steps": MAX_AUTOMATED_PORTAL_STEPS,
                    },
                    ui_state={"requires_user_review": True, "current_step": "portal_step"},
                    payload={
                        "portal_id": workflow.portal_id,
                        "workflow_kind": workflow.workflow_kind,
                        "max_steps": MAX_AUTOMATED_PORTAL_STEPS,
                        "instructions": "Inspect the current portal page before continuing. Applyocalypse stopped to avoid an uncontrolled multi-page loop.",
                    },
                ).emit()
                await adapter.close()
                return
            if handle_runtime_control(work_dir, run_id, context="safe step progression"):
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
            if progression_result == "advanced":
                progression_step_index += 1
                await capture_timeline_screenshot_if_available(
                    adapter=adapter,
                    work_dir=work_dir,
                    run_id=run_id,
                    screenshot_id=f"portal-step-{progression_step_index}",
                    current_step="portal_step",
                )
                if handle_runtime_control(work_dir, run_id, context="post-step field detection"):
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

        if missing_required_answers:
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
            control = wait_for_review_resume(work_dir, run_id=run_id, current_step="field_review", context="required answer review")
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
        control = wait_for_review_resume(work_dir, run_id=run_id, current_step="file_upload", context="required upload artifact review")
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

    ready_message = (
        "Final submission is preapproved by the explicit auto-submit setting"
        if auto_submit_enabled
        else "Final submission is gated until explicit approval"
    )
    WorkerEvent(
        event_type=EventType.READY_TO_SUBMIT,
        run_id=run_id,
        step_id=None,
        severity=Severity.INFO if auto_submit_enabled else Severity.WARN,
        message=ready_message,
        machine_state={"gate": "FINAL_SUBMIT", "auto_submit_enabled": auto_submit_enabled},
        ui_state={"requires_user_review": not auto_submit_enabled},
        payload={"auto_submit_enabled": auto_submit_enabled},
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
        await perform_final_submit_with_control(adapter, work_dir, run_id, auto_submit_control)
    else:
        await perform_final_submit_after_approval(adapter, work_dir, run_id)
    await adapter.close()


def main() -> None:
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

        analysis_result, analysis_source = asyncio.run(analyze_with_optional_llm(job_text))
        analysis = analysis_result.to_dict()
        WorkerEvent(
            event_type=EventType.JD_ANALYSIS_COMPLETED,
            run_id=args.run_id,
            step_id=None,
            severity=Severity.INFO,
            message="Job description analysis completed",
            machine_state={"analysis_version": "jd-analysis-0.2", "analysis_source": analysis_source},
            ui_state={"current_step": "review"},
            payload={
                **analysis,
                "source_text_path": job_text_source_path,
                "jd_source": jd_source,
                **({"url": job_text_source_url} if job_text_source_url else {}),
            },
        ).emit()

        WorkerEvent(
            event_type=EventType.RESUME_TAILORING_STARTED,
            run_id=args.run_id,
            step_id=None,
            severity=Severity.INFO,
            message="Truthful resume tailoring plan started",
            machine_state={"profile_available": bool(canonical_profile), "output_dir": str(output_dir)},
            ui_state={"current_step": "tailoring_plan"},
            payload={},
        ).emit()

        tailoring_plan = TailoringEngine().build_plan(canonical_profile=canonical_profile, jd_analysis=analysis).to_dict()
        plan_path = work_dir / "tailoring-plan.json"
        plan_path.write_text(json.dumps(tailoring_plan, indent=2, sort_keys=True), encoding="utf-8")

        for answer in propose_profile_answers(canonical_profile):
            field_payload = {
                "field_label": answer.field_label,
                "field_type": answer.field_type,
                "confidence": answer.confidence,
                "source": answer.source,
                "requires_review": answer.requires_review,
            }
            WorkerEvent(
                event_type=EventType.FIELD_DETECTED,
                run_id=args.run_id,
                step_id=None,
                severity=Severity.INFO,
                message=f"Detected application field: {answer.field_label}",
                machine_state={},
                ui_state={"current_step": "field_review"},
                payload=field_payload,
            ).emit()
            WorkerEvent(
                event_type=EventType.FIELD_VALUE_PROPOSED,
                run_id=args.run_id,
                step_id=None,
                severity=Severity.WARN if answer.requires_review else Severity.INFO,
                message=f"Proposed answer for {answer.field_label}",
                machine_state={},
                ui_state={"current_step": "field_review", "requires_user_review": answer.requires_review},
                payload={**field_payload, "proposed_value": answer.proposed_value},
            ).emit()

        WorkerEvent(
            event_type=EventType.USER_REVIEW_REQUIRED,
            run_id=args.run_id,
            step_id=None,
            severity=Severity.WARN,
            message="Review truthful tailoring plan before document mutation",
            machine_state={"gate": "TAILORING_PLAN_REVIEW"},
            ui_state={"requires_user_review": True},
            payload={
                "cover_letter_required": analysis["cover_letter_likely_required"],
                "tailoring_plan_path": str(plan_path),
                "missing_keywords": tailoring_plan["missing_keywords"],
                "risky_claims_to_avoid": tailoring_plan["risky_claims_to_avoid"],
            },
        ).emit()

        profile = canonical_profile.get("profile") if isinstance(canonical_profile.get("profile"), dict) else {}
        first_name, last_name = split_legal_name(str(profile.get("legalName") or profile.get("displayName") or "Candidate Profile"))
        _url = str(job_metadata.get("url") or job_text_source_url or "")
        company = str(job_metadata.get("company") or _company_from_url(_url) or "Unknown Company")
        role = str(job_metadata.get("role") or _role_from_url(_url) or "Unknown Role")
        resume_content = build_resume_markdown(canonical_profile=canonical_profile, tailoring_plan=tailoring_plan)
        resume_report = TextArtifactValidator().validate(resume_content, artifact_kind="resume")
        validation_report_path = work_dir / "resume-validation-report.json"
        validation_report_path.write_text(json.dumps(resume_report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        if resume_report.passed:
            resume_artifact = write_text_artifact(
                output_dir=output_dir,
                filename_input=GeneratedNameInput(
                    first_name=first_name,
                    last_name=last_name,
                    company=company,
                    role=role,
                    kind="Resume",
                    extension="md",
                ),
                content=resume_content,
                file_kind="RESUME",
                extension="md",
                review_only=True,
            )
            WorkerEvent(
                event_type=EventType.RESUME_RENDERED,
                run_id=args.run_id,
                step_id=None,
                severity=Severity.INFO,
                message="Resume review artifact rendered to local filesystem",
                machine_state={"format": "MD", "review_only": True},
                ui_state={"current_step": "document_review"},
                payload={**resume_artifact.to_payload(), "validation_report_path": str(validation_report_path)},
            ).emit()
        else:
            WorkerEvent(
                event_type=EventType.VALIDATION_FAILED,
                run_id=args.run_id,
                step_id=None,
                severity=Severity.ERROR,
                message="Resume artifact failed deterministic validation",
                machine_state={"format": "MD", "review_only": True},
                ui_state={"current_step": "document_review", "requires_user_review": True},
                payload={"artifact_kind": "resume", "validation_report_path": str(validation_report_path), **resume_report.to_dict()},
            ).emit()

        editable_master = find_verified_resume_master(canonical_profile)
        if editable_master:
            master_path = Path(str(editable_master["localPath"]))
            master_format = str(editable_master["sourceFormat"])
            replacements = build_placeholder_replacements(canonical_profile=canonical_profile, tailoring_plan=tailoring_plan)
            if master_format == "DOCX":
                output_path = choose_collision_safe_path(
                    output_dir,
                    build_generated_filename(
                        GeneratedNameInput(
                            first_name=first_name,
                            last_name=last_name,
                            company=company,
                            role=role,
                            kind="Resume",
                            extension="docx",
                        )
                    ),
                )
                _, replaced_placeholders = mutate_docx_placeholders(master_path, output_path, replacements)

                # Deep-tailor experience and project bullets via LLM if available
                llm_model = os.getenv("LITELLM_MODEL_STRONG") or os.getenv("LITELLM_MODEL")
                if llm_model and job_text:
                    from .documents.font_detection import detect_resume_font_size
                    detected_font_size = detect_resume_font_size(output_path) if output_path.exists() else 10
                    try:
                        resume_text_for_tailor = extract_docx_text(output_path) if output_path.exists() else ""
                    except Exception:
                        resume_text_for_tailor = ""
                    if not resume_text_for_tailor:
                        resume_text_for_tailor = build_resume_markdown(canonical_profile=canonical_profile, tailoring_plan=tailoring_plan)
                    tailored = asyncio.run(tailor_resume_sections(
                        job_description=job_text,
                        resume_text=resume_text_for_tailor,
                        llm_client=LiteLlmClient(model=llm_model),
                        font_size=detected_font_size,
                    ))
                    if tailored:
                        bullet_map: dict[str, list[str]] = {}
                        for i in range(4):
                            bullets = tailored.exp_bullets(i)
                            if bullets:
                                bullet_map[f"{{{{APPLYO_EXP_{i}_BULLETS}}}}"] = bullets
                        proj_bullets = tailored.all_project_bullets()
                        if proj_bullets:
                            bullet_map["{{APPLYO_PROJECTS_BULLETS}}"] = proj_bullets
                        # Validate LLM bullet content before writing to DOCX
                        if bullet_map:
                            bullet_text = "\n".join(b for bullets in bullet_map.values() for b in bullets)
                            bullet_report = TextArtifactValidator().validate(bullet_text, artifact_kind="resume")
                            if not bullet_report.passed:
                                # One retry with violation guidance appended to the job description
                                retry_tailored = asyncio.run(tailor_resume_sections(
                                    job_description=_build_bullet_retry_jd(job_text, bullet_report),
                                    resume_text=resume_text_for_tailor,
                                    llm_client=LiteLlmClient(model=llm_model),
                                    font_size=detected_font_size,
                                ))
                                if retry_tailored:
                                    bullet_map = {}
                                    for i in range(4):
                                        retry_bullets = retry_tailored.exp_bullets(i)
                                        if retry_bullets:
                                            bullet_map[f"{{{{APPLYO_EXP_{i}_BULLETS}}}}"] = retry_bullets
                                    retry_proj_bullets = retry_tailored.all_project_bullets()
                                    if retry_proj_bullets:
                                        bullet_map["{{APPLYO_PROJECTS_BULLETS}}"] = retry_proj_bullets
                                    retry_bullet_text = "\n".join(b for bullets in bullet_map.values() for b in bullets)
                                    bullet_report = TextArtifactValidator().validate(retry_bullet_text, artifact_kind="resume")
                                if not bullet_report.passed:
                                    WorkerEvent(
                                        event_type=EventType.VALIDATION_FAILED,
                                        run_id=args.run_id,
                                        step_id=None,
                                        severity=Severity.WARN,
                                        message="LLM resume bullets failed validation after retry; skipping bullet mutation",
                                        machine_state={"format": "DOCX", "review_only": False},
                                        ui_state={"current_step": "document_review", "requires_user_review": True},
                                        payload={"artifact_kind": "resume", "stage": "llm_bullets", **bullet_report.to_dict()},
                                    ).emit()
                                    bullet_map = {}
                        if bullet_map:
                            _, bullet_replaced = mutate_docx_bullet_anchors(output_path, output_path, bullet_map)
                            replaced_placeholders = list(set(replaced_placeholders) | set(bullet_replaced))

                # Fall back to the auto-repaired anchored candidate if the master had no placeholders
                if not replaced_placeholders:
                    anchored = find_anchored_resume_candidate(canonical_profile, master_path)
                    if anchored:
                        _, replaced_placeholders = mutate_docx_placeholders(
                            Path(str(anchored["localPath"])), output_path, replacements
                        )

                # Final-file validation gate: catch any banned content in the mutated DOCX
                final_report = TextArtifactValidator().validate_file(output_path, artifact_kind="resume") if output_path.exists() else None
                if final_report is not None and not final_report.passed:
                    WorkerEvent(
                        event_type=EventType.VALIDATION_FAILED,
                        run_id=args.run_id,
                        step_id=None,
                        severity=Severity.ERROR,
                        message="Mutated DOCX resume failed deterministic validation",
                        machine_state={"format": "DOCX", "review_only": False},
                        ui_state={"current_step": "document_review", "requires_user_review": True},
                        payload={"artifact_kind": "resume", "stage": "final_file", "generated_path": str(output_path), **final_report.to_dict()},
                    ).emit()

                if replaced_placeholders:
                    artifact = metadata_for_existing_file(path=output_path, file_kind="RESUME", format_name="DOCX", review_only=False)
                    WorkerEvent(
                        event_type=EventType.RESUME_MUTATION_COMPLETED,
                        run_id=args.run_id,
                        step_id=None,
                        severity=Severity.INFO,
                        message="DOCX editable master mutated through explicit Applyocalypse anchors",
                        machine_state={"source_format": "DOCX", "replaced_placeholders": replaced_placeholders},
                        ui_state={"current_step": "document_review"},
                        payload={"source_master_path": str(master_path), "generated_path": str(output_path), "replaced_placeholders": replaced_placeholders},
                    ).emit()
                    WorkerEvent(
                        event_type=EventType.RESUME_RENDERED,
                        run_id=args.run_id,
                        step_id=None,
                        severity=Severity.INFO,
                        message="Format-preserving DOCX resume rendered to local filesystem",
                        machine_state={"format": "DOCX", "review_only": False},
                        ui_state={"current_step": "document_review"},
                        payload=artifact.to_payload(),
                    ).emit()
                    pdf_export = export_docx_to_pdf(output_path, output_dir)
                    if pdf_export.ok and pdf_export.pdf_path:
                        pdf_artifact = metadata_for_existing_file(
                            path=pdf_export.pdf_path,
                            file_kind="RESUME",
                            format_name="PDF",
                            review_only=False,
                        )
                        WorkerEvent(
                            event_type=EventType.RESUME_RENDERED,
                            run_id=args.run_id,
                            step_id=None,
                            severity=Severity.INFO,
                            message="DOCX resume exported to PDF with a local converter",
                            machine_state={"format": "PDF", "exporter": pdf_export.exporter, "review_only": False},
                            ui_state={"current_step": "document_review"},
                            payload=pdf_artifact.to_payload(),
                        ).emit()
                        # One-page enforcement: count pages and retry with overflow instruction
                        from .documents.font_detection import count_pdf_pages
                        pages = count_pdf_pages(pdf_export.pdf_path)
                        if pages > 1 and llm_model and job_text:
                            overflow_tailored = asyncio.run(tailor_resume_sections(
                                job_description=_build_overflow_jd(job_text, pages),
                                resume_text=resume_text_for_tailor,
                                llm_client=LiteLlmClient(model=llm_model),
                                font_size=detected_font_size,
                            ))
                            if overflow_tailored:
                                overflow_bullet_map: dict[str, list[str]] = {}
                                for i in range(4):
                                    ob = overflow_tailored.exp_bullets(i)
                                    if ob:
                                        overflow_bullet_map[f"{{{{APPLYO_EXP_{i}_BULLETS}}}}"] = ob
                                overflow_proj = overflow_tailored.all_project_bullets()
                                if overflow_proj:
                                    overflow_bullet_map["{{APPLYO_PROJECTS_BULLETS}}"] = overflow_proj
                                retry_export = _remutate_and_export(master_path, output_path, replacements, overflow_bullet_map, output_dir)
                                if retry_export.ok and retry_export.pdf_path:
                                    pages = count_pdf_pages(retry_export.pdf_path)
                                    pdf_export = retry_export
                        if pages > 1:
                            WorkerEvent(
                                event_type=EventType.VALIDATION_FAILED,
                                run_id=args.run_id,
                                step_id=None,
                                severity=Severity.WARN,
                                message="Tailored resume overflows one page",
                                machine_state={"format": "PDF", "pages": pages},
                                ui_state={"current_step": "document_review", "requires_user_review": True},
                                payload={
                                    "artifact_kind": "resume",
                                    "blocking_issues": [{"code": "RESUME_OVERFLOWS_ONE_PAGE"}],
                                    "pages": pages,
                                    "pdf_path": str(pdf_export.pdf_path),
                                },
                            ).emit()
                    else:
                        WorkerEvent(
                            event_type=EventType.VALIDATION_FAILED,
                            run_id=args.run_id,
                            step_id=None,
                            severity=Severity.WARN,
                            message="DOCX resume was tailored but PDF export did not complete",
                            machine_state={"format": "DOCX", "exporter": pdf_export.exporter, "reason": pdf_export.code},
                            ui_state={"current_step": "document_review", "requires_user_review": True},
                            payload={
                                "artifact_kind": "resume",
                                "format": "DOCX",
                                "source_docx_path": str(output_path),
                                "stdout": pdf_export.stdout[-4000:],
                                "stderr": pdf_export.stderr[-4000:],
                                "blocking_issues": [{"code": pdf_export.code or "DOCX_PDF_EXPORT_FAILED"}],
                            },
                        ).emit()
                else:
                    # Anchor-free fallback: build a fresh DOCX from canonical profile
                    output_path.unlink(missing_ok=True)
                    try:
                        from .documents.font_detection import detect_resume_font_size
                        fallback_font_size = detect_resume_font_size(master_path)
                        build_resume_docx(
                            canonical_profile=canonical_profile,
                            tailoring_plan=tailoring_plan,
                            output_path=output_path,
                            font_size=fallback_font_size,
                        )
                        fallback_artifact = metadata_for_existing_file(
                            path=output_path,
                            file_kind="RESUME",
                            format_name="DOCX",
                            review_only=True,
                        )
                        WorkerEvent(
                            event_type=EventType.RESUME_RENDERED,
                            run_id=args.run_id,
                            step_id=None,
                            severity=Severity.WARN,
                            message="Anchor-free DOCX fallback generated from canonical profile (no master anchors found)",
                            machine_state={"source_format": "DOCX", "fallback": True, "review_only": True},
                            ui_state={"current_step": "document_review", "requires_user_review": True},
                            payload=fallback_artifact.to_payload(),
                        ).emit()
                        fallback_pdf = export_docx_to_pdf(output_path, output_dir)
                        if fallback_pdf.ok and fallback_pdf.pdf_path:
                            fallback_pdf_artifact = metadata_for_existing_file(
                                path=fallback_pdf.pdf_path,
                                file_kind="RESUME",
                                format_name="PDF",
                                review_only=True,
                            )
                            WorkerEvent(
                                event_type=EventType.RESUME_RENDERED,
                                run_id=args.run_id,
                                step_id=None,
                                severity=Severity.WARN,
                                message="Anchor-free DOCX fallback exported to PDF",
                                machine_state={"format": "PDF", "fallback": True, "review_only": True},
                                ui_state={"current_step": "document_review", "requires_user_review": True},
                                payload=fallback_pdf_artifact.to_payload(),
                            ).emit()
                    except Exception as _fallback_exc:
                        WorkerEvent(
                            event_type=EventType.USER_REVIEW_REQUIRED,
                            run_id=args.run_id,
                            step_id=None,
                            severity=Severity.WARN,
                            message="Verified DOCX master has no explicit Applyocalypse anchors for safe mutation",
                            machine_state={"source_format": "DOCX", "source_master_path": str(master_path)},
                            ui_state={"requires_user_review": True},
                            payload={"code": "MISSING_DOCX_ANCHORS", "source_master_path": str(master_path)},
                        ).emit()
            elif master_format == "TEX":
                output_path = choose_collision_safe_path(
                    output_dir,
                    build_generated_filename(
                        GeneratedNameInput(
                            first_name=first_name,
                            last_name=last_name,
                            company=company,
                            role=role,
                            kind="Resume",
                            extension="tex",
                        )
                    ),
                )
                tex_replacements = {placeholder: tex_escape(replacement) for placeholder, replacement in replacements.items()}
                _, replaced_placeholders = mutate_tex_placeholders(master_path, output_path, tex_replacements)

                # Final-file validation gate: catch any banned content in the mutated TEX
                tex_final_report = TextArtifactValidator().validate_file(output_path, artifact_kind="resume") if output_path.exists() else None
                if tex_final_report is not None and not tex_final_report.passed:
                    WorkerEvent(
                        event_type=EventType.VALIDATION_FAILED,
                        run_id=args.run_id,
                        step_id=None,
                        severity=Severity.ERROR,
                        message="Mutated TEX resume failed deterministic validation",
                        machine_state={"format": "TEX", "review_only": False},
                        ui_state={"current_step": "document_review", "requires_user_review": True},
                        payload={"artifact_kind": "resume", "stage": "final_file", "generated_path": str(output_path), **tex_final_report.to_dict()},
                    ).emit()

                if replaced_placeholders:
                    artifact = metadata_for_existing_file(path=output_path, file_kind="RESUME", format_name="TEX", review_only=False)
                    WorkerEvent(
                        event_type=EventType.RESUME_MUTATION_COMPLETED,
                        run_id=args.run_id,
                        step_id=None,
                        severity=Severity.INFO,
                        message="TEX editable master mutated through explicit Applyocalypse anchors",
                        machine_state={"source_format": "TEX", "replaced_placeholders": replaced_placeholders},
                        ui_state={"current_step": "document_review"},
                        payload={"source_master_path": str(master_path), "generated_path": str(output_path), "replaced_placeholders": replaced_placeholders},
                    ).emit()
                    WorkerEvent(
                        event_type=EventType.RESUME_RENDERED,
                        run_id=args.run_id,
                        step_id=None,
                        severity=Severity.INFO,
                        message="Format-preserving TEX resume rendered to local filesystem",
                        machine_state={"format": "TEX", "review_only": False},
                        ui_state={"current_step": "document_review"},
                        payload=artifact.to_payload(),
                    ).emit()
                    compile_result = compile_tex_with_tectonic(output_path, output_dir)
                    if compile_result.ok and compile_result.pdf_path:
                        pdf_artifact = metadata_for_existing_file(
                            path=compile_result.pdf_path,
                            file_kind="RESUME",
                            format_name="PDF",
                            review_only=False,
                        )
                        WorkerEvent(
                            event_type=EventType.RESUME_RENDERED,
                            run_id=args.run_id,
                            step_id=None,
                            severity=Severity.INFO,
                            message="TEX resume compiled to PDF with Tectonic",
                            machine_state={"format": "PDF", "compiler": "tectonic", "review_only": False},
                            ui_state={"current_step": "document_review"},
                            payload=pdf_artifact.to_payload(),
                        ).emit()
                    else:
                        WorkerEvent(
                            event_type=EventType.VALIDATION_FAILED,
                            run_id=args.run_id,
                            step_id=None,
                            severity=Severity.WARN,
                            message="TEX resume was tailored but Tectonic PDF compilation did not complete",
                            machine_state={"format": "TEX", "compiler": "tectonic", "reason": "TEX_COMPILE_FAILED"},
                            ui_state={"current_step": "document_review", "requires_user_review": True},
                            payload={
                                "artifact_kind": "resume",
                                "source_tex_path": str(output_path),
                                "stdout": compile_result.stdout[-4000:],
                                "stderr": compile_result.stderr[-4000:],
                                "blocking_issues": [{"code": "TEX_COMPILE_FAILED"}],
                            },
                        ).emit()
                else:
                    output_path.unlink(missing_ok=True)
                    WorkerEvent(
                        event_type=EventType.USER_REVIEW_REQUIRED,
                        run_id=args.run_id,
                        step_id=None,
                        severity=Severity.WARN,
                        message="Verified TEX master has no explicit Applyocalypse anchors for safe mutation",
                        machine_state={"source_format": "TEX", "source_master_path": str(master_path)},
                        ui_state={"requires_user_review": True},
                        payload={"code": "MISSING_TEX_ANCHORS", "source_master_path": str(master_path)},
                    ).emit()

        if analysis["cover_letter_likely_required"]:
            WorkerEvent(
                event_type=EventType.COVER_LETTER_REQUIRED,
                run_id=args.run_id,
                step_id=None,
                severity=Severity.INFO,
                message="Cover letter appears required by the job description",
                machine_state={"source": "JD_ANALYSIS"},
                ui_state={"current_step": "cover_letter"},
                payload={"required": True, "source": "JD_ANALYSIS"},
            ).emit()
            cl_llm_model = os.getenv("LITELLM_MODEL_STRONG") or os.getenv("LITELLM_MODEL")
            cover_letter_content: str | None = None
            cl_generation_mode = "DETERMINISTIC"
            if cl_llm_model and job_text:
                generated = asyncio.run(generate_cover_letter(
                    job_description=job_text,
                    canonical_profile=canonical_profile,
                    cover_letter_sample=cover_letter_sample_text,
                    llm_client=LiteLlmClient(model=cl_llm_model),
                ))
                if generated:
                    cover_letter_content = generated.text
                    cl_generation_mode = "LLM"
            if cover_letter_content is None:
                cover_letter_content = build_cover_letter_text(
                    canonical_profile=canonical_profile,
                    job_metadata=job_metadata,
                    tailoring_plan=tailoring_plan,
                )
                cl_generation_mode = "DETERMINISTIC"

            if cover_letter_content:
                cover_letter_report = TextArtifactValidator().validate(cover_letter_content, artifact_kind="cover_letter")
                cover_letter_report_path = work_dir / "cover-letter-validation-report.json"
                cover_letter_report_path.write_text(json.dumps(cover_letter_report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
                if cover_letter_report.passed:
                    cl_filename_input = GeneratedNameInput(
                        first_name=first_name,
                        last_name=last_name,
                        company=company,
                        role=role,
                        kind="Cover Letter",
                        extension="docx",
                    )
                    cl_filename = build_generated_filename(cl_filename_input)
                    cl_docx_path = choose_collision_safe_path(output_dir, cl_filename)
                    build_cover_letter_docx(cover_letter_content, canonical_profile, cl_docx_path)
                    cover_letter_artifact = metadata_for_existing_file(
                        path=cl_docx_path,
                        file_kind="COVER_LETTER",
                        format_name="DOCX",
                        review_only=True,
                    )
                    WorkerEvent(
                        event_type=EventType.COVER_LETTER_RENDERED,
                        run_id=args.run_id,
                        step_id=None,
                        severity=Severity.INFO,
                        message="Cover letter review artifact rendered to local filesystem",
                        machine_state={"format": "DOCX", "review_only": True, "generation_mode": cl_generation_mode},
                        ui_state={"current_step": "document_review"},
                        payload={**cover_letter_artifact.to_payload(), "validation_report_path": str(cover_letter_report_path)},
                    ).emit()
                    pdf_export = export_docx_to_pdf(cl_docx_path, output_dir)
                    if pdf_export.ok and pdf_export.pdf_path:
                        pdf_artifact = metadata_for_existing_file(
                            path=pdf_export.pdf_path,
                            file_kind="COVER_LETTER",
                            format_name="PDF",
                            review_only=True,
                        )
                        WorkerEvent(
                            event_type=EventType.COVER_LETTER_RENDERED,
                            run_id=args.run_id,
                            step_id=None,
                            severity=Severity.INFO,
                            message="Cover letter PDF exported",
                            machine_state={"format": "PDF", "review_only": True, "generation_mode": cl_generation_mode},
                            ui_state={"current_step": "document_review"},
                            payload={**pdf_artifact.to_payload(), "validation_report_path": str(cover_letter_report_path)},
                        ).emit()
                else:
                    WorkerEvent(
                        event_type=EventType.VALIDATION_FAILED,
                        run_id=args.run_id,
                        step_id=None,
                        severity=Severity.ERROR,
                        message="Cover letter artifact failed validation",
                        machine_state={"format": "DOCX", "review_only": True, "generation_mode": cl_generation_mode},
                        ui_state={"current_step": "document_review", "requires_user_review": True},
                        payload={"artifact_kind": "cover_letter", "validation_report_path": str(cover_letter_report_path), **cover_letter_report.to_dict()},
                    ).emit()
            else:
                WorkerEvent(
                    event_type=EventType.VALIDATION_FAILED,
                    run_id=args.run_id,
                    step_id=None,
                    severity=Severity.WARN,
                    message="Cover letter requires more verified profile evidence before generation",
                    machine_state={"reason": "INSUFFICIENT_VERIFIED_EVIDENCE"},
                    ui_state={"current_step": "document_review", "requires_user_review": True},
                    payload={"artifact_kind": "cover_letter", "blocking_issues": [{"code": "INSUFFICIENT_VERIFIED_EVIDENCE"}]},
                ).emit()

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
