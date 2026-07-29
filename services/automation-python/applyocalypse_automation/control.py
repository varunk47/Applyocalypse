from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

WorkerCommand = Literal["PAUSE", "RESUME", "CANCEL", "RETRY_STEP", "SKIP_STEP"]


@dataclass(frozen=True, slots=True)
class WorkerControl:
    command: WorkerCommand
    reason: str | None
    step_id: str | None
    written_at: str | None
    payload: dict[str, Any]


def read_worker_control(work_dir: Path, *, consume: bool = True) -> WorkerControl | None:
    control_path = work_dir / "control.json"
    if not control_path.exists():
        return None

    try:
        raw = json.loads(control_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # Electron may still be mid-write; treat a torn or unreadable file as
        # "no command yet" and let the next poll pick up the settled file.
        return None
    command = raw.get("command")
    if command not in {"PAUSE", "RESUME", "CANCEL", "RETRY_STEP", "SKIP_STEP"}:
        raise ValueError(f"Unsupported worker control command: {command}")

    control = WorkerControl(
        command=command,
        reason=raw.get("reason") if raw.get("reason") is None or isinstance(raw.get("reason"), str) else str(raw.get("reason")),
        step_id=raw.get("step_id") if raw.get("step_id") is None or isinstance(raw.get("step_id"), str) else str(raw.get("step_id")),
        written_at=raw.get("written_at") if raw.get("written_at") is None or isinstance(raw.get("written_at"), str) else str(raw.get("written_at")),
        payload=raw.get("payload") if isinstance(raw.get("payload"), dict) else {},
    )
    if consume:
        control_path.unlink(missing_ok=True)
    return control
