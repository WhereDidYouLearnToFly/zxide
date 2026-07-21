"""ULA timing/contention and port 0xFE (border/keyboard/tape) handling.

Frame/contention geometry below is standard, publicly documented 48K
Spectrum ULA behavior (see e.g. Chris Smith's "The ZX Spectrum ULA" or the
long-standing comp.sys.sinclair community references), reimplemented
independently -- not derived from fuse's C source.
"""

from __future__ import annotations

FRAME_TSTATES = 69888  # 48K PAL: 312 lines * 224 T-states/line
FRAME_TSTATES_128K = 70908  # 128K PAL: 311 lines * 228 T-states/line
# The 128K ULA runs a slightly longer frame than the 48K, so its 50Hz interrupt
# falls on a different T-state cadence -- code timed against one model runs a hair
# off on the other. Machine128 selects this length; see Machine.frame_tstates.
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
    """Port 0xFE: OUT sets border color (bits 0-2) and the speaker bit (bit 4);
    IN reads keyboard row bits.

    We record the speaker level but do no timing here -- turning the stream of
    speaker flips into sound needs to know *when* each flip happened, and only the
    Machine holds the frame T-state clock, so it timestamps the changes (see
    ``Machine._io_write``). Tape (EAR) input on bit 6 isn't modeled yet; unused
    read bits return 1, matching the floating-bus convention.
    """

    def __init__(self, keyboard=None):
        self.keyboard = keyboard
        self.border_color = 0
        self.speaker = 0  # port 0xFE bit 4: the 1-bit beeper output

    def write_port(self, port: int, value: int) -> None:
        if port & 0x01 == 0:
            self.border_color = value & 0x07
            self.speaker = (value >> 4) & 0x01

    def read_port(self, port: int) -> int:
        if port & 0x01 == 0:
            row_bits = self.keyboard.read(port) if self.keyboard is not None else 0x1F
            return 0xE0 | (row_bits & 0x1F)
        return 0xFF
