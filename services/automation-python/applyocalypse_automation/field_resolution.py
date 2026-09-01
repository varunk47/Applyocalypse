from __future__ import annotations

import os
from dataclasses import dataclass
from dataclasses import field as dataclass_field

from .answers import ProposedApplicationAnswer, label_tokens, propose_answer_for_detected_field
from .browser.adapter import BrowserField
from .secret_env import get_secret

APPLICATION_PASSWORD_SENTINEL = "Use stored application password"

OTP_FIELD_HINTS = (
    "otp",
    "one-time code",
    "one time code",
    "verification code",
    "security code",
    "passcode",
)


def normalize_field_label(value: str) -> str:
    return " ".join("".join(character.lower() if character.isalnum() else " " for character in value).split())


def is_password_field(field: BrowserField) -> bool:
    label = normalize_field_label(field.label)
    return field.field_type == "password" or "password" in label


def is_otp_field(field: BrowserField) -> bool:
    label = normalize_field_label(field.label)
    return any(hint in label for hint in OTP_FIELD_HINTS)


def proposed_answer_for_browser_field(
    field: BrowserField, canonical_profile: dict[str, object], jd_text: str | None = None
) -> ProposedApplicationAnswer:
    if is_password_field(field) and get_secret("APPLYO_APPLICATION_PASSWORD"):
        return ProposedApplicationAnswer(
            field_label=field.label,
            field_type=field.field_type,
            proposed_value=APPLICATION_PASSWORD_SENTINEL,
            confidence=0.84,
            source="PROFILE",
            requires_review=True,
        )
    return propose_answer_for_detected_field(
        field_label=field.label,
        field_type=field.field_type,
        canonical_profile=canonical_profile,
        autofill_approved_defaults=os.getenv("APPLYO_AUTOFILL_APPROVED_DEFAULTS") == "1",
        jd_text=jd_text,
        # Detection already carries what the ATS calls the input. The review gate
        # reads it so a demographic question still gates when its label is worded
        # in a way no phrase list anticipated.
        field_name=str(field.metadata.get("name") or "") or None,
    )


# ── Approved-answer → detected-field matching ─────────────────────────────────
# Matching an approved answer to a field on the page by bidirectional substring
# ("a in b or b in a") cross-assigns values: the "Phone" answer lands in "Phone
# country code", "Email" lands in "Email me about similar jobs", and the
# work-authorization answer lands in the relocation question. Candidates are
# ranked into tiers instead, and a value is applied only when exactly one
# candidate wins the top tier outright.

MATCH_OUTCOME_MATCHED = "MATCHED"
MATCH_OUTCOME_NO_MATCH = "NO_MATCH"
MATCH_OUTCOME_AMBIGUOUS = "AMBIGUOUS"

# Tokens that carry no distinguishing meaning in a field label, so a label that
# differs only by these is the same question ("Phone" / "Phone number").
_FILLER_TOKENS = frozenset(
    {
        "address",
        "detail",
        "enter",
        "field",
        "full",
        "id",
        "info",
        "information",
        "input",
        "no",
        "number",
        "optional",
        "please",
        "required",
        "text",
        "the",
        "value",
        "your",
    }
)

_MATCH_SCORE_FLOOR = 0.6
_PHRASE_COVERAGE_FLOOR = 0.6
_TYPE_FALLBACK_SCORE = 0.5
_TYPE_FALLBACK_FIELD_TYPES = frozenset({"email", "tel", "url"})


@dataclass(frozen=True, slots=True)
class AnswerFieldMatch:
    """The single approved answer that won the match for a field."""

    value: str
    answer_label: str
    strategy: str
    score: float


@dataclass(frozen=True, slots=True)
class AnswerFieldMatchResult:
    """Outcome of matching approved answers against one detected field.

    ``outcome`` distinguishes "nothing claimed this field" (``NO_MATCH``) from
    "several answers claimed it equally well" (``AMBIGUOUS``) so the caller can
    route an ambiguous field to user review instead of silently skipping it.
    """

    outcome: str
    match: AnswerFieldMatch | None = None
    competing_labels: tuple[str, ...] = dataclass_field(default=())


def _is_contiguous_run(needle: tuple[str, ...], haystack: tuple[str, ...]) -> bool:
    return any(haystack[index : index + len(needle)] == needle for index in range(len(haystack) - len(needle) + 1))


def _label_match(field_tokens: tuple[str, ...], answer_tokens: tuple[str, ...]) -> tuple[str, float] | None:
    """Score one label pair, best tier first. ``None`` means "not the same field"."""
    if not field_tokens or not answer_tokens:
        return None
    if field_tokens == answer_tokens:
        return ("exact", 1.0)
    if set(field_tokens) == set(answer_tokens):
        return ("token_set", 0.9)

    smaller, larger = (
        (field_tokens, answer_tokens) if len(field_tokens) <= len(answer_tokens) else (answer_tokens, field_tokens)
    )
    residue = set(larger) - set(smaller)
    if set(smaller) < set(larger) and all(token in _FILLER_TOKENS for token in residue):
        return ("subset", 0.8)
    if (
        len(smaller) >= 2
        and len(smaller) / len(larger) >= _PHRASE_COVERAGE_FLOOR
        and _is_contiguous_run(smaller, larger)
    ):
        return ("phrase", 0.65)
    return None


def match_approved_answer(field: BrowserField, approved_answers: object) -> AnswerFieldMatchResult:
    """Rank approved answers against ``field`` and require a unique winner."""
    if not isinstance(approved_answers, list):
        return AnswerFieldMatchResult(outcome=MATCH_OUTCOME_NO_MATCH)

    field_tokens = label_tokens(field.label)
    scored: list[tuple[float, str, str, str]] = []
    type_fallbacks: list[tuple[str, str]] = []
    for answer in approved_answers:
        if not isinstance(answer, dict):
            continue
        value = answer.get("value")
        if not isinstance(value, str) or not value.strip():
            continue
        answer_label = str(answer.get("fieldLabel") or "")
        answer_tokens = label_tokens(answer_label)
        if not answer_tokens:
            continue
        scored_tier = _label_match(field_tokens, answer_tokens)
        if scored_tier is not None and scored_tier[1] >= _MATCH_SCORE_FLOOR:
            strategy, score = scored_tier
            scored.append((score, strategy, answer_label, value))
        answer_type = normalize_field_label(str(answer.get("fieldType") or ""))
        if field.field_type in _TYPE_FALLBACK_FIELD_TYPES and field.field_type == answer_type:
            type_fallbacks.append((answer_label, value))

    if scored:
        best_score = max(score for score, _strategy, _label, _value in scored)
        winners = [row for row in scored if row[0] == best_score]
        if len({row[3] for row in winners}) > 1:
            return AnswerFieldMatchResult(
                outcome=MATCH_OUTCOME_AMBIGUOUS,
                competing_labels=tuple(row[2] for row in winners),
            )
        score, strategy, answer_label, value = winners[0]
        return AnswerFieldMatchResult(
            outcome=MATCH_OUTCOME_MATCHED,
            match=AnswerFieldMatch(value=value, answer_label=answer_label, strategy=strategy, score=score),
        )

    # A type-only match is safe only when unambiguous; with several approved
    # answers of the same type, guessing writes one field's value into another.
    if type_fallbacks:
        if len({value for _label, value in type_fallbacks}) > 1:
            return AnswerFieldMatchResult(
                outcome=MATCH_OUTCOME_AMBIGUOUS,
                competing_labels=tuple(label for label, _value in type_fallbacks),
            )
        answer_label, value = type_fallbacks[0]
        return AnswerFieldMatchResult(
            outcome=MATCH_OUTCOME_MATCHED,
            match=AnswerFieldMatch(
                value=value,
                answer_label=answer_label,
                strategy="type_fallback",
                score=_TYPE_FALLBACK_SCORE,
            ),
        )

    return AnswerFieldMatchResult(outcome=MATCH_OUTCOME_NO_MATCH)


def approved_value_for_field(field: BrowserField, approved_answers: object) -> str | None:
    """Value to write into ``field``, or ``None`` when there is no unique winner."""
    result = match_approved_answer(field, approved_answers)
    return result.match.value if result.outcome == MATCH_OUTCOME_MATCHED and result.match else None


def resolve_secret_reviewed_value(field: BrowserField, reviewed_value: str | None) -> tuple[str | None, str | None]:
    if reviewed_value == APPLICATION_PASSWORD_SENTINEL and is_password_field(field):
        password = get_secret("APPLYO_APPLICATION_PASSWORD")
        return (password if password else None, "APPLICATION_PASSWORD_SECRET")
    return reviewed_value, None
