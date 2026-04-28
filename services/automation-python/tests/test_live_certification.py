from __future__ import annotations

import json

from applyocalypse_automation.browser.live_certification import (
    TARGET_PORTAL_IDS,
    CertificationTarget,
    certify_target,
    certify_targets,
    load_targets,
    report_payload,
)


def test_live_certification_blocks_without_configured_urls() -> None:
    results = certify_targets(tuple(), live_enabled=False, network_enabled=False)

    assert {result.portal_id for result in results} == set(TARGET_PORTAL_IDS)
    assert all(result.status == "BLOCKED" for result in results)


def test_live_certification_fails_when_url_does_not_match_portal() -> None:
    result = certify_target(
        CertificationTarget(portal_id="greenhouse", url="https://jobs.lever.co/example/123"),
        live_enabled=True,
        network_enabled=False,
    )

    assert result.status == "FAIL"
    assert result.blockers == ("url_does_not_match_portal:https://jobs.lever.co/example/123",)


def test_live_certification_loads_adapter_plan_but_blocks_until_explicitly_enabled() -> None:
    result = certify_target(
        CertificationTarget(portal_id="lever", url="https://jobs.lever.co/example/123"),
        live_enabled=False,
        network_enabled=False,
    )

    assert result.status == "BLOCKED"
    assert "portal_detected" in result.checks
    assert "adapter_plan_loaded" in result.checks
    assert "final_submit_gate_present" in result.checks
    assert "set_APPLYO_LIVE_CERTIFICATION_1_to_run_live_checks" in result.blockers


def test_live_certification_target_file_is_validated(tmp_path) -> None:
    target_file = tmp_path / "targets.json"
    target_file.write_text(
        json.dumps(
            [
                {
                    "portal_id": "workday",
                    "url": "https://acme.myworkdayjobs.com/en-US/acme/job/Engineer",
                    "requires_credentials": True,
                }
            ]
        ),
        encoding="utf-8",
    )

    targets = load_targets(target_file)

    assert len(targets) == 1
    assert targets[0].portal_id == "workday"
    assert targets[0].requires_credentials is True


def test_live_certification_report_payload_is_machine_readable() -> None:
    payload = report_payload(
        (
            certify_target(
                CertificationTarget(portal_id="greenhouse", url="https://boards.greenhouse.io/example/jobs/123"),
                live_enabled=False,
                network_enabled=False,
            ),
        )
    )

    assert payload["report_type"] == "LIVE_PORTAL_CERTIFICATION"
    assert payload["totals"] == {"pass": 0, "blocked": 1, "fail": 0}
    assert "not proof of successful submission" in payload["truthfulness_policy"]
