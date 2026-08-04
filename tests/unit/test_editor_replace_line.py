"""Editing one source line through the editor (zxemu_ui.editor.EditorArea.replace_line).

This is how the memory map moves a block of code, and the reason it goes through the
editor rather than writing the file is entirely about safety: an unsaved tab must not be
clobbered, and the change must be undoable. Those two properties are what these pin.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from zxemu_ui.editor import EditorArea  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _source(tmp_path, text="Attributes  equ $8300       ; 00D7\nGame        equ $8C50\n"):
    path = tmp_path / "memmap.i"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_replaces_the_line_and_leaves_the_rest_alone(qapp, tmp_path):
    path = _source(tmp_path)
    editor = EditorArea()
    assert editor.replace_line(path, 1, "Attributes  equ $9000       ; 00D7")
    assert editor.currentWidget().toPlainText() == "Attributes  equ $9000       ; 00D7\nGame        equ $8C50\n"


def test_the_change_is_not_written_to_disk_until_saved(qapp, tmp_path):
    path = _source(tmp_path)
    original = open(path, encoding="utf-8").read()
    editor = EditorArea()
    editor.replace_line(path, 1, "Attributes  equ $9000       ; 00D7")
    assert open(path, encoding="utf-8").read() == original  # still the old text on disk
    assert editor.currentWidget().document().isModified()

    editor.save_all()
    assert "equ $9000" in open(path, encoding="utf-8").read()


def test_the_change_is_undoable(qapp, tmp_path):
    path = _source(tmp_path)
    editor = EditorArea()
    editor.replace_line(path, 1, "Attributes  equ $9000       ; 00D7")
    editor.currentWidget().undo()
    assert "equ $8300" in editor.currentWidget().toPlainText()


def test_an_unsaved_edit_in_the_tab_survives(qapp, tmp_path):
    """The map must never silently discard what you were typing in that file."""
    path = _source(tmp_path)
    editor = EditorArea()
    editor.open_file(path)
    edit = editor.currentWidget()
    edit.setPlainText("Attributes  equ $8300       ; 00D7\nGame        equ $8C50\n; a line I just typed\n")

    editor.replace_line(path, 1, "Attributes  equ $9000       ; 00D7")
    text = editor.currentWidget().toPlainText()
    assert "; a line I just typed" in text
    assert "equ $9000" in text


def test_replacing_a_line_that_does_not_exist_reports_rather_than_raises(qapp, tmp_path):
    path = _source(tmp_path)
    editor = EditorArea()
    assert not editor.replace_line(path, 99, "nope")


def test_two_edits_to_one_file_both_land(qapp, tmp_path):
    """Arrange moves several blocks at once, which is several edits to the same table."""
    path = _source(tmp_path)
    editor = EditorArea()
    editor.replace_line(path, 1, "Attributes  equ $9000       ; 00D7")
    editor.replace_line(path, 2, "Game        equ $9200")
    assert editor.currentWidget().toPlainText() == "Attributes  equ $9000       ; 00D7\nGame        equ $9200\n"


def test_a_byte_order_mark_stays_at_the_start_of_the_file(qapp, tmp_path):
    """Inserting above line 1 must not push a BOM into the middle of the file.

    It did, and it broke a real build: a UTF-8 BOM read as plain utf-8 survives as an
    invisible U+FEFF character at position 0, so "insert before line 1" went in ahead of
    it. Three bytes then sat in column zero where sjasmplus reads a label name, and the
    error it printed named a character you cannot see.
    """
    path = tmp_path / "bom.asm"
    path.write_bytes(b"\xef\xbb\xbf    org $8000\r\n    nop\r\n")
    editor = EditorArea()
    editor.insert_lines(str(path), 1, ["    ; zxide: pin"])
    editor.save_all()

    data = path.read_bytes()
    assert data.startswith(b"\xef\xbb\xbf")           # still a BOM'd file...
    assert data.count(b"\xef\xbb\xbf") == 1           # ...and only at the front
    assert b"; zxide: pin" in data.split(b"\r\n")[0] or b"; zxide: pin" in data.split(b"\n")[0]


def test_a_file_without_a_bom_does_not_gain_one(qapp, tmp_path):
    path = tmp_path / "plain.asm"
    path.write_bytes(b"    org $8000\n")
    editor = EditorArea()
    editor.replace_line(str(path), 1, "    org $9000")
    editor.save_all()
    assert not path.read_bytes().startswith(b"\xef\xbb\xbf")


# --- invisible characters -------------------------------------------------------------


def _edit(qapp, text=""):
    from zxemu_ui.editor import CodeEdit
    edit = CodeEdit()
    edit.setPlainText(text)
    return edit


def test_pasting_drops_invisible_characters(qapp):
    """They arrive with anything copied from a browser, a PDF or a chat window."""
    from PyQt5.QtCore import QMimeData
    edit = _edit(qapp)
    data = QMimeData()
    data.setText("    ld\u00a0a,1\u200b   ; note\ufeff")
    edit.insertFromMimeData(data)
    assert edit.toPlainText() == "    ld a,1   ; note"


def test_pasting_ordinary_text_is_untouched(qapp):
    from PyQt5.QtCore import QMimeData
    edit = _edit(qapp)
    data = QMimeData()
    data.setText("    ld a,1   ; ordinary\n    ret\n")
    edit.insertFromMimeData(data)
    assert edit.toPlainText() == "    ld a,1   ; ordinary\n    ret\n"


def test_removing_invisible_characters_from_an_existing_file(qapp):
    """The exact shape that broke the build: a file marker pushed off line 1."""
    edit = _edit(qapp, "    ; pin\n﻿    org $8000\n    ld a,1\n")
    assert edit.remove_invisible() == 1
    assert edit.toPlainText() == "    ; pin\n    org $8000\n    ld a,1\n"


def test_removing_when_there_is_nothing_to_remove_changes_nothing(qapp):
    edit = _edit(qapp, "    org $8000\n")
    assert edit.remove_invisible() == 0
    assert edit.toPlainText() == "    org $8000\n"
