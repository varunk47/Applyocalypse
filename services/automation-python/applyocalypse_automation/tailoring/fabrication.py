"""Rejects a tailored bullet that claims something the original did not.

The bullet-rewrite prompt already tells the model not to invent skills, tools,
metrics or experience. That instruction is the only thing standing between a
candidate and a resume they cannot defend in an interview, and an instruction is
not an enforcement: a model that follows it 99 times out of 100 still fabricates
on a resume every few applications, silently, in the one place the person is
least able to check.

So the same rules run again here, in code, over the pair of strings. A rewrite
that trips any of them is rejected and the original bullet is kept, which is
always a safe outcome: the original is the candidate's own honest text.

Four checks, chosen because each one can be decided from the two strings alone
with almost no false positives:

* a number in the rewrite that the original never claimed,
* a tool or acronym the bullet never mentioned and the resume never lists,
* an ownership verb where the original claimed no ownership,
* template or prompt scaffolding that leaked into the text.

Deliberately not checked: tool-of-trade conflation, the case where the candidate
*used* a tool and the rewrite says they *built* it. Separating "Built dashboards
using Tableau" from "Built Tableau dashboards" needs to parse the sentence, and
every cheap approximation rejects the second one, which is a good rewrite. A
false rejection is not free here: it quietly costs the tailoring its point.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass

# Digit runs, keeping decimals and thousands separators together so "1,200" and
# "1200" compare equal and "2.5" is not read as a 2 and a 5.
_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")

# Only ever used to license a digit in the rewrite, never to accuse one. Reading
# "one" or "a couple" in a rewrite as a numeric claim would reject good text, and
# resume metrics are written in digits anyway.
_SPELLED_NUMBERS = {
    "zero": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "eleven": "11",
    "twelve": "12",
    "thirteen": "13",
    "fourteen": "14",
    "fifteen": "15",
    "sixteen": "16",
    "seventeen": "17",
    "eighteen": "18",
    "nineteen": "19",
    "twenty": "20",
}

_EDGE_LEADING = "([{\"'“‘"
_EDGE_TRAILING = ",.;:!?)]}\"'”’"

# AWS, ETL, SQL, S3, K8S. Two characters minimum so a bare "I" is not a tool.
_ACRONYM_RE = re.compile(r"^[A-Z][A-Z0-9]{1,5}$")

# Node.js, C++, C#, .NET. Punctuation inside a word is structural, so this one
# stays trustworthy even in a line that tells us nothing through its capitals.
_SYMBOLIC_TERM_RE = re.compile(r"[A-Za-z][.+#]|^\.[A-Za-z]")

_OWNERSHIP_VERBS = frozenset(
    {
        "architected",
        "architecting",
        "directed",
        "directing",
        "drove",
        "driving",
        "founded",
        "founding",
        "headed",
        "heading",
        "led",
        "leading",
        "leads",
        "managed",
        "manages",
        "managing",
        "oversaw",
        "overseeing",
        "owned",
        "owning",
        "owns",
        "pioneered",
        "spearheaded",
        "spearheading",
    }
)

_PLACEHOLDER_RE = re.compile(
    r"\{\{|\}\}"
    r"|\[(?:insert|company|role|title|name|your|x{2,})\b"
    r"|<(?:insert|company|role|title|name)>"
    r"|\bxyz\b|\btbd\b|\bn/a\b|\bplaceholder\b|\blorem ipsum\b"
    r"|\bas an ai\b|\bthe candidate\b|\bthe user\b|\bjob description\b",
    re.IGNORECASE,
)

_WORD_RE = re.compile(r"[a-z]+")


@dataclass(frozen=True, slots=True)
class FabricationFinding:
    """One reason a rewrite was not trustworthy. ``detail`` is for the log."""

    code: str
    detail: str


def _numbers(text: str, *, include_spelled: bool) -> set[str]:
    found = {match.group(0).replace(",", "") for match in _NUMBER_RE.finditer(text)}
    if include_spelled:
        found |= {_SPELLED_NUMBERS[word] for word in _WORD_RE.findall(text.lower()) if word in _SPELLED_NUMBERS}
    return found


def _tokens(text: str) -> list[str]:
    stripped = (token.lstrip(_EDGE_LEADING).rstrip(_EDGE_TRAILING) for token in text.split())
    return [token for token in stripped if token]


def _is_shouting(tokens: list[str]) -> bool:
    """Whether this line's capitals carry any information at all."""
    lettered = [token for token in tokens if any(character.isalpha() for character in token)]
    if len(lettered) < 3:
        return False
    shouted = [token for token in lettered if token.upper() == token]
    return len(shouted) >= len(lettered) * 0.8


def _is_technical(token: str, *, position: int, trust_capitals: bool) -> bool:
    if len(token) > 1 and any(character.isalpha() for character in token) and _SYMBOLIC_TERM_RE.search(token):
        return True
    if not trust_capitals:
        return False
    if _ACRONYM_RE.fullmatch(token):
        return True
    # A capital that opens the sentence is grammar. One in the middle of a bullet
    # is a proper noun, and in a resume bullet that means a tool: Airflow,
    # Kubernetes, PostgreSQL, Terraform.
    if position == 0:
        return False
    return token[:1].isupper()


def _technical_tokens(text: str) -> dict[str, str]:
    """Lowercased tool names mapped to how they were written."""
    tokens = _tokens(text)
    trust_capitals = not _is_shouting(tokens)
    found: dict[str, str] = {}
    for position, token in enumerate(tokens):
        if _is_technical(token, position=position, trust_capitals=trust_capitals):
            found.setdefault(token.lower(), token)
    return found


def technical_terms(text: str) -> set[str]:
    """The tools and acronyms a piece of text names, lowercased."""
    return set(_technical_tokens(text))


def _ownership_verbs(text: str) -> set[str]:
    return {word for word in _WORD_RE.findall(text.lower()) if word in _OWNERSHIP_VERBS}


def fabrication_findings(
    original: str,
    rewritten: str,
    *,
    known_terms: Collection[str] = (),
) -> list[FabricationFinding]:
    """Every reason ``rewritten`` claims more than ``original`` did.

    ``known_terms`` is the rest of the candidate's own resume, lowercased. Moving
    a tool they genuinely list into the bullet a job cares about is the rewrite
    we want; inventing one is not, and only the resume can tell those apart. It
    licenses tools only. A metric has to be earned by the bullet making the claim,
    so a number is never licensed from elsewhere.
    """
    findings: list[FabricationFinding] = []

    invented_numbers = _numbers(rewritten, include_spelled=False) - _numbers(original, include_spelled=True)
    if invented_numbers:
        findings.append(
            FabricationFinding(
                code="INVENTED_NUMBER",
                detail=f"not in the original bullet: {', '.join(sorted(invented_numbers))}",
            )
        )

    allowed = {term.lower() for term in known_terms} | set(_technical_tokens(original))
    invented_terms = {lower: written for lower, written in _technical_tokens(rewritten).items() if lower not in allowed}
    if invented_terms:
        findings.append(
            FabricationFinding(
                code="INVENTED_TERM",
                detail=f"not on the resume: {', '.join(sorted(invented_terms.values()))}",
            )
        )

    claimed = _ownership_verbs(rewritten)
    if claimed and not _ownership_verbs(original):
        findings.append(
            FabricationFinding(
                code="SCOPE_ESCALATION",
                detail=f"the original claimed no ownership: {', '.join(sorted(claimed))}",
            )
        )

    leaked = sorted({match.group(0).lower() for match in _PLACEHOLDER_RE.finditer(rewritten)})
    if leaked:
        findings.append(
            FabricationFinding(
                code="PLACEHOLDER_LEAK",
                detail=f"scaffolding left in the text: {', '.join(leaked)}",
            )
        )

    return findings


def is_faithful_rewrite(
    original: str,
    rewritten: str,
    *,
    known_terms: Collection[str] = (),
) -> bool:
    """Whether ``rewritten`` may replace ``original`` on the resume.

    An empty rewrite is never faithful: accepting one would delete a line the
    candidate wrote.
    """
    if not rewritten.strip():
        return False
    return not fabrication_findings(original, rewritten, known_terms=known_terms)
