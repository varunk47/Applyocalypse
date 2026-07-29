"""Uploads land before anything is typed, and the form is re-read in between.

Workday and iCIMS parse the resume server-side and repopulate name, email and
experience seconds after the upload request returns. Writing text in the same
pass means the portal's parse wins and the user's reviewed answers vanish.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path

from applyocalypse_automation import runner as runner_module
from applyocalypse_automation.browser.adapter import BrowserField
from applyocalypse_automation.control import WorkerControl
from applyocalypse_automation.runner import run_browser_apply_after_review

JOB_URL = "https://boards.greenhouse.io/northstar-labs/jobs/1"


def field(field_id: str, label: str, field_type: str, selector: str, *, file_count: int = 0) -> BrowserField:
    return BrowserField(
        field_id=field_id,
        label=label,
        field_type=field_type,
        selector=selector,
        required=True,
        confidence=0.95,
        metadata={"file_count": file_count} if field_type == "file" else {},
    )


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


class RecordingAdapter:
    """Records the order of uploads, typed writes, and form reads."""

    name = "playwright"

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.uploaded = False

    async def launch(self, *, run_id, user_data_dir):
        return type("Result", (), {"ok": True, "payload": {}})()

    async def open_url(self, url):
        return type("Result", (), {"ok": True, "payload": {"url": url}})()

    async def detect_blockers(self):
        return []

    async def detect_fields(self):
        self.calls.append("detect_fields")
        return [
            # A portal that already holds the file reports it, and the runner
            # skips a second upload on the pass that follows the parse.
            field("field-resume", "Resume", "file", "#resume", file_count=1 if self.uploaded else 0),
            field("field-first", "First name", "text", "#first-name"),
            field("field-email", "Email", "email", "#email"),
        ]

    async def extract_visible_text(self):
        # The URL moves once the upload lands, which is what the settle wait
        # watches for. Without it the wait would burn its full timeout.
        url = f"{JOB_URL}?parsed=1" if self.uploaded else JOB_URL
        text = "Resume\nFirst name\nEmail"
        return type(
            "Result",
            (),
            {"ok": True, "payload": {"text": text, "url": url, "title": "Apply", "text_length": len(text)}},
        )()

    async def upload_file(self, browser_field, path):
        self.calls.append(f"upload:{browser_field.label}")
        self.uploaded = True
        return type("Result", (), {"ok": True, "payload": {"action": "upload_file"}})()

    async def apply_field_value(self, browser_field, value):
        self.calls.append(f"value:{browser_field.label}")
        return type("Result", (), {"ok": True, "payload": {"action": "apply_field_value"}})()

    async def click_by_text(self, labels):
        return type("Result", (), {"ok": False, "message": "no matching safe portal action was found", "payload": {}})()

    async def click_final_submit(self, labels):
        return type("Result", (), {"ok": True, "payload": {"clicked_label": labels[0]}})()

    async def screenshot(self, output_path):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake-png")
        return type("Result", (), {"ok": True, "payload": {"mime_type": "image/png", "width": 900, "height": 700}})()

    async def close(self):
        return type("Result", (), {"ok": True, "payload": {}})()


def test_uploads_precede_typed_values_and_the_form_is_re_read_between(tmp_path, monkeypatch, capsys) -> None:
    resume_path = tmp_path / "Ada Example Resume.pdf"
    resume_path.write_bytes(b"%PDF-1.7")

    adapter = RecordingAdapter()
    monkeypatch.setattr(runner_module, "create_browser_adapter", lambda adapter_name: adapter)
    monkeypatch.setattr(runner_module, "RESUME_PARSE_SETTLE_S", 1.0)
    monkeypatch.delenv("APPLYO_WORKER_WAIT_FOR_REVIEW", raising=False)

    approval = approve_final_submit(tmp_path)
    asyncio.run(
        run_browser_apply_after_review(
            run_id="run-upload-order",
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
                    "approvedAnswers": [
                        {"fieldLabel": "First name", "selector": "#first-name", "value": "Ada"},
                        {"fieldLabel": "Email", "selector": "#email", "value": "ada@example.com"},
                    ],
                    "generatedFiles": [
                        {
                            "id": "resume-upload",
                            "fileKind": "RESUME",
                            "format": "PDF",
                            "filename": resume_path.name,
                            "localPath": str(resume_path),
                            "uploadStatus": "NOT_UPLOADED",
                        }
                    ],
                },
            ),
        )
    )
    approval.join(timeout=2)
    capsys.readouterr()

    uploads =[index for index, call in enumerate(adapter.calls) if call.startswith("upload:")]
    values = [index for index, call in enumerate(adapter.calls) if call.startswith("value:")]
    reads = [index for index, call in enumerate(adapter.calls) if call == "detect_fields"]

    assert uploads, f"no upload was attempted: {adapter.calls}"
    assert values, f"no value was written: {adapter.calls}"
    # Workday appends attachments rather than replacing them, so a second pass over the
    # same field must not send the resume again.
    assert len(uploads) == 1, f"the resume was attached more than once: {adapter.calls}"
    assert max(uploads) < min(values), f"typed a value before the last upload: {adapter.calls}"
    assert any(max(uploads) < read < min(values) for read in reads), (
        f"the form was not re-read between the upload and the first typed value: {adapter.calls}"
    )


def test_a_form_without_uploads_still_writes_its_values(tmp_path, monkeypatch, capsys) -> None:
    class TextOnlyAdapter(RecordingAdapter):
        async def detect_fields(self):
            self.calls.append("detect_fields")
            return [field("field-first", "First name", "text", "#first-name")]

    adapter = TextOnlyAdapter()
    monkeypatch.setattr(runner_module, "create_browser_adapter", lambda adapter_name: adapter)
    monkeypatch.delenv("APPLYO_WORKER_WAIT_FOR_REVIEW", raising=False)

    approval = approve_final_submit(tmp_path)
    asyncio.run(
        run_browser_apply_after_review(
            run_id="run-text-only",
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
                    "approvedAnswers": [{"fieldLabel": "First name", "selector": "#first-name", "value": "Ada"}],
                    "generatedFiles": [],
                },
            ),
        )
    )
    approval.join(timeout=2)
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]

    assert "value:First name" in adapter.calls
    assert "FIELD_VALUE_APPLIED" in [event["event_type"] for event in events]
