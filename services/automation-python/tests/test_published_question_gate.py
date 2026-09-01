"""What the posting required, checked against what the form actually showed.

A multi-step portal, a question behind a control discovery cannot see, a page the wizard
never reached: in every one of those the run reaches the submit gate looking complete. The
ATS publishes its own question set, so the gap is knowable before anyone approves, instead
of being discovered as silence weeks later.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path

from applyocalypse_automation import runner as runner_module
from applyocalypse_automation.browser.adapter import BrowserField
from applyocalypse_automation.browser.greenhouse_schema import GreenhouseQuestion
from applyocalypse_automation.control import WorkerControl
from applyocalypse_automation.runner import form_field_names, run_browser_apply_after_review

JOB_URL = "https://boards.greenhouse.io/northstar-labs/jobs/1"

WORK_AUTHORIZATION = GreenhouseQuestion(
    label="Are you legally authorized to work in the United States?",
    required=True,
    field_type="multi_value_single_select",
    field_names=("question_12345",),
    options=("Yes", "No"),
)
PUBLISHED = [
    GreenhouseQuestion(
        label="First Name",
        required=True,
        field_type="input_text",
        field_names=("first_name",),
        options=(),
    ),
    WORK_AUTHORIZATION,
    GreenhouseQuestion(
        label="LinkedIn Profile",
        required=False,
        field_type="input_text",
        field_names=("question_99",),
        options=(),
    ),
]


def named_field(field_id: str, label: str, name: str) -> BrowserField:
    return BrowserField(
        field_id=field_id,
        label=label,
        field_type="text",
        selector=f"#{name}",
        required=True,
        confidence=0.95,
        metadata={"name": name, "id": name},
    )


class FormAdapter:
    """A one-page form that shows the fields it is given and submits when told to."""

    name = "playwright"

    def __init__(self, fields: list[BrowserField]) -> None:
        self._fields = fields
        self.submitted = False

    async def launch(self, *, run_id, user_data_dir):
        return type("Result", (), {"ok": True, "payload": {}})()

    async def open_url(self, url):
        return type("Result", (), {"ok": True, "payload": {"url": url}})()

    async def detect_blockers(self):
        return []

    async def detect_fields(self):
        return list(self._fields)

    async def extract_visible_text(self):
        text = "Apply\n" + "\n".join(browser_field.label for browser_field in self._fields)
        return type(
            "Result",
            (),
            {"ok": True, "payload": {"text": text, "url": JOB_URL, "title": "Apply", "text_length": len(text)}},
        )()

    async def upload_file(self, browser_field, path):
        return type("Result", (), {"ok": True, "payload": {"action": "upload_file"}})()

    async def apply_field_value(self, browser_field, value):
        return type("Result", (), {"ok": True, "payload": {"action": "apply_field_value"}})()

    async def click_by_text(self, labels):
        return type("Result", (), {"ok": False, "message": "no matching safe portal action was found", "payload": {}})()

    async def click_final_submit(self, labels):
        self.submitted = True
        return type("Result", (), {"ok": True, "payload": {"clicked_label": labels[0]}})()

    async def screenshot(self, output_path):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake-png")
        return type("Result", (), {"ok": True, "payload": {"mime_type": "image/png", "width": 900, "height": 700}})()

    async def close(self):
        return type("Result", (), {"ok": True, "payload": {}})()


def approve_final_submit(work_dir: Path) -> threading.Thread:
    """Stands in for the human at the submit gate, which otherwise polls forever."""

    def write_approval() -> None:
        time.sleep(0.1)
        (work_dir / "control.json").write_text(
            json.dumps(
                {
                    "command": "RESUME",
                    "reason": "local_user_approved_final_submit",
                    "payload": {"approvalType": "FINAL_SUBMIT"},
                }
            ),
            encoding="utf-8",
        )

    thread = threading.Thread(target=write_approval)
    thread.start()
    return thread


def run_flow(
    *,
    tmp_path: Path,
    monkeypatch,
    fields: list[BrowserField],
    published: list[GreenhouseQuestion] | None,
    auto_submit: bool,
) -> FormAdapter:
    adapter = FormAdapter(fields)
    monkeypatch.setattr(runner_module, "create_browser_adapter", lambda adapter_name: adapter)
    monkeypatch.setattr(runner_module, "fetch_questions", lambda *_a, **_k: published)
    monkeypatch.delenv("APPLYO_WORKER_WAIT_FOR_REVIEW", raising=False)

    approval = approve_final_submit(tmp_path)
    asyncio.run(
        run_browser_apply_after_review(
            run_id="run-published-questions",
            job_url=JOB_URL,
            work_dir=tmp_path,
            adapter_name="playwright",
            control=WorkerControl(
                command="RESUME",
                reason="local_user_approved_document_review",
                step_id=None,
                written_at=None,
                payload={
                    "approvalType": "DOCUMENT_APPROVAL",
                    "autoSubmitEnabled": auto_submit,
                    "approvedAnswers": [
                        {"fieldLabel": browser_field.label, "selector": browser_field.selector, "value": "Ada"}
                        for browser_field in fields
                    ],
                    "generatedFiles": [],
                },
            ),
        )
    )
    approval.join(timeout=2)
    return adapter


def events_of(capsys, event_type: str) -> list[dict]:
    emitted = []
    for line in capsys.readouterr().out.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("eventType") == event_type or event.get("event_type") == event_type:
            emitted.append(event)
    return emitted


def test_a_required_question_that_never_appeared_is_named_before_the_gate(tmp_path, monkeypatch, capsys):
    run_flow(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        fields=[named_field("field-first", "First name", "first_name")],
        published=PUBLISHED,
        auto_submit=False,
    )

    reviews = events_of(capsys, "USER_REVIEW_REQUIRED")
    unseen = [
        event
        for event in reviews
        if (event.get("machineState") or event.get("machine_state") or {}).get("reason")
        == "PUBLISHED_REQUIRED_QUESTION_UNSEEN"
    ]
    assert len(unseen) == 1, f"the unseen required question was not reported: {reviews}"
    labels = [question["label"] for question in unseen[0]["payload"]["questions"]]
    assert labels == [WORK_AUTHORIZATION.label]


def test_a_form_that_showed_every_required_question_is_not_flagged(tmp_path, monkeypatch, capsys):
    """The optional question is absent too, and absence is only worth saying for a required
    one. Reporting every gap would train the user to click past the report."""
    run_flow(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        fields=[
            named_field("field-first", "First name", "first_name"),
            named_field("field-work-auth", "Work authorization", "question_12345"),
        ],
        published=PUBLISHED,
        auto_submit=False,
    )

    reasons = [
        (event.get("machineState") or event.get("machine_state") or {}).get("reason")
        for event in events_of(capsys, "USER_REVIEW_REQUIRED")
    ]
    assert "PUBLISHED_REQUIRED_QUESTION_UNSEEN" not in reasons


def test_preapproved_auto_submit_is_withdrawn_when_a_required_question_was_never_seen(
    tmp_path, monkeypatch, capsys
):
    """Withdrawing costs one click if the signal is wrong. Not withdrawing costs the whole
    application if it is right, and the user never finds out which."""
    adapter = run_flow(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        fields=[named_field("field-first", "First name", "first_name")],
        published=PUBLISHED,
        auto_submit=True,
    )

    ready = events_of(capsys, "READY_TO_SUBMIT")
    assert len(ready) == 1
    machine_state = ready[0].get("machineState") or ready[0].get("machine_state") or {}
    assert machine_state["auto_submit_enabled"] is False
    assert machine_state["auto_submit_withdrawn"] is True
    assert machine_state["unseen_required_question_count"] == 1
    assert ready[0]["payload"]["unseen_required_questions"] == [WORK_AUTHORIZATION.label]
    # It still submits, because the human at the gate approved it. The point is that they
    # were asked, holding the list of what the posting required and the form never showed.
    assert adapter.submitted is True


def test_a_posting_we_cannot_read_leaves_the_gate_exactly_as_it_was(tmp_path, monkeypatch, capsys):
    """Every non-Greenhouse portal takes this path, so it has to be the quiet one."""
    run_flow(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        fields=[named_field("field-first", "First name", "first_name")],
        published=None,
        auto_submit=True,
    )

    ready = events_of(capsys, "READY_TO_SUBMIT")
    assert len(ready) == 1
    machine_state = ready[0].get("machineState") or ready[0].get("machine_state") or {}
    assert machine_state["auto_submit_enabled"] is True
    assert machine_state["unseen_required_question_count"] == 0
    reasons = [
        (event.get("machineState") or event.get("machine_state") or {}).get("reason")
        for event in events_of(capsys, "USER_REVIEW_REQUIRED")
    ]
    assert "PUBLISHED_REQUIRED_QUESTION_UNSEEN" not in reasons


def test_form_field_names_reads_both_attributes():
    fields = [
        BrowserField("a", "First", "text", "#a", True, 0.9, {"name": "first_name", "id": "first_name"}),
        # Workday and several others carry the meaningful token on id alone.
        BrowserField("b", "Email", "text", "#b", True, 0.9, {"id": "email", "name": None}),
        BrowserField("c", "Blank", "text", "#c", True, 0.9, {"name": "   ", "id": ""}),
        BrowserField("d", "Bare", "text", "#d", True, 0.9, {}),
    ]

    assert form_field_names(fields) == {"first_name", "email"}
