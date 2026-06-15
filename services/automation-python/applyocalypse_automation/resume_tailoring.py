from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

_TAILOR_SYSTEM_PROMPT_TEMPLATE = """\
You are an ATS optimization expert tailoring a resume to one job description.

Step 1 - Gap analysis: list every keyword and skill in the job description that is
NOT already in the resume. Rank by importance to the role.

Step 2 - Rewrite: rework summary and bullets to naturally include the TOP 10 missing
keywords. Only claim what the candidate's evidence supports. If a keyword cannot be
truthfully claimed, put it in "unclaimable_keywords" instead of forcing it.

Length limits (font size {font_size}):
- One-line bullet: at most {one_line_limit} characters.
- Two-line bullet: at most {two_line_limit} characters.
- Limits apply to work experience and project bullets. They do NOT apply to the skills section.
- Tailored summary: max 235 characters.

Style: plain text, no markdown bold, no em dashes, no icons/tables. Avoid:
leverage, utilize, spearheaded, robust, comprehensive, seamless, transformative,
passionate, excited, thrilled, dynamic, innovative, holistic, empower, foster,
harness, deep dive.

Output JSON only:
{{
  "missing_keywords_ranked": ["..."],
  "unclaimable_keywords": ["..."],
  "summary": "...",
  "skills": ["..."],
  "work_experience": [{{"company": "...", "role": "...", "bullets": ["..."]}}],
  "projects": [{{"name": "...", "bullets": ["..."]}}]
}}
"""

_FONT_PARAMS: dict[int, dict[str, int]] = {
    10: {"one_line_limit": 125, "two_line_limit": 240},
    11: {"one_line_limit": 115, "two_line_limit": 220},
}

_REQUIRED_SECTION_KEYS = frozenset({"summary", "skills", "work_experience", "projects"})


def build_tailor_system_prompt(font_size: int = 10) -> str:
    params = _FONT_PARAMS.get(font_size, _FONT_PARAMS[10])
    return _TAILOR_SYSTEM_PROMPT_TEMPLATE.format(
        font_size=font_size,
        one_line_limit=params["one_line_limit"],
        two_line_limit=params["two_line_limit"],
    )


def _strip_code_fences(text: str) -> str:
    stripped = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.IGNORECASE)
    stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def _strip_markdown_bold(text: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"\1", text)


def _parse_json_response(raw: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    cleaned = _strip_code_fences(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise


def _validate_tailor_response(data: dict[str, Any]) -> bool:
    return _REQUIRED_SECTION_KEYS.issubset(data.keys())


def _clean_bullets(bullets: list[Any]) -> list[str]:
    return [_strip_markdown_bold(str(b).strip()) for b in bullets if str(b).strip()]


@dataclass(frozen=True, slots=True)
class TailoredResumeSections:
    summary: str
    skills: list[str]
    work_experience: list[dict[str, Any]]
    projects: list[dict[str, Any]]
    missing_keywords_ranked: list[str] = field(default_factory=list)
    unclaimable_keywords: list[str] = field(default_factory=list)

    def skills_text(self) -> str:
        return ", ".join(self.skills)

    def exp_bullets(self, index: int) -> list[str]:
        if index < len(self.work_experience):
            return _clean_bullets(self.work_experience[index].get("bullets") or [])
        return []

    def all_project_bullets(self) -> list[str]:
        bullets: list[str] = []
        for project in self.projects:
            name = str(project.get("name") or "").strip()
            for b in _clean_bullets(project.get("bullets") or []):
                bullets.append(f"{name}: {b}" if name else b)
        return bullets

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "skills": self.skills,
            "work_experience": self.work_experience,
            "projects": self.projects,
            "missing_keywords_ranked": self.missing_keywords_ranked,
            "unclaimable_keywords": self.unclaimable_keywords,
        }


async def tailor_resume_sections(
    *,
    job_description: str,
    resume_text: str,
    llm_client: Any,
    font_size: int = 10,
) -> TailoredResumeSections | None:
    """LLM-based resume tailoring with JSON validation and retry on malformed output."""
    system_prompt = build_tailor_system_prompt(font_size)
    user_message = f"JOB DESCRIPTION:\n{job_description}\n\n---\n\nCANDIDATE RESUME:\n{resume_text}"

    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            raw = await llm_client.complete_json(
                system=system_prompt,
                user=user_message,
                schema_name="TailoredResume",
            )
            data = _parse_json_response(raw)

            if not _validate_tailor_response(data):
                raise ValueError(f"Response missing required keys on attempt {attempt + 1}")

            summary = _strip_markdown_bold(str(data.get("summary") or ""))[:235]
            skills = [_strip_markdown_bold(str(s).strip()) for s in (data.get("skills") or []) if str(s).strip()]
            work_exp = [e for e in (data.get("work_experience") or []) if isinstance(e, dict)]
            projects = [p for p in (data.get("projects") or []) if isinstance(p, dict)]
            missing_kw = [str(k).strip() for k in (data.get("missing_keywords_ranked") or []) if str(k).strip()]
            unclaimable = [str(k).strip() for k in (data.get("unclaimable_keywords") or []) if str(k).strip()]

            return TailoredResumeSections(
                summary=summary,
                skills=skills,
                work_experience=work_exp,
                projects=projects,
                missing_keywords_ranked=missing_kw,
                unclaimable_keywords=unclaimable,
            )

        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            last_exc = exc
            user_message += "\n\nIMPORTANT: Return raw JSON only. No markdown fences. No bold markers."
            continue
        except Exception as exc:
            last_exc = exc
            break

    _ = last_exc  # logged upstream
    return None
