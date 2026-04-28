from __future__ import annotations

from dataclasses import dataclass, asdict, field
import os
import re
from typing import Any

from .llm.litellm_client import LiteLlmClient


TECH_KEYWORDS = [
    "typescript",
    "javascript",
    "python",
    "react",
    "solidjs",
    "electron",
    "sqlite",
    "postgresql",
    "aws",
    "azure",
    "gcp",
    "docker",
    "kubernetes",
    "playwright",
    "llm",
    "machine learning",
    "security",
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


class JobDescriptionAnalyzer:
    def analyze(self, text: str) -> JobDescriptionAnalysis:
        normalized = " ".join(text.lower().split())
        must_have = self._extract_after_markers(normalized, ["required", "requirements", "must have"])
        preferred = self._extract_after_markers(normalized, ["preferred", "nice to have", "bonus"])
        tools = [keyword for keyword in TECH_KEYWORDS if keyword in normalized]

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
        matches = []
        for sentence in sentences:
            lower = sentence.lower()
            if any(needle in lower for needle in needles):
                matches.append(sentence.strip())
        return matches[:8]

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


JD_ANALYSIS_SYSTEM_PROMPT = """
You extract job-description requirements for a local-first job application copilot.
Return only truthful facts present in the job description.
Do not infer qualifications, sponsorship status, metrics, or experience that the text does not state.
Use concise arrays of strings and a boolean cover_letter_likely_required.
"""


def normalize_llm_analysis(raw: dict[str, Any], fallback: JobDescriptionAnalysis) -> JobDescriptionAnalysis:
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


async def analyze_with_optional_llm(text: str) -> tuple[JobDescriptionAnalysis, str]:
    fallback = JobDescriptionAnalyzer().analyze(text)
    model = os.getenv("LITELLM_MODEL")
    if not model:
        return fallback, "deterministic"

    try:
        raw = await LiteLlmClient(model=model).complete_json(
            system=JD_ANALYSIS_SYSTEM_PROMPT,
            user=text,
            schema_name="job_description_analysis",
        )
    except Exception:
        return fallback, "deterministic_fallback"

    return normalize_llm_analysis(raw, fallback), "litellm"
