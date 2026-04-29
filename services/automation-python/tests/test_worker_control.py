import asyncio
import json
import threading
import time

import pytest

from applyocalypse_automation import runner as runner_module
from applyocalypse_automation.browser.adapter import BrowserBlocker, BrowserField, BrowserStepResult
from applyocalypse_automation.control import WorkerControl, read_worker_control
from applyocalypse_automation.browser.field_detection import build_click_by_text_script, build_final_submit_script
from applyocalypse_automation.otp import GmailOtpResult
from applyocalypse_automation.runner import (
    approved_value_for_field,
    control_auto_submit_enabled,
    cover_letter_requirement_from_fields,
    field_file_count,
    handle_runtime_control,
    perform_final_submit_after_approval,
    perform_final_submit_with_control,
    pause_for_blockers,
    pause_for_portal_entry_action,
    portal_entry_requires_manual_action,
    required_document_missing_payload,
    wait_for_document_approval,
    wait_for_review_resume,
    run_browser_apply_after_review,
    select_generated_file_for_upload,
    submission_confirmation_detected,
)
from applyocalypse_automation.browser.portal_workflows import workflow_for_url


def test_read_worker_control_returns_none_without_file(tmp_path):
    assert read_worker_control(tmp_path) is None


def test_read_worker_control_parses_supported_command(tmp_path):
    (tmp_path / "control.json").write_text(
        json.dumps(
            {
                "command": "CANCEL",
                "reason": "local_user_cancel",
                "step_id": "step-1",
                "written_at": "2026-01-01T00:00:00Z",
                "payload": {"approved_answers": []},
            }
        ),
        encoding="utf-8",
    )

    control = read_worker_control(tmp_path)

    assert control is not None
    assert control.command == "CANCEL"
    assert control.step_id == "step-1"
    assert control.payload == {"approved_answers": []}
    assert not (tmp_path / "control.json").exists()


def test_read_worker_control_can_peek_without_consuming(tmp_path):
    (tmp_path / "control.json").write_text(json.dumps({"command": "RESUME", "reason": "local_user_resume"}), encoding="utf-8")

    control = read_worker_control(tmp_path, consume=False)

    assert control is not None
    assert control.command == "RESUME"
    assert (tmp_path / "control.json").exists()


def test_read_worker_control_accepts_safe_skip_command(tmp_path):
    (tmp_path / "control.json").write_text(
        json.dumps({"command": "SKIP_STEP", "reason": "local_user_skip", "step_id": "step-2"}),
        encoding="utf-8",
    )

    control = read_worker_control(tmp_path)

    assert control is not None
    assert control.command == "SKIP_STEP"
    assert control.step_id == "step-2"


def test_read_worker_control_rejects_unknown_command(tmp_path):
    (tmp_path / "control.json").write_text(json.dumps({"command": "DELETE_EVERYTHING"}), encoding="utf-8")

    with pytest.raises(ValueError):
        read_worker_control(tmp_path)


def test_wait_for_review_resume_reports_unsupported_control_commands(tmp_path, capsys):
    def write_controls() -> None:
        (tmp_path / "control.json").write_text(
            json.dumps({"command": "SKIP_STEP", "reason": "local_user_skip", "step_id": "step-2"}),
            encoding="utf-8",
        )
        time.sleep(0.05)
        (tmp_path / "control.json").write_text(
            json.dumps({"command": "RESUME", "reason": "local_user_resumed", "step_id": "step-2"}),
            encoding="utf-8",
        )

    writer = threading.Thread(target=write_controls)
    writer.start()
    control = wait_for_review_resume(
        tmp_path,
        poll_seconds=0.01,
        run_id="run-control",
        current_step="field_review",
        context="required answer review",
    )
    writer.join(timeout=2)

    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert control.command == "RESUME"
    assert events[0]["event_type"] == "USER_REVIEW_REQUIRED"
    assert events[0]["machine_state"]["reason"] == "RESUME_OR_CANCEL_REQUIRED"
    assert events[0]["payload"]["received_command"] == "SKIP_STEP"


def test_runtime_control_cancel_emits_failed_event(tmp_path, capsys):
    (tmp_path / "control.json").write_text(json.dumps({"command": "CANCEL", "reason": "local_user_cancel"}), encoding="utf-8")

    should_stop = handle_runtime_control(tmp_path, "run-control", context="field application")

    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert should_stop is True
    assert events[0]["event_type"] == "FAILED"
    assert events[0]["payload"]["code"] == "USER_CANCELLED"
    assert not (tmp_path / "control.json").exists()


def test_runtime_control_pause_waits_for_fresh_resume(tmp_path, capsys):
    (tmp_path / "control.json").write_text(json.dumps({"command": "PAUSE", "reason": "local_user_pause"}), encoding="utf-8")

    def write_resume() -> None:
        time.sleep(0.05)
        (tmp_path / "control.json").write_text(json.dumps({"command": "RESUME", "reason": "local_user_resume"}), encoding="utf-8")

    resume_thread = threading.Thread(target=write_resume)
    resume_thread.start()
    should_stop = handle_runtime_control(tmp_path, "run-control", context="page navigation")
    resume_thread.join(timeout=2)

    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert should_stop is False
    assert [event["event_type"] for event in events] == ["PAUSED", "RESUMED"]
    assert events[0]["machine_state"]["reason"] == "USER_PAUSE"
    assert not (tmp_path / "control.json").exists()


def test_pause_for_blockers_keeps_worker_alive_until_resume_clears_blocker(tmp_path, capsys):
    class FakeAdapter:
        async def detect_blockers(self):
            return []

    def write_resume() -> None:
        time.sleep(0.05)
        (tmp_path / "control.json").write_text(json.dumps({"command": "RESUME", "reason": "captcha_completed"}), encoding="utf-8")

    resume_thread = threading.Thread(target=write_resume)
    resume_thread.start()
    should_stop = asyncio.run(
        pause_for_blockers(
            FakeAdapter(),
            tmp_path,
            "run-blocked",
            [BrowserBlocker(blocker_type="CAPTCHA", message="CAPTCHA challenge detected", confidence=0.92)],
            context="page review",
        )
    )
    resume_thread.join(timeout=2)

    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert should_stop is False
    assert [event["event_type"] for event in events] == ["PAUSED", "RESUMED"]
    assert events[0]["machine_state"]["reason"] == "CAPTCHA_DETECTED"


def test_pause_for_blockers_cancel_stops_worker(tmp_path, capsys):
    class FakeAdapter:
        async def detect_blockers(self):
            return []

    def write_cancel() -> None:
        time.sleep(0.05)
        (tmp_path / "control.json").write_text(json.dumps({"command": "CANCEL", "reason": "local_user_cancel"}), encoding="utf-8")

    cancel_thread = threading.Thread(target=write_cancel)
    cancel_thread.start()
    should_stop = asyncio.run(
        pause_for_blockers(
            FakeAdapter(),
            tmp_path,
            "run-blocked",
            [BrowserBlocker(blocker_type="MFA", message="MFA challenge detected", confidence=0.82)],
            context="approved field application",
        )
    )
    cancel_thread.join(timeout=2)

    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert should_stop is True
    assert [event["event_type"] for event in events] == ["PAUSED", "FAILED"]


def test_pause_for_blockers_fills_gmail_otp_without_logging_code(tmp_path, capsys, monkeypatch):
    class FakeAdapter:
        def __init__(self):
            self.applied_values: list[str] = []

        async def detect_fields(self):
            return [
                BrowserField(
                    field_id="otp-1",
                    label="Verification code",
                    field_type="text",
                    selector="#otp",
                    required=True,
                    confidence=0.91,
                )
            ]

        async def apply_field_value(self, field, value):
            self.applied_values.append(value)
            return BrowserStepResult(True, "field value applied", {"action": "set_value", "field_id": field.field_id})

        async def detect_blockers(self):
            return []

    fake_adapter = FakeAdapter()
    monkeypatch.setenv("APPLYO_GMAIL_OTP_ENABLED", "1")
    monkeypatch.setattr(
        runner_module,
        "read_gmail_otp_from_env",
        lambda: GmailOtpResult(True, "493821", "Gmail OTP code extracted", metadata={"message_id_sha256": "hash"}),
    )

    should_stop = asyncio.run(
        pause_for_blockers(
            fake_adapter,
            tmp_path,
            "run-otp",
            [BrowserBlocker(blocker_type="OTP", message="One-time code required", confidence=0.92)],
            context="approved field application",
        )
    )

    output = capsys.readouterr().out
    events = [json.loads(line) for line in output.splitlines()]
    assert should_stop is False
    assert fake_adapter.applied_values == ["493821"]
    assert [event["event_type"] for event in events] == [
        "OTP_RETRIEVAL_STARTED",
        "OTP_RETRIEVAL_COMPLETED",
        "FIELD_VALUE_APPLIED",
    ]
    assert "493821" not in output


def test_portal_entry_pause_keeps_worker_alive_until_user_handles_action(tmp_path, capsys):
    class FakeAdapter:
        async def detect_blockers(self):
            return []

    workflow = workflow_for_url("https://jobs.lever.co/example/abc")

    def write_resume() -> None:
        time.sleep(0.05)
        (tmp_path / "control.json").write_text(json.dumps({"command": "RESUME", "reason": "portal_entry_clicked"}), encoding="utf-8")

    resume_thread = threading.Thread(target=write_resume)
    resume_thread.start()
    should_stop = asyncio.run(
        pause_for_portal_entry_action(
            FakeAdapter(),
            tmp_path,
            "run-portal-entry",
            workflow,
            context="observation",
        )
    )
    resume_thread.join(timeout=2)

    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert should_stop is False
    assert [event["event_type"] for event in events] == ["PAUSED", "RESUMED"]
    assert events[0]["machine_state"]["reason"] == "PORTAL_ENTRY_ACTION_REQUIRED"
    assert events[0]["payload"]["attempted_labels"] == ["Apply for this job", "Apply now"]


def test_portal_entry_manual_action_required_for_known_portal_click_miss() -> None:
    workflow = workflow_for_url("https://boards.greenhouse.io/example/jobs/123")

    assert portal_entry_requires_manual_action(workflow, action_applied=False) is True
    assert portal_entry_requires_manual_action(workflow, action_applied=True) is False


def test_final_submit_waits_for_explicit_approval_and_verifies_confirmation(tmp_path, capsys):
    class FakeAdapter:
        async def detect_blockers(self):
            return []

        async def click_final_submit(self, labels):
            assert "Submit application" in labels
            return type("Result", (), {"ok": True, "payload": {"clicked_label": "Submit application"}})()

        async def extract_visible_text(self):
            return type(
                "Result",
                (),
                {
                    "ok": True,
                    "payload": {
                        "text": "Thank you for applying. We have received your application.",
                        "url": "https://example.test/submitted",
                        "title": "Submitted",
                        "text_length": 64,
                    },
                },
            )()

    def write_final_approval() -> None:
        time.sleep(0.05)
        (tmp_path / "control.json").write_text(
            json.dumps({"command": "RESUME", "reason": "local_user_approved_final_submit", "payload": {"approvalType": "FINAL_SUBMIT"}}),
            encoding="utf-8",
        )

    approval_thread = threading.Thread(target=write_final_approval)
    approval_thread.start()
    submitted = asyncio.run(perform_final_submit_after_approval(FakeAdapter(), tmp_path, "run-submit"))
    approval_thread.join(timeout=2)

    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert submitted is True
    assert [event["event_type"] for event in events] == ["RESUMED", "SUBMITTED"]
    assert events[-1]["payload"]["submit_action"]["clicked_label"] == "Submit application"


def test_final_submit_does_not_claim_success_without_confirmation(tmp_path, capsys):
    class FakeAdapter:
        async def detect_blockers(self):
            return []

        async def click_final_submit(self, labels):
            return type("Result", (), {"ok": True, "payload": {"clicked_label": "Submit"}})()

        async def extract_visible_text(self):
            return type("Result", (), {"ok": True, "payload": {"text": "Review your application", "text_length": 23}})()

    (tmp_path / "control.json").write_text(
        json.dumps({"command": "RESUME", "reason": "local_user_approved_final_submit", "payload": {"approvalType": "FINAL_SUBMIT"}}),
        encoding="utf-8",
    )

    submitted = asyncio.run(perform_final_submit_after_approval(FakeAdapter(), tmp_path, "run-submit"))

    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert submitted is False
    assert [event["event_type"] for event in events] == ["RESUMED", "PAUSED"]
    assert events[-1]["machine_state"]["reason"] == "SUBMISSION_CONFIRMATION_UNVERIFIED"


def test_auto_submit_control_clicks_submit_but_still_requires_confirmation(tmp_path, capsys):
    class FakeAdapter:
        async def detect_blockers(self):
            return []

        async def click_final_submit(self, labels):
            return type("Result", (), {"ok": True, "payload": {"clicked_label": labels[0]}})()

        async def extract_visible_text(self):
            return type(
                "Result",
                (),
                {
                    "ok": True,
                    "payload": {
                        "text": "Application submitted. Thank you for applying.",
                        "url": "https://example.test/submitted",
                        "title": "Submitted",
                        "text_length": 49,
                    },
                },
            )()

    control = WorkerControl(
        command="RESUME",
        reason="local_user_preapproved_auto_submit",
        step_id=None,
        written_at=None,
        payload={"approvalType": "FINAL_SUBMIT", "autoSubmitEnabled": True},
    )

    submitted = asyncio.run(perform_final_submit_with_control(FakeAdapter(), tmp_path, "run-auto-submit", control))

    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert submitted is True
    assert control_auto_submit_enabled(control) is True
    assert [event["event_type"] for event in events] == ["SUBMITTED"]
    assert events[0]["payload"]["submit_action"]["clicked_label"] == "Submit"


def test_final_submit_helpers_are_strictly_separated_from_portal_entry_actions():
    portal_script = build_click_by_text_script(["Submit application"])
    final_script = build_final_submit_script(["Submit application"])

    assert "isFinalSubmitLike" in portal_script
    assert "final_submit" in final_script
    assert submission_confirmation_detected("Your application has been submitted successfully.") is True


def test_document_review_gate_ignores_answer_approval_until_documents_are_approved(tmp_path, capsys):
    (tmp_path / "control.json").write_text(
        json.dumps({"command": "RESUME", "reason": "local_user_approved_answer_edit", "payload": {"approvalType": "ANSWER_EDIT"}}),
        encoding="utf-8",
    )

    def write_controls() -> None:
        time.sleep(0.05)
        (tmp_path / "control.json").write_text(
            json.dumps({"command": "RESUME", "reason": "local_user_approved_document_approval", "payload": {"approvalType": "DOCUMENT_APPROVAL"}}),
            encoding="utf-8",
        )

    control_thread = threading.Thread(target=write_controls)
    control_thread.start()
    control = wait_for_document_approval(tmp_path, "run-doc-gate", poll_seconds=0.01)
    control_thread.join(timeout=2)

    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert control is not None
    assert control.payload["approvalType"] == "DOCUMENT_APPROVAL"
    assert [event["event_type"] for event in events] == ["USER_REVIEW_REQUIRED", "RESUMED"]
    assert events[0]["machine_state"]["reason"] == "DOCUMENT_APPROVAL_REQUIRED"


def test_required_upload_pause_refreshes_payload_and_retries(tmp_path, monkeypatch, capsys):
    cover_letter_path = tmp_path / "Ada Example Cover Letter.pdf"
    cover_letter_path.write_bytes(b"%PDF-1.7")

    class FakeAdapter:
        name = "playwright"

        def __init__(self):
            self.final_submit_clicked = False
            self.uploads = []

        async def launch(self, *, run_id, user_data_dir):
            return type("Result", (), {"ok": True, "payload": {"run_id": run_id, "user_data_dir": str(user_data_dir)}})()

        async def open_url(self, url):
            return type("Result", (), {"ok": True, "payload": {"url": url}})()

        async def detect_blockers(self):
            return []

        async def click_by_text(self, labels):
            return type("Result", (), {"ok": True, "payload": {"clicked_label": labels[0]}})()

        async def detect_fields(self):
            return [
                BrowserField(
                    field_id="field-cover-letter",
                    label="Cover Letter",
                    field_type="file",
                    selector="#cover-letter",
                    required=True,
                    confidence=0.94,
                    metadata={"accept": ".pdf", "file_count": 0},
                )
            ]

        async def extract_visible_text(self):
            text = "Thank you for applying. We have received your application." if self.final_submit_clicked else "Apply form cover letter"
            return type(
                "Result",
                (),
                {
                    "ok": True,
                    "payload": {"text": text, "url": "https://boards.greenhouse.io/northstar-labs/jobs/1", "title": "Apply", "text_length": len(text)},
                },
            )()

        async def upload_file(self, field, path):
            self.uploads.append((field.label, str(path)))
            return type("Result", (), {"ok": True, "payload": {"action": "upload_file"}})()

        async def click_final_submit(self, labels):
            self.final_submit_clicked = True
            return type("Result", (), {"ok": True, "payload": {"clicked_label": "Submit application"}})()

        async def screenshot(self, output_path):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"fake-png")
            return type("Result", (), {"ok": True, "payload": {"mime_type": "image/png", "width": 900, "height": 700}})()

        async def close(self):
            return type("Result", (), {"ok": True, "payload": {}})()

    fake_adapter = FakeAdapter()
    monkeypatch.setattr(runner_module, "create_browser_adapter", lambda adapter_name: fake_adapter)
    monkeypatch.setenv("APPLYO_WORKER_WAIT_FOR_REVIEW", "1")

    def write_document_approval() -> None:
        time.sleep(0.05)
        (tmp_path / "control.json").write_text(
            json.dumps(
                {
                    "command": "RESUME",
                    "reason": "local_user_approved_document_approval",
                    "payload": {
                        "approvalType": "DOCUMENT_APPROVAL",
                        "generatedFiles": [
                            {
                                "id": "cover-letter-upload",
                                "fileKind": "COVER_LETTER",
                                "format": "PDF",
                                "filename": cover_letter_path.name,
                                "localPath": str(cover_letter_path),
                                "uploadStatus": "NOT_UPLOADED",
                            }
                        ],
                    },
                }
            ),
            encoding="utf-8",
        )

    def write_final_approval() -> None:
        time.sleep(1.1)
        (tmp_path / "control.json").write_text(
            json.dumps({"command": "RESUME", "reason": "local_user_approved_final_submit", "payload": {"approvalType": "FINAL_SUBMIT"}}),
            encoding="utf-8",
        )

    threads = [threading.Thread(target=write_document_approval), threading.Thread(target=write_final_approval)]
    for thread in threads:
        thread.start()
    asyncio.run(
        run_browser_apply_after_review(
            run_id="run-upload-retry",
            job_url="https://boards.greenhouse.io/northstar-labs/jobs/1",
            work_dir=tmp_path,
            adapter_name="playwright",
            control=WorkerControl(
                command="RESUME",
                reason="local_user_approved_document_review",
                step_id=None,
                written_at=None,
                payload={"approvalType": "DOCUMENT_APPROVAL", "approvedAnswers": [], "generatedFiles": []},
            ),
        )
    )
    for thread in threads:
        thread.join(timeout=2)

    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    event_types = [event["event_type"] for event in events]
    assert "PAUSED" in event_types
    assert "RESUMED" in event_types
    assert "FILE_UPLOADED" in event_types
    assert event_types[-1] == "SUBMITTED"
    assert fake_adapter.uploads == [("Cover Letter", str(cover_letter_path))]
    assert submission_confirmation_detected("Review your application before sending.") is False


def test_required_answer_pause_refreshes_payload_before_filling(tmp_path, monkeypatch, capsys):
    class FakeAdapter:
        name = "playwright"

        def __init__(self):
            self.applied_values = []
            self.final_submit_clicked = False

        async def launch(self, *, run_id, user_data_dir):
            return type("Result", (), {"ok": True, "payload": {"run_id": run_id, "user_data_dir": str(user_data_dir)}})()

        async def open_url(self, url):
            return type("Result", (), {"ok": True, "payload": {"url": url}})()

        async def detect_blockers(self):
            return []

        async def click_by_text(self, labels):
            return type("Result", (), {"ok": True, "payload": {"clicked_label": labels[0]}})()

        async def detect_fields(self):
            return [
                BrowserField(
                    field_id="field-email",
                    label="Email address",
                    field_type="email",
                    selector="#email",
                    required=True,
                    confidence=0.95,
                )
            ]

        async def apply_field_value(self, field, value):
            self.applied_values.append((field.label, value))
            return type("Result", (), {"ok": True, "payload": {"action": "set_value"}})()

        async def extract_visible_text(self):
            text = "Application submitted. Thank you for applying." if self.final_submit_clicked else "Apply form"
            return type("Result", (), {"ok": True, "payload": {"text": text, "text_length": len(text)}})()

        async def click_final_submit(self, labels):
            self.final_submit_clicked = True
            return type("Result", (), {"ok": True, "payload": {"clicked_label": "Submit application"}})()

        async def screenshot(self, output_path):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"fake-png")
            return type("Result", (), {"ok": True, "payload": {"mime_type": "image/png", "width": 900, "height": 700}})()

        async def close(self):
            return type("Result", (), {"ok": True, "payload": {}})()

    fake_adapter = FakeAdapter()
    monkeypatch.setattr(runner_module, "create_browser_adapter", lambda adapter_name: fake_adapter)
    monkeypatch.setenv("APPLYO_WORKER_WAIT_FOR_REVIEW", "1")

    def write_controls() -> None:
        time.sleep(0.05)
        (tmp_path / "control.json").write_text(
            json.dumps(
                {
                    "command": "RESUME",
                    "reason": "local_user_approved_answer_edit",
                    "payload": {
                        "approvalType": "ANSWER_EDIT",
                        "approvedAnswers": [{"fieldLabel": "Email address", "fieldType": "email", "value": "ada@example.com"}],
                    },
                }
            ),
            encoding="utf-8",
        )
        time.sleep(1.1)
        (tmp_path / "control.json").write_text(
            json.dumps({"command": "RESUME", "reason": "local_user_approved_final_submit", "payload": {"approvalType": "FINAL_SUBMIT"}}),
            encoding="utf-8",
        )

    control_thread = threading.Thread(target=write_controls)
    control_thread.start()
    asyncio.run(
        run_browser_apply_after_review(
            run_id="run-answer-retry",
            job_url="https://boards.greenhouse.io/northstar-labs/jobs/1",
            work_dir=tmp_path,
            adapter_name="playwright",
            control=WorkerControl(
                command="RESUME",
                reason="local_user_approved_document_review",
                step_id=None,
                written_at=None,
                payload={"approvalType": "DOCUMENT_APPROVAL", "approvedAnswers": [], "generatedFiles": []},
            ),
        )
    )
    control_thread.join(timeout=2)

    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    event_types = [event["event_type"] for event in events]
    assert "PAUSED" in event_types
    assert "FIELD_VALUE_APPLIED" in event_types
    assert event_types[-1] == "SUBMITTED"
    assert fake_adapter.applied_values == [("Email address", "ada@example.com")]


def test_multi_page_progression_refills_next_page_before_final_submit(tmp_path, monkeypatch, capsys):
    class FakeAdapter:
        name = "playwright"

        def __init__(self):
            self.page_index = 1
            self.applied_values = []
            self.progression_clicks = []
            self.final_submit_clicked = False

        async def launch(self, *, run_id, user_data_dir):
            return type("Result", (), {"ok": True, "payload": {"run_id": run_id, "user_data_dir": str(user_data_dir)}})()

        async def open_url(self, url):
            return type("Result", (), {"ok": True, "payload": {"url": url}})()

        async def detect_blockers(self):
            return []

        async def click_by_text(self, labels):
            if "Apply for this job" in labels:
                return type("Result", (), {"ok": True, "payload": {"action": "click_by_text", "clicked_label": "Apply for this job"}})()
            if self.page_index == 1 and "Next" in labels:
                self.progression_clicks.append("Next")
                self.page_index = 2
                return type("Result", (), {"ok": True, "payload": {"action": "click_by_text", "clicked_label": "Next", "clicked_tag": "button"}})()
            return type(
                "Result",
                (),
                {"ok": False, "payload": {"action": "click_by_text", "message": "no matching safe portal action was found", "candidate_count": 0}},
            )()

        async def detect_fields(self):
            if self.page_index == 1:
                return [
                    BrowserField(
                        field_id="field-email",
                        label="Email address",
                        field_type="email",
                        selector="#email",
                        required=True,
                        confidence=0.95,
                    )
                ]
            return [
                BrowserField(
                    field_id="field-phone",
                    label="Phone number",
                    field_type="tel",
                    selector="#phone",
                    required=True,
                    confidence=0.95,
                )
            ]

        async def apply_field_value(self, field, value):
            self.applied_values.append((field.label, value, self.page_index))
            return type("Result", (), {"ok": True, "payload": {"action": "set_value"}})()

        async def extract_visible_text(self):
            text = "Application submitted. Thank you for applying." if self.final_submit_clicked else f"Apply form page {self.page_index}"
            return type(
                "Result",
                (),
                {
                    "ok": True,
                    "payload": {
                        "text": text,
                        "url": "https://boards.greenhouse.io/northstar-labs/jobs/1",
                        "title": "Apply",
                        "text_length": len(text),
                    },
                },
            )()

        async def click_final_submit(self, labels):
            self.final_submit_clicked = True
            return type("Result", (), {"ok": True, "payload": {"clicked_label": "Submit application"}})()

        async def screenshot(self, output_path):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"fake-png")
            return type("Result", (), {"ok": True, "payload": {"mime_type": "image/png", "width": 900, "height": 700}})()

        async def close(self):
            return type("Result", (), {"ok": True, "payload": {}})()

    fake_adapter = FakeAdapter()
    monkeypatch.setattr(runner_module, "create_browser_adapter", lambda adapter_name: fake_adapter)

    def write_final_approval() -> None:
        time.sleep(0.1)
        (tmp_path / "control.json").write_text(
            json.dumps({"command": "RESUME", "reason": "local_user_approved_final_submit", "payload": {"approvalType": "FINAL_SUBMIT"}}),
            encoding="utf-8",
        )

    approval_thread = threading.Thread(target=write_final_approval)
    approval_thread.start()
    asyncio.run(
        run_browser_apply_after_review(
            run_id="run-multi-page",
            job_url="https://boards.greenhouse.io/northstar-labs/jobs/1",
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
                        {"fieldLabel": "Email address", "fieldType": "email", "value": "ada@example.com"},
                        {"fieldLabel": "Phone number", "fieldType": "tel", "value": "555-0100"},
                    ],
                    "generatedFiles": [],
                },
            ),
        )
    )
    approval_thread.join(timeout=2)

    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    event_types = [event["event_type"] for event in events]
    progression_events = [
        event
        for event in events
        if event["event_type"] == "PORTAL_ACTION_APPLIED" and event["payload"].get("action_role") == "STEP_PROGRESSION"
    ]
    screenshot_ids = [event["payload"]["screenshot_id"] for event in events if event["event_type"] == "SCREENSHOT_CAPTURED"]

    assert fake_adapter.progression_clicks == ["Next"]
    assert fake_adapter.applied_values == [
        ("Email address", "ada@example.com", 1),
        ("Phone number", "555-0100", 2),
    ]
    assert len(progression_events) == 1
    assert progression_events[0]["payload"]["clicked_label"] == "Next"
    assert screenshot_ids == ["approved-application-reopened", "reviewed-fields-applied-1", "portal-step-1", "reviewed-fields-applied-2"]
    assert "READY_TO_SUBMIT" in event_types
    assert event_types[-1] == "SUBMITTED"


def test_approved_value_matches_detected_field_by_label():
    field = BrowserField(
        field_id="field-1",
        label="Email address",
        field_type="email",
        selector="#email",
        required=True,
        confidence=0.9,
    )

    assert (
        approved_value_for_field(
            field,
            [{"fieldLabel": "Email", "fieldType": "text", "value": "ada@example.com"}],
        )
        == "ada@example.com"
    )


def test_approved_value_matches_reviewed_choice_controls_by_label():
    field = BrowserField(
        field_id="field-work-auth",
        label="Are you authorized to work in the United States?",
        field_type="radio",
        selector='input[name="authorized"][value="yes"]',
        required=True,
        confidence=0.9,
        metadata={"value": "yes"},
    )

    assert (
        approved_value_for_field(
            field,
            [
                {
                    "fieldLabel": "Authorized to work in the United States",
                    "fieldType": "radio",
                    "value": "Yes",
                }
            ],
        )
        == "Yes"
    )


def test_select_generated_file_for_resume_upload_prefers_pdf(tmp_path):
    pdf_path = tmp_path / "Ada Example Resume.pdf"
    docx_path = tmp_path / "Ada Example Resume.docx"
    pdf_path.write_bytes(b"%PDF-1.7")
    docx_path.write_bytes(b"docx")
    field = BrowserField(
        field_id="field-resume",
        label="Upload resume",
        field_type="file",
        selector="#resume",
        required=True,
        confidence=0.92,
        metadata={"accept": ".pdf,.docx"},
    )

    selected = select_generated_file_for_upload(
        field,
        [
            {"id": "docx", "fileKind": "RESUME", "format": "DOCX", "localPath": str(docx_path), "uploadStatus": "NOT_UPLOADED"},
            {"id": "pdf", "fileKind": "RESUME", "format": "PDF", "localPath": str(pdf_path), "uploadStatus": "NOT_UPLOADED"},
        ],
    )

    assert selected is not None
    assert selected["id"] == "pdf"


def test_select_generated_file_for_upload_requires_clear_document_intent(tmp_path):
    pdf_path = tmp_path / "Ada Example Resume.pdf"
    pdf_path.write_bytes(b"%PDF-1.7")
    field = BrowserField(
        field_id="field-generic",
        label="Upload file",
        field_type="file",
        selector="#file",
        required=True,
        confidence=0.8,
        metadata={"accept": ".pdf"},
    )

    assert (
        select_generated_file_for_upload(
            field,
            [{"id": "pdf", "fileKind": "RESUME", "format": "PDF", "localPath": str(pdf_path), "uploadStatus": "NOT_UPLOADED"}],
        )
        is None
    )


def test_select_generated_file_for_upload_respects_accept_metadata(tmp_path):
    pdf_path = tmp_path / "Ada Example Resume.pdf"
    docx_path = tmp_path / "Ada Example Resume.docx"
    pdf_path.write_bytes(b"%PDF-1.7")
    docx_path.write_bytes(b"docx")
    field = BrowserField(
        field_id="field-resume",
        label="CV",
        field_type="file",
        selector="#cv",
        required=True,
        confidence=0.92,
        metadata={"accept": ".docx"},
    )

    selected = select_generated_file_for_upload(
        field,
        [
            {"id": "pdf", "fileKind": "RESUME", "format": "PDF", "localPath": str(pdf_path), "uploadStatus": "NOT_UPLOADED"},
            {"id": "docx", "fileKind": "RESUME", "format": "DOCX", "localPath": str(docx_path), "uploadStatus": "NOT_UPLOADED"},
        ],
    )

    assert selected is not None
    assert selected["id"] == "docx"


def test_cover_letter_requirement_detects_required_application_form_field():
    field = BrowserField(
        field_id="field-cover-letter",
        label="Cover Letter",
        field_type="file",
        selector="#cover-letter",
        required=True,
        confidence=0.94,
        metadata={"accept": ".pdf,.docx"},
    )

    requirement = cover_letter_requirement_from_fields([field])

    assert requirement is not None
    assert requirement["source"] == "APPLICATION_FORM"
    assert requirement["required"] is True
    assert requirement["field_count"] == 1
    assert requirement["fields"] == [
        {
            "field_label": "Cover Letter",
            "field_type": "file",
            "selector": "#cover-letter",
            "required": True,
            "confidence": 0.94,
        }
    ]


def test_cover_letter_requirement_detects_letter_of_interest_text_area():
    field = BrowserField(
        field_id="field-letter-interest",
        label="Letter of interest",
        field_type="textarea",
        selector="#letter-interest",
        required=False,
        confidence=0.86,
    )

    requirement = cover_letter_requirement_from_fields([field])

    assert requirement is not None
    assert requirement["required"] is False
    assert requirement["field_count"] == 1


def test_required_document_missing_payload_marks_cover_letter_kind():
    field = BrowserField(
        field_id="field-cover-letter",
        label="Upload cover letter",
        field_type="file",
        selector="#cover-letter",
        required=True,
        confidence=0.93,
        metadata={"accept": ".pdf"},
    )

    payload = required_document_missing_payload(field, generated_files=[])

    assert payload["file_kind"] == "COVER_LETTER"
    assert payload["accepted_formats"] == ["PDF"]
    assert payload["required"] is True


def test_field_file_count_reads_safe_metadata():
    field = BrowserField(
        field_id="field-cover-letter",
        label="Upload cover letter",
        field_type="file",
        selector="#cover-letter",
        required=True,
        confidence=0.93,
        metadata={"file_count": 1},
    )

    assert field_file_count(field) == 1


def test_required_document_missing_payload_includes_existing_file_count():
    field = BrowserField(
        field_id="field-cover-letter",
        label="Upload cover letter",
        field_type="file",
        selector="#cover-letter",
        required=True,
        confidence=0.93,
        metadata={"accept": ".pdf", "file_count": "2"},
    )

    payload = required_document_missing_payload(field, generated_files=[])

    assert payload["existing_file_count"] == 2
