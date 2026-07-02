from __future__ import annotations

import asyncio
import io
import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from applyocalypse_automation.browser.field_detection import ControlCandidate, choose_safe_click_target
from applyocalypse_automation.browser.html_replay import analyze_portal_html_fixture, choose_entry_action_for_fixture
from applyocalypse_automation.event_protocol import EventType
from applyocalypse_automation.runner import _lazy_generate_cover_letter_for_portal


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
            "https://jobs.ashbyhq.com/northstar/aaaabbbb-cccc-dddd-eeee-ffff00001111",
            """
            <html><title>Product Engineer - Northstar</title><body>
              <button>Apply for this Job</button>
              <form>
                <label for="name">Full name</label><input id="name" required>
                <label for="email">Email</label><input id="email" type="email" required>
                <label for="resume">Resume</label><input id="resume" type="file" accept=".pdf,.docx" required>
                <label for="cover">Cover letter</label><input id="cover" type="file" accept=".pdf">
              </form>
              <p>Review your autofilled answers before you submit your application.</p>
            </body></html>
            """,
            "ashby",
            "Apply for this Job",
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
    assert "known_ats_surface" in analysis.page_state.signals
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


# ---------------------------------------------------------------------------
# Task 3.4: lazy cover letter generation at portal cover-letter upload field
# ---------------------------------------------------------------------------

_VALID_LAZY_CL = (
    "Dear Hiring Team,\n\n"
    "My background in guidance software maps to the systems engineer role you describe. "
    "At MIT I led the team that created error detection routines that prevented mid-flight aborts.\n\n"
    "I would bring a careful engineering style and strong Python skills to this position.\n\n"
    "Thank you for your consideration.\n\n"
    "Best regards,\nMargaret Hamilton"
)

_LAZY_PROFILE = {
    "profile": {
        "legalName": "Margaret Hamilton",
        "email": "margaret@mit.edu",
    },
    "experience": [
        {
            "title": "Lead Software Engineer",
            "company": "MIT",
            "bullets": ["Led error detection for Apollo Guidance Computer."],
        }
    ],
}


def _fake_lazy_client(text: str) -> Any:
    async def _complete(*, system: str, user: str, schema_name: str) -> dict[str, Any]:
        return {"cover_letter_text": text}
    client = AsyncMock()
    client.complete_json = _complete
    return client


def _capture_events(fn: Any, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    """Capture JSON events emitted to stdout during an async coroutine call."""
    buf = io.BytesIO()
    old_buf = None
    import sys

    old_buf = sys.stdout.buffer
    try:
        sys.stdout = type(sys.stdout)(buf)  # type: ignore[assignment]
    except Exception:
        pass

    events: list[dict[str, Any]] = []
    try:
        captured_bytes = io.BytesIO()

        class _Cap:
            def write(self, data: bytes) -> int:
                captured_bytes.write(data)
                return len(data)

            def flush(self) -> None:
                pass

        real_buffer = sys.stdout.buffer
        sys.stdout.buffer = _Cap()  # type: ignore[assignment]
        try:
            asyncio.run(fn(*args, **kwargs))
        finally:
            sys.stdout.buffer = real_buffer  # type: ignore[assignment]

        for line in captured_bytes.getvalue().decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    except Exception:
        pass

    if old_buf is not None:
        try:
            sys.stdout = type(sys.stdout)(old_buf)  # type: ignore[assignment]
        except Exception:
            pass
    return events


def test_lazy_cover_letter_emits_rendered_and_review_events(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        from docx import Document  # type: ignore  # noqa: F401
    except ImportError:
        pytest.skip("python-docx not installed")

    monkeypatch.setenv("APPLYO_LAZY_COVER_LETTER", "1")
    monkeypatch.delenv("LITELLM_MODEL_STRONG", raising=False)
    monkeypatch.delenv("LITELLM_MODEL", raising=False)

    from applyocalypse_automation.event_protocol import WorkerEvent
    emitted: list[str] = []

    def _capture_emit(self: WorkerEvent) -> None:
        emitted.append(self.event_type.value)

    monkeypatch.setattr(WorkerEvent, "emit", _capture_emit)

    with tempfile.TemporaryDirectory() as tmp:
        work_dir = Path(tmp)
        (work_dir / "canonical-profile.json").write_text(
            json.dumps(_LAZY_PROFILE), encoding="utf-8"
        )
        (work_dir / "job-description.txt").write_text(
            "We need a systems engineer with Python and guidance software experience.",
            encoding="utf-8",
        )
        (work_dir / "job-target.json").write_text(
            json.dumps({"company": "NASA", "role": "Systems Engineer"}), encoding="utf-8"
        )

        result = asyncio.run(
            _lazy_generate_cover_letter_for_portal(
                run_id="test-run-lazy-cl",
                work_dir=work_dir,
                output_dir=work_dir,
            )
        )

        assert result is not None, "Expected a generated file dict"
        assert Path(result["local_path"]).exists(), "Generated DOCX file must exist on disk"

    assert EventType.COVER_LETTER_RENDERED.value in emitted, (
        f"COVER_LETTER_RENDERED not found in {emitted}"
    )
    assert EventType.USER_REVIEW_REQUIRED.value in emitted, (
        f"USER_REVIEW_REQUIRED not found in {emitted}"
    )
    cl_rendered_idx = emitted.index(EventType.COVER_LETTER_RENDERED.value)
    review_idx = emitted.index(EventType.USER_REVIEW_REQUIRED.value)
    assert cl_rendered_idx < review_idx, "COVER_LETTER_RENDERED must precede USER_REVIEW_REQUIRED"


def test_lazy_cover_letter_disabled_when_env_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APPLYO_LAZY_COVER_LETTER", raising=False)

    with tempfile.TemporaryDirectory() as tmp:
        result = asyncio.run(
            _lazy_generate_cover_letter_for_portal(
                run_id="test-run-disabled",
                work_dir=Path(tmp),
                output_dir=Path(tmp),
            )
        )
        assert result is None


def test_portal_with_required_cover_letter_field_is_detected_as_cover_letter() -> None:
    analysis = analyze_portal_html_fixture(
        "https://boards.greenhouse.io/acme/jobs/789",
        """
        <html><title>Apply - Systems Engineer</title><body>
          <a href="/acme/jobs/789#app">Apply for this job</a>
          <form>
            <label for="name">Full name</label><input id="name" required>
            <label for="email">Email</label><input id="email" type="email" required>
            <label for="resume">Resume</label><input id="resume" type="file" accept=".pdf,.docx" required>
            <label for="cover_letter">Cover letter</label>
            <input id="cover_letter" name="cover_letter" type="file" accept=".pdf,.doc,.docx" required>
          </form>
        </body></html>
        """,
    )

    field_labels = [f.label.lower() for f in analysis.fields]
    assert any("cover" in label for label in field_labels), (
        f"Expected a cover letter field in {field_labels}"
    )
    assert analysis.page_state.likely_application_surface is True
