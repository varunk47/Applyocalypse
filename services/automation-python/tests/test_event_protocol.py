from __future__ import annotations

import pytest

from applyocalypse_automation.event_protocol import EventType, Severity, WorkerEvent, parse_event_line


def test_worker_event_round_trips_json_line() -> None:
    event = WorkerEvent(
        event_type=EventType.RUN_STARTED,
        run_id="run_1",
        step_id=None,
        severity=Severity.INFO,
        message="started",
        machine_state={"phase": "boot"},
        ui_state={"current_step": "preparing"},
        payload={},
    )

    parsed = parse_event_line(event.to_json_line())

    assert parsed.event_type == EventType.RUN_STARTED
    assert parsed.run_id == "run_1"
    assert parsed.machine_state["phase"] == "boot"


def test_screenshot_event_rejects_base64_payload() -> None:
    event = WorkerEvent(
        event_type=EventType.SCREENSHOT_CAPTURED,
        run_id="run_1",
        step_id="step_1",
        severity=Severity.INFO,
        message="screenshot",
        payload={
            "screenshot_id": "shot_1",
            "local_path": "C:/tmp/shot.png",
            "mime_type": "image/png",
            "width": 100,
            "height": 100,
            "captured_at": "2026-04-25T00:00:00Z",
            "base64": "not allowed",
        },
    )

    with pytest.raises(ValueError, match="metadata only"):
        event.to_json_line()
