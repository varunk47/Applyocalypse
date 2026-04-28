from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Iterable
from typing import Any


@dataclass(frozen=True, slots=True)
class DocxAnchor:
    anchor_id: str
    section_label: str
    paragraph_index: int
    run_fingerprint: str
    confidence: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DocxMutationPlan:
    source_docx: Path
    anchors: list[DocxAnchor]
    warnings: list[str]


@dataclass(frozen=True, slots=True)
class DocxParagraphMutation:
    paragraph_index: int
    replacement_text: str


def iter_table_paragraphs(table: Any) -> Iterable[Any]:
    for row in table.rows:
        for cell in row.cells:
            yield from cell.paragraphs
            for nested_table in cell.tables:
                yield from iter_table_paragraphs(nested_table)


def iter_document_paragraphs(document: Any) -> list[Any]:
    paragraphs = list(document.paragraphs)
    for table in document.tables:
        paragraphs.extend(iter_table_paragraphs(table))
    return paragraphs


def replace_paragraph_text_preserving_runs(paragraph: Any, replacement_text: str) -> None:
    runs = list(paragraph.runs)
    if not runs:
        paragraph.add_run(replacement_text)
        return

    original_lengths = [max(len(run.text), 0) for run in runs]
    total_original_length = sum(original_lengths)
    if total_original_length == 0:
        runs[0].text = replacement_text
        for run in runs[1:]:
            run.text = ""
        return

    cursor = 0
    replacement_length = len(replacement_text)
    for index, run in enumerate(runs):
        if index == len(runs) - 1:
            run.text = replacement_text[cursor:]
            break

        share = original_lengths[index] / total_original_length
        next_cursor = min(replacement_length, cursor + round(replacement_length * share))
        run.text = replacement_text[cursor:next_cursor]
        cursor = next_cursor


def mutate_docx_paragraphs(source_docx: Path, output_docx: Path, mutations: list[DocxParagraphMutation]) -> Path:
    if source_docx.suffix.lower() != ".docx":
        raise ValueError("source_docx must be a DOCX file")
    if output_docx.suffix.lower() != ".docx":
        raise ValueError("output_docx must be a DOCX file")
    if not source_docx.exists():
        raise FileNotFoundError(source_docx)

    try:
        from docx import Document  # type: ignore
    except ImportError as exc:
        raise RuntimeError("python-docx is required for DOCX mutation") from exc

    document = Document(str(source_docx))
    paragraphs = list(document.paragraphs)
    for mutation in mutations:
        if mutation.paragraph_index < 0 or mutation.paragraph_index >= len(paragraphs):
            raise IndexError(f"paragraph index out of range: {mutation.paragraph_index}")
        replace_paragraph_text_preserving_runs(paragraphs[mutation.paragraph_index], mutation.replacement_text)

    output_docx.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(output_docx))
    return output_docx


def mutate_docx_placeholders(source_docx: Path, output_docx: Path, replacements: dict[str, str]) -> tuple[Path, list[str]]:
    if source_docx.suffix.lower() != ".docx":
        raise ValueError("source_docx must be a DOCX file")
    if output_docx.suffix.lower() != ".docx":
        raise ValueError("output_docx must be a DOCX file")
    if not source_docx.exists():
        raise FileNotFoundError(source_docx)

    try:
        from docx import Document  # type: ignore
    except ImportError as exc:
        raise RuntimeError("python-docx is required for DOCX mutation") from exc

    document = Document(str(source_docx))
    replaced: list[str] = []
    for paragraph in iter_document_paragraphs(document):
        paragraph_text = paragraph.text
        next_text = paragraph_text
        for placeholder, replacement in replacements.items():
            if placeholder in next_text:
                next_text = next_text.replace(placeholder, replacement)
                replaced.append(placeholder)
        if next_text != paragraph_text:
            replace_paragraph_text_preserving_runs(paragraph, next_text)

    output_docx.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(output_docx))
    return output_docx, sorted(set(replaced))


def inspect_docx_for_anchors(source_docx: Path) -> DocxMutationPlan:
    if source_docx.suffix.lower() != ".docx":
        raise ValueError("source_docx must be a DOCX file")
    if not source_docx.exists():
        raise FileNotFoundError(source_docx)

    try:
        from docx import Document  # type: ignore
    except ImportError as exc:
        raise RuntimeError("python-docx is required for DOCX inspection") from exc

    document = Document(str(source_docx))
    anchors: list[DocxAnchor] = []
    warnings: list[str] = []

    for index, paragraph in enumerate(iter_document_paragraphs(document)):
        text = paragraph.text.strip()
        if not text:
            continue
        style_name = paragraph.style.name if paragraph.style is not None else ""
        is_likely_heading = "heading" in style_name.lower()
        is_likely_bullet = paragraph._p.pPr is not None and paragraph._p.pPr.numPr is not None  # noqa: SLF001
        if is_likely_heading or is_likely_bullet:
            fingerprint = "|".join(run.text[:24] for run in paragraph.runs if run.text)
            anchors.append(
                DocxAnchor(
                    anchor_id=f"docx:p:{index}",
                    section_label=text[:80],
                    paragraph_index=index,
                    run_fingerprint=fingerprint,
                    confidence=0.72 if is_likely_bullet else 0.66,
                    metadata={"style": style_name, "bullet": is_likely_bullet},
                )
            )

    if not anchors:
        warnings.append("No high-confidence anchors found. User review is required before automated mutation.")

    return DocxMutationPlan(source_docx=source_docx, anchors=anchors, warnings=warnings)
