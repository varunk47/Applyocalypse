from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .style_profile import DEFAULT_STYLE_PROFILE, StyleProfile


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _date_range(entry: dict[str, Any]) -> str:
    """``2019-06`` and no end date reads as ``2019-06 to Present``.

    The canonical profile keeps the two endpoints in separate fields, so a
    missing end date on an entry that has a start date is a role still held,
    not an unknown one. A resume without dates is not merely thinner: an ATS
    parses employment history by date, so omitting them mangles the history it
    reconstructs.
    """
    start = str(entry.get("startDate") or "").strip()
    end = str(entry.get("endDate") or "").strip()
    if start and end:
        return f"{start} to {end}"
    if start:
        return f"{start} to Present"
    return end


def build_cover_letter_docx(
    text: str,
    canonical_profile: dict[str, Any],
    output_path: Path,
    *,
    style: StyleProfile | None = None,
) -> None:
    """Write a plain-text cover letter as a DOCX using python-docx.

    Format: name + contact header, today's date, then body paragraphs (split
    on double newline).

    With a ``style`` read off the user's master the letter takes their
    typeface and contact separator, so it reads as the same person's document
    as the resume it is sent with. It keeps its own one inch margins either
    way: a resume is often squeezed to half an inch to make one page, and a
    letter set that tight looks wrong. Without a style it is Calibri 11, the
    look this builder always had.
    """
    try:
        from docx import Document  # type: ignore
        from docx.oxml.ns import qn  # type: ignore
        from docx.shared import Inches, Pt
    except ImportError as exc:
        raise RuntimeError("python-docx is required for cover letter DOCX generation") from exc

    # The letter's own long-standing look, used whenever no master was read.
    look = style or replace(DEFAULT_STYLE_PROFILE, body_font="Calibri", body_size_pt=11.0)

    profile = canonical_profile.get("profile") if isinstance(canonical_profile.get("profile"), dict) else {}
    legal_name = str(profile.get("legalName") or profile.get("displayName") or "").strip()
    email = str(profile.get("email") or "").strip()
    phone = str(profile.get("phone") or "").strip()
    location = str(profile.get("location") or "").strip()
    contact_parts = [part for part in [email, phone, location] if part]

    doc = Document()

    # Margins: 1 inch on all sides. Deliberately not the master's, which is
    # sized to fit a resume on one page rather than to set a letter.
    for section in doc.sections:
        section.top_margin = Inches(1)
        section.bottom_margin = Inches(1)
        section.left_margin = Inches(1)
        section.right_margin = Inches(1)

    def _set_run_font(run: Any, bold: bool = False) -> None:
        run.font.name = look.body_font
        run.font.size = Pt(look.body_size_pt)
        run.bold = bold
        # Force theme font override so Word renders the requested family.
        run._r.get_or_add_rPr()
        rFonts = run._r.rPr.get_or_add_rFonts()
        rFonts.set(qn("w:ascii"), look.body_font)
        rFonts.set(qn("w:hAnsi"), look.body_font)

    def _add_para(text_content: str, bold: bool = False) -> Any:
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        run = p.add_run(text_content)
        _set_run_font(run, bold=bold)
        return p

    # Header: name line
    if legal_name:
        _add_para(legal_name, bold=True)
    if contact_parts:
        _add_para(look.contact_separator.join(contact_parts))

    # Blank line between header and date
    _add_para("")

    # Date
    today = datetime.now(UTC).strftime("%B %d, %Y")
    _add_para(today)

    # Blank line before body
    _add_para("")

    # Body: split on blank lines; each block is a paragraph
    body_blocks = [block.strip() for block in text.split("\n\n") if block.strip()]
    for i, block in enumerate(body_blocks):
        # Within each block, replace single newlines with spaces for paragraph continuity
        single_line = " ".join(block.splitlines())
        _add_para(single_line)
        if i < len(body_blocks) - 1:
            _add_para("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))


def build_resume_docx(
    canonical_profile: dict[str, Any],
    tailoring_plan: dict[str, Any],
    output_path: Path,
    *,
    font_size: int = 10,
    style: StyleProfile | None = None,
) -> None:
    """Build a resume DOCX from canonical profile, tailoring plan and style.

    With a ``style`` read off the user's master this reproduces their look:
    their typeface, margins, heading treatment and section wording. Without
    one it falls back to the look this builder always had, so passing nothing
    changes nothing.
    """
    try:
        from docx import Document  # type: ignore
        from docx.enum.text import WD_ALIGN_PARAGRAPH  # type: ignore
        from docx.oxml.ns import qn  # type: ignore
        from docx.shared import Inches, Pt
    except ImportError as exc:
        raise RuntimeError("python-docx is required for resume DOCX generation") from exc

    # `font_size` predates style profiles and still sets the tier when no
    # profile is supplied, so old callers keep their exact previous output.
    look = style or replace(
        DEFAULT_STYLE_PROFILE,
        body_size_pt=float(font_size),
        heading_size_pt=float(font_size),
        name_size_pt=float(font_size + 4),
    )

    profile = canonical_profile.get("profile") if isinstance(canonical_profile.get("profile"), dict) else {}
    legal_name = str(profile.get("legalName") or profile.get("displayName") or "").strip()
    email = str(profile.get("email") or "").strip()
    phone = str(profile.get("phone") or "").strip()
    location = str(profile.get("location") or "").strip()
    # `linkedinUrl` is the canonical key. Reading `linkedin` matched nothing the
    # profile ever emits, so this line silently resolved to "" on every run and
    # the URL never reached a generated resume.
    linkedin = str(profile.get("linkedinUrl") or "").strip()
    contact_parts = [part for part in [email, phone, location, linkedin] if part]

    one_page_plan = tailoring_plan.get("one_page_plan") if isinstance(tailoring_plan.get("one_page_plan"), dict) else {}
    bullet_limit = int(one_page_plan.get("bullet_limit_per_role", 4)) if isinstance(one_page_plan.get("bullet_limit_per_role"), (int, float)) else 4
    experience_limit = int(one_page_plan.get("experience_limit", 4)) if isinstance(one_page_plan.get("experience_limit"), (int, float)) else 4
    project_limit = int(one_page_plan.get("project_limit", 3)) if isinstance(one_page_plan.get("project_limit"), (int, float)) else 3

    doc = Document()
    for section in doc.sections:
        section.top_margin = Inches(look.margins.top_in)
        section.bottom_margin = Inches(look.margins.bottom_in)
        section.left_margin = Inches(look.margins.left_in)
        section.right_margin = Inches(look.margins.right_in)

    body_pt = Pt(look.body_size_pt)

    def _set_run(run: Any, bold: bool = False, size: Any = None, font: str | None = None) -> None:
        family = font or look.body_font
        run.font.name = family
        run.font.size = size or body_pt
        run.bold = bold
        # Force theme font override so Word renders the requested family.
        run._r.get_or_add_rPr()
        rFonts = run._r.rPr.get_or_add_rFonts()
        rFonts.set(qn("w:ascii"), family)
        rFonts.set(qn("w:hAnsi"), family)

    def _add_plain(text_content: str, bold: bool = False, center: bool = False, size: Any = None) -> Any:
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        if center:
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(text_content)
        _set_run(run, bold=bold, size=size)
        return p

    def _add_section_heading(kind: str, default_label: str) -> None:
        label = look.label_for(kind, default_label)
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(4)
        p.paragraph_format.space_after = Pt(0)
        run = p.add_run(label.upper() if look.heading_all_caps else label)
        _set_run(run, bold=look.heading_bold, size=Pt(look.heading_size_pt), font=look.heading_font)
        if not look.heading_rule:
            return
        # Horizontal rule below heading via bottom border
        from docx.oxml import OxmlElement  # type: ignore
        pPr = p._p.get_or_add_pPr()
        pBdr = OxmlElement("w:pBdr")
        bottom = OxmlElement("w:bottom")
        bottom.set(qn("w:val"), "single")
        bottom.set(qn("w:sz"), "4")
        bottom.set(qn("w:space"), "1")
        bottom.set(qn("w:color"), "000000")
        pBdr.append(bottom)
        pPr.append(pBdr)

    def _add_bullet(text_content: str) -> None:
        # A master may name a bullet style this blank document has never heard
        # of, which python-docx reports as a KeyError. A resume with unmarked
        # bullets still beats no resume at all.
        try:
            p = doc.add_paragraph(style=look.bullet_style)
        except KeyError:
            try:
                p = doc.add_paragraph(style=DEFAULT_STYLE_PROFILE.bullet_style)
            except KeyError:
                p = doc.add_paragraph()
                text_content = "• " + text_content
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        run = p.add_run(text_content)
        _set_run(run)

    # Name header
    if legal_name:
        _add_plain(legal_name, bold=look.name_bold, center=look.name_centered, size=Pt(look.name_size_pt))
    if contact_parts:
        _add_plain(look.contact_separator.join(contact_parts), center=look.name_centered)

    # Skills
    skill_groups = canonical_profile.get("skillGroups") if isinstance(canonical_profile.get("skillGroups"), list) else []
    all_skills: list[str] = []
    for grp in skill_groups:
        if isinstance(grp, dict):
            all_skills.extend(_string_list(grp.get("skills")))
    skills_priority = _string_list(one_page_plan.get("skills_priority"))
    ordered_skills: list[str] = [
        s for priority in skills_priority for s in all_skills if s.lower() == priority.lower()
    ]
    ordered_skills.extend([s for s in all_skills if s not in ordered_skills])
    if ordered_skills:
        _add_section_heading("SKILLS", "Skills")
        _add_plain(", ".join(ordered_skills[:36]))

    # Experience
    experience = canonical_profile.get("experience") if isinstance(canonical_profile.get("experience"), list) else []
    if experience:
        _add_section_heading("EXPERIENCE", "Experience")
        for entry in experience[:experience_limit]:
            if not isinstance(entry, dict):
                continue
            title = str(entry.get("title") or "").strip()
            company_name = str(entry.get("company") or "").strip()
            heading = " | ".join(part for part in [title, company_name, _date_range(entry)] if part)
            if heading:
                _add_plain(heading, bold=True)
            bullets_raw = _string_list(entry.get("bullets"))
            for bullet in bullets_raw[:bullet_limit]:
                _add_bullet(bullet)

    # Projects
    projects = canonical_profile.get("projects") if isinstance(canonical_profile.get("projects"), list) else []
    if projects:
        _add_section_heading("PROJECTS", "Projects")
        for project in projects[:project_limit]:
            if not isinstance(project, dict):
                continue
            name = str(project.get("name") or "").strip()
            if name:
                _add_plain(name, bold=True)
            summary = str(project.get("summary") or "").strip()
            if summary:
                _add_plain(summary)
            for bullet in _string_list(project.get("bullets"))[:bullet_limit]:
                _add_bullet(bullet)

    # Education
    education = canonical_profile.get("education") if isinstance(canonical_profile.get("education"), list) else []
    if education:
        _add_section_heading("EDUCATION", "Education")
        for entry in education[:3]:
            if not isinstance(entry, dict):
                continue
            institution = str(entry.get("institution") or "").strip()
            degree = str(entry.get("degree") or "").strip()
            field_name = str(entry.get("field") or "").strip()
            line = " | ".join(part for part in [institution, degree, field_name, _date_range(entry)] if part)
            if line:
                _add_plain(line)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))
