"""Reading a scanned resume through NVIDIA's nemotron-parse.

No test here reaches the network: the HTTP call is injected, so what is checked
is how a reply becomes lines, and that a missing key or a failed call falls back
to the plain "this is a scan" message instead of breaking the upload.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path
from typing import Any

import pytest
from docx import Document  # type: ignore

from applyocalypse_automation.documents import nemotron_parse, pdf_ingestion
from applyocalypse_automation.documents.nemotron_parse import (
    DEFAULT_SIZE,
    HEADING_SIZE,
    blocks_to_lines,
    encode_png,
    parse_page,
)
from applyocalypse_automation.documents.pdf_ingestion import convert_pdf_to_candidate_docx

# Trimmed from a real nemotron-parse-2.0 reply: each block sits between its box
# corners and is closed by its class.
REPLY_TEXT = (
    "<x_0.1445><y_0.1086>## JANE DOE<x_0.2666><y_0.1258><class_Section-header>\n\n"
    "<x_0.1426><y_0.1664>Senior Engineer, Initech 2021 - 2024<x_0.4043><y_0.1781><class_Text>\n\n"
    r"<x_0.1543><y_0.1810>\- Built a billing pipeline<x_0.4082><y_0.1930><class_List-item>"
)


def _reply(content: str | None) -> dict[str, Any]:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


@pytest.fixture(autouse=True)
def _no_text_layer(monkeypatch: pytest.MonkeyPatch) -> None:
    # A scan is an image, so the text-layer reader finds nothing.
    monkeypatch.setattr(pdf_ingestion, "read_pdf_lines", lambda source_pdf: ())


def _scan_pdf(path: Path) -> Path:
    import pypdfium2  # type: ignore

    document = pypdfium2.PdfDocument.new()
    document.new_page(612, 792)
    document.save(str(path))
    document.close()
    return path


def test_png_is_a_valid_grayscale_image() -> None:
    # Two rows of three pixels, stored with one byte of row padding.
    png = encode_png(3, 2, 4, bytes([0, 128, 255, 9, 10, 20, 30, 9]))

    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    width, height, depth, color = struct.unpack(">IIBB", png[16:26])
    assert (width, height, depth, color) == (3, 2, 8, 0)
    idat_length = struct.unpack(">I", png[33:37])[0]
    rows = zlib.decompress(png[41 : 41 + idat_length])
    assert rows == bytes([0, 0, 128, 255, 0, 10, 20, 30])


@pytest.mark.parametrize(
    ("block", "expected"),
    [
        ({"type": "Title", "text": "# JANE DOE"}, [("JANE DOE", True, HEADING_SIZE)]),
        ({"type": "Section-header", "text": "### EXPERIENCE"}, [("EXPERIENCE", True, HEADING_SIZE)]),
        ({"type": "Text", "text": "Senior Engineer, Initech"}, [("Senior Engineer, Initech", False, DEFAULT_SIZE)]),
        ({"type": "Text", "text": "**Initech**"}, [("Initech", True, DEFAULT_SIZE)]),
        ({"type": "List-item", "text": "- Cut costs\n- Led team"}, [("- Cut costs", False, DEFAULT_SIZE), ("- Led team", False, DEFAULT_SIZE)]),
        ({"type": "List-item", "text": r"\- Led a team of 4\."}, [("- Led a team of 4.", False, DEFAULT_SIZE)]),
        ({"type": "Page-header", "text": "Page 1"}, []),
        ({"type": "Page-footer", "text": "jane@example.com"}, []),
        ({"type": "Picture", "text": ""}, []),
        ({"type": "Text", "text": "   \n"}, []),
    ],
)
def test_blocks_become_lines(block: dict[str, str], expected: list[tuple[str, bool, float]]) -> None:
    lines = blocks_to_lines([block])

    assert [(line.runs[0].text, line.runs[0].bold, line.size) for line in lines] == expected


def test_parse_page_reads_blocks_in_order() -> None:
    sent: dict[str, Any] = {}

    def post(url: str, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
        sent.update(url=url, headers=headers, body=body)
        return _reply(REPLY_TEXT)

    assert parse_page(b"png", "test-key", post) == [
        {"type": "Section-header", "text": "## JANE DOE"},
        {"type": "Text", "text": "Senior Engineer, Initech 2021 - 2024"},
        {"type": "List-item", "text": r"\- Built a billing pipeline"},
    ]
    assert sent["headers"]["Authorization"] == "Bearer test-key"
    assert sent["body"]["model"] == nemotron_parse.MODEL
    prompt, image = sent["body"]["messages"][0]["content"]
    assert prompt == {"type": "text", "text": nemotron_parse.PROMPT}
    assert image["image_url"]["url"].startswith("data:image/png;base64,")


@pytest.mark.parametrize("content", [None, "", "no tagged blocks here"])
def test_parse_page_with_nothing_tagged_returns_no_blocks(content: str | None) -> None:
    assert parse_page(b"png", "test-key", lambda url, headers, body: _reply(content)) == []


def test_scan_without_a_key_keeps_the_scan_message(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nemotron_parse, "nvidia_key", lambda: None)

    with pytest.raises(RuntimeError, match="no selectable text"):
        convert_pdf_to_candidate_docx(_scan_pdf(tmp_path / "scan.pdf"), tmp_path / "out")


def test_scan_with_a_key_is_read_by_the_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nemotron_parse, "nvidia_key", lambda: "test-key")
    monkeypatch.setattr(nemotron_parse, "_post", lambda url, headers, body: _reply(REPLY_TEXT))
    # Default arguments bind at definition time, so route the default through the patch.
    real_read = nemotron_parse.read_scanned_pdf_lines
    monkeypatch.setattr(
        nemotron_parse,
        "read_scanned_pdf_lines",
        lambda pdf, key: real_read(pdf, key, nemotron_parse._post),
    )

    result = convert_pdf_to_candidate_docx(_scan_pdf(tmp_path / "scan.pdf"), tmp_path / "out")

    texts = [paragraph.text for paragraph in Document(str(result.candidate_docx_path)).paragraphs if paragraph.text]
    assert texts == ["JANE DOE", "Senior Engineer, Initech 2021 - 2024", "Built a billing pipeline"]


def test_a_failed_call_falls_back_to_the_scan_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(pdf: Path, key: str) -> Any:
        raise ConnectionError("secret detail test-key")

    monkeypatch.setattr(nemotron_parse, "nvidia_key", lambda: "test-key")
    monkeypatch.setattr(nemotron_parse, "read_scanned_pdf_lines", fail)

    with pytest.raises(RuntimeError, match="no selectable text"):
        convert_pdf_to_candidate_docx(_scan_pdf(tmp_path / "scan.pdf"), tmp_path / "out")
    # Only the error type is reported, never its message, which could echo the key.
    assert "test-key" not in capsys.readouterr().err
