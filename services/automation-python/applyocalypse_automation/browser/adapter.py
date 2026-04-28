from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def read_png_dimensions(path: Path) -> tuple[int, int] | None:
    with path.open("rb") as file:
        header = file.read(24)
    if len(header) < 24 or not header.startswith(PNG_SIGNATURE) or header[12:16] != b"IHDR":
        return None
    width = int.from_bytes(header[16:20], "big")
    height = int.from_bytes(header[20:24], "big")
    if width <= 0 or height <= 0:
        return None
    return width, height


def screenshot_payload(path: Path, *, default_width: int = 1280, default_height: int = 800) -> dict[str, Any]:
    dimensions = read_png_dimensions(path)
    width, height = dimensions if dimensions is not None else (default_width, default_height)
    return {"local_path": str(path), "mime_type": "image/png", "width": width, "height": height}


@dataclass(frozen=True, slots=True)
class BrowserField:
    field_id: str
    label: str
    field_type: str
    selector: str | None
    required: bool
    confidence: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BrowserBlocker:
    blocker_type: str
    message: str
    confidence: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BrowserStepResult:
    ok: bool
    message: str
    payload: dict[str, Any] = field(default_factory=dict)


class BrowserAdapter(Protocol):
    name: str

    async def launch(self, *, run_id: str, user_data_dir: Path) -> BrowserStepResult:
        ...

    async def open_url(self, url: str) -> BrowserStepResult:
        ...

    async def detect_fields(self) -> list[BrowserField]:
        ...

    async def detect_blockers(self) -> list[BrowserBlocker]:
        ...

    async def capture_dom_snapshot(self, output_path: Path) -> BrowserStepResult:
        ...

    async def extract_visible_text(self) -> BrowserStepResult:
        ...

    async def fill_field(self, field: BrowserField, value: str) -> BrowserStepResult:
        ...

    async def apply_field_value(self, field: BrowserField, value: str) -> BrowserStepResult:
        ...

    async def click_by_text(self, labels: list[str]) -> BrowserStepResult:
        ...

    async def click_final_submit(self, labels: list[str]) -> BrowserStepResult:
        ...

    async def upload_file(self, field: BrowserField, path: Path) -> BrowserStepResult:
        ...

    async def screenshot(self, output_path: Path) -> BrowserStepResult:
        ...

    async def pause(self, reason: str) -> BrowserStepResult:
        ...

    async def close(self) -> BrowserStepResult:
        ...
