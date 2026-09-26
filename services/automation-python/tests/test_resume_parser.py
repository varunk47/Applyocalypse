"""Parsing a real resume's layout into profile facts.

Every line below is taken from a real resume as the PDF converter lays it out,
with columns recovered as " | ". Each case is a fact the parser used to drop or
mangle.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from applyocalypse_automation.parsing.document_parser import parse_document

RESUME = """VARUN KADAM
Chicago, IL | (872) 288-5427 | varun@example.com | linkedin.com/in/varunkadam47
SUMMARY
Recent MS CS graduate building AI agent systems.
EDUCATION
Illinois Institute of Technology | May 2026
Master of Science in Computer Science | Chicago, IL
SKILLS
Languages: Python, TypeScript, SQL, R
Cloud & DevOps: AWS, Azure, Docker, CI/CD, Linux
WORK EXPERIENCE
Build Fellowship by Open Avenues | Jan 2025 – Mar 2025
AI Engineering Intern | Chicago, IL
Built a semantic search engine mapping messy job titles to canonical roles.
SkillCred.co | Jan 2024 � Jun 2024 Data Science Intern | Mumbai, India
Drove a 45% increase in user engagement.
PROJECTS
Applyocalypse | Electron, SolidJS, Python, SQLite | Apr 2026 – Present
Cut application time by 90% with a desktop agent.
"""


@pytest.fixture(scope="module")
def canonical(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    source = tmp_path_factory.mktemp("resume") / "resume.txt"
    source.write_text(RESUME, encoding="utf-8")
    return parse_document(source, document_kind="RESUME").canonical


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        # an ALL-CAPS name is the name, written the way a form wants it
        ("legalName", "Varun Kadam"),
        # the area code's parenthesis used to be cut off
        ("phone", "(872) 288-5427"),
        ("location", "Chicago, IL"),
        ("links", [{"label": "linkedin.com", "url": "https://linkedin.com/in/varunkadam47"}]),
    ],
)
def test_the_header_yields_the_contact_details(canonical: dict[str, Any], field: str, expected: Any) -> None:
    assert canonical["identity"][field] == expected


def test_the_name_line_is_not_a_section(canonical: dict[str, Any]) -> None:
    labels = [section["normalizedLabel"] for section in canonical["sections"]]
    assert labels[0] == "summary"


def test_each_skill_category_is_its_own_group(canonical: dict[str, Any]) -> None:
    groups = {group["label"]: group["skills"] for group in canonical["skillGroups"]}
    assert groups == {
        "Languages": ["Python", "TypeScript", "SQL", "R"],
        # CI/CD is one skill, not two
        "Cloud & DevOps": ["AWS", "Azure", "Docker", "CI/CD", "Linux"],
    }


@pytest.mark.parametrize(
    ("index", "expected"),
    [
        # the role on the row under a dated company row is that job's title,
        # not a second job at a company called "Chicago, IL"
        (0, {"company": "Build Fellowship by Open Avenues", "title": "AI Engineering Intern",
             "location": "Chicago, IL", "startDate": "Jan 2025", "endDate": "Mar 2025"}),
        # older converted files carry U+FFFD where the PDF had an en dash
        (1, {"company": "SkillCred.co", "title": "Data Science Intern",
             "location": "Mumbai, India", "startDate": "Jan 2024", "endDate": "Jun 2024"}),
    ],
)
def test_experience_rows_resolve_to_one_job_each(canonical: dict[str, Any], index: int, expected: dict[str, str]) -> None:
    assert len(canonical["experience"]) == 2
    entry = canonical["experience"][index]
    assert {key: entry[key] for key in expected} == expected
    assert len(entry["bullets"]) == 1


def test_a_project_row_splits_into_name_and_tools(canonical: dict[str, Any]) -> None:
    (project,) = canonical["projects"]
    assert project["name"] == "Applyocalypse"
    assert project["tools"] == ["Electron", "SolidJS", "Python", "SQLite"]
    assert project["summary"] is None
    assert project["bullets"] == ["Cut application time by 90% with a desktop agent."]


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("Ada Lovelace\nada@example.com\nSKILLS\nPython", "Ada Lovelace"),
        # a section heading is never taken for the name
        ("ada@example.com\nWORK EXPERIENCE\nEngineer at Acme", None),
    ],
)
def test_the_name_is_never_a_section_heading(tmp_path: Path, header: str, expected: str | None) -> None:
    source = tmp_path / "resume.txt"
    source.write_text(header, encoding="utf-8")
    assert parse_document(source, document_kind="RESUME").canonical["identity"]["legalName"] == expected
