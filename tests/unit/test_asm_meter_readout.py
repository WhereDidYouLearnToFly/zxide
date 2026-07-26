"""Tests for the assembly meter's readout strip (MainWindow._update_asm_meter).

The arithmetic is covered in ``test_asm_meter``; what's pinned here is the wiring --
that it follows the focused tab, switches between "the selection" and "the whole file",
stays quiet for files that aren't assembly at all, and sits under the editor rather than
in the status bar's crowded corner.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt5.QtGui import QTextCursor  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from zxemu_ui.controller import EmulatorController  # noqa: E402
from zxemu_ui.machine_factory import build_machine  # noqa: E402
from zxemu_ui.main_window import MainWindow  # noqa: E402
from zxemu_ui.workspace.project import Project  # noqa: E402

_SOURCE = "start:\n    ld a,1\n    nop\n    ret\n"


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def _window_with(tmp_path, name="main.asm", text=_SOURCE):
    project = Project.create(tmp_path / "p", "P", "48k")
    path = project.folder / name
    path.write_text(text)
    machine = build_machine("48k")
    window = MainWindow(machine, EmulatorController(machine))
    window._open_project(str(project.folder))
    window.editor.open_file(str(path))
    return window


def _select_lines(window, first, last):
    """Select whole lines ``first``..``last`` (0-based) in the focused editor."""
    edit = window.editor.currentWidget()
    cursor = edit.textCursor()
    cursor.setPosition(edit.document().findBlockByNumber(first).position())
    end_block = edit.document().findBlockByNumber(last)
    cursor.setPosition(end_block.position() + end_block.length() - 1, QTextCursor.KeepAnchor)
    edit.setTextCursor(cursor)


def test_with_no_selection_it_measures_the_whole_file(qapp, tmp_path):
    window = _window_with(tmp_path)
    window._update_asm_meter()
    # ld a,1 (2) + nop (1) + ret (1) = 4 bytes; 7 + 4 + 10 = 21T
    assert window._meter_label.text() == "whole file: 4 bytes · 21 T · 3 instr"


def test_with_a_selection_it_measures_only_that(qapp, tmp_path):
    window = _window_with(tmp_path)
    _select_lines(window, 1, 1)  # just `ld a,1`
    window._update_asm_meter()
    assert window._meter_label.text() == "selection: 2 bytes · 7 T · 1 instr"


def test_a_multi_line_selection_sums_its_lines(qapp, tmp_path):
    window = _window_with(tmp_path)
    _select_lines(window, 1, 2)  # `ld a,1` and `nop`
    window._update_asm_meter()
    assert window._meter_label.text() == "selection: 3 bytes · 11 T · 2 instr"


def test_a_non_assembly_file_shows_nothing(qapp, tmp_path):
    window = _window_with(tmp_path, name="readme.txt", text="ld a,1\n")
    window._update_asm_meter()
    assert window._meter_label.text() == ""


def test_an_include_file_is_measured_even_though_it_cannot_be_built(qapp, tmp_path):
    window = _window_with(tmp_path, name="sprites.inc", text="    ld a,1\n")
    window._update_asm_meter()
    assert window._meter_label.text() == "whole file: 2 bytes · 7 T · 1 instr"


def test_the_welcome_tab_shows_nothing(qapp, tmp_path):
    project = Project.create(tmp_path / "p", "P", "48k")
    machine = build_machine("48k")
    window = MainWindow(machine, EmulatorController(machine))
    window._open_project(str(project.folder))
    window._update_asm_meter()  # only the welcome tab is open, which has no file path
    assert window._meter_label.text() == ""


def test_the_readout_sits_under_the_editor_not_in_the_status_bar(qapp, tmp_path):
    """It measures the text above it, so it lives with that text.

    In the status bar it was in the busiest corner of the window: the size grip owns that
    corner, and a maximized window (which has no grip) let the readout run flush to the
    screen edge with its last glyph clipped. As the editor's own footer it has the full
    width of the central widget and nothing can squeeze it.
    """
    window = _window_with(tmp_path)
    assert window.centralWidget().isAncestorOf(window._meter_label)
    assert not window.statusBar().isAncestorOf(window._meter_label)


def test_the_strip_disappears_when_there_is_nothing_to_measure(qapp, tmp_path):
    """An empty bar under a text file would be a row of height saying nothing."""
    window = _window_with(tmp_path, name="readme.txt", text="hello\n")
    window._update_asm_meter()
    assert not window._meter_bar.isVisible()

    window = _window_with(tmp_path / "code")
    window._update_asm_meter()
    assert window._meter_bar.isVisibleTo(window.centralWidget())


def test_selecting_text_schedules_a_refresh(qapp, tmp_path):
    """A selection change has to reach the readout, not just an edit."""
    window = _window_with(tmp_path)
    window._meter_timer.stop()
    _select_lines(window, 1, 2)
    assert window._meter_timer.isActive()


def test_editing_the_text_schedules_a_refresh(qapp, tmp_path):
    """The readout is debounced rather than recomputed on every keystroke."""
    window = _window_with(tmp_path)
    window._meter_timer.stop()
    window.editor.currentWidget().insertPlainText("    inc hl\n")
    assert window._meter_timer.isActive()
