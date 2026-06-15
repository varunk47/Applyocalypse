from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class TexRegion:
    region_id: str
    command_name: str
    source_preview: str
    confidence: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TexCompileResult:
    ok: bool
    pdf_path: Path | None
    stdout: str
    stderr: str


@dataclass(frozen=True, slots=True)
class TexBlockMutation:
    region_id: str
    replacement_source: str


def inspect_tex_regions(source_tex: Path) -> list[TexRegion]:
    if source_tex.suffix.lower() != ".tex":
        raise ValueError("source_tex must be a TEX file")
    text = source_tex.read_text(encoding="utf-8")

    try:
        from TexSoup import TexSoup  # type: ignore
    except ImportError:
        return inspect_tex_regions_fallback(text)

    try:
        soup = TexSoup(text)
        regions: list[TexRegion] = []
        for command_name in ("section", "subsection", "item"):
            for index, node in enumerate(soup.find_all(command_name)):
                preview = str(node)[:160]
                regions.append(
                    TexRegion(
                        region_id=f"tex:{command_name}:{index}",
                        command_name=command_name,
                        source_preview=preview,
                        confidence=0.75,
                        metadata={},
                    )
                )
        if regions:
            return regions
    except Exception:
        pass

    return inspect_tex_regions_fallback(text)


def inspect_tex_regions_fallback(text: str) -> list[TexRegion]:
    regions: list[TexRegion] = []
    patterns = [
        ("section", re.compile(r"\\section\*?\{([^}]*)\}")),
        ("subsection", re.compile(r"\\subsection\*?\{([^}]*)\}")),
        ("item", re.compile(r"\\item\s+([^\n]+)")),
    ]
    for command_name, pattern in patterns:
        for index, match in enumerate(pattern.finditer(text)):
            regions.append(
                TexRegion(
                    region_id=f"tex:{command_name}:{index}",
                    command_name=command_name,
                    source_preview=match.group(0)[:160],
                    confidence=0.58 if command_name == "item" else 0.64,
                    metadata={"fallback": True, "span": [match.start(), match.end()]},
                )
            )
    return regions


def mutate_tex_regions(source_tex: Path, output_tex: Path, mutations: list[TexBlockMutation]) -> Path:
    if source_tex.suffix.lower() != ".tex":
        raise ValueError("source_tex must be a TEX file")
    source = source_tex.read_text(encoding="utf-8")
    regions = inspect_tex_regions(source_tex)
    region_map = {region.region_id: region for region in regions}

    replacements: list[tuple[int, int, str]] = []
    for mutation in mutations:
        region = region_map.get(mutation.region_id)
        if region is None:
            raise KeyError(f"TEX region not found: {mutation.region_id}")
        span = region.metadata.get("span")
        if isinstance(span, list) and len(span) == 2:
            replacements.append((int(span[0]), int(span[1]), mutation.replacement_source))
            continue

        start = source.find(region.source_preview)
        if start == -1 or source.find(region.source_preview, start + 1) != -1:
            raise RuntimeError(f"TEX region lacks a unique deterministic source span: {mutation.region_id}")
        replacements.append((start, start + len(region.source_preview), mutation.replacement_source))

    for start, end, replacement in sorted(replacements, key=lambda item: item[0], reverse=True):
        source = f"{source[:start]}{replacement}{source[end:]}"

    output_tex.parent.mkdir(parents=True, exist_ok=True)
    output_tex.write_text(source, encoding="utf-8")
    return output_tex


def mutate_tex_placeholders(source_tex: Path, output_tex: Path, replacements: dict[str, str]) -> tuple[Path, list[str]]:
    if source_tex.suffix.lower() != ".tex":
        raise ValueError("source_tex must be a TEX file")
    source = source_tex.read_text(encoding="utf-8")
    replaced: list[str] = []
    for placeholder, replacement in replacements.items():
        if placeholder in source:
            source = source.replace(placeholder, replacement)
            replaced.append(placeholder)

    output_tex.parent.mkdir(parents=True, exist_ok=True)
    output_tex.write_text(source, encoding="utf-8")
    return output_tex, sorted(set(replaced))


def compile_tex_with_tectonic(source_tex: Path, output_dir: Path) -> TexCompileResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    command = ["tectonic", "--outdir", str(output_dir), str(source_tex)]
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
    except FileNotFoundError as exc:
        return TexCompileResult(
            ok=False,
            pdf_path=None,
            stdout="",
            stderr=f"Tectonic executable was not found: {exc}",
        )
    pdf_path = output_dir / f"{source_tex.stem}.pdf"
    return TexCompileResult(
        ok=completed.returncode == 0 and pdf_path.exists(),
        pdf_path=pdf_path if pdf_path.exists() else None,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
