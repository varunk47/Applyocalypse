"""The user's job filters, checked once the job description is known.

Filters come from canonical-profile.json ("jobFilters": [{"kind", "value"}])
and decide whether a job is worth tailoring for at all. A filter only rules a
job out on evidence: a job with no advertised salary, no stated arrangement or
no location passes the matching filter. Saved addresses ("addresses") count as
allowed places and pick the address that goes on the job's forms.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .answers import jd_salary_range

ARRANGEMENTS: tuple[str, ...] = ("remote", "hybrid", "onsite")

# A location label is short and plain, so a bare word is enough there.
_LABEL_PATTERNS: dict[str, re.Pattern[str]] = {
    "remote": re.compile(r"\bremote\b", re.IGNORECASE),
    "hybrid": re.compile(r"\bhybrid\b", re.IGNORECASE),
    "onsite": re.compile(r"\bon[- ]?site\b|\bin[- ]office\b|\bin[- ]person\b", re.IGNORECASE),
}

# Descriptions say "remote collaboration" and "hybrid cloud", so only clear phrases count.
_DESCRIPTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "remote": re.compile(
        r"\b(?:fully|100%|completely|entirely) remote\b|\bremote[- ](?:first|only)\b"
        r"|\bremote (?:role|position|job|opportunity)\b|\bwork(?:ing)? from home\b",
        re.IGNORECASE,
    ),
    "hybrid": re.compile(
        r"\bhybrid(?:,| \(| (?:role|position|job|schedule|work|working|model|arrangement)\b)"
        r"|\b\d days? (?:a|per) week in (?:the )?office\b",
        re.IGNORECASE,
    ),
    "onsite": re.compile(
        r"\bon[- ]?site (?:in|at|role|position|job)\b|\bfully on[- ]?site\b|\bin[- ]office (?:role|position)\b",
        re.IGNORECASE,
    ),
}

_ADDRESS_KEYS: tuple[str, ...] = ("addressLine1", "addressLine2", "city", "state", "postalCode", "country")


@dataclass(frozen=True)
class FilterVerdict:
    passed: bool
    reasons: tuple[str, ...]


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _mentions(term: str, text: str) -> bool:
    """Whole-word, case-insensitive: "Meta" is not in "Metabase"."""
    return bool(term) and re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, re.IGNORECASE) is not None


def _found(patterns: dict[str, re.Pattern[str]], text: str) -> set[str]:
    return {name for name, pattern in patterns.items() if pattern.search(text)}


def detect_arrangements(description: str) -> set[str]:
    """Arrangements a job description states outright."""
    return _found(_DESCRIPTION_PATTERNS, description)


def _job_arrangements(job_metadata: dict[str, Any], jd_text: str) -> set[str]:
    from_label = _found(_LABEL_PATTERNS, _text(job_metadata.get("location")))
    return from_label or detect_arrangements(jd_text)


def _filter_values(profile: dict[str, Any], kind: str) -> list[str]:
    filters = profile.get("jobFilters")
    if not isinstance(filters, list):
        return []
    return [
        _text(item.get("value"))
        for item in filters
        if isinstance(item, dict) and item.get("kind") == kind and _text(item.get("value"))
    ]


def _saved_addresses(profile: dict[str, Any]) -> list[dict[str, Any]]:
    addresses = profile.get("addresses")
    return [item for item in addresses if isinstance(item, dict)] if isinstance(addresses, list) else []


def _allowed_places(profile: dict[str, Any], places: list[str]) -> list[str]:
    own = profile.get("address")
    cities = [_text(a.get("city")) for a in [*_saved_addresses(profile), own if isinstance(own, dict) else {}]]
    return [*places, *(city for city in cities if city)]


def evaluate_job_filters(profile: dict[str, Any], job_metadata: dict[str, Any], jd_text: str) -> FilterVerdict:
    """Every filter this job breaks, in words the user can read on the run."""
    company = _text(job_metadata.get("company"))
    role = _text(job_metadata.get("role"))
    location = _text(job_metadata.get("location"))
    reasons: list[str] = []

    for name in _filter_values(profile, "skip_company"):
        if _mentions(name, company):
            reasons.append(f"{company} is on your list of companies to skip.")

    for keyword in _filter_values(profile, "skip_keyword"):
        if _mentions(keyword, role) or _mentions(keyword, jd_text):
            reasons.append(f'The title or description mentions "{keyword}", which you asked to skip.')

    minimums = [int(value) for value in _filter_values(profile, "min_salary") if value.isdigit()]
    advertised = jd_salary_range(jd_text)
    if minimums and advertised is not None and advertised[1] < max(minimums):
        reasons.append(f"The advertised pay tops out at {advertised[1]:,}, below your minimum of {max(minimums):,}.")

    arrangements = _job_arrangements(job_metadata, jd_text)
    allowed = {value.lower() for value in _filter_values(profile, "work_arrangement")}
    if allowed and arrangements and not arrangements & allowed:
        wanted = " or ".join(a for a in ARRANGEMENTS if a in allowed)
        found = " and ".join(a for a in ARRANGEMENTS if a in arrangements)
        reasons.append(f"This job is {found}, and you only want {wanted} work.")

    places = _filter_values(profile, "place")
    if places and location and arrangements != {"remote"}:
        if not any(_mentions(place, location) for place in _allowed_places(profile, places)):
            reasons.append(f"{location} is not one of your places or near any of your addresses.")

    return FilterVerdict(passed=not reasons, reasons=tuple(reasons))


def address_for_job(addresses: list[dict[str, Any]], job_metadata: dict[str, Any]) -> dict[str, Any] | None:
    """The saved address in the job's city, if the job names one."""
    location = _text(job_metadata.get("location"))
    if not location:
        return None
    return next((a for a in addresses if _mentions(_text(a.get("city")), location)), None)


def with_job_address(profile: dict[str, Any], job_metadata: dict[str, Any]) -> dict[str, Any]:
    """A copy of the profile whose address is the saved one in the job's city, else the profile unchanged."""
    chosen = address_for_job(_saved_addresses(profile), job_metadata)
    if chosen is None:
        return profile
    return {**profile, "address": {key: _text(chosen.get(key)) for key in _ADDRESS_KEYS}}
