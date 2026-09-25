import asyncio
import json

import httpx
import pytest

from applyocalypse_automation import secret_env
from applyocalypse_automation.browser.jev_client import (
    JEV_ENDPOINT,
    JEV_KEY_NAME,
    JEV_MODEL,
    JevError,
    ask_jev,
    jev_configured,
)

FAKE_KEY = "vck_test_not_a_real_key"
QUESTIONS = {"is_signup": {"type": "noul", "instructions": "Is this an account creation form?"}}


@pytest.fixture(autouse=True)
def gateway_key(monkeypatch):
    monkeypatch.delenv("APPLYO_SECRETS_FILE", raising=False)
    monkeypatch.setenv(JEV_KEY_NAME, FAKE_KEY)
    secret_env._secrets_from_file.cache_clear()
    yield
    secret_env._secrets_from_file.cache_clear()


class Recorder:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        reply = self.responses.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


async def _no_sleep(_seconds: float) -> None:
    return None


def ask(recorder: Recorder):
    return asyncio.run(
        ask_jev("A form with Email and two Password fields.", QUESTIONS,
                transport=httpx.MockTransport(recorder), sleep=_no_sleep)
    )


def ok(answers):
    return httpx.Response(200, json={"answers": answers, "usage": {"input_tokens": 42}})


def test_a_request_carries_the_model_state_questions_and_bearer_key():
    recorder = Recorder(ok({"is_signup": {"type": "noul", "noul": 0.97}}))

    result = ask(recorder)

    request = recorder.requests[0]
    assert str(request.url) == JEV_ENDPOINT
    assert request.headers["authorization"] == f"Bearer {FAKE_KEY}"
    body = json.loads(request.content)
    assert body["model"] == JEV_MODEL
    assert body["questions"] == QUESTIONS
    assert result.answers["is_signup"]["noul"] == 0.97
    assert result.input_tokens == 42


@pytest.mark.parametrize(
    "first",
    [httpx.Response(429, json={}), httpx.Response(503, text="busy"), httpx.ConnectError("down")],
)
def test_transient_failures_are_retried(first):
    recorder = Recorder(first, ok({"is_signup": {"type": "noul", "noul": 0.5}}))

    assert ask(recorder).answers["is_signup"]["noul"] == 0.5
    assert len(recorder.requests) == 2


def test_a_rejected_request_is_not_retried_and_names_the_gateway_error():
    body = {"error": {"message": "add a card", "type": "customer_verification_required"}}
    recorder = Recorder(httpx.Response(403, json=body))

    with pytest.raises(JevError, match="403: customer_verification_required"):
        ask(recorder)
    assert len(recorder.requests) == 1


def test_retries_stop_after_the_limit():
    recorder = Recorder(*[httpx.Response(500, text="x")] * 3)

    with pytest.raises(JevError, match="HTTP 500"):
        ask(recorder)
    assert len(recorder.requests) == 3


def test_errors_never_contain_the_key():
    recorder = Recorder(httpx.Response(401, text=f"invalid key {FAKE_KEY}"))

    with pytest.raises(JevError) as caught:
        ask(recorder)
    assert FAKE_KEY not in str(caught.value)


def test_a_missing_key_fails_before_any_request(monkeypatch):
    monkeypatch.delenv(JEV_KEY_NAME)
    recorder = Recorder()

    assert not jev_configured()
    with pytest.raises(JevError, match="not set"):
        ask(recorder)
    assert recorder.requests == []


def test_a_reply_without_answers_is_an_error():
    recorder = Recorder(httpx.Response(200, json={"usage": {}}))

    with pytest.raises(JevError, match="no answers"):
        ask(recorder)
