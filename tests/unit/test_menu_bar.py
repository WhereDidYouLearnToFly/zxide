"""Tests for the menu bar built by zxemu_ui.menu_builder.

The menu was two hundred lines of hand-written QAction plumbing before it became a data
declaration, and nothing about a menu fails loudly: a lost item, a dropped shortcut or an
unconnected handler all look like a working IDE until you reach for the thing. So the
shape is asserted here, plus the fact that items actually invoke something.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from zxemu_ui import menu_builder  # noqa: E402
from zxemu_ui.controller import EmulatorController  # noqa: E402
from zxemu_ui.machine_factory import build_machine  # noqa: E402
from zxemu_ui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp):
    machine = build_machine("48k")
    return MainWindow(machine, EmulatorController(machine))


def _menu(window, title):
    return next(a.menu() for a in window.menuBar().actions() if a.text() == title)


def _labels(menu):
    return [a.text() for a in menu.actions() if not a.isSeparator()]


def _shortcuts(window):
    found = {}
    for top in window.menuBar().actions():
        if top.menu() is None:
            continue
        for action in top.menu().actions():
            if not action.shortcut().isEmpty():
                found[action.shortcut().toString()] = action.text()
    return found


def test_every_expected_menu_is_present_and_in_order(window):
    titles = [a.text() for a in window.menuBar().actions()]
    assert titles == [
        "&File", "&Edit", "&Build", "&Load", "&Model", "D&isassembly",
        "&Breaks", "&Watch", "&Reversing", "&Compression", "&View", "Settings",
    ]


def test_the_documented_shortcuts_are_all_bound(window):
    """These are in the README's key table; a silent loss would make the docs lie."""
    shortcuts = _shortcuts(window)
    assert shortcuts["F5"] == "Build && Debug"
    assert shortcuts["Ctrl+F5"] == "Build && Run"
    assert shortcuts["Ctrl+F"] == "&Find in Project…"
    assert shortcuts["Ctrl+G"] == "&Go to Line…"
    assert shortcuts["Ctrl+F10"] == "Run to Cursor"
    assert shortcuts["Ctrl+S"] == "&Save"
    assert shortcuts["Ctrl+Shift+S"] == "Save A&ll"


def test_separators_survive_the_move_to_data(window):
    """A separator is a positional thing, so it can only be checked by counting."""
    assert sum(1 for a in _menu(window, "&File").actions() if a.isSeparator()) == 2
    assert sum(1 for a in _menu(window, "&Watch").actions() if a.isSeparator()) == 1


def test_checkable_items_are_checkable_and_the_rest_are_not(window):
    reversing = {a.text(): a.isCheckable() for a in _menu(window, "&Reversing").actions()}
    assert reversing["Record Coverage"] and reversing["Record Trace"]
    assert not reversing["Find Bytes…"]


def test_the_model_menu_ticks_the_live_machine(window):
    labels = _labels(_menu(window, "&Model"))
    assert labels == ["ZX Spectrum 48K", "ZX Spectrum 128K"]
    checked = [a.text() for a in _menu(window, "&Model").actions() if a.isChecked()]
    assert checked == ["ZX Spectrum 48K"]  # the machine this window was built with


def test_the_view_menu_lists_every_dock(window):
    labels = _labels(_menu(window, "&View"))
    assert len(window._all_docks) == 12
    for dock in window._all_docks:
        assert dock.toggleViewAction().text() in labels


def test_items_are_connected_to_something(window):
    """Triggering a harmless item must actually reach the window.

    "Clear All Watchpoints" is the safest probe: no dialog, no file, and its effect is
    visible in the log.
    """
    window.output_console.clear_output()
    action = next(a for a in _menu(window, "&Watch").actions()
                  if a.text() == "Clear All Watchpoints")

    action.trigger()

    assert "Cleared all watchpoints." in window.output_console.toPlainText()


def test_tooltips_survive(window):
    action = next(a for a in _menu(window, "&Build").actions() if a.text() == "Build && Debug")
    assert "breakpoints active" in action.toolTip()


# --- the builder's own vocabulary --------------------------------------------

def test_an_item_with_no_label_is_a_separator(qapp, window):
    from PyQt5.QtWidgets import QMenu

    menu = QMenu()
    menu_builder.add_items(window, menu, [
        menu_builder.Item("First", lambda: None),
        menu_builder.SEPARATOR,
        menu_builder.Item("Second", lambda: None),
    ])
    kinds = [("sep" if a.isSeparator() else a.text()) for a in menu.actions()]
    assert kinds == ["First", "sep", "Second"]


def test_a_prebuilt_action_is_reused_and_can_be_renamed(qapp, window):
    """Dock toggles come with their own action; the menu may relabel it."""
    from PyQt5.QtWidgets import QMenu

    existing = window._disasm_dock.toggleViewAction()
    menu = QMenu()
    menu_builder.add_items(window, menu, [menu_builder.Item("Show Disassembly", action=existing)])

    assert menu.actions() == [existing]
    assert existing.text() == "Show Disassembly"


def test_a_checkable_item_connects_to_toggled_not_triggered(qapp, window):
    """A checkable action's handler wants the new state, which only toggled carries."""
    from PyQt5.QtWidgets import QMenu

    seen = []
    menu = QMenu()
    menu_builder.add_items(window, menu, [
        menu_builder.Item("Record", seen.append, checkable=True),
    ])
    menu.actions()[0].setChecked(True)

    assert seen == [True]
