"""Kempston Mouse: a buttons byte and two free-running position counters.

Standard, publicly documented Kempston Mouse behaviour -- reimplemented independently.

**What the hardware is.** Two 8-bit counters and one buttons byte, and that is the
entire device. The counters are driven straight off the mouse's rollers, so they only
ever *change by* how far the mouse moved, and they wrap silently past 0 and 255 --
nothing in a roller knows where the edge of a screen is. Software therefore reads a
counter, subtracts what it read last time, and treats the (wrapped) difference as
movement; it can never ask "where is the pointer", because the interface has never
known. X counts up moving right. Y counts up moving *up* -- the opposite of screen and
Qt coordinates, where Y grows downward -- so ``move_by`` performs that flip once, here,
rather than leaving every caller to remember it.

**How it is addressed.** Like most Spectrum peripherals the interface decodes only a
few address lines and ignores the rest, because decoding costs chips and nobody fitted
more of them than the job needed. Four lines are examined out of sixteen:

    A0 = 1    Always required. Bit 0 clear belongs to the ULA, the one device on the
              bus that must never be shouted over.
    A5 = 0    Always required. This is the line the whole *Kempston* family sits on --
              the Kempston joystick at port 0x1F is on it too, which is precisely why
              a machine cannot usefully have both fitted at once.
    A8        What you are reading: 0 the buttons, 1 a position counter.
    A10       Which counter, once A8 says it is one: 0 is X, 1 is Y.

The addresses everyone quotes -- **0xFADF** buttons, **0xFBDF** X, **0xFFDF** Y -- are
just those four lines set correctly with every ignored line left high. Decoding lines
rather than the three literal addresses is what makes this answer the same reads the
real interface answers, including software that arrives with different high bits set.

It also means the interface is *greedy*: between them A8 and A10 cover every remaining
case, so **every** port with A0 set and A5 clear reads back as one of the three
registers -- 0x1F and 0x5F included. That is not over-reach in the emulation, it is
what a mouse plugged into a real expansion bus does to its neighbours, and it is a
large part of why this interface stays off until somebody asks for it (see ``enabled``).
"""

from __future__ import annotations

# Which bit of the buttons byte each button owns. The order looks arbitrary and is
# simply what the hardware does: right on bit 0, left on bit 1.
BUTTON_RIGHT = 0
BUTTON_LEFT = 1
BUTTON_MIDDLE = 2

# The address decode from the module docstring, as (mask, value) pairs: a port selects
# a register when ``port & mask == value``. Kept as constants rather than inlined so
# each one can be read against the line it stands for.
_SELECT_MASK, _SELECT_VALUE = 0x0021, 0x0001    # A5 = 0, A0 = 1  -- "this port is ours"
_BUTTONS_MASK, _BUTTONS_VALUE = 0x0121, 0x0001  # ... and A8 = 0
_X_MASK, _X_VALUE = 0x0521, 0x0101              # ... and A8 = 1, A10 = 0
_Y_MASK, _Y_VALUE = 0x0521, 0x0501              # ... and A8 = 1, A10 = 1


class KempstonMouse:
    """The interface's whole state: two counters, a buttons byte, and whether it exists.

    ``enabled`` models the interface being *fitted at all*, and defaults to off. A
    phantom mouse is not harmless: software probes these ports to decide whether one is
    present, so answering when nothing is plugged in makes programs take the mouse path
    on a machine that has no mouse -- and, because the decode above is deliberately
    greedy, it also puts this device on top of every other port with A0 set and A5
    clear. A UI toggle turns it on for whoever actually has one configured.
    """

    def __init__(self) -> None:
        self.enabled = False
        self.x = 0
        self.y = 0
        # Active-low, one bit per button: 0 means held. Unused bits read back as 1, the
        # same idle-high convention the rest of the bus uses.
        self._buttons = 0xFF

    def move_by(self, dx: int, dy: int) -> None:
        """Add a relative movement given in host (Qt) coordinates, where +dy is downward.

        Wrapping is the point, not a safeguard against bad input: the real counters wrap,
        software knows they wrap, and reading a wrapped counter is how it learns that the
        mouse went left past zero.
        """
        self.x = (self.x + dx) & 0xFF
        self.y = (self.y - dy) & 0xFF

    def set_button(self, button: int, pressed: bool) -> None:
        mask = 1 << button
        self._buttons = (self._buttons & ~mask) if pressed else (self._buttons | mask)

    def release_all_buttons(self) -> None:
        """Let go of everything at once, for when the *host* stops delivering events.

        Nothing about the emulated machine needs this; the host does. A UI that grabs
        the pointer can lose it mid-click -- the window loses focus, the user presses
        Esc, the interface gets switched off -- and the matching release then lands
        somewhere that isn't listening. Without a way to say "I am no longer in a
        position to tell you", the bit stays low forever: a phantom held button that
        outlives even re-grabbing the pointer, because a press nobody saw is a press
        nobody can release.
        """
        self._buttons = 0xFF

    def read_port(self, port: int) -> int:
        """The byte an ``IN`` from one of this interface's ports returns.

        ``enabled`` is re-tested here even though ``Machine._io_read`` already checked
        it (there, to keep an absent mouse down to one attribute compare on the I/O
        path). This is the object's own invariant, and anything reading it directly --
        a test, the debugger's port watch -- has to see the same silence the CPU does.
        """
        if not self.enabled:
            return 0xFF
        if port & _X_MASK == _X_VALUE:
            return self.x
        if port & _Y_MASK == _Y_VALUE:
            return self.y
        if port & _BUTTONS_MASK == _BUTTONS_VALUE:
            return self._buttons
        return 0xFF

    @staticmethod
    def handles(port: int) -> bool:
        """Whether this port belongs to the interface, ignoring whether one is fitted.

        Only the two always-required lines are tested, because the other two cannot
        rule a port out -- A8 chooses buttons or counter and A10 chooses which counter,
        so every combination lands on a register. There is no unclaimed address in the
        middle of this interface's range; see the module docstring on greediness.
        """
        return port & _SELECT_MASK == _SELECT_VALUE
