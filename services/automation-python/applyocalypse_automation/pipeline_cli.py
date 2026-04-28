from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .documents.docx_mutation import DocxParagraphMutation, mutate_docx_paragraphs
from .documents.anchor_repair import repair_editable_master_anchors
from .documents.file_generation import GeneratedNameInput, build_generated_filename, choose_collision_safe_path
from .documents.tex_mutation import TexBlockMutation, compile_tex_with_tectonic, mutate_tex_regions
from .jd_analysis import JobDescriptionAnalyzer
from .parsing.document_parser import parse_document
from .validation import TextArtifactValidator


def _load_json(path_or_json: str) -> Any:
    candidate = Path(path_or_json)
    if candidate.exists():
        return json.loads(candidate.read_text(encoding="utf-8"))
    return json.loads(path_or_json)


def _print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True), flush=True)


def analyze_jd(args: argparse.Namespace) -> None:
    text = Path(args.source_text_file).read_text(encoding="utf-8")
    _print_json(JobDescriptionAnalyzer().analyze(text).to_dict())


def validate_text(args: argparse.Namespace) -> None:
    text = Path(args.source_text_file).read_text(encoding="utf-8")
    report = TextArtifactValidator().validate(text, artifact_kind=args.artifact_kind)
    _print_json(report.to_dict())


def validate_file(args: argparse.Namespace) -> None:
    report = TextArtifactValidator().validate_file(Path(args.source), artifact_kind=args.artifact_kind)
    _print_json(report.to_dict())


def repair_anchors(args: argparse.Namespace) -> None:
    result = repair_editable_master_anchors(Path(args.source), Path(args.output))
    _print_json(result.to_payload())


def docx_mutate(args: argparse.Namespace) -> None:
    mutations = [
        DocxParagraphMutation(paragraph_index=int(item["paragraph_index"]), replacement_text=str(item["replacement_text"]))
        for item in _load_json(args.mutations_json)
    ]
    output = mutate_docx_paragraphs(Path(args.source), Path(args.output), mutations)
    _print_json({"output_path": str(output)})


def tex_mutate(args: argparse.Namespace) -> None:
    mutations = [
        TexBlockMutation(region_id=str(item["region_id"]), replacement_source=str(item["replacement_source"]))
        for item in _load_json(args.mutations_json)
    ]
    output = mutate_tex_regions(Path(args.source), Path(args.output), mutations)
    _print_json({"output_path": str(output)})


def tex_compile(args: argparse.Namespace) -> None:
    result = compile_tex_with_tectonic(Path(args.source), Path(args.output_dir))
    _print_json(
        {
            "ok": result.ok,
            "pdf_path": str(result.pdf_path) if result.pdf_path else None,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    )


def generated_name(args: argparse.Namespace) -> None:
    filename = build_generated_filename(
        GeneratedNameInput(
            first_name=args.first_name,
            last_name=args.last_name,
            company=args.company,
            role=args.role,
            kind=args.kind,
            extension=args.extension,
        )
    )
    path = choose_collision_safe_path(Path(args.output_dir), filename)
    _print_json({"filename": filename, "local_path": str(path)})


def parse_source(args: argparse.Namespace) -> None:
    result = parse_document(Path(args.source), document_kind=args.document_kind)
    _print_json(result.to_payload())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="applyocalypse-pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser("analyze-jd")
    analyze.add_argument("--source-text-file", required=True)
    analyze.set_defaults(func=analyze_jd)

    validate = subparsers.add_parser("validate-text")
    validate.add_argument("--source-text-file", required=True)
    validate.add_argument("--artifact-kind", choices=["resume", "cover_letter", "generic"], required=True)
    validate.set_defaults(func=validate_text)

    validate_artifact = subparsers.add_parser("validate-file")
    validate_artifact.add_argument("--source", required=True)
    validate_artifact.add_argument("--artifact-kind", choices=["resume", "cover_letter", "generic"], required=True)
    validate_artifact.set_defaults(func=validate_file)

    repair = subparsers.add_parser("repair-anchors")
    repair.add_argument("--source", required=True)
    repair.add_argument("--output", required=True)
    repair.set_defaults(func=repair_anchors)

    docx = subparsers.add_parser("docx-mutate")
    docx.add_argument("--source", required=True)
    docx.add_argument("--output", required=True)
    docx.add_argument("--mutations-json", required=True)
    docx.set_defaults(func=docx_mutate)

    tex = subparsers.add_parser("tex-mutate")
    tex.add_argument("--source", required=True)
    tex.add_argument("--output", required=True)
    tex.add_argument("--mutations-json", required=True)
    tex.set_defaults(func=tex_mutate)

    tex_pdf = subparsers.add_parser("tex-compile")
    tex_pdf.add_argument("--source", required=True)
    tex_pdf.add_argument("--output-dir", required=True)
    tex_pdf.set_defaults(func=tex_compile)

    name = subparsers.add_parser("generated-name")
    name.add_argument("--first-name", required=True)
    name.add_argument("--last-name", required=True)
    name.add_argument("--company", required=True)
    name.add_argument("--role", required=True)
    name.add_argument("--kind", choices=["Resume", "CoverLetter"], required=True)
    name.add_argument("--extension", choices=["docx", "pdf", "tex", "txt", "md"], required=True)
    name.add_argument("--output-dir", required=True)
    name.set_defaults(func=generated_name)

    parse = subparsers.add_parser("parse-source")
    parse.add_argument("--source", required=True)
    parse.add_argument("--document-kind", choices=["RESUME", "COVER_LETTER", "SUPPORTING_DETAILS", "OTHER"], required=True)
    parse.set_defaults(func=parse_source)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
