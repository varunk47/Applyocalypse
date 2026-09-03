from __future__ import annotations

import asyncio
import importlib.util
import json

from applyocalypse_automation.browser.adapter_factory import (
    SUPPORTED_BROWSER_ADAPTERS,
    adapter_candidates_for_workflow,
    create_browser_adapter,
)
from applyocalypse_automation.browser.field_detection import (
    blockers_from_dom_snapshot,
    build_apply_field_value_script,
    build_click_by_text_script,
    fields_from_dom_snapshot,
    parse_apply_field_result,
    parse_click_by_text_result,
)
from applyocalypse_automation.browser.portal_adapters import (
    final_submit_labels_for_workflow,
    portal_adapter_plan_for_workflow,
    progression_labels_for_workflow,
)
from applyocalypse_automation.browser.portal_registry import PORTALS, detect_portal
from applyocalypse_automation.browser.portal_state import classify_portal_page_state
from applyocalypse_automation.browser.portal_workflows import workflow_for_portal, workflow_for_url
from applyocalypse_automation.runner import SAFE_STEP_PROGRESSION_LABELS


def test_portal_registry_covers_requested_targets() -> None:
    portal_ids = {portal.portal_id for portal in PORTALS}

    assert {
        "indeed",
        "glassdoor",
        "ziprecruiter",
        "dice",
        "wellfound",
        "otta",
        "careerbuilder",
        "monster",
        "usajobs",
        "governmentjobs",
        "linkedin",
        "naukri",
        "instahyre",
        "hirist",
        "iimjobs",
        "foundit",
        "shine",
        "timesjobs",
        "freshersworld",
        "ncs",
        "workday",
        "greenhouse",
        "lever",
        "ashby",
        "icims",
        "taleo",
    }.issubset(portal_ids)


def test_browser_adapter_factory_keeps_nodriver_default_and_playwright_fallback() -> None:
    assert create_browser_adapter(None).name == "nodriver"
    assert create_browser_adapter("playwright").name == "playwright"


# Adapter name -> the third-party module its launch() imports. The playwright adapter is
# named for the protocol it speaks; patchright is the driver that speaks it.
_ADAPTER_DRIVER_MODULES = {
    "nodriver": "nodriver",
    "playwright": "patchright",
    "seleniumbase": "seleniumbase",
}


def test_every_portal_defaults_to_an_adapter_that_is_actually_installed() -> None:
    """A declared default nobody can launch is worse than a wrong default.

    Every ATS here used to declare "playwright", which is absent from
    requirements.in, from the lock file and from the PyInstaller hidden imports.
    On a real install the launch returned "playwright is not installed" and the
    run fell through to nodriver without ever saying so. Nothing looked broken,
    which is why it survived: the Playwright-only cross-origin frame support was
    simply never the code any user ran.

    Asserting against the installed environment is the point. A default that only
    works on a developer's machine is exactly the failure being pinned.
    """
    missing = sorted(
        {
            f"{portal.portal_id} -> {portal.default_adapter}"
            for portal in PORTALS
            if importlib.util.find_spec(_ADAPTER_DRIVER_MODULES[portal.default_adapter]) is None
        }
    )

    assert missing == [], f"portals default to adapters that are not installed: {missing}"


def test_adapter_driver_module_map_covers_every_supported_adapter() -> None:
    """Otherwise the check above silently stops covering a newly added adapter."""
    assert set(_ADAPTER_DRIVER_MODULES) == set(SUPPORTED_BROWSER_ADAPTERS)


def test_the_automatic_adapter_chain_never_offers_an_adapter_that_is_not_installed() -> None:
    """The declared default was only half of it; the fallback chain was the other half.

    Every ATS used to fall back nodriver -> playwright -> seleniumbase. With no
    playwright in the build, a nodriver failure spent a launch on an adapter that
    could not start and wrote that dead attempt into the record the UI shows, ahead
    of the seleniumbase fallback that could actually have worked.
    """
    offered = {
        name for portal in PORTALS for name in adapter_candidates_for_workflow(workflow_for_portal(portal))
    }
    not_installed = sorted(
        name for name in offered if importlib.util.find_spec(_ADAPTER_DRIVER_MODULES[name]) is None
    )

    assert not_installed == [], f"the automatic chain offers uninstalled adapters: {not_installed}"


def test_an_explicitly_named_adapter_leads_the_chain() -> None:
    """Naming an adapter moves it to the front; it never drops the others."""
    workflow = workflow_for_url("https://jobs.lever.co/example/abc")

    assert adapter_candidates_for_workflow(workflow, "playwright") == ("playwright", "nodriver", "seleniumbase")
    assert adapter_candidates_for_workflow(workflow, "seleniumbase") == ("seleniumbase", "nodriver", "playwright")


def test_detect_portal_from_known_url() -> None:
    portal = detect_portal("https://boards.greenhouse.io/example/jobs/123")

    assert portal is not None
    assert portal.portal_id == "greenhouse"
    assert portal.default_adapter == "nodriver"


def test_detect_portal_for_ashby_url() -> None:
    portal = detect_portal("https://jobs.ashbyhq.com/example/aaaabbbb-cccc-dddd-eeee-ffff00001111")

    assert portal is not None
    assert portal.portal_id == "ashby"
    assert portal.default_adapter == "nodriver"
    assert portal.requires_high_stealth is False


def test_workflow_for_common_ats_selects_safe_entry_actions() -> None:
    workflow = workflow_for_url("https://jobs.lever.co/example/abc")

    assert workflow.portal_id == "lever"
    assert workflow.workflow_kind == "ATS_DIRECT_FORM"
    assert workflow.default_adapter == "nodriver"
    assert adapter_candidates_for_workflow(workflow) == ("nodriver", "playwright", "seleniumbase")
    assert "Apply for this job" in workflow.entry_action_labels
    assert workflow.requires_manual_review_before_fill is True
    payload = workflow.to_event_payload()
    assert "Click known apply/start action" in payload["expected_steps"]
    assert "Final submit" in payload["review_checkpoints"]


def test_workflow_for_high_stealth_board_keeps_nodriver_and_login_watch() -> None:
    workflow = workflow_for_url("https://www.linkedin.com/jobs/view/123")

    assert workflow.portal_id == "linkedin"
    assert workflow.workflow_kind == "JOB_BOARD_REDIRECT_OR_STEALTH"
    assert workflow.default_adapter == "nodriver"
    assert workflow.requires_high_stealth is True
    # A high-stealth board used to drop a named playwright on the floor, because the
    # adapter could not launch at all. It can now, so the name is honoured here too.
    assert adapter_candidates_for_workflow(workflow, "playwright") == ("playwright", "nodriver", "seleniumbase")
    assert adapter_candidates_for_workflow(workflow) == ("nodriver", "playwright", "seleniumbase")
    assert workflow.requires_login_watch is True
    payload = workflow.to_event_payload()
    assert "Confirm trusted application surface" in payload["expected_steps"]
    assert "Redirect trust" in payload["review_checkpoints"]


def test_portal_page_state_requires_review_when_redirect_watch_does_not_move() -> None:
    workflow = workflow_for_url("https://www.linkedin.com/jobs/view/123")

    page_state = classify_portal_page_state(
        workflow=workflow,
        original_url="https://www.linkedin.com/jobs/view/123",
        current_url="https://www.linkedin.com/jobs/view/123",
        title="Senior Engineer Job",
        text="About the role",
        field_count=0,
    )

    assert page_state.requires_review is True
    assert page_state.likely_application_surface is False


def test_portal_page_state_trusts_known_ats_or_field_surface() -> None:
    workflow = workflow_for_url("https://www.linkedin.com/jobs/view/123")

    page_state = classify_portal_page_state(
        workflow=workflow,
        original_url="https://www.linkedin.com/jobs/view/123",
        current_url="https://boards.greenhouse.io/example/jobs/123",
        title="Application",
        text="Upload resume and cover letter",
        field_count=4,
    )

    assert page_state.requires_review is False
    assert page_state.host_changed is True
    assert page_state.current_portal_id == "greenhouse"
    assert "known_ats_surface" in page_state.signals


def test_generic_field_detection_normalizes_dom_snapshot() -> None:
    fields = fields_from_dom_snapshot(
        [
            {
                "label": "Email address",
                "field_type": "email",
                "selector": "#email",
                "required": True,
                "metadata": {"autocomplete": "email"},
            },
            {"label": "", "field_type": "hidden", "selector": None},
        ]
    )

    assert fields[0].label == "Email address"
    assert fields[0].required is True
    assert fields[0].metadata["autocomplete"] == "email"
    assert fields[0].confidence > fields[1].confidence
    assert fields[1].label == "Unlabeled field"


def test_field_detection_preserves_select_options_without_values_from_text_fields() -> None:
    fields = fields_from_dom_snapshot(
        [
            {
                "label": "Work authorization",
                "field_type": "select",
                "selector": "#authorization",
                "required": True,
                "metadata": {
                    "options": [
                        {"value": "yes", "label": "Yes", "selected": False},
                        {"value": "no", "label": "No", "selected": False},
                    ],
                    "value": None,
                },
            }
        ]
    )

    assert fields[0].metadata["options"][0]["label"] == "Yes"
    assert fields[0].metadata["value"] is None


def test_apply_field_script_uses_json_embedding_for_reviewed_values() -> None:
    script = build_apply_field_value_script('select[name="role"]', 'Senior "Platform" Engineer')

    assert 'const selector = "select[name=\\"role\\"]";' in script
    assert 'Senior \\"Platform\\" Engineer' in script
    assert "selected_value_length" in script


def test_click_by_text_script_blocks_final_submit_labels() -> None:
    script = build_click_by_text_script(["Apply for this job"])

    assert "submit application" in script
    assert "isFinalSubmitLike" in script
    assert "startsWith('submit ')" in script
    assert "send application" in script
    assert "Apply for this job" in script
    assert "AMBIGUOUS_PORTAL_ACTION" in script
    assert "candidate_labels" in script
    assert "clicked_label" in script


def test_safe_step_progression_labels_are_non_final_submit_controls() -> None:
    script = build_click_by_text_script(list(SAFE_STEP_PROGRESSION_LABELS))

    normalized_labels = {label.lower() for label in SAFE_STEP_PROGRESSION_LABELS}
    assert {"next", "continue", "review application"}.issubset(normalized_labels)
    assert all(not label.startswith(("submit", "send", "finish", "complete")) for label in normalized_labels)
    assert "submit application" in script
    assert "AMBIGUOUS_PORTAL_ACTION" in script


def test_common_ats_entry_actions_do_not_configure_final_submit_labels() -> None:
    dangerous_prefixes = ("submit", "send", "finish", "complete")
    urls = {
        "workday": "https://acme.myworkdayjobs.com/en-US/acme/job/Engineer",
        "greenhouse": "https://boards.greenhouse.io/example/jobs/123",
        "lever": "https://jobs.lever.co/example/abc",
        "ashby": "https://jobs.ashbyhq.com/example/aaaabbbb-cccc-dddd-eeee-ffff00001111",
        "icims": "https://acme.icims.com/jobs/123/job",
        "taleo": "https://acme.taleo.net/careersection/jobdetail.ftl?job=123",
    }
    for portal_id, url in urls.items():
        workflow = workflow_for_url(url)
        normalized = [label.strip().lower() for label in workflow.entry_action_labels]
        assert workflow.portal_id == portal_id
        assert normalized
        assert all(not label.startswith(dangerous_prefixes) for label in normalized)


def test_common_ats_targets_have_portal_specific_multi_page_adapter_plans() -> None:
    urls = {
        "workday": "https://acme.myworkdayjobs.com/en-US/acme/job/Engineer",
        "greenhouse": "https://boards.greenhouse.io/example/jobs/123",
        "lever": "https://jobs.lever.co/example/abc",
        "ashby": "https://jobs.ashbyhq.com/example/aaaabbbb-cccc-dddd-eeee-ffff00001111",
        "icims": "https://acme.icims.com/jobs/123/job",
        "taleo": "https://acme.taleo.net/careersection/jobdetail.ftl?job=123",
    }
    for portal_id, url in urls.items():
        workflow = workflow_for_url(url)
        plan = portal_adapter_plan_for_workflow(workflow)

        assert plan.portal_id == portal_id
        assert plan.workflow_kind == "ATS_DIRECT_FORM"
        assert len(plan.steps) >= 4
        assert "FINAL_SUBMIT" in plan.required_review_gates
        assert "DOCUMENT" in plan.required_review_gates
        assert plan.max_automated_steps <= 6
        assert progression_labels_for_workflow(workflow) == plan.step_progression_labels
        assert final_submit_labels_for_workflow(workflow) == plan.final_submit_labels
        assert all("submit" not in label.lower() for label in plan.entry_action_labels)


def test_portal_adapter_plan_event_payload_is_safe_and_review_oriented() -> None:
    workflow = workflow_for_url("https://jobs.lever.co/example/abc")
    payload = portal_adapter_plan_for_workflow(workflow).to_event_payload()

    assert payload["portal_id"] == "lever"
    assert "FINAL_SUBMIT" in payload["required_review_gates"]
    assert "Submit application" in payload["final_submit_labels"]
    assert isinstance(payload["steps"], list)
    assert all("required_review_gate" in step for step in payload["steps"])


def test_requested_job_board_workflows_have_safe_entry_action_hints() -> None:
    dangerous_prefixes = ("submit", "send", "finish", "complete")
    board_urls = {
        "careerbuilder": "https://www.careerbuilder.com/job/J3N",
        "dice": "https://www.dice.com/job-detail/123",
        "foundit": "https://www.foundit.in/job/123",
        "freshersworld": "https://www.freshersworld.com/jobs/123",
        "glassdoor": "https://www.glassdoor.com/job-listing/123.htm",
        "hirist": "https://www.hirist.tech/job/123",
        "iimjobs": "https://www.iimjobs.com/j/123",
        "indeed": "https://www.indeed.com/viewjob?jk=123",
        "instahyre": "https://www.instahyre.com/job-123",
        "linkedin": "https://www.linkedin.com/jobs/view/123",
        "monster": "https://www.monster.com/job-openings/123",
        "naukri": "https://www.naukri.com/job-listings-123",
        "otta": "https://app.otta.com/jobs/123",
        "shine": "https://www.shine.com/jobs/123",
        "timesjobs": "https://www.timesjobs.com/job-detail/123",
        "wellfound": "https://wellfound.com/jobs/123",
        "ziprecruiter": "https://www.ziprecruiter.com/jobs/123",
    }

    for portal_id, url in board_urls.items():
        workflow = workflow_for_url(url)
        normalized = [label.strip().lower() for label in workflow.entry_action_labels]
        assert workflow.portal_id == portal_id
        assert normalized
        assert all(not label.startswith(dangerous_prefixes) for label in normalized)


def test_parse_click_by_text_result_returns_safe_metadata_only() -> None:
    result = parse_click_by_text_result('{"ok": true, "clicked_label": "Apply for this job", "clicked_tag": "button", "href": null}')

    assert result.ok is True
    assert result.payload == {
        "action": "click_by_text",
        "clicked_label": "Apply for this job",
        "clicked_tag": "button",
        "href": None,
    }


def test_parse_click_by_text_result_preserves_ambiguous_action_metadata() -> None:
    result = parse_click_by_text_result(
        json.dumps(
            {
                "ok": False,
                "message": "multiple safe portal actions matched; manual review is required",
                "ambiguity_code": "AMBIGUOUS_PORTAL_ACTION",
                "candidate_count": 2,
                "candidate_labels": ["Apply", "Apply on company site"],
                "raw_dom": "<button>secret</button>",
            }
        )
    )

    assert result.ok is False
    assert result.payload == {
        "action": "click_by_text",
        "candidate_count": 2,
        "ambiguity_code": "AMBIGUOUS_PORTAL_ACTION",
        "href": None,
        "candidate_labels": ["Apply", "Apply on company site"],
        "message": "multiple safe portal actions matched; manual review is required",
    }


def test_parse_apply_field_result_returns_safe_metadata_only() -> None:
    field = fields_from_dom_snapshot(
        [
            {
                "label": "Location preference",
                "field_type": "radio",
                "selector": 'input[name="location"][value="remote"]',
            }
        ]
    )[0]

    result = parse_apply_field_result(
        '{"ok": true, "action": "set_radio", "selected_label": "Remote", "selected_value_length": 6}',
        field,
    )

    assert result.ok is True
    assert result.payload == {
        "field_id": field.field_id,
        "action": "set_radio",
        "selected_value_length": 6,
        "selected_label": "Remote",
    }


def test_blocker_detection_normalizes_dom_snapshot() -> None:
    blockers = blockers_from_dom_snapshot(
        [
            {"blocker_type": "captcha", "message": "CAPTCHA challenge detected", "confidence": 0.92},
            {
                "blocker_type": "login",
                "message": "Login page detected",
                "confidence": 0.9,
                "metadata": {"password_input_count": 1},
            },
            {"blocker_type": "otp", "message": "One-time code required", "confidence": 0.8},
            {
                "blocker_type": "ambiguous_question",
                "message": "Sensitive or ambiguous application question detected",
                "confidence": 0.86,
                "metadata": {"matched_patterns": ["sponsorship"]},
            },
            {"blocker_type": "unknown", "message": "ignored"},
        ]
    )

    assert [blocker.blocker_type for blocker in blockers] == ["CAPTCHA", "LOGIN", "OTP", "AMBIGUOUS_QUESTION"]
    assert blockers[1].metadata["password_input_count"] == 1
    assert blockers[0].confidence > blockers[2].confidence
    assert blockers[3].metadata["matched_patterns"] == ["sponsorship"]


def test_playwright_adapter_fails_safely_when_runtime_is_absent(tmp_path) -> None:
    if importlib.util.find_spec("patchright") is not None:
        return

    adapter = create_browser_adapter("playwright")
    result = asyncio.run(adapter.launch(run_id="run-1", user_data_dir=tmp_path / "browser"))

    assert result.ok is False
    assert "playwright is not installed" in result.message
