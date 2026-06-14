"""Tests for the one-page resume enforcement logic in runner.py."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from applyocalypse_automation.runner import _build_overflow_jd, _remutate_and_export


def test_overflow_jd_mentions_page_count_and_one_page() -> None:
    result = _build_overflow_jd("We need a Python engineer.", 2)
    assert "2" in result
    assert "ONE page" in result


def test_overflow_jd_mentions_page_count_and_one_page_three_pages() -> None:
    result = _build_overflow_jd("Backend engineer role.", 3)
    assert "3" in result
    assert "ONE page" in result


def test_remutate_and_export_runs_mutations_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    import applyocalypse_automation.runner as runner_module

    call_order: list[str] = []

    def fake_placeholders(master, output, replacements):
        call_order.append("placeholders")
        return (output, list(replacements.keys()))

    def fake_bullets(src, dst, bullet_map):
        call_order.append("bullets")
        return (dst, list(bullet_map.keys()))

    fake_export_result = MagicMock()
    fake_export_result.ok = True

    def fake_export(docx_path, out_dir):
        call_order.append("export")
        return fake_export_result

    monkeypatch.setattr(runner_module, "mutate_docx_placeholders", fake_placeholders)
    monkeypatch.setattr(runner_module, "mutate_docx_bullet_anchors", fake_bullets)
    monkeypatch.setattr(runner_module, "export_docx_to_pdf", fake_export)

    result = _remutate_and_export(
        master_path=Path("/fake/master.docx"),
        output_path=Path("/fake/output.docx"),
        replacements={"{{NAME}}": "Jane"},
        bullet_map={"{{BULLETS}}": ["• Did a thing"]},
        output_dir=Path("/fake/out"),
    )

    assert call_order == ["placeholders", "bullets", "export"]
    assert result is fake_export_result


def test_remutate_and_export_skips_bullets_when_bullet_map_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    import applyocalypse_automation.runner as runner_module

    call_order: list[str] = []

    def fake_placeholders(master, output, replacements):
        call_order.append("placeholders")
        return (output, list(replacements.keys()))

    def fake_bullets(src, dst, bullet_map):
        call_order.append("bullets")
        return (dst, list(bullet_map.keys()))

    fake_export_result = MagicMock()

    def fake_export(docx_path, out_dir):
        call_order.append("export")
        return fake_export_result

    monkeypatch.setattr(runner_module, "mutate_docx_placeholders", fake_placeholders)
    monkeypatch.setattr(runner_module, "mutate_docx_bullet_anchors", fake_bullets)
    monkeypatch.setattr(runner_module, "export_docx_to_pdf", fake_export)

    _remutate_and_export(
        master_path=Path("/fake/master.docx"),
        output_path=Path("/fake/output.docx"),
        replacements={"{{NAME}}": "Jane"},
        bullet_map={},
        output_dir=Path("/fake/out"),
    )

    assert call_order == ["placeholders", "export"]
    assert "bullets" not in call_order
