"""Tests for the Output console: clickable result lines, Clear, and the window's wiring."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt5.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PyQt5.QtGui import QContextMenuEvent, QMouseEvent  # noqa: E402
from PyQt5.QtWidgets import QApplication, QInputDialog, QMenu  # noqa: E402

from zxemu_ui.controller import EmulatorController  # noqa: E402
from zxemu_ui.machine_factory import build_machine  # noqa: E402
from zxemu_ui.main_window import MainWindow  # noqa: E402
from zxemu_ui.panels.output_console import OutputConsole  # noqa: E402
from zxemu_ui.workspace.project import Project  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def _click(console, block_number: int):
    """Click in the middle of a document block, the way a user clicks a result line."""
    block = console.document().findBlockByNumber(block_number)
    cursor = console.textCursor()
    cursor.setPosition(block.position())
    rect = console.cursorRect(cursor)
    point = QPoint(rect.center().x() + 4, rect.center().y())
    console.mousePressEvent(QMouseEvent(
        QEvent.MouseButtonPress, QPointF(point), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier
    ))


def _click_line_containing(console, needle: str):
    """Click the result line holding ``needle``.

    The window has already logged other things (opening the project, for one), so a
    result's block number isn't known up front -- find it the way a user does, by reading.
    """
    document = console.document()
    for number in range(document.blockCount()):
        if needle in document.findBlockByNumber(number).text():
            _click(console, number)
            return number
    raise AssertionError(f"no output line containing {needle!r}")


def _context_menu_actions(console, monkeypatch):
    """Open the console's context menu without blocking, and return its actions."""
    captured = {}
    monkeypatch.setattr(QMenu, "exec_", lambda self, *args: captured.setdefault("menu", self))
    console.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Mouse, QPoint(5, 5)))
    return captured["menu"].actions()


def _find_action(actions, text):
    """Find a menu action by label. Qt appends "\tCtrl+C" to the standard ones."""
    def label(action):
        return action.text().split("\t")[0].replace("&", "")

    return next((a for a in actions if label(a) == text), None)


# --- the console itself -------------------------------------------------------

def test_clicking_a_linked_line_emits_its_target(qapp, tmp_path):
    console = OutputConsole()
    fired = []
    console.link_activated.connect(lambda path, line: fired.append((path, line)))

    console.append_line('── Find "player" ──')
    console.append_link("core/player.asm:12: player_init:", tmp_path / "core" / "player.asm", 12)

    _click(console, 1)

    assert fired == [(str(tmp_path / "core" / "player.asm"), 12)]


def test_clicking_ordinary_log_text_does_nothing(qapp):
    console = OutputConsole()
    fired = []
    console.link_activated.connect(lambda *args: fired.append(args))

    console.append_line("Build failed (exit code 1).")
    _click(console, 0)

    assert fired == []


def test_linked_lines_are_underlined_to_look_clickable(qapp, tmp_path):
    console = OutputConsole()
    console.append_line("plain")
    console.append_link("main.asm:1: start:", tmp_path / "main.asm", 1)

    def underlined(block_number):
        block = console.document().findBlockByNumber(block_number)
        return any(f.format.fontUnderline() for f in block.textFormats())

    assert not underlined(0)
    assert underlined(1)


# --- Clear, on the context menu -----------------------------------------------

def test_clear_is_on_the_context_menu_beside_the_usual_text_actions(qapp, monkeypatch):
    """It lives there rather than on a button: rare action, and a button costs a row of
    height in a panel whose job is showing as many lines as possible."""
    console = OutputConsole()
    console.append_line("something to clear")

    actions = _context_menu_actions(console, monkeypatch)

    assert _find_action(actions, "Clear") is not None
    assert _find_action(actions, "Select All") is not None  # the standard menu survives


def test_clear_empties_the_text_and_forgets_the_links(qapp, tmp_path, monkeypatch):
    """Stale targets would leave clicks jumping to results no longer on screen."""
    console = OutputConsole()
    fired = []
    console.link_activated.connect(lambda *args: fired.append(args))
    console.append_link("main.asm:3: start:", tmp_path / "main.asm", 3)

    _find_action(_context_menu_actions(console, monkeypatch), "Clear").trigger()

    assert console.toPlainText() == ""
    console.append_line("fresh log line")  # now block 0, where the link used to be
    _click(console, 0)
    assert fired == []


def test_clear_is_disabled_when_there_is_nothing_to_clear(qapp, monkeypatch):
    console = OutputConsole()
    assert not _find_action(_context_menu_actions(console, monkeypatch), "Clear").isEnabled()


# --- wired into the window ----------------------------------------------------

def _window_with_project(qapp, tmp_path):
    project = Project.create(tmp_path / "p", "P", "48k")
    (project.folder / "core").mkdir()
    (project.folder / "core" / "player.asm").write_text(
        "player_init:\n    ld a,0\n    ret\n", encoding="utf-8"
    )
    machine = build_machine("48k")
    window = MainWindow(machine, EmulatorController(machine))
    window._open_project(str(project.folder))
    return window, project


def test_find_in_project_lists_hits_and_clicking_one_opens_the_file(qapp, tmp_path, monkeypatch):
    window, project = _window_with_project(qapp, tmp_path)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("player_init", True))

    window._find_in_project()

    text = window.output_console.toPlainText()
    assert "player.asm:1" in text
    assert "match(es) in 1 file(s)" in text

    _click_line_containing(window.output_console, "player.asm:1")
    path, line = window.editor.current_location()
    assert path == str(project.folder / "core" / "player.asm") and line == 1


def test_find_in_project_says_so_when_there_are_no_matches(qapp, tmp_path, monkeypatch):
    window, _project = _window_with_project(qapp, tmp_path)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("nothing_here", True))

    window._find_in_project()

    assert "No matches" in window.output_console.toPlainText()


def test_find_in_project_needs_a_project(qapp, tmp_path, monkeypatch):
    machine = build_machine("48k")
    window = MainWindow(machine, EmulatorController(machine))
    window.project = None
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("x", True))

    window._find_in_project()

    assert "needs a project folder" in window.output_console.toPlainText()


def test_go_to_line_moves_the_caret_in_the_open_file(qapp, tmp_path, monkeypatch):
    window, project = _window_with_project(qapp, tmp_path)
    window.editor.open_file(str(project.folder / "core" / "player.asm"))
    monkeypatch.setattr(QInputDialog, "getInt", lambda *a, **k: (3, True))

    window._goto_line_dialog()

    assert window.editor.current_location()[1] == 3


def test_go_to_line_is_bounded_by_the_file_length(qapp, tmp_path, monkeypatch):
    """The dialog's maximum comes from the file, so you can't ask for line 9000 of 4.

    Four, not three: the file ends in a newline, so the editor really does show an empty
    fourth line the caret can sit on -- the bound follows what's on screen.
    """
    window, project = _window_with_project(qapp, tmp_path)
    window.editor.open_file(str(project.folder / "core" / "player.asm"))
    seen = {}

    def fake_get_int(_parent, _title, label, value, minimum, maximum, step):
        seen.update(label=label, maximum=maximum)
        return maximum, True

    monkeypatch.setattr(QInputDialog, "getInt", fake_get_int)
    window._goto_line_dialog()

    assert seen["maximum"] == 4
    assert "1–4" in seen["label"]


def test_go_to_line_without_an_open_file_explains_itself(qapp, tmp_path):
    machine = build_machine("48k")
    window = MainWindow(machine, EmulatorController(machine))
    window._goto_line_dialog()
    assert "needs an open file" in window.output_console.toPlainText()


def test_show_in_file_manager_launches_the_platform_command(qapp, tmp_path, monkeypatch):
    window, project = _window_with_project(qapp, tmp_path)
    launched = []
    monkeypatch.setattr("zxemu_ui.system_open.subprocess.Popen", lambda argv: launched.append(argv))

    window.project_tree.setCurrentIndex(window._fs_model.index(str(project.folder / "main.asm")))
    window._reveal_in_file_manager()

    assert len(launched) == 1
    assert "main.asm" in " ".join(launched[0])
