from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ProposedApplicationAnswer:
    field_label: str
    field_type: str
    proposed_value: str | None
    confidence: float
    source: str
    requires_review: bool


def propose_profile_answers(canonical_profile: dict[str, Any]) -> list[ProposedApplicationAnswer]:
    profile = canonical_profile.get("profile") if isinstance(canonical_profile.get("profile"), dict) else {}
    if not isinstance(profile, dict):
        profile = {}

    work_authorization = profile.get("workAuthorization") if isinstance(profile.get("workAuthorization"), dict) else {}
    answers: list[ProposedApplicationAnswer] = []

    for label, key in [
        ("Legal name", "legalName"),
        ("Email", "email"),
        ("Phone", "phone"),
        ("Location", "location"),
    ]:
        value = profile.get(key)
        if value:
            answers.append(
                ProposedApplicationAnswer(
                    field_label=label,
                    field_type="text",
                    proposed_value=str(value),
                    confidence=0.96,
                    source="PROFILE",
                    requires_review=False,
                )
            )

    if work_authorization:
        work_auth_value = work_authorization.get("summary") or work_authorization.get("status")
        confidence = 0.86 if work_auth_value else 0.5
        answers.append(
            ProposedApplicationAnswer(
                field_label="Work authorization",
                field_type="text",
                proposed_value=str(work_auth_value) if work_auth_value else None,
                confidence=confidence,
                source="PROFILE",
                requires_review=True,
            )
        )
    else:
        answers.append(
            ProposedApplicationAnswer(
                field_label="Work authorization",
                field_type="text",
                proposed_value=None,
                confidence=0.2,
                source="UNKNOWN",
                requires_review=True,
            )
        )

    return answers


def _profile(canonical_profile: dict[str, Any]) -> dict[str, Any]:
    profile = canonical_profile.get("profile")
    return profile if isinstance(profile, dict) else {}


def _work_authorization(profile: dict[str, Any]) -> dict[str, Any]:
    value = profile.get("workAuthorization")
    return value if isinstance(value, dict) else {}


def propose_answer_for_detected_field(
    *,
    field_label: str,
    field_type: str,
    canonical_profile: dict[str, Any],
) -> ProposedApplicationAnswer:
    profile = _profile(canonical_profile)
    label = field_label.lower()

    candidates: list[tuple[tuple[str, ...], str, float]] = [
        (("email", "e-mail"), "email", 0.96),
        (("phone", "mobile", "telephone"), "phone", 0.94),
        (("full name", "legal name", "name"), "legalName", 0.92),
        (("location", "city", "address"), "location", 0.78),
    ]
    for aliases, profile_key, confidence in candidates:
        if any(alias in label for alias in aliases):
            value = profile.get(profile_key)
            return ProposedApplicationAnswer(
                field_label=field_label,
                field_type=field_type,
                proposed_value=str(value) if value else None,
                confidence=confidence if value else 0.24,
                source="PROFILE" if value else "UNKNOWN",
                requires_review=not bool(value) or profile_key in {"location"},
            )

    if "linkedin" in label or "portfolio" in label or "github" in label or "website" in label:
        links = profile.get("links") if isinstance(profile.get("links"), list) else []
        selected_url: str | None = None
        for link in links:
            if not isinstance(link, dict):
                continue
            url = str(link.get("url") or "")
            link_label = str(link.get("label") or "").lower()
            if ("linkedin" in label and "linkedin" in url.lower()) or ("github" in label and "github" in url.lower()):
                selected_url = url
                break
            if not selected_url and (link_label in label or "portfolio" in label or "website" in label):
                selected_url = url
        return ProposedApplicationAnswer(
            field_label=field_label,
            field_type=field_type,
            proposed_value=selected_url,
            confidence=0.86 if selected_url else 0.25,
            source="PROFILE" if selected_url else "UNKNOWN",
            requires_review=not bool(selected_url),
        )

    if "authorization" in label or "sponsorship" in label or "visa" in label or "legally authorized" in label:
        work_authorization = _work_authorization(profile)
        value = work_authorization.get("summary") or work_authorization.get("status")
        return ProposedApplicationAnswer(
            field_label=field_label,
            field_type=field_type,
            proposed_value=str(value) if value else None,
            confidence=0.82 if value else 0.18,
            source="PROFILE" if value else "UNKNOWN",
            requires_review=True,
        )

    if "salary" in label or "compensation" in label or "expected pay" in label:
        defaults = profile.get("jobDefaults") if isinstance(profile.get("jobDefaults"), dict) else {}
        value = defaults.get("salaryExpectation") or defaults.get("compensationExpectation")
        return ProposedApplicationAnswer(
            field_label=field_label,
            field_type=field_type,
            proposed_value=str(value) if value else None,
            confidence=0.72 if value else 0.16,
            source="PROFILE" if value else "UNKNOWN",
            requires_review=True,
        )

    return ProposedApplicationAnswer(
        field_label=field_label,
        field_type=field_type,
        proposed_value=None,
        confidence=0.12,
        source="UNKNOWN",
        requires_review=True,
    )
