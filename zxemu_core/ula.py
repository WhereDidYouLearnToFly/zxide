"""ULA timing/contention and port 0xFE (border/keyboard/tape) handling.

Frame/contention geometry below is standard, publicly documented 48K
Spectrum ULA behavior (see e.g. Chris Smith's "The ZX Spectrum ULA" or the
long-standing comp.sys.sinclair community references), reimplemented
independently -- not derived from fuse's C source.
"""

from __future__ import annotations

FRAME_TSTATES = 69888  # 48K PAL: 312 lines * 224 T-states/line
LINE_TSTATES = 224
TOP_BORDER_LINES = 64
SCREEN_LINES = 192
SCREEN_START_TSTATE = TOP_BORDER_LINES * LINE_TSTATES  # 14336
CONTENDED_WINDOW_TSTATES = 128  # first 128 T-states of each screen line are the pixel/attr fetch window

_CONTENTION_PATTERN = (6, 5, 4, 3, 2, 1, 0, 0)


def contention_delay(t_state: int) -> int:
    """Extra T-states added when accessing contended memory/IO at this frame T-state.

    Only the 192 screen scanlines contend, and only during the first 128
    T-states of each such line (the ULA's pixel+attribute fetch window) --
    the rest of each line (right border, H-retrace, left border) does not.
    """
    t = t_state % FRAME_TSTATES
    relative = t - SCREEN_START_TSTATE
    if relative < 0 or relative >= SCREEN_LINES * LINE_TSTATES:
        return 0
    within_line = relative % LINE_TSTATES
    if within_line >= CONTENDED_WINDOW_TSTATES:
        return 0
    return _CONTENTION_PATTERN[within_line % 8]


class Ula:
    """Port 0xFE: OUT sets border color (bits 0-2); IN reads keyboard row bits.

    Beeper/MIC output and tape (EAR) input aren't modeled in this milestone;
    unused/undriven bits read as 1, matching the floating-bus convention.
    """

    def __init__(self, keyboard=None):
        self.keyboard = keyboard
        self.border_color = 0

    def write_port(self, port: int, value: int) -> None:
        if port & 0x01 == 0:
            self.border_color = value & 0x07

    def read_port(self, port: int) -> int:
        if port & 0x01 == 0:
            row_bits = self.keyboard.read(port) if self.keyboard is not None else 0x1F
            return 0xE0 | (row_bits & 0x1F)
        return 0xFF
