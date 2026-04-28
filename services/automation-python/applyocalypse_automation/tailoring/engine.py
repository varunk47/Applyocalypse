from __future__ import annotations

from dataclasses import dataclass, field
from dataclasses import asdict
import re
from typing import Any


@dataclass(frozen=True, slots=True)
class TailoringPlan:
    matched_evidence: list[dict[str, Any]]
    missing_keywords: list[str]
    truthful_additions: list[str]
    risky_claims_to_avoid: list[str]
    resume_bullet_plan: list[dict[str, Any]]
    cover_letter_required: bool
    one_page_plan: dict[str, Any] = field(default_factory=dict)
    cover_letter_evidence_points: list[dict[str, Any]] = field(default_factory=list)
    project_substitution_suggestions: list[dict[str, Any]] = field(default_factory=list)
    validation_requirements: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    source_type: str
    source_id: str | None
    label: str
    text: str
    bullets: list[str]
    tools: list[str]
    confidence: float
    source_rank: int


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip()


def _normalized_keywords(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    keywords: list[str] = []
    for value in values:
        keyword = re.sub(r"\s+", " ", str(value).strip())
        if not keyword:
            continue
        key = keyword.lower()
        if key not in seen:
            seen.add(key)
            keywords.append(keyword)
    return keywords


def _profile_rows(canonical_profile: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = canonical_profile.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _safe_confidence(value: Any) -> float:
    if isinstance(value, int | float):
        return max(0.0, min(1.0, float(value)))
    return 0.75


def _contains_keyword(text: str, keyword: str) -> bool:
    normalized_text = _normalize_text(text)
    normalized_keyword = _normalize_text(keyword)
    if not normalized_keyword:
        return False
    if len(normalized_keyword) <= 2:
        return bool(re.search(rf"\b{re.escape(normalized_keyword)}\b", normalized_text))
    return normalized_keyword in normalized_text


def _evidence_items(canonical_profile: dict[str, Any]) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []

    for entry in _profile_rows(canonical_profile, "experience"):
        title = str(entry.get("title") or "").strip()
        company = str(entry.get("company") or "").strip()
        label = " | ".join(part for part in [title, company] if part) or "Experience"
        bullets = _string_list(entry.get("bullets"))
        tools = _string_list(entry.get("tools"))
        text = " ".join([label, *bullets, *tools])
        items.append(
            EvidenceItem(
                source_type="experience",
                source_id=str(entry.get("id")) if entry.get("id") else None,
                label=label,
                text=text,
                bullets=bullets,
                tools=tools,
                confidence=_safe_confidence(entry.get("confidence")),
                source_rank=4,
            )
        )

    for project in _profile_rows(canonical_profile, "projects"):
        name = str(project.get("name") or "").strip() or "Project"
        summary = str(project.get("summary") or "").strip()
        bullets = _string_list(project.get("bullets"))
        tools = _string_list(project.get("tools"))
        text = " ".join([name, summary, *bullets, *tools])
        items.append(
            EvidenceItem(
                source_type="project",
                source_id=str(project.get("id")) if project.get("id") else None,
                label=name,
                text=text,
                bullets=bullets,
                tools=tools,
                confidence=_safe_confidence(project.get("confidence")),
                source_rank=3,
            )
        )

    for group in _profile_rows(canonical_profile, "skillGroups"):
        label = str(group.get("label") or "Skills").strip()
        skills = _string_list(group.get("skills"))
        items.append(
            EvidenceItem(
                source_type="skill_group",
                source_id=str(group.get("id")) if group.get("id") else None,
                label=label,
                text=" ".join([label, *skills]),
                bullets=[],
                tools=skills,
                confidence=_safe_confidence(group.get("confidence")),
                source_rank=2,
            )
        )

    for entry in _profile_rows(canonical_profile, "education"):
        institution = str(entry.get("institution") or "").strip()
        degree = str(entry.get("degree") or "").strip()
        field = str(entry.get("field") or "").strip()
        details = _string_list(entry.get("details"))
        label = " | ".join(part for part in [institution, degree, field] if part) or "Education"
        items.append(
            EvidenceItem(
                source_type="education",
                source_id=str(entry.get("id")) if entry.get("id") else None,
                label=label,
                text=" ".join([label, *details]),
                bullets=details,
                tools=[],
                confidence=_safe_confidence(entry.get("confidence")),
                source_rank=1,
            )
        )

    return items


def _score_evidence(item: EvidenceItem, keywords: list[str], keyword_weights: dict[str, int]) -> tuple[int, list[str]]:
    matched = [keyword for keyword in keywords if _contains_keyword(item.text, keyword)]
    score = sum(keyword_weights.get(keyword.lower(), 1) for keyword in matched)
    score += item.source_rank
    score += int(item.confidence * 10)
    if item.bullets:
        score += 3
    return score, matched


def _best_evidence_for_keyword(items: list[EvidenceItem], keyword: str, weights: dict[str, int]) -> EvidenceItem | None:
    candidates = [item for item in items if _contains_keyword(item.text, keyword)]
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: _score_evidence(item, [keyword], weights)[0], reverse=True)[0]


def _best_bullets(item: EvidenceItem, matched_keywords: list[str], limit: int = 3) -> list[str]:
    keyword_bullets = [
        bullet
        for bullet in item.bullets
        if any(_contains_keyword(bullet, keyword) for keyword in matched_keywords)
    ]
    fallback_bullets = [bullet for bullet in item.bullets if bullet not in keyword_bullets]
    return [*keyword_bullets, *fallback_bullets][:limit]


class TailoringEngine:
    def build_plan(self, *, canonical_profile: dict[str, Any], jd_analysis: dict[str, Any]) -> TailoringPlan:
        must_have = _normalized_keywords(list(jd_analysis.get("must_have_keywords", [])))
        preferred = _normalized_keywords(list(jd_analysis.get("preferred_keywords", [])))
        tools = _normalized_keywords(list(jd_analysis.get("tools_and_technologies", [])))
        keywords = _normalized_keywords([*must_have, *preferred, *tools])
        keyword_weights = {keyword.lower(): 3 for keyword in must_have}
        keyword_weights.update({keyword.lower(): 2 for keyword in preferred})
        keyword_weights.update({keyword.lower(): 2 for keyword in tools})
        evidence_items = _evidence_items(canonical_profile)

        matched: list[dict[str, Any]] = []
        missing: list[str] = []
        for keyword in keywords:
            item = _best_evidence_for_keyword(evidence_items, keyword, keyword_weights)
            if item is None:
                missing.append(keyword)
                continue
            matched.append(
                {
                    "keyword": keyword,
                    "source_type": item.source_type,
                    "source_id": item.source_id,
                    "evidence_label": item.label,
                    "evidence_text": item.text[:600],
                    "confidence": item.confidence,
                }
            )

        ranked_items: list[tuple[int, EvidenceItem, list[str]]] = []
        for item in evidence_items:
            score, matched_keywords = _score_evidence(item, keywords, keyword_weights)
            if matched_keywords:
                ranked_items.append((score, item, matched_keywords))
        ranked_items.sort(key=lambda value: value[0], reverse=True)

        resume_bullet_plan = [
            {
                "source_type": item.source_type,
                "source_id": item.source_id,
                "heading": item.label,
                "emphasize_keywords": matched_keywords,
                "keep_bullets": _best_bullets(item, matched_keywords),
                "rewrite_allowed": False,
                "reason": "Uses verified profile evidence only. Missing keywords are not inserted.",
            }
            for _, item, matched_keywords in ranked_items[:6]
            if item.bullets or item.source_type == "skill_group"
        ]

        truthful_additions = [
            f"Keep {match['keyword']} where it is already supported by {match['evidence_label']}."
            for match in matched
            if str(match["keyword"]).lower() not in {keyword.lower() for keyword in must_have}
        ][:8]

        project_substitution_suggestions = [
            {
                "project": item.label,
                "matched_keywords": matched_keywords,
                "reason": "Project has stronger verified JD overlap than lower-ranked profile material.",
            }
            for _, item, matched_keywords in ranked_items
            if item.source_type == "project"
        ][:3]

        cover_letter_evidence_points = [
            {
                "label": item.label,
                "source_type": item.source_type,
                "matched_keywords": matched_keywords,
                "evidence": (_best_bullets(item, matched_keywords, limit=1) or [item.text[:240]])[0],
            }
            for _, item, matched_keywords in ranked_items[:4]
        ]

        one_page_plan = {
            "target_pages": 1,
            "experience_limit": 4,
            "project_limit": 3 if project_substitution_suggestions else 2,
            "bullet_limit_per_role": 3,
            "skills_priority": [match["keyword"] for match in matched[:18]],
            "compression_notes": [
                "Prefer verified matching evidence over broad chronology.",
                "Remove weak bullets before shortening factual bullets.",
                "Keep unsupported missing keywords out of the rendered resume.",
            ],
        }

        return TailoringPlan(
            matched_evidence=matched,
            missing_keywords=missing,
            truthful_additions=truthful_additions,
            risky_claims_to_avoid=list(map(str, jd_analysis.get("risky_claims_to_avoid", []))),
            resume_bullet_plan=resume_bullet_plan,
            cover_letter_required=bool(jd_analysis.get("cover_letter_likely_required", False)),
            one_page_plan=one_page_plan,
            cover_letter_evidence_points=cover_letter_evidence_points,
            project_substitution_suggestions=project_substitution_suggestions,
            validation_requirements=[
                "No fabricated tools, metrics, responsibilities, dates, credentials, or work authorization claims.",
                "Run deterministic banned wording and formatting validation before accepting files.",
            ],
        )
