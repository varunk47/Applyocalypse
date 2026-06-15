from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..documents.docx_mutation import inspect_docx_for_anchors
from ..documents.tex_mutation import inspect_tex_regions

PARSER_NAME = "applyocalypse-local-parser"
PARSER_VERSION = "0.3.0"

SECTION_ALIASES = {
    "experience": {
        "experience",
        "work experience",
        "professional experience",
        "employment",
        "employment history",
    },
    "projects": {"projects", "selected projects", "personal projects", "technical projects"},
    "education": {"education", "academic background"},
    "skills": {"skills", "technical skills", "technologies", "tools", "core skills"},
    "certifications": {"certifications", "certificates", "licenses"},
    "summary": {"summary", "profile", "professional summary"},
}

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_RE = re.compile(r"(?:\+?\d[\d\s().-]{7,}\d)")
URL_RE = re.compile(r"https?://[^\s)>\]]+", re.IGNORECASE)
LIST_PREFIX_RE = re.compile(r"^\s*(?:[-*\u2022]|\d+[.)])\s+")
SKILL_SPLIT_RE = re.compile(r"[,|;/]")
APPLYO_PLACEHOLDER_RE = re.compile(r"\{\{APPLYO_[A-Z0-9_]+\}\}")
SHORT_HEADING_MAX_CHARS = 120


@dataclass(frozen=True, slots=True)
class ParsedSection:
    section_id: str
    label: str
    normalized_label: str
    start_line: int
    end_line: int
    confidence: float
    items: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return {
            "sectionId": self.section_id,
            "label": self.label,
            "normalizedLabel": self.normalized_label,
            "startLine": self.start_line,
            "endLine": self.end_line,
            "confidence": self.confidence,
            "items": self.items,
        }


@dataclass(frozen=True, slots=True)
class ParsedDocumentResult:
    parser_name: str
    parser_version: str
    confidence: float
    canonical: dict[str, Any]
    style_map: dict[str, Any]
    anchor_map: dict[str, Any]
    warnings: list[str]

    def to_payload(self) -> dict[str, Any]:
        return {
            "parser_name": self.parser_name,
            "parser_version": self.parser_version,
            "confidence": self.confidence,
            "canonical": self.canonical,
            "style_map": self.style_map,
            "anchor_map": self.anchor_map,
            "warnings": self.warnings,
        }


def _source_format(path: Path) -> str:
    extension = path.suffix.lower()
    if extension == ".pdf":
        return "PDF"
    if extension == ".docx":
        return "DOCX"
    if extension == ".tex":
        return "TEX"
    if extension == ".md":
        return "MD"
    if extension == ".txt":
        return "TXT"
    raise ValueError(f"Unsupported document format: {extension or '(none)'}")


def _document_kind(value: str) -> str:
    normalized = value.upper()
    if normalized in {"RESUME", "COVER_LETTER", "SUPPORTING_DETAILS", "OTHER"}:
        return normalized
    return "OTHER"


def _normalize_line(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def _plain_text_from_docx(path: Path) -> tuple[str, dict[str, Any]]:
    try:
        from docx import Document  # type: ignore
    except ImportError as exc:
        raise RuntimeError("python-docx is required for DOCX parsing") from exc

    document = Document(str(path))
    paragraphs: list[dict[str, Any]] = []
    text_lines: list[str] = []
    for index, paragraph in enumerate(document.paragraphs):
        text = _normalize_line(paragraph.text)
        if not text:
            continue
        style = paragraph.style.name if paragraph.style is not None else ""
        is_bullet = paragraph._p.pPr is not None and paragraph._p.pPr.numPr is not None  # noqa: SLF001
        paragraphs.append(
            {
                "index": index,
                "style": style,
                "isBullet": is_bullet,
                "runCount": len(paragraph.runs),
                "textPreview": text[:160],
            }
        )
        text_lines.append(text)

    for table_index, table in enumerate(document.tables):
        for row_index, row in enumerate(table.rows):
            cell_lines: list[str] = []
            for cell_index, cell in enumerate(row.cells):
                for paragraph_index, paragraph in enumerate(cell.paragraphs):
                    text = _normalize_line(paragraph.text)
                    if not text:
                        continue
                    cell_lines.append(text)
                    style = paragraph.style.name if paragraph.style is not None else ""
                    paragraphs.append(
                        {
                            "index": f"table:{table_index}:{row_index}:{cell_index}:{paragraph_index}",
                            "style": style or "table-cell",
                            "isBullet": paragraph._p.pPr is not None and paragraph._p.pPr.numPr is not None,  # noqa: SLF001
                            "runCount": len(paragraph.runs),
                            "textPreview": text[:160],
                        }
                    )
                    text_lines.append(text)
            row_line = " | ".join(cell_lines)
            if len(cell_lines) > 1 and not any(_canonical_section_label(cell_line) for cell_line in cell_lines):
                paragraphs.append(
                    {
                        "index": f"table:{table_index}:{row_index}",
                        "style": "table-row",
                        "isBullet": False,
                        "runCount": 0,
                        "textPreview": row_line[:160],
                    }
                )
                text_lines.append(row_line)

    return "\n".join(text_lines), {"paragraphs": paragraphs, "tableCount": len(document.tables)}


def _plain_text(path: Path) -> tuple[str, dict[str, Any], list[str]]:
    source_format = _source_format(path)
    warnings: list[str] = []
    if source_format == "DOCX":
        text, style_map = _plain_text_from_docx(path)
        return text, style_map, warnings
    if source_format in {"TEX", "TXT", "MD"}:
        return path.read_text(encoding="utf-8", errors="replace"), {}, warnings
    warnings.append("PDF is ingestion-only. Parse the verified DOCX editable master produced from conversion.")
    return "", {}, warnings


def _detect_applyo_placeholders(source: str) -> list[str]:
    placeholders: list[str] = []
    seen: set[str] = set()
    for match in APPLYO_PLACEHOLDER_RE.finditer(source):
        placeholder = match.group(0)
        if placeholder not in seen:
            seen.add(placeholder)
            placeholders.append(placeholder)
    return placeholders


def _canonical_section_label(line: str) -> tuple[str, float] | None:
    cleaned = _normalize_line(line).strip(":").lower()
    cleaned = re.sub(r"[^a-z0-9 &/+-]", "", cleaned)
    if len(cleaned) > 42:
        return None
    for canonical, aliases in SECTION_ALIASES.items():
        if cleaned in aliases:
            return canonical, 0.86
    if cleaned.isupper() and 2 <= len(cleaned) <= 32:
        return cleaned.lower(), 0.58
    return None


def _strip_list_prefix(value: str) -> str:
    return LIST_PREFIX_RE.sub("", value).strip()


def _extract_sections(lines: list[str]) -> list[ParsedSection]:
    markers: list[tuple[int, str, str, float]] = []
    for index, line in enumerate(lines):
        label = _canonical_section_label(line)
        if label:
            markers.append((index, line, label[0], label[1]))

    sections: list[ParsedSection] = []
    for marker_index, (line_index, label, normalized_label, confidence) in enumerate(markers):
        end_line = markers[marker_index + 1][0] if marker_index + 1 < len(markers) else len(lines)
        items = [
            _strip_list_prefix(line)
            for line in lines[line_index + 1 : end_line]
            if _strip_list_prefix(line) and not _canonical_section_label(line)
        ]
        sections.append(
            ParsedSection(
                section_id=f"section:{normalized_label}:{marker_index}",
                label=label,
                normalized_label=normalized_label,
                start_line=line_index,
                end_line=max(line_index, end_line - 1),
                confidence=confidence,
                items=items,
            )
        )
    return sections


def _identity_from_lines(lines: list[str]) -> dict[str, Any]:
    joined = "\n".join(lines[:18])
    email = EMAIL_RE.search(joined)
    phone = PHONE_RE.search(joined)
    links = [
        {"label": url.split("//", 1)[-1].split("/", 1)[0], "url": url.rstrip(".,")}
        for url in URL_RE.findall(joined)
    ]

    legal_name: str | None = None
    for line in lines[:6]:
        if EMAIL_RE.search(line) or URL_RE.search(line) or PHONE_RE.search(line):
            continue
        candidate = _normalize_line(line)
        if 2 <= len(candidate.split()) <= 5 and len(candidate) <= 80:
            legal_name = candidate
            break

    return {
        "legalName": legal_name,
        "email": email.group(0) if email else None,
        "phone": _normalize_line(phone.group(0)) if phone else None,
        "location": None,
        "links": links,
    }


def _skills_from_section(section: ParsedSection) -> list[str]:
    skills: list[str] = []
    for item in section.items:
        cleaned = re.sub(r"^[A-Za-z /+&-]{2,32}:\s*", "", item)
        parts = [part.strip() for part in SKILL_SPLIT_RE.split(cleaned)]
        for part in parts:
            if not part or len(part) > 48:
                continue
            if len(part.split()) > 5:
                continue
            skills.append(part)
    deduped: list[str] = []
    seen: set[str] = set()
    for skill in skills:
        key = skill.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(skill)
    return deduped


def _split_once(value: str, separators: list[str]) -> tuple[str, str] | None:
    for separator in separators:
        if separator in value:
            left, right = value.split(separator, 1)
            left = _normalize_line(left)
            right = _normalize_line(right)
            if left and right:
                return left, right
    return None


def _is_probable_heading(value: str) -> bool:
    item = _normalize_line(value)
    if not item or len(item) > SHORT_HEADING_MAX_CHARS:
        return False
    if item.endswith((".", ";")):
        return False
    return True


def _experience_heading(item: str) -> tuple[str, str] | None:
    if not _is_probable_heading(item):
        return None
    at_match = re.match(r"^(?P<title>.+?)\s+(?:at|@)\s+(?P<company>.+)$", item, flags=re.IGNORECASE)
    if at_match:
        return _normalize_line(at_match.group("company")), _normalize_line(at_match.group("title"))

    split = _split_once(item, [" | ", " - "])
    if split:
        left, right = split
        if len(left.split()) <= 8 and len(right.split()) <= 10:
            return right, left
    return None


def _experience_from_section(section: ParsedSection) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for item in section.items:
        heading = _experience_heading(item)
        if heading:
            if current:
                entries.append(current)
            company, title = heading
            current = {
                "company": company,
                "title": title,
                "location": None,
                "startDate": None,
                "endDate": None,
                "bullets": [],
                "tools": [],
                "confidence": min(section.confidence, 0.82),
            }
            continue
        if current and item:
            current["bullets"].append(item)
    if current:
        entries.append(current)
    return entries


def _project_from_items(section: ParsedSection) -> list[dict[str, Any]]:
    projects: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for item in section.items:
        if _is_probable_heading(item):
            split = _split_once(item, [": ", " - ", " | "])
            if split or current is None:
                if current:
                    projects.append(current)
                name, summary = split if split else (item, None)
                current = {
                    "name": name,
                    "role": None,
                    "summary": summary,
                    "bullets": [],
                    "tools": [],
                    "links": URL_RE.findall(item),
                    "confidence": min(section.confidence, 0.82),
                }
                continue
        if current and item:
            current["bullets"].append(item)
    if current:
        projects.append(current)
    return projects


def _education_from_section(section: ParsedSection) -> list[dict[str, Any]]:
    education: list[dict[str, Any]] = []
    for item in section.items:
        if not _is_probable_heading(item):
            continue
        split = _split_once(item, [" | ", " - ", ", "])
        institution = split[0] if split else item
        degree = split[1] if split else None
        education.append(
            {
                "institution": institution,
                "degree": degree,
                "field": None,
                "startDate": None,
                "endDate": None,
                "details": [] if split else [item],
                "confidence": min(section.confidence, 0.8),
            }
        )
    return education


def _canonical_from_sections(*, source_format: str, document_kind: str, text: str, sections: list[ParsedSection]) -> dict[str, Any]:
    lines = [_normalize_line(line) for line in text.splitlines() if _normalize_line(line)]
    skill_groups = []
    for section in sections:
        if section.normalized_label == "skills":
            skills = _skills_from_section(section)
            if skills:
                skill_groups.append({"label": section.label, "skills": skills, "confidence": min(section.confidence, 0.82)})

    education = [
        entry
        for section in sections
        if section.normalized_label == "education"
        for entry in _education_from_section(section)
    ]
    experience = [
        entry
        for section in sections
        if section.normalized_label == "experience"
        for entry in _experience_from_section(section)
    ]
    projects = [
        entry
        for section in sections
        if section.normalized_label == "projects"
        for entry in _project_from_items(section)
    ]
    certifications = [
        {
            "name": item,
            "issuer": None,
            "issuedAt": None,
            "expiresAt": None,
            "credentialUrl": None,
            "confidence": min(section.confidence, 0.78),
        }
        for section in sections
        if section.normalized_label == "certifications"
        for item in section.items
        if item
    ]

    return {
        "documentKind": document_kind,
        "sourceFormat": source_format,
        "identity": _identity_from_lines(lines),
        "sections": [section.to_payload() for section in sections],
        "skillGroups": skill_groups,
        "education": education,
        "experience": experience,
        "projects": projects,
        "certifications": certifications,
        "rawTextPreview": text if document_kind == "COVER_LETTER" else text[:2000],
    }


def parse_document(path: Path, *, document_kind: str = "OTHER") -> ParsedDocumentResult:
    source_format = _source_format(path)
    text, style_map, warnings = _plain_text(path)
    lines = [_normalize_line(line) for line in text.splitlines() if _normalize_line(line)]
    sections = _extract_sections(lines)
    anchor_map: dict[str, Any] = {}

    if source_format == "DOCX":
        plan = inspect_docx_for_anchors(path)
        placeholders = _detect_applyo_placeholders(text)
        anchor_map = {"anchors": [asdict(anchor) for anchor in plan.anchors], "placeholders": placeholders}
        warnings.extend(plan.warnings)
        if not placeholders:
            warnings.append("No explicit Applyocalypse placeholders found. Automated DOCX mutation will pause for anchor repair.")
    elif source_format == "TEX":
        regions = inspect_tex_regions(path)
        source = path.read_text(encoding="utf-8", errors="replace")
        placeholders = _detect_applyo_placeholders(source)
        anchor_map = {"regions": [asdict(region) for region in regions], "placeholders": placeholders}
        if not regions:
            warnings.append("No high-confidence TEX regions found. User review is required before automated mutation.")
        if not placeholders:
            warnings.append("No explicit Applyocalypse placeholders found. Automated TEX mutation will pause for anchor repair.")

    if source_format == "PDF":
        confidence = 0.15
    else:
        section_confidence = sum(section.confidence for section in sections) / len(sections) if sections else 0.45
        anchor_bonus = 0.08 if anchor_map else 0
        confidence = min(0.92, max(0.35, section_confidence + anchor_bonus))

    if not sections and source_format != "PDF":
        warnings.append("No recognizable resume sections were detected. Manual profile review is required.")

    canonical = _canonical_from_sections(
        source_format=source_format,
        document_kind=_document_kind(document_kind),
        text=text,
        sections=sections,
    )

    return ParsedDocumentResult(
        parser_name=PARSER_NAME,
        parser_version=PARSER_VERSION,
        confidence=round(confidence, 3),
        canonical=canonical,
        style_map=style_map,
        anchor_map=anchor_map,
        warnings=warnings,
    )
