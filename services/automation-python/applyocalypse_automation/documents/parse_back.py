"""Parse-back gate: does the tailored resume still say what the master said?

Mutation writes into a copy of the user's own document, and when it goes wrong
the failure is silent. The file still opens, still looks broadly right, and
still gets submitted, but an employer or a whole Education section has quietly
gone missing on the way through. Every other check on this path reads the words
(banned phrases, page count) rather than the structure, so nothing catches it.

So run the master and the tailored copy back through the same resume parser an
ATS-shaped reader would use, and ask one narrow question: is everything the
master claimed still claimed by the copy? Only literal content is compared.
Anything the master carries as an ``{{APPLYO_...}}`` placeholder is meant to
change, so those fields are skipped rather than reported.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..parsing.document_parser import parse_document

PLACEHOLDER_RE = re.compile(r"\{\{\s*APPLYO_[A-Z0-9_]+\s*\}\}")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")

# (canonical section, entry key, finding code, how to name it to the user).
# The key names the parser's own heading column rather than a guaranteed
# employer or school: the parser reads columns positionally, so which side of a
# "Title | Company" line lands in ``company`` depends on the resume. That costs
# the gate nothing, because both sides of the comparison are read the same way.
_STRUCTURE_CHECKS: tuple[tuple[str, str, str, str], ...] = (
    ("experience", "company", "PARSE_BACK_EXPERIENCE_LOST", "experience entry"),
    ("education", "institution", "PARSE_BACK_EDUCATION_LOST", "education entry"),
)

_CONTACT_FIELDS: tuple[tuple[str, str], ...] = (
    ("email", "email address"),
    ("phone", "phone number"),
)


@dataclass(frozen=True, slots=True)
class ParseBackFinding:
    code: str
    detail: str

    def to_payload(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class ParseBackResult:
    passed: bool
    findings: tuple[ParseBackFinding, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "parse_back_passed": self.passed,
            "blocking_issues": [finding.to_payload() for finding in self.findings],
        }


def _normalize(value: Any) -> str:
    return _NON_ALNUM.sub(" ", str(value or "").casefold()).strip()


def _is_placeholder(value: Any) -> bool:
    return bool(PLACEHOLDER_RE.search(str(value or "")))


def _survives(expected: str, candidates: list[str]) -> bool:
    """True when some parsed value still carries the master's text.

    Containment either way, because mutation legitimately reflows a line: the
    parser may hand back "Acme Corp, Remote" where the master had "Acme Corp",
    or clip a trailing column off it. Leniency is the safe direction here, since
    a false alarm on a good resume costs the user a stop for nothing.
    """
    if not expected:
        return True
    return any(expected in candidate or candidate in expected for candidate in candidates if candidate)


def _unmatched(expected: list[tuple[str, str]], candidates: list[str]) -> list[str]:
    """Pair every master entry with a *distinct* survivor, exact matches first.

    Distinctness is what makes the check bite. A resume listing "Engineer" and
    then "Senior Engineer" would otherwise let the one surviving line stand in
    for both under containment, which is precisely the loss the gate exists to
    catch. Returns the raw text of the entries nothing was left to match.
    """
    pool = [candidate for candidate in candidates if candidate]
    lost: list[str] = []
    for raw, normalized in expected:
        hit = next((candidate for candidate in pool if candidate == normalized), None)
        if hit is None:
            hit = next((candidate for candidate in pool if _survives(normalized, [candidate])), None)
        if hit is None:
            lost.append(raw)
        else:
            pool.remove(hit)
    return lost


def _values(canonical: dict[str, Any], section: str, key: str) -> list[str]:
    entries = canonical.get(section)
    if not isinstance(entries, list):
        return []
    return [str(entry.get(key) or "") for entry in entries if isinstance(entry, dict)]


def _sections(canonical: dict[str, Any]) -> set[str]:
    raw = canonical.get("sections")
    if not isinstance(raw, list):
        return set()
    # A master's placeholder line ({{APPLYO_SKILLS}} on its own) reads to the
    # parser as a heading. It is meant to disappear into real content, so it is
    # not a section anyone lost.
    return {
        str(section.get("normalizedLabel") or "")
        for section in raw
        if isinstance(section, dict)
        and section.get("normalizedLabel")
        and not _is_placeholder(section.get("label"))
    }


def verify_parse_back(*, master_path: Path, output_path: Path) -> ParseBackResult:
    """Compare a tailored resume against the master it was mutated from."""
    try:
        master = parse_document(master_path, document_kind="RESUME").canonical
    except Exception:
        # No baseline means nothing to compare against, and failing a good
        # document because its master would not open helps nobody.
        return ParseBackResult(passed=True, findings=())

    try:
        tailored = parse_document(output_path, document_kind="RESUME").canonical
    except Exception as exc:
        return ParseBackResult(
            passed=False,
            findings=(
                ParseBackFinding(
                    "PARSE_BACK_UNREADABLE",
                    f"The tailored resume could not be read back: {exc}",
                ),
            ),
        )

    findings: list[ParseBackFinding] = []

    for section, key, code, label in _STRUCTURE_CHECKS:
        survivors = [_normalize(value) for value in _values(tailored, section, key)]
        expected = [
            (raw.strip(), _normalize(raw))
            for raw in _values(master, section, key)
            if raw.strip() and not _is_placeholder(raw)
        ]
        for raw in _unmatched(expected, survivors):
            findings.append(
                ParseBackFinding(code, f"The {label} '{raw}' is in your resume but not in the tailored copy.")
            )

    master_identity = master.get("identity") if isinstance(master.get("identity"), dict) else {}
    tailored_identity = tailored.get("identity") if isinstance(tailored.get("identity"), dict) else {}
    for field_name, label in _CONTACT_FIELDS:
        raw = master_identity.get(field_name)
        if not str(raw or "").strip() or _is_placeholder(raw):
            continue
        if not _survives(_normalize(raw), [_normalize(tailored_identity.get(field_name))]):
            findings.append(
                ParseBackFinding("PARSE_BACK_CONTACT_LOST", f"Your {label} did not survive tailoring.")
            )

    for lost in sorted(_sections(master) - _sections(tailored)):
        findings.append(
            ParseBackFinding("PARSE_BACK_SECTION_LOST", f"The {lost} section is missing from the tailored copy.")
        )

    return ParseBackResult(passed=not findings, findings=tuple(findings))
