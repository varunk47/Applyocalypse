from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import re
from typing import Literal


BANNED_WORDS = [
    "leverage",
    "utilize",
    "spearheaded",
    "robust",
    "comprehensive",
    "seamless",
    "transformative",
    "passionate",
    "excited",
    "thrilled",
    "dynamic",
    "innovative",
    "holistic",
    "empower",
    "foster",
    "harness",
    "deep dive",
]

WEAK_BULLET_PATTERNS = [
    r"\bresponsible for\b",
    r"\bworked on\b",
    r"\bhelped with\b",
    r"\bparticipated in\b",
    r"\bvarious\b",
]


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    message: str
    severity: str


@dataclass(frozen=True, slots=True)
class ValidationReport:
    passed: bool
    blocking_issues: list[ValidationIssue]
    warnings: list[ValidationIssue]

    def human_report(self) -> str:
        lines = ["Validation passed." if self.passed else "Validation failed."]
        if self.blocking_issues:
            lines.append("Blocking issues:")
            lines.extend(f"- {issue.code}: {issue.message}" for issue in self.blocking_issues)
        if self.warnings:
            lines.append("Warnings:")
            lines.extend(f"- {issue.code}: {issue.message}" for issue in self.warnings)
        return "\n".join(lines)

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "blocking_issues": [asdict(issue) for issue in self.blocking_issues],
            "warnings": [asdict(issue) for issue in self.warnings],
            "human_report": self.human_report(),
        }


ArtifactKind = Literal["resume", "cover_letter", "generic"]


@dataclass(frozen=True, slots=True)
class ArtifactTextExtraction:
    text: str
    source_format: str
    warnings: list[str]


def extract_docx_text(path: Path) -> ArtifactTextExtraction:
    try:
        from docx import Document  # type: ignore
    except ImportError as exc:
        raise RuntimeError("python-docx is required for DOCX validation") from exc

    document = Document(str(path))
    lines: list[str] = []
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if text:
            lines.append(text)

    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                cell_text = " ".join(paragraph.text.strip() for paragraph in cell.paragraphs if paragraph.text.strip())
                if cell_text:
                    lines.append(cell_text)

    return ArtifactTextExtraction(text="\n".join(lines), source_format="DOCX", warnings=[])


def extract_tex_text(path: Path) -> ArtifactTextExtraction:
    source = path.read_text(encoding="utf-8")
    warnings: list[str] = []

    try:
        from TexSoup import TexSoup  # type: ignore
    except ImportError:
        warnings.append("TexSoup unavailable; used constrained TEX text fallback.")
        return ArtifactTextExtraction(text=extract_tex_text_fallback(source), source_format="TEX", warnings=warnings)

    try:
        soup = TexSoup(source)
        text = str(soup.text)
        if text.strip():
            return ArtifactTextExtraction(text=normalize_extracted_text(text), source_format="TEX", warnings=warnings)
    except Exception as exc:
        warnings.append(f"TexSoup parsing failed; used constrained fallback: {type(exc).__name__}.")

    return ArtifactTextExtraction(text=extract_tex_text_fallback(source), source_format="TEX", warnings=warnings)


def extract_tex_text_fallback(source: str) -> str:
    without_comments = re.sub(r"(?<!\\)%.*", "", source)
    without_environments = re.sub(r"\\(begin|end)\s*\{[^}]+\}", "\n", without_comments)
    with_item_markers = re.sub(r"\\item\b", "\n- ", without_environments)
    without_commands_with_args = re.sub(r"\\[a-zA-Z*]+\s*(?:\[[^\]]*])?\s*\{([^{}]*)\}", r"\1", with_item_markers)
    without_commands = re.sub(r"\\[a-zA-Z*]+(?:\s*\[[^\]]*])?", " ", without_commands_with_args)
    unescaped = (
        without_commands.replace(r"\&", "&")
        .replace(r"\%", "%")
        .replace(r"\_", "_")
        .replace(r"\#", "#")
        .replace(r"\$", "$")
    )
    return normalize_extracted_text(unescaped)


def extract_pdf_text(path: Path) -> ArtifactTextExtraction:
    try:
        import fitz  # type: ignore
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required for rendered PDF validation") from exc

    lines: list[str] = []
    with fitz.open(path) as document:
        for page in document:
            text = page.get_text("text").strip()
            if text:
                lines.append(text)

    return ArtifactTextExtraction(text="\n".join(lines), source_format="PDF", warnings=[])


def normalize_extracted_text(text: str) -> str:
    normalized_lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in normalized_lines if line)


def extract_artifact_text(path: Path) -> ArtifactTextExtraction:
    if not path.exists():
        raise FileNotFoundError(path)

    suffix = path.suffix.lower()
    if suffix in {".txt", ".md"}:
        return ArtifactTextExtraction(text=path.read_text(encoding="utf-8"), source_format=suffix[1:].upper(), warnings=[])
    if suffix == ".docx":
        return extract_docx_text(path)
    if suffix == ".tex":
        return extract_tex_text(path)
    if suffix == ".pdf":
        return extract_pdf_text(path)
    raise ValueError(f"Unsupported validation artifact format: {suffix or '<none>'}")


class TextArtifactValidator:
    def validate(self, text: str, *, artifact_kind: ArtifactKind) -> ValidationReport:
        blocking: list[ValidationIssue] = []
        warnings: list[ValidationIssue] = []
        lower = text.lower()

        for word in BANNED_WORDS:
            pattern = r"\b" + re.escape(word).replace(r"\ ", r"\s+") + r"\b"
            if re.search(pattern, lower):
                blocking.append(ValidationIssue("BANNED_WORD", f"Banned wording found: {word}", "blocking"))

        em_dash_count = text.count("\u2014")
        if em_dash_count:
            blocking.append(ValidationIssue("EM_DASH", f"Em dash count must be 0. Found {em_dash_count}.", "blocking"))

        if artifact_kind == "cover_letter":
            word_count = len([token for token in re.split(r"\s+", text.strip()) if token])
            if word_count > 450:
                blocking.append(ValidationIssue("COVER_LETTER_TOO_LONG", f"Cover letter has {word_count} words.", "blocking"))
            if re.match(r"^\s*(i am applying for|i'?m writing to apply|i am writing to apply)\b", text, flags=re.IGNORECASE):
                warnings.append(ValidationIssue("GENERIC_OPENER", "Cover letter starts with a generic opener.", "warning"))
            if not re.search(r"\b(sincerely|best regards|regards|thank you)\b", text, flags=re.IGNORECASE):
                warnings.append(ValidationIssue("MISSING_SIGN_OFF", "Cover letter should include a human sign-off.", "warning"))

        if artifact_kind == "resume":
            bullets = [line for line in text.splitlines() if re.match(r"^\s*[-*]\s+", line)]
            for bullet in bullets:
                word_count = len([token for token in re.split(r"\s+", bullet.strip()) if token])
                if word_count > 32:
                    warnings.append(ValidationIssue("LONG_BULLET", "Resume bullet is longer than the target length.", "warning"))
                if any(re.search(pattern, bullet, flags=re.IGNORECASE) for pattern in WEAK_BULLET_PATTERNS):
                    warnings.append(ValidationIssue("WEAK_BULLET", "Resume bullet uses weak or vague phrasing.", "warning"))

            for required in [r"\bexperience\b", r"\bskills?\b"]:
                if not re.search(required, text, flags=re.IGNORECASE):
                    warnings.append(ValidationIssue("RESUME_MISSING_SECTION", "Resume may be missing an expected section.", "warning"))

            first_words = [
                re.sub(r"^\s*[-*]\s+", "", bullet).strip().split()[0].lower()
                for bullet in bullets
                if re.sub(r"^\s*[-*]\s+", "", bullet).strip().split()
            ]
            if any(first_words.count(word) >= 3 for word in set(first_words)):
                warnings.append(ValidationIssue("REPETITIVE_RHYTHM", "Multiple bullets start with the same word.", "warning"))

        return ValidationReport(passed=not blocking, blocking_issues=blocking, warnings=warnings)

    def validate_file(self, path: Path, *, artifact_kind: ArtifactKind) -> ValidationReport:
        extraction = extract_artifact_text(path)
        report = self.validate(extraction.text, artifact_kind=artifact_kind)
        extraction_warnings = [
            ValidationIssue("TEXT_EXTRACTION_WARNING", warning, "warning") for warning in extraction.warnings
        ]
        return ValidationReport(
            passed=report.passed,
            blocking_issues=report.blocking_issues,
            warnings=[*extraction_warnings, *report.warnings],
        )
