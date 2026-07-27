"""Kempston Mouse interface: ports 0xFADF (buttons), 0xFBDF (X), 0xFFDF (Y).

Standard, publicly documented Kempston Mouse interface behaviour -- reimplemented
independently. The interface exposes two free-running 8-bit counters that wrap on
overflow/underflow (the host only ever tells it a *relative* movement, never a
position), plus a buttons byte. X counts up moving right; Y counts up moving *up*
(inverted from screen/Qt coordinates, where Y grows downward) -- both match the
convention long-established by Kempston-mouse-aware software and the emulators it
was written against.
"""

from __future__ import annotations

BUTTON_RIGHT = 0
BUTTON_LEFT = 1
BUTTON_MIDDLE = 2


class KempstonMouse:
    """Free-running X/Y counters plus a buttons byte, addressed by three ports.

    ``enabled`` gates whether the ports respond at all: disabled (the default),
    they must stay silent -- some software probes these addresses to decide
    whether a mouse is fitted, and a phantom "yes" would misdetect hardware
    that was never there. A UI toggle flips it on for whoever actually has a
    Kempston Mouse configured.
    """

    def __init__(self) -> None:
        self.enabled = False
        self.x = 0
        self.y = 0
        # Active-low, one bit per button; unused bits (and no interface fitted)
        # read back as 1, matching the floating-bus convention used elsewhere.
        self._buttons = 0xFF

    def move_by(self, dx: int, dy: int) -> None:
        """Add a relative movement, in host (Qt) coordinates: +dy is downward.

        The counters are 8-bit and wrap -- exactly what the real interface's
        quadrature counters do, and what software reading them already expects.
        """
        self.x = (self.x + dx) & 0xFF
        self.y = (self.y - dy) & 0xFF

    def set_button(self, button: int, pressed: bool) -> None:
        mask = 1 << button
        self._buttons = (self._buttons & ~mask) if pressed else (self._buttons | mask)

    def read_port(self, port: int) -> int:
        if not self.enabled:
            return 0xFF
        if port == 0xFBDF:
            return self.x
        if port == 0xFFDF:
            return self.y
        if port == 0xFADF:
            return self._buttons
        return 0xFF

    @staticmethod
    def handles(port: int) -> bool:
        return port in (0xFADF, 0xFBDF, 0xFFDF)
