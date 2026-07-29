"""Registering an ATS must route it to the direct-form flow without loosening a gate.

An unregistered host falls through to ``GENERIC_REVIEW_FIRST``: Nodriver, high
stealth, and no field detection at all until a human confirms the page. That is
the right default for a host we know nothing about and the wrong one for an
ordinary ATS form, where it costs the user a manual confirmation on every run.

Registering a portal only asserts two things: this host is an ATS, and here is
the label on its apply button. It must not change what the run is allowed to do
on its own, so these cases pin the gates as tightly as the routing.
"""
from __future__ import annotations

import pytest

from applyocalypse_automation.browser.portal_adapters import portal_adapter_plan_for_workflow
from applyocalypse_automation.browser.portal_registry import PORTALS, detect_portal
from applyocalypse_automation.browser.portal_workflows import (
    ATS_ENTRY_ACTIONS,
    ATS_PORTAL_QUIRKS,
    workflow_for_url,
)

# One realistically shaped URL per newly registered ATS. Shape matters: several of
# these serve every customer from a tenant subdomain, so a registration that only
# matched the bare apex would miss every real posting.
ATS_URLS: tuple[tuple[str, str], ...] = (
    ("workable", "https://apply.workable.com/acme-inc/j/A1B2C3D4E5/"),
    ("smartrecruiters", "https://jobs.smartrecruiters.com/AcmeInc/743999812345"),
    ("jobvite", "https://jobs.jobvite.com/acme/job/oXYZbfwK"),
    ("bamboohr", "https://acme.bamboohr.com/careers/1234"),
    ("jazzhr", "https://acme.applytojob.com/apply/AbCdEf/Staff-Engineer"),
    ("breezy", "https://acme.breezy.hr/p/1a2b3c4d5e-staff-engineer"),
    ("recruitee", "https://acme.recruitee.com/o/staff-engineer"),
    ("teamtailor", "https://acme.teamtailor.com/jobs/1234567-staff-engineer"),
    ("pinpoint", "https://acme.pinpointhq.com/en/postings/1a2b3c4d"),
    ("rippling", "https://ats.rippling.com/acme/jobs/1a2b3c4d"),
    ("successfactors", "https://career5.successfactors.eu/career?career_job_req_id=1234"),
    ("oraclecloud", "https://eabc.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/job/1234"),
    ("adp", "https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?cid=1234"),
    ("ultipro", "https://recruiting.ultipro.com/ACM1000ACME/JobBoard/1a2b/OpportunityDetail?opportunityId=1a2b"),
    ("paylocity", "https://recruiting.paylocity.com/recruiting/jobs/Details/1234567/Acme/Staff-Engineer"),
    ("paycom", "https://www.paycomonline.net/v4/ats/web.php/jobs/ViewJobDetails?job=1234"),
    ("avature", "https://acme.avature.net/careers/JobDetail/Staff-Engineer/1234"),
    ("bullhorn", "https://acme.bullhornstaffing.com/careers/JobDetail?jobId=1234"),
)


@pytest.mark.parametrize(("portal_id", "url"), ATS_URLS, ids=[portal_id for portal_id, _ in ATS_URLS])
def test_registered_ats_urls_route_to_the_direct_form_flow(portal_id: str, url: str) -> None:
    workflow = workflow_for_url(url)

    assert workflow.portal_id == portal_id, f"{url} resolved to {workflow.portal_id}"
    assert workflow.workflow_kind == "ATS_DIRECT_FORM"
    assert workflow.default_adapter == "playwright"
    assert workflow.requires_high_stealth is False
    assert workflow.entry_action_labels, "an ATS with no apply label cannot be entered"


@pytest.mark.parametrize(("portal_id", "url"), ATS_URLS, ids=[portal_id for portal_id, _ in ATS_URLS])
def test_registering_an_ats_does_not_weaken_the_review_gates(portal_id: str, url: str) -> None:
    """The whole safety argument for registering these is that nothing relaxes."""
    workflow = workflow_for_url(url)
    plan = portal_adapter_plan_for_workflow(workflow)

    assert workflow.requires_manual_review_before_fill is True
    assert "FINAL_SUBMIT" in plan.required_review_gates
    assert "SENSITIVE_QUESTION" in plan.required_review_gates


# Enterprise suites put a candidate account between the apply click and the form.
# Spelled out rather than derived from the production set, so that moving a portal
# in or out of the walled list has to be a deliberate edit to this expectation.
LOGIN_WALLED = frozenset(
    {"successfactors", "oraclecloud", "adp", "ultipro", "paylocity", "paycom", "avature", "bullhorn"}
)


@pytest.mark.parametrize(("portal_id", "url"), ATS_URLS, ids=[portal_id for portal_id, _ in ATS_URLS])
def test_login_walled_portals_watch_for_the_sign_in_wall(portal_id: str, url: str) -> None:
    """Without the watch the run reads a login screen as an application with no fields."""
    workflow = workflow_for_url(url)

    assert workflow.requires_login_watch is (portal_id in LOGIN_WALLED)


def test_no_two_portals_claim_the_same_host() -> None:
    """``detect_portal`` returns the first match, so an overlap silently picks a winner.

    Suffix overlap counts: ``endswith(f".{domain}")`` means registering ``acme.com``
    would also swallow every ``jobs.acme.com`` another portal had claimed, and which
    of the two wins would depend on tuple order rather than on anything meaningful.
    """
    claims = [(portal.portal_id, domain) for portal in PORTALS for domain in portal.domains]

    collisions = [
        (owner, domain, other_owner, other_domain)
        for owner, domain in claims
        for other_owner, other_domain in claims
        if owner != other_owner and (domain == other_domain or domain.endswith(f".{other_domain}"))
    ]

    assert collisions == [], f"overlapping portal domains: {collisions}"


@pytest.mark.parametrize("table_name", ("ATS_ENTRY_ACTIONS", "ATS_PORTAL_QUIRKS"))
def test_portal_keyed_tables_only_reference_registered_portals(table_name: str) -> None:
    """A key for an unregistered id is unreachable data, not a feature.

    ``workable`` sat in ``ATS_PORTAL_QUIRKS`` for a long time without a matching
    ``PortalDefinition``, so the note it carried could never reach a run.
    """
    table = {"ATS_ENTRY_ACTIONS": ATS_ENTRY_ACTIONS, "ATS_PORTAL_QUIRKS": ATS_PORTAL_QUIRKS}[table_name]
    registered = {portal.portal_id for portal in PORTALS}

    assert set(table) <= registered, f"{table_name} keys off the registry: {set(table) - registered}"


def test_an_unknown_host_still_takes_the_conservative_path() -> None:
    """Widening the registry must not widen what happens off it."""
    workflow = workflow_for_url("https://careers.some-employer.example/openings/1")

    assert detect_portal("https://careers.some-employer.example/openings/1") is None
    assert workflow.workflow_kind == "GENERIC_REVIEW_FIRST"
    assert workflow.requires_manual_review_before_fill is True
    assert workflow.requires_login_watch is True
