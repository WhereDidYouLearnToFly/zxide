"""Gamepad input for the Kempston Joystick, via SDL2 (pygame).

**Why pygame.** A USB pad is the natural way to play a Spectrum game, and reaching one is
harder than it looks: PyQt5 ships no ``QtGamepad``, and Windows' own XInput -- the route
that would need no dependency at all -- speaks only the Xbox protocol, so it cannot see the
plain-HID pads that the cheap USB NES/SNES clones are. SDL2 handles all of them, and pygame
is the ordinary way to reach SDL2 from Python. It is a declared dependency (see
``pyproject.toml``), so it ships with zxide.

**Every failure here is still survivable, deliberately.** The import is attempted rather
than assumed, and every SDL call is guarded. A declared dependency can still be missing
from a hand-assembled environment, SDL can fail to start on a machine with no usable
backend, and -- much the most likely -- there may simply be no pad plugged in. None of
those is worth an error dialog or a traceback: the arrow keys play every game, so the whole
module degrades to "returns no switches" and says nothing.

**Digital sticks arriving as analogue axes.** A d-pad has no middle positions, but HID
descriptors routinely report one as a pair of axes, so the values come through as roughly
-1, 0 or +1 rather than as buttons. Hence a deadzone: anything nearer the centre than
``DEADZONE`` is "not pushed". It is set loose (half travel) because these axes do not sit
at exactly zero when idle -- the pad this was written against rests at -0.01 -- and because
there is nothing in between to be precise about.

**Buttons, and why the mapping looks the way it does.** The extended (Next / MD 3-button)
port has four: B, C, A and START. SDL reports a pad's buttons only by index, and indices are
whatever the device's HID descriptor says -- the reference pad claims ten of which only 0, 1,
8 and 9 physically exist. So the first two indices become the two fire buttons, the pair that
NES-style pads put under your thumb, and 8/9 become A and START, which is where such pads put
Select and Start. **Any unrecognised index also fires**, so an unfamiliar pad is never mute:
its buttons all do the one thing every Kempston game asks for.

Only B (bit 4) matters to ordinary software. C, A and START reach a program at all only when
the joystick is in extended mode -- see ``zxemu_core/joystick.py``.
"""

from __future__ import annotations

import os

from zxemu_core.joystick import BUTTON_A, DOWN, FIRE, FIRE2, LEFT, RIGHT, START, UP

#: SDL button index -> switch. Anything not named here falls back to ``FIRE``.
BUTTON_MAP = {0: FIRE, 1: FIRE2, 8: BUTTON_A, 9: START}

#: How far an axis must travel from centre before it counts as pushed.
DEADZONE = 0.5


def switches_from(x: float, y: float, hats, buttons) -> int:
    """Translate one poll of a pad into a Kempston switch mask.

    ``buttons`` is the indices currently held. Kept a plain function of plain values so the
    mapping can be tested without a device plugged in, which is the only way this stays
    honest -- everything below it is SDL.

    Both axes *and* hats are consulted because pads disagree about which a d-pad is: the
    reference NES clone reports axes and no hat, plenty of others do the opposite, and
    a pad offering both costs nothing to accept from either.
    """
    switches = 0
    if x <= -DEADZONE:
        switches |= LEFT
    elif x >= DEADZONE:
        switches |= RIGHT
    if y <= -DEADZONE:
        switches |= UP
    elif y >= DEADZONE:
        switches |= DOWN
    for hat_x, hat_y in hats:
        # SDL hats are already digital, and their Y is the opposite way up from an axis:
        # +1 is up, where +1 on an axis is down.
        switches |= LEFT if hat_x < 0 else RIGHT if hat_x > 0 else 0
        switches |= DOWN if hat_y < 0 else UP if hat_y > 0 else 0
    for index in buttons:
        switches |= BUTTON_MAP.get(index, FIRE)
    return switches


class GamepadSource:
    """The first connected pad, polled once per frame, or nothing at all.

    "Nothing at all" is a first-class state, not an error: pygame may be absent, no pad may
    be plugged in, or SDL may fail to start. Each of those simply leaves ``device_name``
    None and ``poll`` returning 0, because a missing pad is not a problem to report -- the
    keyboard is right there, and the user never asked for a pad in the first place.
    """

    def __init__(self) -> None:
        self._pygame = _import_pygame()
        self._joystick = None
        self._started = False

    @property
    def device_name(self) -> str | None:
        """The open pad's name, or None when there is nothing to read."""
        return self._joystick.get_name() if self._joystick is not None else None

    def open(self) -> str | None:
        """Start SDL if needed and open the first pad. Returns its name, or None.

        Called when a joystick interface is fitted rather than at startup, so a user who
        never touches the feature never pays for SDL initialising or a device being opened.
        """
        if self._pygame is None:
            return None
        if not self._started:
            # The joystick subsystem alone is not enough: pygame refuses to pump its event
            # queue -- which is what refreshes joystick state -- without a video system. The
            # dummy driver satisfies that without creating a window, which matters because
            # the window here belongs to Qt and SDL must not open one of its own.
            os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
            try:
                self._pygame.display.init()
                self._pygame.joystick.init()
            except Exception:
                # A machine with no usable SDL video/joystick backend at all. Not worth
                # reporting: the keyboard still plays the game.
                self._pygame = None
                return None
            self._started = True
        return self._open_first_device()

    def close(self) -> None:
        """Let go of the pad (but leave SDL up, in case the interface is fitted again)."""
        self._joystick = None

    def poll(self) -> int:
        """The switch mask the pad is holding right now, or 0 if there is no pad."""
        if self._joystick is None:
            return 0
        try:
            # Drain rather than merely pump. Both refresh the cached device state, but
            # pumping alone leaves every joystick event sitting in SDL's queue -- nothing
            # else in this application ever reads it -- and a queue nobody empties fills
            # up and stops accepting the updates this depends on.
            self._pygame.event.get()
            axes = self._joystick.get_numaxes()
            x = self._joystick.get_axis(0) if axes > 0 else 0.0
            y = self._joystick.get_axis(1) if axes > 1 else 0.0
            hats = [self._joystick.get_hat(h) for h in range(self._joystick.get_numhats())]
            held = [b for b in range(self._joystick.get_numbuttons()) if self._joystick.get_button(b)]
        except Exception:
            # Unplugged mid-game. Drop it and report a centred stick, so whatever was held
            # at the moment it vanished does not stay held for the rest of the session.
            self._joystick = None
            return 0
        return switches_from(x, y, hats, held)

    def _open_first_device(self) -> str | None:
        try:
            if self._pygame.joystick.get_count() == 0:
                self._joystick = None
                return None
            self._joystick = self._pygame.joystick.Joystick(0)
            self._joystick.init()
            return self._joystick.get_name()
        except Exception:
            self._joystick = None
            return None


def _import_pygame():
    """pygame if it is installed, else None -- and quietly either way.

    The environment variable is not decoration: importing pygame prints a version banner
    and a greeting to stdout, which has no business appearing in an IDE's console.
    """
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    try:
        import pygame
    except Exception:
        return None
    return pygame
