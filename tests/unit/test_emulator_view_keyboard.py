import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt5.QtCore import QEvent, Qt  # noqa: E402
from PyQt5.QtGui import QKeyEvent  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from zxemu_ui.emulator_view import EmulatorView  # noqa: E402
from zxemu_core.keyboard import Keyboard  # noqa: E402


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


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def _key_event(kind, qt_key: int) -> QKeyEvent:
    return QKeyEvent(kind, qt_key, Qt.NoModifier)


def test_letter_key_press_reaches_keyboard_matrix(qapp):
    machine = FakeMachine()
    view = EmulatorView(machine)
    view.keyPressEvent(_key_event(QEvent.KeyPress, Qt.Key_H))
    assert machine.keyboard.read(0xBFFE) == 0b01111  # row6=ENTER,L,K,J,H; H is bit4


def test_key_release_restores_matrix(qapp):
    machine = FakeMachine()
    view = EmulatorView(machine)
    view.keyPressEvent(_key_event(QEvent.KeyPress, Qt.Key_H))
    view.keyReleaseEvent(_key_event(QEvent.KeyRelease, Qt.Key_H))
    assert machine.keyboard.read(0xBFFE) == 0x1F


def test_enter_key_maps_to_enter():
    kb = Keyboard()
    machine = FakeMachine()
    machine.keyboard = kb
    view = EmulatorView(machine)
    view.keyPressEvent(_key_event(QEvent.KeyPress, Qt.Key_Return))
    assert kb.read(0xBFFE) == 0b11110  # ENTER is bit0 of row6


def test_quote_chord_presses_both_sym_shift_and_p():
    machine = FakeMachine()
    view = EmulatorView(machine)
    view.keyPressEvent(_key_event(QEvent.KeyPress, Qt.Key_QuoteDbl))
    # SYM SHIFT: row7 bit1; P: row5 bit0
    assert machine.keyboard.read(0x7FFE) == 0b11101
    assert machine.keyboard.read(0xDFFE) == 0b11110


def test_quote_chord_release_releases_both():
    machine = FakeMachine()
    view = EmulatorView(machine)
    view.keyPressEvent(_key_event(QEvent.KeyPress, Qt.Key_QuoteDbl))
    view.keyReleaseEvent(_key_event(QEvent.KeyRelease, Qt.Key_QuoteDbl))
    assert machine.keyboard.read(0x7FFE) == 0x1F
    assert machine.keyboard.read(0xDFFE) == 0x1F


def test_unmapped_key_is_a_no_op():
    machine = FakeMachine()
    view = EmulatorView(machine)
    view.keyPressEvent(_key_event(QEvent.KeyPress, Qt.Key_F12))
    for port in (0xFEFE, 0xFDFE, 0xFBFE, 0xF7FE, 0xEFFE, 0xDFFE, 0xBFFE, 0x7FFE):
        assert machine.keyboard.read(port) == 0x1F


def test_autorepeat_press_is_ignored():
    machine = FakeMachine()
    view = EmulatorView(machine)
    event = QKeyEvent(QEvent.KeyPress, Qt.Key_H, Qt.NoModifier, "", True)  # autorep=True
    view.keyPressEvent(event)
    assert machine.keyboard.read(0xBFFE) == 0x1F  # never registered as a press


def _is_pressed(kb: Keyboard, key: str) -> bool:
    from zxemu_core.keyboard import _KEY_TO_POSITION

    row, bit = _KEY_TO_POSITION[key]
    return not (kb.row_state[row] & (1 << bit))


# --- editing keys (CAPS SHIFT + digit chords) --------------------------------

def test_backspace_maps_to_caps_shift_plus_0_delete():
    machine = FakeMachine()
    view = EmulatorView(machine)
    view.keyPressEvent(_key_event(QEvent.KeyPress, Qt.Key_Backspace))
    assert _is_pressed(machine.keyboard, "CAPS SHIFT")
    assert _is_pressed(machine.keyboard, "0")


def test_arrow_keys_map_to_caps_shift_cursor_chords():
    machine = FakeMachine()
    view = EmulatorView(machine)
    for qt_key, digit in (
        (Qt.Key_Left, "5"),
        (Qt.Key_Down, "6"),
        (Qt.Key_Up, "7"),
        (Qt.Key_Right, "8"),
    ):
        view.keyPressEvent(_key_event(QEvent.KeyPress, qt_key))
        assert _is_pressed(machine.keyboard, "CAPS SHIFT")
        assert _is_pressed(machine.keyboard, digit)
        view.keyReleaseEvent(_key_event(QEvent.KeyRelease, qt_key))
        assert machine.keyboard.row_state == [0x1F] * 8


# --- punctuation chords ------------------------------------------------------

def test_comma_maps_to_sym_shift_n():
    machine = FakeMachine()
    view = EmulatorView(machine)
    view.keyPressEvent(_key_event(QEvent.KeyPress, Qt.Key_Comma))
    assert _is_pressed(machine.keyboard, "SYM SHIFT")
    assert _is_pressed(machine.keyboard, "N")


def test_plus_maps_to_sym_shift_k():
    machine = FakeMachine()
    view = EmulatorView(machine)
    view.keyPressEvent(_key_event(QEvent.KeyPress, Qt.Key_Plus))
    assert _is_pressed(machine.keyboard, "SYM SHIFT")
    assert _is_pressed(machine.keyboard, "K")


# --- physical-Shift contamination fix ----------------------------------------

def test_shift_plus_symbol_does_not_leak_caps_shift():
    # PC Shift+1 -> the OS sends a Shift key event AND a "!" (Key_Exclam) event.
    # The result must be exactly SYM SHIFT + 1, NOT CAPS SHIFT + SYM SHIFT + 1
    # (which would be the Spectrum's extended mode).
    machine = FakeMachine()
    view = EmulatorView(machine)
    view.keyPressEvent(_key_event(QEvent.KeyPress, Qt.Key_Shift))
    view.keyPressEvent(_key_event(QEvent.KeyPress, Qt.Key_Exclam))
    assert _is_pressed(machine.keyboard, "SYM SHIFT")
    assert _is_pressed(machine.keyboard, "1")
    assert not _is_pressed(machine.keyboard, "CAPS SHIFT")


def test_shift_plus_letter_still_gives_caps_shift_for_capitals():
    # Shift+A must remain CAPS SHIFT + A (capital letter), unaffected by the fix.
    machine = FakeMachine()
    view = EmulatorView(machine)
    view.keyPressEvent(_key_event(QEvent.KeyPress, Qt.Key_Shift))
    view.keyPressEvent(_key_event(QEvent.KeyPress, Qt.Key_A))
    assert _is_pressed(machine.keyboard, "CAPS SHIFT")
    assert _is_pressed(machine.keyboard, "A")


def test_releasing_one_of_several_held_keys_leaves_the_rest_pressed():
    machine = FakeMachine()
    view = EmulatorView(machine)
    view.keyPressEvent(_key_event(QEvent.KeyPress, Qt.Key_A))
    view.keyPressEvent(_key_event(QEvent.KeyPress, Qt.Key_B))
    view.keyReleaseEvent(_key_event(QEvent.KeyRelease, Qt.Key_A))
    assert not _is_pressed(machine.keyboard, "A")
    assert _is_pressed(machine.keyboard, "B")


def _scan_event(kind, qt_key: int, scan_code: int) -> QKeyEvent:
    # Full constructor lets us set a native scan code, as real hardware events carry.
    return QKeyEvent(kind, qt_key, Qt.NoModifier, scan_code, 0, 0)


def test_shifted_symbol_release_reports_unshifted_key_but_still_releases():
    # Reproduces the stuck-" bug: the ' physical key reports Qt.Key_QuoteDbl on
    # press (Shift held) but Qt.Key_Apostrophe on release (Shift already up).
    # Same physical scan code, so it must still release cleanly.
    machine = FakeMachine()
    view = EmulatorView(machine)
    scan = 40  # arbitrary but consistent physical scan code for the ' key

    view.keyPressEvent(_scan_event(QEvent.KeyPress, Qt.Key_QuoteDbl, scan))
    assert _is_pressed(machine.keyboard, "SYM SHIFT")
    assert _is_pressed(machine.keyboard, "P")

    view.keyReleaseEvent(_scan_event(QEvent.KeyRelease, Qt.Key_Apostrophe, scan))
    assert machine.keyboard.row_state == [0x1F] * 8  # fully released, nothing stuck
