import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt5.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PyQt5.QtGui import QFocusEvent, QMouseEvent  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

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


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def _press(button, pos=QPointF(10, 10)) -> QMouseEvent:
    return QMouseEvent(QEvent.MouseButtonPress, pos, pos, button, button, Qt.NoModifier)


def _release(button, pos=QPointF(10, 10)) -> QMouseEvent:
    return QMouseEvent(QEvent.MouseButtonRelease, pos, pos, button, Qt.NoButton, Qt.NoModifier)


def _move(pos: QPointF) -> QMouseEvent:
    return QMouseEvent(QEvent.MouseMove, pos, pos, Qt.NoButton, Qt.NoButton, Qt.NoModifier)


def test_disabled_mouse_never_captures(qapp):
    machine = FakeMachine()
    view = EmulatorView(machine)
    view.mousePressEvent(_press(Qt.LeftButton))
    assert not view._mouse_captured
    assert machine.mouse.read_port(0xFADF) == 0xFF  # left button never registered


def test_first_click_captures_without_registering_a_button(qapp):
    machine = FakeMachine()
    machine.mouse.enabled = True
    view = EmulatorView(machine)

    view.mousePressEvent(_press(Qt.LeftButton))

    assert view._mouse_captured
    assert machine.mouse.read_port(0xFADF) == 0xFF  # the capturing click itself doesn't count


def test_click_while_captured_presses_the_mapped_button(qapp):
    machine = FakeMachine()
    machine.mouse.enabled = True
    view = EmulatorView(machine)
    view.mousePressEvent(_press(Qt.LeftButton))  # capture

    view.mousePressEvent(_press(Qt.RightButton))

    assert machine.mouse.read_port(0xFADF) == 0b11111110  # bit0 (right) clear


def test_release_while_captured_restores_the_button(qapp):
    machine = FakeMachine()
    machine.mouse.enabled = True
    view = EmulatorView(machine)
    view.mousePressEvent(_press(Qt.LeftButton))  # capture
    view.mousePressEvent(_press(Qt.RightButton))

    view.mouseReleaseEvent(_release(Qt.RightButton))

    assert machine.mouse.read_port(0xFADF) == 0xFF


def test_move_while_captured_feeds_the_mouse_and_recentres(qapp, monkeypatch):
    from PyQt5.QtCore import QPoint
    from PyQt5.QtGui import QCursor

    machine = FakeMachine()
    machine.mouse.enabled = True
    view = EmulatorView(machine)
    view.mousePressEvent(_press(Qt.LeftButton))  # capture

    center = QPoint(50, 40)
    monkeypatch.setattr(view, "mapToGlobal", lambda p: center)  # widget center -> fixed screen point
    recentred = []
    monkeypatch.setattr(QCursor, "setPos", staticmethod(lambda p: recentred.append(p)))

    view.mouseMoveEvent(_move(QPointF(56, 33)))  # global (56,33) vs centre (50,40): dx=+6, dy=-7

    assert machine.mouse.read_port(0xFBDF) == 6
    assert machine.mouse.read_port(0xFFDF) == 7
    assert recentred == [center]  # cursor was snapped back to the centre


def test_escape_releases_capture(qapp):
    machine = FakeMachine()
    machine.mouse.enabled = True
    view = EmulatorView(machine)
    view.mousePressEvent(_press(Qt.LeftButton))  # capture
    assert view._mouse_captured

    from PyQt5.QtGui import QKeyEvent
    view.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))

    assert not view._mouse_captured


def test_losing_focus_releases_capture(qapp):
    machine = FakeMachine()
    machine.mouse.enabled = True
    view = EmulatorView(machine)
    view.mousePressEvent(_press(Qt.LeftButton))  # capture
    assert view._mouse_captured

    view.focusOutEvent(QFocusEvent(QEvent.FocusOut))

    assert not view._mouse_captured


def test_release_mouse_capture_is_a_no_op_when_not_captured(qapp):
    machine = FakeMachine()
    view = EmulatorView(machine)
    view.release_mouse_capture()  # must not raise
    assert not view._mouse_captured
