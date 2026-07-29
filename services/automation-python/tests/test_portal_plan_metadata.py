"""Portal registry consistency and adapter-plan metadata well-formedness.

Two audit findings are covered here:

* every per-portal lookup table must be keyed by a *registered* portal id, so a
  quirk or entry action can never be silently unreachable; and
* the per-portal plan metadata (step cap, review evidence) must be well-formed
  and reachable through a real accessor, instead of being decorative fields that
  nothing can evaluate at runtime.
"""
from __future__ import annotations

import pytest

from applyocalypse_automation.browser.portal_adapters import (
    ATS_ADAPTER_PLANS,
    FILL_CAPABILITY_STATUSES,
    FILL_CAPABILITY_UNPROVEN,
    KNOWN_EVIDENCE_SIGNALS,
    KNOWN_REVIEW_GATES,
    PortalAdapterPlan,
    portal_adapter_plan_for_workflow,
    portal_runtime_policy_for_workflow,
)
from applyocalypse_automation.browser.portal_registry import PORTALS
from applyocalypse_automation.browser.portal_workflows import (
    ATS_ENTRY_ACTIONS,
    ATS_PORTAL_QUIRKS,
    workflow_for_url,
)

REGISTERED_PORTAL_IDS = frozenset(portal.portal_id for portal in PORTALS)

PORTAL_KEYED_TABLES = (
    ("ATS_PORTAL_QUIRKS", tuple(ATS_PORTAL_QUIRKS)),
    ("ATS_ENTRY_ACTIONS", tuple(ATS_ENTRY_ACTIONS)),
    ("ATS_ADAPTER_PLANS", tuple(ATS_ADAPTER_PLANS)),
)

TABLE_KEYS = tuple(
    (table_name, portal_id) for table_name, portal_ids in PORTAL_KEYED_TABLES for portal_id in portal_ids
)

ATS_URLS = {
    "workday": "https://acme.wd5.myworkdayjobs.com/en-US/careers/job/123",
    "greenhouse": "https://boards.greenhouse.io/example/jobs/123",
    "lever": "https://jobs.lever.co/example/abc",
    "ashby": "https://jobs.ashbyhq.com/example/aaaabbbb-cccc-dddd-eeee-ffff00001111",
    "icims": "https://acme.icims.com/jobs/123/job",
    "taleo": "https://acme.taleo.net/careersection/jobdetail.ftl?job=123",
}

GENERIC_URL = "https://www.indeed.com/viewjob?jk=1"

ALL_PLANS = tuple(ATS_ADAPTER_PLANS.values()) + (portal_adapter_plan_for_workflow(workflow_for_url(GENERIC_URL)),)


# ── Registry consistency ──────────────────────────────────────────────────────
@pytest.mark.parametrize(("table_name", "portal_id"), TABLE_KEYS)
def test_portal_keyed_tables_only_reference_registered_portals(table_name: str, portal_id: str) -> None:
    assert portal_id in REGISTERED_PORTAL_IDS, (
        f"{table_name} has an entry for '{portal_id}', which is not a registered portal_id. "
        "The entry is unreachable: either register the portal or drop the entry."
    )


# ── Plan metadata well-formedness ─────────────────────────────────────────────
@pytest.mark.parametrize("plan", ALL_PLANS, ids=lambda plan: plan.portal_id)
def test_plan_steps_are_well_formed(plan: PortalAdapterPlan) -> None:
    step_ids = [step.step_id for step in plan.steps]
    assert step_ids, f"{plan.portal_id}: a plan with no steps cannot gate anything"
    assert len(set(step_ids)) == len(step_ids), f"{plan.portal_id}: duplicate step ids {step_ids}"

    for step in plan.steps:
        assert step.required_review_gate in KNOWN_REVIEW_GATES, (
            f"{plan.portal_id}/{step.step_id}: unknown review gate '{step.required_review_gate}'"
        )
        unknown_signals = set(step.evidence_signals) - KNOWN_EVIDENCE_SIGNALS
        assert not unknown_signals, (
            f"{plan.portal_id}/{step.step_id}: evidence signals {sorted(unknown_signals)} are not "
            "declared in KNOWN_EVIDENCE_SIGNALS, so nothing at runtime can evaluate them"
        )

    final_steps = [step for step in plan.steps if step.required_review_gate == "FINAL_SUBMIT"]
    assert len(final_steps) == 1, f"{plan.portal_id}: expected exactly one FINAL_SUBMIT step"
    assert final_steps[0] is plan.steps[-1], f"{plan.portal_id}: the FINAL_SUBMIT step must be last"
    assert "FINAL_SUBMIT" in plan.required_review_gates


@pytest.mark.parametrize("plan", ALL_PLANS, ids=lambda plan: plan.portal_id)
def test_max_automated_steps_can_actually_cover_the_declared_steps(plan: PortalAdapterPlan) -> None:
    assert plan.max_automated_steps >= len(plan.steps), (
        f"{plan.portal_id}: the step cap ({plan.max_automated_steps}) is below the number of "
        f"declared steps ({len(plan.steps)}), so the plan can never be completed"
    )


# ── Runtime accessor (the half the runner consumes) ───────────────────────────
@pytest.mark.parametrize("portal_id", sorted(ATS_URLS))
def test_runtime_policy_mirrors_the_plan(portal_id: str) -> None:
    workflow = workflow_for_url(ATS_URLS[portal_id])
    plan = portal_adapter_plan_for_workflow(workflow)
    policy = portal_runtime_policy_for_workflow(workflow)

    assert policy.portal_id == portal_id
    assert policy.max_automated_steps == plan.max_automated_steps
    assert policy.final_submit_step_id == plan.steps[-1].step_id
    expected_review_required = any("review_text_detected" in step.evidence_signals for step in plan.steps)
    assert policy.review_evidence_required is expected_review_required
    if expected_review_required:
        assert policy.review_text_markers, f"{portal_id}: review evidence is required but no marker is declared"


def test_generic_workflow_gets_a_conservative_runtime_policy() -> None:
    policy = portal_runtime_policy_for_workflow(workflow_for_url(GENERIC_URL))

    assert policy.max_automated_steps <= 6
    assert policy.final_submit_step_id == "submit"


@pytest.mark.parametrize(
    ("visible_text", "expected"),
    [
        ("Review your application before submitting", True),
        ("Please review the information below", True),
        ("REVIEW AND SUBMIT", True),
        ("Application  review\n  page", True),
        ("Upload your resume", False),
        ("Peer review experience", False),
        ("", False),
    ],
)
def test_review_signal_observed_reads_visible_text(visible_text: str, expected: bool) -> None:
    policy = portal_runtime_policy_for_workflow(workflow_for_url(ATS_URLS["workday"]))

    assert policy.review_evidence_required is True
    assert policy.review_signal_observed(visible_text) is expected


# ── Fill capability honesty ───────────────────────────────────────────────────
@pytest.mark.parametrize("plan", ALL_PLANS, ids=lambda plan: plan.portal_id)
def test_fill_capability_status_is_declared_and_never_claims_unproven_success(plan: PortalAdapterPlan) -> None:
    assert plan.fill_capability_status in FILL_CAPABILITY_STATUSES
    assert plan.fill_capability_status != "LIVE_FILL_VERIFIED", (
        f"{plan.portal_id}: no portal has been exercised by a live fill-and-read-back run, "
        "so none may claim LIVE_FILL_VERIFIED"
    )
    assert plan.fill_capability_blockers, (
        f"{plan.portal_id}: a portal that is not live-verified must say what is still missing"
    )


def test_portal_without_a_specific_adapter_is_unproven() -> None:
    plan = portal_adapter_plan_for_workflow(workflow_for_url(GENERIC_URL))

    assert plan.fill_capability_status == FILL_CAPABILITY_UNPROVEN


def test_plan_event_payload_reports_fill_capability() -> None:
    payload = portal_adapter_plan_for_workflow(workflow_for_url(ATS_URLS["lever"])).to_event_payload()

    assert payload["fill_capability_status"] == ATS_ADAPTER_PLANS["lever"].fill_capability_status
    assert isinstance(payload["fill_capability_blockers"], list)
    assert "live_certification_status" not in payload, (
        "a reachability-only probe never certified anything; the key must not come back"
    )
