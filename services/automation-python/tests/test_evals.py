"""The eval gate runs in CI as an ordinary test.

Two failures matter equally. A good sample rejected means the app will refuse
documents users would have been happy to send. A bad sample accepted means the
gate is decorative, and a fabricated employer reaches a real recruiter.
"""

from __future__ import annotations

import pytest

from applyocalypse_automation.evals import grade_groundedness, grade_mentions, grade_style, grade_text
from evals.run_evals import load_suites, run, score_case

PROFILE = "Ada Byron worked at Halcyon Systems from 2019 to 2025 and cut p95 latency by 38%."
JOB = "Northstar Labs is hiring a Platform Engineer."
SOURCES = [PROFILE, JOB]


def all_cases() -> list[tuple[dict, dict]]:
    return [(suite, case) for suite in load_suites() for case in suite["cases"]]


def case_id(pair: tuple[dict, dict]) -> str:
    return f"{pair[0]['stage']}-{pair[1]['id']}"


@pytest.mark.parametrize("pair", all_cases(), ids=case_id)
def test_every_golden_case_behaves_as_expected(pair: tuple[dict, dict]) -> None:
    suite, case = pair
    outcome = score_case(suite, case)
    assert outcome.ok, outcome.reason


def test_the_dataset_holds_both_good_and_bad_samples() -> None:
    """A dataset of only-passing samples proves nothing about the graders."""
    expectations = {case["expect"] for _, case in all_cases()}
    assert expectations == {"pass", "fail"}


def test_the_runner_reports_one_outcome_per_case() -> None:
    assert len(run()) == len(all_cases())


@pytest.mark.parametrize(
    ("text", "expected_finding"),
    [
        ("I led the platform team at Stripe.", "Stripe"),
        ("At Halcyon Systems I cut latency by 91%.", "91%"),
        ("I studied at Cambridge and worked at Halcyon Systems.", "Cambridge"),
        # An invented name leading a sentence is still a claim, even though the
        # capital letter alone would be explained by the sentence starting.
        ("Datadog Payments paid for the migration.", "Datadog Payments"),
    ],
)
def test_groundedness_names_the_invented_claim(text: str, expected_finding: str) -> None:
    result = grade_groundedness(text, sources=SOURCES)
    assert not result.passed
    assert expected_finding in result.findings


@pytest.mark.parametrize(
    "text",
    [
        "At Halcyon Systems I cut p95 latency by 38%.",
        "Dear Hiring Manager, I would like to join Northstar Labs as a Platform Engineer.",
        "I worked at Halcyon Systems from 2019 to 2025.",
        # The verb is capitalized by grammar, and the name after it is real.
        "Joined Halcyon Systems in 2019.",
    ],
)
def test_groundedness_accepts_claims_the_sources_support(text: str) -> None:
    result = grade_groundedness(text, sources=SOURCES)
    assert result.passed, result.findings


def test_mentions_names_what_is_missing() -> None:
    result = grade_mentions("A letter about nothing in particular.", must_mention=["Northstar Labs"])
    assert not result.passed
    assert result.findings == ("Northstar Labs",)


def test_style_still_blocks_banned_wording_and_em_dashes() -> None:
    banned = grade_style("I am thrilled to leverage my robust background.", artifact_kind="cover_letter")
    em_dash = grade_style("I worked at Halcyon — on payments.", artifact_kind="cover_letter")
    assert not banned.passed
    assert not em_dash.passed


def test_grade_text_skips_the_mentions_grader_when_nothing_is_required() -> None:
    names = {result.name for result in grade_text("Plain text.", artifact_kind="generic", sources=SOURCES)}
    assert names == {"style", "groundedness"}
