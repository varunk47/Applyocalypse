"""Reading a scanned resume through NVIDIA's nemotron-parse.

No test here reaches the network: the HTTP call is injected, so what is checked
is how a reply becomes lines, and that a missing key or a failed call falls back
to the plain "this is a scan" message instead of breaking the upload.
"""

from __future__ import annotations

import json
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


def _reply(blocks: Any) -> dict[str, Any]:
    arguments = json.dumps(blocks)
    return {"choices": [{"message": {"tool_calls": [{"function": {"arguments": arguments}}]}}]}


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
        ({"type": "Page-header", "text": "Page 1"}, []),
        ({"type": "Page-footer", "text": "jane@example.com"}, []),
        ({"type": "Picture", "text": ""}, []),
        ({"type": "Text", "text": "   \n"}, []),
    ],
)
def test_blocks_become_lines(block: dict[str, str], expected: list[tuple[str, bool, float]]) -> None:
    lines = blocks_to_lines([block])

    assert [(line.runs[0].text, line.runs[0].bold, line.size) for line in lines] == expected


@pytest.mark.parametrize(
    "blocks",
    [
        [[{"type": "Text", "text": "Hello"}]],
        [{"type": "Text", "text": "Hello"}],
    ],
)
def test_parse_page_accepts_nested_or_flat_blocks(blocks: Any) -> None:
    sent: dict[str, Any] = {}

    def post(url: str, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
        sent.update(url=url, headers=headers, body=body)
        return _reply(blocks)

    assert parse_page(b"png", "test-key", post) == [{"type": "Text", "text": "Hello"}]
    assert sent["headers"]["Authorization"] == "Bearer test-key"
    assert sent["body"]["model"] == nemotron_parse.MODEL
    image = sent["body"]["messages"][0]["content"][0]["image_url"]["url"]
    assert image.startswith("data:image/png;base64,")


def test_scan_without_a_key_keeps_the_scan_message(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nemotron_parse, "nvidia_key", lambda: None)

    with pytest.raises(RuntimeError, match="no selectable text"):
        convert_pdf_to_candidate_docx(_scan_pdf(tmp_path / "scan.pdf"), tmp_path / "out")


def test_scan_with_a_key_is_read_by_the_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    blocks = [[{"type": "Section-header", "text": "## JANE DOE"}, {"type": "Text", "text": "Senior Engineer, Initech"}]]
    monkeypatch.setattr(nemotron_parse, "nvidia_key", lambda: "test-key")
    monkeypatch.setattr(nemotron_parse, "_post", lambda url, headers, body: _reply(blocks))
    # Default arguments bind at definition time, so route the default through the patch.
    real_read = nemotron_parse.read_scanned_pdf_lines
    monkeypatch.setattr(
        nemotron_parse,
        "read_scanned_pdf_lines",
        lambda pdf, key: real_read(pdf, key, nemotron_parse._post),
    )

    result = convert_pdf_to_candidate_docx(_scan_pdf(tmp_path / "scan.pdf"), tmp_path / "out")

    texts = [paragraph.text for paragraph in Document(str(result.candidate_docx_path)).paragraphs if paragraph.text]
    assert texts == ["JANE DOE", "Senior Engineer, Initech"]


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
