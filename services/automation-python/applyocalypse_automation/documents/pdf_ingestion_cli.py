from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pdf_ingestion import convert_pdf_to_candidate_docx


def main() -> None:
    parser = argparse.ArgumentParser(prog="pdf-ingestion")
    parser.add_argument("--source", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    result = convert_pdf_to_candidate_docx(Path(args.source), Path(args.output_dir))
    print(
        json.dumps(
            {
                "original_pdf_path": str(result.original_pdf_path),
                "candidate_docx_path": str(result.candidate_docx_path),
                "editable_master_status": result.editable_master_status,
                "user_message": result.user_message,
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
