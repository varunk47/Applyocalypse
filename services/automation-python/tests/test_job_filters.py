from __future__ import annotations

from typing import Any

import pytest

from applyocalypse_automation.answers import jd_salary_range
from applyocalypse_automation.job_filters import (
    address_for_job,
    detect_arrangements,
    evaluate_job_filters,
    with_job_address,
)

HOME = {"label": "Home", "addressLine1": "10 Peachtree St", "addressLine2": "", "city": "Atlanta",
        "state": "GA", "postalCode": "30303", "country": "United States"}
FAMILY = {"label": "Family", "addressLine1": "1 Beacon St", "addressLine2": "", "city": "Boston",
          "state": "MA", "postalCode": "02108", "country": "United States"}


def _profile(filters: list[tuple[str, str]], addresses: list[dict[str, str]] | None = None) -> dict[str, Any]:
    return {
        "address": {"city": "Savannah", "state": "GA", "addressLine1": "5 Bay St", "county": "Chatham"},
        "jobFilters": [{"kind": kind, "value": value} for kind, value in filters],
        "addresses": addresses or [],
    }


@pytest.mark.parametrize(
    ("filters", "job", "jd", "passed", "reason_part"),
    [
        ([], {"company": "Initech"}, "Anything", True, None),
        ([("skip_company", "initech")], {"company": "Initech LLC"}, "", False, "Initech LLC"),
        ([("skip_company", "Meta")], {"company": "Metabase"}, "", True, None),
        ([("skip_keyword", "clearance")], {"role": "Engineer"}, "Requires an active security clearance.", False, "clearance"),
        ([("skip_keyword", "Senior")], {"role": "Senior Engineer"}, "", False, "Senior"),
        ([("skip_keyword", "java")], {"role": "Engineer"}, "We use JavaScript.", True, None),
        ([("min_salary", "120000")], {}, "Salary: $90,000 - $110,000 per year", False, "110,000"),
        ([("min_salary", "120000")], {}, "Salary: $100,000 - $140,000 per year", True, None),
        ([("min_salary", "120000")], {}, "Competitive pay.", True, None),
        ([("work_arrangement", "remote")], {"location": "Atlanta, GA (On-site)"}, "", False, "onsite"),
        ([("work_arrangement", "remote")], {"location": "Remote, US"}, "", True, None),
        ([("work_arrangement", "remote"), ("work_arrangement", "hybrid")], {"location": "Hybrid - Boston"}, "", True, None),
        ([("work_arrangement", "remote")], {"location": ""}, "No arrangement stated.", True, None),
        ([("place", "Denver")], {"location": "Chicago, IL"}, "", False, "Chicago, IL"),
        ([("place", "Denver")], {"location": "Denver, CO"}, "", True, None),
        ([("place", "Denver")], {"location": "Remote"}, "", True, None),
        ([("place", "Denver")], {"location": ""}, "", True, None),
    ],
)
def test_evaluate_job_filters(
    filters: list[tuple[str, str]], job: dict[str, str], jd: str, passed: bool, reason_part: str | None
) -> None:
    verdict = evaluate_job_filters(_profile(filters), job, jd)

    assert verdict.passed is passed
    if reason_part is None:
        assert verdict.reasons == ()
    else:
        assert any(reason_part in reason for reason in verdict.reasons)
        assert all("—" not in reason for reason in verdict.reasons)


@pytest.mark.parametrize(
    ("location", "passed"),
    [("Boston, MA", True), ("Savannah, GA", True), ("Chicago, IL", False)],
)
def test_saved_addresses_and_the_profile_address_count_as_allowed_places(location: str, passed: bool) -> None:
    profile = _profile([("place", "Denver")], [HOME, FAMILY])

    assert evaluate_job_filters(profile, {"location": location}, "").passed is passed


def test_every_failing_filter_is_reported() -> None:
    profile = _profile([("skip_company", "Initech"), ("skip_keyword", "Senior")])

    verdict = evaluate_job_filters(profile, {"company": "Initech", "role": "Senior Engineer"}, "")

    assert len(verdict.reasons) == 2


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Work from home anywhere in the US.", {"remote"}),
        ("This is a fully remote role.", {"remote"}),
        ("Hybrid, 3 days a week in the office", {"hybrid"}),
        ("On-site in Austin", {"onsite"}),
        ("Remote collaboration tools and hybrid cloud experience", set()),
    ],
)
def test_detect_arrangements_in_a_description_needs_a_clear_phrase(text: str, expected: set[str]) -> None:
    assert detect_arrangements(text) == expected


@pytest.mark.parametrize(
    ("location", "expected_city"),
    [("Boston, MA", "Boston"), ("Atlanta, Georgia", "Atlanta"), ("Chicago, IL", None), ("", None)],
)
def test_address_for_job_picks_the_address_in_the_job_city(location: str, expected_city: str | None) -> None:
    chosen = address_for_job([HOME, FAMILY], {"location": location})

    assert (chosen or {}).get("city") == expected_city


def test_with_job_address_swaps_the_whole_address_and_leaves_the_rest() -> None:
    profile = _profile([], [HOME, FAMILY])

    swapped = with_job_address(profile, {"location": "Boston, MA"})

    assert swapped["address"] == {
        "addressLine1": "1 Beacon St", "addressLine2": "", "city": "Boston",
        "state": "MA", "postalCode": "02108", "country": "United States",
    }
    assert profile["address"]["city"] == "Savannah"
    assert with_job_address(profile, {"location": "Chicago, IL"}) is profile


@pytest.mark.parametrize(
    ("jd", "expected"),
    [
        ("Salary: $80,000 - $100,000", (80000, 100000)),
        ("Pay 120k-150k base", (120000, 150000)),
        ("Founded 1999 to 2005", None),
        ("", None),
    ],
)
def test_jd_salary_range(jd: str, expected: tuple[int, int] | None) -> None:
    assert jd_salary_range(jd) == expected


def test_the_run_stops_before_tailoring_when_a_filter_rules_the_job_out(tmp_path, monkeypatch, capsys) -> None:
    import json
    import sys

    from applyocalypse_automation import runner

    (tmp_path / "jd.txt").write_text("Senior Engineer at Initech.", encoding="utf-8")
    (tmp_path / "job.json").write_text(json.dumps({"company": "Initech", "role": "Engineer"}), encoding="utf-8")
    (tmp_path / "profile.json").write_text(json.dumps(_profile([("skip_company", "Initech")])), encoding="utf-8")

    def tailoring_must_not_run(**_: object) -> None:
        raise AssertionError("tailoring ran for a filtered-out job")

    monkeypatch.setattr(runner, "generate_application_documents", tailoring_must_not_run)
    monkeypatch.setattr(sys, "argv", [
        "runner", "--run-id", "run-f", "--work-dir", str(tmp_path / "work"),
        "--job-text-file", str(tmp_path / "jd.txt"),
        "--job-metadata-file", str(tmp_path / "job.json"),
        "--profile-json-file", str(tmp_path / "profile.json"),
    ])

    runner._main_impl()

    last = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert last["event_type"] == "FAILED"
    assert last["payload"]["code"] == "FILTERED_OUT"
    assert "Initech" in last["message"]
