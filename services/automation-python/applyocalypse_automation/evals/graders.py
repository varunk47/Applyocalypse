"""Deterministic graders for generated application text.

Deterministic on purpose: an LLM judge cannot gate CI, because it needs a key,
costs money per run, and disagrees with itself. These graders run offline, in
milliseconds, and give the same verdict every time. A model-graded layer can sit
on top later for the judgements that genuinely need taste.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..validation import ArtifactKind, TextArtifactValidator

# Capitalized words that carry no factual claim, so seeing one in generated text
# that is absent from the source material proves nothing.
_NEUTRAL_CAPITALIZED = frozenset(
    {
        "a", "an", "and", "as", "at", "best", "but", "by", "dear", "for", "from", "hello", "hi", "hiring",
        "i", "if", "in", "is", "it", "kind", "manager", "my", "of", "on", "or", "recruiter", "regards",
        "sincerely", "so", "team", "thank", "thanks", "that", "the", "their", "there", "they", "this",
        "to", "we", "what", "when", "while", "with", "yours",
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
        "january", "february", "march", "april", "may", "june", "july",
        "august", "september", "october", "november", "december",
    }
)

# Numbers too small or too common to read as a claim: "one of", "3 of the".
_NEUTRAL_NUMBER_MAX = 2

_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9&./+'-]*")
_CAPITALIZED_RUN = re.compile(r"\b[A-Z][A-Za-z0-9&.'+-]*(?:\s+[A-Z][A-Za-z0-9&.'+-]*)*")
# No trailing \b: a percent sign is not a word character, so requiring a boundary
# after it would silently drop the sign and compare "38" where "38%" was written.
_NUMBER = re.compile(r"\b\d[\d,]*(?:\.\d+)?%?")


@dataclass(frozen=True, slots=True)
class GraderResult:
    """One grader's verdict on one piece of text."""

    name: str
    passed: bool
    detail: str
    findings: tuple[str, ...] = ()

    def summary(self) -> str:
        verdict = "PASS" if self.passed else "FAIL"
        return f"{verdict} {self.name}: {self.detail}"


def normalize(text: str) -> str:
    """Lowercased, punctuation-insensitive form used for containment checks.

    A dot inside a token is part of the name ("Node.js"), so it survives; a dot
    at the end is the sentence stopping, and keeping it would make "Systems."
    look like a different employer from "Systems".
    """
    tokens = (token.strip(".'-") for token in _WORD.findall(text.lower()))
    return " ".join(token for token in tokens if token)


def _allowed_vocabulary(sources: list[str]) -> set[str]:
    return set(normalize(" ".join(sources)).split())


def _number_key(token: str) -> str:
    return token.replace(",", "")


def _source_numbers(sources: list[str]) -> set[str]:
    return {_number_key(match.group()) for source in sources for match in _NUMBER.finditer(source)}


def _claim_phrases(text: str) -> list[tuple[str, bool]]:
    """Capitalized runs that read like a name: an employer, school, or product.

    Neutral words are trimmed off both ends first, so \"At Halcyon Systems I\"
    is judged as the claim it contains rather than as the grammar around it. A
    lone capitalized word opening a sentence is dropped outright, because that
    is a capital letter rather than a claim.

    The second element of each pair says whether the phrase still leads with a
    word that only got its capital from opening a sentence. The caller uses it
    to forgive \"Utilized Kubernetes\", where the claim is the tool, not the verb.
    """
    phrases: list[tuple[str, bool]] = []
    for match in _CAPITALIZED_RUN.finditer(text):
        words = match.group().strip(" .,;:").split()
        trimmed_head = False
        while words and words[0].lower().strip(".,;:") in _NEUTRAL_CAPITALIZED:
            words.pop(0)
            trimmed_head = True
        while words and words[-1].lower().strip(".,;:") in _NEUTRAL_CAPITALIZED:
            words.pop()
        if not words:
            continue
        sentence_initial_head = not trimmed_head and _starts_a_sentence(text, match.start())
        if len(words) == 1 and sentence_initial_head:
            continue
        phrases.append((" ".join(words), sentence_initial_head))
    return phrases


def _starts_a_sentence(text: str, index: int) -> bool:
    before = text[:index].rstrip()
    return not before or before[-1] in ".!?:\n"


def _claim_numbers(text: str) -> list[str]:
    numbers: list[str] = []
    for match in _NUMBER.finditer(text):
        token = match.group()
        bare = token.rstrip("%").replace(",", "")
        try:
            value = float(bare)
        except ValueError:
            continue
        if not token.endswith("%") and value <= _NEUTRAL_NUMBER_MAX:
            continue
        numbers.append(token)
    return numbers


def grade_groundedness(text: str, *, sources: list[str]) -> GraderResult:
    """Every name and number in the text must be traceable to the source material.

    `sources` is what the model was allowed to know: the profile, the resume, and
    the job description. Anything else is the model inventing an employer, a
    school, or a metric, which is the one failure that can genuinely harm a user.
    """
    allowed_words = _allowed_vocabulary(sources)
    allowed_text = normalize(" ".join(sources))

    def is_grounded(words: list[str]) -> bool:
        if not words:
            return True
        if " ".join(words) in allowed_text:
            return True
        # A multi-word name counts as grounded when every word of it is known,
        # so "Northstar Labs Platform" survives if the profile names both.
        return all(word in allowed_words for word in words)

    ungrounded: list[str] = []
    for phrase, sentence_initial_head in _claim_phrases(text):
        words = normalize(phrase).split()
        if is_grounded(words):
            continue
        # "Utilized Kubernetes": the head is capitalized because the sentence
        # started, not because it names anything. Forgive it only when the rest
        # of the phrase does trace to the sources, so an invented name leading a
        # sentence is still reported.
        if sentence_initial_head and len(words) > 1 and is_grounded(words[1:]):
            continue
        ungrounded.append(phrase)

    # Compared as whole tokens, not as substrings: "9" reads as grounded inside
    # "95" under a substring check, which would wave through an invented figure.
    allowed_numbers = _source_numbers(sources)
    for number in _claim_numbers(text):
        if _number_key(number) in allowed_numbers:
            continue
        if _number_key(number.rstrip("%")) in {value.rstrip("%") for value in allowed_numbers}:
            continue
        ungrounded.append(number)

    deduped = tuple(dict.fromkeys(ungrounded))
    if deduped:
        return GraderResult(
            name="groundedness",
            passed=False,
            detail=f"{len(deduped)} claim(s) appear nowhere in the profile or job description",
            findings=deduped,
        )
    return GraderResult(name="groundedness", passed=True, detail="every name and number traces to the source material")


def grade_mentions(text: str, *, must_mention: list[str]) -> GraderResult:
    """The letter has to be about this job: the company and role must appear."""
    haystack = normalize(text)
    missing = tuple(term for term in must_mention if normalize(term) not in haystack)
    if missing:
        return GraderResult(
            name="mentions",
            passed=False,
            detail=f"{len(missing)} required term(s) missing",
            findings=missing,
        )
    return GraderResult(name="mentions", passed=True, detail="every required term appears")


def grade_style(text: str, *, artifact_kind: ArtifactKind) -> GraderResult:
    """The shipping style gate: banned wording and em dashes block a release."""
    report = TextArtifactValidator().validate(text, artifact_kind=artifact_kind)
    if report.passed:
        return GraderResult(name="style", passed=True, detail="no blocking style issues")
    findings = tuple(f"{issue.code}: {issue.message}" for issue in report.blocking_issues)
    return GraderResult(
        name="style",
        passed=False,
        detail=f"{len(findings)} blocking style issue(s)",
        findings=findings,
    )


def grade_text(
    text: str,
    *,
    artifact_kind: ArtifactKind,
    sources: list[str],
    must_mention: list[str] | None = None,
) -> list[GraderResult]:
    """Runs every grader that applies to a piece of generated text."""
    results = [
        grade_style(text, artifact_kind=artifact_kind),
        grade_groundedness(text, sources=sources),
    ]
    if must_mention:
        results.append(grade_mentions(text, must_mention=must_mention))
    return results
