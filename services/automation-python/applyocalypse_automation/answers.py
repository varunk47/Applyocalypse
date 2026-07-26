from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Standard "highest level of education" ladder; matched against resume degree text.
_EDUCATION_LEVELS: tuple[tuple[int, str, tuple[str, ...]], ...] = (
    (5, "Doctorate", ("phd", "ph.d", "doctor", "dphil")),
    (4, "Master's degree", ("master", "msc", "m.sc", "m.s.", "mba", "meng", "m.eng", "m.a.")),
    (3, "Bachelor's degree", ("bachelor", "bsc", "b.sc", "b.s.", "btech", "b.tech", "beng", "b.eng", "b.a.")),
    (2, "Associate degree", ("associate",)),
    (1, "High school or equivalent", ("high school", "ged", "secondary school")),
)

_SALARY_CONTEXT_HINTS = ("salary", "compensation", "pay", "remuneration", "annual", "per year", "base")

# "$80,000 - $100,000", "80k-100k", "80.000 to 100.000" (bare 4-digit years never match).
_SALARY_RANGE_PATTERN = re.compile(
    r"(?P<cur>[$€£])?\s*(?P<min>\d{1,3}(?:[,.]\d{3})+|\d{2,3})\s*(?P<mink>k)?\s*"
    r"(?:-|–|—|to)\s*"
    r"(?P<cur2>[$€£])?\s*(?P<max>\d{1,3}(?:[,.]\d{3})+|\d{2,3})\s*(?P<maxk>k)?",
    re.IGNORECASE,
)


def _salary_number(raw: str, k_scale: bool) -> int | None:
    digits = re.sub(r"[,.]", "", raw)
    if not digits.isdigit():
        return None
    value = int(digits)
    if k_scale and value < 1000:
        value *= 1000
    return value


def jd_salary_midpoint(jd_text: str | None) -> str | None:
    """Midpoint of the salary range advertised in the JD, formatted for a form answer."""
    if not jd_text:
        return None
    for match in _SALARY_RANGE_PATTERN.finditer(jd_text):
        has_currency = bool(match.group("cur") or match.group("cur2"))
        context = jd_text[max(0, match.start() - 80) : match.start()].lower()
        if not has_currency and not any(hint in context for hint in _SALARY_CONTEXT_HINTS):
            continue
        k_scale = bool(match.group("mink") or match.group("maxk"))
        low = _salary_number(match.group("min"), k_scale)
        high = _salary_number(match.group("max"), k_scale)
        if low is None or high is None or not 10000 <= low <= high <= 2000000:
            continue
        currency = match.group("cur") or match.group("cur2") or ""
        return f"{currency}{round((low + high) / 2):,}"
    return None


def _highest_education_level(canonical_profile: dict[str, Any]) -> str | None:
    entries = canonical_profile.get("education")
    if not isinstance(entries, list):
        return None
    best_rank = 0
    best_label: str | None = None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        degree = str(entry.get("degree") or "").lower()
        for rank, level_label, hints in _EDUCATION_LEVELS:
            if rank > best_rank and any(hint in degree for hint in hints):
                best_rank = rank
                best_label = level_label
                break
    return best_label


# Screening questions whose wrong answer commonly hard-rejects the application
# (knockout questions). Adapted from santifer/career-ops (MIT). Visa/sponsorship/
# work-authorization knockouts are handled by the dedicated work-auth branches.
_KNOCKOUT_KEYWORDS: tuple[str, ...] = (
    "years of experience",
    "how many years",
    "minimum experience",
    "salary expectation",
    "expected salary",
    "desired salary",
    "salary requirement",
    "compensation expectation",
    "willing to relocate",
    "relocation",
    "security clearance",
    "highest level of education",
    "degree required",
    "notice period",
    "driver's license",
    "driving license",
)


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
        ("Email", "applicationEmail"),
        ("Phone", "phone"),
        ("Location", "location"),
    ]:
        value = profile.get(key) or (profile.get("email") if key == "applicationEmail" else None)
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


def _eeo(profile: dict[str, Any]) -> dict[str, Any]:
    value = profile.get("equalEmploymentDefaults")
    return value if isinstance(value, dict) else {}


def _address(profile: dict[str, Any]) -> dict[str, Any]:
    value = profile.get("address")
    return value if isinstance(value, dict) else {}


_ADDRESS_RULES: list[tuple[tuple[str, ...], str]] = [
    (("country",), "country"),
    (("city", "municipality"), "city"),
    (("state", "province", "region"), "state"),
    (("address line 1", "street address", "address 1", "address1"), "addressLine1"),
    (("address line 2", "apt", "suite", "address 2", "address2"), "addressLine2"),
    (("zip", "postal", "post code", "postcode"), "postalCode"),
    (("county",), "county"),
]

_EEO_RULES: list[tuple[tuple[str, ...], str]] = [
    (("sexual orientation", "sexualorientation"), "sexualOrientation"),
    (("gender", "sex"), "gender"),
    (("disability", "disabled"), "disability"),
    (("veteran", "military service"), "veteran"),
    (("race",), "race"),
    (("ethnicity", "ethnic"), "race"),
    (("hispanic", "latino"), "hispanicOrLatino"),
    (("lgbtq",), "lgbtq"),
]


def propose_answer_for_detected_field(
    *,
    field_label: str,
    field_type: str,
    canonical_profile: dict[str, Any],
    autofill_approved_defaults: bool = False,
    jd_text: str | None = None,
) -> ProposedApplicationAnswer:
    profile = _profile(canonical_profile)
    label = field_label.lower()

    # ── First / last name ──────────────────────────────────────────────────────
    if any(kw in label for kw in ("first name", "given name", "firstname")):
        value = profile.get("firstName") or (
            profile.get("legalName", "").split(" ")[0] if profile.get("legalName") else None
        )
        return ProposedApplicationAnswer(
            field_label=field_label, field_type=field_type,
            proposed_value=str(value) if value else None,
            confidence=0.94 if value else 0.24, source="PROFILE" if value else "UNKNOWN",
            requires_review=not autofill_approved_defaults or not bool(value),
        )

    if any(kw in label for kw in ("last name", "family name", "surname", "lastname")):
        value = profile.get("lastName")
        if not value:
            legal = profile.get("legalName", "")
            parts = legal.split(" ", 1)
            value = parts[1] if len(parts) > 1 else None
        return ProposedApplicationAnswer(
            field_label=field_label, field_type=field_type,
            proposed_value=str(value) if value else None,
            confidence=0.94 if value else 0.24, source="PROFILE" if value else "UNKNOWN",
            requires_review=not autofill_approved_defaults or not bool(value),
        )

    # ── EEO fields — always requires_review (legal sensitivity) ──────────────────
    # Must come before address rules because "ethnicity" contains "city"
    eeo = _eeo(profile)
    for aliases, eeo_key in _EEO_RULES:
        if any(alias in label for alias in aliases):
            raw = eeo.get(eeo_key)
            if isinstance(raw, list):
                value = ", ".join(str(v) for v in raw) if raw else None
            else:
                value = str(raw) if raw is not None else None
            return ProposedApplicationAnswer(
                field_label=field_label, field_type=field_type,
                proposed_value=value,
                confidence=0.88 if value else 0.20, source="PROFILE" if value else "UNKNOWN",
                requires_review=True,
            )

    # ── Address fields ────────────────────────────────────────────────────────────
    address = _address(profile)
    for aliases, addr_key in _ADDRESS_RULES:
        if any(alias in label for alias in aliases):
            value = address.get(addr_key)
            return ProposedApplicationAnswer(
                field_label=field_label, field_type=field_type,
                proposed_value=str(value) if value else None,
                confidence=0.90 if value else 0.20, source="PROFILE" if value else "UNKNOWN",
                requires_review=not (autofill_approved_defaults and bool(value)),
            )

    # ── Previously employed / former employee ──────────────────────────────────
    if any(kw in label for kw in ("previously employed", "former employee", "worked for us", "worked here", "previously worked", "ever worked for", "employed by", "employed with")):
        return ProposedApplicationAnswer(
            field_label=field_label, field_type=field_type,
            proposed_value="No", confidence=0.90, source="PROFILE", requires_review=True,
        )

    # ── Criminal / background ──────────────────────────────────────────────────
    if any(kw in label for kw in ("criminal", "convicted", "felony", "misdemeanor")):
        return ProposedApplicationAnswer(
            field_label=field_label, field_type=field_type,
            proposed_value="No", confidence=0.90, source="PROFILE", requires_review=True,
        )

    # ── Knockout-class screening questions — proposed but always review-gated ──
    # A wrong answer here commonly triggers immediate automatic ATS rejection,
    # so a sensible default is proposed where one exists but is never auto-filled.
    if any(kw in label for kw in _KNOCKOUT_KEYWORDS):
        knockout_value: str | None = None
        knockout_source = "UNKNOWN"
        if any(kw in label for kw in ("salary", "compensation")):
            knockout_value = jd_salary_midpoint(jd_text)
            knockout_source = "JD_ANALYSIS" if knockout_value else "UNKNOWN"
        elif "security clearance" in label:
            knockout_value = "N/A"
            knockout_source = "PROFILE"
        elif "notice period" in label:
            knockout_value = "0"
            knockout_source = "PROFILE"
        elif any(kw in label for kw in ("highest level of education", "degree required")):
            knockout_value = _highest_education_level(canonical_profile)
            knockout_source = "PROFILE" if knockout_value else "UNKNOWN"
        return ProposedApplicationAnswer(
            field_label=field_label, field_type=field_type,
            proposed_value=knockout_value,
            confidence=0.55 if knockout_value else 0.2,
            source=knockout_source,
            requires_review=True,
        )

    # ── Standard profile candidates ────────────────────────────────────────────
    candidates: list[tuple[tuple[str, ...], str, float]] = [
        (("email", "e-mail", "login"), "applicationEmail", 0.96),
        (("phone", "mobile", "telephone"), "phone", 0.94),
        (("full name", "legal name", "name"), "legalName", 0.92),
        (("location",), "location", 0.78),
    ]
    for aliases, profile_key, confidence in candidates:
        if any(alias in label for alias in aliases):
            value = profile.get(profile_key) or (profile.get("email") if profile_key == "applicationEmail" else None)
            non_review_keys = {"applicationEmail", "phone", "legalName"}
            return ProposedApplicationAnswer(
                field_label=field_label, field_type=field_type,
                proposed_value=str(value) if value else None,
                confidence=confidence if value else 0.24,
                source="PROFILE" if value else "UNKNOWN",
                requires_review=not bool(value) or (
                    not (autofill_approved_defaults and profile_key in non_review_keys)
                    and profile_key not in non_review_keys
                ),
            )

    # ── LinkedIn / GitHub / portfolio ──────────────────────────────────────────
    if "linkedin" in label or "portfolio" in label or "github" in label or "website" in label:
        # Check convenience fields first
        if "linkedin" in label:
            direct = profile.get("linkedinUrl")
            if direct:
                return ProposedApplicationAnswer(
                    field_label=field_label, field_type=field_type,
                    proposed_value=str(direct), confidence=0.90, source="PROFILE",
                    requires_review=not autofill_approved_defaults,
                )
        if "github" in label:
            direct = profile.get("githubUrl")
            if direct:
                return ProposedApplicationAnswer(
                    field_label=field_label, field_type=field_type,
                    proposed_value=str(direct), confidence=0.90, source="PROFILE",
                    requires_review=not autofill_approved_defaults,
                )
        # Fall through to links[] lookup
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
            field_label=field_label, field_type=field_type,
            proposed_value=selected_url,
            confidence=0.86 if selected_url else 0.25,
            source="PROFILE" if selected_url else "UNKNOWN",
            requires_review=not (autofill_approved_defaults and bool(selected_url)),
        )

    # ── Work-auth: free-text sponsorship detail ────────────────────────────────
    if "authorization" in label or "sponsorship" in label or "visa" in label or "legally authorized" in label:
        eeo = _eeo(profile)
        detail_text = eeo.get("sponsorshipDetailText") if field_type in ("textarea", "text") else None
        if detail_text:
            return ProposedApplicationAnswer(
                field_label=field_label, field_type=field_type,
                proposed_value=str(detail_text), confidence=0.84, source="PROFILE",
                requires_review=True,
            )
        work_authorization = _work_authorization(profile)
        value = work_authorization.get("summary") or work_authorization.get("status")
        return ProposedApplicationAnswer(
            field_label=field_label, field_type=field_type,
            proposed_value=str(value) if value else None,
            confidence=0.82 if value else 0.18, source="PROFILE" if value else "UNKNOWN",
            requires_review=True,
        )

    # ── Salary / compensation ──────────────────────────────────────────────────
    if "salary" in label or "compensation" in label or "expected pay" in label:
        defaults = profile.get("jobDefaults") if isinstance(profile.get("jobDefaults"), dict) else {}
        value = defaults.get("salaryExpectation") or defaults.get("compensationExpectation")
        return ProposedApplicationAnswer(
            field_label=field_label, field_type=field_type,
            proposed_value=str(value) if value else None,
            confidence=0.72 if value else 0.16, source="PROFILE" if value else "UNKNOWN",
            requires_review=True,
        )

    return ProposedApplicationAnswer(
        field_label=field_label, field_type=field_type,
        proposed_value=None, confidence=0.12, source="UNKNOWN", requires_review=True,
    )
