"""The user's own answers, chosen per job at fill time.

A rule pairs a question phrase with an answer and, optionally, conditions on the
job ("location": "GA", "company": "Bank of America", "portal": "workday"). Rules
arrive in canonical-profile.json as ``preferenceRules`` and the job they are
judged against as ``jobContext``. Matching is whole-word, so "GA" never matches
inside "Chicago", and there is no state-name aliasing: a rule on "GA" does not
match a job listed as "Georgia".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .answers import _contains_phrase as contains_phrase
from .answers import label_tokens

CONDITION_KEYS: tuple[str, ...] = ("location", "company", "portal")


@dataclass(frozen=True)
class RuleOutcome:
    """``answer`` is None when no rule applies, or when ``ambiguous`` is True."""

    answer: str | None
    ambiguous: bool = False


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _specificity(rule: object, tokens: tuple[str, ...], job_context: dict[str, Any]) -> tuple[int, int] | None:
    """(conditions held, question length) for a rule that applies, else None."""
    if not isinstance(rule, dict) or rule.get("enabled", True) is False:
        return None
    question, answer = _text(rule.get("question")), _text(rule.get("answer"))
    if question is None or answer is None or not contains_phrase(tokens, question):
        return None
    conditions = rule.get("conditions") or {}
    if not isinstance(conditions, dict):
        return None
    for key, expected in conditions.items():
        wanted, actual = _text(expected), _text(job_context.get(key))
        # A condition the resolver cannot evaluate must not make the rule apply everywhere.
        if key not in CONDITION_KEYS or wanted is None or actual is None:
            return None
        if not contains_phrase(label_tokens(actual), wanted):
            return None
    return (len(conditions), len(label_tokens(question)))


def resolve_preference_rule(field_label: str, rules: object, job_context: object) -> RuleOutcome:
    """Pick the most specific rule whose question and conditions all hold."""
    if not isinstance(rules, list):
        return RuleOutcome(answer=None)
    context = job_context if isinstance(job_context, dict) else {}
    tokens = label_tokens(field_label)
    best: tuple[int, int] | None = None
    answers: set[str] = set()
    for rule in rules:
        score = _specificity(rule, tokens, context)
        if score is None or (best is not None and score < best):
            continue
        if best is None or score > best:
            best, answers = score, set()
        answers.add(str(rule["answer"]).strip())
    if len(answers) > 1:
        return RuleOutcome(answer=None, ambiguous=True)
    return RuleOutcome(answer=next(iter(answers), None))


def with_job_context(canonical_profile: dict[str, Any], job_metadata: dict[str, Any]) -> dict[str, Any]:
    """A copy of the profile carrying the job facts rules are judged against."""
    context = {key: job_metadata[key] for key in CONDITION_KEYS if _text(job_metadata.get(key))}
    return {**canonical_profile, "jobContext": context}
