"""Read the look of a user's resume so a rebuilt one can keep it.

The tailoring pipeline mutates a copy of the user's DOCX because that is the
only way it has ever known to preserve their formatting: editing runs in place
keeps the formatting as a side effect, since every run already carries its own
XML. The cost is that the document is only ever patched, never understood, and
`parse_back.py` exists to catch the times patching quietly destroys it.

Capturing the look explicitly removes that constraint. With a style profile in
hand, a resume can be rebuilt from structured data and still come out looking
like the one the user wrote.

Nothing here raises. A style profile is a nicety, and a master that cannot be
read must degrade to the defaults rather than stop a run. It reports which of
the two happened via `detected` so a caller never has to guess.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

# An em dash separator would be copied into generated text and trip the banned
# word gate, so it is not offered as a candidate however the master spells it.
_SEPARATOR_CANDIDATES = ("•", "|", "·", "‧", "/")

_HEADING_MAX_CHARS = 48

#: Words that identify which of the builder's sections a user's own heading is.
#: "Professional Experience" and "Work History" are the same section as far as
#: the builder is concerned, but only one of them is what the user wrote.
_SECTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "SKILLS": ("skill", "technical", "competenc", "expertise", "technolog"),
    "EXPERIENCE": ("experience", "employment", "work history", "professional"),
    "PROJECTS": ("project", "portfolio"),
    "EDUCATION": ("education", "academic", "qualification"),
}


@dataclass(frozen=True)
class Margins:
    top_in: float
    bottom_in: float
    left_in: float
    right_in: float


@dataclass(frozen=True)
class StyleProfile:
    """How a resume looks, in the terms a builder needs to reproduce it."""

    body_font: str
    body_size_pt: float
    heading_font: str
    heading_size_pt: float
    heading_bold: bool
    heading_all_caps: bool
    heading_rule: bool
    name_size_pt: float
    name_bold: bool
    name_centered: bool
    margins: Margins
    bullet_style: str
    contact_separator: str
    #: The user's own section wording, in their own order.
    section_labels: tuple[str, ...]
    #: False when this is the fallback rather than something read off a file.
    detected: bool

    def label_for(self, kind: str, default: str) -> str:
        """The user's own wording for a section, or the builder's default.

        A resume that renames "Professional Experience" to "Experience" reads
        as someone else's document, so the master's wording wins whenever it
        can be matched to a section the builder knows how to fill.
        """
        keywords = _SECTION_KEYWORDS.get(kind, ())
        for label in self.section_labels:
            lowered = label.lower()
            if any(keyword in lowered for keyword in keywords):
                return label
        return default


#: The look the builder hardcoded before profiles existed, kept as the fallback
#: so behaviour is unchanged when a master cannot be read.
DEFAULT_STYLE_PROFILE = StyleProfile(
    body_font="Calibri",
    body_size_pt=10.0,
    heading_font="Calibri",
    heading_size_pt=10.0,
    heading_bold=True,
    heading_all_caps=True,
    heading_rule=True,
    name_size_pt=14.0,
    name_bold=True,
    name_centered=True,
    margins=Margins(top_in=0.75, bottom_in=0.75, left_in=0.75, right_in=0.75),
    bullet_style="List Bullet",
    contact_separator="  |  ",
    section_labels=(),
    detected=False,
)


def _dominant(values: list[Any], fallback: Any) -> Any:
    """The most frequent value, or the fallback when there is nothing to count."""
    if not values:
        return fallback
    counts: dict[Any, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return max(counts, key=lambda item: counts[item])


def _run_size_pt(run: Any, paragraph: Any, document: Any) -> float | None:
    """A run's size in points, following the inheritance Word itself follows."""
    for source in (
        lambda: run.font.size,
        lambda: paragraph.style.font.size if paragraph.style is not None else None,
        lambda: document.styles["Normal"].font.size,
    ):
        try:
            size = source()
        except Exception:
            size = None
        if size is not None:
            return float(size.pt)
    return None


def _run_font_name(run: Any, paragraph: Any, document: Any) -> str | None:
    for source in (
        lambda: run.font.name,
        lambda: paragraph.style.font.name if paragraph.style is not None else None,
        lambda: document.styles["Normal"].font.name,
    ):
        try:
            name = source()
        except Exception:
            name = None
        if name:
            return str(name)
    return None


def _is_bullet(paragraph: Any) -> bool:
    try:
        return "list" in str(paragraph.style.name).lower()
    except Exception:
        return False


def _has_bottom_rule(paragraph: Any) -> bool:
    try:
        from docx.oxml.ns import qn  # type: ignore

        properties = paragraph._p.pPr
        if properties is None:
            return False
        borders = properties.find(qn("w:pBdr"))
        return borders is not None and borders.find(qn("w:bottom")) is not None
    except Exception:
        return False


def _looks_like_heading(paragraph: Any, text: str, body_size_pt: float, document: Any) -> bool:
    """Section headings, without mistaking a bold job title for one.

    A role line is bold too, so boldness alone cannot decide it. What separates
    a heading is that it is set apart: an explicit Word heading style, or all
    caps, or bold text set larger than the body.
    """
    if not text or len(text) > _HEADING_MAX_CHARS or _is_bullet(paragraph):
        return False
    try:
        if str(paragraph.style.name).lower().startswith("heading"):
            return True
    except Exception:
        pass
    if text.isupper() and any(character.isalpha() for character in text):
        return True
    runs = [run for run in paragraph.runs if run.text.strip()]
    if not runs or not all(run.bold for run in runs):
        return False
    sizes = [size for size in (_run_size_pt(run, paragraph, document) for run in runs) if size is not None]
    return bool(sizes) and min(sizes) > body_size_pt


def _detect_separator(text: str) -> str | None:
    for candidate in _SEPARATOR_CANDIDATES:
        if candidate in text:
            spaced = f" {candidate} "
            return spaced if spaced in text else candidate
    return None


def extract_docx_style_profile(path: Path) -> StyleProfile:
    """Read a DOCX master's look, falling back to the defaults if it cannot."""
    try:
        from docx import Document  # type: ignore
        from docx.enum.text import WD_ALIGN_PARAGRAPH  # type: ignore

        document = Document(str(path))
        paragraphs = [para for para in document.paragraphs if para.text.strip()]
        if not paragraphs:
            return DEFAULT_STYLE_PROFILE

        name_paragraph = paragraphs[0]
        body_paragraphs = paragraphs[1:]

        # The name is set larger than everything else by design, so counting it
        # would drag the body size up towards it.
        body_sizes = [
            size
            for para in body_paragraphs
            for size in (_run_size_pt(run, para, document) for run in para.runs if run.text.strip())
            if size is not None
        ]
        body_size_pt = float(_dominant(body_sizes, DEFAULT_STYLE_PROFILE.body_size_pt))
        body_fonts = [
            font
            for para in body_paragraphs
            for font in (_run_font_name(run, para, document) for run in para.runs if run.text.strip())
            if font
        ]
        body_font = str(_dominant(body_fonts, DEFAULT_STYLE_PROFILE.body_font))

        headings = [para for para in body_paragraphs if _looks_like_heading(para, para.text.strip(), body_size_pt, document)]
        heading_runs = [run for para in headings for run in para.runs if run.text.strip()]
        heading_sizes = [
            size
            for para in headings
            for size in (_run_size_pt(run, para, document) for run in para.runs if run.text.strip())
            if size is not None
        ]
        heading_fonts = [
            font
            for para in headings
            for font in (_run_font_name(run, para, document) for run in para.runs if run.text.strip())
            if font
        ]

        name_runs = [run for run in name_paragraph.runs if run.text.strip()]
        name_sizes = [
            size for size in (_run_size_pt(run, name_paragraph, document) for run in name_runs) if size is not None
        ]

        separator = None
        for para in body_paragraphs[:2]:
            separator = _detect_separator(para.text)
            if separator:
                break

        bullet_style = next(
            (str(para.style.name) for para in paragraphs if _is_bullet(para)),
            DEFAULT_STYLE_PROFILE.bullet_style,
        )

        section = document.sections[0]
        return StyleProfile(
            body_font=body_font,
            body_size_pt=body_size_pt,
            heading_font=str(_dominant(heading_fonts, body_font)),
            heading_size_pt=float(_dominant(heading_sizes, body_size_pt)),
            heading_bold=bool(heading_runs) and all(run.bold for run in heading_runs),
            heading_all_caps=bool(headings) and all(para.text.strip().isupper() for para in headings),
            heading_rule=any(_has_bottom_rule(para) for para in headings),
            name_size_pt=float(_dominant(name_sizes, body_size_pt)),
            name_bold=bool(name_runs) and all(run.bold for run in name_runs),
            name_centered=name_paragraph.alignment == WD_ALIGN_PARAGRAPH.CENTER,
            margins=Margins(
                top_in=float(section.top_margin.inches),
                bottom_in=float(section.bottom_margin.inches),
                left_in=float(section.left_margin.inches),
                right_in=float(section.right_margin.inches),
            ),
            bullet_style=bullet_style,
            contact_separator=separator or DEFAULT_STYLE_PROFILE.contact_separator,
            section_labels=tuple(para.text.strip() for para in headings),
            detected=True,
        )
    except Exception:
        return replace(DEFAULT_STYLE_PROFILE, detected=False)
