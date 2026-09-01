from __future__ import annotations

import asyncio
from typing import Any

import litellm
import pytest

from applyocalypse_automation.llm.litellm_client import LiteLlmClient, _parse_json_response

FENCED = '```json\n{"role": "Staff Engineer"}\n```'
FENCED_NO_LANGUAGE = '```\n{"role": "Staff Engineer"}\n```'
PREAMBLE = 'Here is the tailored resume:\n\n{"role": "Staff Engineer"}'
PREAMBLE_AND_FENCE = 'Sure! Here you go:\n\n```json\n{"role": "Staff Engineer"}\n```\n\nLet me know if you want changes.'
NESTED = '```json\n{"sections": {"summary": {"text": "ok"}}, "bullets": [{"text": "shipped"}]}\n```'


@pytest.mark.parametrize(
    ("label", "content", "expected"),
    [
        ("bare_object", '{"role": "Staff Engineer"}', {"role": "Staff Engineer"}),
        ("fenced_with_language", FENCED, {"role": "Staff Engineer"}),
        ("fenced_without_language", FENCED_NO_LANGUAGE, {"role": "Staff Engineer"}),
        ("preamble_then_object", PREAMBLE, {"role": "Staff Engineer"}),
        ("preamble_fence_and_epilogue", PREAMBLE_AND_FENCE, {"role": "Staff Engineer"}),
        ("leading_and_trailing_whitespace", '\n\n  {"role": "Staff Engineer"}  \n', {"role": "Staff Engineer"}),
        (
            "nested_objects_and_arrays",
            NESTED,
            {"sections": {"summary": {"text": "ok"}}, "bullets": [{"text": "shipped"}]},
        ),
        # The strict attempt handles this one, which is the point: a brace inside a
        # string value would defeat the span search if it ever got that far.
        ("brace_inside_a_string_value", '{"note": "closes with }"}', {"note": "closes with }"}),
    ],
)
def test_the_object_is_recovered_however_the_model_wrapped_it(label: str, content: str, expected: dict[str, Any]) -> None:
    assert _parse_json_response(content, "ResumeTailoring") == expected


@pytest.mark.parametrize(
    ("label", "content"),
    [
        ("prose_only", "I cannot help with that request."),
        ("empty", ""),
        ("whitespace_only", "   \n  "),
        ("braces_but_not_json", "use the {placeholder} token"),
        ("truncated_object", '{"role": "Staff Engineer"'),
        ("fence_with_no_object", "```json\n```"),
    ],
)
def test_content_with_no_object_in_it_still_raises_value_error(label: str, content: str) -> None:
    """ValueError, not RuntimeError, so the callers' retry branches keep working."""
    with pytest.raises(ValueError, match="was not valid JSON"):
        _parse_json_response(content, "ResumeTailoring")


def test_a_fenced_response_now_survives_the_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    """The wiring: what used to raise on the way out of the client now returns a dict."""

    async def fake_acompletion(**_: Any) -> dict[str, Any]:
        return {"choices": [{"message": {"content": FENCED}}]}

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    result = asyncio.run(LiteLlmClient(model="openrouter/mistralai/mistral-7b-instruct").complete_json(system="s", user="u", schema_name="ResumeTailoring"))
    assert result == {"role": "Staff Engineer"}


def test_a_json_array_is_still_rejected_as_not_an_object(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unchanged behaviour, asserted so the tolerant parse cannot quietly widen it."""

    async def fake_acompletion(**_: Any) -> dict[str, Any]:
        return {"choices": [{"message": {"content": '["a", "b"]'}}]}

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    with pytest.raises(RuntimeError, match="must be a JSON object"):
        asyncio.run(LiteLlmClient(model="gpt-4o-mini").complete_json(system="s", user="u", schema_name="JdAnalysis"))
