"""Rebuild a PDF resume as an editable Word document.

A PDF cannot be mutated in place, so a user who only has a PDF gets a DOCX
standing in for it, and that copy is what every later tailoring run writes into.
The conversion is never exact, which is why onboarding makes the user look at the
result before anything is built on top of it.

The reconstruction is deliberately linear: one Word paragraph per line of PDF
text, with headings and bullets recovered from the font the line was set in. It
does not try to rebuild multi-column frames or tables as Word objects. That is
the better trade for this job twice over, because a plain paragraph flow is what
a person can actually edit and what an ATS can actually read, where the
absolutely positioned text boxes a layout-faithful converter emits are hostile
to both.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docx import Document  # type: ignore
from docx.enum.text import WD_TAB_ALIGNMENT  # type: ignore
from docx.oxml.ns import qn  # type: ignore
from docx.shared import Inches, Pt  # type: ignore

# A leading marker and the space after it. The glyph is dropped because Word's
# own list style draws the bullet, and keeping both prints two.
_BULLET_GLYPHS = "•‣▪●◦·⁃–"
_BULLET_RE = re.compile(f"^\\s*[{_BULLET_GLYPHS}*-]\\s+")
# "ABCDEF+Arial-BoldMT" is a subsetted font. Word wants the family, not the tag.
_SUBSET_PREFIX_RE = re.compile(r"^[A-Z]{6}\+")
_STYLE_SUFFIX_RE = re.compile(
    r"[-,_](?:Bold|Italic|Oblique|Regular|Roman|Light|Medium|MT|PS)+$", re.IGNORECASE
)

DEFAULT_FONT = "Calibri"
DEFAULT_SIZE = 11.0
# A line set larger than the body is a heading. Resume section headers are often
# only a point or two up, so the margin has to stay small.
HEADING_SIZE_RATIO = 1.08
# An all-bold line short enough to be a label rather than a sentence.
HEADING_MAX_CHARS = 60
# In pypdf's layout rendering, a run of spaces this long inside a line is a
# column gutter (a right-aligned date or city), not word spacing.
GUTTER_RE = re.compile(r"(?<=\S) {6,}(?=\S)")
# Two lines starting this close together start at the same indent.
INDENT_TOLERANCE_PT = 1.5
# Where the right-aligned tab stop goes: the page's text width at 0.75" margins.
TEXT_WIDTH_IN = 7.0


@dataclass(frozen=True, slots=True)
class PdfRun:
    text: str
    bold: bool


@dataclass(frozen=True, slots=True)
class PdfLine:
    runs: tuple[PdfRun, ...]
    size: float
    font: str
    # Where the line's words start, after any bullet marker drawn on its own.
    text_x: float | None = None

    @property
    def text(self) -> str:
        return "".join(run.text for run in self.runs)

    @property
    def all_bold(self) -> bool:
        return all(run.bold for run in self.runs if run.text.strip())


@dataclass(frozen=True, slots=True)
class PdfIngestionResult:
    original_pdf_path: Path
    candidate_docx_path: Path
    editable_master_status: str
    user_message: str


def _clean_font(base_font: Any) -> str:
    name = str(base_font or "").lstrip("/")
    name = _SUBSET_PREFIX_RE.sub("", name)
    name = _STYLE_SUFFIX_RE.sub("", name)
    return name.replace("-", " ").strip() or DEFAULT_FONT


def read_pdf_lines(source_pdf: Path) -> tuple[PdfLine, ...]:
    """Read a PDF back as styled lines of text.

    pypdf reports the font and size for every piece of text a page lays down, and
    emits a newline of its own where the page breaks a line. That is enough to
    recover the structure. Lines are never rebuilt or reordered by coordinate:
    pypdf flushes a run and updates the matrix at different moments, so a run's
    reported position is sometimes the previous one's, and reconstruction by
    coordinate would silently scramble exactly the resumes it looked like it
    handled best. Position is only read within a line, for the indent its words
    start at. Column gutters come from pypdf's layout rendering instead, which
    spaces text out by position and so shows a gutter as a long run of spaces.
    """
    from pypdf import PdfReader  # type: ignore

    lines: list[PdfLine] = []
    pending: list[PdfRun] = []
    # The style of the line being built, taken from its first non-blank text.
    pending_size = DEFAULT_SIZE
    pending_font = DEFAULT_FONT
    pending_text_x: float | None = None

    def close() -> None:
        nonlocal pending, pending_text_x
        if any(run.text.strip() for run in pending):
            lines.append(PdfLine(runs=tuple(pending), size=pending_size, font=pending_font, text_x=pending_text_x))
        pending, pending_text_x = [], None

    def visit(text: str, _cm: Any, tm: Any, font_dict: Any, font_size: Any) -> None:
        nonlocal pending_size, pending_font, pending_text_x
        size = float(font_size) if isinstance(font_size, (int, float)) and font_size else DEFAULT_SIZE
        raw_font = (font_dict or {}).get("/BaseFont") if isinstance(font_dict, dict) else None
        bold = "bold" in str(raw_font or "").casefold()
        x = float(tm[4]) if tm and (tm[4] or tm[5]) else None
        for index, part in enumerate(str(text).split("\n")):
            if index:
                close()
            if not part:
                continue
            if part.strip() and not any(run.text.strip() for run in pending):
                pending_size, pending_font = size, _clean_font(raw_font)
            if pending_text_x is None and index == 0 and x is not None and part.strip(" -*" + _BULLET_GLYPHS):
                pending_text_x = x
            pending.append(PdfRun(text=part, bold=bold))

    reader = PdfReader(str(source_pdf))
    gutters: dict[str, list[int]] = {}
    for page in reader.pages:
        page.extract_text(visitor_text=visit)
        close()
        gutters.update(_layout_gutters(page.extract_text(extraction_mode="layout")))

    return _join_wrapped_lines(tuple(_with_gutters(line, gutters) for line in lines))


def _squeezed(text: str) -> str:
    return "".join(text.split())


def _layout_gutters(layout_text: str) -> dict[str, list[int]]:
    """For each line with a gutter: where the gutters fall, counted in the
    non-space characters before each, keyed by the line's non-space text."""
    gutters: dict[str, list[int]] = {}
    for layout_line in layout_text.splitlines():
        stripped = layout_line.strip()
        found = [len(_squeezed(stripped[: match.start()])) for match in GUTTER_RE.finditer(stripped)]
        if found:
            gutters[_squeezed(layout_line)] = found
    return gutters


def _with_gutters(line: PdfLine, gutters: dict[str, list[int]]) -> PdfLine:
    """Put a tab at each gutter the layout rendering found in this line."""
    positions = set(gutters.get(_squeezed(line.text), ()))
    if not positions:
        return line
    runs: list[PdfRun] = []
    seen = 0
    for run in line.runs:
        text = ""
        for char in run.text:
            if not char.isspace() and seen in positions:
                positions.discard(seen)
                runs.append(PdfRun(text=text.rstrip(), bold=run.bold))
                runs.append(PdfRun(text="\t", bold=False))
                text = ""
            text += char
            seen += 0 if char.isspace() else 1
        runs.append(PdfRun(text=text, bold=run.bold))
    return PdfLine(
        runs=tuple(run for run in runs if run.text), size=line.size, font=line.font, text_x=line.text_x
    )


def _is_hanging_bullet(line: PdfLine) -> bool:
    """A bullet whose marker was drawn on its own, so its words sit at an indent."""
    marker = line.runs[0].text.strip() if line.runs else ""
    return len(marker) == 1 and marker in _BULLET_GLYPHS + "-*"


def _hyphen_break(previous: PdfLine, line: PdfLine) -> bool:
    text = previous.text.rstrip()
    return text.endswith("-") and text[:-1].rstrip()[-1:].isalnum() and line.text.lstrip()[:1].isalnum()


def _continues(previous: PdfLine, line: PdfLine) -> bool:
    """Whether `line` is the rest of `previous`, carried over by the page width.

    A plain paragraph that wraps back to the margin looks exactly like the next
    paragraph, so only the two unambiguous cases are joined: a bullet's words
    carried onto its hanging indent, and a word hyphenated across the break.
    """
    if previous.text_x is None or line.text_x is None or abs(previous.text_x - line.text_x) > INDENT_TOLERANCE_PT:
        return False
    if _BULLET_RE.match(line.text) or "\t" in previous.text or line.size != previous.size:
        return False
    return _is_hanging_bullet(previous) or _hyphen_break(previous, line)


def _joined(previous: PdfLine, line: PdfLine) -> PdfLine:
    runs = list(previous.runs)
    while runs and not runs[-1].text.strip():
        runs.pop()
    last = runs.pop()
    if _hyphen_break(previous, line):
        # "Fine -" + "Tuning" reads "Fine-Tuning": drop any space around the hyphen.
        head = last.text.rstrip()[:-1].rstrip()
        if head:
            runs.append(PdfRun(text=head + "-", bold=last.bold))
        else:
            if runs:
                runs[-1] = PdfRun(text=runs[-1].text.rstrip(), bold=runs[-1].bold)
            runs.append(PdfRun(text="-", bold=last.bold))
    else:
        runs += [PdfRun(text=last.text.rstrip(), bold=last.bold), PdfRun(text=" ", bold=False)]
    return PdfLine(
        runs=(*runs, *line.runs), size=previous.size, font=previous.font, text_x=previous.text_x
    )


def _join_wrapped_lines(lines: tuple[PdfLine, ...]) -> tuple[PdfLine, ...]:
    joined: list[PdfLine] = []
    for line in lines:
        if joined and _continues(joined[-1], line):
            joined[-1] = _joined(joined[-1], line)
        else:
            joined.append(line)
    return tuple(joined)


def _body_size(lines: tuple[PdfLine, ...]) -> float:
    """The size most of the document's *text* is set in, not most of its lines.

    Weighting by character count keeps a resume with many short headings from
    electing a heading size as the body size, which would flatten the whole
    document to a single level.
    """
    weights: dict[float, int] = {}
    for line in lines:
        weights[line.size] = weights.get(line.size, 0) + len(line.text.strip())
    if not weights:
        return DEFAULT_SIZE
    return max(weights.items(), key=lambda item: (item[1], -item[0]))[0]


def _is_heading(line: PdfLine, body_size: float) -> bool:
    stripped = line.text.strip()
    if not stripped or _BULLET_RE.match(line.text):
        return False
    if line.size >= body_size * HEADING_SIZE_RATIO:
        return True
    # Same size but wholly bold and short: the other common way resumes mark a
    # section. Closing punctuation means it is a sentence that happens to be bold.
    return (
        line.all_bold
        and len(stripped) <= HEADING_MAX_CHARS
        and not stripped.endswith((".", ",", ";", ":"))
    )


def write_candidate_docx(lines: tuple[PdfLine, ...], destination: Path) -> None:
    """Render extracted lines as a Word document the user can edit."""
    body_size = _body_size(lines)
    family = lines[0].font if lines else DEFAULT_FONT

    document = Document()
    for section in document.sections:
        section.top_margin = Inches(0.75)
        section.bottom_margin = Inches(0.75)
        section.left_margin = Inches(0.75)
        section.right_margin = Inches(0.75)

    def styled(run: Any, *, bold: bool, size: float) -> None:
        run.font.name = family
        run.font.size = Pt(size)
        run.bold = bold
        run._r.get_or_add_rPr()
        fonts = run._r.rPr.get_or_add_rFonts()
        fonts.set(qn("w:ascii"), family)
        fonts.set(qn("w:hAnsi"), family)

    for line in lines:
        bullet = bool(_BULLET_RE.match(line.text))
        heading = _is_heading(line, body_size)
        paragraph = document.add_paragraph(style="List Bullet") if bullet else document.add_paragraph()
        paragraph.paragraph_format.space_before = Pt(6 if heading else 0)
        paragraph.paragraph_format.space_after = Pt(0)
        if "\t" in line.text:
            # The gutter's far column sat on the right margin in the PDF.
            paragraph.paragraph_format.tab_stops.add_tab_stop(Inches(TEXT_WIDTH_IN), WD_TAB_ALIGNMENT.RIGHT)

        stripped_marker = False
        for source in line.runs:
            text = source.text
            if bullet and not stripped_marker:
                text = _BULLET_RE.sub("", text, count=1)
                stripped_marker = True
            if not text:
                continue
            styled(paragraph.add_run(text), bold=source.bold or heading, size=line.size)

    destination.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(destination))


def convert_pdf_to_candidate_docx(source_pdf: Path, output_dir: Path) -> PdfIngestionResult:
    if source_pdf.suffix.lower() != ".pdf":
        raise ValueError("source_pdf must be a PDF")
    if not source_pdf.exists():
        raise FileNotFoundError(source_pdf)

    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_path = output_dir / f"{source_pdf.stem} editable candidate.docx"

    lines = read_pdf_lines(source_pdf)
    if not lines:
        # A scanned resume is a picture of text. Saying so beats handing back an
        # empty document the user has to open before discovering it is empty.
        raise RuntimeError(
            "This PDF has no selectable text, so it is most likely a scan or an image. "
            "Upload the Word original, or a PDF exported from it, and we can tailor that."
        )
    write_candidate_docx(lines, candidate_path)

    return PdfIngestionResult(
        original_pdf_path=source_pdf,
        candidate_docx_path=candidate_path,
        editable_master_status="UNVERIFIED_EDITABLE_MASTER",
        user_message=(
            "We converted your PDF into an editable Word document so the system can tailor your resume while "
            "preserving structure as closely as possible. Review and fix any layout issues, then confirm this as "
            "your master editable resume."
        ),
    )
