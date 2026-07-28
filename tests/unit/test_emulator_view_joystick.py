"""Arrow keys and Ctrl driving a fitted Kempston Joystick.

The load-bearing claim here is that the keys are *taken away* from the Spectrum keyboard
while an interface is fitted. Feeding both would mean a game reading the arrows as CAPS
SHIFT + 5/6/7/8 and the joystick port at once, seeing every nudge twice.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt5.QtCore import QEvent, Qt  # noqa: E402
from PyQt5.QtGui import QFocusEvent, QKeyEvent  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from zxemu_core.joystick import FIRE, LEFT, RIGHT, UP, KempstonJoystick  # noqa: E402
from zxemu_core.keyboard import Keyboard  # noqa: E402
from zxemu_core.mouse import KempstonMouse  # noqa: E402
from zxemu_ui.panels.emulator_view import EmulatorView  # noqa: E402


class FakeMemory:
    def read_byte(self, address: int) -> int:
        return 0


class FakeUla:
    border_color = 0


class FakeMachine:
    def __init__(self):
        self.memory = FakeMemory()
        self.ula = FakeUla()
        self.keyboard = Keyboard()
        self.mouse = KempstonMouse()
        self.joystick = KempstonJoystick()


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def fitted(qapp):
    machine = FakeMachine()
    machine.joystick.enabled = True
    return machine, EmulatorView(machine)


def _press(view, key) -> None:
    view.keyPressEvent(QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier))


def _release(view, key) -> None:
    view.keyReleaseEvent(QKeyEvent(QEvent.KeyRelease, key, Qt.NoModifier))


def test_arrows_move_the_stick(fitted):
    machine, view = fitted
    _press(view, Qt.Key_Up)
    assert machine.joystick.read_port(0x1F) == UP
    _release(view, Qt.Key_Up)
    assert machine.joystick.read_port(0x1F) == 0x00


def test_ctrl_is_fire(fitted):
    """Chosen because the Spectrum has no Ctrl key, so nothing is displaced by it."""
    machine, view = fitted
    _press(view, Qt.Key_Control)
    assert machine.joystick.read_port(0x1F) == FIRE


def test_a_diagonal_with_fire_is_one_byte(fitted):
    machine, view = fitted
    _press(view, Qt.Key_Left)
    _press(view, Qt.Key_Up)
    _press(view, Qt.Key_Control)
    assert machine.joystick.read_port(0x1F) == LEFT | UP | FIRE


def test_the_keys_stop_reaching_the_spectrum_keyboard(fitted):
    """One stick, one meaning: the arrows must not also arrive as CAPS SHIFT + 5/6/7/8."""
    machine, view = fitted
    _press(view, Qt.Key_Left)
    assert view._held_keys == {}
    # The two halves of "left" on a Spectrum: CAPS SHIFT (row 0xFE) and 5 (row 0xF7).
    # 0x1F is "no key in this row held".
    assert machine.keyboard.read(0xFEFE) == 0x1F
    assert machine.keyboard.read(0xF7FE) == 0x1F


def test_with_no_interface_fitted_the_arrows_are_the_keyboards_again(qapp):
    machine = FakeMachine()  # joystick left unfitted
    view = EmulatorView(machine)

    _press(view, Qt.Key_Left)

    assert view._held_keys != {}
    assert machine.joystick.read_port(0x1F) == 0x00


def test_other_keys_are_untouched_while_fitted(fitted):
    machine, view = fitted
    _press(view, Qt.Key_A)
    assert view._held_keys != {}
    assert machine.joystick.read_port(0x1F) == 0x00


def test_losing_focus_centres_the_stick(fitted):
    """A direction held when focus leaves never gets its key-up, so the game would keep
    walking into the wall until the user noticed and pressed that arrow again."""
    machine, view = fitted
    _press(view, Qt.Key_Right)
    _press(view, Qt.Key_Control)

    view.focusOutEvent(QFocusEvent(QEvent.FocusOut))

    assert machine.joystick.read_port(0x1F) == 0x00


def test_escape_still_belongs_to_fullscreen_while_a_stick_is_fitted(fitted):
    """The joystick claims the arrows and Ctrl, nothing else -- Esc must still be
    declined so the fullscreen window above can close on it."""
    machine, view = fitted
    event = QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)

    view.keyPressEvent(event)

    assert not event.isAccepted()
    assert machine.joystick.read_port(0x1F) == 0x00


def test_holding_right_then_left_gives_both_as_hardware_would(fitted):
    """Two switches closed at once is a physically possible (if useless) stick position,
    and the interface reports it rather than second-guessing the player."""
    machine, view = fitted
    _press(view, Qt.Key_Right)
    _press(view, Qt.Key_Left)
    assert machine.joystick.read_port(0x1F) == RIGHT | LEFT
