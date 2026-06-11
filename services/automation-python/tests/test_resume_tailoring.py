"""Tests for resume_tailoring: prompt generation, JSON parsing, and new keyword fields."""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

from applyocalypse_automation.resume_tailoring import (
    TailoredResumeSections,
    build_tailor_system_prompt,
    tailor_resume_sections,
)


# ---------------------------------------------------------------------------
# Prompt generation
# ---------------------------------------------------------------------------


def test_build_prompt_font10_includes_correct_limits() -> None:
    prompt = build_tailor_system_prompt(10)
    assert "125" in prompt
    assert "240" in prompt
    assert "font size 10" in prompt


def test_build_prompt_font11_includes_correct_limits() -> None:
    prompt = build_tailor_system_prompt(11)
    assert "115" in prompt
    assert "220" in prompt
    assert "font size 11" in prompt


def test_build_prompt_unknown_font_falls_back_to_font10() -> None:
    prompt = build_tailor_system_prompt(99)
    assert "125" in prompt
    assert "240" in prompt


def test_build_prompt_contains_gap_analysis_step() -> None:
    prompt = build_tailor_system_prompt()
    assert "Step 1" in prompt
    assert "Gap analysis" in prompt
    assert "Step 2" in prompt


def test_build_prompt_contains_banned_word_list() -> None:
    prompt = build_tailor_system_prompt()
    for word in ("leverage", "utilize", "spearheaded", "robust"):
        assert word in prompt, f"banned word '{word}' missing from prompt"


def test_build_prompt_includes_new_json_keys() -> None:
    prompt = build_tailor_system_prompt()
    assert "missing_keywords_ranked" in prompt
    assert "unclaimable_keywords" in prompt


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FULL_RESPONSE = {
    "missing_keywords_ranked": ["Kubernetes", "CI/CD", "gRPC"],
    "unclaimable_keywords": ["FPGA", "VHDL"],
    "summary": "Software engineer with 5 years of distributed systems experience.",
    "skills": ["Python", "Go", "Kubernetes"],
    "work_experience": [
        {
            "company": "DataCo",
            "role": "Senior Engineer",
            "bullets": ["Reduced pipeline latency by 40% via async processing."],
        }
    ],
    "projects": [
        {
            "name": "Open Mesh",
            "bullets": ["Built an open-source service mesh handling 50k RPS."],
        }
    ],
}

_LEGACY_RESPONSE = {
    "summary": "Python developer.",
    "skills": ["Python"],
    "work_experience": [],
    "projects": [],
}


def _client_returning(response: dict[str, Any]) -> Any:
    async def _complete(*, system: str, user: str, schema_name: str) -> dict[str, Any]:
        return response
    c = AsyncMock()
    c.complete_json = _complete
    return c


# ---------------------------------------------------------------------------
# Parsing — new keys present
# ---------------------------------------------------------------------------


def test_tailor_resume_sections_parses_missing_keywords() -> None:
    result = asyncio.run(tailor_resume_sections(
        job_description="Need Kubernetes and CI/CD experience.",
        resume_text="Python developer.",
        llm_client=_client_returning(_FULL_RESPONSE),
    ))
    assert result is not None
    assert result.missing_keywords_ranked == ["Kubernetes", "CI/CD", "gRPC"]


def test_tailor_resume_sections_parses_unclaimable_keywords() -> None:
    result = asyncio.run(tailor_resume_sections(
        job_description="Need FPGA and VHDL.",
        resume_text="Python developer.",
        llm_client=_client_returning(_FULL_RESPONSE),
    ))
    assert result is not None
    assert result.unclaimable_keywords == ["FPGA", "VHDL"]


def test_tailor_resume_sections_parses_existing_keys() -> None:
    result = asyncio.run(tailor_resume_sections(
        job_description="JD",
        resume_text="Resume",
        llm_client=_client_returning(_FULL_RESPONSE),
    ))
    assert result is not None
    assert result.summary.startswith("Software engineer")
    assert "Python" in result.skills
    assert len(result.work_experience) == 1
    assert len(result.projects) == 1


# ---------------------------------------------------------------------------
# Backward compat — new keys absent (legacy LLM response)
# ---------------------------------------------------------------------------


def test_tailor_resume_sections_tolerates_absent_new_keys() -> None:
    result = asyncio.run(tailor_resume_sections(
        job_description="JD",
        resume_text="Resume",
        llm_client=_client_returning(_LEGACY_RESPONSE),
    ))
    assert result is not None
    assert result.missing_keywords_ranked == []
    assert result.unclaimable_keywords == []


def test_to_dict_includes_new_keys() -> None:
    sections = TailoredResumeSections(
        summary="A summary.",
        skills=["Python"],
        work_experience=[],
        projects=[],
        missing_keywords_ranked=["Kubernetes"],
        unclaimable_keywords=["VHDL"],
    )
    d = sections.to_dict()
    assert d["missing_keywords_ranked"] == ["Kubernetes"]
    assert d["unclaimable_keywords"] == ["VHDL"]


def test_to_dict_new_keys_default_empty() -> None:
    sections = TailoredResumeSections(
        summary="S",
        skills=[],
        work_experience=[],
        projects=[],
    )
    d = sections.to_dict()
    assert d["missing_keywords_ranked"] == []
    assert d["unclaimable_keywords"] == []


# ---------------------------------------------------------------------------
# font_size parameter flows into prompt
# ---------------------------------------------------------------------------


def test_font_size_parameter_flows_to_system_prompt() -> None:
    calls: list[str] = []

    async def _capture(*, system: str, user: str, schema_name: str) -> dict[str, Any]:
        calls.append(system)
        return _FULL_RESPONSE

    c = AsyncMock()
    c.complete_json = _capture

    asyncio.run(tailor_resume_sections(
        job_description="JD",
        resume_text="Resume",
        llm_client=c,
        font_size=11,
    ))
    assert calls, "complete_json was not called"
    assert "font size 11" in calls[0]
    assert "115" in calls[0]


# ---------------------------------------------------------------------------
# Retry
# ---------------------------------------------------------------------------


def test_tailor_resume_sections_retries_on_missing_keys() -> None:
    call_count = [0]

    async def _flaky(*, system: str, user: str, schema_name: str) -> dict[str, Any]:
        call_count[0] += 1
        if call_count[0] == 1:
            return {"summary": "partial"}
        return _FULL_RESPONSE

    c = AsyncMock()
    c.complete_json = _flaky

    result = asyncio.run(tailor_resume_sections(
        job_description="JD",
        resume_text="Resume",
        llm_client=c,
    ))
    assert result is not None
    assert call_count[0] == 2


def test_tailor_resume_sections_returns_none_after_two_failures() -> None:
    async def _bad(*, system: str, user: str, schema_name: str) -> dict[str, Any]:
        return {"summary": "no keys"}

    c = AsyncMock()
    c.complete_json = _bad

    result = asyncio.run(tailor_resume_sections(
        job_description="JD",
        resume_text="Resume",
        llm_client=c,
    ))
    assert result is None
