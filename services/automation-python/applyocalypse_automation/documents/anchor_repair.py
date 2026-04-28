from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re
import shutil

from .docx_mutation import iter_document_paragraphs, replace_paragraph_text_preserving_runs


REQUIRED_PLACEHOLDERS = (
    "{{APPLYO_FULL_NAME}}",
    "{{APPLYO_RESUME_SUMMARY}}",
    "{{APPLYO_SKILLS}}",
)

SUMMARY_LABELS = {"summary", "profile", "professional summary"}
SKILLS_LABELS = {"skills", "technical skills", "technologies", "tools", "core skills"}


@dataclass(frozen=True, slots=True)
class AnchorRepairResult:
    source_path: str
    output_path: str
    source_format: str
    added_placeholders: list[str]
    already_present_placeholders: list[str]
    warnings: list[str]

    def to_payload(self) -> dict[str, object]:
        return asdict(self)


def normalize_label(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9 &/+-]", "", value.strip().strip(":").lower())
    return re.sub(r"\s+", " ", cleaned)


def detect_placeholders(text: str) -> list[str]:
    return [placeholder for placeholder in REQUIRED_PLACEHOLDERS if placeholder in text]


def is_likely_contact_line(value: str) -> bool:
    lowered = value.lower()
    return "@" in value or "http" in lowered or "linkedin" in lowered or bool(re.search(r"\+?\d[\d\s().-]{7,}\d", value))


def first_candidate_name_paragraph(paragraphs: list[object]) -> object | None:
    for paragraph in paragraphs[:8]:
        text = str(getattr(paragraph, "text", "")).strip()
        if not text or is_likely_contact_line(text):
            continue
        if 2 <= len(text.split()) <= 6 and len(text) <= 90:
            return paragraph
    return None


def next_non_empty_paragraph(paragraphs: list[object], start_index: int) -> object | None:
    for paragraph in paragraphs[start_index + 1 :]:
        text = str(getattr(paragraph, "text", "")).strip()
        if text:
            return paragraph
    return None


def find_body_after_section(paragraphs: list[object], labels: set[str]) -> object | None:
    for index, paragraph in enumerate(paragraphs):
        if normalize_label(str(getattr(paragraph, "text", ""))) in labels:
            return next_non_empty_paragraph(paragraphs, index)
    return None


def repair_docx_anchors(source: Path, output: Path) -> AnchorRepairResult:
    try:
        from docx import Document  # type: ignore
    except ImportError as exc:
        raise RuntimeError("python-docx is required for DOCX anchor repair") from exc

    document = Document(str(source))
    paragraphs = iter_document_paragraphs(document)
    full_text = "\n".join(paragraph.text for paragraph in paragraphs)
    already_present = detect_placeholders(full_text)
    added: list[str] = []
    warnings: list[str] = []

    if "{{APPLYO_FULL_NAME}}" not in already_present:
        paragraph = first_candidate_name_paragraph(paragraphs)
        if paragraph is None:
            warnings.append("Could not identify a high-confidence legal-name paragraph.")
        else:
            replace_paragraph_text_preserving_runs(paragraph, "{{APPLYO_FULL_NAME}}")
            added.append("{{APPLYO_FULL_NAME}}")

    if "{{APPLYO_RESUME_SUMMARY}}" not in already_present:
        paragraph = find_body_after_section(paragraphs, SUMMARY_LABELS)
        if paragraph is None:
            warnings.append("No summary/profile section body found for {{APPLYO_RESUME_SUMMARY}}.")
        else:
            replace_paragraph_text_preserving_runs(paragraph, "{{APPLYO_RESUME_SUMMARY}}")
            added.append("{{APPLYO_RESUME_SUMMARY}}")

    if "{{APPLYO_SKILLS}}" not in already_present:
        paragraph = find_body_after_section(paragraphs, SKILLS_LABELS)
        if paragraph is None:
            warnings.append("No skills section body found for {{APPLYO_SKILLS}}.")
        else:
            replace_paragraph_text_preserving_runs(paragraph, "{{APPLYO_SKILLS}}")
            added.append("{{APPLYO_SKILLS}}")

    output.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(output))
    return AnchorRepairResult(
        source_path=str(source),
        output_path=str(output),
        source_format="DOCX",
        added_placeholders=added,
        already_present_placeholders=already_present,
        warnings=warnings,
    )


def replace_tex_section_body(source: str, labels: set[str], placeholder: str) -> tuple[str, bool]:
    section_pattern = re.compile(r"(\\section\*?\{([^}]*)\})(.*?)(?=\\section\*?\{|\\end\{document\}|\Z)", re.DOTALL)
    for match in section_pattern.finditer(source):
        label = normalize_label(match.group(2))
        if label not in labels:
            continue
        replacement = f"{match.group(1)}\n{placeholder}\n"
        return f"{source[:match.start()]}{replacement}{source[match.end():]}", True
    return source, False


def repair_tex_anchors(source: Path, output: Path) -> AnchorRepairResult:
    text = source.read_text(encoding="utf-8")
    already_present = detect_placeholders(text)
    added: list[str] = []
    warnings: list[str] = []
    repaired = text

    if "{{APPLYO_FULL_NAME}}" not in already_present:
        warnings.append("TEX name/title macros are not auto-repaired because bare placeholders inside command braces can corrupt LaTeX syntax.")

    if "{{APPLYO_RESUME_SUMMARY}}" not in already_present:
        repaired, replaced = replace_tex_section_body(repaired, SUMMARY_LABELS, "{{APPLYO_RESUME_SUMMARY}}")
        if replaced:
            added.append("{{APPLYO_RESUME_SUMMARY}}")
        else:
            warnings.append("No summary/profile section body found for {{APPLYO_RESUME_SUMMARY}}.")

    if "{{APPLYO_SKILLS}}" not in already_present:
        repaired, replaced = replace_tex_section_body(repaired, SKILLS_LABELS, "{{APPLYO_SKILLS}}")
        if replaced:
            added.append("{{APPLYO_SKILLS}}")
        else:
            warnings.append("No skills section body found for {{APPLYO_SKILLS}}.")

    if not added and not already_present:
        insertion = "\n\\section*{Applyocalypse Review Anchors}\n{{APPLYO_RESUME_SUMMARY}}\n{{APPLYO_SKILLS}}\n"
        if "\\end{document}" in repaired:
            repaired = repaired.replace("\\end{document}", f"{insertion}\\end{{document}}", 1)
            added.extend(["{{APPLYO_RESUME_SUMMARY}}", "{{APPLYO_SKILLS}}"])
            warnings.append("Inserted a review-only anchor section. Move these placeholders into the intended layout before confirmation.")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(repaired, encoding="utf-8")
    return AnchorRepairResult(
        source_path=str(source),
        output_path=str(output),
        source_format="TEX",
        added_placeholders=added,
        already_present_placeholders=already_present,
        warnings=warnings,
    )


def repair_editable_master_anchors(source: Path, output: Path) -> AnchorRepairResult:
    suffix = source.suffix.lower()
    if suffix == ".docx":
        return repair_docx_anchors(source, output)
    if suffix == ".tex":
        return repair_tex_anchors(source, output)
    if suffix in {".txt", ".md"}:
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, output)
        return AnchorRepairResult(
            source_path=str(source),
            output_path=str(output),
            source_format=suffix[1:].upper(),
            added_placeholders=[],
            already_present_placeholders=[],
            warnings=["Anchor repair is only available for DOCX and TEX editable masters."],
        )
    raise ValueError("Anchor repair is only available for DOCX and TEX editable masters.")
