"""Translating a gamepad poll into Kempston switches.

``switches_from`` is a plain function of plain numbers precisely so this can be tested with
no pad plugged in -- everything below it in ``gamepad.py`` is SDL, and SDL cannot be
asserted about on a build machine. The values here are the ones the reference device
actually produced (a "usb gamepad" NES clone: two axes, no hat, resting at -0.01).
"""

import pytest

from zxemu_core.joystick import BUTTON_A, DOWN, FIRE, FIRE2, LEFT, RIGHT, START, UP, KempstonJoystick
from zxemu_ui.gamepad import DEADZONE, GamepadSource, switches_from


def test_a_resting_stick_is_no_switches():
    """-0.01 rather than 0.0: these axes do not centre exactly, which is what the
    deadzone is for. A tighter one would have the pad walking left on its own."""
    assert switches_from(-0.01, -0.01, [], []) == 0


@pytest.mark.parametrize("x, y, expected", [
    (-1.0, -0.01, LEFT),
    (1.0, -0.01, RIGHT),
    (-0.01, -1.0, UP),      # axis Y is negative upward, as on a screen
    (-0.01, 1.0, DOWN),
    (-1.0, -1.0, LEFT | UP),
    (1.0, 1.0, RIGHT | DOWN),
])
def test_each_axis_direction_maps_to_its_switch(x, y, expected):
    assert switches_from(x, y, [], []) == expected


def test_the_first_two_buttons_are_the_two_fires():
    """SDL reports buttons only by index, so the pair a NES-style pad puts under your
    thumb become B and C -- the two fire buttons of the extended port."""
    assert switches_from(-0.01, -0.01, [], [0]) == FIRE
    assert switches_from(-0.01, -0.01, [], [1]) == FIRE2
    assert switches_from(-0.01, -0.01, [], [0, 1]) == FIRE | FIRE2


def test_select_and_start_become_a_and_start():
    """Indices 8 and 9 on the reference pad. They reach software only in extended mode --
    ``switches_from`` reports them regardless, and the port does the masking."""
    assert switches_from(-0.01, -0.01, [], [8]) == BUTTON_A
    assert switches_from(-0.01, -0.01, [], [9]) == START


def test_an_unrecognised_button_still_fires():
    """An unfamiliar pad must never be mute: whatever it reports does the one thing every
    Kempston game actually asks for."""
    assert switches_from(-0.01, -0.01, [], [4]) == FIRE
    assert switches_from(-0.01, -0.01, [], [7]) == FIRE


def test_a_hat_works_too_and_its_y_is_the_other_way_up():
    """Pads disagree about whether a d-pad is axes or a hat; SDL hats are digital and
    report +1 as *up*, the opposite sign from an axis. Getting that wrong inverts the
    controls on every pad that uses one."""
    assert switches_from(0.0, 0.0, [(0, 1)], []) == UP
    assert switches_from(0.0, 0.0, [(0, -1)], []) == DOWN
    assert switches_from(0.0, 0.0, [(-1, 0)], []) == LEFT
    assert switches_from(0.0, 0.0, [(1, 0)], []) == RIGHT


def test_a_push_short_of_the_deadzone_is_ignored():
    almost = DEADZONE - 0.01
    assert switches_from(almost, almost, [], []) == 0


def test_axes_and_a_hat_and_a_button_combine():
    assert switches_from(-1.0, -0.01, [(0, 1)], [0]) == LEFT | UP | FIRE


# --- the source object itself ----------------------------------------------------

def test_a_source_with_no_pad_is_silent_rather_than_broken():
    """Every way this can come up empty -- pygame absent, SDL unusable, nothing plugged
    in -- has to be an ordinary state. The user never asked for a pad; the keyboard plays
    the game either way, so there is nothing here worth raising or reporting."""
    source = GamepadSource()
    source._pygame = None  # as if pygame were not installed

    assert source.open() is None
    assert source.device_name is None
    assert source.poll() == 0


# --- the two input sources, merged ------------------------------------------------

def test_the_keyboard_and_the_pad_do_not_cancel_each_other():
    """The reason the joystick keeps two masks. The keyboard arrives as edges and the pad
    as a whole-state poll fifty times a second, so a single shared field would have each
    poll wipe whatever key the user was holding down."""
    joystick = KempstonJoystick()
    joystick.enabled = True

    joystick.set_switch(FIRE, True)      # finger on Ctrl
    joystick.set_pad_switches(LEFT)      # and the pad pushed left
    assert joystick.read_port(0x1F) == FIRE | LEFT

    joystick.set_pad_switches(0)         # pad centred; Ctrl is still held
    assert joystick.read_port(0x1F) == FIRE


def test_releasing_everything_clears_both_sources():
    joystick = KempstonJoystick()
    joystick.enabled = True
    joystick.set_switch(UP, True)
    joystick.set_pad_switches(RIGHT | FIRE)

    joystick.release_all()

    assert joystick.read_port(0x1F) == 0x00
