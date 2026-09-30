import asyncio
import json

import pytest

from applyocalypse_automation import runner
from applyocalypse_automation.browser.adapter import BrowserStepResult
from applyocalypse_automation.browser.jev_client import JevError
from applyocalypse_automation.browser.jev_page import JevElement, JevPage
from applyocalypse_automation.control import WorkerControl
from applyocalypse_automation.jev_run import jev_ready, personal_values
from applyocalypse_automation.runner import MAX_JEV_PAUSES, jev_advance


def button(index, text):
    return JevElement(index=index, tag="button", is_field=False, label="", text=text, placeholder="",
                      filled=None, required=False, disabled=False, expanded=None, options=(), href="", hidden=False)


class FakeJevAdapter:
    """Each successful click moves to the next page, so the stuck detector stays quiet."""

    def __init__(self):
        self.clicks: list[int] = []

    async def jev_read_page(self):
        return JevPage(f"https://jobs.example.com/{len(self.clicks)}", "Apply", "", (),
                       (button(0, "Next"), button(1, "Submit application")))

    async def jev_click(self, element):
        self.clicks.append(element.index)
        return BrowserStepResult(True, "clicked", {"index": element.index})

    async def jev_scroll(self):
        return None

    async def detect_blockers(self):
        return []


def reply(tool="click", target=0, **noul):
    answers = {key: {"noul": noul.get(key, 0.0)} for key in ("done", "login", "error", "blocked", "irreversible")}
    answers["tool"] = {"choice": tool, "probabilities": {tool: 0.9}}
    answers["target"] = {"choice": str(target), "probabilities": {str(target): 0.9}}
    return answers


def scripted(*replies):
    queue = list(replies)

    async def ask(_state, _questions):
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    return ask


@pytest.fixture
def controls(monkeypatch):
    """What the user does at each pause, in order."""
    commands: list[str] = []

    def fake_wait(_work_dir, **_kwargs):
        command = commands.pop(0) if commands else "RESUME"
        return WorkerControl(command=command, reason=None, step_id=None, written_at=None, payload={})

    monkeypatch.setattr(runner, "wait_for_review_resume", fake_wait)
    return commands


def advance(adapter, ask, tmp_path, *, require_move=False):
    return asyncio.run(jev_advance(adapter=adapter, work_dir=tmp_path, run_id="run-jev", personal=[],
                                   context="test", require_move=require_move, ask=ask))


def events(capsys):
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


@pytest.mark.parametrize(
    ("replies", "result", "clicks"),
    [
        # Apply, then a page of fields: the runner's field loop takes over
        ((reply(target=0), reply(tool="fill")), "fill", [0]),
        # the review page: the submit gate takes over
        ((reply(done=0.95),), "final", []),
        # a final submit is never clicked, it goes to the submit gate
        ((reply(target=1),), "final", []),
        ((reply(target=0, irreversible=0.9),), "final", []),
    ],
)
def test_jev_hands_each_page_to_the_right_owner(replies, result, clicks, tmp_path, controls):
    adapter = FakeJevAdapter()

    assert advance(adapter, scripted(*replies), tmp_path) == result
    assert adapter.clicks == clicks


def test_a_page_just_filled_that_jev_wants_filled_again_goes_to_the_user(tmp_path, controls, capsys):
    adapter = FakeJevAdapter()

    assert advance(adapter, scripted(reply(tool="fill")), tmp_path, require_move=True) == "fill"

    kinds = [(e["event_type"], e["machine_state"].get("reason")) for e in events(capsys)]
    assert ("PAUSED", "JEV_FILL") in kinds
    assert ("RESUMED", "local_user_resolved_jev_pause") in kinds


@pytest.mark.parametrize(
    "first",
    [reply(tool="none"), JevError("Jev returned HTTP 429: rate_limit_exceeded")],
)
def test_an_unsure_or_unreachable_jev_pauses_and_the_user_can_cancel(first, tmp_path, controls, capsys):
    controls.append("CANCEL")

    assert advance(FakeJevAdapter(), scripted(first), tmp_path) == "cancelled"

    seen = events(capsys)
    assert seen[0]["event_type"] == "PAUSED"
    assert seen[-1]["payload"]["code"] == "USER_CANCELLED"


def test_a_page_that_keeps_stopping_jev_fails_the_run(tmp_path, controls, capsys):
    assert advance(FakeJevAdapter(), scripted(reply(tool="none")), tmp_path) == "cancelled"

    seen = events(capsys)
    assert sum(e["event_type"] == "PAUSED" for e in seen) == MAX_JEV_PAUSES
    assert seen[-1]["payload"]["code"] == "JEV_UNRESOLVED"


def test_jev_clicks_are_reported_as_portal_actions(tmp_path, controls, capsys):
    advance(FakeJevAdapter(), scripted(reply(target=0), reply(tool="fill")), tmp_path)

    click = next(e for e in events(capsys) if e["event_type"] == "PORTAL_ACTION_APPLIED")
    assert click["payload"]["clicked_label"] == "Next"
    assert click["payload"]["action_role"] == "JEV_CLICK"


def test_personal_values_keep_the_users_details_and_drop_generic_answers(monkeypatch):
    monkeypatch.setenv("APPLYO_APPLICATION_EMAIL", "jordan@example.com")
    answers = [{"fieldLabel": "Name", "value": "Jordan Rivera"}, {"fieldLabel": "Sponsor?", "value": "No"},
               {"fieldLabel": "Phone", "value": " "}, "not a dict"]

    assert personal_values(answers) == ["jordan@example.com", "Jordan Rivera"]


def test_jev_drives_only_with_a_key_and_an_adapter_that_can_serve_it(monkeypatch):
    monkeypatch.delenv("APPLYO_SECRETS_FILE", raising=False)
    runner_secret = "applyocalypse_automation.jev_run.jev_configured"
    monkeypatch.setattr(runner_secret, lambda: True)
    assert jev_ready(FakeJevAdapter())
    assert not jev_ready(object())
    monkeypatch.setattr(runner_secret, lambda: False)
    assert not jev_ready(FakeJevAdapter())
