"""Read a Greenhouse job's application form from its public board API.

Greenhouse publishes the exact question set for a posting, unauthenticated, which
means the form can be known before a browser is launched: which questions exist,
which are required, and which are closed lists of options rather than free text.
Guessing that from the rendered DOM is what makes portal filling brittle.

This module only reads. It deliberately does not submit: Greenhouse accepts an API
application that omits required fields, so a submission that succeeds there can
still be an incomplete application nobody ever reviews. Submission stays in the
browser, behind the human approval gate, where the portal enforces its own rules.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

_BOARD_API = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job}?questions=true"
_GREENHOUSE_HOSTS = ("greenhouse.io", "greenhouse.com")


@dataclass(frozen=True, slots=True)
class GreenhouseJobRef:
    board_token: str
    job_id: str


@dataclass(frozen=True, slots=True)
class GreenhouseQuestion:
    """One question on the application form.

    ``field_names`` is what the rendered inputs are actually called, so an answer can
    be matched to a question without re-deriving it from the label. A question can own
    more than one input: a name question is a first and a last, and a select renders a
    visible input plus the hidden field carrying the option id.
    """

    label: str
    required: bool
    field_type: str
    field_names: tuple[str, ...]
    options: tuple[str, ...]

    @property
    def is_free_text(self) -> bool:
        return self.field_type in {"input_text", "textarea"}

    @property
    def is_attachment(self) -> bool:
        return self.field_type == "input_file"


def parse_job_ref(url: str) -> GreenhouseJobRef | None:
    """The board token and job id in a Greenhouse job URL, or None if it is not one.

    Four shapes are in the wild: the board host and its job-boards sibling, the embed
    form that carries both in the query string, and a company's own careers page that
    passes only ``gh_jid``. The last one cannot be resolved here because the board
    token is not in the URL, so it is treated as unknown rather than guessed.
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if not any(host == domain or host.endswith("." + domain) for domain in _GREENHOUSE_HOSTS):
        return None

    query = urllib.parse.parse_qs(parsed.query)
    embedded_board = _first(query.get("for"))
    embedded_job = _first(query.get("token")) or _first(query.get("gh_jid"))
    if embedded_board and embedded_job:
        return GreenhouseJobRef(board_token=embedded_board, job_id=embedded_job)

    segments = [segment for segment in parsed.path.split("/") if segment]
    if len(segments) >= 3 and segments[-2] == "jobs":
        return GreenhouseJobRef(board_token=segments[-3], job_id=segments[-1])
    if len(segments) == 2 and segments[0] and segments[1].isdigit():
        return GreenhouseJobRef(board_token=segments[0], job_id=segments[1])
    return None


def schema_url(ref: GreenhouseJobRef) -> str:
    return _BOARD_API.format(
        board=urllib.parse.quote(ref.board_token, safe=""),
        job=urllib.parse.quote(ref.job_id, safe=""),
    )


def questions_from_payload(payload: Any) -> list[GreenhouseQuestion]:
    """The questions in a board-API job payload, skipping anything unrecognisable.

    A malformed entry is dropped rather than raised on, because a partial view of the
    form is still worth having and this runs on a response we do not control.
    """
    if not isinstance(payload, dict):
        return []
    raw_questions = payload.get("questions")
    if not isinstance(raw_questions, list):
        return []

    questions: list[GreenhouseQuestion] = []
    for raw in raw_questions:
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or "").strip()
        if not label:
            continue
        fields = raw.get("fields")
        field_names: list[str] = []
        field_type = ""
        options: list[str] = []
        if isinstance(fields, list):
            for field in fields:
                if not isinstance(field, dict):
                    continue
                name = str(field.get("name") or "").strip()
                if name:
                    field_names.append(name)
                if not field_type:
                    field_type = str(field.get("type") or "").strip()
                for value in field.get("values") or ():
                    if isinstance(value, dict):
                        label_text = str(value.get("label") or "").strip()
                        if label_text:
                            options.append(label_text)
        questions.append(
            GreenhouseQuestion(
                label=label,
                required=bool(raw.get("required")),
                field_type=field_type,
                field_names=tuple(field_names),
                options=tuple(dict.fromkeys(options)),
            )
        )
    return questions


def unanswered_required(
    questions: Iterable[GreenhouseQuestion], answered_field_names: Iterable[str]
) -> list[GreenhouseQuestion]:
    """Required questions with no answer against any of their inputs.

    This is the point of reading the schema at all: it makes an incomplete application
    something we can say out loud before the approval gate, rather than something the
    candidate discovers from silence weeks later.
    """
    answered = {name for name in answered_field_names if name}
    return [
        question
        for question in questions
        if question.required and not (set(question.field_names) & answered)
    ]


def fetch_questions(
    job_url: str,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
    timeout: float = 10.0,
) -> list[GreenhouseQuestion] | None:
    """The form for a Greenhouse job URL, or None when it cannot be read.

    None means "fall back to reading the rendered page", which is the existing
    behaviour, so every failure here is non-fatal: an unrecognised URL, a board that
    404s, a network that is not there, a body that is not the JSON we expect.
    """
    ref = parse_job_ref(job_url)
    if ref is None:
        return None
    request = urllib.request.Request(
        schema_url(ref),
        headers={"Accept": "application/json", "User-Agent": "Applyocalypse"},
    )
    try:
        with opener(request, timeout=timeout) as response:
            body = response.read()
    except (urllib.error.URLError, OSError, ValueError):
        return None
    try:
        payload = json.loads(body)
    except (TypeError, ValueError):
        return None
    return questions_from_payload(payload)


def _first(values: list[str] | None) -> str:
    if not values:
        return ""
    return values[0].strip()
