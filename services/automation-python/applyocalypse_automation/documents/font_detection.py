"""Font size detection for DOCX and TEX resume files.

Used to select the correct character-limit tier for the tailoring prompt.
Supported tiers: font 10pt (limits: 125/240) and font 11pt (limits: 115/220).
Falls back to 10 when detection is inconclusive.
"""
from __future__ import annotations

import re
from pathlib import Path

_FALLBACK_FONT_SIZE = 10
_SUPPORTED_SIZES = {10, 11}


def detect_docx_body_font_size(path: Path) -> int:
    """Return dominant body font size (pt) from a DOCX file.

    Scans all paragraph runs, collects non-None font sizes, and returns
    the most common one if it is in the supported set {10, 11}.
    Falls back to 10 on any error or when no valid size is found.
    """
    try:
        from docx import Document  # type: ignore
        from docx.shared import Pt  # type: ignore  # noqa: F401
    except ImportError:
        return _FALLBACK_FONT_SIZE

    try:
        doc = Document(str(path))

        def _style_size_pt(para) -> int | None:
            try:
                style_size = para.style.font.size if para.style is not None else None
            except Exception:
                style_size = None
            if style_size is None:
                try:
                    style_size = doc.styles["Normal"].font.size
                except Exception:
                    style_size = None
            return round(style_size / 12700) if style_size is not None else None

        size_counts: dict[int, int] = {}
        for para in doc.paragraphs:
            for run in para.runs:
                size = run.font.size
                if size is not None:
                    pt = round(size / 12700)  # EMUs → pt
                else:
                    pt_or_none = _style_size_pt(para)
                    if pt_or_none is None:
                        continue
                    pt = pt_or_none
                size_counts[pt] = size_counts.get(pt, 0) + 1
        if not size_counts:
            return _FALLBACK_FONT_SIZE
        dominant = max(size_counts, key=lambda s: size_counts[s])
        return dominant if dominant in _SUPPORTED_SIZES else _FALLBACK_FONT_SIZE
    except Exception:
        return _FALLBACK_FONT_SIZE


def detect_tex_body_font_size(path: Path) -> int:
    """Return body font size from a TEX file by scanning \\documentclass options.

    Looks for patterns like \\documentclass[11pt]{...} or \\documentclass[10pt]{...}.
    Falls back to 10 if not found or on error.
    """
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return _FALLBACK_FONT_SIZE

    match = re.search(r"\\documentclass\s*\[([^\]]*)\]", source)
    if match:
        options = match.group(1)
        size_match = re.search(r"\b(10|11)pt\b", options)
        if size_match:
            size = int(size_match.group(1))
            return size if size in _SUPPORTED_SIZES else _FALLBACK_FONT_SIZE

    # Also check \fontsize{11}{...} or \fontsize{10}{...}
    fontsize_match = re.search(r"\\fontsize\s*\{(10|11)\}", source)
    if fontsize_match:
        size = int(fontsize_match.group(1))
        return size if size in _SUPPORTED_SIZES else _FALLBACK_FONT_SIZE

    return _FALLBACK_FONT_SIZE


def detect_resume_font_size(path: Path) -> int:
    """Detect body font size from a resume file (DOCX or TEX).

    Returns 10 or 11 (pt). Falls back to 10 for unsupported formats.
    """
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return detect_docx_body_font_size(path)
    if suffix == ".tex":
        return detect_tex_body_font_size(path)
    return _FALLBACK_FONT_SIZE


def count_pdf_pages(path: Path) -> int:
    """Return page count of a PDF using pypdf.

    Returns 0 on import error or parse error.
    """
    try:
        from pypdf import PdfReader  # type: ignore
        reader = PdfReader(str(path))
        return len(reader.pages)
    except ImportError:
        return 0
    except Exception:
        return 0
