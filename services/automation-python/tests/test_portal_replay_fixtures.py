from __future__ import annotations

import pytest

from applyocalypse_automation.browser.field_detection import ControlCandidate, choose_safe_click_target
from applyocalypse_automation.browser.html_replay import analyze_portal_html_fixture, choose_entry_action_for_fixture


@pytest.mark.parametrize(
    ("url", "html", "expected_portal", "expected_click"),
    [
        (
            "https://acme.myworkdayjobs.com/en-US/acme/job/Engineer",
            """
            <html><title>Software Engineer | Workday</title><body>
              <main>
                <h1>Software Engineer</h1>
                <button>Start Application</button>
                <form>
                  <label for="first">First Name</label><input id="first" name="firstName" required>
                  <label for="last">Last Name</label><input id="last" name="lastName" required>
                  <label for="email">Email</label><input id="email" name="email" type="email" required>
                  <label for="resume">Resume</label><input id="resume" name="resume" type="file" accept=".pdf,.docx" required>
                </form>
              </main>
            </body></html>
            """,
            "workday",
            "Start Application",
        ),
        (
            "https://boards.greenhouse.io/northstar/jobs/123",
            """
            <html><title>Apply to Platform Engineer</title><body>
              <a href="/northstar/jobs/123#app">Apply for this job</a>
              <form>
                <label for="name">Full name</label><input id="name" required>
                <label for="email">Email</label><input id="email" type="email" required>
                <label for="resume">Resume</label><input id="resume" type="file" accept="application/pdf" required>
                <label for="cover">Cover letter</label><input id="cover" type="file" accept=".pdf">
              </form>
            </body></html>
            """,
            "greenhouse",
            "Apply for this job",
        ),
        (
            "https://jobs.lever.co/northstar/abc",
            """
            <html><title>Senior Backend Engineer</title><body>
              <button>Apply for this job</button>
              <button>Submit application</button>
              <form>
                <label for="email">Email</label><input id="email" type="email" required>
                <label for="phone">Phone</label><input id="phone" type="tel">
                <label for="resume">Resume</label><input id="resume" type="file" required>
              </form>
            </body></html>
            """,
            "lever",
            "Apply for this job",
        ),
        (
            "https://acme.icims.com/jobs/123/software-engineer/job",
            """
            <html><title>Software Engineer Application</title><body>
              <a>Apply Now</a>
              <form>
                <label for="email">Email</label><input id="email" type="email" required>
                <label for="password">Password</label><input id="password" type="password" required>
                <label for="resume">Resume</label><input id="resume" type="file" required>
              </form>
              <p>Sign in with your password to continue your application.</p>
            </body></html>
            """,
            "icims",
            "Apply Now",
        ),
        (
            "https://acme.taleo.net/careersection/jobdetail.ftl?job=123",
            """
            <html><title>Taleo Application</title><body>
              <button>Apply Online</button>
              <form>
                <label for="email">Email address</label><input id="email" type="email" required>
                <label for="resume">Resume</label><input id="resume" type="file" required>
                <label for="auth">Are you legally authorized to work?</label><select id="auth" required></select>
              </form>
              <p>Multi-factor authentication may be required for returning candidates.</p>
            </body></html>
            """,
            "taleo",
            "Apply Online",
        ),
    ],
)
def test_ats_html_replay_fixtures_detect_workflow_fields_and_safe_entry_action(url, html, expected_portal, expected_click):
    analysis = analyze_portal_html_fixture(url, html)
    entry_action = choose_entry_action_for_fixture(analysis)

    assert analysis.workflow.portal_id == expected_portal
    assert analysis.workflow.workflow_kind == "ATS_DIRECT_FORM"
    assert analysis.page_state.likely_application_surface is True
    assert analysis.page_state.confidence >= 0.65
    assert len(analysis.fields) >= 3
    assert entry_action.ok is True
    assert entry_action.payload["clicked_label"] == expected_click


@pytest.mark.parametrize(
    ("url", "html", "expected_portal", "expected_click"),
    [
        (
            "https://www.indeed.com/viewjob?jk=123",
            """
            <html><title>Backend Engineer - Indeed</title><body>
              <h1>Backend Engineer</h1>
              <button>Apply now</button>
              <button>Save job</button>
              <section>About the role. Build APIs and data pipelines.</section>
            </body></html>
            """,
            "indeed",
            "Apply now",
        ),
        (
            "https://www.linkedin.com/jobs/view/123",
            """
            <html><title>Staff Engineer | LinkedIn</title><body>
              <h1>Staff Engineer</h1>
              <button>Easy Apply</button>
              <article>Lead platform reliability work across cloud services.</article>
            </body></html>
            """,
            "linkedin",
            "Easy Apply",
        ),
        (
            "https://www.naukri.com/job-listings-123",
            """
            <html><title>Senior Python Developer - Naukri</title><body>
              <h1>Senior Python Developer</h1>
              <a href="/apply/123">Apply</a>
              <p>Experience with Python, distributed systems, and SQL is required.</p>
            </body></html>
            """,
            "naukri",
            "Apply",
        ),
        (
            "https://www.instahyre.com/job-123",
            """
            <html><title>Machine Learning Engineer - Instahyre</title><body>
              <h1>Machine Learning Engineer</h1>
              <button>Apply Now</button>
              <p>Work on model evaluation and production ML infrastructure.</p>
            </body></html>
            """,
            "instahyre",
            "Apply Now",
        ),
        (
            "https://wellfound.com/jobs/123",
            """
            <html><title>Founding Engineer - Wellfound</title><body>
              <h1>Founding Engineer</h1>
              <a role="button">Apply</a>
              <p>Own backend systems, product iteration, and customer integrations.</p>
            </body></html>
            """,
            "wellfound",
            "Apply",
        ),
    ],
)
def test_job_board_html_replay_requires_review_until_application_surface_is_trusted(
    url, html, expected_portal, expected_click
):
    analysis = analyze_portal_html_fixture(url, html)
    entry_action = choose_entry_action_for_fixture(analysis)

    assert analysis.workflow.portal_id == expected_portal
    assert analysis.workflow.workflow_kind == "JOB_BOARD_REDIRECT_OR_STEALTH"
    assert analysis.workflow.requires_external_redirect_watch is True
    assert analysis.page_state.likely_application_surface is False
    assert analysis.page_state.requires_review is True
    assert len(analysis.fields) == 0
    assert entry_action.ok is True
    assert entry_action.payload["clicked_label"] == expected_click


def test_job_board_replay_trusts_embedded_application_surface_with_fields():
    analysis = analyze_portal_html_fixture(
        "https://www.ziprecruiter.com/jobs/123",
        """
        <html><title>Apply to Data Engineer</title><body>
          <button>1-Click Apply</button>
          <form>
            <label for="name">Full name</label><input id="name" required>
            <label for="email">Email</label><input id="email" type="email" required>
            <label for="resume">Resume</label><input id="resume" type="file" required>
          </form>
          <p>Submit your application after reviewing your resume.</p>
        </body></html>
        """,
    )

    assert analysis.workflow.portal_id == "ziprecruiter"
    assert analysis.page_state.likely_application_surface is True
    assert analysis.page_state.requires_review is False
    assert len(analysis.fields) == 3


def test_replay_detects_login_mfa_and_sensitive_question_blockers():
    analysis = analyze_portal_html_fixture(
        "https://acme.taleo.net/careersection/jobdetail.ftl?job=123",
        """
        <html><body>
          <button>Apply Online</button>
          <label for="password">Password</label><input id="password" type="password">
          <label for="auth">Will you require sponsorship now or in the future?</label><select id="auth"></select>
          <p>Use your authenticator app for multi-factor authentication.</p>
        </body></html>
        """,
    )

    blocker_types = {blocker.blocker_type for blocker in analysis.blockers}
    assert {"LOGIN", "MFA", "AMBIGUOUS_QUESTION"}.issubset(blocker_types)


def test_safe_click_policy_pauses_when_multiple_entry_actions_match():
    result = choose_safe_click_target(
        ["Apply for this job", "Apply now"],
        [
            ControlCandidate("Apply for this job", "a", "https://boards.greenhouse.io/acme/jobs/1#app"),
            ControlCandidate("Apply for this job", "button", None),
        ],
    )

    assert result.ok is False
    assert result.payload["ambiguity_code"] == "AMBIGUOUS_PORTAL_ACTION"
    assert result.payload["candidate_count"] == 2


def test_safe_click_policy_refuses_final_submit_like_controls_for_entry_actions():
    result = choose_safe_click_target(
        ["Apply", "Submit application"],
        [
            ControlCandidate("Submit application", "button"),
            ControlCandidate("Complete application", "button"),
        ],
    )

    assert result.ok is False
    assert result.payload["message"] == "no matching safe portal action was found"
