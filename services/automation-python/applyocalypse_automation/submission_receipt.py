"""Write one plain-text record of exactly what was sent to a portal.

An application, once submitted, is gone. The portal shows a thank-you page and
then forgets; the user is left with an email that says a company received
something, and no way to answer the only questions that matter three weeks
later: which resume did I send, and what did I say when they asked about
sponsorship?

Everything needed to answer that already passes through the fill loop. This
turns it into a file the user owns, written next to the run's other artifacts at
the moment of submission, so it records the documents as they were then rather
than as they are now.

Two rules govern what goes in it. Values are recorded only when the field was
neither filled from a secret nor looks like it holds one, which is stricter than
the event log because a file gets shared and an event log does not. And nothing
here is inferred: the receipt says the portal confirmed the submission only when
a confirmation was actually detected, and says so plainly when it was not.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

RECEIPT_FILENAME = "submission-receipt.txt"

REDACTED = "[redacted]"

# Long enough for a paragraph-length answer, short enough that a cover letter
# pasted into a textarea does not bury the rest of the receipt.
_MAX_RECORDED_VALUE_CHARS = 400

# One column per block, wide enough for that block's longest label and no wider.
_META_WIDTH = 14
_DOCUMENT_WIDTH = 10
_ANSWER_WIDTH = 34
_LINE_WIDTH = 96


@dataclass(frozen=True, slots=True)
class ReceiptDocument:
    """One file that was accepted by an upload control."""

    field_label: str
    filename: str
    file_kind: str
    file_format: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ReceiptAnswer:
    """One answer that was written into the form.

    ``value`` is ``None`` when the answer was withheld because it came from a
    secret or the field looked like it held one.
    """

    field_label: str
    value: str | None


@dataclass(frozen=True, slots=True)
class SubmissionRecord:
    """What the fill loop observed, carried to the submit step to be receipted."""

    job_url: str
    portal_id: str | None = None
    auto_submit: bool = False
    documents: tuple[ReceiptDocument, ...] = ()
    answers: tuple[ReceiptAnswer, ...] = ()


def _labelled(label: str, value: object, *, width: int, indent: str = "  ") -> str:
    """One label and its value, side by side when they fit and stacked when they do not.

    The label has to leave two clear spaces before the value, because the long
    end of this scale is a real screening question ("Are you legally authorized
    to work in the United States without sponsorship?") whose answer is "Yes".
    Run together, that reads as neither one.
    """
    text = "" if value is None else str(value)
    lines = text.splitlines() or [""]
    fits = len(label) <= width - 2 and len(indent) + width + len(lines[0]) <= _LINE_WIDTH
    if len(lines) == 1 and fits:
        return f"{indent}{label.ljust(width)}{lines[0]}"
    body = "\n".join(f"{indent}    {line}" for line in lines)
    return f"{indent}{label}\n{body}"


def _heading(title: str) -> str:
    return f"{title}\n{'-' * len(title)}"


def _clip(value: str) -> str:
    if len(value) <= _MAX_RECORDED_VALUE_CHARS:
        return value
    return f"{value[:_MAX_RECORDED_VALUE_CHARS]}... ({len(value)} characters in total)"


def _document_block(index: int, document: ReceiptDocument) -> str:
    return "\n".join(
        [
            f"  {index}. {document.field_label}",
            _labelled("File", document.filename, width=_DOCUMENT_WIDTH, indent="     "),
            _labelled("Kind", document.file_kind, width=_DOCUMENT_WIDTH, indent="     "),
            _labelled("Format", document.file_format, width=_DOCUMENT_WIDTH, indent="     "),
            _labelled("Size", f"{document.size_bytes} bytes", width=_DOCUMENT_WIDTH, indent="     "),
            _labelled("SHA-256", document.sha256, width=_DOCUMENT_WIDTH, indent="     "),
        ]
    )


def render_receipt(
    record: SubmissionRecord,
    *,
    run_id: str,
    submitted_at: str,
    confirmed: bool,
    confirmation_url: object = None,
    confirmation_title: object = None,
) -> str:
    title = "Applyocalypse submission receipt"
    sections: list[str] = [
        title,
        "=" * len(title),
        "",
        _labelled("Run", run_id, width=_META_WIDTH),
        _labelled("Submitted", submitted_at, width=_META_WIDTH),
        _labelled(
            "Outcome",
            "The portal confirmed the submission"
            if confirmed
            else "Submit was clicked, but no confirmation could be verified",
            width=_META_WIDTH,
        ),
        _labelled(
            "Approval",
            "Preapproved auto-submit" if record.auto_submit else "Explicit approval at the submit gate",
            width=_META_WIDTH,
        ),
        _labelled("Job", record.job_url, width=_META_WIDTH),
        _labelled("Portal", record.portal_id or "not identified", width=_META_WIDTH),
        "",
        _heading("Confirmation page"),
        _labelled("URL", confirmation_url or "not captured", width=_META_WIDTH),
        _labelled("Title", confirmation_title or "not captured", width=_META_WIDTH),
        "",
        _heading(f"Documents sent ({len(record.documents)})"),
    ]

    if record.documents:
        sections.extend(_document_block(index, document) for index, document in enumerate(record.documents, start=1))
    else:
        sections.append("  No document was uploaded by Applyocalypse during this run.")

    sections.extend(["", _heading(f"Answers written ({len(record.answers)})")])

    if record.answers:
        sections.extend(
            _labelled(
                answer.field_label,
                REDACTED if answer.value is None else _clip(answer.value),
                width=_ANSWER_WIDTH,
            )
            for answer in record.answers
        )
    else:
        sections.append("  No answer was written by Applyocalypse during this run.")

    sections.extend(
        [
            "",
            _heading("About this file"),
            "  It lists what Applyocalypse itself uploaded and typed. Anything the portal filled in on its",
            "  own, or that was typed by hand in the browser window, is not recorded here.",
            "",
            f"  {REDACTED} means the value was withheld on purpose. Passwords, one-time codes and anything",
            "  else that looked like a secret are never written to this file.",
            "",
            "  The SHA-256 of each document is taken from the bytes that were uploaded, so it still",
            "  identifies the exact file that was sent even if that file is later edited or deleted.",
            "",
        ]
    )

    return "\n".join(sections)


def write_receipt(
    work_dir: Path,
    record: SubmissionRecord,
    *,
    run_id: str,
    submitted_at: str,
    confirmed: bool,
    confirmation_url: object = None,
    confirmation_title: object = None,
) -> tuple[Path, str]:
    """Write the receipt into ``work_dir`` and return its path and SHA-256."""
    raw = render_receipt(
        record,
        run_id=run_id,
        submitted_at=submitted_at,
        confirmed=confirmed,
        confirmation_url=confirmation_url,
        confirmation_title=confirmation_title,
    ).encode("utf-8")
    path = work_dir / RECEIPT_FILENAME
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest()


def sha256_of(path: Path) -> str:
    """Hash a file on disk, in chunks, so a large upload does not sit in memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
