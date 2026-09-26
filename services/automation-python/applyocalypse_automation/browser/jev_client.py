"""Client for Jev (TypeSafe System One) through the Vercel AI Gateway.

Ported from jev-browser's `src/jev.mjs` (MIT, Ying-Kai Liao). Jev never writes
text: it takes a state string plus typed questions and returns a probability
(`noul`), a distribution over named options (`choice`) or a score per question.
Every value the worker types into a page still comes from the answer engine.

The gateway key arrives in the 0600 worker secrets file like every other
provider key, and is never logged or put in an error message.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx

from ..secret_env import get_secret

JEV_ENDPOINT = "https://ai-gateway.vercel.sh/typesafe/v1/systemone"
JEV_MODEL = "typesafe-ai/jev"
JEV_KEY_NAME = "AI_GATEWAY_API_KEY"
JEV_TIMEOUT_S = 30.0
JEV_RETRIES = 2
JEV_RETRY_BACKOFF_S = 0.8
# The upstream model answers 429 "high demand" for minutes at a time. That is a
# queue, not a failure, so it gets its own, much longer budget.
JEV_BUSY_RETRIES = 36
JEV_BUSY_WAIT_S = 10.0


class JevError(RuntimeError):
    """A Jev request failed. The message never contains the key."""


@dataclass(frozen=True)
class JevResult:
    answers: dict[str, dict[str, Any]]
    input_tokens: int


def jev_configured() -> bool:
    return bool(get_secret(JEV_KEY_NAME))


async def ask_jev(
    state: str,
    questions: dict[str, dict[str, Any]],
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    on_busy: Callable[[int], None] | None = None,
) -> JevResult:
    """Ask Jev every question about `state` in one request.

    Network errors and 5xx are retried twice with a linear backoff. A 429 means
    the model is busy, so it is waited out for up to six minutes, calling
    `on_busy` with the attempt number each time. Any other status fails at once,
    since resending a rejected request cannot succeed.
    """
    key = get_secret(JEV_KEY_NAME)
    if not key:
        raise JevError(f"{JEV_KEY_NAME} is not set")
    body = {"model": JEV_MODEL, "state": state, "questions": questions}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    failures = 0
    busy = 0
    async with httpx.AsyncClient(timeout=JEV_TIMEOUT_S, transport=transport) as client:
        while True:
            try:
                response = await client.post(JEV_ENDPOINT, json=body, headers=headers)
            except httpx.HTTPError as exc:
                if failures == JEV_RETRIES:
                    raise JevError(f"Jev request failed: {type(exc).__name__}") from None
                failures += 1
                await sleep(JEV_RETRY_BACKOFF_S * failures)
                continue
            if response.status_code == 200:
                return _parse(response)
            if response.status_code == 429 and busy < JEV_BUSY_RETRIES:
                busy += 1
                if on_busy is not None:
                    on_busy(busy)
                await sleep(JEV_BUSY_WAIT_S)
                continue
            if response.status_code >= 500 and failures < JEV_RETRIES:
                failures += 1
                await sleep(JEV_RETRY_BACKOFF_S * failures)
                continue
            detail = _error_detail(response).replace(key, "***")
            raise JevError(f"Jev returned HTTP {response.status_code}: {detail}")


def _parse(response: httpx.Response) -> JevResult:
    try:
        data = response.json()
    except ValueError:
        raise JevError("Jev returned a body that is not JSON") from None
    answers = data.get("answers") if isinstance(data, dict) else None
    if not isinstance(answers, dict):
        raise JevError("Jev response has no answers")
    usage = data.get("usage") or {}
    return JevResult(answers=answers, input_tokens=int(usage.get("input_tokens") or 0))


def _error_detail(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text[:200]
    error = data.get("error", data) if isinstance(data, dict) else {}
    if isinstance(error, dict):
        return str(error.get("type") or error.get("error_type") or error.get("message") or "")[:200]
    return str(error)[:200]
