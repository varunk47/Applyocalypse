"""Locks the resume render-tail event sequences (DOCX + TEX) extracted into
``export_flow.run_resume_render_tail``. These assertions encode the exact events
the previous inline runner.py blocks emitted; if the consolidation drifts, they
fail."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from applyocalypse_automation import event_protocol
from applyocalypse_automation.documents.export_flow import (
    RESUME_DOCX_TAIL,
    RESUME_TEX_TAIL,
    run_resume_render_tail,
)
from applyocalypse_automation.event_protocol import EventType, Severity, WorkerEvent


@pytest.fixture
def captured_events(monkeypatch: pytest.MonkeyPatch) -> list[WorkerEvent]:
    events: list[WorkerEvent] = []
    monkeypatch.setattr(event_protocol.WorkerEvent, "emit", lambda self: events.append(self))
    return events


def _make_files(tmp_path: Path, source_name: str) -> tuple[Path, Path]:
    source = tmp_path / source_name
    source.write_bytes(b"source-bytes")
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"%PDF-fake")
    return source, pdf


def test_docx_success_emits_mutation_render_and_pdf(tmp_path: Path, captured_events: list[WorkerEvent]) -> None:
    source, pdf = _make_files(tmp_path, "resume.docx")
    result = SimpleNamespace(ok=True, pdf_path=pdf, exporter="libreoffice", code=None, stdout="", stderr="")

    returned = run_resume_render_tail(
        run_id="run-1",
        output_path=source,
        output_dir=tmp_path,
        master_path=tmp_path / "master.docx",
        replaced_placeholders=["{{A}}"],
        spec=RESUME_DOCX_TAIL,
        exporter=lambda _src, _out: result,
    )

    assert returned is result
    assert [(e.event_type, e.severity) for e in captured_events] == [
        (EventType.RESUME_MUTATION_COMPLETED, Severity.INFO),
        (EventType.RESUME_RENDERED, Severity.INFO),
        (EventType.RESUME_RENDERED, Severity.INFO),
    ]
    mutation, rendered_src, rendered_pdf = captured_events
    assert mutation.message == "DOCX editable master mutated through explicit Applyocalypse anchors"
    assert mutation.machine_state == {"source_format": "DOCX", "replaced_placeholders": ["{{A}}"]}
    assert mutation.payload["replaced_placeholders"] == ["{{A}}"]
    assert rendered_src.machine_state == {"format": "DOCX", "review_only": False}
    assert rendered_pdf.message == "DOCX resume exported to PDF with a local converter"
    assert rendered_pdf.machine_state == {"format": "PDF", "exporter": "libreoffice", "review_only": False}


def test_docx_failure_emits_validation_failed_with_tails(tmp_path: Path, captured_events: list[WorkerEvent]) -> None:
    source, _ = _make_files(tmp_path, "resume.docx")
    result = SimpleNamespace(
        ok=False, pdf_path=None, exporter="libreoffice", code="LIBRE_BOOM", stdout="o" * 5000, stderr="e" * 5000
    )

    run_resume_render_tail(
        run_id="run-1",
        output_path=source,
        output_dir=tmp_path,
        master_path=tmp_path / "master.docx",
        replaced_placeholders=["{{A}}"],
        spec=RESUME_DOCX_TAIL,
        exporter=lambda _src, _out: result,
    )

    fail = captured_events[-1]
    assert fail.event_type == EventType.VALIDATION_FAILED
    assert fail.severity == Severity.WARN
    assert fail.message == "DOCX resume was tailored but PDF export did not complete"
    assert fail.machine_state == {"format": "DOCX", "exporter": "libreoffice", "reason": "LIBRE_BOOM"}
    assert fail.ui_state == {"current_step": "document_review", "requires_user_review": True}
    assert fail.payload["format"] == "DOCX"
    assert fail.payload["source_docx_path"] == str(source)
    assert len(fail.payload["stdout"]) == 4000 and len(fail.payload["stderr"]) == 4000
    assert fail.payload["blocking_issues"] == [{"code": "LIBRE_BOOM"}]


def test_docx_failure_blocking_code_falls_back_when_result_code_missing(
    tmp_path: Path, captured_events: list[WorkerEvent]
) -> None:
    source, _ = _make_files(tmp_path, "resume.docx")
    result = SimpleNamespace(ok=False, pdf_path=None, exporter="docx2pdf", code=None, stdout="", stderr="")

    run_resume_render_tail(
        run_id="run-1",
        output_path=source,
        output_dir=tmp_path,
        master_path=tmp_path / "master.docx",
        replaced_placeholders=["{{A}}"],
        spec=RESUME_DOCX_TAIL,
        exporter=lambda _src, _out: result,
    )

    assert captured_events[-1].payload["blocking_issues"] == [{"code": "DOCX_PDF_EXPORT_FAILED"}]


def test_tex_success_uses_tectonic_compiler_machine_state(tmp_path: Path, captured_events: list[WorkerEvent]) -> None:
    source, pdf = _make_files(tmp_path, "resume.tex")
    result = SimpleNamespace(ok=True, pdf_path=pdf, stdout="", stderr="")

    run_resume_render_tail(
        run_id="run-1",
        output_path=source,
        output_dir=tmp_path,
        master_path=tmp_path / "master.tex",
        replaced_placeholders=["{{A}}"],
        spec=RESUME_TEX_TAIL,
        exporter=lambda _src, _out: result,
    )

    mutation, rendered_src, rendered_pdf = captured_events
    assert mutation.message == "TEX editable master mutated through explicit Applyocalypse anchors"
    assert mutation.machine_state == {"source_format": "TEX", "replaced_placeholders": ["{{A}}"]}
    assert rendered_src.machine_state == {"format": "TEX", "review_only": False}
    assert rendered_pdf.message == "TEX resume compiled to PDF with Tectonic"
    assert rendered_pdf.machine_state == {"format": "PDF", "compiler": "tectonic", "review_only": False}


def test_tex_failure_payload_uses_source_tex_path_without_format_key(
    tmp_path: Path, captured_events: list[WorkerEvent]
) -> None:
    source, _ = _make_files(tmp_path, "resume.tex")
    result = SimpleNamespace(ok=False, pdf_path=None, stdout="o" * 5000, stderr="e" * 5000)

    run_resume_render_tail(
        run_id="run-1",
        output_path=source,
        output_dir=tmp_path,
        master_path=tmp_path / "master.tex",
        replaced_placeholders=["{{A}}"],
        spec=RESUME_TEX_TAIL,
        exporter=lambda _src, _out: result,
    )

    fail = captured_events[-1]
    assert fail.message == "TEX resume was tailored but Tectonic PDF compilation did not complete"
    assert fail.machine_state == {"format": "TEX", "compiler": "tectonic", "reason": "TEX_COMPILE_FAILED"}
    assert "format" not in fail.payload
    assert fail.payload["source_tex_path"] == str(source)
    assert len(fail.payload["stdout"]) == 4000 and len(fail.payload["stderr"]) == 4000
    assert fail.payload["blocking_issues"] == [{"code": "TEX_COMPILE_FAILED"}]
