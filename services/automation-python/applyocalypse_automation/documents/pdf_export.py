from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .file_generation import choose_collision_safe_path


@dataclass(frozen=True, slots=True)
class PdfExportResult:
    ok: bool
    pdf_path: Path | None
    exporter: str | None
    stdout: str
    stderr: str
    code: str | None = None


def _collision_safe_pdf_path(docx_path: Path, output_dir: Path) -> Path:
    return choose_collision_safe_path(output_dir, f"{docx_path.stem}.pdf")


def _export_with_libreoffice(docx_path: Path, output_dir: Path, *, timeout_seconds: int) -> PdfExportResult | None:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return None

    with tempfile.TemporaryDirectory(prefix="applyocalypse-docx-pdf-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        completed = subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(temp_dir), str(docx_path)],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        produced_pdf = temp_dir / f"{docx_path.stem}.pdf"
        if completed.returncode != 0 or not produced_pdf.exists():
            return PdfExportResult(
                ok=False,
                pdf_path=None,
                exporter="libreoffice",
                stdout=completed.stdout,
                stderr=completed.stderr,
                code="DOCX_PDF_EXPORT_FAILED",
            )
        target_path = _collision_safe_pdf_path(docx_path, output_dir)
        shutil.move(str(produced_pdf), target_path)
        return PdfExportResult(
            ok=True,
            pdf_path=target_path,
            exporter="libreoffice",
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


def _export_with_docx2pdf(docx_path: Path, output_dir: Path) -> PdfExportResult | None:
    try:
        from docx2pdf import convert  # type: ignore
    except ImportError:
        return None

    target_path = _collision_safe_pdf_path(docx_path, output_dir)
    try:
        convert(str(docx_path), str(target_path))
    except Exception as exc:
        return PdfExportResult(
            ok=False,
            pdf_path=None,
            exporter="docx2pdf",
            stdout="",
            stderr=str(exc),
            code="DOCX_PDF_EXPORT_FAILED",
        )
    if not target_path.exists():
        return PdfExportResult(
            ok=False,
            pdf_path=None,
            exporter="docx2pdf",
            stdout="",
            stderr="docx2pdf completed without producing a PDF",
            code="DOCX_PDF_EXPORT_FAILED",
        )
    return PdfExportResult(ok=True, pdf_path=target_path, exporter="docx2pdf", stdout="", stderr="")


def export_docx_to_pdf(docx_path: Path, output_dir: Path, *, timeout_seconds: int = 90) -> PdfExportResult:
    if not docx_path.exists():
        return PdfExportResult(
            ok=False,
            pdf_path=None,
            exporter=None,
            stdout="",
            stderr=f"DOCX file does not exist: {docx_path}",
            code="DOCX_PDF_SOURCE_MISSING",
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        libreoffice_result = _export_with_libreoffice(docx_path, output_dir, timeout_seconds=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        return PdfExportResult(
            ok=False,
            pdf_path=None,
            exporter="libreoffice",
            stdout=exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else str(exc.stdout or ""),
            stderr=exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else str(exc.stderr or "Timed out"),
            code="DOCX_PDF_EXPORT_TIMEOUT",
        )
    if libreoffice_result is not None:
        return libreoffice_result

    docx2pdf_result = _export_with_docx2pdf(docx_path, output_dir)
    if docx2pdf_result is not None:
        return docx2pdf_result

    return PdfExportResult(
        ok=False,
        pdf_path=None,
        exporter=None,
        stdout="",
        stderr="No local DOCX-to-PDF exporter is available. Install LibreOffice, Microsoft Word with docx2pdf, or upload the generated DOCX.",
        code="DOCX_PDF_EXPORTER_UNAVAILABLE",
    )
