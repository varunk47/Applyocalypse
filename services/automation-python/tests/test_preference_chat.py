from __future__ import annotations

import asyncio
from typing import Any

import pytest

from applyocalypse_automation.preference_chat import chat_preferences, normalize_proposal, rule_proposals


def _filter(kind: str, value: str) -> dict[str, str]:
    return {"type": "job_filter", "kind": kind, "value": value}


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Skip jobs at Initech.", [_filter("skip_company", "Initech")]),
        ("Never apply to Globex and Hooli", [_filter("skip_company", "Globex"), _filter("skip_company", "Hooli")]),
        ("Skip anything mentioning security clearance", [_filter("skip_keyword", "security clearance")]),
        ("My minimum salary is 120k", [_filter("min_salary", "120000")]),
        ("Pay of at least $95,000 please", [_filter("min_salary", "95000")]),
        ("Remote or hybrid only", [_filter("work_arrangement", "remote"), _filter("work_arrangement", "hybrid")]),
        ("I only want jobs in Denver or Boulder", [_filter("place", "Denver"), _filter("place", "Boulder")]),
        (
            "My parents' place is 1 Beacon St, Boston, MA 02108",
            [{"type": "address", "label": "Parents", "addressLine1": "1 Beacon St", "addressLine2": "",
              "city": "Boston", "state": "MA", "postalCode": "02108", "country": ""}],
        ),
        (
            "When they ask about notice period, say 2 weeks",
            [{"type": "answer_rule", "question": "notice period", "answer": "2 weeks", "conditions": {}}],
        ),
        (
            "If a form asks for start date, answer January 5 for Initech jobs",
            [{"type": "answer_rule", "question": "start date", "answer": "January 5", "conditions": {"company": "Initech"}}],
        ),
        ("I had a great day today", []),
        ("I worked remote last year", []),
    ],
)
def test_rule_proposals(message: str, expected: list[dict[str, Any]]) -> None:
    assert rule_proposals(message) == expected


def test_several_sentences_each_become_proposals() -> None:
    proposals = rule_proposals("Skip jobs at Initech. Remote only. Minimum salary 100k.")

    assert [p["kind"] for p in proposals] == ["skip_company", "work_arrangement", "min_salary"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"type": "job_filter", "kind": "min_salary", "value": "$130k"}, _filter("min_salary", "130000")),
        ({"type": "job_filter", "kind": "work_arrangement", "value": "On-site"}, _filter("work_arrangement", "onsite")),
        ({"type": "job_filter", "kind": "work_arrangement", "value": "sometimes"}, None),
        ({"type": "job_filter", "kind": "delete_everything", "value": "x"}, None),
        ({"type": "address", "city": " "}, None),
        ({"type": "answer_rule", "question": "Relocate?", "answer": ""}, None),
        (
            {"type": "answer_rule", "question": "Relocate?", "answer": "Yes — anywhere", "conditions": {"salary": "x"}},
            {"type": "answer_rule", "question": "Relocate?", "answer": "Yes, anywhere", "conditions": {}},
        ),
        ("not a dict", None),
    ],
)
def test_normalize_proposal(raw: object, expected: dict[str, Any] | None) -> None:
    assert normalize_proposal(raw) == expected


class _FakeModel:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict[str, str]] = []

    async def complete_json(self, *, system: str, user: str, schema_name: str) -> object:
        self.calls.append({"system": system, "user": user})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_the_model_answers_when_configured_and_bad_proposals_are_dropped() -> None:
    model = _FakeModel({
        "reply": "Saved two things — check them.",
        "proposals": [_filter("skip_company", "Initech"), {"type": "job_filter", "kind": "bogus", "value": "x"}],
    })

    result = asyncio.run(chat_preferences("no Initech please", {"jobFilters": []}, client=model))  # type: ignore[arg-type]

    assert result == {"reply": "Saved two things, check them.", "proposals": [_filter("skip_company", "Initech")],
                      "source": "model"}
    assert "no Initech please" in model.calls[0]["user"]


def test_a_failing_model_falls_back_to_the_rules() -> None:
    result = asyncio.run(chat_preferences("Remote only", client=_FakeModel(RuntimeError("down"))))  # type: ignore[arg-type]

    assert result["source"] == "rules"
    assert result["proposals"] == [_filter("work_arrangement", "remote")]


def test_without_a_model_an_unreadable_message_explains_how_to_phrase_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LITELLM_MODEL_FAST", raising=False)
    monkeypatch.delenv("LITELLM_MODEL", raising=False)

    result = asyncio.run(chat_preferences("hello there"))

    assert result["proposals"] == []
    assert "model key" in result["reply"]
    assert "—" not in result["reply"]


def test_the_pipeline_command_prints_the_reply_as_json(tmp_path, monkeypatch, capsys) -> None:
    import json
    import sys

    from applyocalypse_automation import pipeline_cli

    monkeypatch.delenv("LITELLM_MODEL_FAST", raising=False)
    monkeypatch.delenv("LITELLM_MODEL", raising=False)
    request = tmp_path / "chat.json"
    request.write_text(json.dumps({"message": "Skip jobs at Initech", "known": {}}), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["pipeline", "chat-preferences", "--input-file", str(request)])

    pipeline_cli.main()

    printed = json.loads(capsys.readouterr().out)
    assert printed["proposals"] == [_filter("skip_company", "Initech")]
    assert printed["source"] == "rules"
