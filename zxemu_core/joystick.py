"""Kempston Joystick: one byte of directions and a fire button, read from port 0x1F.

Standard, publicly documented Kempston interface behaviour -- reimplemented independently.

**What the hardware is.** A handful of switches and nothing else. There is no latch, no handshake
and nothing to write to: the byte an ``IN`` returns *is* the state of the switches at that
instant, one bit each, and a program polls it as often as it likes. The bits are **active
high** -- 1 means pressed -- which is the opposite of nearly everything else on a Spectrum
(the keyboard, the mouse's buttons) and the single most common thing to get backwards:

    bit 0   right      bit 3   up
    bit 1   left       bit 4   fire

so an idle joystick reads 0x00 and "up and fire" reads 0x18.

**The upper bits, and the two modes.** Later interfaces widened the port to a full eight
bits for pads with more than one button. They do not all agree on how, so this follows the
**ZX Spectrum Next**, whose layout is really the Mega Drive pad's::

    bit 7   START      bit 5   C  (second fire)
    bit 6   A          bit 4   B  (the original fire)

and which reaches the port through two different masks, depending on the mode the Next's
NR 0x05 selects for that connector:

    Kempston (modes 001/100)      bits 5:0 pass, bits 7:6 are forced to 0  -> 0x3F
    MD 3-button (modes 101/110)   the whole byte passes                    -> 0xFF

That masking *is* the specification -- the difference between the two modes is nothing else
-- so it is modelled here rather than glossed over: ``extended`` picks between them. Note
what follows from it, because it surprises people: a second fire button (bit 5) works in
plain Kempston mode, while A and START need the extended mode. Traced to the Next's own
VHDL via the jnext emulator (``zxnext.vhd:3441-3442`` for the layout, ``:3478-3479`` for the
two lanes; see ``jnext/src/input/joystick.cpp``).

Original 1980s hardware drove only bits 0-4, so it looks like an extended interface whose
extra buttons are never pressed -- which is exactly why software written for one works
unchanged on the other, and why this needs no third mode.

**How it is addressed.** Everyone writes the port as 0x1F, but as with the rest of the
Kempston family the interface decodes only a few lines -- here A5, A6 and A7, all of which
must be **clear**. Every other address line is ignored, so the whole low-byte range
0x00-0x1F answers, at any high byte. (Fuse offers a "loose" variant that tests A5 alone,
for the handful of clones that decoded even less; the stricter decode is the safer default
and the one modelled here.)

**Why this cannot coexist with the Kempston Mouse.** The mouse (see ``mouse.py``) requires
A5 clear too, and port 0x1F satisfies both decodes -- plug both into a real Spectrum and
they drive the data bus against each other. The UI enforces the same exclusivity by making
the two menu items mutually exclusive, which is the honest emulation of a physical fact
rather than a limitation of the software.
"""

from __future__ import annotations

# One bit per switch, active high. Named rather than numbered at the call sites, because
# "bit 3" is meaningless and "up" is not. The names in brackets are the Mega Drive pad's,
# which is what the Next's layout is really describing.
RIGHT = 0x01
LEFT = 0x02
DOWN = 0x04
UP = 0x08
FIRE = 0x10     # [B] the one button an original Kempston has
FIRE2 = 0x20    # [C] second fire; present in both of the Next's modes
BUTTON_A = 0x40  # [A] extended only -- masked off in Kempston mode
START = 0x80    # [START] extended only -- masked off in Kempston mode

#: What reaches the port in each mode, straight from the VHDL (see the module docstring).
KEMPSTON_MASK = 0x3F   # zxnext.vhd:3479 -- bits 5:0 pass, 7:6 forced to 0
EXTENDED_MASK = 0xFF   # zxnext.vhd:3478 -- MD 3-button mode passes 7:6 as well

# Address decode as a (mask, value) pair: the port belongs to the interface when
# ``port & mask == value``. A7, A6 and A5 clear; the other thirteen lines are not wired.
_SELECT_MASK, _SELECT_VALUE = 0x00E0, 0x0000


class KempstonJoystick:
    """The switches, which of them reach the port, and whether one is plugged in at all.

    ``enabled`` defaults to off for the same two reasons the mouse's does: software probes
    the port to decide whether a joystick is fitted, and the decode is wide enough (any
    port with A5, A6 and A7 clear) that fitting one puts this device on top of its
    neighbours -- the Kempston Mouse among them, which is why the two are exclusive.
    """

    def __init__(self) -> None:
        self.enabled = False
        #: Pass the whole byte (the Next's MD 3-button mode) rather than masking bits 7:6
        #: off (its Kempston mode). Off by default: A and START reaching software that was
        #: written for a one-button stick is the kind of difference that shows up as a game
        #: mysteriously pausing, and the mode is exactly what a real Next has to be told.
        self.extended = False
        # Two input sources, kept apart and merged only on read. Active high throughout,
        # so "nothing pressed" is zero -- the reverse of the mouse's 0xFF.
        #
        # They must not share one field. The keyboard arrives as *edges* (this key went
        # down, that one came up) while a gamepad is *polled* (here is the whole stick,
        # once per frame), so a poll writing the full mask would wipe a key the user is
        # still holding, fifty times a second. One field each, OR-ed at the port, and
        # each source can say only what it knows.
        self._keys = 0x00
        self._pad = 0x00

    def set_switch(self, switch: int, pressed: bool) -> None:
        """Hold or let go of one direction or fire from the *keyboard* (a ``RIGHT``/... mask)."""
        self._keys = (self._keys | switch) if pressed else (self._keys & ~switch)

    def set_pad_switches(self, switches: int) -> None:
        """Replace the *gamepad's* whole contribution, as read in one poll.

        Wholesale rather than per-switch because that is what a poll knows: the state of
        every direction and button at one instant. Nothing needs to track edges, and a
        pad unplugged mid-game simply stops contributing once someone passes 0.
        """
        self._pad = switches

    def release_all(self) -> None:
        """Centre the stick and let go of fire, for when the host stops sending events.

        Same hazard as the mouse's ``release_all_buttons``: whatever was held when the
        emulator lost focus never gets its key-up, so the game would keep running left
        into a wall forever. See ``KempstonMouse.release_all_buttons``.
        """
        self._keys = 0x00
        self._pad = 0x00

    def read_port(self, port: int) -> int:
        """The byte an ``IN`` returns: the switches, or 0x00 if this is read while unfitted.

        That 0x00 is this object keeping quiet, *not* what a Spectrum without a Kempston
        interface reads. There the machine never routes the port here at all and the
        undriven bus answers -- 0xFF, every direction and fire apparently held down at
        once. Active-high switches are why an absent joystick reads as "everything
        pressed" rather than as nothing, and why a game polling 0x1F on a machine with no
        interface can career off on its own.
        """
        if not self.enabled:
            return 0x00
        if port & _SELECT_MASK == _SELECT_VALUE:
            # Keyboard and gamepad OR together: one physical stick as far as the Spectrum
            # can tell, so either can drive it and neither cancels the other. The mask is
            # applied here, at the port, rather than when switches are set -- the buttons
            # stay pressed either way, exactly as on hardware where the pad's extra
            # switches close whether or not the interface passes them on.
            mask = EXTENDED_MASK if self.extended else KEMPSTON_MASK
            return (self._keys | self._pad) & mask
        return 0x00

    @staticmethod
    def handles(port: int) -> bool:
        return port & _SELECT_MASK == _SELECT_VALUE
