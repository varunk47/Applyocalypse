"""Jev's step loop: read the page, ask Jev once, take one action, repeat.

Adapted from jev-browser's `do()` loop (MIT, Ying-Kai Liao), with this app's
rules on top:

- Jev picks clicks and classifies pages. Filling is handed back to the answer
  engine (the `fill` tool), so Jev never chooses or types a value.
- Anything Jev is unsure about stops the loop with UNSURE, and the run pauses
  for the user. There is no silent fallback.
- A click Jev rates as hard to undo, or on a button that reads like a final
  submit, is never taken: the loop stops with NEEDS_CONFIRMATION so the
  submit approval gate decides.
"""
from __future__ import annotations

import asyncio
import re
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from .jev_page import JevElement, JevPage, jev_state

MAX_ROUNDS = 15
MAX_WAITS = 6
REPEAT_LIMIT = 3
DONE_AT = 0.85
LOGIN_AT = 0.7
ERROR_AT = 0.7
BLOCKED_AT = 0.85
IRREVERSIBLE_AT = 0.6
MIN_TOOL = 0.4
MIN_TARGET = 0.3
WAIT_S = 1.0

TOOLS = {
    "click": "Click an element: a button, link, tab, menu entry or option.",
    "fill": "Answer the empty form fields on the page (typing, choosing, ticking, uploading).",
    "scroll": "Scroll down to reveal more of the page.",
    "wait": "Wait for the page to finish loading or updating.",
    "none": "No action helps: the goal is reached or nothing on the page can move it forward.",
}

FINAL_SUBMIT = re.compile(
    r"\b(submit|send)\b(?!\s*(a\s+)?(code|otp|again|link))|\bfinish\b|\bcomplete (my |your )?application\b",
    re.IGNORECASE,
)


class JevStatus(StrEnum):
    CLICK = "CLICK"
    FILL = "FILL"
    SCROLL = "SCROLL"
    WAIT = "WAIT"
    DONE = "DONE"
    NEEDS_LOGIN = "NEEDS_LOGIN"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
    BLOCKED = "BLOCKED"
    ERROR = "ERROR"
    UNSURE = "UNSURE"
    MAX_ROUNDS = "MAX_ROUNDS"


TERMINAL = {
    JevStatus.DONE, JevStatus.NEEDS_LOGIN, JevStatus.NEEDS_CONFIRMATION, JevStatus.BLOCKED,
    JevStatus.ERROR, JevStatus.UNSURE, JevStatus.MAX_ROUNDS,
}


@dataclass(frozen=True, slots=True)
class JevDecision:
    status: JevStatus
    reason: str
    target: JevElement | None = None
    scores: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class JevOutcome:
    status: JevStatus
    reason: str
    page: JevPage | None
    history: tuple[str, ...]
    jev_calls: int
    target: JevElement | None = None


class JevDriver(Protocol):
    async def read_page(self) -> JevPage: ...

    async def click_element(self, element: JevElement) -> bool: ...

    async def fill_page(self) -> bool: ...

    async def scroll(self) -> None: ...


Ask = Callable[[str, dict[str, dict[str, Any]]], Awaitable[dict[str, dict[str, Any]]]]


def clickable(page: JevPage) -> list[JevElement]:
    """Elements Jev may click. Text boxes are the answer engine's, not Jev's."""
    return [
        e for e in page.elements
        if not e.disabled and not e.hidden and not (e.is_field and e.tag.split("[")[0] in _TEXT_TAGS)
    ]


_TEXT_TAGS = {"textarea", "select", "input:text", "input:email", "input:tel", "input:password",
              "input:number", "input:url", "input:search", "input:date", "input:file"}


def build_questions(goal: str, targets: list[JevElement]) -> dict[str, dict[str, Any]]:
    questions: dict[str, dict[str, Any]] = {
        "done": _noul(f"Does `page` show that this goal has been achieved: {goal}?"),
        "login": _noul("Is `page` a sign-in or sign-up screen, or asking the user to log in, before the goal can continue?"),
        "error": _noul("Does `page` show an error or rejection message, such as a validation error or access denied?"),
        "blocked": _noul(
            "Is there something on `page` that stops progress and cannot be handled by clicking or filling "
            "fields, such as a captcha, access denied or an error page?"
        ),
        "irreversible": _noul(
            "Would the next action toward the goal on `page` have an effect outside this browser that is hard "
            "to undo, such as submitting an application, paying, sending a message or deleting something?"
        ),
        "tool": {
            "type": "choice",
            "instructions": f"What is the next action toward this goal on `page`: {goal}?",
            "criteria": TOOLS,
        },
    }
    if targets:
        questions["target"] = {
            "type": "choice",
            "instructions": "If the next action is a click, which entry of `page.elements` (by its number) should it click?",
            "criteria": {str(e.index): None for e in targets},
        }
    return questions


def _noul(instructions: str) -> dict[str, Any]:
    return {"type": "noul", "instructions": instructions}


def resolve(answers: dict[str, dict[str, Any]], page: JevPage, *, round_index: int) -> JevDecision:
    """Turn one round of Jev answers into a single decision. Pure, so it is table-tested."""
    scores = {key: _noul_score(answers, key) for key in ("done", "login", "error", "blocked", "irreversible")}
    tool, p_tool = _top_choice(answers, "tool")
    target_key, p_target = _top_choice(answers, "target")
    target = page.element(int(target_key)) if target_key.isdigit() else None
    scores |= {"tool": p_tool, "target": p_target}

    if scores["done"] >= DONE_AT:
        return JevDecision(JevStatus.DONE, "Jev judged the goal reached", scores=scores)
    if scores["login"] >= LOGIN_AT:
        return JevDecision(JevStatus.NEEDS_LOGIN, "the page asks to sign in or create an account", scores=scores)
    if round_index > 0 and scores["error"] >= ERROR_AT:
        return JevDecision(JevStatus.ERROR, "the page shows an error after the last action", scores=scores)
    if scores["blocked"] >= BLOCKED_AT:
        return JevDecision(JevStatus.BLOCKED, "something on the page blocks progress", scores=scores)
    if tool not in TOOLS or p_tool < MIN_TOOL:
        return JevDecision(JevStatus.UNSURE, "Jev is unsure what to do next", scores=scores)
    if tool == "none":
        return JevDecision(JevStatus.UNSURE, "Jev sees no action that moves the goal forward", scores=scores)
    if tool == "fill":
        return JevDecision(JevStatus.FILL, "the page has fields to answer", scores=scores)
    if tool == "scroll":
        return JevDecision(JevStatus.SCROLL, "more of the page is needed", scores=scores)
    if tool == "wait":
        return JevDecision(JevStatus.WAIT, "the page is still loading", scores=scores)
    if target is None or p_target < MIN_TARGET:
        return JevDecision(JevStatus.UNSURE, "Jev is unsure which element to click", scores=scores)
    if scores["irreversible"] >= IRREVERSIBLE_AT or FINAL_SUBMIT.search(target.name):
        return JevDecision(
            JevStatus.NEEDS_CONFIRMATION, f"clicking '{target.name}' may submit or be hard to undo",
            target=target, scores=scores,
        )
    return JevDecision(JevStatus.CLICK, f"click '{target.name}'", target=target, scores=scores)


def _noul_score(answers: dict[str, dict[str, Any]], key: str) -> float:
    try:
        return float(answers.get(key, {}).get("noul", 0.0))
    except (TypeError, ValueError):
        return 0.0


def _top_choice(answers: dict[str, dict[str, Any]], key: str) -> tuple[str, float]:
    answer = answers.get(key) or {}
    choice = str(answer.get("choice") or "")
    probabilities = answer.get("probabilities") or {}
    try:
        p = float(probabilities.get(choice, answer.get("confidence", 0.0)))
    except (TypeError, ValueError):
        p = 0.0
    return choice, p


async def run_jev_steps(
    driver: JevDriver,
    ask: Ask,
    goal: str,
    personal_values: list[str],
    *,
    max_rounds: int = MAX_ROUNDS,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    stop_on: frozenset[JevStatus] = frozenset(),
) -> JevOutcome:
    """Drive the page toward `goal` until Jev is done, unsure, or needs the user.

    `stop_on` ends the loop on a step it would otherwise take, for a caller that
    takes that step itself (the runner fills pages with its own field loop).
    """
    history: list[str] = []
    seen: Counter[str] = Counter()
    waits = 0
    page: JevPage | None = None
    for round_index in range(max_rounds):
        page = await driver.read_page()
        targets = clickable(page)
        answers = await ask(jev_state(page, personal_values), build_questions(goal, targets))
        decision = resolve(answers, page, round_index=round_index)
        if decision.status in TERMINAL or decision.status in stop_on:
            return _outcome(decision, page, history, round_index + 1)
        action_key = f"{decision.status.value}|{decision.target.index if decision.target else ''}|{page.fingerprint()}"
        seen[action_key] += 1
        if seen[action_key] >= REPEAT_LIMIT:
            stuck = JevDecision(JevStatus.UNSURE, "the same action keeps leaving the page unchanged")
            return _outcome(stuck, page, history, round_index + 1)
        history.append(decision.reason)
        if decision.status is JevStatus.CLICK and decision.target is not None:
            if not await driver.click_element(decision.target):
                history.append(f"click on '{decision.target.name}' failed")
        elif decision.status is JevStatus.FILL:
            await driver.fill_page()
        elif decision.status is JevStatus.SCROLL:
            await driver.scroll()
        elif decision.status is JevStatus.WAIT:
            waits += 1
            if waits > MAX_WAITS:
                return _outcome(JevDecision(JevStatus.UNSURE, "the page never finished loading"), page, history, round_index + 1)
            await sleep(WAIT_S)
    return JevOutcome(JevStatus.MAX_ROUNDS, "step limit reached", page, tuple(history), max_rounds)


def _outcome(decision: JevDecision, page: JevPage, history: list[str], calls: int) -> JevOutcome:
    return JevOutcome(decision.status, decision.reason, page, tuple(history), calls, decision.target)
