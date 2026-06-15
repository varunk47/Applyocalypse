from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class GeneratedNameInput:
    first_name: str
    last_name: str
    company: str
    role: str
    kind: str
    extension: str


def sanitize_filename_part(value: str) -> str:
    sanitized = WHITESPACE.sub(" ", INVALID_FILENAME_CHARS.sub(" ", value)).strip()
    return sanitized or "Untitled"


def build_generated_filename(input_value: GeneratedNameInput) -> str:
    stem = " ".join(
        sanitize_filename_part(part)
        for part in [
            input_value.first_name,
            input_value.last_name,
            input_value.company,
            input_value.role,
            input_value.kind,
        ]
    )
    extension = input_value.extension.strip(".").lower()
    return f"{stem}.{extension}"


def choose_collision_safe_path(directory: Path, filename: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / filename
    if not candidate.exists():
        return candidate

    suffix = 2
    stem = candidate.stem
    extension = candidate.suffix
    while True:
        next_candidate = directory / f"{stem} ({suffix}){extension}"
        if not next_candidate.exists():
            return next_candidate
        suffix += 1
