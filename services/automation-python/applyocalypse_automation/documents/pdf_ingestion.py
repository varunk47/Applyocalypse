from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PdfIngestionResult:
    original_pdf_path: Path
    candidate_docx_path: Path
    editable_master_status: str
    user_message: str


def convert_pdf_to_candidate_docx(source_pdf: Path, output_dir: Path) -> PdfIngestionResult:
    if source_pdf.suffix.lower() != ".pdf":
        raise ValueError("source_pdf must be a PDF")
    if not source_pdf.exists():
        raise FileNotFoundError(source_pdf)

    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_path = output_dir / f"{source_pdf.stem} editable candidate.docx"

    try:
        from pdf2docx import Converter  # type: ignore
    except ImportError as exc:
        raise RuntimeError("pdf2docx is required for local PDF ingestion") from exc

    converter = Converter(str(source_pdf))
    try:
        converter.convert(str(candidate_path))
    finally:
        converter.close()

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
