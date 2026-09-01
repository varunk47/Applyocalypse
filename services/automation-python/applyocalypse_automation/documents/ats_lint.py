"""Check a resume template against the formatting Greenhouse says breaks its parser.

Greenhouse publishes the list, which is unusual and worth using:
https://support.greenhouse.io/hc/en-us/articles/200989175-Unsuccessful-resume-parse

The reason to run this on the master template rather than on each generated
document is that the hazards are properties of the template, so they travel to
every application the user ever sends from it. One warning about the template is
worth more than the same warning attached to the fiftieth tailored copy.

Nothing here blocks. A template with a table in it still produces a document, and
whether the tradeoff is worth it is the user's call to make. What they cannot do
is make it without being told, because a bad parse is silent: the application
submits, and the profile the recruiter opens is just thinner than the resume that
was sent.

Only the checks that can be decided from the file itself are implemented. Two
items on Greenhouse's list, company names missing "Inc." or "LLC" and job titles
abbreviated to "Sr. Account Exec", need to know which words are the company and
which are the title, and guessing that from a text dump would produce false
alarms about a document that is fine.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_V = "{urn:schemas-microsoft-com:vml}"

# Greenhouse states the parser cannot read a resume above 2.5MB at all.
_MAX_PARSEABLE_BYTES = int(2.5 * 1024 * 1024)

# Below this the document has no meaningful text layer, which is what a resume
# pasted in as one big image looks like from the outside.
_MIN_MEANINGFUL_TEXT_CHARS = 40

# Four single characters in a row is deliberate. "a b c" shows up in ordinary
# prose; "E X P E R I E N C E" does not happen by accident, and it is invisible
# to the eye while being unreadable to the parser.
_SPACED_LETTERS = re.compile(r"(?:\b\w\b[ \t]+){3,}\b\w\b")

_STANDARD_HEADINGS = frozenset(
    {
        "experience",
        "work experience",
        "professional experience",
        "employment",
        "employment history",
        "work history",
        "education",
        "skills",
        "technical skills",
        "projects",
        "certifications",
    }
)


@dataclass(frozen=True, slots=True)
class ParseRisk:
    """One thing in the template that Greenhouse says can break a parse."""

    code: str
    detail: str

    def to_payload(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}


def _parts(archive: zipfile.ZipFile, prefix: str) -> list[ElementTree.Element]:
    roots: list[ElementTree.Element] = []
    for name in archive.namelist():
        if name.startswith(prefix) and name.endswith(".xml"):
            try:
                roots.append(ElementTree.fromstring(archive.read(name)))
            except ElementTree.ParseError:
                # One unreadable part should not hide the hazards in the others.
                continue
    return roots


def _text_of(root: ElementTree.Element) -> str:
    return "".join(node.text or "" for node in root.iter(f"{_W}t"))


def _structural_risks(path: Path) -> list[ParseRisk]:
    risks: list[ParseRisk] = []
    with zipfile.ZipFile(path) as archive:
        body_roots = _parts(archive, "word/document")
        if not body_roots:
            return risks
        body = body_roots[0]

        tables = sum(1 for _ in body.iter(f"{_W}tbl"))
        if tables:
            risks.append(
                ParseRisk(
                    "TABLES",
                    f"The template uses {tables} table(s). Greenhouse reads each cell as a separate block, "
                    "so a job title can arrive without the company or dates that sat beside it.",
                )
            )

        # Not a sum: Word nests w:txbxContent inside v:textbox for a legacy shape, so
        # adding the two counts reports one box as two. The modern element is the
        # reliable count, and the VML one is the fallback for anything without it.
        text_boxes = sum(1 for _ in body.iter(f"{_W}txbxContent")) or sum(1 for _ in body.iter(f"{_V}textbox"))
        if text_boxes:
            risks.append(
                ParseRisk(
                    "TEXT_BOXES",
                    f"The template has {text_boxes} text box(es). Text inside one is often skipped entirely, "
                    "and Greenhouse names contact details in a text box as a specific cause of a failed parse.",
                )
            )

        images = sum(1 for _ in body.iter(f"{_A}blip"))
        if images:
            risks.append(
                ParseRisk(
                    "GRAPHICS",
                    f"The template embeds {images} image(s). Greenhouse lists graphics, photos and word art "
                    "as parse hazards, and any text inside them is not read at all.",
                )
            )

        columns = max(
            (int(node.get(f"{_W}num") or 1) for node in body.iter(f"{_W}cols")),
            default=1,
        )
        if columns > 1:
            risks.append(
                ParseRisk(
                    "MULTI_COLUMN",
                    f"The page is laid out in {columns} columns. Greenhouse reads top to bottom across the "
                    "full width, so a sidebar gets interleaved into the middle of the work history.",
                )
            )

        for prefix, where in (("word/header", "header"), ("word/footer", "footer")):
            content = "".join(_text_of(root) for root in _parts(archive, prefix)).strip()
            if content:
                risks.append(
                    ParseRisk(
                        f"{where.upper()}_CONTENT",
                        f"The page {where} contains text. Greenhouse extracts it less reliably than the body, "
                        "and a name or email that lives only there can be missing from the parsed profile.",
                    )
                )

    return risks


def _text_risks(text: str) -> list[ParseRisk]:
    risks: list[ParseRisk] = []

    if len(text.strip()) < _MIN_MEANINGFUL_TEXT_CHARS:
        risks.append(
            ParseRisk(
                "NO_TEXT_LAYER",
                "Almost no readable text was found in the document. A resume that is really a picture of a "
                "resume parses to nothing, whatever it looks like on screen.",
            )
        )
        # Every remaining text check would fire on an empty document and say the
        # same thing three more ways.
        return risks

    spaced = _SPACED_LETTERS.search(text)
    if spaced:
        risks.append(
            ParseRisk(
                "SPACED_LETTERS",
                f"Letters are spaced apart in {spaced.group(0).strip()!r}. The parser sees separate letters "
                "rather than a word, so whatever is written that way is not searchable.",
            )
        )

    headings = {line.strip().rstrip(":").lower() for line in text.splitlines() if len(line.strip()) <= 40}
    if not headings & _STANDARD_HEADINGS:
        risks.append(
            ParseRisk(
                "NO_STANDARD_HEADINGS",
                "No conventional section heading was found on a line of its own. Greenhouse maps sections by "
                "matching headings it recognises, so 'Where I Have Worked' can leave the employment section empty.",
            )
        )

    return risks


def lint_resume_docx(path: Path) -> tuple[ParseRisk, ...]:
    """Every documented parse hazard found in this DOCX, in a stable order."""
    from .docx_mutation import extract_docx_text  # noqa: PLC0415

    risks: list[ParseRisk] = []

    size = path.stat().st_size
    if size > _MAX_PARSEABLE_BYTES:
        risks.append(
            ParseRisk(
                "FILE_TOO_LARGE",
                f"The file is {size / 1024 / 1024:.1f}MB. Greenhouse cannot parse a resume over 2.5MB, "
                "so the whole document is skipped rather than parsed badly.",
            )
        )

    risks.extend(_structural_risks(path))
    risks.extend(_text_risks(extract_docx_text(path)))
    return tuple(risks)
