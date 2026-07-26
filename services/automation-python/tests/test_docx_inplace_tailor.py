"""In-place resume tailoring must change bullet TEXT while preserving the master's
exact run formatting (font, size, bold) and paragraph list/bullet style."""
from __future__ import annotations

from docx import Document
from docx.shared import Pt

from applyocalypse_automation.documents.docx_mutation import (
    collect_tailorable_bullets,
    tailor_master_docx_in_place,
)


def _make_master(path) -> None:
    doc = Document()
    doc.add_paragraph("EXPERIENCE")
    bullet = doc.add_paragraph(style="List Bullet")
    run = bullet.add_run("Built a data pipeline processing 10GB of logs using Python and Airflow daily")
    run.font.name = "Garamond"
    run.font.size = Pt(11)
    run.bold = True
    doc.save(str(path))


def test_collect_finds_the_bullet(tmp_path):
    master = tmp_path / "master.docx"
    _make_master(master)

    bullets = collect_tailorable_bullets(Document(str(master)))

    assert len(bullets) == 1
    _, text = bullets[0]
    assert "data pipeline" in text


def test_in_place_tailor_preserves_formatting(tmp_path):
    master = tmp_path / "master.docx"
    _make_master(master)
    index, _ = collect_tailorable_bullets(Document(str(master)))[0]
    new_text = "Engineered an ETL pipeline handling 10GB of logs with Python and Airflow"

    out = tmp_path / "out.docx"
    _, changed = tailor_master_docx_in_place(master, out, {index: new_text})

    assert changed == 1
    result = Document(str(out))
    paragraph = result.paragraphs[index]
    assert paragraph.text.strip() == new_text
    assert paragraph.style.name == "List Bullet"  # bullet/indent style preserved
    donor = paragraph.runs[0]
    assert donor.font.name == "Garamond"  # font preserved
    assert donor.font.size == Pt(11)  # size preserved
    assert donor.bold is True  # inline bold preserved


def test_no_changes_copies_master_verbatim(tmp_path):
    master = tmp_path / "m.docx"
    _make_master(master)
    out = tmp_path / "o.docx"

    _, changed = tailor_master_docx_in_place(master, out, {})

    assert changed == 0
    assert out.exists()
    # The bullet still has its original text and formatting.
    result = Document(str(out))
    index, text = collect_tailorable_bullets(result)[0]
    assert "data pipeline" in text
    assert result.paragraphs[index].runs[0].font.name == "Garamond"
