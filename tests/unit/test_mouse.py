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


def test_releasing_everything_clears_a_button_the_host_stopped_tracking():
    """The escape hatch for a UI that loses the pointer mid-click: without it the bit
    stays low forever, because the release event never reaches whoever set it."""
    m = KempstonMouse()
    m.enabled = True
    m.set_button(BUTTON_LEFT, True)
    m.set_button(BUTTON_RIGHT, True)
    m.release_all_buttons()
    assert m.read_port(0xFADF) == 0xFF


def test_unhandled_port_reads_ff_even_when_enabled():
    m = KempstonMouse()
    m.enabled = True
    assert m.read_port(0x1234) == 0xFF  # A0 clear: the ULA's half of the bus, never ours


# --- address decoding ------------------------------------------------------------
#
# The interface reads four address lines and ignores twelve, so each register answers to
# a whole family of ports rather than the one address the manuals quote. Software that
# arrives with different high bits set is the reason this matters: on real hardware it
# reaches the mouse, and an emulator matching only 0xFADF/0xFBDF/0xFFDF leaves it talking
# to nothing.

def test_the_quoted_addresses_select_the_registers_they_are_quoted_for():
    m = KempstonMouse()
    m.enabled = True
    m.move_by(dx=1, dy=-2)
    m.set_button(BUTTON_LEFT, True)
    assert m.read_port(0xFBDF) == 1
    assert m.read_port(0xFFDF) == 2
    assert m.read_port(0xFADF) == 0b11111101


def test_aliased_addresses_reach_the_same_registers():
    """Same four lines, different ignored ones: 0x0ADF/0x01DF/0x05DF are the quoted
    ports with their don't-care bits low, and the hardware cannot tell them apart."""
    m = KempstonMouse()
    m.enabled = True
    m.move_by(dx=1, dy=-2)
    m.set_button(BUTTON_LEFT, True)
    assert m.read_port(0x01DF) == 1          # A8 = 1, A10 = 0: X
    assert m.read_port(0x05DF) == 2          # A8 = 1, A10 = 1: Y
    assert m.read_port(0x0ADF) == 0b11111101  # A8 = 0: buttons


def test_handles_every_port_with_a0_set_and_a5_clear():
    """Including 0x1F, the Kempston joystick's port -- the two devices really do
    collide on real hardware, which is why the mouse stays unfitted by default."""
    assert KempstonMouse.handles(0xFADF)
    assert KempstonMouse.handles(0xFBDF)
    assert KempstonMouse.handles(0xFFDF)
    assert KempstonMouse.handles(0x001F)


def test_handles_nothing_the_machine_needs_for_itself():
    assert not KempstonMouse.handles(0x00FE)  # ULA: A0 clear
    assert not KempstonMouse.handles(0xFFFD)  # AY register select: A5 set
    assert not KempstonMouse.handles(0xBFFD)  # AY data write: A5 set
    assert not KempstonMouse.handles(0x7FFD)  # 128K paging latch: A5 set
    assert not KempstonMouse.handles(0x00FF)  # floating-bus read: A5 set
