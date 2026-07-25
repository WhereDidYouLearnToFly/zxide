"""Tests for the "Show in Explorer" command builder (zxemu_ui.system_open).

The point of splitting the argv out of the launch is that these can be checked without
a file manager opening on the developer's desktop -- including the platforms this machine
isn't.
"""

from __future__ import annotations

from zxemu_ui.system_open import file_manager_name, reveal, reveal_command


def test_windows_selects_the_file_within_its_folder(tmp_path):
    target = tmp_path / "main.asm"
    target.write_text("nop\n", encoding="utf-8")
    # No space after the comma: explorer takes the path glued to /select, and opens
    # My Documents for anything else.
    assert reveal_command(target, "win32") == ["explorer", f"/select,{target}"]


def test_windows_opens_a_folder_directly(tmp_path):
    assert reveal_command(tmp_path, "win32") == ["explorer", str(tmp_path)]


def test_macos_reveals_a_file_and_opens_a_folder(tmp_path):
    target = tmp_path / "main.asm"
    target.write_text("nop\n", encoding="utf-8")
    assert reveal_command(target, "darwin") == ["open", "-R", str(target)]
    assert reveal_command(tmp_path, "darwin") == ["open", str(tmp_path)]


def test_linux_gets_the_containing_folder(tmp_path):
    """xdg-open has no portable "select this file", so aim at the folder it lives in."""
    target = tmp_path / "main.asm"
    target.write_text("nop\n", encoding="utf-8")
    assert reveal_command(target, "linux") == ["xdg-open", str(tmp_path)]
    assert reveal_command(tmp_path, "linux") == ["xdg-open", str(tmp_path)]


def test_the_menu_label_matches_the_platform():
    assert file_manager_name("win32") == "Explorer"
    assert file_manager_name("darwin") == "Finder"
    assert file_manager_name("linux") == "File Manager"


def test_reveal_reports_a_missing_path_instead_of_launching(tmp_path, monkeypatch):
    launched = []
    monkeypatch.setattr("zxemu_ui.system_open.subprocess.Popen", lambda argv: launched.append(argv))

    error = reveal(tmp_path / "gone.asm")

    assert error and "no longer exists" in error
    assert not launched


def test_reveal_survives_a_missing_file_manager(tmp_path, monkeypatch):
    """No file manager is a cosmetic disappointment, not a reason to take the IDE down."""
    def boom(_argv):
        raise OSError("xdg-open not found")

    monkeypatch.setattr("zxemu_ui.system_open.subprocess.Popen", boom)

    error = reveal(tmp_path)

    assert error and "could not open a file manager" in error
