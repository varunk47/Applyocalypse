"""Document-generation stage extracted from runner.py (plan 020, no behavior change).

Owns the tailoring/analysis document pipeline: work-dir input handling, JD
analysis, tailoring plan, markdown review artifact, master mutation, export
tails, cover-letter generation, and the lazy portal cover-letter path.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

from .answers import propose_profile_answers
from .cover_letter_tailoring import generate_cover_letter
from .documents.artifact_generation import (
    build_cover_letter_text,
    build_placeholder_replacements,
    build_resume_markdown,
    find_anchored_resume_candidate,
    find_verified_resume_master,
    metadata_for_existing_file,
    split_legal_name,
    write_text_artifact,
)
from .documents.docx_builder import build_cover_letter_docx, build_resume_docx
from .documents.docx_mutation import extract_docx_text, mutate_docx_bullet_anchors, mutate_docx_placeholders
from .documents.export_flow import RESUME_DOCX_TAIL, RESUME_TEX_TAIL, run_resume_render_tail
from .documents.file_generation import GeneratedNameInput, build_generated_filename, choose_collision_safe_path
from .documents.pdf_export import export_docx_to_pdf
from .documents.tex_mutation import compile_tex_with_tectonic, mutate_tex_placeholders
from .event_protocol import EventType, Severity, WorkerEvent
from .jd_analysis import analyze_with_optional_llm
from .llm.litellm_client import LiteLlmClient
from .resume_tailoring import tailor_resume_sections
from .tailoring.engine import TailoringEngine
from .validation import TextArtifactValidator, ValidationReport


def tex_escape(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
    }
    return "".join(replacements.get(character, character) for character in value)


def _company_from_url(url: str) -> str | None:
    try:
        host = urlparse(url).hostname or ""
        if "myworkdayjobs.com" in host or "workdayjobs.com" in host:
            return host.split(".")[0].replace("-", " ").title()
        parts = host.replace("www.", "").split(".")
        if parts:
            return parts[0].replace("-", " ").title()
    except Exception:
        pass
    return None


def _role_from_url(url: str) -> str | None:
    try:
        path = unquote(urlparse(url).path)
        segments = [s for s in path.split("/") if s]
        # Workday: /en-US/External_Careers/job/<location>/<title>_<id>
        if "job" in segments:
            idx = segments.index("job")
            if idx + 2 <= len(segments):
                slug = segments[idx + 2] if idx + 2 < len(segments) else segments[idx + 1]
                slug = re.sub(r"_[A-Z0-9]{6,}$", "", slug)
                return re.sub(r"[-_]+", " ", slug).strip().title()
        if segments:
            slug = re.sub(r"_[A-Z0-9]{6,}$", "", segments[-1])
            return re.sub(r"[-_]+", " ", slug).strip().title()
    except Exception:
        pass
    return None


def _build_bullet_retry_jd(job_text: str, report: ValidationReport) -> str:
    """Return a modified job description string that appends violation guidance for a retry."""
    violation_codes = ", ".join(issue.code for issue in report.blocking_issues)
    return job_text + (
        "\n\nIMPORTANT: The previous bullet set failed validation ("
        + violation_codes
        + "). No em dashes. No banned words. Plain text bullets only."
    )


def _build_overflow_jd(job_text: str, pages: int) -> str:
    """Return a modified job description string that instructs the LLM to reduce resume length."""
    return job_text + (
        "\n\nIMPORTANT: The tailored resume overflowed to "
        + str(pages)
        + " pages. Cut the weakest bullets and tighten wording so the resume fits ONE page."
    )


def _remutate_and_export(master_path, output_path, replacements, bullet_map, output_dir):
    """Re-run placeholder + bullet mutation from the master and export PDF. Returns the export result."""
    mutate_docx_placeholders(master_path, output_path, replacements)
    if bullet_map:
        mutate_docx_bullet_anchors(output_path, output_path, bullet_map)
    return export_docx_to_pdf(output_path, output_dir)


async def _lazy_generate_cover_letter_for_portal(
    *,
    run_id: str,
    work_dir: Path,
    output_dir: Path,
) -> dict[str, object] | None:
    """Lazily generate a cover letter DOCX when a portal upload field requires one.

    Only runs when APPLYO_LAZY_COVER_LETTER=1. Reads canonical_profile, job text,
    sample text, and job metadata from well-known work_dir paths written by the
    scheduler before the run starts.

    Emits COVER_LETTER_RENDERED and USER_REVIEW_REQUIRED(DOCUMENT) on success.
    Returns a generated-file metadata dict (same shape as ArtifactMetadata.to_payload)
    suitable for appending to generated_files, or None on failure.
    """
    if os.getenv("APPLYO_LAZY_COVER_LETTER") != "1":
        return None

    canonical_profile: dict[str, object] = {}
    profile_path = work_dir / "canonical-profile.json"
    if profile_path.exists():
        try:
            canonical_profile = json.loads(profile_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    job_text = ""
    for _job_name in ("job-description.txt", "job-description-scraped.txt"):
        _p = work_dir / _job_name
        if _p.exists():
            job_text = _p.read_text(encoding="utf-8")
            break

    cover_letter_sample: str | None = None
    sample_path = work_dir / "cover-letter-sample.txt"
    if sample_path.exists():
        cover_letter_sample = sample_path.read_text(encoding="utf-8") or None

    job_metadata: dict[str, object] = {}
    metadata_path = work_dir / "job-target.json"
    if metadata_path.exists():
        try:
            job_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    cover_letter_content: str | None = None
    cl_generation_mode = "DETERMINISTIC"
    cl_llm_model = os.getenv("LITELLM_MODEL_STRONG") or os.getenv("LITELLM_MODEL")
    if cl_llm_model and job_text:
        try:
            generated = await generate_cover_letter(
                job_description=job_text,
                canonical_profile=canonical_profile,
                cover_letter_sample=cover_letter_sample,
                llm_client=LiteLlmClient(model=cl_llm_model),
            )
            if generated:
                cover_letter_content = generated.text
                cl_generation_mode = "LLM"
        except Exception:
            pass

    if cover_letter_content is None:
        tailoring_plan: dict[str, object] = {}
        plan_path = work_dir / "tailoring-plan.json"
        if plan_path.exists():
            try:
                tailoring_plan = json.loads(plan_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        cover_letter_content = build_cover_letter_text(
            canonical_profile=canonical_profile,
            job_metadata=job_metadata,
            tailoring_plan=tailoring_plan,
        )
        cl_generation_mode = "DETERMINISTIC"

    if not cover_letter_content:
        return None

    report = TextArtifactValidator().validate(cover_letter_content, artifact_kind="cover_letter")
    report_path = work_dir / "cover-letter-lazy-validation-report.json"
    report_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")

    if not report.passed:
        WorkerEvent(
            event_type=EventType.VALIDATION_FAILED,
            run_id=run_id,
            step_id=None,
            severity=Severity.ERROR,
            message="Lazily generated cover letter failed validation",
            machine_state={"generation_mode": cl_generation_mode},
            ui_state={"current_step": "document_review", "requires_user_review": True},
            payload={"artifact_kind": "cover_letter", "validation_report_path": str(report_path), **report.to_dict()},
        ).emit()
        return None

    profile = canonical_profile.get("profile") if isinstance(canonical_profile.get("profile"), dict) else {}
    first_name, last_name = split_legal_name(str(profile.get("legalName") or profile.get("displayName") or "Candidate Profile"))
    company = str(job_metadata.get("company") or "")
    role = str(job_metadata.get("role") or "")
    cl_filename_input = GeneratedNameInput(
        first_name=first_name,
        last_name=last_name,
        company=company,
        role=role,
        kind="Cover Letter",
        extension="docx",
    )
    cl_docx_path = choose_collision_safe_path(output_dir, build_generated_filename(cl_filename_input))
    build_cover_letter_docx(cover_letter_content, canonical_profile, cl_docx_path)

    cl_artifact = metadata_for_existing_file(
        path=cl_docx_path,
        file_kind="COVER_LETTER",
        format_name="DOCX",
        review_only=True,
    )

    WorkerEvent(
        event_type=EventType.COVER_LETTER_RENDERED,
        run_id=run_id,
        step_id=None,
        severity=Severity.INFO,
        message="Cover letter generated lazily for portal upload field",
        machine_state={"format": "DOCX", "review_only": True, "generation_mode": cl_generation_mode},
        ui_state={"current_step": "document_review"},
        payload={**cl_artifact.to_payload(), "validation_report_path": str(report_path)},
    ).emit()

    WorkerEvent(
        event_type=EventType.USER_REVIEW_REQUIRED,
        run_id=run_id,
        step_id=None,
        severity=Severity.WARN,
        message="Lazily generated cover letter awaits review before upload",
        machine_state={"artifact_kind": "DOCUMENT", "generation_mode": cl_generation_mode},
        ui_state={"requires_user_review": True, "current_step": "document_review", "artifact_kind": "DOCUMENT"},
        payload={"artifact_kind": "DOCUMENT", **cl_artifact.to_payload()},
    ).emit()

    return cl_artifact.to_payload()


def generate_application_documents(
    *,
    run_id: str,
    work_dir: Path,
    output_dir: Path,
    canonical_profile: dict[str, object],
    job_text: str,
    job_metadata: dict[str, object],
    cover_letter_sample_text: str | None,
    job_text_source_path: str | None,
    job_text_source_url: str | None,
    jd_source: str,
) -> None:
    analysis_result, analysis_source = asyncio.run(analyze_with_optional_llm(job_text))
    analysis = analysis_result.to_dict()
    WorkerEvent(
        event_type=EventType.JD_ANALYSIS_COMPLETED,
        run_id=run_id,
        step_id=None,
        severity=Severity.INFO,
        message="Job description analysis completed",
        machine_state={"analysis_version": "jd-analysis-0.2", "analysis_source": analysis_source},
        ui_state={"current_step": "review"},
        payload={
            **analysis,
            "source_text_path": job_text_source_path,
            "jd_source": jd_source,
            **({"url": job_text_source_url} if job_text_source_url else {}),
        },
    ).emit()

    WorkerEvent(
        event_type=EventType.RESUME_TAILORING_STARTED,
        run_id=run_id,
        step_id=None,
        severity=Severity.INFO,
        message="Truthful resume tailoring plan started",
        machine_state={"profile_available": bool(canonical_profile), "output_dir": str(output_dir)},
        ui_state={"current_step": "tailoring_plan"},
        payload={},
    ).emit()

    tailoring_plan = TailoringEngine().build_plan(canonical_profile=canonical_profile, jd_analysis=analysis).to_dict()
    plan_path = work_dir / "tailoring-plan.json"
    plan_path.write_text(json.dumps(tailoring_plan, indent=2, sort_keys=True), encoding="utf-8")

    for answer in propose_profile_answers(canonical_profile):
        field_payload = {
            "field_label": answer.field_label,
            "field_type": answer.field_type,
            "confidence": answer.confidence,
            "source": answer.source,
            "requires_review": answer.requires_review,
        }
        WorkerEvent(
            event_type=EventType.FIELD_DETECTED,
            run_id=run_id,
            step_id=None,
            severity=Severity.INFO,
            message=f"Detected application field: {answer.field_label}",
            machine_state={},
            ui_state={"current_step": "field_review"},
            payload=field_payload,
        ).emit()
        WorkerEvent(
            event_type=EventType.FIELD_VALUE_PROPOSED,
            run_id=run_id,
            step_id=None,
            severity=Severity.WARN if answer.requires_review else Severity.INFO,
            message=f"Proposed answer for {answer.field_label}",
            machine_state={},
            ui_state={"current_step": "field_review", "requires_user_review": answer.requires_review},
            payload={**field_payload, "proposed_value": answer.proposed_value},
        ).emit()

    WorkerEvent(
        event_type=EventType.USER_REVIEW_REQUIRED,
        run_id=run_id,
        step_id=None,
        severity=Severity.WARN,
        message="Review truthful tailoring plan before document mutation",
        machine_state={"gate": "TAILORING_PLAN_REVIEW"},
        ui_state={"requires_user_review": True},
        payload={
            "cover_letter_required": analysis["cover_letter_likely_required"],
            "tailoring_plan_path": str(plan_path),
            "missing_keywords": tailoring_plan["missing_keywords"],
            "risky_claims_to_avoid": tailoring_plan["risky_claims_to_avoid"],
        },
    ).emit()

    profile = canonical_profile.get("profile") if isinstance(canonical_profile.get("profile"), dict) else {}
    first_name, last_name = split_legal_name(str(profile.get("legalName") or profile.get("displayName") or "Candidate Profile"))
    _url = str(job_metadata.get("url") or job_text_source_url or "")
    company = str(job_metadata.get("company") or _company_from_url(_url) or "Unknown Company")
    role = str(job_metadata.get("role") or _role_from_url(_url) or "Unknown Role")
    resume_content = build_resume_markdown(canonical_profile=canonical_profile, tailoring_plan=tailoring_plan)
    resume_report = TextArtifactValidator().validate(resume_content, artifact_kind="resume")
    validation_report_path = work_dir / "resume-validation-report.json"
    validation_report_path.write_text(json.dumps(resume_report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    if resume_report.passed:
        resume_artifact = write_text_artifact(
            output_dir=output_dir,
            filename_input=GeneratedNameInput(
                first_name=first_name,
                last_name=last_name,
                company=company,
                role=role,
                kind="Resume",
                extension="md",
            ),
            content=resume_content,
            file_kind="RESUME",
            extension="md",
            review_only=True,
        )
        WorkerEvent(
            event_type=EventType.RESUME_RENDERED,
            run_id=run_id,
            step_id=None,
            severity=Severity.INFO,
            message="Resume review artifact rendered to local filesystem",
            machine_state={"format": "MD", "review_only": True},
            ui_state={"current_step": "document_review"},
            payload={**resume_artifact.to_payload(), "validation_report_path": str(validation_report_path)},
        ).emit()
    else:
        WorkerEvent(
            event_type=EventType.VALIDATION_FAILED,
            run_id=run_id,
            step_id=None,
            severity=Severity.ERROR,
            message="Resume artifact failed deterministic validation",
            machine_state={"format": "MD", "review_only": True},
            ui_state={"current_step": "document_review", "requires_user_review": True},
            payload={"artifact_kind": "resume", "validation_report_path": str(validation_report_path), **resume_report.to_dict()},
        ).emit()

    editable_master = find_verified_resume_master(canonical_profile)
    if editable_master:
        master_path = Path(str(editable_master["localPath"]))
        master_format = str(editable_master["sourceFormat"])
        replacements = build_placeholder_replacements(canonical_profile=canonical_profile, tailoring_plan=tailoring_plan)
        if master_format == "DOCX":
            output_path = choose_collision_safe_path(
                output_dir,
                build_generated_filename(
                    GeneratedNameInput(
                        first_name=first_name,
                        last_name=last_name,
                        company=company,
                        role=role,
                        kind="Resume",
                        extension="docx",
                    )
                ),
            )
            _, replaced_placeholders = mutate_docx_placeholders(master_path, output_path, replacements)

            # Deep-tailor experience and project bullets via LLM if available
            llm_model = os.getenv("LITELLM_MODEL_STRONG") or os.getenv("LITELLM_MODEL")
            if llm_model and job_text:
                from .documents.font_detection import detect_resume_font_size
                detected_font_size = detect_resume_font_size(output_path) if output_path.exists() else 10
                try:
                    resume_text_for_tailor = extract_docx_text(output_path) if output_path.exists() else ""
                except Exception:
                    resume_text_for_tailor = ""
                if not resume_text_for_tailor:
                    resume_text_for_tailor = build_resume_markdown(canonical_profile=canonical_profile, tailoring_plan=tailoring_plan)
                tailored = asyncio.run(tailor_resume_sections(
                    job_description=job_text,
                    resume_text=resume_text_for_tailor,
                    llm_client=LiteLlmClient(model=llm_model),
                    font_size=detected_font_size,
                ))
                if tailored:
                    bullet_map: dict[str, list[str]] = {}
                    for i in range(4):
                        bullets = tailored.exp_bullets(i)
                        if bullets:
                            bullet_map[f"{{{{APPLYO_EXP_{i}_BULLETS}}}}"] = bullets
                    proj_bullets = tailored.all_project_bullets()
                    if proj_bullets:
                        bullet_map["{{APPLYO_PROJECTS_BULLETS}}"] = proj_bullets
                    # Validate LLM bullet content before writing to DOCX
                    if bullet_map:
                        bullet_text = "\n".join(b for bullets in bullet_map.values() for b in bullets)
                        bullet_report = TextArtifactValidator().validate(bullet_text, artifact_kind="resume")
                        if not bullet_report.passed:
                            # One retry with violation guidance appended to the job description
                            retry_tailored = asyncio.run(tailor_resume_sections(
                                job_description=_build_bullet_retry_jd(job_text, bullet_report),
                                resume_text=resume_text_for_tailor,
                                llm_client=LiteLlmClient(model=llm_model),
                                font_size=detected_font_size,
                            ))
                            if retry_tailored:
                                bullet_map = {}
                                for i in range(4):
                                    retry_bullets = retry_tailored.exp_bullets(i)
                                    if retry_bullets:
                                        bullet_map[f"{{{{APPLYO_EXP_{i}_BULLETS}}}}"] = retry_bullets
                                retry_proj_bullets = retry_tailored.all_project_bullets()
                                if retry_proj_bullets:
                                    bullet_map["{{APPLYO_PROJECTS_BULLETS}}"] = retry_proj_bullets
                                retry_bullet_text = "\n".join(b for bullets in bullet_map.values() for b in bullets)
                                bullet_report = TextArtifactValidator().validate(retry_bullet_text, artifact_kind="resume")
                            if not bullet_report.passed:
                                WorkerEvent(
                                    event_type=EventType.VALIDATION_FAILED,
                                    run_id=run_id,
                                    step_id=None,
                                    severity=Severity.WARN,
                                    message="LLM resume bullets failed validation after retry; skipping bullet mutation",
                                    machine_state={"format": "DOCX", "review_only": False},
                                    ui_state={"current_step": "document_review", "requires_user_review": True},
                                    payload={"artifact_kind": "resume", "stage": "llm_bullets", **bullet_report.to_dict()},
                                ).emit()
                                bullet_map = {}
                    if bullet_map:
                        _, bullet_replaced = mutate_docx_bullet_anchors(output_path, output_path, bullet_map)
                        replaced_placeholders = list(set(replaced_placeholders) | set(bullet_replaced))

            # Fall back to the auto-repaired anchored candidate if the master had no placeholders
            if not replaced_placeholders:
                anchored = find_anchored_resume_candidate(canonical_profile, master_path)
                if anchored:
                    _, replaced_placeholders = mutate_docx_placeholders(
                        Path(str(anchored["localPath"])), output_path, replacements
                    )

            # Final-file validation gate: catch any banned content in the mutated DOCX
            final_report = TextArtifactValidator().validate_file(output_path, artifact_kind="resume") if output_path.exists() else None
            if final_report is not None and not final_report.passed:
                WorkerEvent(
                    event_type=EventType.VALIDATION_FAILED,
                    run_id=run_id,
                    step_id=None,
                    severity=Severity.ERROR,
                    message="Mutated DOCX resume failed deterministic validation",
                    machine_state={"format": "DOCX", "review_only": False},
                    ui_state={"current_step": "document_review", "requires_user_review": True},
                    payload={"artifact_kind": "resume", "stage": "final_file", "generated_path": str(output_path), **final_report.to_dict()},
                ).emit()

            if replaced_placeholders:
                pdf_export = run_resume_render_tail(
                    run_id=run_id,
                    output_path=output_path,
                    output_dir=output_dir,
                    master_path=master_path,
                    replaced_placeholders=replaced_placeholders,
                    spec=RESUME_DOCX_TAIL,
                    exporter=export_docx_to_pdf,
                )
                if pdf_export.ok and pdf_export.pdf_path:
                    # One-page enforcement: count pages and retry with overflow instruction
                    from .documents.font_detection import count_pdf_pages
                    pages = count_pdf_pages(pdf_export.pdf_path)
                    if pages > 1 and llm_model and job_text:
                        overflow_tailored = asyncio.run(tailor_resume_sections(
                            job_description=_build_overflow_jd(job_text, pages),
                            resume_text=resume_text_for_tailor,
                            llm_client=LiteLlmClient(model=llm_model),
                            font_size=detected_font_size,
                        ))
                        if overflow_tailored:
                            overflow_bullet_map: dict[str, list[str]] = {}
                            for i in range(4):
                                ob = overflow_tailored.exp_bullets(i)
                                if ob:
                                    overflow_bullet_map[f"{{{{APPLYO_EXP_{i}_BULLETS}}}}"] = ob
                            overflow_proj = overflow_tailored.all_project_bullets()
                            if overflow_proj:
                                overflow_bullet_map["{{APPLYO_PROJECTS_BULLETS}}"] = overflow_proj
                            retry_export = _remutate_and_export(master_path, output_path, replacements, overflow_bullet_map, output_dir)
                            if retry_export.ok and retry_export.pdf_path:
                                pages = count_pdf_pages(retry_export.pdf_path)
                                pdf_export = retry_export
                    if pages > 1:
                        WorkerEvent(
                            event_type=EventType.VALIDATION_FAILED,
                            run_id=run_id,
                            step_id=None,
                            severity=Severity.WARN,
                            message="Tailored resume overflows one page",
                            machine_state={"format": "PDF", "pages": pages},
                            ui_state={"current_step": "document_review", "requires_user_review": True},
                            payload={
                                "artifact_kind": "resume",
                                "blocking_issues": [{"code": "RESUME_OVERFLOWS_ONE_PAGE"}],
                                "pages": pages,
                                "pdf_path": str(pdf_export.pdf_path),
                            },
                        ).emit()
            else:
                # Anchor-free fallback: build a fresh DOCX from canonical profile
                output_path.unlink(missing_ok=True)
                try:
                    from .documents.font_detection import detect_resume_font_size
                    fallback_font_size = detect_resume_font_size(master_path)
                    build_resume_docx(
                        canonical_profile=canonical_profile,
                        tailoring_plan=tailoring_plan,
                        output_path=output_path,
                        font_size=fallback_font_size,
                    )
                    fallback_artifact = metadata_for_existing_file(
                        path=output_path,
                        file_kind="RESUME",
                        format_name="DOCX",
                        review_only=True,
                    )
                    WorkerEvent(
                        event_type=EventType.RESUME_RENDERED,
                        run_id=run_id,
                        step_id=None,
                        severity=Severity.WARN,
                        message="Anchor-free DOCX fallback generated from canonical profile (no master anchors found)",
                        machine_state={"source_format": "DOCX", "fallback": True, "review_only": True},
                        ui_state={"current_step": "document_review", "requires_user_review": True},
                        payload=fallback_artifact.to_payload(),
                    ).emit()
                    fallback_pdf = export_docx_to_pdf(output_path, output_dir)
                    if fallback_pdf.ok and fallback_pdf.pdf_path:
                        fallback_pdf_artifact = metadata_for_existing_file(
                            path=fallback_pdf.pdf_path,
                            file_kind="RESUME",
                            format_name="PDF",
                            review_only=True,
                        )
                        WorkerEvent(
                            event_type=EventType.RESUME_RENDERED,
                            run_id=run_id,
                            step_id=None,
                            severity=Severity.WARN,
                            message="Anchor-free DOCX fallback exported to PDF",
                            machine_state={"format": "PDF", "fallback": True, "review_only": True},
                            ui_state={"current_step": "document_review", "requires_user_review": True},
                            payload=fallback_pdf_artifact.to_payload(),
                        ).emit()
                except Exception as _fallback_exc:
                    WorkerEvent(
                        event_type=EventType.USER_REVIEW_REQUIRED,
                        run_id=run_id,
                        step_id=None,
                        severity=Severity.WARN,
                        message="Verified DOCX master has no explicit Applyocalypse anchors for safe mutation",
                        machine_state={"source_format": "DOCX", "source_master_path": str(master_path)},
                        ui_state={"requires_user_review": True},
                        payload={"code": "MISSING_DOCX_ANCHORS", "source_master_path": str(master_path)},
                    ).emit()
        elif master_format == "TEX":
            output_path = choose_collision_safe_path(
                output_dir,
                build_generated_filename(
                    GeneratedNameInput(
                        first_name=first_name,
                        last_name=last_name,
                        company=company,
                        role=role,
                        kind="Resume",
                        extension="tex",
                    )
                ),
            )
            tex_replacements = {placeholder: tex_escape(replacement) for placeholder, replacement in replacements.items()}
            _, replaced_placeholders = mutate_tex_placeholders(master_path, output_path, tex_replacements)

            # Final-file validation gate: catch any banned content in the mutated TEX
            tex_final_report = TextArtifactValidator().validate_file(output_path, artifact_kind="resume") if output_path.exists() else None
            if tex_final_report is not None and not tex_final_report.passed:
                WorkerEvent(
                    event_type=EventType.VALIDATION_FAILED,
                    run_id=run_id,
                    step_id=None,
                    severity=Severity.ERROR,
                    message="Mutated TEX resume failed deterministic validation",
                    machine_state={"format": "TEX", "review_only": False},
                    ui_state={"current_step": "document_review", "requires_user_review": True},
                    payload={"artifact_kind": "resume", "stage": "final_file", "generated_path": str(output_path), **tex_final_report.to_dict()},
                ).emit()

            if replaced_placeholders:
                run_resume_render_tail(
                    run_id=run_id,
                    output_path=output_path,
                    output_dir=output_dir,
                    master_path=master_path,
                    replaced_placeholders=replaced_placeholders,
                    spec=RESUME_TEX_TAIL,
                    exporter=compile_tex_with_tectonic,
                )
            else:
                output_path.unlink(missing_ok=True)
                WorkerEvent(
                    event_type=EventType.USER_REVIEW_REQUIRED,
                    run_id=run_id,
                    step_id=None,
                    severity=Severity.WARN,
                    message="Verified TEX master has no explicit Applyocalypse anchors for safe mutation",
                    machine_state={"source_format": "TEX", "source_master_path": str(master_path)},
                    ui_state={"requires_user_review": True},
                    payload={"code": "MISSING_TEX_ANCHORS", "source_master_path": str(master_path)},
                ).emit()

    if analysis["cover_letter_likely_required"]:
        WorkerEvent(
            event_type=EventType.COVER_LETTER_REQUIRED,
            run_id=run_id,
            step_id=None,
            severity=Severity.INFO,
            message="Cover letter appears required by the job description",
            machine_state={"source": "JD_ANALYSIS"},
            ui_state={"current_step": "cover_letter"},
            payload={"required": True, "source": "JD_ANALYSIS"},
        ).emit()
        cl_llm_model = os.getenv("LITELLM_MODEL_STRONG") or os.getenv("LITELLM_MODEL")
        cover_letter_content: str | None = None
        cl_generation_mode = "DETERMINISTIC"
        if cl_llm_model and job_text:
            generated = asyncio.run(generate_cover_letter(
                job_description=job_text,
                canonical_profile=canonical_profile,
                cover_letter_sample=cover_letter_sample_text,
                llm_client=LiteLlmClient(model=cl_llm_model),
            ))
            if generated:
                cover_letter_content = generated.text
                cl_generation_mode = "LLM"
        if cover_letter_content is None:
            cover_letter_content = build_cover_letter_text(
                canonical_profile=canonical_profile,
                job_metadata=job_metadata,
                tailoring_plan=tailoring_plan,
            )
            cl_generation_mode = "DETERMINISTIC"

        if cover_letter_content:
            cover_letter_report = TextArtifactValidator().validate(cover_letter_content, artifact_kind="cover_letter")
            cover_letter_report_path = work_dir / "cover-letter-validation-report.json"
            cover_letter_report_path.write_text(json.dumps(cover_letter_report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
            if cover_letter_report.passed:
                cl_filename_input = GeneratedNameInput(
                    first_name=first_name,
                    last_name=last_name,
                    company=company,
                    role=role,
                    kind="Cover Letter",
                    extension="docx",
                )
                cl_filename = build_generated_filename(cl_filename_input)
                cl_docx_path = choose_collision_safe_path(output_dir, cl_filename)
                build_cover_letter_docx(cover_letter_content, canonical_profile, cl_docx_path)
                cover_letter_artifact = metadata_for_existing_file(
                    path=cl_docx_path,
                    file_kind="COVER_LETTER",
                    format_name="DOCX",
                    review_only=True,
                )
                WorkerEvent(
                    event_type=EventType.COVER_LETTER_RENDERED,
                    run_id=run_id,
                    step_id=None,
                    severity=Severity.INFO,
                    message="Cover letter review artifact rendered to local filesystem",
                    machine_state={"format": "DOCX", "review_only": True, "generation_mode": cl_generation_mode},
                    ui_state={"current_step": "document_review"},
                    payload={**cover_letter_artifact.to_payload(), "validation_report_path": str(cover_letter_report_path)},
                ).emit()
                pdf_export = export_docx_to_pdf(cl_docx_path, output_dir)
                if pdf_export.ok and pdf_export.pdf_path:
                    pdf_artifact = metadata_for_existing_file(
                        path=pdf_export.pdf_path,
                        file_kind="COVER_LETTER",
                        format_name="PDF",
                        review_only=True,
                    )
                    WorkerEvent(
                        event_type=EventType.COVER_LETTER_RENDERED,
                        run_id=run_id,
                        step_id=None,
                        severity=Severity.INFO,
                        message="Cover letter PDF exported",
                        machine_state={"format": "PDF", "review_only": True, "generation_mode": cl_generation_mode},
                        ui_state={"current_step": "document_review"},
                        payload={**pdf_artifact.to_payload(), "validation_report_path": str(cover_letter_report_path)},
                    ).emit()
            else:
                WorkerEvent(
                    event_type=EventType.VALIDATION_FAILED,
                    run_id=run_id,
                    step_id=None,
                    severity=Severity.ERROR,
                    message="Cover letter artifact failed validation",
                    machine_state={"format": "DOCX", "review_only": True, "generation_mode": cl_generation_mode},
                    ui_state={"current_step": "document_review", "requires_user_review": True},
                    payload={"artifact_kind": "cover_letter", "validation_report_path": str(cover_letter_report_path), **cover_letter_report.to_dict()},
                ).emit()
        else:
            WorkerEvent(
                event_type=EventType.VALIDATION_FAILED,
                run_id=run_id,
                step_id=None,
                severity=Severity.WARN,
                message="Cover letter requires more verified profile evidence before generation",
                machine_state={"reason": "INSUFFICIENT_VERIFIED_EVIDENCE"},
                ui_state={"current_step": "document_review", "requires_user_review": True},
                payload={"artifact_kind": "cover_letter", "blocking_issues": [{"code": "INSUFFICIENT_VERIFIED_EVIDENCE"}]},
            ).emit()
