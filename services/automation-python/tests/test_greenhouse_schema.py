"""Greenhouse publishes the application form; reading it beats guessing it from the DOM."""
from __future__ import annotations

import json
import urllib.error

import pytest

from applyocalypse_automation.browser.greenhouse_schema import (
    GreenhouseJobRef,
    fetch_questions,
    parse_job_ref,
    questions_from_payload,
    schema_url,
    unanswered_required,
)

_PAYLOAD = {
    "id": 4001,
    "title": "Staff Engineer",
    "questions": [
        {
            "label": "First Name",
            "required": True,
            "fields": [{"name": "first_name", "type": "input_text", "values": []}],
        },
        {
            "label": "Resume",
            "required": True,
            "fields": [{"name": "resume", "type": "input_file", "values": []}],
        },
        {
            "label": "Are you legally authorized to work in the United States?",
            "required": True,
            "fields": [
                {
                    "name": "question_12345",
                    "type": "multi_value_single_select",
                    "values": [{"label": "Yes", "value": 1}, {"label": "No", "value": 0}],
                }
            ],
        },
        {
            "label": "LinkedIn Profile",
            "required": False,
            "fields": [{"name": "question_99", "type": "input_text", "values": []}],
        },
    ],
}


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://boards.greenhouse.io/acmecorp/jobs/4001",
            GreenhouseJobRef("acmecorp", "4001"),
        ),
        (
            "https://job-boards.greenhouse.io/acmecorp/jobs/4001",
            GreenhouseJobRef("acmecorp", "4001"),
        ),
        (
            "https://boards.greenhouse.io/acmecorp/jobs/4001?gh_src=abc#apply",
            GreenhouseJobRef("acmecorp", "4001"),
        ),
        (
            "https://boards.greenhouse.io/embed/job_app?for=acmecorp&token=4001",
            GreenhouseJobRef("acmecorp", "4001"),
        ),
        ("https://boards.greenhouse.io/acmecorp/4001", GreenhouseJobRef("acmecorp", "4001")),
        # A company's own careers page carries the job id but not the board token, so the
        # board cannot be resolved from the URL alone and must not be guessed.
        ("https://acmecorp.com/careers?gh_jid=4001", None),
        ("https://boards.greenhouse.io/acmecorp", None),
        ("https://myworkdayjobs.com/acme/job/4001", None),
        ("not a url at all", None),
        ("", None),
        # A host that merely ends in the brand name is not the brand.
        ("https://notgreenhouse.io/acmecorp/jobs/4001", None),
    ],
)
def test_parse_job_ref(url: str, expected: GreenhouseJobRef | None) -> None:
    assert parse_job_ref(url) == expected


def test_schema_url_escapes_its_parts() -> None:
    assert schema_url(GreenhouseJobRef("acme corp", "40/01")) == (
        "https://boards-api.greenhouse.io/v1/boards/acme%20corp/jobs/40%2F01?questions=true"
    )


def test_questions_carry_requiredness_types_and_options() -> None:
    questions = questions_from_payload(_PAYLOAD)

    assert [q.label for q in questions] == [
        "First Name",
        "Resume",
        "Are you legally authorized to work in the United States?",
        "LinkedIn Profile",
    ]
    assert [q.required for q in questions] == [True, True, True, False]
    assert questions[0].is_free_text
    assert questions[1].is_attachment
    assert questions[2].options == ("Yes", "No")
    assert questions[3].field_names == ("question_99",)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        "not a dict",
        {},
        {"questions": None},
        {"questions": "not a list"},
        {"questions": [None, 7, "text"]},
        {"questions": [{"label": "   "}]},
        {"questions": [{"no_label": True}]},
    ],
)
def test_a_payload_we_cannot_read_yields_no_questions(payload: object) -> None:
    assert questions_from_payload(payload) == []


def test_a_question_with_broken_fields_still_survives() -> None:
    """A partial view of the form beats none, so one bad field does not lose the question."""
    questions = questions_from_payload(
        {"questions": [{"label": "Cover Letter", "required": True, "fields": [None, {"name": ""}]}]}
    )

    assert len(questions) == 1
    assert questions[0].label == "Cover Letter"
    assert questions[0].required is True
    assert questions[0].field_names == ()


def test_unanswered_required_names_what_is_missing() -> None:
    questions = questions_from_payload(_PAYLOAD)

    missing = unanswered_required(questions, ["first_name", "resume"])

    assert [q.label for q in missing] == [
        "Are you legally authorized to work in the United States?"
    ]


def test_unanswered_required_ignores_optional_gaps() -> None:
    questions = questions_from_payload(_PAYLOAD)

    missing = unanswered_required(questions, ["first_name", "resume", "question_12345"])

    assert missing == []


def test_fetch_questions_reads_the_board_api() -> None:
    seen: list[str] = []

    def opener(request, timeout):  # noqa: ANN001, ANN202 - test double
        seen.append(request.full_url)
        return _FakeResponse(json.dumps(_PAYLOAD).encode())

    questions = fetch_questions("https://boards.greenhouse.io/acmecorp/jobs/4001", opener=opener)

    assert seen == ["https://boards-api.greenhouse.io/v1/boards/acmecorp/jobs/4001?questions=true"]
    assert questions is not None
    assert len(questions) == 4


@pytest.mark.parametrize(
    "failure",
    [
        urllib.error.URLError("no network"),
        urllib.error.HTTPError("url", 404, "Not Found", {}, None),  # type: ignore[arg-type]
        OSError("connection reset"),
    ],
)
def test_a_failed_fetch_falls_back_rather_than_raising(failure: Exception) -> None:
    def opener(request, timeout):  # noqa: ANN001, ANN202 - test double
        raise failure

    assert fetch_questions("https://boards.greenhouse.io/acmecorp/jobs/4001", opener=opener) is None


def test_a_body_that_is_not_json_falls_back() -> None:
    def opener(request, timeout):  # noqa: ANN001, ANN202 - test double
        return _FakeResponse(b"<html>rate limited</html>")

    assert fetch_questions("https://boards.greenhouse.io/acmecorp/jobs/4001", opener=opener) is None


def test_a_url_that_is_not_greenhouse_is_never_fetched() -> None:
    def opener(request, timeout):  # noqa: ANN001, ANN202 - test double
        raise AssertionError("must not reach the network for a non-Greenhouse URL")

    assert fetch_questions("https://acme.wd1.myworkdayjobs.com/job/4001", opener=opener) is None
