"""Rebuilding a PDF resume as an editable DOCX.

The converted file is what every later tailoring run writes into, so what
matters here is not that the copy looks like the PDF but that nothing the user
wrote is dropped and that the structure a reader depends on - headings, bullets,
bold - is still marked as structure rather than flattened into one grey block.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document  # type: ignore

from applyocalypse_automation.documents.pdf_ingestion import (
    PdfLine,
    PdfRun,
    convert_pdf_to_candidate_docx,
    read_pdf_lines,
    write_candidate_docx,
)
from applyocalypse_automation.validation import extract_artifact_text


def _write_pdf(path: Path, lines: list[tuple[float, float, float, bool, str]]) -> Path:
    """Emit a minimal one-page PDF: (x, y, point size, bold, text) per line.

    Hand-built rather than produced by a library so the test owns exactly what
    the reader has to cope with, and so nothing new has to be installed to run it.
    """
    drawn = "\n".join(
        f"BT /{'F2' if bold else 'F1'} {size} Tf 1 0 0 1 {x} {y} Tm ({text}) Tj ET"
        for x, y, size, bold, text in lines
    ).encode("latin-1")

    objects = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources "
            b"<< /Font << /F1 5 0 R /F2 6 0 R >> >> /Contents 4 0 R >>"
        ),
        4: b"<< /Length " + str(len(drawn)).encode() + b" >>\nstream\n" + drawn + b"\nendstream",
        5: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        6: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
    }

    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for number in sorted(objects):
        offsets[number] = len(out)
        out += f"{number} 0 obj\n".encode() + objects[number] + b"\nendobj\n"

    start_xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for number in sorted(objects):
        out += f"{offsets[number]:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{start_xref}\n%%EOF\n".encode()

    path.write_bytes(bytes(out))
    return path


RESUME = [
    (72, 720, 18, True, "Jane Doe"),
    (72, 700, 10, False, "jane@example.com | 415-555-0132"),
    (72, 660, 13, True, "EXPERIENCE"),
    (72, 640, 10, True, "Senior Engineer, Acme Corp"),
    (80, 625, 10, False, "- Owned the billing service"),
    (80, 610, 10, False, "- Cut checkout latency by half"),
    (72, 575, 13, True, "EDUCATION"),
    (72, 555, 10, False, "Georgia Institute of Technology, BS Computer Science"),
]


@pytest.fixture
def resume_pdf(tmp_path: Path) -> Path:
    return _write_pdf(tmp_path / "jane-doe-resume.pdf", RESUME)


def test_every_line_of_the_pdf_comes_back(resume_pdf: Path) -> None:
    """The whole point of the gate the user is shown next is that this is lossless
    on content, so a dropped line has to fail here rather than at review time."""
    read = [line.text.strip() for line in read_pdf_lines(resume_pdf)]
    for _x, _y, _size, _bold, expected in RESUME:
        assert any(expected in line for line in read), expected


def test_the_font_each_line_was_set_in_survives(resume_pdf: Path) -> None:
    lines = {line.text.strip(): line for line in read_pdf_lines(resume_pdf)}
    assert lines["Jane Doe"].size == 18
    assert lines["Jane Doe"].all_bold
    assert lines["EXPERIENCE"].size == 13
    assert not lines["jane@example.com | 415-555-0132"].all_bold


def test_a_pdf_with_no_text_is_named_as_a_scan(tmp_path: Path) -> None:
    """An image-only PDF used to produce an empty document that looked fine until
    the user opened it. Say what is wrong instead."""
    blank = _write_pdf(tmp_path / "scan.pdf", [])
    with pytest.raises(RuntimeError, match="no selectable text"):
        convert_pdf_to_candidate_docx(blank, tmp_path / "out")


def test_conversion_writes_a_readable_docx(resume_pdf: Path, tmp_path: Path) -> None:
    result = convert_pdf_to_candidate_docx(resume_pdf, tmp_path / "out")

    assert result.candidate_docx_path.name == "jane-doe-resume editable candidate.docx"
    assert result.editable_master_status == "UNVERIFIED_EDITABLE_MASTER"
    assert result.original_pdf_path == resume_pdf

    text = "\n".join(p.text for p in Document(str(result.candidate_docx_path)).paragraphs)
    assert "Jane Doe" in text
    assert "Georgia Institute of Technology" in text
    # The list style draws its own marker, so carrying the PDF's would print two.
    assert "- Owned" not in text
    assert "Owned the billing service" in text


def test_bullets_become_word_list_items(resume_pdf: Path, tmp_path: Path) -> None:
    result = convert_pdf_to_candidate_docx(resume_pdf, tmp_path / "out")
    styles = {
        p.text.strip(): p.style.name for p in Document(str(result.candidate_docx_path)).paragraphs if p.text.strip()
    }
    assert styles["Owned the billing service"] == "List Bullet"
    assert styles["Cut checkout latency by half"] == "List Bullet"
    assert styles["Georgia Institute of Technology, BS Computer Science"] != "List Bullet"


def test_the_docx_still_reads_as_the_same_resume(resume_pdf: Path, tmp_path: Path) -> None:
    """The converted copy is the master everything downstream parses, so it has
    to hold up to the same reader the tailored output is checked against."""
    result = convert_pdf_to_candidate_docx(resume_pdf, tmp_path / "out")
    docx_text = extract_artifact_text(result.candidate_docx_path).text
    for phrase in ("Jane Doe", "EXPERIENCE", "Senior Engineer, Acme Corp", "EDUCATION"):
        assert phrase in docx_text


def _line(text: str, *, size: float = 10.0, bold: bool = False) -> PdfLine:
    return PdfLine(runs=(PdfRun(text=text, bold=bold),), size=size, font="Helvetica")


# (what the line looks like on the page, whether it should read as a heading)
HEADING_CASES: tuple[tuple[str, PdfLine, bool], ...] = (
    ("larger than the body", _line("EXPERIENCE", size=13, bold=True), True),
    ("same size but bold and short", _line("Senior Engineer", bold=True), True),
    ("body text", _line("Owned the billing service"), False),
    ("a bold sentence is still a sentence", _line("Led the migration end to end.", bold=True), False),
    ("a bullet is never a heading", _line("- Cut latency in half", size=13, bold=True), False),
)


@pytest.mark.parametrize("description,line,is_heading", HEADING_CASES, ids=[case[0] for case in HEADING_CASES])
def test_headings_are_recovered_from_the_font(
    tmp_path: Path, description: str, line: PdfLine, is_heading: bool
) -> None:
    """Word has no notion of a heading beyond how it is set, so the only signal
    is the type: bigger, or bold and short enough to be a label."""
    body = tuple([_line("Owned the billing service, and several other things besides.")] * 4 + [line])
    destination = tmp_path / "candidate.docx"
    write_candidate_docx(body, destination)

    rendered = next(p for p in Document(str(destination)).paragraphs if line.text.strip().lstrip("- ") in p.text)
    assert all(run.bold for run in rendered.runs) is (is_heading or line.runs[0].bold), description


def test_a_document_of_headings_does_not_elect_a_heading_as_its_body(tmp_path: Path) -> None:
    """Body size is weighted by how much text is set in it, not how many lines
    are. Counting lines lets a resume of short headers flatten to one level."""
    lines = tuple(
        [_line("SECTION", size=14, bold=True)] * 5 + [_line("A long paragraph of ordinary body copy.", size=10)]
    )
    destination = tmp_path / "candidate.docx"
    write_candidate_docx(lines, destination)

    paragraphs = {p.text.strip(): p for p in Document(str(destination)).paragraphs if p.text.strip()}
    assert all(run.bold for run in paragraphs["SECTION"].runs)
    assert not any(run.bold for run in paragraphs["A long paragraph of ordinary body copy."].runs)
