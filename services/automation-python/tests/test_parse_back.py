"""The parse-back gate: a tailored resume that no longer reads back like the
master it came from is a silent failure, so these cases pin down exactly which
mutations are allowed through and which have to stop for review."""

from __future__ import annotations

from pathlib import Path

import pytest

from applyocalypse_automation.documents.parse_back import verify_parse_back

# An anchored master: name, summary and skills are placeholders that mutation is
# meant to overwrite; everything else is the user's own literal content and has
# to come back out the other side unchanged.
MASTER = """{{APPLYO_FULL_NAME}}
jane.doe@example.com | (415) 555-0132

SUMMARY
{{APPLYO_RESUME_SUMMARY}}

EXPERIENCE
Senior Engineer | Acme Corp | Jan 2020 - Present
- Owned the billing service
Engineer | Globex Inc | Jun 2017 - Dec 2019
- Improved page load time

EDUCATION
Georgia Institute of Technology | BS Computer Science | 2017

SKILLS
{{APPLYO_SKILLS}}
"""

GLOBEX_BLOCK = "Engineer | Globex Inc | Jun 2017 - Dec 2019\n- Improved page load time\n"
EDUCATION_LINE = "Georgia Institute of Technology | BS Computer Science | 2017\n"
CONTACT_LINE = "jane.doe@example.com | (415) 555-0132\n"


def _tailored() -> str:
    """The master as a clean mutation should leave it."""
    return (
        MASTER.replace("{{APPLYO_FULL_NAME}}", "Jane Doe")
        .replace("{{APPLYO_RESUME_SUMMARY}}", "Verified evidence aligns with Python, Kubernetes.")
        .replace("{{APPLYO_SKILLS}}", "Python, TypeScript, Kubernetes")
    )


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _run(tmp_path: Path, tailored_text: str):
    return verify_parse_back(
        master_path=_write(tmp_path, "master.txt", MASTER),
        output_path=_write(tmp_path, "tailored.txt", tailored_text),
    )


def test_a_clean_mutation_passes(tmp_path: Path) -> None:
    result = _run(tmp_path, _tailored())
    assert result.passed, [finding.detail for finding in result.findings]


def test_rewriting_a_bullet_is_not_damage(tmp_path: Path) -> None:
    """Tailoring exists to rewrite bullets. Only the scaffolding has to survive."""
    rewritten = _tailored().replace(
        "- Owned the billing service", "- Led a four person team through a billing platform migration"
    )
    assert _run(tmp_path, rewritten).passed


def test_placeholder_fields_are_never_reported(tmp_path: Path) -> None:
    """The name is a placeholder in the master and real in the copy. Changing it
    is the whole point, so it must not read as a field the user lost."""
    result = _run(tmp_path, _tailored())
    assert "APPLYO" not in " ".join(finding.detail for finding in result.findings)


# (what the mutation did to the document, the code the gate has to raise)
DAMAGE_CASES: tuple[tuple[str, str, str], ...] = (
    ("drops an employer block", GLOBEX_BLOCK, "PARSE_BACK_EXPERIENCE_LOST"),
    ("drops the education line", EDUCATION_LINE, "PARSE_BACK_EDUCATION_LOST"),
    ("drops the whole education section", f"EDUCATION\n{EDUCATION_LINE}", "PARSE_BACK_SECTION_LOST"),
    ("loses the contact line", CONTACT_LINE, "PARSE_BACK_CONTACT_LOST"),
)


@pytest.mark.parametrize(
    "description,removed,expected_code", DAMAGE_CASES, ids=[case[0] for case in DAMAGE_CASES]
)
def test_lost_content_is_reported(
    tmp_path: Path, description: str, removed: str, expected_code: str
) -> None:
    result = _run(tmp_path, _tailored().replace(removed, ""))
    assert not result.passed, description
    assert expected_code in {finding.code for finding in result.findings}


def test_a_near_duplicate_entry_cannot_stand_in_for_the_one_that_vanished(tmp_path: Path) -> None:
    """"Engineer" is a substring of "Senior Engineer". Without distinct pairing
    the surviving line would cover for the deleted one and the gate would pass."""
    result = _run(tmp_path, _tailored().replace(GLOBEX_BLOCK, ""))
    assert [finding.code for finding in result.findings] == ["PARSE_BACK_EXPERIENCE_LOST"]
    assert "Engineer" in result.findings[0].detail


def test_an_unreadable_tailored_file_is_reported(tmp_path: Path) -> None:
    result = verify_parse_back(
        master_path=_write(tmp_path, "master.txt", MASTER),
        output_path=tmp_path / "never-written.txt",
    )
    assert not result.passed
    assert [finding.code for finding in result.findings] == ["PARSE_BACK_UNREADABLE"]


def test_an_unreadable_master_does_not_fail_a_good_copy(tmp_path: Path) -> None:
    """Without a baseline there is nothing to compare, and stopping a run over a
    master we could not open would punish the user for our own gap."""
    result = verify_parse_back(
        master_path=tmp_path / "missing.docx",
        output_path=_write(tmp_path, "tailored.txt", _tailored()),
    )
    assert result.passed


def test_payload_carries_the_findings_as_blocking_issues(tmp_path: Path) -> None:
    result = _run(tmp_path, _tailored().replace(EDUCATION_LINE, ""))
    payload = result.to_payload()
    assert payload["parse_back_passed"] is False
    assert payload["blocking_issues"]
    assert all({"code", "detail"} == set(issue) for issue in payload["blocking_issues"])
