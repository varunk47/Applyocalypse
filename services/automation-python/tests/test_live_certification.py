"""Tests for the portal reachability probe.

The probe used to call a 200 OK a "PASS" of a "LIVE_PORTAL_CERTIFICATION",
which reads as "this portal can be filled". It cannot know that: it never opens
the form. These tests pin the honest shape - a reachability verdict, plus a
fill capability that is carried from the adapter plan and can never be raised
by an HTTP response.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from applyocalypse_automation.browser import live_certification
from applyocalypse_automation.browser.live_certification import (
    REACHABILITY_BLOCKED,
    REACHABILITY_MISCONFIGURED,
    REACHABILITY_REACHABLE,
    REACHABILITY_STATUSES,
    REACHABILITY_UNREACHABLE,
    REPORT_TYPE,
    TARGET_PORTAL_IDS,
    ReachabilityTarget,
    load_targets,
    probe_target_reachability,
    probe_targets,
    report_payload,
)
from applyocalypse_automation.browser.portal_adapters import (
    ATS_ADAPTER_PLANS,
    FILL_CAPABILITY_LIVE_VERIFIED,
)

PORTAL_URLS = {
    "workday": "https://acme.myworkdayjobs.com/en-US/acme/job/Engineer",
    "greenhouse": "https://boards.greenhouse.io/example/jobs/123",
    "lever": "https://jobs.lever.co/example/123",
    "ashby": "https://jobs.ashbyhq.com/example/aaaabbbb-cccc-dddd-eeee-ffff00001111",
    "icims": "https://acme.icims.com/jobs/123/job",
    "taleo": "https://acme.taleo.net/careersection/jobdetail.ftl?job=123",
}


# ── A reachable URL is never a fillability claim ──────────────────────────────
@pytest.mark.parametrize("portal_id", sorted(PORTAL_URLS))
@pytest.mark.parametrize("http_status", [200, 204, 301])
def test_http_success_alone_cannot_certify_that_a_portal_can_be_filled(
    monkeypatch: pytest.MonkeyPatch, portal_id: str, http_status: int
) -> None:
    monkeypatch.setattr(live_certification, "_fetch_status", lambda url, timeout_seconds: http_status)

    result = probe_target_reachability(
        ReachabilityTarget(portal_id=portal_id, url=PORTAL_URLS[portal_id]),
        live_enabled=True,
        network_enabled=True,
    )

    assert result.status == REACHABILITY_REACHABLE
    assert result.http_status == http_status
    # The probe opened no form, so it may not raise the fill capability.
    assert result.fill_capability == ATS_ADAPTER_PLANS[portal_id].fill_capability_status
    assert result.fill_capability != FILL_CAPABILITY_LIVE_VERIFIED
    assert result.fill_capability_blockers

    payload = result.to_dict()
    assert payload["reachability_status"] == REACHABILITY_REACHABLE
    assert "PASS" not in json.dumps(payload)
    assert "certif" not in json.dumps(payload).lower()


def test_no_probe_outcome_is_a_certification() -> None:
    assert REACHABILITY_STATUSES == {
        REACHABILITY_REACHABLE,
        REACHABILITY_UNREACHABLE,
        REACHABILITY_BLOCKED,
        REACHABILITY_MISCONFIGURED,
    }
    assert not any("PASS" in status or "CERTIFIED" in status for status in REACHABILITY_STATUSES)


# ── Verdict table ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("target", "live_enabled", "network_enabled", "expected_status", "expected_blocker"),
    [
        (
            ReachabilityTarget(portal_id="lever", url=None),
            True,
            True,
            REACHABILITY_BLOCKED,
            "missing_live_application_url",
        ),
        (
            ReachabilityTarget(portal_id="lever", url="file:///etc/passwd"),
            True,
            True,
            REACHABILITY_MISCONFIGURED,
            "unsupported_url_scheme",
        ),
        (
            ReachabilityTarget(portal_id="greenhouse", url="https://jobs.lever.co/example/123"),
            True,
            True,
            REACHABILITY_MISCONFIGURED,
            "url_does_not_match_portal:https://jobs.lever.co/example/123",
        ),
        (
            ReachabilityTarget(portal_id="lever", url=PORTAL_URLS["lever"]),
            False,
            False,
            REACHABILITY_BLOCKED,
            "set_APPLYO_LIVE_CERTIFICATION_1_to_run_live_checks",
        ),
        (
            ReachabilityTarget(portal_id="lever", url=PORTAL_URLS["lever"]),
            True,
            False,
            REACHABILITY_BLOCKED,
            "network_probe_disabled",
        ),
        (
            ReachabilityTarget(portal_id="workday", url=PORTAL_URLS["workday"], requires_credentials=True),
            True,
            True,
            REACHABILITY_BLOCKED,
            "requires_portal_account_or_test_identity",
        ),
    ],
)
def test_probe_verdicts(
    target: ReachabilityTarget,
    live_enabled: bool,
    network_enabled: bool,
    expected_status: str,
    expected_blocker: str,
) -> None:
    result = probe_target_reachability(target, live_enabled=live_enabled, network_enabled=network_enabled)

    assert result.status == expected_status
    assert expected_blocker in result.blockers
    assert result.fill_capability != FILL_CAPABILITY_LIVE_VERIFIED


def test_adapter_plan_checks_run_before_the_network_probe() -> None:
    result = probe_target_reachability(
        ReachabilityTarget(portal_id="lever", url=PORTAL_URLS["lever"]),
        live_enabled=False,
        network_enabled=False,
    )

    assert result.checks == ("portal_detected", "adapter_plan_loaded", "final_submit_gate_present")


@pytest.mark.parametrize("http_status", [403, 404, 500])
def test_error_responses_are_unreachable(monkeypatch: pytest.MonkeyPatch, http_status: int) -> None:
    monkeypatch.setattr(live_certification, "_fetch_status", lambda url, timeout_seconds: http_status)

    result = probe_target_reachability(
        ReachabilityTarget(portal_id="lever", url=PORTAL_URLS["lever"]),
        live_enabled=True,
        network_enabled=True,
    )

    assert result.status == REACHABILITY_UNREACHABLE
    assert f"unexpected_http_status:{http_status}" in result.blockers


def test_network_failure_is_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(url: str, timeout_seconds: float) -> int:
        raise TimeoutError("probe timed out")

    monkeypatch.setattr(live_certification, "_fetch_status", _boom)

    result = probe_target_reachability(
        ReachabilityTarget(portal_id="lever", url=PORTAL_URLS["lever"]),
        live_enabled=True,
        network_enabled=True,
    )

    assert result.status == REACHABILITY_UNREACHABLE
    assert result.blockers == ("network_probe_failed:TimeoutError",)


# ── Batch + report ────────────────────────────────────────────────────────────
def test_every_registered_portal_is_blocked_without_configured_urls() -> None:
    results = probe_targets(tuple(), live_enabled=False, network_enabled=False)

    assert {result.portal_id for result in results} == set(TARGET_PORTAL_IDS)
    assert all(result.status == REACHABILITY_BLOCKED for result in results)
    assert all(result.fill_capability != FILL_CAPABILITY_LIVE_VERIFIED for result in results)


def test_target_file_is_validated(tmp_path: Path) -> None:
    target_file = tmp_path / "targets.json"
    target_file.write_text(
        json.dumps([{"portal_id": "workday", "url": PORTAL_URLS["workday"], "requires_credentials": True}]),
        encoding="utf-8",
    )

    targets = load_targets(target_file)

    assert len(targets) == 1
    assert targets[0].portal_id == "workday"
    assert targets[0].requires_credentials is True


@pytest.mark.parametrize(
    "raw",
    ['{"portal_id": "workday"}', '["workday"]', '[{"portal_id": "not-a-portal"}]'],
)
def test_malformed_target_files_are_rejected(tmp_path: Path, raw: str) -> None:
    target_file = tmp_path / "targets.json"
    target_file.write_text(raw, encoding="utf-8")

    with pytest.raises(ValueError):
        load_targets(target_file)


def test_report_payload_reports_reachability_not_certification() -> None:
    payload = report_payload(
        (
            probe_target_reachability(
                ReachabilityTarget(portal_id="greenhouse", url=PORTAL_URLS["greenhouse"]),
                live_enabled=False,
                network_enabled=False,
            ),
        )
    )

    assert payload["report_type"] == REPORT_TYPE
    assert payload["totals"] == {"reachable": 0, "blocked": 1, "unreachable": 0, "misconfigured": 0}
    assert payload["fill_capability_totals"] == {ATS_ADAPTER_PLANS["greenhouse"].fill_capability_status: 1}
    assert "not evidence that any field was filled" in str(payload["truthfulness_policy"])
    assert FILL_CAPABILITY_LIVE_VERIFIED not in json.dumps(payload)
