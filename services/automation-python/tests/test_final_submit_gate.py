"""CLAUDE.md safety invariant #1: no auto-submit without the explicit approval gate.

A user who turns auto-submit on is preapproving *the submission of this
application*, not "click whatever button the run happens to be looking at". For
portals whose plan declares a review step (Workday, iCIMS), the plan already
recorded ``review_text_detected`` as evidence and nothing evaluated it, so a run
that ended up on a mid-wizard page with a "Submit" button would fire the
preapproved click there.

``evaluate_final_submit_gate`` is that evaluation. These tests pin the direction
it is allowed to move the decision: it may withdraw a preapproval, never grant
one.
"""
from __future__ import annotations

import pytest

from applyocalypse_automation.browser.portal_adapters import portal_runtime_policy_for_workflow
from applyocalypse_automation.browser.portal_workflows import workflow_for_url
from applyocalypse_automation.runner import evaluate_final_submit_gate

REVIEW_PORTAL_URL = "https://acme.wd5.myworkdayjobs.com/en-US/careers/job/123"
NO_REVIEW_PORTAL_URL = "https://boards.greenhouse.io/example/jobs/123"

REVIEW_PAGE_TEXT = "Review your application before submitting"
MID_WIZARD_TEXT = "My Experience. Add your work history and click Save and Continue."


def policy_for(url: str):
    return portal_runtime_policy_for_workflow(workflow_for_url(url))


def test_preapproval_survives_when_the_promised_review_page_is_actually_there() -> None:
    gate = evaluate_final_submit_gate(
        policy=policy_for(REVIEW_PORTAL_URL), auto_submit_enabled=True, visible_text=REVIEW_PAGE_TEXT
    )

    assert gate.auto_submit_enabled is True
    assert gate.review_text_detected is True
    assert gate.withdrawn is False


def test_preapproval_is_withdrawn_when_the_promised_review_page_is_missing() -> None:
    """A Submit button on a mid-wizard page is not the submission the user approved."""
    gate = evaluate_final_submit_gate(
        policy=policy_for(REVIEW_PORTAL_URL), auto_submit_enabled=True, visible_text=MID_WIZARD_TEXT
    )

    assert gate.auto_submit_enabled is False
    assert gate.review_text_detected is False
    assert gate.withdrawn is True
    assert "review page" in gate.message


def test_an_unreadable_page_is_not_evidence_that_the_review_screen_is_there() -> None:
    gate = evaluate_final_submit_gate(
        policy=policy_for(REVIEW_PORTAL_URL), auto_submit_enabled=True, visible_text=None
    )

    assert gate.auto_submit_enabled is False
    assert gate.withdrawn is True


@pytest.mark.parametrize("visible_text", [REVIEW_PAGE_TEXT, MID_WIZARD_TEXT, "", None])
def test_the_gate_never_grants_an_approval_the_user_did_not_give(visible_text: str | None) -> None:
    """Seeing a review page is not consent. Only the user's setting is.

    Parametrized over both portal kinds so neither branch of the policy check can
    turn an absent preapproval into a present one.
    """
    for url in (REVIEW_PORTAL_URL, NO_REVIEW_PORTAL_URL):
        gate = evaluate_final_submit_gate(
            policy=policy_for(url), auto_submit_enabled=False, visible_text=visible_text
        )

        assert gate.auto_submit_enabled is False, url
        assert gate.withdrawn is False, f"{url}: nothing was withdrawn; there was no preapproval"
        assert "gated until explicit approval" in gate.message, url


@pytest.mark.parametrize("visible_text", [REVIEW_PAGE_TEXT, MID_WIZARD_TEXT, "", None])
def test_a_portal_that_promises_no_review_page_is_not_penalised_for_lacking_one(
    visible_text: str | None,
) -> None:
    """Greenhouse submits from the form itself. Demanding review text would gate every run."""
    policy = policy_for(NO_REVIEW_PORTAL_URL)
    assert policy.review_evidence_required is False

    gate = evaluate_final_submit_gate(policy=policy, auto_submit_enabled=True, visible_text=visible_text)

    assert gate.auto_submit_enabled is True
    assert gate.review_text_detected is None
    assert gate.withdrawn is False
