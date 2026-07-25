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


def _submenu(menu, title):
    return next(a.menu() for a in menu.actions() if a.text() == title)


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


def test_the_load_menu_offers_one_item_per_format(window):
    """One item per format, generated from media.FORMATS, so the menu says what it opens
    and the file dialog lists one format's files rather than a mixed bag."""
    from zxemu_ui import media

    labels = _labels(_menu(window, "&Load"))
    assert labels[:6] == [
        "Load TAP…", "Load TZX…", "Load TRD…", "Load SCL…", "Load SNA…", "Load Z80…",
    ]
    assert labels == [f.menu_label for f in media.FORMATS] + [
        "Load &Recent", "&Tape Deck", "&Disk Drive",
    ]
    # Tapes, disks and snapshots are different things, so they are separated -- as are the
    # deck and the drive, which operate the medium you already mounted rather than
    # choosing a new one.
    assert sum(1 for a in _menu(window, "&Load").actions() if a.isSeparator()) == 4


def test_the_tape_deck_menu_exposes_both_loaders_and_the_transport(window):
    """Fast Load is the switch between the ROM trap and real pulse replay, so it has to be
    reachable and has to start on -- an IDE that loads tapes in real time by default would
    look broken."""
    deck = _submenu(_menu(window, "&Load"), "&Tape Deck")
    labels = _labels(deck)
    assert labels == ["&Fast Load", "Tape &Sound", "&Play", "S&top", "&Rewind", "&Eject"]
    checked = {a.text(): a.isChecked() for a in deck.actions() if a.isCheckable()}
    assert checked == {"&Fast Load": True, "Tape &Sound": True}


def test_each_load_item_opens_a_dialog_filtered_to_its_own_format(window, monkeypatch):
    """The whole point of splitting them: clicking Load TZX must not show .tap files."""
    seen = []

    class _FakeFileDialog:
        """Stands in for QFileDialog. Patched at the window's own reference, because
        replacing a sip static method on the real class crashes the interpreter."""

        @staticmethod
        def getOpenFileName(*args):  # noqa: N802 (Qt naming)
            seen.append(args)
            return "", ""

    monkeypatch.setattr("zxemu_ui.main_window.QFileDialog", _FakeFileDialog)

    for action in _menu(window, "&Load").actions():
        if action.text().startswith("Load ") and not action.menu():
            action.trigger()

    titles = [args[1] for args in seen]
    filters = [args[3] for args in seen]
    assert titles == [
        "Load TAP", "Load TZX", "Load TRD", "Load SCL", "Load SNA", "Load Z80",
    ]
    assert filters == [
        "TAP tape image (*.tap)", "TZX tape image (*.tzx)",
        "TR-DOS disk image (*.trd)", "SCL disk image (*.scl)",
        "SNA snapshot (*.sna)", "Z80 snapshot (*.z80)",
    ]


def test_the_disk_drive_menu_exposes_the_transport(window):
    drive = _submenu(_menu(window, "&Load"), "&Disk Drive")
    assert _labels(drive) == [
        "Mount in Drive &B…", "&Write Protect", "&Save Disk As…", "E&ject Disk",
    ]
    protect = next(a for a in drive.actions() if a.text() == "&Write Protect")
    assert protect.isCheckable() and not protect.isChecked()


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
    assert labels == ["ZX Spectrum 48K", "ZX Spectrum 128K", "Pentagon 128 (TR-DOS)"]
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


def test_a_handler_never_receives_the_triggered_checked_flag(qapp, window):
    """PyQt hands ``triggered``'s bool to any slot that accepts an argument, which turns
    a handler like ``lambda f=thing: ...`` into ``f=False`` -- and an exception inside a
    Qt slot aborts the process rather than logging. add_items must absorb the flag."""
    from PyQt5.QtWidgets import QMenu

    got = []
    menu = QMenu()
    menu_builder.add_items(window, menu, [
        Item := menu_builder.Item("Open", lambda value="the real default": got.append(value)),
    ])
    menu.actions()[0].trigger()

    assert got == ["the real default"]


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
