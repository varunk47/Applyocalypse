"""Unit tests for SeleniumBaseBrowserAdapter that run without a live browser.

Tests cover:
  - Adapter name attribute
  - launch() fail-safe when seleniumbase is not installed (ImportError path)
  - No-driver guard: detect_fields / detect_blockers / capture_dom_snapshot /
    extract_visible_text / fill_field / upload_file all return safe empty/False
    results when driver has not been launched
  - pause() always succeeds with the given reason
  - close() is a no-op (succeeds) when driver is None
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

from applyocalypse_automation.browser.adapter import BrowserField
from applyocalypse_automation.browser.seleniumbase_adapter import SeleniumBaseBrowserAdapter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_field(selector: str = "#email", field_type: str = "text") -> BrowserField:
    return BrowserField(
        field_id="f1",
        label="Email",
        field_type=field_type,
        selector=selector,
        required=False,
        confidence=1.0,
    )


# ---------------------------------------------------------------------------
# Metadata / identity
# ---------------------------------------------------------------------------

def test_adapter_name_attribute():
    adapter = SeleniumBaseBrowserAdapter()
    assert adapter.name == "seleniumbase"


# ---------------------------------------------------------------------------
# launch() fail-safe
# ---------------------------------------------------------------------------

def test_launch_returns_ok_false_when_seleniumbase_not_installed(tmp_path: Path):
    with patch.dict(sys.modules, {"seleniumbase": None}):
        adapter = SeleniumBaseBrowserAdapter()
        result = asyncio.run(adapter.launch(run_id="test-run", user_data_dir=tmp_path / "profile"))
    assert result.ok is False
    assert "seleniumbase" in result.message.lower()
    assert result.payload is not None
    assert result.payload.get("install_hint") is not None


# ---------------------------------------------------------------------------
# No-driver guards (driver is None before launch)
# ---------------------------------------------------------------------------

def test_open_url_without_launch_returns_ok_false():
    adapter = SeleniumBaseBrowserAdapter()
    result = asyncio.run(adapter.open_url("https://example.com"))
    assert result.ok is False


def test_detect_fields_without_launch_returns_empty_list():
    adapter = SeleniumBaseBrowserAdapter()
    fields = asyncio.run(adapter.detect_fields())
    assert fields == []


def test_detect_blockers_without_launch_returns_empty_list():
    adapter = SeleniumBaseBrowserAdapter()
    blockers = asyncio.run(adapter.detect_blockers())
    assert blockers == []


def test_capture_dom_snapshot_without_launch_returns_ok_false(tmp_path: Path):
    adapter = SeleniumBaseBrowserAdapter()
    result = asyncio.run(adapter.capture_dom_snapshot(tmp_path / "snap.json"))
    assert result.ok is False


def test_extract_visible_text_without_launch_returns_ok_false():
    adapter = SeleniumBaseBrowserAdapter()
    result = asyncio.run(adapter.extract_visible_text())
    assert result.ok is False


def test_fill_field_without_launch_returns_ok_false():
    adapter = SeleniumBaseBrowserAdapter()
    result = asyncio.run(adapter.fill_field(_make_field(), "test@example.com"))
    assert result.ok is False


def test_fill_field_with_empty_selector_returns_ok_false():
    adapter = SeleniumBaseBrowserAdapter()
    result = asyncio.run(adapter.fill_field(_make_field(selector=""), "test@example.com"))
    assert result.ok is False


def test_upload_file_missing_path_returns_ok_false(tmp_path: Path):
    adapter = SeleniumBaseBrowserAdapter()
    missing = tmp_path / "nonexistent.pdf"
    result = asyncio.run(adapter.upload_file(_make_field(), missing))
    assert result.ok is False
    assert "does not exist" in result.message.lower()


def test_click_by_text_without_launch_returns_ok_false():
    adapter = SeleniumBaseBrowserAdapter()
    result = asyncio.run(adapter.click_by_text(["Submit"]))
    assert result.ok is False


def test_click_final_submit_without_launch_returns_ok_false():
    adapter = SeleniumBaseBrowserAdapter()
    result = asyncio.run(adapter.click_final_submit(["Submit Application"]))
    assert result.ok is False


def test_screenshot_without_launch_returns_ok_false(tmp_path: Path):
    adapter = SeleniumBaseBrowserAdapter()
    result = asyncio.run(adapter.screenshot(tmp_path / "shot.png"))
    assert result.ok is False


# ---------------------------------------------------------------------------
# pause / close — always succeed regardless of driver state
# ---------------------------------------------------------------------------

def test_pause_always_returns_ok_true():
    adapter = SeleniumBaseBrowserAdapter()
    result = asyncio.run(adapter.pause("waiting for OTP"))
    assert result.ok is True
    assert result.payload is not None
    assert result.payload.get("reason") == "waiting for OTP"


def test_close_without_launch_is_noop():
    adapter = SeleniumBaseBrowserAdapter()
    result = asyncio.run(adapter.close())
    assert result.ok is True
