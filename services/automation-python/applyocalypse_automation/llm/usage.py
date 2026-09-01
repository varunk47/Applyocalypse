"""Per-run accounting for what the LLM calls actually consumed.

The worker is one process per run, so module state here is run-scoped without
having to be told: nothing has to thread a ledger through four call sites and
back out again. Every completion passes through ``LiteLlmClient.complete_json``,
so that is the one place that records, and the document stage reads the totals
once at the end.

This exists because the prompt-caching work had no way to be checked. Sending a
stable prefix first and marking a breakpoint either produces cache reads or it
does not, and without the token counts coming back there was no answer either
way. ``cached_prompt_tokens`` is that answer.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CallUsage:
    """What a single completion consumed.

    ``cost_usd`` is None when litellm has no price for the model, which is the
    normal case for a self-hosted endpoint or a model released last week. None
    is kept distinct from 0.0 on purpose, so an unpriced call never reads as a
    free one.
    """

    schema_name: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cached_prompt_tokens: int
    cost_usd: float | None


_LOCK = threading.Lock()
_CALLS: list[CallUsage] = []


def _get(container: Any, name: str) -> Any:
    """Read one field from either a litellm response object or a plain dict.

    Real calls return a ModelResponse and tests hand back dicts, and both have
    to work here or the accounting only functions in production, which is where
    it is hardest to check.
    """
    if container is None:
        return None
    if isinstance(container, dict):
        return container.get(name)
    return getattr(container, name, None)


def _as_int(container: Any, name: str) -> int:
    value = _get(container, name)
    return int(value) if isinstance(value, (int, float)) else 0


def _cached_prompt_tokens(usage: Any) -> int:
    """Prompt tokens served from cache, however the provider reports them.

    Anthropic puts cache reads at the top level of usage; OpenAI and Deepseek
    nest theirs under ``prompt_tokens_details``. Reading both means the number
    is right whichever provider the user brought their own key for.
    """
    direct = _as_int(usage, "cache_read_input_tokens")
    if direct:
        return direct
    return _as_int(_get(usage, "prompt_tokens_details"), "cached_tokens")


def _cost_usd(response: Any) -> float | None:
    """What this call cost, from litellm's own price tables.

    Deliberately not a price list kept in this file. Rates change and models are
    added constantly, and a stale hardcoded table does something worse than
    failing: it reports a wrong number confidently instead of admitting it does
    not know. Returning None when litellm has no price keeps that distinction.
    """
    try:
        from litellm import completion_cost  # type: ignore
    except ImportError:
        return None
    try:
        value = completion_cost(completion_response=response)
    except Exception:
        # No price for this model: self-hosted, brand new, or behind a custom
        # OpenAI-compatible endpoint. Not knowing the cost is not an error.
        return None
    return float(value) if isinstance(value, (int, float)) else None


def record(*, schema_name: str, model: str, response: Any) -> None:
    """Record one completion, if the provider reported usage at all.

    A provider that returns no usage block is not an error worth failing a run
    over, so it is simply not counted, and the snapshot's call count will say so.
    """
    usage = _get(response, "usage")
    if usage is None:
        return
    call = CallUsage(
        schema_name=schema_name,
        model=model,
        prompt_tokens=_as_int(usage, "prompt_tokens"),
        completion_tokens=_as_int(usage, "completion_tokens"),
        cached_prompt_tokens=_cached_prompt_tokens(usage),
        cost_usd=_cost_usd(response),
    )
    with _LOCK:
        _CALLS.append(call)


def reset() -> None:
    """Drop everything recorded so far. For tests, and for reuse of a process."""
    with _LOCK:
        _CALLS.clear()


def snapshot() -> dict[str, Any]:
    """Totals so far, shaped for an event payload.

    ``cost_is_partial`` is the honest half of the cost figure: if any call had no
    price, the total is a floor rather than the amount spent, and a consumer that
    cannot tell those apart will quote the wrong number.
    """
    with _LOCK:
        calls = list(_CALLS)

    by_schema: dict[str, dict[str, Any]] = {}
    for call in calls:
        bucket = by_schema.setdefault(
            call.schema_name,
            {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cached_prompt_tokens": 0, "cost_usd": 0.0},
        )
        bucket["calls"] += 1
        bucket["prompt_tokens"] += call.prompt_tokens
        bucket["completion_tokens"] += call.completion_tokens
        bucket["cached_prompt_tokens"] += call.cached_prompt_tokens
        bucket["cost_usd"] += call.cost_usd or 0.0

    prompt_tokens = sum(call.prompt_tokens for call in calls)
    cached_prompt_tokens = sum(call.cached_prompt_tokens for call in calls)
    priced = [call.cost_usd for call in calls if call.cost_usd is not None]
    return {
        "calls": len(calls),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": sum(call.completion_tokens for call in calls),
        "cached_prompt_tokens": cached_prompt_tokens,
        # The number the caching work is judged by. Guarded because a run that
        # made no priced call still has to produce a payload rather than divide
        # by zero on the way out.
        "cache_hit_rate": round(cached_prompt_tokens / prompt_tokens, 4) if prompt_tokens else 0.0,
        "cost_usd": round(sum(priced), 6) if priced else None,
        "cost_is_partial": len(priced) < len(calls),
        "models": sorted({call.model for call in calls}),
        "by_schema": by_schema,
    }
