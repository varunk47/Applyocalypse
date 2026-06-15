"""Tests for cover_letter_tailoring.generate_cover_letter."""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

from applyocalypse_automation.cover_letter_tailoring import (
    COVER_LETTER_SYSTEM_PROMPT,
    GeneratedCoverLetter,
    _build_user_message,
    generate_cover_letter,
)
from applyocalypse_automation.validation import BANNED_WORDS

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_CL = (
    "Dear Hiring Team,\n\n"
    "My background in distributed systems aligns closely with the principal "
    "engineer role at Acme Corp. Over the past four years at DataStream I "
    "reduced end-to-end pipeline latency by 60 percent by redesigning the "
    "Kafka consumer topology, an achievement directly relevant to the "
    "high-throughput ingestion requirements you describe.\n\n"
    "I hold a strong command of Go and Python and have led cross-functional "
    "teams through two major platform migrations. My communication style "
    "focuses on outcomes and I thrive in ambiguous problem spaces.\n\n"
    "Thank you for considering my application. I look forward to discussing "
    "how my work can contribute to Acme's engineering goals.\n\n"
    "Best regards,\n"
    "Alex Kim"
)

_PROFILE = {
    "profile": {"legalName": "Alex Kim"},
    "experience": [
        {
            "title": "Senior Engineer",
            "company": "DataStream",
            "bullets": [
                "Reduced Kafka pipeline latency by 60%.",
                "Led team of 5 engineers through platform migration.",
            ],
        }
    ],
}

_JD = "We need a principal engineer with Go and Python skills for high-throughput data pipelines."


def _fake_client(response: dict[str, Any] | Exception, *, call_count: list[int] | None = None) -> Any:
    """Return a mock LLM client whose complete_json returns the given response."""
    calls: list[int] = call_count if call_count is not None else []

    async def _complete_json(*, system: str, user: str, schema_name: str) -> dict[str, Any]:
        calls.append(1)
        if isinstance(response, Exception):
            raise response
        return response

    client = AsyncMock()
    client.complete_json = _complete_json
    return client


def _two_response_client(first: dict[str, Any], second: dict[str, Any]) -> Any:
    """Return a client that returns first on attempt 1 and second on attempt 2."""
    responses = [first, second]
    index = [0]

    async def _complete_json(*, system: str, user: str, schema_name: str) -> dict[str, Any]:
        resp = responses[index[0]]
        index[0] = min(index[0] + 1, len(responses) - 1)
        return resp

    client = AsyncMock()
    client.complete_json = _complete_json
    return client


# ---------------------------------------------------------------------------
# Tests: successful generation
# ---------------------------------------------------------------------------


def test_generate_cover_letter_returns_generated_cover_letter() -> None:
    client = _fake_client({"cover_letter_text": _VALID_CL})
    result = asyncio.run(
        generate_cover_letter(
            job_description=_JD,
            canonical_profile=_PROFILE,
            llm_client=client,
        )
    )
    assert isinstance(result, GeneratedCoverLetter)
    assert result.text == _VALID_CL


def test_generate_cover_letter_with_sample_text_passes_snippet_in_prompt() -> None:
    calls: list[tuple[str, str]] = []

    async def _capture(*, system: str, user: str, schema_name: str) -> dict[str, Any]:
        calls.append((system, user))
        return {"cover_letter_text": _VALID_CL}

    client = AsyncMock()
    client.complete_json = _capture

    sample = "Dear Team, I bring ten years of distributed systems experience."
    asyncio.run(
        generate_cover_letter(
            job_description=_JD,
            canonical_profile=_PROFILE,
            cover_letter_sample=sample,
            llm_client=client,
        )
    )
    assert calls, "complete_json was not called"
    user_msg = calls[0][1]
    assert "CANDIDATE'S OWN COVER LETTER SAMPLE" in user_msg
    assert sample[:50] in user_msg


def test_generate_cover_letter_no_sample_omits_sample_section() -> None:
    calls: list[tuple[str, str]] = []

    async def _capture(*, system: str, user: str, schema_name: str) -> dict[str, Any]:
        calls.append((system, user))
        return {"cover_letter_text": _VALID_CL}

    client = AsyncMock()
    client.complete_json = _capture

    asyncio.run(
        generate_cover_letter(
            job_description=_JD,
            canonical_profile=_PROFILE,
            llm_client=client,
        )
    )
    user_msg = calls[0][1]
    assert "CANDIDATE'S OWN COVER LETTER SAMPLE" not in user_msg


# ---------------------------------------------------------------------------
# Tests: validation failure triggers retry
# ---------------------------------------------------------------------------


def test_generate_cover_letter_retries_when_banned_word_present() -> None:
    banned_cl = _VALID_CL.replace("aligns closely", "leverage aligns")
    call_count: list[int] = []
    client = _fake_client({"cover_letter_text": banned_cl}, call_count=call_count)

    result = asyncio.run(
        generate_cover_letter(
            job_description=_JD,
            canonical_profile=_PROFILE,
            llm_client=client,
        )
    )
    assert result is None
    assert len(call_count) == 2, "Should have retried exactly once"


def test_generate_cover_letter_second_attempt_succeeds_after_validation_failure() -> None:
    banned_cl = "Dear Hiring Team,\nI leverage my skills.\nThank you.\nBest regards,\nAlex"
    client = _two_response_client(
        {"cover_letter_text": banned_cl},
        {"cover_letter_text": _VALID_CL},
    )

    result = asyncio.run(
        generate_cover_letter(
            job_description=_JD,
            canonical_profile=_PROFILE,
            llm_client=client,
        )
    )
    assert result is not None
    assert result.text == _VALID_CL


def test_generate_cover_letter_returns_none_when_both_attempts_fail() -> None:
    too_long = "word " * 460
    client = _fake_client({"cover_letter_text": too_long.strip()})

    result = asyncio.run(
        generate_cover_letter(
            job_description=_JD,
            canonical_profile=_PROFILE,
            llm_client=client,
        )
    )
    assert result is None


def test_generate_cover_letter_returns_none_on_llm_exception() -> None:
    client = _fake_client(RuntimeError("network timeout"))

    result = asyncio.run(
        generate_cover_letter(
            job_description=_JD,
            canonical_profile=_PROFILE,
            llm_client=client,
        )
    )
    assert result is None


# ---------------------------------------------------------------------------
# Tests: em dash stripping
# ---------------------------------------------------------------------------


def test_generate_cover_letter_strips_markdown_bold_markers() -> None:
    cl_with_bold = _VALID_CL.replace("distributed systems", "**distributed systems**")
    client = _fake_client({"cover_letter_text": cl_with_bold})

    result = asyncio.run(
        generate_cover_letter(
            job_description=_JD,
            canonical_profile=_PROFILE,
            llm_client=client,
        )
    )
    assert result is not None
    assert "**" not in result.text
    assert "distributed systems" in result.text


# ---------------------------------------------------------------------------
# Tests: GeneratedCoverLetter.word_count
# ---------------------------------------------------------------------------


def test_generated_cover_letter_word_count() -> None:
    gcl = GeneratedCoverLetter(text="Hello world this is four words and more.")
    assert gcl.word_count() == 8


def test_generated_cover_letter_word_count_empty() -> None:
    gcl = GeneratedCoverLetter(text="   ")
    assert gcl.word_count() == 0


# ---------------------------------------------------------------------------
# Tests: _build_user_message
# ---------------------------------------------------------------------------


def test_build_user_message_includes_candidate_name() -> None:
    msg = _build_user_message(
        job_description="Some JD",
        canonical_profile=_PROFILE,
        cover_letter_sample=None,
    )
    assert "Alex Kim" in msg


def test_build_user_message_includes_experience_bullets() -> None:
    msg = _build_user_message(
        job_description="Some JD",
        canonical_profile=_PROFILE,
        cover_letter_sample=None,
    )
    assert "DataStream" in msg
    assert "Reduced Kafka pipeline latency" in msg


def test_build_user_message_handles_empty_profile_gracefully() -> None:
    msg = _build_user_message(
        job_description="JD text",
        canonical_profile={},
        cover_letter_sample=None,
    )
    assert "Candidate" in msg
    assert "JD text" in msg


def test_build_user_message_truncates_sample_to_1200_chars() -> None:
    long_sample = "x" * 2000
    msg = _build_user_message(
        job_description="JD",
        canonical_profile=_PROFILE,
        cover_letter_sample=long_sample,
    )
    assert "x" * 1200 in msg
    assert "x" * 1201 not in msg


def test_system_prompt_matches_validator_banned_words() -> None:
    for word in BANNED_WORDS:
        assert word in COVER_LETTER_SYSTEM_PROMPT
    assert "—" not in COVER_LETTER_SYSTEM_PROMPT
