"""Read a scanned PDF with NVIDIA's hosted nemotron-parse model.

A scan has no text layer, so pypdf finds nothing to rebuild. Each page is
rendered to a grayscale PNG and sent to nemotron-parse, which returns the page's
text in reading order with a class per block (heading, text, list item). Those
blocks become the same ``PdfLine`` records the text-layer path produces, so the
candidate DOCX is written by the same code either way.

This only runs when the user has saved an NVIDIA NIM key, and it sends the page
images to NVIDIA. Fonts cannot be recovered from an image, so every line uses the
default font; the user reviews the candidate before it becomes the master.
"""

from __future__ import annotations

import base64
import re
import struct
import zlib
from pathlib import Path
from typing import Any, Callable

import httpx

from ..secret_env import get_secret
from .pdf_ingestion import DEFAULT_FONT, DEFAULT_SIZE, PdfLine, PdfRun

API_KEY_NAME = "NVIDIA_NIM_API_KEY"
ENDPOINT = "https://integrate.api.nvidia.com/v1/chat/completions"
MODEL = "nvidia/nemotron-parse-2.0"
# Control tokens from the model card: boxes, classes and markdown text, with no
# text transcribed from inside pictures.
PROMPT = "</s><s><predict_bbox><predict_classes><output_markdown><predict_no_text_in_pic>"
# The model's context is 4096 tokens and the image does not count against it.
MAX_TOKENS = 3500
# 150 dpi: small enough to upload quickly, large enough for 9pt resume text.
RENDER_SCALE = 150 / 72
MAX_PAGES = 6
TIMEOUT_SECONDS = 90.0
HEADING_SIZE = DEFAULT_SIZE + 3

_HEADING_TYPES = {"Title", "Section-header"}
_SKIPPED_TYPES = {"Page-header", "Page-footer", "Picture"}
_MARKDOWN_HEADING_RE = re.compile(r"^#{1,6}\s+")
_MARKDOWN_EMPHASIS_RE = re.compile(r"(\*\*|__)(.+?)\1")
# The model escapes markdown punctuation, e.g. "\- Built" for a literal dash.
_MARKDOWN_ESCAPE_RE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|])")
# One block: <x_..><y_..>text<x_..><y_..><class_Name>
_BLOCK_RE = re.compile(r"<x_[\d.]+><y_[\d.]+>(.*?)<x_[\d.]+><y_[\d.]+><class_([^>]+)>", re.DOTALL)

Poster = Callable[[str, dict[str, str], dict[str, Any]], dict[str, Any]]


def nvidia_key() -> str | None:
    return get_secret(API_KEY_NAME)


def encode_png(width: int, height: int, stride: int, pixels: bytes) -> bytes:
    """Encode 8-bit grayscale rows as a PNG, so no imaging library is needed."""
    rows = b"".join(b"\x00" + pixels[row * stride : row * stride + width] for row in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows, 6)) + chunk(b"IEND", b"")


def render_pages(source_pdf: Path) -> list[bytes]:
    import pypdfium2  # type: ignore

    document = pypdfium2.PdfDocument(str(source_pdf))
    try:
        pages: list[bytes] = []
        for index in range(min(len(document), MAX_PAGES)):
            bitmap = document[index].render(scale=RENDER_SCALE, grayscale=True)
            pages.append(encode_png(bitmap.width, bitmap.height, bitmap.stride, bytes(bitmap.buffer)))
        return pages
    finally:
        document.close()


def _post(url: str, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
    response = httpx.post(url, headers=headers, json=body, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def parse_page(png: bytes, api_key: str, post: Poster = _post) -> list[dict[str, Any]]:
    """Return the page's blocks as ``{"type", "text"}`` dicts in reading order."""
    image = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    body = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "temperature": 0,
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": PROMPT}, {"type": "image_url", "image_url": {"url": image}}],
            }
        ],
    }
    reply = post(ENDPOINT, {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}, body)
    content = reply["choices"][0]["message"]["content"] or ""
    return [{"type": kind, "text": text.strip()} for text, kind in _BLOCK_RE.findall(content)]


def _plain(text: str) -> tuple[str, bool]:
    stripped = _MARKDOWN_HEADING_RE.sub("", text.strip())
    bold = bool(_MARKDOWN_EMPHASIS_RE.fullmatch(stripped))
    return _MARKDOWN_ESCAPE_RE.sub(r"\1", _MARKDOWN_EMPHASIS_RE.sub(r"\2", stripped)), bold


def blocks_to_lines(blocks: list[dict[str, Any]]) -> list[PdfLine]:
    lines: list[PdfLine] = []
    for block in blocks:
        kind = str(block.get("type", "Text"))
        if kind in _SKIPPED_TYPES:
            continue
        heading = kind in _HEADING_TYPES
        for raw in str(block.get("text", "")).splitlines():
            text, bold = _plain(raw)
            if not text:
                continue
            size = HEADING_SIZE if heading else DEFAULT_SIZE
            lines.append(PdfLine(runs=(PdfRun(text=text, bold=heading or bold),), size=size, font=DEFAULT_FONT))
    return lines


def read_scanned_pdf_lines(source_pdf: Path, api_key: str, post: Poster = _post) -> tuple[PdfLine, ...]:
    lines: list[PdfLine] = []
    for png in render_pages(source_pdf):
        lines.extend(blocks_to_lines(parse_page(png, api_key, post)))
    return tuple(lines)
