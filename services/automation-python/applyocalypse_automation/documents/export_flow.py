"""Shared render-tail for the two resume export paths (DOCX and TEX).

Both paths emit the same event skeleton — RESUME_MUTATION_COMPLETED ->
RESUME_RENDERED(source) -> run the exporter -> RESUME_RENDERED(PDF) or a
VALIDATION_FAILED with stdout/stderr tails. They differ only in data (messages,
the PDF-event machine_state, and the failure payload), captured by
``ResumeRenderTailSpec``. This is a behavior-preserving extraction: the emitted
events are byte-for-byte identical to the previous inline blocks in runner.py.

Scope note: only the two resume tails are consolidated here. The anchor-free
fallback, cover-letter, and lazy-cover-letter paths diverge structurally
(no mutation event, no PDF stage, report-file threading) and stay inline — see
plan 018's STOP-condition findings.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..event_protocol import EventType, Severity, WorkerEvent
from .artifact_generation import metadata_for_existing_file

# An exporter takes (source_path, output_dir) and returns an object exposing
# ``ok``, ``pdf_path``, ``stdout`` and ``stderr`` (PdfExportResult / TexCompileResult).
Exporter = Callable[[Path, Path], Any]


@dataclass(frozen=True, slots=True)
class ResumeRenderTailSpec:
    source_format: str  # "DOCX" | "TEX"
    mutation_message: str
    rendered_source_message: str
    rendered_pdf_message: str
    pdf_fail_message: str
    # Built from the exporter result so per-format dynamic fields (DOCX reads
    # result.exporter/result.code; TEX uses literals) stay exactly as before.
    pdf_rendered_machine_state: Callable[[Any], dict[str, Any]]
    pdf_fail_machine_state: Callable[[Any], dict[str, Any]]
    pdf_fail_payload: Callable[[Any, Path], dict[str, Any]]


def run_resume_render_tail(
    *,
    run_id: str,
    output_path: Path,
    output_dir: Path,
    master_path: Path,
    replaced_placeholders: list[str],
    spec: ResumeRenderTailSpec,
    exporter: Exporter,
) -> Any:
    """Emit the resume render-tail events and run the exporter.

    Returns the exporter result so the caller can run format-specific follow-up
    (the DOCX path's one-page enforcement). The events emitted are identical to
    the previous inline resume DOCX/TEX blocks.
    """
    artifact = metadata_for_existing_file(
        path=output_path, file_kind="RESUME", format_name=spec.source_format, review_only=False
    )
    WorkerEvent(
        event_type=EventType.RESUME_MUTATION_COMPLETED,
        run_id=run_id,
        step_id=None,
        severity=Severity.INFO,
        message=spec.mutation_message,
        machine_state={"source_format": spec.source_format, "replaced_placeholders": replaced_placeholders},
        ui_state={"current_step": "document_review"},
        payload={
            "source_master_path": str(master_path),
            "generated_path": str(output_path),
            "replaced_placeholders": replaced_placeholders,
        },
    ).emit()
    WorkerEvent(
        event_type=EventType.RESUME_RENDERED,
        run_id=run_id,
        step_id=None,
        severity=Severity.INFO,
        message=spec.rendered_source_message,
        machine_state={"format": spec.source_format, "review_only": False},
        ui_state={"current_step": "document_review"},
        payload=artifact.to_payload(),
    ).emit()

    result = exporter(output_path, output_dir)
    if result.ok and result.pdf_path:
        pdf_artifact = metadata_for_existing_file(
            path=result.pdf_path, file_kind="RESUME", format_name="PDF", review_only=False
        )
        WorkerEvent(
            event_type=EventType.RESUME_RENDERED,
            run_id=run_id,
            step_id=None,
            severity=Severity.INFO,
            message=spec.rendered_pdf_message,
            machine_state=spec.pdf_rendered_machine_state(result),
            ui_state={"current_step": "document_review"},
            payload=pdf_artifact.to_payload(),
        ).emit()
    else:
        WorkerEvent(
            event_type=EventType.VALIDATION_FAILED,
            run_id=run_id,
            step_id=None,
            severity=Severity.WARN,
            message=spec.pdf_fail_message,
            machine_state=spec.pdf_fail_machine_state(result),
            ui_state={"current_step": "document_review", "requires_user_review": True},
            payload=spec.pdf_fail_payload(result, output_path),
        ).emit()
    return result


RESUME_DOCX_TAIL = ResumeRenderTailSpec(
    source_format="DOCX",
    mutation_message="DOCX editable master mutated through explicit Applyocalypse anchors",
    rendered_source_message="Format-preserving DOCX resume rendered to local filesystem",
    rendered_pdf_message="DOCX resume exported to PDF with a local converter",
    pdf_fail_message="DOCX resume was tailored but PDF export did not complete",
    pdf_rendered_machine_state=lambda r: {"format": "PDF", "exporter": r.exporter, "review_only": False},
    pdf_fail_machine_state=lambda r: {"format": "DOCX", "exporter": r.exporter, "reason": r.code},
    pdf_fail_payload=lambda r, output_path: {
        "artifact_kind": "resume",
        "format": "DOCX",
        "source_docx_path": str(output_path),
        "stdout": r.stdout[-4000:],
        "stderr": r.stderr[-4000:],
        "blocking_issues": [{"code": r.code or "DOCX_PDF_EXPORT_FAILED"}],
    },
)


RESUME_TEX_TAIL = ResumeRenderTailSpec(
    source_format="TEX",
    mutation_message="TEX editable master mutated through explicit Applyocalypse anchors",
    rendered_source_message="Format-preserving TEX resume rendered to local filesystem",
    rendered_pdf_message="TEX resume compiled to PDF with Tectonic",
    pdf_fail_message="TEX resume was tailored but Tectonic PDF compilation did not complete",
    pdf_rendered_machine_state=lambda r: {"format": "PDF", "compiler": "tectonic", "review_only": False},
    pdf_fail_machine_state=lambda r: {"format": "TEX", "compiler": "tectonic", "reason": "TEX_COMPILE_FAILED"},
    pdf_fail_payload=lambda r, output_path: {
        "artifact_kind": "resume",
        "source_tex_path": str(output_path),
        "stdout": r.stdout[-4000:],
        "stderr": r.stderr[-4000:],
        "blocking_issues": [{"code": "TEX_COMPILE_FAILED"}],
    },
)
