"""Get past a portal's create-account or sign-in page with the saved application login.

Workday, iCIMS, Taleo and most enterprise ATSes put an account page between the
Apply click and the form. The login the user saved in onboarding is the one every
portal account is created with, so the run creates the account, falls back to
signing in when the portal says the account already exists, and hands the page
back to the user only when neither gets through. Any verification code the portal
emails afterwards is picked up from Gmail by the blocker loop, as for any OTP.

The password is a secret (CLAUDE.md #3): it is typed into the page and nowhere
else, and no event here carries it or the email.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Literal

from .browser.adapter import BrowserField
from .browser.portal_workflows import workflow_for_url
from .event_protocol import EventType, Severity, WorkerEvent
from .field_resolution import normalize_field_label
from .secret_env import get_secret

ACCOUNT_CREATE_LABELS = ("Create Account", "Create an Account", "Register", "Sign Up")
SIGN_IN_LABELS = ("Sign In", "Log In", "Login")

# Ticking "I agree to the terms" is part of creating the account. A marketing
# opt-in on the same page is not, so anything about alerts or offers stays unticked.
_CONSENT = re.compile(r"\b(agree|accept|terms|privacy|consent)\b")
_NOT_CONSENT = re.compile(r"\b(alert|alerts|marketing|newsletter|offers|promotional|sms|text messages?)\b")

AccountFormKind = Literal["CREATE", "SIGN_IN"]

# Runs whose saved login has already been tried. A worker process handles one run,
# but the runner pauses for blockers at several steps, and each of those pauses
# must not type a password the portal may already have rejected.
_ATTEMPTED_RUNS: set[str] = set()


@dataclass(frozen=True, slots=True)
class AccountForm:
    kind: AccountFormKind
    emails: tuple[BrowserField, ...]
    passwords: tuple[BrowserField, ...]
    consent: tuple[BrowserField, ...]


def classify_account_form(fields: list[BrowserField]) -> AccountForm | None:
    """A create form asks for the password twice; a sign-in form asks once."""
    passwords = tuple(item for item in fields if item.field_type == "password")
    emails = tuple(
        item
        for item in fields
        if item.field_type != "password" and (item.field_type == "email" or "email" in normalize_field_label(item.label))
    )
    if not passwords or not emails:
        return None
    kind: AccountFormKind = "CREATE" if len(passwords) >= 2 else "SIGN_IN"
    consent = tuple(
        item
        for item in fields
        if kind == "CREATE"
        and item.field_type == "checkbox"
        and _CONSENT.search(normalize_field_label(item.label))
        and not _NOT_CONSENT.search(normalize_field_label(item.label))
    )
    return AccountForm(kind=kind, emails=emails, passwords=passwords, consent=consent)


async def try_account_wall(adapter: object, run_id: str, *, context: str) -> bool:
    """Create the account, or sign in, with the saved login. True once a form was submitted.

    Tried at most once per run: retrying a password the portal rejected is how an
    account gets locked.
    """
    email = os.getenv("APPLYO_APPLICATION_EMAIL", "").strip()
    password = get_secret("APPLYO_APPLICATION_PASSWORD")
    if not email or not password or run_id in _ATTEMPTED_RUNS or not await _on_known_ats(adapter):
        return False
    form = classify_account_form(await adapter.detect_fields())  # type: ignore[attr-defined]
    if form is None or not _fillable(form):
        return False
    _ATTEMPTED_RUNS.add(run_id)
    if form.kind == "CREATE":
        if not await _submit(adapter, run_id, form, email, password, ACCOUNT_CREATE_LABELS, "CREATE_ACCOUNT", context):
            return False
        # A portal that already holds an account for this email shows the create
        # form again; its own "Sign In" link sits below the password boxes.
        again = classify_account_form(await adapter.detect_fields())  # type: ignore[attr-defined]
        if again is None or again.kind != "CREATE":
            return True
        opened = await adapter.click_by_text(list(SIGN_IN_LABELS), after_selector=again.passwords[-1].selector)  # type: ignore[attr-defined]
        if not opened.ok:
            return False
        form = classify_account_form(await adapter.detect_fields())  # type: ignore[attr-defined]
        if form is None or form.kind != "SIGN_IN" or not _fillable(form):
            return False
    return await _submit(adapter, run_id, form, email, password, SIGN_IN_LABELS, "SIGN_IN", context)


async def _on_known_ats(adapter: object) -> bool:
    """Only an ATS the app recognises gets the saved password.

    A redirect can land on LinkedIn, Indeed or a Google sign-in, where the login
    is the user's own account; typing the portal password there is a failed
    login at best and a lockout at worst.
    """
    try:
        page = await adapter.extract_visible_text()  # type: ignore[attr-defined]
    except Exception:
        return False
    url = str(page.payload.get("url") or "")
    return bool(url) and workflow_for_url(url).workflow_kind == "ATS_DIRECT_FORM"


def _fillable(form: AccountForm) -> bool:
    """Every field sits in the page or in an ATS frame, and the submit can be anchored.

    An SSO iframe (Okta, Azure AD, Google) on a genuine Workday page belongs to the
    identity provider, so a field in a frame from any other host refuses the form.
    Without a password selector the submit click cannot be pinned below the form
    and could land on the page header's own Sign In.
    """
    fields = (*form.emails, *form.passwords, *form.consent)
    in_ats = all(
        not item.metadata.get("frame_url")
        or workflow_for_url(str(item.metadata["frame_url"])).workflow_kind == "ATS_DIRECT_FORM"
        for item in fields
    )
    return in_ats and bool(form.passwords[-1].selector)


async def _submit(
    adapter: object,
    run_id: str,
    form: AccountForm,
    email: str,
    password: str,
    labels: tuple[str, ...],
    account_action: str,
    context: str,
) -> bool:
    writes = [
        *((item, email) for item in form.emails),
        *((item, password) for item in form.passwords),
        *((item, "Yes") for item in form.consent),
    ]
    for target, value in writes:
        filled = await adapter.apply_field_value(target, value)  # type: ignore[attr-defined]
        if not filled.ok:
            _emit(run_id, account_action, context, ok=False, message=f"Could not fill {target.label or 'a login field'}")
            return False
    result = await adapter.click_by_text(list(labels), after_selector=form.passwords[-1].selector)  # type: ignore[attr-defined]
    _emit(
        run_id,
        account_action,
        context,
        ok=result.ok,
        message=result.message,
        clicked_label=result.payload.get("clicked_label"),
        attempted_labels=list(labels),
    )
    return result.ok


def _emit(run_id: str, account_action: str, context: str, *, ok: bool, message: str, **payload: object) -> None:
    done = "Created the portal account" if account_action == "CREATE_ACCOUNT" else "Signed in to the portal"
    WorkerEvent(
        event_type=EventType.PORTAL_ACTION_APPLIED,
        run_id=run_id,
        step_id=None,
        severity=Severity.INFO if ok else Severity.WARN,
        message=f"{done} with the saved application login" if ok else f"Portal login step did not go through: {message}",
        machine_state={"account_action": account_action, "context": context, "ok": ok},
        ui_state={"current_step": "portal_workflow"},
        payload={"account_action": account_action, "context": context, **payload},
    ).emit()
