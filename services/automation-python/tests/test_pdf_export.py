"""Discovery of the external converter binaries used for DOCX to PDF export."""

from __future__ import annotations

from pathlib import Path

import pytest

from applyocalypse_automation.documents import pdf_export


def test_find_soffice_prefers_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pdf_export.shutil, "which", lambda name: "/usr/bin/soffice" if name == "soffice" else None)
    assert pdf_export._find_soffice() == "/usr/bin/soffice"


def test_find_soffice_accepts_libreoffice_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pdf_export.shutil, "which", lambda name: "/usr/bin/libreoffice" if name == "libreoffice" else None
    )
    assert pdf_export._find_soffice() == "/usr/bin/libreoffice"


def test_find_soffice_finds_windows_install_missing_from_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Windows installer does not add soffice.exe to PATH.

    Without this fallback the app reports LibreOffice as present in Settings (the
    TypeScript diagnostic checks Program Files) while export silently falls through
    to another exporter or fails outright.
    """
    program_files = tmp_path / "Program Files"
    installed = program_files / "LibreOffice" / "program" / "soffice.exe"
    installed.parent.mkdir(parents=True)
    installed.write_text("", encoding="utf-8")

    monkeypatch.setattr(pdf_export.sys, "platform", "win32")
    monkeypatch.setattr(pdf_export.shutil, "which", lambda name: None)
    monkeypatch.setenv("PROGRAMFILES", str(program_files))

    assert pdf_export._find_soffice() == str(installed)


def test_find_soffice_returns_none_when_absent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pdf_export.sys, "platform", "win32")
    monkeypatch.setattr(pdf_export.shutil, "which", lambda name: None)
    monkeypatch.setenv("PROGRAMFILES", str(tmp_path / "nowhere"))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "nowhere-x86"))

    assert pdf_export._find_soffice() is None


def test_find_soffice_skips_windows_paths_on_posix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    program_files = tmp_path / "Program Files"
    installed = program_files / "LibreOffice" / "program" / "soffice.exe"
    installed.parent.mkdir(parents=True)
    installed.write_text("", encoding="utf-8")

    monkeypatch.setattr(pdf_export.sys, "platform", "linux")
    monkeypatch.setattr(pdf_export.shutil, "which", lambda name: None)
    monkeypatch.setenv("PROGRAMFILES", str(program_files))

    assert pdf_export._find_soffice() is None


MAC_SOFFICE = "/Applications/LibreOffice.app/Contents/MacOS/soffice"


def test_find_soffice_looks_inside_the_mac_app_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    """The macOS app is a bundle dragged into /Applications, and it never touches PATH."""
    monkeypatch.setattr(pdf_export.sys, "platform", "darwin")
    monkeypatch.setattr(pdf_export.shutil, "which", lambda name: None)
    monkeypatch.setattr(pdf_export.Path, "exists", lambda self: self.as_posix() == MAC_SOFFICE)

    assert Path(pdf_export._find_soffice() or "").as_posix() == MAC_SOFFICE


def test_find_soffice_finds_a_per_user_mac_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    installed = tmp_path / "Applications" / "LibreOffice.app" / "Contents" / "MacOS" / "soffice"
    installed.parent.mkdir(parents=True)
    installed.write_text("", encoding="utf-8")

    monkeypatch.setattr(pdf_export.sys, "platform", "darwin")
    monkeypatch.setattr(pdf_export.shutil, "which", lambda name: None)
    monkeypatch.setattr(pdf_export.Path, "home", lambda: tmp_path)

    assert pdf_export._find_soffice() == str(installed)


def test_find_soffice_returns_none_on_a_mac_without_libreoffice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pdf_export.sys, "platform", "darwin")
    monkeypatch.setattr(pdf_export.shutil, "which", lambda name: None)
    monkeypatch.setattr(pdf_export.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(pdf_export.Path, "exists", lambda self: False)

    assert pdf_export._find_soffice() is None


def test_export_reports_missing_converters_when_nothing_is_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    docx_path = tmp_path / "resume.docx"
    docx_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(pdf_export, "_find_soffice", lambda: None)
    monkeypatch.setattr(pdf_export, "_export_with_docx2pdf", lambda *_args, **_kwargs: None)

    result = pdf_export.export_docx_to_pdf(docx_path, tmp_path)

    assert result.ok is False
    assert result.code == "DOCX_PDF_EXPORTER_UNAVAILABLE"
