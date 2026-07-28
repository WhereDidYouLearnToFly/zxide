"""Unit tests for the Kempston Joystick interface.

Two things about this device are the opposite of everything around it, and both are easy
to get backwards in a way nothing reports: the switches are **active high** (1 = pressed,
idle 0x00, where the keyboard and the mouse are active low), and an *absent* interface
therefore reads as every direction held at once rather than as nothing. Each has a test.
"""

from zxemu_core.joystick import BUTTON_A, DOWN, FIRE, FIRE2, LEFT, RIGHT, START, UP, KempstonJoystick


def _fitted() -> KempstonJoystick:
    joystick = KempstonJoystick()
    joystick.enabled = True
    return joystick


def test_unfitted_by_default():
    assert not KempstonJoystick().enabled


def test_an_idle_stick_reads_zero_not_ff():
    """Active high: nothing pressed is no bits set. Reading 0xFF here would look to a game
    exactly like up+down+left+right+fire, which is what an *unfitted* port gives it."""
    assert _fitted().read_port(0x1F) == 0x00


def test_each_switch_owns_its_documented_bit():
    joystick = _fitted()
    for switch, bit in ((RIGHT, 0x01), (LEFT, 0x02), (DOWN, 0x04), (UP, 0x08), (FIRE, 0x10)):
        joystick.set_switch(switch, True)
        assert joystick.read_port(0x1F) == bit
        joystick.set_switch(switch, False)
        assert joystick.read_port(0x1F) == 0x00


def test_switches_combine():
    joystick = _fitted()
    joystick.set_switch(UP, True)
    joystick.set_switch(FIRE, True)
    assert joystick.read_port(0x1F) == 0x18


def test_releasing_one_switch_leaves_the_others_held():
    joystick = _fitted()
    joystick.set_switch(LEFT, True)
    joystick.set_switch(FIRE, True)
    joystick.set_switch(LEFT, False)
    assert joystick.read_port(0x1F) == FIRE


def test_releasing_everything_centres_the_stick():
    """For when the host stops delivering events -- otherwise a direction held at the
    moment focus was lost never gets its key-up and the game walks into a wall forever."""
    joystick = _fitted()
    joystick.set_switch(RIGHT, True)
    joystick.set_switch(FIRE, True)
    joystick.release_all()
    assert joystick.read_port(0x1F) == 0x00


def test_an_unfitted_interface_reads_nothing_even_from_its_own_port():
    joystick = KempstonJoystick()
    joystick.set_switch(FIRE, True)  # state can be set; it just isn't reachable
    assert joystick.read_port(0x1F) == 0x00


# --- the two modes, and what each lets through ------------------------------------
#
# The Next's Kempston and MD 3-button modes differ in exactly one thing: whether bits 7:6
# reach the port or are forced to 0 (zxnext.vhd:3478-3479). These pin that down, because
# "8-bit Kempston" is otherwise easy to implement as "all eight bits, always" -- which
# would hand A and START to software that has never heard of them.

def test_kempston_mode_masks_off_a_and_start():
    joystick = _fitted()
    joystick.set_switch(BUTTON_A, True)
    joystick.set_switch(START, True)
    assert joystick.read_port(0x1F) == 0x00


def test_kempston_mode_still_passes_the_second_fire():
    """Bit 5 is in the low lane, so C works without the extended mode -- the part of the
    Next's layout that surprises people."""
    joystick = _fitted()
    joystick.set_switch(FIRE2, True)
    assert joystick.read_port(0x1F) == FIRE2


def test_extended_mode_passes_the_whole_byte():
    joystick = _fitted()
    joystick.extended = True
    for switch in (RIGHT, LEFT, DOWN, UP, FIRE, FIRE2, BUTTON_A, START):
        joystick.set_switch(switch, True)
    assert joystick.read_port(0x1F) == 0xFF


def test_the_mode_masks_the_port_not_the_switches():
    """A pad's extra buttons close whether or not the interface passes them on, so
    switching modes must reveal what was already held rather than need it pressed again."""
    joystick = _fitted()
    joystick.set_switch(START, True)
    assert joystick.read_port(0x1F) == 0x00

    joystick.extended = True
    assert joystick.read_port(0x1F) == START


def test_kempston_mode_is_the_default():
    """Software written for a one-button stick can read bits 6-7 as something else
    entirely, so the wider mode is opt-in."""
    assert not KempstonJoystick().extended


def test_an_original_five_switch_stick_reads_the_same_in_either_mode():
    """Why no third mode is needed for 1980s hardware: it simply never closes the upper
    switches, so it looks like an extended interface with those buttons unpressed."""
    for extended in (False, True):
        joystick = _fitted()
        joystick.extended = extended
        joystick.set_switch(UP, True)
        joystick.set_switch(FIRE, True)
        assert joystick.read_port(0x1F) == 0x18


# --- address decoding ------------------------------------------------------------

def test_handles_every_port_with_a5_a6_and_a7_clear():
    """0x1F is what the manuals quote, but only three lines are wired, so the whole
    0x00-0x1F low-byte range answers at any high byte."""
    assert KempstonJoystick.handles(0x001F)
    assert KempstonJoystick.handles(0x0000)
    assert KempstonJoystick.handles(0xFF1F)  # high byte ignored entirely


def test_handles_nothing_the_machine_needs_for_itself():
    assert not KempstonJoystick.handles(0x00FE)  # ULA
    assert not KempstonJoystick.handles(0xFFFD)  # AY register select
    assert not KempstonJoystick.handles(0x7FFD)  # 128K paging latch
    assert not KempstonJoystick.handles(0x005F)  # Beta 128 sector register: A6 set


def test_it_collides_with_the_mouse_which_is_why_they_are_exclusive():
    """Not a quirk of this implementation -- both interfaces answer 0x1F on real
    hardware, and the UI refuses to fit both because of it (see test_menu_bar)."""
    from zxemu_core.mouse import KempstonMouse

    assert KempstonJoystick.handles(0x001F) and KempstonMouse.handles(0x001F)
