from zxemu_core.mouse import BUTTON_LEFT, BUTTON_MIDDLE, BUTTON_RIGHT, KempstonMouse


def test_disabled_by_default_and_silent():
    m = KempstonMouse()
    assert not m.enabled
    assert m.read_port(0xFBDF) == 0xFF
    assert m.read_port(0xFFDF) == 0xFF
    assert m.read_port(0xFADF) == 0xFF


def test_moving_right_and_up_increments_counters():
    m = KempstonMouse()
    m.enabled = True
    m.move_by(dx=5, dy=-3)  # right 5, up 3 (screen coords: -y is up)
    assert m.read_port(0xFBDF) == 5
    assert m.read_port(0xFFDF) == 3


def test_moving_left_and_down_wraps_counters_downward():
    m = KempstonMouse()
    m.enabled = True
    m.move_by(dx=-1, dy=1)  # left 1, down 1
    assert m.read_port(0xFBDF) == 0xFF
    assert m.read_port(0xFFDF) == 0xFF


def test_counters_wrap_on_overflow():
    m = KempstonMouse()
    m.enabled = True
    m.move_by(dx=200, dy=0)
    m.move_by(dx=200, dy=0)
    assert m.read_port(0xFBDF) == (400 & 0xFF)


def test_buttons_idle_read_all_ones():
    m = KempstonMouse()
    m.enabled = True
    assert m.read_port(0xFADF) == 0xFF


def test_pressing_right_button_clears_bit0():
    m = KempstonMouse()
    m.enabled = True
    m.set_button(BUTTON_RIGHT, True)
    assert m.read_port(0xFADF) == 0b11111110


def test_pressing_left_and_middle_clears_bits_1_and_2():
    m = KempstonMouse()
    m.enabled = True
    m.set_button(BUTTON_LEFT, True)
    m.set_button(BUTTON_MIDDLE, True)
    assert m.read_port(0xFADF) == 0b11111001


def test_releasing_a_button_restores_its_bit():
    m = KempstonMouse()
    m.enabled = True
    m.set_button(BUTTON_LEFT, True)
    m.set_button(BUTTON_LEFT, False)
    assert m.read_port(0xFADF) == 0xFF


def test_unhandled_port_reads_ff_even_when_enabled():
    m = KempstonMouse()
    m.enabled = True
    assert m.read_port(0x1234) == 0xFF


def test_handles_only_the_three_mouse_ports():
    assert KempstonMouse.handles(0xFADF)
    assert KempstonMouse.handles(0xFBDF)
    assert KempstonMouse.handles(0xFFDF)
    assert not KempstonMouse.handles(0xFE)
    assert not KempstonMouse.handles(0x7FFD)
