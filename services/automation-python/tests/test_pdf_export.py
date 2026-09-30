"""Discovery of the external converter binaries used for DOCX to PDF export."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

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
    monkeypatch.setattr(pdf_export, "_export_with_word", lambda *_args, **_kwargs: None)

    result = pdf_export.export_docx_to_pdf(docx_path, tmp_path)

    assert result.ok is False
    assert result.code == "DOCX_PDF_EXPORTER_UNAVAILABLE"


def test_word_command_drives_word_over_com_on_windows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pdf_export.sys, "platform", "win32")
    docx_path, pdf_path = tmp_path / "it's a resume.docx", tmp_path / "out.pdf"

    word = pdf_export._word_command(docx_path, pdf_path)

    assert word is not None
    command, env = word
    assert command[0] == "powershell"
    # Paths ride in env vars so a quote in a file name cannot reach the script text.
    assert str(docx_path) not in " ".join(command)
    assert env["APPLYO_DOCX_PATH"] == str(docx_path)
    assert env["APPLYO_PDF_PATH"] == str(pdf_path)


def test_word_command_uses_applescript_on_a_mac_with_word(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pdf_export.sys, "platform", "darwin")
    monkeypatch.setattr(pdf_export.Path, "exists", lambda self: self == pdf_export._MAC_WORD_APP)

    word = pdf_export._word_command(tmp_path / "a.docx", tmp_path / "a.pdf")

    assert word is not None
    command, _env = word
    assert command[0] == "osascript"
    assert command[-2:] == [str(tmp_path / "a.docx"), str(tmp_path / "a.pdf")]


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_word_command_is_none_without_word(platform: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pdf_export.sys, "platform", platform)
    monkeypatch.setattr(pdf_export.Path, "exists", lambda self: False)

    assert pdf_export._word_command(tmp_path / "a.docx", tmp_path / "a.pdf") is None


def _fake_word(monkeypatch: pytest.MonkeyPatch, *, returncode: int, writes_pdf: bool) -> None:
    def run(command: list[str], **kwargs: object) -> SimpleNamespace:
        env = kwargs["env"]
        assert isinstance(env, dict)
        if writes_pdf:
            Path(env["APPLYO_PDF_PATH"]).write_bytes(b"%PDF-1.7")
        return SimpleNamespace(returncode=returncode, stdout="", stderr="")

    monkeypatch.setattr(pdf_export.sys, "platform", "win32")
    monkeypatch.setattr(pdf_export, "_find_soffice", lambda: None)
    monkeypatch.setattr(pdf_export.subprocess, "run", run)


@pytest.mark.parametrize(
    ("returncode", "writes_pdf", "ok", "code"),
    [
        (0, True, True, None),
        (1, False, False, "DOCX_PDF_EXPORT_FAILED"),
        (0, False, False, "DOCX_PDF_EXPORT_FAILED"),
        (3, False, False, "DOCX_PDF_EXPORTER_UNAVAILABLE"),
    ],
)
def test_export_through_word(
    returncode: int, writes_pdf: bool, ok: bool, code: str | None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    docx_path = tmp_path / "resume.docx"
    docx_path.write_text("", encoding="utf-8")
    _fake_word(monkeypatch, returncode=returncode, writes_pdf=writes_pdf)

    result = pdf_export.export_docx_to_pdf(docx_path, tmp_path / "out")

    assert (result.ok, result.code) == (ok, code)
    if ok:
        assert result.exporter == "word"
        assert result.pdf_path == tmp_path / "out" / "resume.pdf"
        assert result.pdf_path.read_bytes() == b"%PDF-1.7"


def test_export_reports_a_word_that_hangs_as_a_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    docx_path = tmp_path / "resume.docx"
    docx_path.write_text("", encoding="utf-8")

    def hang(command: list[str], **kwargs: object) -> None:
        raise subprocess.TimeoutExpired(command, 5)

    monkeypatch.setattr(pdf_export.sys, "platform", "win32")
    monkeypatch.setattr(pdf_export, "_find_soffice", lambda: None)
    monkeypatch.setattr(pdf_export.subprocess, "run", hang)

    result = pdf_export.export_docx_to_pdf(docx_path, tmp_path, timeout_seconds=5)

    assert (result.ok, result.exporter, result.code) == (False, "word", "DOCX_PDF_EXPORT_TIMEOUT")


@pytest.mark.skipif(sys.platform != "win32", reason="drives the real Word over COM")
def test_real_word_exports_a_pdf_when_installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_paragraph("Ada Lovelace")
    docx_path = tmp_path / "it's a resume.docx"
    document.save(str(docx_path))
    monkeypatch.setattr(pdf_export, "_find_soffice", lambda: None)

    result = pdf_export.export_docx_to_pdf(docx_path, tmp_path / "out", timeout_seconds=120)

    if result.code == "DOCX_PDF_EXPORTER_UNAVAILABLE":
        pytest.skip("Microsoft Word is not installed")
    assert result.ok, result.stderr
    assert result.pdf_path is not None
    assert result.pdf_path.read_bytes().startswith(b"%PDF")
