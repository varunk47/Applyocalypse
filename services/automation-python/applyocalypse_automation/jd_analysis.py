from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .llm.litellm_client import LiteLlmClient

# Fallback enrichment keywords only — not the primary detection method
_FALLBACK_TECH_KEYWORDS = [
    "typescript", "javascript", "python", "react", "solidjs", "electron",
    "sqlite", "postgresql", "aws", "azure", "gcp", "docker", "kubernetes",
    "playwright", "llm", "machine learning", "security",
]


@dataclass(frozen=True, slots=True)
class JobDescriptionAnalysis:
    must_have_keywords: list[str]
    preferred_keywords: list[str]
    hard_requirements: list[str]
    tools_and_technologies: list[str]
    domain_signals: list[str]
    location_signals: list[str]
    work_authorization_signals: list[str]
    seniority_cues: list[str]
    communication_cues: list[str]
    required_materials: list[str]
    cover_letter_likely_required: bool
    risky_claims_to_avoid: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


JD_ANALYSIS_SYSTEM_PROMPT = """You extract job-description requirements for a local-first job application copilot.

Return a JSON object with EXACTLY these keys:
- must_have_keywords: string[] — required skills/qualifications explicitly stated
- preferred_keywords: string[] — nice-to-have or bonus qualifications
- hard_requirements: string[] — sentences stating mandatory requirements
- tools_and_technologies: string[] — technologies, frameworks, platforms mentioned
- domain_signals: string[] — industry/domain context sentences
- location_signals: string[] — remote/hybrid/onsite/relocation sentences
- work_authorization_signals: string[] — visa/sponsorship/citizenship sentences
- seniority_cues: string[] — experience level indicators
- communication_cues: string[] — collaboration/communication requirement sentences
- required_materials: string[] — application materials needed (resume, cover_letter, portfolio, references)
- cover_letter_likely_required: boolean
- risky_claims_to_avoid: string[] — specific claims a candidate might be tempted to fabricate that
  are not supported by a generic background (e.g. "10+ years with X", "led team of 50+",
  "built system handling 1B requests/day"). Flag only claims that appear in this JD and would
  be difficult to defend without direct evidence.

Return only truthful facts present in the job description. Output raw JSON only — no markdown fences."""


def _strip_code_fences(text: str) -> str:
    stripped = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.IGNORECASE)
    stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def _parse_llm_json(raw: str) -> dict[str, Any]:
    cleaned = _strip_code_fences(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise


_REQUIRED_KEYS = frozenset({
    "must_have_keywords", "preferred_keywords", "hard_requirements",
    "tools_and_technologies", "domain_signals", "location_signals",
    "work_authorization_signals", "seniority_cues", "communication_cues",
    "required_materials", "cover_letter_likely_required", "risky_claims_to_avoid",
})


def _validate_llm_response(data: dict[str, Any]) -> bool:
    return _REQUIRED_KEYS.issubset(data.keys())


def _normalize_llm_analysis(raw: dict[str, Any], fallback: JobDescriptionAnalysis) -> JobDescriptionAnalysis:
    fallback_dict = fallback.to_dict()

    def list_value(key: str) -> list[str]:
        value = raw.get(key, fallback_dict[key])
        if not isinstance(value, list):
            return list(fallback_dict[key])  # type: ignore[arg-type]
        return [str(item).strip() for item in value if str(item).strip()][:24]

    return JobDescriptionAnalysis(
        must_have_keywords=list_value("must_have_keywords"),
        preferred_keywords=list_value("preferred_keywords"),
        hard_requirements=list_value("hard_requirements"),
        tools_and_technologies=list_value("tools_and_technologies"),
        domain_signals=list_value("domain_signals"),
        location_signals=list_value("location_signals"),
        work_authorization_signals=list_value("work_authorization_signals"),
        seniority_cues=list_value("seniority_cues"),
        communication_cues=list_value("communication_cues"),
        required_materials=list_value("required_materials"),
        cover_letter_likely_required=bool(raw.get("cover_letter_likely_required", fallback.cover_letter_likely_required)),
        risky_claims_to_avoid=list_value("risky_claims_to_avoid"),
    )


class JobDescriptionAnalyzer:
    """Regex-only fallback analyzer. Used when LLM is unavailable or fails."""

    def analyze(self, text: str) -> JobDescriptionAnalysis:
        normalized = " ".join(text.lower().split())
        must_have = self._extract_after_markers(normalized, ["required", "requirements", "must have"])
        preferred = self._extract_after_markers(normalized, ["preferred", "nice to have", "bonus"])
        tools = [kw for kw in _FALLBACK_TECH_KEYWORDS if kw in normalized]

        return JobDescriptionAnalysis(
            must_have_keywords=sorted(set(must_have + tools[:6])),
            preferred_keywords=sorted(set(preferred)),
            hard_requirements=self._sentences_matching(text, ["required", "must", "minimum"]),
            tools_and_technologies=tools,
            domain_signals=self._sentences_matching(text, ["fintech", "healthcare", "security", "ai", "data", "developer tools"]),
            location_signals=self._sentences_matching(text, ["remote", "hybrid", "onsite", "relocation"]),
            work_authorization_signals=self._sentences_matching(text, ["sponsorship", "work authorization", "citizen", "visa"]),
            seniority_cues=self._sentences_matching(text, ["senior", "staff", "principal", "lead", "manager"]),
            communication_cues=self._sentences_matching(text, ["stakeholder", "written", "communication", "cross-functional"]),
            required_materials=self._required_materials(normalized),
            cover_letter_likely_required="cover letter" in normalized,
            risky_claims_to_avoid=[],
        )

    @staticmethod
    def _extract_after_markers(text: str, markers: list[str]) -> list[str]:
        values: list[str] = []
        for marker in markers:
            for match in re.finditer(rf"{re.escape(marker)}[:\s]+([^.;\n]+)", text):
                values.extend(part.strip(" -") for part in re.split(r",|/|\band\b", match.group(1)) if part.strip())
        return values[:12]

    @staticmethod
    def _sentences_matching(text: str, needles: list[str]) -> list[str]:
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        return [s.strip() for s in sentences if any(n in s.lower() for n in needles)][:8]

    @staticmethod
    def _required_materials(text: str) -> list[str]:
        materials = ["resume"]
        if "cover letter" in text:
            materials.append("cover_letter")
        if "portfolio" in text:
            materials.append("portfolio")
        if "references" in text:
            materials.append("references")
        return materials


# Public alias for backwards compatibility with existing tests
normalize_llm_analysis = _normalize_llm_analysis


async def analyze_with_optional_llm(
    text: str,
    client: LiteLlmClient | None = None,
) -> tuple[JobDescriptionAnalysis, str]:
    """LLM is the primary path. Falls back to regex only on failure."""
    regex_fallback = JobDescriptionAnalyzer().analyze(text)

    model = os.getenv("LITELLM_MODEL_FAST") or os.getenv("LITELLM_MODEL")
    llm = client or (LiteLlmClient(model=model) if model else None)
    if not llm:
        return regex_fallback, "deterministic"

    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            raw_text = await llm.complete_json(
                system=JD_ANALYSIS_SYSTEM_PROMPT,
                user=text,
                schema_name="job_description_analysis",
            )
            if isinstance(raw_text, str):
                data = _parse_llm_json(raw_text)
            else:
                data = raw_text  # type: ignore[assignment]

            if not _validate_llm_response(data):
                raise ValueError(f"LLM response missing required keys on attempt {attempt + 1}")

            return _normalize_llm_analysis(data, regex_fallback), "litellm"

        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            last_exc = exc
            continue
        except Exception as exc:
            last_exc = exc
            break

    _ = last_exc  # logged upstream via runner
    return regex_fallback, "deterministic_fallback"
