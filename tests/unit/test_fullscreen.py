"""Fullscreen lends the emulator stage out and always gets it back.

The feature is small but has one way to fail badly: the stage is a *live* widget lent to
another window, so any exit route that forgets to reclaim it leaves the IDE with an empty
emulator dock and no picture. These tests are mostly about that -- every route home.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from zxemu_core.machine import Machine  # noqa: E402
from zxemu_ui.controller import EmulatorController  # noqa: E402
from zxemu_ui.panels.emulator_panel import EmulatorPanel  # noqa: E402
from zxemu_ui.panels.emulator_view import EmulatorView  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def panel(qapp):
    machine = Machine(bytes(0x4000))
    view = EmulatorView(machine)
    return EmulatorPanel(view, EmulatorController(machine))


def test_entering_fullscreen_moves_the_stage_out_of_the_panel(panel):
    stage = panel._stage
    panel.enter_fullscreen()

    assert panel.is_fullscreen
    assert stage.parent() is panel._fullscreen
    assert stage.parent() is not panel


def test_leaving_fullscreen_puts_the_stage_back(panel):
    stage = panel._stage
    panel.enter_fullscreen()
    panel.exit_fullscreen()

    assert not panel.is_fullscreen
    assert stage.parentWidget() is panel


def test_closing_the_window_directly_also_puts_the_stage_back(panel):
    """The window manager's close button is an exit route we do not control."""
    stage = panel._stage
    panel.enter_fullscreen()
    panel._fullscreen.close()

    assert not panel.is_fullscreen
    assert stage.parentWidget() is panel


def test_escape_leaves_fullscreen(panel):
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QKeyEvent

    panel.enter_fullscreen()
    panel._fullscreen.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))

    assert not panel.is_fullscreen


def test_the_same_view_object_survives_the_round_trip(panel):
    """Why the stage is *lent* rather than rebuilt: the view keeps its signal
    connections, its key matrix and any keys currently held down."""
    view = panel._view
    panel.enter_fullscreen()
    panel.exit_fullscreen()

    assert panel._stage._view is view


def test_toggling_reports_the_state(panel):
    states = []
    panel.fullscreen_changed.connect(states.append)

    panel.toggle_fullscreen()
    panel.toggle_fullscreen()

    assert states == [True, False]


def test_escape_is_not_a_spectrum_key(qapp):
    """Esc can only mean "leave fullscreen" because the Spectrum has no such key --
    if it were ever mapped, this test is where that collision shows up."""
    from PyQt5.QtCore import Qt
    from zxemu_ui.panels import emulator_view

    assert Qt.Key_Escape not in emulator_view._SINGLE_KEY_MAP
    assert Qt.Key_Escape not in emulator_view._CHORD_KEY_MAP
