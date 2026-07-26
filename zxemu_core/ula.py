"""ULA timing/contention and port 0xFE (border/keyboard/tape) handling.

Frame/contention geometry below is standard, publicly documented 48K
Spectrum ULA behavior (see e.g. Chris Smith's "The ZX Spectrum ULA" or the
long-standing comp.sys.sinclair community references), reimplemented
independently -- not derived from fuse's C source.
"""

from __future__ import annotations

FRAME_TSTATES = 69888  # 48K PAL: 312 lines * 224 T-states/line
FRAME_TSTATES_128K = 70908  # 128K PAL: 311 lines * 228 T-states/line
FRAME_TSTATES_PENTAGON = 71680  # Pentagon 128: 224 lines * 320 T-states/line
# The 128K ULA runs a slightly longer frame than the 48K, so its 50Hz interrupt
# falls on a different T-state cadence -- code timed against one model runs a hair
# off on the other. Machine128 selects this length; see Machine.frame_tstates.
#
# The Pentagon's frame is longer again, and its line is a round 320 T-states. That
# tidiness is the point: the clone's designers rebuilt the ULA's timing in discrete
# logic, and while they were there they dropped memory contention altogether (see
# MachinePentagon). Soviet-era demos are written against *this* cadence, which is why
# emulating a Pentagon as "a 128K with a disk drive" makes them run visibly wrong.
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
    IN reads keyboard row bits (0-4) and the tape input (bit 6).

    We record the levels but do no timing here. Both directions of the audio path
    need to know *when* something happened, and only the Machine holds the T-state
    clock, so it does the timestamping: it stamps outgoing speaker flips for the
    beeper (``Machine._io_write``) and sets :attr:`ear_level` from the tape player
    before each read (``Machine._io_read``). Unused read bits return 1, matching the
    floating-bus convention -- and with no tape playing, bit 6 stays 1 too, so a
    machine with an empty deck reads exactly what it always did.
    """

    def __init__(self, keyboard=None):
        self.keyboard = keyboard
        self.border_color = 0
        self.speaker = 0    # port 0xFE bit 4: the 1-bit beeper output
        self.ear_level = 1  # port 0xFE bit 6: what the tape input is doing right now

        # Where the border changed *during* this frame, as (frame T-state, colour). The
        # border is painted by the beam as it sweeps, so a program that writes 0xFE
        # part-way down the frame gets a horizontal band -- which is how border timing
        # is taught, how loading stripes happen, and what a single per-frame colour can
        # never show. The Machine appends here, for the same reason it timestamps
        # speaker flips: it owns the clock.
        self.border_changes: list[tuple[int, int]] = []
        self.frame_border_changes: list[tuple[int, int]] = []  # the last *completed* frame
        self.border_start_color = 0        # colour in force when the current frame began
        self.frame_border_start = 0        # ...and when the completed one did

    def write_port(self, port: int, value: int) -> None:
        if port & 0x01 == 0:
            self.border_color = value & 0x07
            self.speaker = (value >> 4) & 0x01

    def end_frame(self) -> None:
        """Close the frame's border log, so the renderer reads a complete frame.

        Kept separate from the live list because rendering happens *after* the frame is
        over: hand the renderer the list still being appended to and it would race the
        next frame's first few writes into the picture.
        """
        self.frame_border_changes = self.border_changes
        self.frame_border_start = self.border_start_color
        self.border_changes = []
        self.border_start_color = self.border_color

    def read_port(self, port: int) -> int:
        if port & 0x01 == 0:
            row_bits = self.keyboard.read(port) if self.keyboard is not None else 0x1F
            # Bit 6 is the whole of tape loading: a loader reads this one bit in a tight
            # loop and works out the data from how long it stays put between flips.
            return 0xA0 | (self.ear_level << 6) | (row_bits & 0x1F)
        return 0xFF
