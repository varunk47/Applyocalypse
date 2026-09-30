"""Getting past a portal's account wall with the saved application login.

Workday, iCIMS, Taleo and most enterprise ATSes put a create-account or sign-in
page between the Apply click and the form. The run creates the account with the
email and password the user saved in onboarding, falls back to signing in when
the account already exists, and only hands the page back when neither works.
The password is a secret (CLAUDE.md #3), so no event may carry it.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path

import pytest
from js_bridge import run_browser_script

from applyocalypse_automation import account_wall
from applyocalypse_automation.account_wall import (
    ACCOUNT_CREATE_LABELS,
    SIGN_IN_LABELS,
    classify_account_form,
    try_account_wall,
)
from applyocalypse_automation.browser.adapter import BrowserBlocker, BrowserField, BrowserStepResult
from applyocalypse_automation.browser.field_detection import build_click_by_text_script, parse_click_by_text_result
from applyocalypse_automation.browser.portal_workflows import workflow_for_url
from applyocalypse_automation.otp.gmail_mcp import GmailApiOtpExtractor
from applyocalypse_automation.runner import (
    ENTRY_FIELDS_TIMEOUT_S,
    detect_fields_after_entry,
    execute_portal_entry_action,
    pause_for_blockers,
)

EMAIL = "grace.hopper@example.com"
PASSWORD = "Sm0ke#Pass-4821!"


def field(selector: str, label: str, field_type: str = "text") -> BrowserField:
    return BrowserField(
        field_id=selector.lstrip("#"),
        label=label,
        field_type=field_type,
        selector=selector,
        required=True,
        confidence=0.9,
    )


# The real Workday create-account page, as read from ghr.wd1.myworkdayjobs.com on
# 2026-09-25 (the honeypot is already dropped at detection).
CREATE = [
    field("#input-4", "Email Address*", "text"),
    field("#input-5", "Password*", "password"),
    field("#input-6", "Verify New Password*", "password"),
]
SIGN_IN = [field("#input-7", "Email Address*", "email"), field("#input-8", "Password*", "password")]
MY_INFORMATION = [field("#first-name", "Given Name(s)"), field("#last-name", "Family Name")]
PAGES: dict[str, list[BrowserField]] = {"create": CREATE, "sign_in": SIGN_IN, "form": MY_INFORMATION}


class FakeAccountAdapter:
    """Walks a small page graph: clicking a label moves to the page it leads to."""

    def __init__(
        self,
        page: str,
        transitions: dict[tuple[str, str], str],
        pages: dict[str, list[BrowserField]] | None = None,
        url: str = "https://ghr.wd1.myworkdayjobs.com/lateral-us/job/Atlanta/Data-Scientist-I_26034307/apply/applyManually",
    ) -> None:
        self.page = page
        self.url = url
        self.transitions = transitions
        self.pages = pages or PAGES
        self.filled: list[tuple[str | None, str]] = []
        self.clicks: list[tuple[tuple[str, ...], str | None]] = []

    async def detect_fields(self) -> list[BrowserField]:
        return list(self.pages[self.page])

    async def extract_visible_text(self) -> BrowserStepResult:
        return BrowserStepResult(True, "text extracted", {"url": self.url, "text": ""})

    async def apply_field_value(self, target: BrowserField, value: str) -> BrowserStepResult:
        self.filled.append((target.selector, value))
        return BrowserStepResult(True, "field value applied", {"field_id": target.field_id})

    async def click_by_text(self, labels: list[str], *, after_selector: str | None = None) -> BrowserStepResult:
        self.clicks.append((tuple(labels), after_selector))
        for label in labels:
            destination = self.transitions.get((self.page, label))
            if destination:
                self.page = destination
                return BrowserStepResult(True, "portal action clicked", {"clicked_label": label})
        return BrowserStepResult(False, "no matching safe portal action was found", {})

    async def detect_blockers(self) -> list[BrowserBlocker]:
        if self.page in {"create", "sign_in"}:
            return [BrowserBlocker("LOGIN", "Login or account creation page detected", 0.9)]
        return []


@pytest.fixture(autouse=True)
def _fresh_run_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(account_wall, "_ATTEMPTED_RUNS", set())


@pytest.fixture(name="saved_login")
def _saved_login(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APPLYO_APPLICATION_EMAIL", EMAIL)
    monkeypatch.setenv("APPLYO_APPLICATION_PASSWORD", PASSWORD)


def run_wall(adapter: FakeAccountAdapter) -> bool:
    return asyncio.run(try_account_wall(adapter, "run-account", context="portal entry action"))


# ---------------------------------------------------------------------------
# which page is this
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fields", "kind"),
    [
        (CREATE, "CREATE"),
        (SIGN_IN, "SIGN_IN"),
        (MY_INFORMATION, None),
        # A password with nowhere to put the email is not a form we can fill.
        ([field("#pw", "Password", "password")], None),
        # A field that only mentions a password is not a password input.
        ([field("#email", "Email"), field("#hint", "Password hint")], None),
    ],
)
def test_classifies_the_account_page(fields: list[BrowserField], kind: str | None) -> None:
    form = classify_account_form(fields)

    assert (form.kind if form else None) == kind


def test_only_an_account_terms_checkbox_counts_as_consent() -> None:
    fields = [
        *CREATE,
        field("#terms", "I agree to the Terms and Conditions", "checkbox"),
        field("#alerts", "Send me job alerts", "checkbox"),
    ]

    form = classify_account_form(fields)

    assert form is not None
    assert [item.selector for item in form.consent] == ["#terms"]


# ---------------------------------------------------------------------------
# getting through
# ---------------------------------------------------------------------------


def test_creates_the_account_with_the_saved_login(saved_login: None, capsys: pytest.CaptureFixture[str]) -> None:
    adapter = FakeAccountAdapter("create", {("create", "Create Account"): "form"})

    assert run_wall(adapter) is True

    assert adapter.filled == [("#input-4", EMAIL), ("#input-5", PASSWORD), ("#input-6", PASSWORD)]
    # The submit is the button after the last password box, not a header link.
    assert adapter.clicks == [(ACCOUNT_CREATE_LABELS, "#input-6")]
    output = capsys.readouterr().out
    assert PASSWORD not in output
    event = json.loads(output.splitlines()[-1])
    assert event["event_type"] == "PORTAL_ACTION_APPLIED"
    assert event["machine_state"]["account_action"] == "CREATE_ACCOUNT"


def test_an_existing_account_falls_back_to_signing_in(saved_login: None, capsys: pytest.CaptureFixture[str]) -> None:
    adapter = FakeAccountAdapter(
        "create",
        {
            # The portal re-renders the create form: this email already has an account.
            ("create", "Create Account"): "create",
            ("create", "Sign In"): "sign_in",
            ("sign_in", "Sign In"): "form",
        },
    )

    assert run_wall(adapter) is True

    assert adapter.filled[-2:] == [("#input-7", EMAIL), ("#input-8", PASSWORD)]
    assert adapter.clicks[-1] == (SIGN_IN_LABELS, "#input-8")
    assert adapter.page == "form"
    assert PASSWORD not in capsys.readouterr().out


def test_a_sign_in_page_signs_in(saved_login: None, capsys: pytest.CaptureFixture[str]) -> None:
    adapter = FakeAccountAdapter("sign_in", {("sign_in", "Sign In"): "form"})

    assert run_wall(adapter) is True

    assert adapter.filled == [("#input-7", EMAIL), ("#input-8", PASSWORD)]
    event = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert event["machine_state"]["account_action"] == "SIGN_IN"


def test_the_account_terms_are_accepted_but_nothing_else_is_ticked(saved_login: None, capsys: pytest.CaptureFixture[str]) -> None:
    pages = {
        **PAGES,
        "create": [
            *CREATE,
            field("#terms", "I agree to the Terms and Conditions", "checkbox"),
            field("#alerts", "Send me job alerts", "checkbox"),
        ],
    }
    adapter = FakeAccountAdapter("create", {("create", "Create Account"): "form"}, pages)

    run_wall(adapter)
    capsys.readouterr()

    assert ("#terms", "Yes") in adapter.filled
    assert all(selector != "#alerts" for selector, _value in adapter.filled)


def test_without_a_saved_login_the_wall_is_left_to_the_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APPLYO_APPLICATION_EMAIL", raising=False)
    monkeypatch.delenv("APPLYO_APPLICATION_PASSWORD", raising=False)
    adapter = FakeAccountAdapter("create", {("create", "Create Account"): "form"})

    assert run_wall(adapter) is False
    assert adapter.filled == []
    assert adapter.clicks == []


@pytest.mark.parametrize(
    "url",
    [
        "https://careers.example.com/login",
        "https://jobs.acme-industries.io/candidate/register",
        "https://secure.indeed.com/auth",
    ],
)
def test_an_unrecognised_portal_gets_the_saved_login_too(saved_login: None, url: str) -> None:
    adapter = FakeAccountAdapter("sign_in", {("sign_in", "Sign In"): "form"}, url=url)

    assert run_wall(adapter) is True
    assert adapter.filled == [("#input-7", EMAIL), ("#input-8", PASSWORD)]


@pytest.mark.parametrize(
    "url",
    [
        "https://www.linkedin.com/login",
        "https://linkedin.com/checkpoint/lg/login",
        "https://accounts.google.com/v3/signin/identifier",
        "https://login.microsoftonline.com/common/oauth2/authorize",
        "https://login.live.com/login.srf",
        "https://appleid.apple.com/auth/authorize",
        "https://acme.okta.com/login/login.htm",
        "",
    ],
)
def test_linkedin_and_identity_providers_never_get_the_saved_password(saved_login: None, url: str) -> None:
    """LinkedIn is the user's own account, and so is a Google, Microsoft, Apple or Okta sign-in."""
    adapter = FakeAccountAdapter("sign_in", {("sign_in", "Sign In"): "form"}, url=url)

    assert run_wall(adapter) is False
    assert adapter.filled == []


def test_a_lookalike_host_is_not_mistaken_for_linkedin(saved_login: None) -> None:
    adapter = FakeAccountAdapter("sign_in", {("sign_in", "Sign In"): "form"}, url="https://notlinkedin.com/login")

    assert run_wall(adapter) is True


def test_a_login_box_in_a_foreign_frame_never_gets_the_password(saved_login: None) -> None:
    """An SSO iframe on a real Workday page is the identity provider's form, not Workday's."""
    okta = {"frame_url": "https://acme.okta.com/login/login.htm", "frame_index": 1}
    framed = [
        BrowserField("frame:1:email", "Username", "email", "#okta-signin-username", True, 0.9, okta),
        BrowserField("frame:1:pw", "Password", "password", "#okta-signin-password", True, 0.9, okta),
    ]
    adapter = FakeAccountAdapter("sign_in", {("sign_in", "Sign In"): "form"}, {**PAGES, "sign_in": framed})

    assert run_wall(adapter) is False
    assert adapter.filled == []


def test_a_password_box_without_a_selector_is_not_submitted(saved_login: None) -> None:
    """Unanchored, the click could land on the page header's Sign In instead of the form's."""
    unanchored = [SIGN_IN[0], BrowserField("pw", "Password*", "password", None, True, 0.9)]
    adapter = FakeAccountAdapter("sign_in", {("sign_in", "Sign In"): "form"}, {**PAGES, "sign_in": unanchored})

    assert run_wall(adapter) is False
    assert adapter.clicks == []


def test_a_page_that_is_not_an_account_form_is_left_alone(saved_login: None) -> None:
    adapter = FakeAccountAdapter("form", {})

    assert run_wall(adapter) is False
    assert adapter.filled == []


# ---------------------------------------------------------------------------
# inside the blocker pause
# ---------------------------------------------------------------------------


def test_the_login_blocker_clears_without_a_pause(saved_login: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    adapter = FakeAccountAdapter("create", {("create", "Create Account"): "form"})

    should_stop = asyncio.run(
        pause_for_blockers(adapter, tmp_path, "run-account", asyncio.run(adapter.detect_blockers()), context="portal entry action")
    )

    output = capsys.readouterr().out
    assert should_stop is False
    assert "PAUSED" not in [json.loads(line)["event_type"] for line in output.splitlines()]
    assert PASSWORD not in output


def test_a_wall_that_will_not_clear_is_tried_once_then_handed_to_the_user(
    saved_login: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Retrying a rejected password is how an account gets locked, so one attempt only."""
    adapter = FakeAccountAdapter("sign_in", {})

    def cancel_after_pause() -> None:
        time.sleep(0.2)
        (tmp_path / "control.json").write_text(json.dumps({"command": "CANCEL"}), encoding="utf-8")

    thread = threading.Thread(target=cancel_after_pause, daemon=True)
    thread.start()
    should_stop = asyncio.run(
        pause_for_blockers(adapter, tmp_path, "run-account", asyncio.run(adapter.detect_blockers()), context="portal entry action")
    )
    thread.join(timeout=2)

    events = [json.loads(line)["event_type"] for line in capsys.readouterr().out.splitlines()]
    assert should_stop is True
    assert len(adapter.clicks) == 1
    assert "PAUSED" in events


def test_the_wall_is_tried_once_per_run_not_once_per_pause(saved_login: None) -> None:
    """The runner pauses for blockers at more than one step; each must not retry the password."""
    adapter = FakeAccountAdapter("sign_in", {})
    run_wall(adapter)

    assert run_wall(adapter) is False
    assert len(adapter.clicks) == 1


def test_a_new_account_can_still_sign_in_once_after_its_verification_email(saved_login: None) -> None:
    """Workday: create the account, verify the email, then sign in with the password just set."""
    adapter = FakeAccountAdapter("create", {("create", "Create Account"): "form", ("sign_in", "Sign In"): "form"})
    assert run_wall(adapter) is True

    adapter.page = "sign_in"
    assert run_wall(adapter) is True
    adapter.page = "sign_in"
    assert run_wall(adapter) is False
    assert [labels[0] for labels, _ in adapter.clicks] == ["Create Account", "Sign In"]


# ---------------------------------------------------------------------------
# which button the submit lands on
# ---------------------------------------------------------------------------

ORIGIN = "https://acme.wd1.myworkdayjobs.com"
HEADER_RECT = {"left": 900, "top": 10, "width": 80, "height": 30}
FORM_RECT = {"left": 100, "top": 400, "width": 200, "height": 40}


def sign_in_page() -> dict:
    """Workday's header carries its own Sign In button above the form's."""
    return {
        "origin": ORIGIN,
        "elements": [
            {"tag": "button", "text": "Sign In", "rect": HEADER_RECT},
            {"tag": "input", "attrs": {"id": "input-8", "type": "password"}, "rect": {"left": 100, "top": 300, "width": 200, "height": 30}},
            {"tag": "button", "text": "Sign In", "rect": FORM_RECT},
        ],
    }


def test_the_submit_is_the_button_after_the_password_field() -> None:
    script = build_click_by_text_script(list(SIGN_IN_LABELS), locate_only=True, after_selector="#input-8")

    payload = parse_click_by_text_result(json.dumps(run_browser_script(script, sign_in_page())["result"])).payload

    assert payload["click_target"]["x"] == FORM_RECT["left"] + FORM_RECT["width"] / 2
    assert payload["click_target"]["y"] == FORM_RECT["top"] + FORM_RECT["height"] / 2


def test_a_missing_anchor_clicks_nothing() -> None:
    script = build_click_by_text_script(list(SIGN_IN_LABELS), locate_only=True, after_selector="#gone")

    result = run_browser_script(script, sign_in_page())["result"]

    assert result["ok"] is False


# ---------------------------------------------------------------------------
# reaching the wall: Workday's apply chooser
# ---------------------------------------------------------------------------


class FakeEntryAdapter:
    def __init__(self, visible: set[str]) -> None:
        self.visible = visible
        self.clicks: list[list[str]] = []

    async def click_by_text(self, labels: list[str], *, after_selector: str | None = None) -> BrowserStepResult:
        self.clicks.append(list(labels))
        for label in labels:
            if label in self.visible:
                return BrowserStepResult(True, "portal action clicked", {"clicked_label": label})
        return BrowserStepResult(False, "no matching safe portal action was found", {})


def test_workday_picks_apply_manually_on_the_chooser(capsys: pytest.CaptureFixture[str]) -> None:
    """Apply opens a chooser; Autofill with Resume would upload a file no one reviewed."""
    workflow = workflow_for_url("https://ghr.wd1.myworkdayjobs.com/lateral-us/job/Atlanta/Data-Scientist-I_26034307")
    adapter = FakeEntryAdapter({"Apply", "Apply Manually", "Autofill with Resume"})

    result = asyncio.run(execute_portal_entry_action(adapter=adapter, workflow=workflow, run_id="run-entry", context="observation"))

    assert result.ok is True
    assert adapter.clicks[-1] == ["Apply Manually"]
    event = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert event["payload"]["followup_clicked_label"] == "Apply Manually"


def test_a_portal_without_a_chooser_clicks_once(capsys: pytest.CaptureFixture[str]) -> None:
    workflow = workflow_for_url("https://boards.greenhouse.io/acme/jobs/123")
    adapter = FakeEntryAdapter({"Apply now"})

    asyncio.run(execute_portal_entry_action(adapter=adapter, workflow=workflow, run_id="run-entry", context="observation"))
    capsys.readouterr()

    assert len(adapter.clicks) == 1


class SlowFormAdapter:
    """Workday's applyManually route shows a spinner before the account form paints."""

    def __init__(self, empty_polls: int) -> None:
        self.empty_polls = empty_polls
        self.detections = 0

    async def detect_fields(self) -> list[BrowserField]:
        self.detections += 1
        return [] if self.detections <= self.empty_polls else list(CREATE)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


def detect_after_entry(adapter: SlowFormAdapter, entry_ok: bool, clock: FakeClock) -> list[BrowserField]:
    return asyncio.run(detect_fields_after_entry(adapter, entry_ok, sleep=clock.sleep, clock=clock))


def test_the_form_is_waited_for_after_the_entry_click() -> None:
    """Found live: detection ran on the spinner, saw no fields and no login wall, and moved on."""
    adapter = SlowFormAdapter(empty_polls=3)

    fields = detect_after_entry(adapter, True, FakeClock())

    assert fields == CREATE
    assert adapter.detections == 4


def test_a_failed_entry_click_is_not_waited_on() -> None:
    adapter = SlowFormAdapter(empty_polls=3)

    assert detect_after_entry(adapter, False, FakeClock()) == []
    assert adapter.detections == 1


def test_a_page_that_never_shows_a_form_stops_waiting() -> None:
    adapter = SlowFormAdapter(empty_polls=10_000)
    clock = FakeClock()

    assert detect_after_entry(adapter, True, clock) == []
    assert clock.now <= ENTRY_FIELDS_TIMEOUT_S + 1


# ---------------------------------------------------------------------------
# the code has to come from this sign-up, not an older email
# ---------------------------------------------------------------------------


def test_the_gmail_search_only_reads_mail_sent_after_the_cutoff(tmp_path: Path) -> None:
    extractor = GmailApiOtpExtractor(token_json_path=str(tmp_path / "token.json"), received_after=1_790_000_000.7)

    assert "after:1790000000" in extractor.search_query()
