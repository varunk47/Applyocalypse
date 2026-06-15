from __future__ import annotations

from dataclasses import dataclass

from .portal_workflows import PortalWorkflow

COMMON_STEP_PROGRESSION_LABELS = (
    "Next",
    "Continue",
    "Continue application",
    "Continue to next step",
    "Save and continue",
    "Save & continue",
    "Review",
    "Review application",
    "Continue to review",
)

COMMON_FINAL_SUBMIT_LABELS = (
    "Submit",
    "Submit application",
    "Send application",
    "Finish application",
    "Complete application",
)


@dataclass(frozen=True, slots=True)
class PortalStepPolicy:
    step_id: str
    title: str
    allowed_labels: tuple[str, ...]
    required_review_gate: str
    evidence_signals: tuple[str, ...]
    notes: tuple[str, ...] = ()

    def to_event_payload(self) -> dict[str, object]:
        return {
            "step_id": self.step_id,
            "title": self.title,
            "allowed_labels": list(self.allowed_labels),
            "required_review_gate": self.required_review_gate,
            "evidence_signals": list(self.evidence_signals),
            "notes": list(self.notes),
        }


@dataclass(frozen=True, slots=True)
class PortalAdapterPlan:
    portal_id: str
    display_name: str
    workflow_kind: str
    max_automated_steps: int
    entry_action_labels: tuple[str, ...]
    step_progression_labels: tuple[str, ...]
    final_submit_labels: tuple[str, ...]
    required_review_gates: tuple[str, ...]
    material_field_hints: tuple[str, ...]
    steps: tuple[PortalStepPolicy, ...]
    live_certification_status: str
    notes: tuple[str, ...]

    def to_event_payload(self) -> dict[str, object]:
        return {
            "portal_id": self.portal_id,
            "display_name": self.display_name,
            "workflow_kind": self.workflow_kind,
            "max_automated_steps": self.max_automated_steps,
            "entry_action_labels": list(self.entry_action_labels),
            "step_progression_labels": list(self.step_progression_labels),
            "final_submit_labels": list(self.final_submit_labels),
            "required_review_gates": list(self.required_review_gates),
            "material_field_hints": list(self.material_field_hints),
            "steps": [step.to_event_payload() for step in self.steps],
            "live_certification_status": self.live_certification_status,
            "notes": list(self.notes),
        }


def _step(
    step_id: str,
    title: str,
    allowed_labels: tuple[str, ...],
    required_review_gate: str,
    evidence_signals: tuple[str, ...],
    notes: tuple[str, ...] = (),
) -> PortalStepPolicy:
    return PortalStepPolicy(
        step_id=step_id,
        title=title,
        allowed_labels=allowed_labels,
        required_review_gate=required_review_gate,
        evidence_signals=evidence_signals,
        notes=notes,
    )


ATS_ADAPTER_PLANS: dict[str, PortalAdapterPlan] = {
    "workday": PortalAdapterPlan(
        portal_id="workday",
        display_name="Workday",
        workflow_kind="ATS_DIRECT_FORM",
        max_automated_steps=6,
        entry_action_labels=("Apply", "Apply Manually", "Start Application", "Apply Now"),
        step_progression_labels=("Next", "Save and continue", "Review", "Submit"),
        final_submit_labels=("Submit", "Submit application"),
        required_review_gates=("LOGIN", "MFA", "SENSITIVE_QUESTION", "DOCUMENT", "PORTAL_STEP", "FINAL_SUBMIT"),
        material_field_hints=("resume", "cv", "cover letter", "additional documents"),
        steps=(
            _step("start", "Start application", ("Apply", "Apply Manually", "Start Application"), "PORTAL_ENTRY", ("known_workday_host",)),
            _step("account", "Account and contact", ("Next", "Save and continue"), "LOGIN", ("password_field_absent_or_user_resolved",)),
            _step("experience", "Experience and documents", ("Next", "Save and continue"), "DOCUMENT", ("file_inputs_detected",)),
            _step("questions", "Application questions", ("Next", "Save and continue"), "SENSITIVE_QUESTION", ("required_fields_detected",)),
            _step("review", "Review application", ("Review", "Next"), "PORTAL_STEP", ("review_text_detected",)),
            _step("submit", "Submit application", ("Submit", "Submit application"), "FINAL_SUBMIT", ("confirmation_required_after_click",)),
        ),
        live_certification_status="REQUIRES_ACCOUNT_FIXTURES",
        notes=("Workday flows are tenant-configurable. Account and questionnaire steps must remain review-gated.",),
    ),
    "greenhouse": PortalAdapterPlan(
        portal_id="greenhouse",
        display_name="Greenhouse",
        workflow_kind="ATS_DIRECT_FORM",
        max_automated_steps=4,
        entry_action_labels=("Apply for this job", "Apply now"),
        step_progression_labels=("Next", "Continue", "Submit application"),
        final_submit_labels=("Submit application",),
        required_review_gates=("SENSITIVE_QUESTION", "DOCUMENT", "FINAL_SUBMIT"),
        material_field_hints=("resume", "cover letter"),
        steps=(
            _step("entry", "Open application form", ("Apply for this job", "Apply now"), "PORTAL_ENTRY", ("known_greenhouse_host",)),
            _step("fields", "Candidate fields", ("Next", "Continue"), "ANSWER", ("application_form_detected", "required_fields_detected")),
            _step("documents", "Resume and cover letter", ("Next", "Continue"), "DOCUMENT", ("file_inputs_detected",)),
            _step("submit", "Submit application", ("Submit application",), "FINAL_SUBMIT", ("confirmation_required_after_click",)),
        ),
        live_certification_status="REQUIRES_LIVE_JOB_FIXTURES",
        notes=("Greenhouse may expose all fields on one page or defer EEO questions to later panels.",),
    ),
    "lever": PortalAdapterPlan(
        portal_id="lever",
        display_name="Lever",
        workflow_kind="ATS_DIRECT_FORM",
        max_automated_steps=4,
        entry_action_labels=("Apply for this job", "Apply now"),
        step_progression_labels=("Next", "Continue", "Review application", "Submit application"),
        final_submit_labels=("Submit application",),
        required_review_gates=("SENSITIVE_QUESTION", "DOCUMENT", "FINAL_SUBMIT"),
        material_field_hints=("resume", "cv", "cover letter", "additional information"),
        steps=(
            _step("entry", "Open apply panel", ("Apply for this job", "Apply now"), "PORTAL_ENTRY", ("known_lever_host",)),
            _step("profile", "Profile fields", ("Next", "Continue"), "ANSWER", ("candidate_fields_detected",)),
            _step("review", "Review answers", ("Review application", "Continue"), "PORTAL_STEP", ("review_text_detected",)),
            _step("submit", "Submit application", ("Submit application",), "FINAL_SUBMIT", ("confirmation_required_after_click",)),
        ),
        live_certification_status="REQUIRES_LIVE_JOB_FIXTURES",
        notes=("Lever commonly mixes resume upload, profile fields, and optional questions on a compact form.",),
    ),
    "icims": PortalAdapterPlan(
        portal_id="icims",
        display_name="iCIMS",
        workflow_kind="ATS_DIRECT_FORM",
        max_automated_steps=6,
        entry_action_labels=("Apply Now", "Apply for this job"),
        step_progression_labels=("Next", "Continue", "Save and Continue", "Review", "Submit Profile"),
        final_submit_labels=("Submit Profile", "Submit application"),
        required_review_gates=("LOGIN", "SENSITIVE_QUESTION", "DOCUMENT", "PORTAL_STEP", "FINAL_SUBMIT"),
        material_field_hints=("resume", "cv", "cover letter", "profile attachment"),
        steps=(
            _step("entry", "Open application", ("Apply Now", "Apply for this job"), "PORTAL_ENTRY", ("known_icims_host",)),
            _step("login", "Login or create profile", ("Next", "Continue"), "LOGIN", ("password_or_account_prompt_checked",)),
            _step("profile", "Candidate profile", ("Next", "Save and Continue"), "ANSWER", ("required_fields_detected",)),
            _step("documents", "Profile attachments", ("Next", "Save and Continue"), "DOCUMENT", ("file_inputs_detected",)),
            _step("review", "Review profile", ("Review", "Next"), "PORTAL_STEP", ("review_text_detected",)),
            _step("submit", "Submit profile", ("Submit Profile", "Submit application"), "FINAL_SUBMIT", ("confirmation_required_after_click",)),
        ),
        live_certification_status="REQUIRES_ACCOUNT_FIXTURES",
        notes=("iCIMS frequently requires account flows. Automation must pause for login and profile creation.",),
    ),
    "taleo": PortalAdapterPlan(
        portal_id="taleo",
        display_name="Taleo",
        workflow_kind="ATS_DIRECT_FORM",
        max_automated_steps=6,
        entry_action_labels=("Apply Online", "Apply", "Start"),
        step_progression_labels=("Next", "Save and Continue", "Continue", "Review", "Submit"),
        final_submit_labels=("Submit", "Submit application"),
        required_review_gates=("LOGIN", "MFA", "SENSITIVE_QUESTION", "DOCUMENT", "PORTAL_STEP", "FINAL_SUBMIT"),
        material_field_hints=("resume", "cv", "cover letter", "attachments"),
        steps=(
            _step("entry", "Open Taleo flow", ("Apply Online", "Apply", "Start"), "PORTAL_ENTRY", ("known_taleo_host",)),
            _step("candidate", "Candidate profile", ("Next", "Save and Continue"), "LOGIN", ("returning_candidate_prompt_checked",)),
            _step("documents", "Attachments", ("Next", "Save and Continue"), "DOCUMENT", ("file_inputs_detected",)),
            _step("questions", "Prescreen questions", ("Next", "Continue"), "SENSITIVE_QUESTION", ("questionnaire_detected",)),
            _step("review", "Review application", ("Review", "Next"), "PORTAL_STEP", ("review_text_detected",)),
            _step("submit", "Submit", ("Submit", "Submit application"), "FINAL_SUBMIT", ("confirmation_required_after_click",)),
        ),
        live_certification_status="REQUIRES_ACCOUNT_FIXTURES",
        notes=("Taleo tenants vary heavily. Keep six-step cap and manual review on each uncertain transition.",),
    ),
}


def portal_adapter_plan_for_workflow(workflow: PortalWorkflow) -> PortalAdapterPlan:
    plan = ATS_ADAPTER_PLANS.get(workflow.portal_id)
    if plan:
        return plan
    return PortalAdapterPlan(
        portal_id=workflow.portal_id,
        display_name=workflow.display_name,
        workflow_kind=workflow.workflow_kind,
        max_automated_steps=4 if workflow.workflow_kind == "ATS_DIRECT_FORM" else 2,
        entry_action_labels=workflow.entry_action_labels,
        step_progression_labels=COMMON_STEP_PROGRESSION_LABELS,
        final_submit_labels=COMMON_FINAL_SUBMIT_LABELS,
        required_review_gates=("LOGIN", "CAPTCHA", "MFA", "OTP", "SENSITIVE_QUESTION", "FINAL_SUBMIT"),
        material_field_hints=("resume", "cv", "cover letter"),
        steps=(
            _step("entry", "Open application surface", workflow.entry_action_labels, "PORTAL_ENTRY", ("portal_detected",)),
            _step("review", "Review detected fields", COMMON_STEP_PROGRESSION_LABELS, "ANSWER", ("required_fields_detected",)),
            _step("submit", "Gate final submit", COMMON_FINAL_SUBMIT_LABELS, "FINAL_SUBMIT", ("confirmation_required_after_click",)),
        ),
        live_certification_status="REQUIRES_PORTAL_SPECIFIC_ADAPTER",
        notes=("Generic adapter plan. Pause on every uncertain portal transition.",),
    )


def progression_labels_for_workflow(workflow: PortalWorkflow) -> tuple[str, ...]:
    return portal_adapter_plan_for_workflow(workflow).step_progression_labels


def final_submit_labels_for_workflow(workflow: PortalWorkflow) -> tuple[str, ...]:
    return portal_adapter_plan_for_workflow(workflow).final_submit_labels
