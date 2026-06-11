from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def build_cover_letter_docx(
    text: str,
    canonical_profile: dict[str, Any],
    output_path: Path,
) -> None:
    """Write a plain-text cover letter as a DOCX using python-docx.

    Format: Calibri 11, 1-inch normal margins, name + contact header,
    today's date, then body paragraphs (split on double newline).
    """
    try:
        from docx import Document  # type: ignore
        from docx.shared import Inches, Pt
        from docx.oxml.ns import qn  # type: ignore
    except ImportError as exc:
        raise RuntimeError("python-docx is required for cover letter DOCX generation") from exc

    profile = canonical_profile.get("profile") if isinstance(canonical_profile.get("profile"), dict) else {}
    legal_name = str(profile.get("legalName") or profile.get("displayName") or "").strip()
    email = str(profile.get("email") or "").strip()
    phone = str(profile.get("phone") or "").strip()
    location = str(profile.get("location") or "").strip()
    contact_parts = [part for part in [email, phone, location] if part]

    doc = Document()

    # Margins: 1 inch on all sides
    for section in doc.sections:
        section.top_margin = Inches(1)
        section.bottom_margin = Inches(1)
        section.left_margin = Inches(1)
        section.right_margin = Inches(1)

    def _set_run_font(run: Any, bold: bool = False) -> None:
        run.font.name = "Calibri"
        run.font.size = Pt(11)
        run.bold = bold
        # Force theme font override so Word renders Calibri
        run._r.get_or_add_rPr()
        rFonts = run._r.rPr.get_or_add_rFonts()
        rFonts.set(qn("w:ascii"), "Calibri")
        rFonts.set(qn("w:hAnsi"), "Calibri")

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
        _add_para("  |  ".join(contact_parts))

    # Blank line between header and date
    _add_para("")

    # Date
    today = datetime.now(timezone.utc).strftime("%B %d, %Y")
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
