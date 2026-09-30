from __future__ import annotations

import os
import shutil
import subprocess
import sys
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


def _find_soffice() -> str | None:
    """Locate the LibreOffice binary.

    PATH is checked first. Neither the Windows installer nor the macOS app bundle
    puts soffice on PATH, so the standard install locations are checked too. Keep
    these in sync with findLibreOffice() in
    apps/desktop/src/main/services/converterDiagnostics.ts: if the diagnostic finds
    an install that this function misses, Settings reports the converter as present
    while every export silently falls through it.
    """
    on_path = shutil.which("soffice") or shutil.which("libreoffice")
    if on_path:
        return on_path

    if sys.platform == "darwin":
        for applications in (Path("/Applications"), Path.home() / "Applications"):
            candidate = applications / "LibreOffice.app" / "Contents" / "MacOS" / "soffice"
            if candidate.exists():
                return str(candidate)
        return None

    if sys.platform != "win32":
        return None

    bases = [
        os.environ.get("PROGRAMFILES", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
    ]
    for base in bases:
        candidate = Path(base) / "LibreOffice" / "program" / "soffice.exe"
        if candidate.exists():
            return str(candidate)
    return None


def _export_with_libreoffice(docx_path: Path, output_dir: Path, *, timeout_seconds: int) -> PdfExportResult | None:
    soffice = _find_soffice()
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


# Word runs out of process so a hung Word (a first-run dialog, a licence prompt)
# hits the timeout instead of hanging the worker. Paths travel in env vars, never
# in the script text, so a quote in a file name cannot break or inject into it.
# Exit 3 means Word is not installed, which is "no exporter", not a failure.
_WORD_WINDOWS_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
try { $word = New-Object -ComObject Word.Application } catch { exit 3 }
try {
  $word.Visible = $false
  $word.DisplayAlerts = 0
  $doc = $word.Documents.Open($env:APPLYO_DOCX_PATH, $false, $true)
  try { $doc.ExportAsFixedFormat($env:APPLYO_PDF_PATH, 17) } finally { $doc.Close(0) }
} finally {
  # COM can hand back a Word the user already has open. Never close their work.
  if ($word.Documents.Count -eq 0) { $word.Quit() }
  [void][Runtime.InteropServices.Marshal]::ReleaseComObject($word)
}
"""

_WORD_MAC_SCRIPT = """
on run argv
  set docxFile to POSIX file (item 1 of argv)
  set pdfPath to (POSIX file (item 2 of argv)) as string
  tell application "Microsoft Word"
    open docxFile
    set theDoc to active document
    save as theDoc file name pdfPath file format format PDF
    close theDoc saving no
  end tell
end run
"""

_MAC_WORD_APP = Path("/Applications/Microsoft Word.app")
_WORD_NOT_INSTALLED_EXIT = 3


def _word_command(docx_path: Path, pdf_path: Path) -> tuple[list[str], dict[str, str]] | None:
    """The command that makes Word export one PDF, or None when this OS has no Word."""
    if sys.platform == "win32":
        env = {**os.environ, "APPLYO_DOCX_PATH": str(docx_path), "APPLYO_PDF_PATH": str(pdf_path)}
        powershell = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass"]
        return [*powershell, "-Command", _WORD_WINDOWS_SCRIPT], env
    if sys.platform == "darwin" and _MAC_WORD_APP.exists():
        return ["osascript", "-e", _WORD_MAC_SCRIPT, str(docx_path), str(pdf_path)], dict(os.environ)
    return None


def _export_with_word(docx_path: Path, output_dir: Path, *, timeout_seconds: int) -> PdfExportResult | None:
    with tempfile.TemporaryDirectory(prefix="applyocalypse-word-pdf-") as temp_dir_name:
        produced_pdf = Path(temp_dir_name) / f"{docx_path.stem}.pdf"
        word = _word_command(docx_path.resolve(), produced_pdf)
        if word is None:
            return None
        command, env = word
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            env=env,
        )
        if sys.platform == "win32" and completed.returncode == _WORD_NOT_INSTALLED_EXIT:
            return None
        if completed.returncode != 0 or not produced_pdf.exists():
            return PdfExportResult(
                ok=False,
                pdf_path=None,
                exporter="word",
                stdout=completed.stdout,
                stderr=completed.stderr or "Word finished without producing a PDF",
                code="DOCX_PDF_EXPORT_FAILED",
            )
        target_path = _collision_safe_pdf_path(docx_path, output_dir)
        shutil.move(str(produced_pdf), target_path)
        return PdfExportResult(
            ok=True,
            pdf_path=target_path,
            exporter="word",
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


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

    try:
        word_result = _export_with_word(docx_path, output_dir, timeout_seconds=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        return PdfExportResult(
            ok=False,
            pdf_path=None,
            exporter="word",
            stdout=exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else str(exc.stdout or ""),
            stderr=exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else str(exc.stderr or "Timed out"),
            code="DOCX_PDF_EXPORT_TIMEOUT",
        )
    if word_result is not None:
        return word_result

    return PdfExportResult(
        ok=False,
        pdf_path=None,
        exporter=None,
        stdout="",
        stderr="No local DOCX-to-PDF exporter is available. Install LibreOffice or Microsoft Word, or upload the generated DOCX.",
        code="DOCX_PDF_EXPORTER_UNAVAILABLE",
    )
