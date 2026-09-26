"""Jev's side of an application run: the adapter driver, the goal, and what Jev may see.

Jev chooses the clicks that move an application along (Apply, Apply Manually,
Next, Save and Continue); the runner's own field loop still types every value.
So the loop stops at every page with fields, hands it to the runner, and is
started again when the runner has filled it.
"""
from __future__ import annotations

import os
from typing import Any

from .browser.jev_client import ask_jev, jev_configured
from .browser.jev_page import JevElement, JevPage
from .browser.jev_step import Ask
from .event_protocol import EventType, Severity, WorkerEvent

JEV_GOAL = (
    "Reach the final review page of this job application, the page whose only way forward is "
    "submitting it. Open the application, get past account pages, and move through each page "
    "of the form with its Next or Continue button. Never submit the application."
)

# Short answers that are not the user's own details, and would cut the page's
# own words ("Yes", "No") out of what Jev reads if they were redacted.
_GENERIC_ANSWERS = frozenset({"yes", "no", "true", "false", "none", "n/a", "other"})

# Tell the user the model is queueing on the first busy reply, then once a minute.
_BUSY_REPORT_EVERY = 6


def jev_ready(adapter: object) -> bool:
    """Jev drives the run when its key is set and the browser adapter can serve it."""
    return jev_configured() and hasattr(adapter, "jev_read_page")


def personal_values(approved_answers: object) -> list[str]:
    """The user's own details, cut out of every page before Jev reads it."""
    values = [os.getenv("APPLYO_APPLICATION_EMAIL", "")]
    if isinstance(approved_answers, list):
        values += [str(a.get("value") or "") for a in approved_answers if isinstance(a, dict)]
    return [v.strip() for v in values if v.strip() and v.strip().lower() not in _GENERIC_ANSWERS]


def jev_ask(run_id: str) -> Ask:
    def report_busy(attempt: int) -> None:
        if attempt % _BUSY_REPORT_EVERY != 1:
            return
        WorkerEvent(
            event_type=EventType.PORTAL_STATE_OBSERVED,
            run_id=run_id,
            step_id=None,
            severity=Severity.INFO,
            message="Waiting on Jev: the model is busy right now, retrying",
            machine_state={"reason": "JEV_BUSY", "attempt": attempt},
            ui_state={"current_step": "portal_workflow"},
            payload={"attempt": attempt},
        ).emit()

    async def ask(state: str, questions: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        return (await ask_jev(state, questions, on_busy=report_busy)).answers

    return ask


class AdapterJevDriver:
    """Runs Jev's chosen actions on the run's browser adapter."""

    def __init__(self, adapter: Any, run_id: str, *, context: str) -> None:
        self.adapter = adapter
        self.run_id = run_id
        self.context = context
        self.clicks = 0

    async def read_page(self) -> JevPage:
        return await self.adapter.jev_read_page()

    async def click_element(self, element: JevElement) -> bool:
        result = await self.adapter.jev_click(element)
        if result.ok:
            self.clicks += 1
        WorkerEvent(
            event_type=EventType.PORTAL_ACTION_APPLIED,
            run_id=self.run_id,
            step_id=None,
            severity=Severity.INFO if result.ok else Severity.WARN,
            message=f"Jev clicked '{element.name}'" if result.ok else f"Jev's click on '{element.name}' failed",
            machine_state={"action_role": "JEV_CLICK", "context": self.context, "ok": result.ok},
            ui_state={"current_step": "portal_workflow"},
            payload={"action_role": "JEV_CLICK", "context": self.context, "clicked_label": element.name, **result.payload},
        ).emit()
        return result.ok

    async def fill_page(self) -> bool:
        # Never reached: the runner stops the loop at FILL and fills the page itself.
        return False

    async def scroll(self) -> None:
        await self.adapter.jev_scroll()
