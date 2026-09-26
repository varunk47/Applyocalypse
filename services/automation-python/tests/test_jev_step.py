import asyncio

import pytest

from applyocalypse_automation.browser.jev_page import JevElement, JevPage
from applyocalypse_automation.browser.jev_step import (
    MAX_WAITS,
    JevStatus,
    build_questions,
    clickable,
    resolve,
    run_jev_steps,
)


def element(index, tag="button", *, text="", is_field=False, disabled=False, hidden=False):
    return JevElement(index=index, tag=tag, is_field=is_field, label="", text=text, placeholder="",
                      filled=False if is_field else None, required=False, disabled=disabled,
                      expanded=None, options=(), href="", hidden=hidden)


PAGE = JevPage("https://jobs.example.com/apply", "Apply", "", (), (
    element(0, "input:email", is_field=True),
    element(1, text="Next"),
    element(2, text="Submit application"),
    element(3, text="Send code"),
    element(4, "input:checkbox", is_field=True),
))


def answers(tool="click", p_tool=0.9, target=1, p_target=0.8, **noul):
    reply = {key: {"noul": noul.get(key, 0.0)} for key in ("done", "login", "error", "blocked", "irreversible")}
    reply["tool"] = {"choice": tool, "probabilities": {tool: p_tool}}
    if target is not None:
        reply["target"] = {"choice": str(target), "probabilities": {str(target): p_target}}
    return reply


@pytest.mark.parametrize(
    ("reply", "round_index", "status", "target"),
    [
        (answers(done=0.9), 0, JevStatus.DONE, None),
        (answers(login=0.75), 0, JevStatus.NEEDS_LOGIN, None),
        (answers(error=0.8), 1, JevStatus.ERROR, None),
        # an error before any action is the page's own state, not ours to stop on
        (answers(error=0.8), 0, JevStatus.CLICK, 1),
        (answers(blocked=0.9), 0, JevStatus.BLOCKED, None),
        (answers(p_tool=0.2), 0, JevStatus.UNSURE, None),
        (answers(tool="none"), 0, JevStatus.UNSURE, None),
        (answers(tool="teleport"), 0, JevStatus.UNSURE, None),
        (answers(tool="fill"), 0, JevStatus.FILL, None),
        (answers(tool="scroll"), 0, JevStatus.SCROLL, None),
        (answers(tool="wait"), 0, JevStatus.WAIT, None),
        (answers(p_target=0.1), 0, JevStatus.UNSURE, None),
        (answers(target=None), 0, JevStatus.UNSURE, None),
        (answers(target=99), 0, JevStatus.UNSURE, None),
        (answers(target=1), 0, JevStatus.CLICK, 1),
        (answers(target=1, irreversible=0.7), 0, JevStatus.NEEDS_CONFIRMATION, 1),
        # a final submit button is held for approval even when Jev rates it reversible
        (answers(target=2), 0, JevStatus.NEEDS_CONFIRMATION, 2),
        (answers(target=3), 0, JevStatus.CLICK, 3),
        (answers(), 0, JevStatus.CLICK, 1),
        ({}, 0, JevStatus.UNSURE, None),
    ],
)
def test_resolve(reply, round_index, status, target):
    decision = resolve(reply, PAGE, round_index=round_index)

    assert decision.status is status
    assert (decision.target.index if decision.target else None) == target


def test_text_fields_are_not_click_targets_but_boxes_and_buttons_are():
    page = JevPage("u", "t", "", (), PAGE.elements + (element(5, disabled=True), element(6, hidden=True)))

    assert [e.index for e in clickable(page)] == [1, 2, 3, 4]
    assert set(build_questions("apply", clickable(page))["target"]["criteria"]) == {"1", "2", "3", "4"}
    assert "target" not in build_questions("apply", [])


class FakeDriver:
    def __init__(self, pages):
        self.pages = list(pages)
        self.actions: list[str] = []

    async def read_page(self):
        return self.pages[0] if len(self.pages) == 1 else self.pages.pop(0)

    async def click_element(self, target):
        self.actions.append(f"click {target.index}")
        return True

    async def fill_page(self):
        self.actions.append("fill")
        return True

    async def scroll(self):
        self.actions.append("scroll")


def scripted(*replies):
    queue = list(replies)
    states: list[str] = []

    async def ask(state, _questions):
        states.append(state)
        return queue.pop(0) if len(queue) > 1 else queue[0]

    return ask, states


async def _no_sleep(_seconds):
    return None


def run(driver, ask, personal=(), **kwargs):
    return asyncio.run(run_jev_steps(driver, ask, "apply to the job", list(personal), sleep=_no_sleep, **kwargs))


def page_with_text(text):
    return JevPage("u", "t", text, (), PAGE.elements)


def test_loop_fills_clicks_and_stops_when_done():
    driver = FakeDriver([page_with_text("a"), page_with_text("b"), page_with_text("c")])
    ask, _ = scripted(answers(tool="fill"), answers(target=1), answers(done=0.95))

    outcome = run(driver, ask)

    assert outcome.status is JevStatus.DONE
    assert driver.actions == ["fill", "click 1"]
    assert outcome.jev_calls == 3


def test_loop_never_clicks_a_final_submit():
    driver = FakeDriver([PAGE])
    ask, _ = scripted(answers(target=2))

    outcome = run(driver, ask)

    assert outcome.status is JevStatus.NEEDS_CONFIRMATION
    assert outcome.target.index == 2
    assert driver.actions == []


def test_loop_pauses_when_the_same_click_leaves_the_page_unchanged():
    driver = FakeDriver([PAGE])
    ask, _ = scripted(answers(target=1))

    outcome = run(driver, ask)

    assert outcome.status is JevStatus.UNSURE
    assert driver.actions == ["click 1", "click 1"]


def test_loop_pauses_when_the_page_never_loads():
    driver = FakeDriver([page_with_text(str(n)) for n in range(MAX_WAITS + 3)])
    ask, _ = scripted(answers(tool="wait"))

    outcome = run(driver, ask)

    assert outcome.status is JevStatus.UNSURE
    assert "loading" in outcome.reason


def test_loop_sends_redacted_state_only():
    driver = FakeDriver([page_with_text("Welcome back Jordan Rivera")])
    ask, states = scripted(answers(done=0.95))

    run(driver, ask, personal=["Jordan Rivera"])

    assert "Jordan Rivera" not in states[0]


def test_a_caller_that_fills_pages_itself_gets_the_fill_step_back():
    driver = FakeDriver([page_with_text("a"), page_with_text("b")])
    ask, _ = scripted(answers(target=1), answers(tool="fill"))

    outcome = run(driver, ask, stop_on=frozenset({JevStatus.FILL}))

    assert outcome.status is JevStatus.FILL
    assert driver.actions == ["click 1"]
