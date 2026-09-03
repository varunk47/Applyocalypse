from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from applyocalypse_automation.submission_receipt import (
    RECEIPT_FILENAME,
    ReceiptAnswer,
    ReceiptDocument,
    SubmissionRecord,
    render_receipt,
    sha256_of,
    write_receipt,
)

_RESUME = ReceiptDocument(
    field_label="Resume/CV",
    filename="Jane_Doe_Resume.docx",
    file_kind="RESUME",
    file_format="DOCX",
    size_bytes=41284,
    sha256="9f2b" + "0" * 60,
)

_RECORD = SubmissionRecord(
    job_url="https://boards.greenhouse.io/acme/jobs/4242",
    portal_id="greenhouse",
    documents=(_RESUME,),
    answers=(
        ReceiptAnswer(field_label="First name", value="Jane"),
        ReceiptAnswer(field_label="Are you authorized to work in the US?", value="Yes"),
    ),
)


def _render(record: SubmissionRecord = _RECORD, **overrides: object) -> str:
    kwargs: dict[str, object] = {
        "run_id": "run-4242",
        "submitted_at": "2026-09-01T08:15:22.000000Z",
        "confirmed": True,
        "confirmation_url": "https://boards.greenhouse.io/acme/jobs/4242/confirmation",
        "confirmation_title": "Thanks for applying",
    }
    kwargs.update(overrides)
    return render_receipt(record, **kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "expected",
    [
        "run-4242",
        "2026-09-01T08:15:22.000000Z",
        "https://boards.greenhouse.io/acme/jobs/4242",
        "greenhouse",
        "Thanks for applying",
        "Resume/CV",
        "Jane_Doe_Resume.docx",
        "41284 bytes",
        "9f2b",
        "First name",
        "Jane",
        "Are you authorized to work in the US?",
    ],
)
def test_the_receipt_states_what_was_sent(expected: str) -> None:
    """Every fact the user would go looking for months later has to be in the file."""
    assert expected in _render()


def test_a_withheld_answer_shows_as_redacted_and_never_as_itself() -> None:
    record = SubmissionRecord(
        job_url="https://example.com/apply",
        answers=(
            ReceiptAnswer(field_label="Password", value=None),
            ReceiptAnswer(field_label="Verification code", value=None),
        ),
    )
    rendered = _render(record)

    assert rendered.count("[redacted]") >= 2
    assert "Password" in rendered
    assert "Verification code" in rendered


def test_a_value_that_was_passed_in_is_the_only_thing_that_can_be_printed() -> None:
    """The renderer holds no secret to leak: a withheld answer arrives as None."""
    record = SubmissionRecord(
        job_url="https://example.com/apply",
        answers=(ReceiptAnswer(field_label="One-time code", value=None),),
    )
    assert "482913" not in _render(record)


@pytest.mark.parametrize(
    ("confirmed", "expected", "forbidden"),
    [
        (True, "The portal confirmed the submission", "no confirmation could be verified"),
        (False, "no confirmation could be verified", "The portal confirmed the submission"),
    ],
)
def test_the_outcome_is_stated_rather_than_assumed(confirmed: bool, expected: str, forbidden: str) -> None:
    rendered = _render(confirmed=confirmed)
    assert expected in rendered
    assert forbidden not in rendered


@pytest.mark.parametrize(
    ("auto_submit", "expected"),
    [(True, "Preapproved auto-submit"), (False, "Explicit approval at the submit gate")],
)
def test_how_the_submission_was_approved_is_recorded(auto_submit: bool, expected: str) -> None:
    record = SubmissionRecord(job_url="https://example.com/apply", auto_submit=auto_submit)
    assert expected in _render(record)


def test_an_empty_run_says_so_instead_of_showing_an_empty_list() -> None:
    rendered = _render(SubmissionRecord(job_url="https://example.com/apply"))
    assert "No document was uploaded" in rendered
    assert "No answer was written" in rendered
    assert "Documents sent (0)" in rendered
    assert "Answers written (0)" in rendered


def test_a_missing_confirmation_page_is_labelled_not_left_blank() -> None:
    rendered = _render(confirmed=False, confirmation_url=None, confirmation_title=None)
    assert rendered.count("not captured") == 2


def test_a_long_answer_is_clipped_and_says_how_long_it_really_was() -> None:
    """A cover letter pasted into a textarea must not bury the rest of the file."""
    essay = "x" * 900
    record = SubmissionRecord(
        job_url="https://example.com/apply",
        answers=(ReceiptAnswer(field_label="Why this company?", value=essay),),
    )
    rendered = _render(record)

    assert "(900 characters in total)" in rendered
    assert essay not in rendered


def test_a_multi_line_answer_keeps_its_lines() -> None:
    record = SubmissionRecord(
        job_url="https://example.com/apply",
        answers=(ReceiptAnswer(field_label="Address", value="1 Main St\nAustin, TX"),),
    )
    rendered = _render(record)

    assert "1 Main St" in rendered
    assert "Austin, TX" in rendered
    assert "1 Main StAustin, TX" not in rendered


def test_writing_the_receipt_returns_the_hash_of_what_landed_on_disk(tmp_path: Path) -> None:
    path, digest = write_receipt(
        tmp_path,
        _RECORD,
        run_id="run-4242",
        submitted_at="2026-09-01T08:15:22.000000Z",
        confirmed=True,
        confirmation_url="https://example.com/done",
        confirmation_title="Application received",
    )

    assert path == tmp_path / RECEIPT_FILENAME
    assert digest == hashlib.sha256(path.read_bytes()).hexdigest()
    assert "Applyocalypse submission receipt" in path.read_text(encoding="utf-8")


def test_the_document_hash_is_taken_from_the_bytes_on_disk(tmp_path: Path) -> None:
    """It has to survive the file being edited afterwards, so it cannot be recomputed later."""
    uploaded = tmp_path / "resume.docx"
    uploaded.write_bytes(b"PK\x03\x04 pretend this is a docx")

    assert sha256_of(uploaded) == hashlib.sha256(uploaded.read_bytes()).hexdigest()


def test_a_file_larger_than_one_chunk_hashes_correctly(tmp_path: Path) -> None:
    """The reader loops at 1MB, so a file that spans chunks is the case that can break."""
    big = tmp_path / "big.bin"
    big.write_bytes(b"a" * (1024 * 1024 + 17))

    assert sha256_of(big) == hashlib.sha256(big.read_bytes()).hexdigest()


def test_a_long_question_never_runs_into_its_answer() -> None:
    """The label here is a real screening question and the answer is one word."""
    question = "Are you legally authorized to work in the United States without sponsorship?"
    record = SubmissionRecord(
        job_url="https://example.com/apply",
        answers=(ReceiptAnswer(field_label=question, value="Yes"),),
    )
    rendered = _render(record)

    assert question + "Yes" not in rendered
    assert question + "\n      Yes" in rendered


@pytest.mark.parametrize("label_length", [4, 31, 32, 33, 34, 40])
def test_a_label_and_its_value_are_always_separated(label_length: int) -> None:
    """Sweeps the column boundary, which is where padding silently stops padding."""
    record = SubmissionRecord(
        job_url="https://example.com/apply",
        answers=(ReceiptAnswer(field_label="Q" * label_length, value="Yes"),),
    )
    assert "QYes" not in _render(record)
