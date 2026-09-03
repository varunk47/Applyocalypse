from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import litellm
import pytest

from applyocalypse_automation.llm import usage
from applyocalypse_automation.llm.litellm_client import LiteLlmClient


@pytest.fixture(autouse=True)
def _clean_ledger() -> Any:
    """The ledger is module state, so a test that leaks poisons every later one."""
    usage.reset()
    yield
    usage.reset()


@pytest.fixture(autouse=True)
def _no_pricing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default to an unpriced model so cost assertions are opt-in, not incidental.

    Otherwise every test's numbers would depend on litellm's shipped price table,
    which changes with the dependency.
    """
    monkeypatch.setattr(litellm, "completion_cost", lambda **_: (_ for _ in ()).throw(Exception("no price")))


def _openai_usage(prompt: int, completion: int, cached: int) -> dict[str, Any]:
    return {"usage": {"prompt_tokens": prompt, "completion_tokens": completion, "prompt_tokens_details": {"cached_tokens": cached}}}


def _anthropic_usage(prompt: int, completion: int, cached: int) -> dict[str, Any]:
    return {"usage": {"prompt_tokens": prompt, "completion_tokens": completion, "cache_read_input_tokens": cached}}


@pytest.mark.parametrize(
    ("label", "response", "expected"),
    [
        ("openai_nested_cache", _openai_usage(1000, 50, 800), (1000, 50, 800)),
        ("anthropic_top_level_cache", _anthropic_usage(1000, 50, 800), (1000, 50, 800)),
        ("no_cache_reported", {"usage": {"prompt_tokens": 300, "completion_tokens": 20}}, (300, 20, 0)),
        ("zero_cached_tokens", _openai_usage(300, 20, 0), (300, 20, 0)),
        (
            "object_style_response",
            SimpleNamespace(usage=SimpleNamespace(prompt_tokens=42, completion_tokens=7, cache_read_input_tokens=12)),
            (42, 7, 12),
        ),
    ],
)
def test_record_reads_usage_from_every_provider_shape(label: str, response: Any, expected: tuple[int, int, int]) -> None:
    usage.record(schema_name=label, model="gpt-4o-mini", response=response)
    snapshot = usage.snapshot()
    assert snapshot["calls"] == 1
    assert (snapshot["prompt_tokens"], snapshot["completion_tokens"], snapshot["cached_prompt_tokens"]) == expected


@pytest.mark.parametrize(
    ("label", "response"),
    [
        ("no_usage_key", {"choices": [{"message": {"content": "{}"}}]}),
        ("usage_is_none", {"usage": None}),
        ("response_is_none", None),
    ],
)
def test_a_response_without_usage_is_not_counted(label: str, response: Any) -> None:
    """Providers that report nothing must not fail a run, and must not be counted as zero."""
    usage.record(schema_name=label, model="gpt-4o-mini", response=response)
    assert usage.snapshot()["calls"] == 0


def test_snapshot_aggregates_and_buckets_by_schema() -> None:
    usage.record(schema_name="JdAnalysis", model="gpt-4o-mini", response=_openai_usage(1000, 100, 0))
    usage.record(schema_name="ResumeTailoring", model="gpt-4o-mini", response=_openai_usage(2000, 200, 1500))
    usage.record(schema_name="ResumeTailoring", model="gpt-4o-mini", response=_openai_usage(2000, 200, 1500))

    snapshot = usage.snapshot()
    assert snapshot["calls"] == 3
    assert snapshot["prompt_tokens"] == 5000
    assert snapshot["completion_tokens"] == 500
    assert snapshot["cached_prompt_tokens"] == 3000
    assert snapshot["by_schema"]["ResumeTailoring"]["calls"] == 2
    assert snapshot["by_schema"]["ResumeTailoring"]["prompt_tokens"] == 4000
    assert snapshot["by_schema"]["JdAnalysis"]["calls"] == 1


@pytest.mark.parametrize(
    ("label", "prompt_tokens", "cached", "expected_rate"),
    [
        ("all_cached", 1000, 1000, 1.0),
        ("half_cached", 1000, 500, 0.5),
        ("none_cached", 1000, 0, 0.0),
        ("no_tokens_at_all", 0, 0, 0.0),
    ],
)
def test_cache_hit_rate(label: str, prompt_tokens: int, cached: int, expected_rate: float) -> None:
    """The number the prompt-caching work is judged by, including the divide-by-zero case."""
    usage.record(schema_name=label, model="gpt-4o-mini", response=_openai_usage(prompt_tokens, 10, cached))
    assert usage.snapshot()["cache_hit_rate"] == expected_rate


def test_cost_is_summed_and_flagged_partial_when_a_model_has_no_price(monkeypatch: pytest.MonkeyPatch) -> None:
    prices = {"priced-model": 0.25}

    def fake_cost(**kwargs: Any) -> float:
        model = kwargs["completion_response"]["model"]
        if model not in prices:
            raise Exception("no price for model")
        return prices[model]

    monkeypatch.setattr(litellm, "completion_cost", fake_cost)

    usage.record(schema_name="A", model="priced-model", response={**_openai_usage(10, 1, 0), "model": "priced-model"})
    usage.record(schema_name="B", model="priced-model", response={**_openai_usage(10, 1, 0), "model": "priced-model"})
    snapshot = usage.snapshot()
    assert snapshot["cost_usd"] == 0.5
    assert snapshot["cost_is_partial"] is False

    usage.record(schema_name="C", model="mystery-model", response={**_openai_usage(10, 1, 0), "model": "mystery-model"})
    snapshot = usage.snapshot()
    # An unpriced call must not read as a free one: the total stays a floor and says so.
    assert snapshot["cost_usd"] == 0.5
    assert snapshot["cost_is_partial"] is True


def test_cost_is_none_when_nothing_could_be_priced() -> None:
    """None rather than 0.0, so 'we do not know' never renders as 'it was free'."""
    usage.record(schema_name="A", model="mystery-model", response=_openai_usage(10, 1, 0))
    assert usage.snapshot()["cost_usd"] is None


def test_complete_json_records_the_call_it_made(monkeypatch: pytest.MonkeyPatch) -> None:
    """The wiring itself: a real completion through the client lands in the ledger."""

    async def fake_acompletion(**_: Any) -> dict[str, Any]:
        return {"choices": [{"message": {"content": '{"ok": true}'}}], **_anthropic_usage(4000, 120, 3200)}

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    result = asyncio.run(LiteLlmClient(model="claude-3-5-sonnet-20241022").complete_json(system="s", user="u", schema_name="JdAnalysis"))
    assert result == {"ok": True}

    snapshot = usage.snapshot()
    assert snapshot["calls"] == 1
    assert snapshot["cached_prompt_tokens"] == 3200
    assert snapshot["cache_hit_rate"] == 0.8
    assert snapshot["models"] == ["claude-3-5-sonnet-20241022"]
    assert snapshot["by_schema"]["JdAnalysis"]["prompt_tokens"] == 4000


def test_a_malformed_completion_is_still_billed_and_still_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tokens are spent whether or not the JSON parses, so the ledger records them either way."""

    async def fake_acompletion(**_: Any) -> dict[str, Any]:
        return {"choices": [{"message": {"content": "not json at all"}}], **_openai_usage(500, 30, 0)}

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    with pytest.raises(ValueError):
        asyncio.run(LiteLlmClient(model="gpt-4o-mini").complete_json(system="s", user="u", schema_name="JdAnalysis"))

    assert usage.snapshot()["prompt_tokens"] == 500
