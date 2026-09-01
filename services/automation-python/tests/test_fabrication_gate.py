from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from applyocalypse_automation.resume_tailoring import tailor_bullets_1to1
from applyocalypse_automation.tailoring.fabrication import (
    fabrication_findings,
    is_faithful_rewrite,
    technical_terms,
)


@pytest.mark.parametrize(
    ("original", "rewritten"),
    [
        # Reordering to lead with the most relevant evidence is the whole point.
        (
            "Built ingestion pipelines in Python, cutting nightly load time by 40%",
            "Cut nightly load time 40% by building Python ingestion pipelines",
        ),
        # Adopting the job's vocabulary for something the bullet already says.
        (
            "Wrote automated checks that ran on every merge",
            "Wrote automated regression checks that ran on every merge",
        ),
        # Numbers may be dropped, just not conjured.
        (
            "Handled 12 support escalations a week without a missed SLA",
            "Handled weekly support escalations without a missed SLA",
        ),
        # A number spelled out in the original licenses the digit in the rewrite.
        (
            "Mentored three junior engineers through their first on-call rotation",
            "Mentored 3 junior engineers through their first on-call rotation",
        ),
        # Thousands separators are formatting, not a different number.
        (
            "Migrated 1200 records with no data loss",
            "Migrated 1,200 records with no data loss",
        ),
    ],
)
def test_an_honest_rewrite_passes(original: str, rewritten: str) -> None:
    assert fabrication_findings(original, rewritten) == []
    assert is_faithful_rewrite(original, rewritten)


@pytest.mark.parametrize(
    ("original", "rewritten", "detail_fragment"),
    [
        # The classic: a bullet with no metric acquires one.
        ("Improved checkout latency", "Improved checkout latency by 40%", "40"),
        # Seniority inflation by way of the tenure number.
        ("Three years supporting the billing platform", "8 years supporting the billing platform", "8"),
        # Team size invented out of nothing.
        ("Reviewed code for the platform team", "Reviewed code for a team of 15", "15"),
        # A plausible-looking dollar figure.
        ("Reduced cloud spend", "Reduced cloud spend by $2M", "2"),
    ],
)
def test_a_number_the_candidate_never_claimed_is_rejected(original: str, rewritten: str, detail_fragment: str) -> None:
    findings = fabrication_findings(original, rewritten)
    assert [finding.code for finding in findings] == ["INVENTED_NUMBER"]
    assert detail_fragment in findings[0].detail
    assert not is_faithful_rewrite(original, rewritten)


@pytest.mark.parametrize(
    ("original", "rewritten", "invented"),
    [
        ("Built nightly data pipelines", "Built nightly Airflow data pipelines", "Airflow"),
        ("Deployed services to the cluster", "Deployed services to EKS", "EKS"),
        ("Wrote the reporting layer", "Wrote the reporting layer in PostgreSQL", "PostgreSQL"),
        ("Shipped the mobile client", "Shipped the React Native mobile client", "Native"),
        ("Automated the release checks", "Automated the release checks with Node.js", "Node.js"),
    ],
)
def test_a_tool_the_bullet_never_mentioned_is_rejected(original: str, rewritten: str, invented: str) -> None:
    findings = fabrication_findings(original, rewritten)
    assert [finding.code for finding in findings] == ["INVENTED_TERM"]
    assert invented in findings[0].detail


def test_a_tool_from_elsewhere_in_the_same_resume_is_allowed() -> None:
    """Tailoring may move the candidate's own evidence between bullets.

    Airflow is fabricated only if the candidate never claimed it anywhere. If it
    is already on their resume, pulling it into the bullet the job cares about is
    exactly the rewrite we want.
    """
    original = "Built nightly data pipelines"
    rewritten = "Built nightly Airflow data pipelines"

    assert fabrication_findings(original, rewritten) != []
    assert fabrication_findings(original, rewritten, known_terms={"airflow"}) == []


def test_known_terms_do_not_license_invented_numbers() -> None:
    """A metric has to be earned by the bullet that makes the claim."""
    findings = fabrication_findings(
        "Improved checkout latency",
        "Improved checkout latency by 40%",
        known_terms={"40", "airflow"},
    )
    assert [finding.code for finding in findings] == ["INVENTED_NUMBER"]


@pytest.mark.parametrize(
    ("original", "rewritten", "verb"),
    [
        ("Assisted with the payments migration", "Led the payments migration", "led"),
        ("Contributed to the design review process", "Owned the design review process", "owned"),
        ("Worked on the internal tooling", "Architected the internal tooling", "architected"),
        ("Collaborated on the rollout plan", "Drove the rollout plan", "drove"),
        ("Tracked the release backlog", "Managed the release backlog", "managed"),
    ],
)
def test_promotion_the_candidate_did_not_get_is_rejected(original: str, rewritten: str, verb: str) -> None:
    findings = fabrication_findings(original, rewritten)
    assert [finding.code for finding in findings] == ["SCOPE_ESCALATION"]
    assert verb in findings[0].detail


def test_ownership_the_original_already_claimed_survives() -> None:
    original = "Led the payments migration across four teams"
    rewritten = "Led the payments migration, coordinating four teams"

    assert fabrication_findings(original, rewritten) == []


@pytest.mark.parametrize(
    "rewritten",
    [
        "Delivered the reporting service for {{company}}",
        "Delivered the reporting service for [Company Name]",
        "Delivered the reporting service for XYZ Corp",
        "As an AI language model I cannot verify this bullet",
        "The candidate delivered the reporting service",
        "Delivered the reporting service matching the job description keywords",
        "Delivered the reporting service; metrics TBD",
    ],
)
def test_prompt_and_template_residue_is_rejected(rewritten: str) -> None:
    """The failure that shows up in competitors' one-star reviews.

    Leaked scaffolding reaches a recruiter as proof the application was machine
    generated, so it has to fail closed rather than be cleaned up in place.
    """
    findings = fabrication_findings("Delivered the reporting service", rewritten)
    assert "PLACEHOLDER_LEAK" in {finding.code for finding in findings}


def test_every_reason_for_rejection_is_reported_not_just_the_first() -> None:
    findings = fabrication_findings(
        "Assisted with data pipeline maintenance",
        "Led 4 Airflow data pipelines for {{company}}",
    )
    assert {finding.code for finding in findings} == {
        "INVENTED_NUMBER",
        "INVENTED_TERM",
        "SCOPE_ESCALATION",
        "PLACEHOLDER_LEAK",
    }


@pytest.mark.parametrize("rewritten", ["", "   "])
def test_an_empty_rewrite_is_not_treated_as_faithful(rewritten: str) -> None:
    """An empty bullet would silently delete a line from the resume."""
    assert not is_faithful_rewrite("Built the ingestion pipeline", rewritten)


def test_an_unchanged_bullet_is_always_faithful() -> None:
    text = "Led the migration of 40 services to Kubernetes using ArgoCD"
    assert fabrication_findings(text, text) == []


def test_technical_terms_picks_out_tools_and_leaves_prose_alone() -> None:
    found = technical_terms("Built ETL jobs in PostgreSQL and Node.js for the AWS migration")

    assert found == {"etl", "postgresql", "node.js", "aws"}


def test_technical_terms_distrusts_capitals_when_the_whole_line_shouts() -> None:
    """A bullet in caps must not read as a wall of invented acronyms.

    Capitalisation is the signal this gate leans on, and a shouted line carries
    none, so it is given up entirely rather than guessed at. A real acronym in
    such a line goes unnoticed, which costs a rejection we would have liked; the
    alternative costs every shouted bullet its rewrite.
    """
    assert technical_terms("BUILT AND SHIPPED THE NEW API") == set()
    assert technical_terms("Shipped the new API") == {"api"}


# ---------------------------------------------------------------------------
# The gate as the bullet rewriter applies it
# ---------------------------------------------------------------------------


def _rewriter_returning(bullets: list[str]) -> Any:
    async def _complete(*, system: str, user: str, schema_name: str) -> dict[str, Any]:
        return {"bullets": bullets}

    client = AsyncMock()
    client.complete_json = _complete
    return client


def test_a_fabricated_bullet_falls_back_to_the_original() -> None:
    """One bad bullet must not cost the other bullets their tailoring.

    The rewriter used to be all-or-nothing, so a single invented metric either
    went onto the resume or threw the whole batch away. Neither is what we want.
    """
    originals = ["Improved checkout latency", "Wrote automated checks for the payment flow"]
    client = _rewriter_returning(
        [
            "Improved checkout latency by 40%",  # a metric that was never claimed
            "Wrote automated regression checks for the payment flow",  # honest
        ]
    )

    result = asyncio.run(tailor_bullets_1to1(originals, job_description="Payments engineer", llm_client=client))

    assert result == ["Improved checkout latency", "Wrote automated regression checks for the payment flow"]


def test_known_terms_reach_the_gate_from_the_caller() -> None:
    """What the document stage passes in when it reads the master resume."""
    originals = ["Built nightly data pipelines"]
    rewritten = ["Built nightly Airflow data pipelines"]

    without = asyncio.run(
        tailor_bullets_1to1(originals, job_description="Data engineer", llm_client=_rewriter_returning(rewritten))
    )
    with_resume = asyncio.run(
        tailor_bullets_1to1(
            originals,
            job_description="Data engineer",
            llm_client=_rewriter_returning(rewritten),
            known_terms=technical_terms("Skills: Airflow, dbt, Snowflake"),
        )
    )

    assert without == originals
    assert with_resume == rewritten
