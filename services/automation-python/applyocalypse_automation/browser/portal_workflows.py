from __future__ import annotations

from dataclasses import dataclass

from .portal_registry import PortalDefinition, detect_portal


@dataclass(frozen=True, slots=True)
class PortalWorkflow:
    portal_id: str
    display_name: str
    workflow_kind: str
    default_adapter: str
    requires_high_stealth: bool
    entry_action_labels: tuple[str, ...]
    requires_login_watch: bool
    requires_external_redirect_watch: bool
    requires_manual_review_before_fill: bool
    expected_steps: tuple[str, ...]
    review_checkpoints: tuple[str, ...]
    notes: tuple[str, ...]

    def to_event_payload(self) -> dict[str, object]:
        return {
            "portal_id": self.portal_id,
            "display_name": self.display_name,
            "workflow_kind": self.workflow_kind,
            "default_adapter": self.default_adapter,
            "requires_high_stealth": self.requires_high_stealth,
            "entry_action_labels": list(self.entry_action_labels),
            "requires_login_watch": self.requires_login_watch,
            "requires_external_redirect_watch": self.requires_external_redirect_watch,
            "requires_manual_review_before_fill": self.requires_manual_review_before_fill,
            "expected_steps": list(self.expected_steps),
            "review_checkpoints": list(self.review_checkpoints),
            "notes": list(self.notes),
        }


ATS_ENTRY_ACTIONS: dict[str, tuple[str, ...]] = {
    "workday": ("Apply", "Apply Manually", "Start Application", "Apply Now"),
    "greenhouse": ("Apply for this job", "Apply now"),
    "lever": ("Apply for this job", "Apply now"),
    "ashby": ("Apply for this Job", "Apply now", "Apply"),
    "icims": ("Apply Now", "Apply for this job"),
    "taleo": ("Apply Online", "Apply", "Start"),
    "governmentjobs": ("Apply", "Apply Online"),
    "usajobs": ("Apply", "Apply on company site"),
    "ncs": ("Apply", "Apply Now"),
}

HIGH_STEALTH_ENTRY_ACTIONS: dict[str, tuple[str, ...]] = {
    "careerbuilder": ("Apply Now", "Apply"),
    "dice": ("Apply Now", "Apply"),
    "foundit": ("Apply", "Apply Now"),
    "freshersworld": ("Apply Now", "Apply"),
    "glassdoor": ("Apply Now", "Easy Apply"),
    "hirist": ("Apply", "Apply Now"),
    "iimjobs": ("Apply", "Apply Now"),
    "indeed": ("Apply now", "Apply on company site"),
    "instahyre": ("Apply", "Apply Now"),
    "linkedin": ("Easy Apply", "Apply"),
    "monster": ("Apply Now", "Apply"),
    "naukri": ("Apply", "Register to apply"),
    "otta": ("Apply", "Apply now"),
    "shine": ("Apply", "Apply Now"),
    "timesjobs": ("Apply", "Apply Now"),
    "wellfound": ("Apply", "Apply Now"),
    "ziprecruiter": ("Apply Now", "1-Click Apply"),
}


def workflow_for_portal(portal: PortalDefinition | None) -> PortalWorkflow:
    if portal is None:
        return PortalWorkflow(
            portal_id="unknown",
            display_name="Unknown portal",
            workflow_kind="GENERIC_REVIEW_FIRST",
            default_adapter="nodriver",
            requires_high_stealth=True,
            entry_action_labels=(),
            requires_login_watch=True,
            requires_external_redirect_watch=True,
            requires_manual_review_before_fill=True,
            expected_steps=(
                "Open target page",
                "Capture diagnostics",
                "Wait for user confirmation before field detection",
                "Review fields and answers",
                "Gate final submit",
            ),
            review_checkpoints=("Portal identity", "Ambiguous questions", "Document approval", "Final submit"),
            notes=("Unknown portal. Detect fields only after user review.",),
        )

    if portal.portal_id in ATS_ENTRY_ACTIONS:
        return PortalWorkflow(
            portal_id=portal.portal_id,
            display_name=portal.display_name,
            workflow_kind="ATS_DIRECT_FORM",
            default_adapter=portal.default_adapter,
            requires_high_stealth=portal.requires_high_stealth,
            entry_action_labels=ATS_ENTRY_ACTIONS[portal.portal_id],
            requires_login_watch=portal.portal_id in {"workday", "taleo", "governmentjobs", "usajobs", "ncs"},
            requires_external_redirect_watch=False,
            requires_manual_review_before_fill=True,
            expected_steps=(
                "Open ATS job page",
                "Click known apply/start action",
                "Capture form diagnostics",
                "Detect required fields and uploads",
                "Review answers before fill",
                "Upload reviewed documents",
                "Gate final submit",
            ),
            review_checkpoints=("Login/MFA/CAPTCHA", "Sensitive questions", "Document approval", "Final submit"),
            notes=(
                "Click only known apply/start actions.",
                "Pause on login, CAPTCHA, MFA, OTP, ambiguous questions, and final submit.",
            ),
        )

    return PortalWorkflow(
        portal_id=portal.portal_id,
        display_name=portal.display_name,
        workflow_kind="JOB_BOARD_REDIRECT_OR_STEALTH",
        default_adapter=portal.default_adapter,
        requires_high_stealth=portal.requires_high_stealth,
        entry_action_labels=HIGH_STEALTH_ENTRY_ACTIONS.get(portal.portal_id, ()),
        requires_login_watch=True,
        requires_external_redirect_watch=True,
        requires_manual_review_before_fill=True,
        expected_steps=(
            "Open job-board listing",
            "Click known apply action when safe",
            "Observe redirect or embedded form",
            "Confirm trusted application surface",
            "Review fields and answers",
            "Gate final submit",
        ),
        review_checkpoints=("Login/MFA/CAPTCHA", "Redirect trust", "Sensitive questions", "Final submit"),
        notes=(
            "Job board flow may redirect to ATS or require login.",
            "Use Nodriver by default for high-stealth portals and pause on uncertainty.",
        ),
    )


def workflow_for_url(url: str) -> PortalWorkflow:
    return workflow_for_portal(detect_portal(url))
