from __future__ import annotations

from applyocalypse_automation.browser.adapter import read_png_dimensions, screenshot_payload


def minimal_png_header(width: int, height: int) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + (13).to_bytes(4, "big") + b"IHDR" + width.to_bytes(4, "big") + height.to_bytes(4, "big")


def test_read_png_dimensions_extracts_actual_image_size(tmp_path):
    screenshot_path = tmp_path / "screenshot.png"
    screenshot_path.write_bytes(minimal_png_header(321, 123))

    assert read_png_dimensions(screenshot_path) == (321, 123)
    assert screenshot_payload(screenshot_path)["width"] == 321
    assert screenshot_payload(screenshot_path)["height"] == 123


def test_screenshot_payload_falls_back_for_non_png_files(tmp_path):
    screenshot_path = tmp_path / "screenshot.png"
    screenshot_path.write_bytes(b"not-a-png")

    assert read_png_dimensions(screenshot_path) is None
    assert screenshot_payload(screenshot_path, default_width=640, default_height=480) == {
        "local_path": str(screenshot_path),
        "mime_type": "image/png",
        "width": 640,
        "height": 480,
    }
