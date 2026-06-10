from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
from typing import Any

from .file_generation import GeneratedNameInput, build_generated_filename, choose_collision_safe_path


@dataclass(frozen=True, slots=True)
class ArtifactMetadata:
    file_kind: str
    format: str
    filename: str
    local_path: str
    sha256: str
    size_bytes: int
    retention_policy: str
    delete_after: str
    review_only: bool

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


def split_legal_name(legal_name: str) -> tuple[str, str]:
    parts = [part for part in legal_name.strip().split() if part]
    if not parts:
        return ("Candidate", "Profile")
    if len(parts) == 1:
        return (parts[0], "Profile")
    return (parts[0], " ".join(parts[1:]))


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _profile_section(canonical_profile: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = canonical_profile.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _tailoring_plan_items(tailoring_plan: dict[str, Any]) -> list[dict[str, Any]]:
    value = tailoring_plan.get("resume_bullet_plan")
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _entry_heading(entry: dict[str, Any], kind: str) -> str:
    if kind == "experience":
        title = str(entry.get("title") or "").strip()
        company = str(entry.get("company") or "").strip()
        return " | ".join(part for part in [title, company] if part)
    return str(entry.get("name") or "").strip()


def _plan_for_entry(entry: dict[str, Any], kind: str, tailoring_plan: dict[str, Any]) -> dict[str, Any] | None:
    heading = _entry_heading(entry, kind)
    entry_id = str(entry.get("id")) if entry.get("id") else None
    for item in _tailoring_plan_items(tailoring_plan):
        if item.get("source_type") != kind:
            continue
        if entry_id and item.get("source_id") == entry_id:
            return item
        if heading and item.get("heading") == heading:
            return item
    return None


def _ordered_entries(entries: list[dict[str, Any]], kind: str, tailoring_plan: dict[str, Any]) -> list[dict[str, Any]]:
    plan_items = _tailoring_plan_items(tailoring_plan)
    plan_order: dict[str, int] = {}
    for index, item in enumerate(plan_items):
        if item.get("source_type") != kind:
            continue
        source_id = str(item.get("source_id")) if item.get("source_id") else ""
        heading = str(item.get("heading") or "")
        if source_id:
            plan_order[source_id] = index
        if heading:
            plan_order[heading] = index

    def sort_key(entry: dict[str, Any]) -> tuple[int, int]:
        entry_id = str(entry.get("id")) if entry.get("id") else ""
        heading = _entry_heading(entry, kind)
        if entry_id in plan_order:
            return (0, plan_order[entry_id])
        if heading in plan_order:
            return (0, plan_order[heading])
        return (1, entries.index(entry))

    return sorted(entries, key=sort_key)


def _planned_bullets(entry: dict[str, Any], kind: str, tailoring_plan: dict[str, Any], limit: int) -> list[str]:
    plan = _plan_for_entry(entry, kind, tailoring_plan)
    planned = _string_list(plan.get("keep_bullets") if plan else None)
    original = _string_list(entry.get("bullets"))
    if planned:
        remaining = [bullet for bullet in original if bullet not in planned]
        return [*planned, *remaining][:limit]
    return original[:limit]


def find_anchored_resume_candidate(canonical_profile: dict[str, Any], master_path: Path) -> dict[str, Any] | None:
    """Return an auto-repaired anchored RESUME file derived from master_path, if one exists.

    The anchor-repair pipeline names repaired files with 'Anchored' in originalName.
    """
    uploaded_files = canonical_profile.get("uploadedFiles")
    if not isinstance(uploaded_files, list):
        return None
    master_local = str(master_path)
    master_id: str | None = None
    for f in uploaded_files:
        if isinstance(f, dict) and f.get("localPath") == master_local:
            master_id = f.get("id")
            break
    for f in uploaded_files:
        if not isinstance(f, dict):
            continue
        if (
            f.get("fileKind") == "RESUME"
            and f.get("sourceFormat") == "DOCX"
            and f.get("status") not in {"REJECTED", "DELETED"}
            and f.get("id") != master_id
            and "Anchored" in str(f.get("originalName", ""))
            and f.get("localPath")
        ):
            return f
    return None


def find_verified_resume_master(canonical_profile: dict[str, Any]) -> dict[str, Any] | None:
    uploaded_files = canonical_profile.get("uploadedFiles")
    if not isinstance(uploaded_files, list):
        return None
    for uploaded_file in uploaded_files:
        if not isinstance(uploaded_file, dict):
            continue
        if (
            uploaded_file.get("fileKind") == "RESUME"
            and uploaded_file.get("status") == "VERIFIED_EDITABLE_MASTER"
            and uploaded_file.get("sourceFormat") in {"DOCX", "TEX"}
            and uploaded_file.get("localPath")
        ):
            return uploaded_file
    return None


def build_placeholder_replacements(*, canonical_profile: dict[str, Any], tailoring_plan: dict[str, Any]) -> dict[str, str]:
    profile = canonical_profile.get("profile") if isinstance(canonical_profile.get("profile"), dict) else {}
    summary_keywords = [
        str(item.get("keyword")).strip()
        for item in tailoring_plan.get("matched_evidence", [])
        if isinstance(item, dict) and str(item.get("keyword", "")).strip()
    ][:5]
    summary = "Truthful profile evidence prepared for this role."
    if summary_keywords:
        summary = f"Verified evidence aligns with {', '.join(summary_keywords)}."

    skill_groups = _profile_section(canonical_profile, "skillGroups")
    skills: list[str] = []
    for group in skill_groups:
        skills.extend(_string_list(group.get("skills")))

    return {
        "{{APPLYO_FULL_NAME}}": str(profile.get("legalName") or profile.get("displayName") or "Candidate Profile"),
        "{{APPLYO_RESUME_SUMMARY}}": summary,
        "{{APPLYO_SKILLS}}": ", ".join(skills[:36]),
    }


def build_resume_markdown(*, canonical_profile: dict[str, Any], tailoring_plan: dict[str, Any]) -> str:
    profile = canonical_profile.get("profile") if isinstance(canonical_profile.get("profile"), dict) else {}
    legal_name = str(profile.get("legalName") or profile.get("displayName") or "Candidate Profile")
    contact = [str(profile.get(key)).strip() for key in ["email", "phone", "location"] if profile.get(key)]
    one_page_plan = tailoring_plan.get("one_page_plan") if isinstance(tailoring_plan.get("one_page_plan"), dict) else {}
    bullet_limit = int(one_page_plan.get("bullet_limit_per_role", 3)) if isinstance(one_page_plan.get("bullet_limit_per_role"), int) else 3
    experience_limit = int(one_page_plan.get("experience_limit", 4)) if isinstance(one_page_plan.get("experience_limit"), int) else 4
    project_limit = int(one_page_plan.get("project_limit", 3)) if isinstance(one_page_plan.get("project_limit"), int) else 3
    lines = [f"# {legal_name}", ""]
    if contact:
        lines.extend([" | ".join(contact), ""])

    matched_keywords = [
        str(item.get("keyword")).strip()
        for item in tailoring_plan.get("matched_evidence", [])
        if isinstance(item, dict) and str(item.get("keyword", "")).strip()
    ]
    skill_groups = _profile_section(canonical_profile, "skillGroups")
    skills: list[str] = []
    for group in skill_groups:
        skills.extend(_string_list(group.get("skills")))
    skills_priority = _string_list(one_page_plan.get("skills_priority"))
    ordered_skills = [
        skill
        for priority in skills_priority
        for skill in skills
        if skill.lower() == priority.lower()
    ]
    ordered_skills.extend([skill for skill in skills if skill.lower() in {keyword.lower() for keyword in matched_keywords} and skill not in ordered_skills])
    ordered_skills.extend([skill for skill in skills if skill not in ordered_skills])
    if ordered_skills:
        lines.extend(["## Skills", ", ".join(ordered_skills[:36]), ""])

    experience = _ordered_entries(_profile_section(canonical_profile, "experience"), "experience", tailoring_plan)
    if experience:
        lines.extend(["## Experience"])
        for entry in experience[:experience_limit]:
            title = str(entry.get("title") or "").strip()
            company = str(entry.get("company") or "").strip()
            heading = " | ".join(part for part in [title, company] if part)
            if heading:
                lines.append(f"### {heading}")
            for bullet in _planned_bullets(entry, "experience", tailoring_plan, bullet_limit):
                lines.append(f"- {bullet}")
            lines.append("")

    projects = _ordered_entries(_profile_section(canonical_profile, "projects"), "project", tailoring_plan)
    if projects:
        lines.extend(["## Projects"])
        for project in projects[:project_limit]:
            name = str(project.get("name") or "").strip()
            if name:
                lines.append(f"### {name}")
            summary = str(project.get("summary") or "").strip()
            if summary:
                lines.append(summary)
            for bullet in _planned_bullets(project, "project", tailoring_plan, bullet_limit):
                lines.append(f"- {bullet}")
            lines.append("")

    education = _profile_section(canonical_profile, "education")
    if education:
        lines.extend(["## Education"])
        for entry in education[:3]:
            institution = str(entry.get("institution") or "").strip()
            degree = str(entry.get("degree") or "").strip()
            field = str(entry.get("field") or "").strip()
            line = " | ".join(part for part in [institution, degree, field] if part)
            if line:
                lines.append(line)
        lines.append("")

    missing = _string_list(tailoring_plan.get("missing_keywords"))
    if missing:
        lines.extend(["## Review Notes", "Missing keywords were not added because verified evidence was not found:", ", ".join(missing), ""])

    return "\n".join(lines).strip() + "\n"


def build_cover_letter_text(*, canonical_profile: dict[str, Any], job_metadata: dict[str, Any], tailoring_plan: dict[str, Any]) -> str | None:
    profile = canonical_profile.get("profile") if isinstance(canonical_profile.get("profile"), dict) else {}
    legal_name = str(profile.get("legalName") or profile.get("displayName") or "").strip()
    experience = _profile_section(canonical_profile, "experience")
    projects = _profile_section(canonical_profile, "projects")
    evidence_source = experience[0] if experience else (projects[0] if projects else None)
    if not legal_name or not evidence_source:
        return None

    role = str(job_metadata.get("role") or "the role").strip()
    company = str(job_metadata.get("company") or "your team").strip()
    evidence_title = str(evidence_source.get("title") or evidence_source.get("name") or "verified engineering work").strip()
    bullets = _string_list(evidence_source.get("bullets"))
    evidence_sentence = bullets[0] if bullets else f"My closest verified evidence is {evidence_title}."
    matched = [
        str(item.get("keyword")).strip()
        for item in tailoring_plan.get("matched_evidence", [])
        if isinstance(item, dict) and str(item.get("keyword", "")).strip()
    ][:4]
    keyword_sentence = f"The strongest verified overlap is {', '.join(matched)}." if matched else "I only want to use claims that are already verified in my profile."

    return (
        f"Dear Hiring Team,\n\n"
        f"{company}'s {role} work maps to my verified background in {evidence_title}. "
        f"{evidence_sentence} {keyword_sentence}\n\n"
        "I would bring a careful engineering style, clear judgment around tradeoffs, and a bias toward systems that operators can inspect and control.\n\n"
        f"Thank you,\n{legal_name}\n"
    )


def write_text_artifact(
    *,
    output_dir: Path,
    filename_input: GeneratedNameInput,
    content: str,
    file_kind: str,
    extension: str,
    review_only: bool,
) -> ArtifactMetadata:
    filename = build_generated_filename(filename_input)
    local_path = choose_collision_safe_path(output_dir, filename)
    local_path.write_text(content, encoding="utf-8")
    raw = local_path.read_bytes()
    delete_after = datetime.now(timezone.utc) + timedelta(days=14)
    return ArtifactMetadata(
        file_kind=file_kind,
        format=extension.strip(".").upper(),
        filename=local_path.name,
        local_path=str(local_path),
        sha256=hashlib.sha256(raw).hexdigest(),
        size_bytes=len(raw),
        retention_policy="DELETE_AFTER_RETENTION",
        delete_after=delete_after.isoformat().replace("+00:00", "Z"),
        review_only=review_only,
    )


def metadata_for_existing_file(*, path: Path, file_kind: str, format_name: str, review_only: bool) -> ArtifactMetadata:
    raw = path.read_bytes()
    delete_after = datetime.now(timezone.utc) + timedelta(days=14)
    return ArtifactMetadata(
        file_kind=file_kind,
        format=format_name,
        filename=path.name,
        local_path=str(path),
        sha256=hashlib.sha256(raw).hexdigest(),
        size_bytes=len(raw),
        retention_policy="DELETE_AFTER_RETENTION",
        delete_after=delete_after.isoformat().replace("+00:00", "Z"),
        review_only=review_only,
    )
