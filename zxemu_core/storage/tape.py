"""ZX Spectrum tape (.tap) support: parse blocks and fast-load them via a ROM trap.

A ``.tap`` file is nothing more than a back-to-back list of tape blocks. On the file
each block is stored as:

    * a 2-byte little-endian length ``N``,
    * then ``N`` bytes of block data.

That block data is a standard ROM tape block: a **flag byte** (0x00 = header,
0xFF = data), the payload, and a final **checksum** byte that is the XOR of the flag
and every payload byte (so the XOR of the whole block is zero when intact). A BASIC
program on tape is therefore two blocks -- a 19-byte header, then the data.

This module does two things:

  * :func:`parse_tap` / :class:`TapeBlock` / :class:`TapeDeck` -- read a tape into
    blocks and keep a play position (which block loads next).
  * :func:`fast_load` -- the *fast* (instant) loader. It emulates the ROM's
    ``LD-BYTES`` routine by copying a whole block into memory in one go and setting the
    success flag the ROM would, so a tape loads with no waiting. The machine installs
    this behind a CPU trap; see ``Machine._tape_trap``.

**Where the trap sits, and why it matters.** ``LD-BYTES`` starts at
:data:`LD_BYTES_ENTRY` (0x0556), but the trap is on :data:`LD_BYTES_TRAP` (0x0562) --
the point *after* its preamble, where it starts sampling the tape::

    0556 LD-BYTES  inc d          ; \\
    0557            ex af,af'      ;  | preamble: stash the wanted flag byte and the
    0558            dec d          ;  | LOAD/VERIFY carry in AF', silence interrupts,
    0559            di             ;  | set the border, and push SA/LD-RET as the
    055A            ld a,$0F       ;  | routine's own return address
    055C            out ($FE),a    ;  |
    055E            ld hl,$053F    ;  |
    0561            push hl        ; /
    0562            in a,($FE)     ; <- the trap: first sample of the tape input

Trapping the later address catches *two* kinds of caller for the price of one. Loading
from BASIC enters at 0x0556 and falls through. But many game loaders -- especially the
multi-part 128K ones that page banks between blocks -- ``CALL 0x0562`` directly, having
done the preamble's work themselves; a trap on 0x0556 never sees those, so the game
spins forever in the ROM's edge-sampling loop waiting for pulses that fast loading
never produces. (Aliens: Neoplasma II is one such loader.)

The cost of trapping there is that the *expected flag byte and the LOAD/VERIFY carry
live in the shadow ``AF'``*, not the main one -- that is what ``ex af,af'`` above did,
and what a direct caller must therefore arrange too.

Fast loading is one of *two* loaders sharing this block model. The other is authentic
edge-level replay (``pulse.py``): the same blocks turned back into the pilot/sync/data
pulse train a real ULA samples on port 0xFE bit 6. Both drive the same
:class:`TapeDeck`, so they agree on where the play head is, and either can be the one
that moves it -- which matters, because a game's own turbo loader never calls
``LD-BYTES`` at all and can only ever be served by edges.
"""

from __future__ import annotations

from ..cpu.registers import FLAG_C
from .pulse import ROM_TIMING, BlockTiming, data_pulses

# The ROM's LD-BYTES routine starts here...
LD_BYTES_ENTRY = 0x0556
# ...and this is where it first samples the tape -- where the trap sits, so that game
# loaders calling in past the preamble are intercepted too (see the module docstring).
LD_BYTES_TRAP = 0x0562

FLAG_HEADER = 0x00
FLAG_DATA = 0xFF

# A standard header's 17 data bytes start with a type byte; these name it for logging.
_HEADER_TYPES = {0: "Program", 1: "Number array", 2: "Character array", 3: "Code"}


class TapeBlock:
    """One tape block: its raw bytes (flag, payload, checksum) plus friendly decoding.

    ``timing`` says how those bytes are spelled out as pulses when the block is played
    for real. Every ``.tap`` block uses the ROM's own numbers; a ``.tzx`` turbo block
    brings its own, which is the entire difference between a turbo tape and a normal
    one. The fast loader ignores the field completely -- it never generates a pulse.
    """

    def __init__(self, data: bytes, timing: BlockTiming = ROM_TIMING):
        self.data = bytes(data)
        self.timing = timing

    @property
    def pause_ms(self) -> int:
        """The silence that follows this block on tape (part of its timing)."""
        return self.timing.pause_ms

    def pulses(self):
        """The pulse lengths that spell this block out on the wire (see ``pulse.py``)."""
        return data_pulses(self.data, self.timing)

    @property
    def flag(self) -> int | None:
        """The leading flag byte (0x00 header / 0xFF data), or None for an empty block."""
        return self.data[0] if self.data else None

    @property
    def is_header(self) -> bool:
        """A standard 19-byte header block (flag 0x00, 17 data bytes, checksum)."""
        return len(self.data) == 19 and self.flag == FLAG_HEADER

    def describe(self) -> str:
        """A one-line, human-readable summary for the Output log.

        Decodes a standard header (filename, kind, length); otherwise just reports the
        block's flag and size. Purely cosmetic -- loading never depends on it.
        """
        if self.is_header:
            kind = _HEADER_TYPES.get(self.data[1], "type {}".format(self.data[1]))
            name = bytes(self.data[2:12]).decode("ascii", "replace").rstrip()
            length = self.data[12] | (self.data[13] << 8)
            return 'Header "{}" ({}, {} bytes)'.format(name, kind, length)
        flag = self.flag
        label = "data" if flag == FLAG_DATA else "header" if flag == FLAG_HEADER else "flag ${:02X}".format(flag)
        return "Block ({}, {} bytes)".format(label, len(self.data))


def parse_tap(data: bytes) -> list[TapeBlock]:
    """Split raw ``.tap`` bytes into blocks; raise ValueError if it isn't a tape.

    Walks the file as (2-byte length, that many bytes) records. A trailing run that is
    too short to be a whole block -- a truncated file -- is ignored rather than fatal,
    so a slightly damaged tape still yields the blocks it does contain.
    """
    blocks: list[TapeBlock] = []
    offset = 0
    while offset + 2 <= len(data):
        length = data[offset] | (data[offset + 1] << 8)
        offset += 2
        if length == 0 or offset + length > len(data):
            break  # zero-length marker or a truncated final block -- stop cleanly
        blocks.append(TapeBlock(data[offset:offset + length]))
        offset += length
    if not blocks:
        raise ValueError("no tape blocks found (not a .tap file?)")
    return blocks


def data_blocks(items) -> list[TapeBlock]:
    """Just the items carrying block data -- the ones a fast load can serve.

    A ``.tzx`` also holds bare tones, pulse lists and silences (see ``pulse.py``).
    They are essential when the tape is *played*, and meaningless when it is
    shortcut, so anything counting or listing "the blocks on this tape" filters here.
    """
    return [item for item in items if item.data is not None]


class TapeDeck:
    """A loaded tape plus a play head: where both loaders are up to on it.

    The head is a single index into :attr:`items`, shared deliberately. Fast loading
    moves it a whole block at a time; edge replay moves it as it finishes playing one.
    A game that starts under the ROM loader and switches to its own turbo loader
    halfway -- which is most commercial multi-part tapes -- therefore hands over
    without either loader losing its place.
    """

    def __init__(self, items: list):
        self.items = list(items)
        self.index = 0  # the next item to play or load

    @property
    def blocks(self) -> list[TapeBlock]:
        """The loadable blocks, ignoring tones and silences (see :func:`data_blocks`)."""
        return data_blocks(self.items)

    @property
    def at_end(self) -> bool:
        return self.index >= len(self.items)

    def current_item(self) -> object | None:
        """Whatever is under the head -- block, tone or silence -- or None at the end."""
        return None if self.at_end else self.items[self.index]

    def current(self) -> TapeBlock | None:
        """The next *loadable block*, winding past anything that isn't one.

        Fast loading can only serve real block data, so a pilot tone stored as its own
        container entry has to be wound over rather than stared at. Skipping is what a
        cassette does anyway: unusable signal goes past the head, it doesn't stop it.
        """
        while not self.at_end and self.items[self.index].data is None:
            self.index += 1
        return None if self.at_end else self.items[self.index]

    def advance(self) -> None:
        """Move the play head to the next item."""
        self.index += 1

    def rewind(self) -> None:
        """Wind back to the start (e.g. to reload the same tape)."""
        self.index = 0


def fast_load(machine, deck: TapeDeck) -> bool:
    """Instantly satisfy one ROM ``LD-BYTES`` call from the deck's current block.

    Called when the CPU reaches :data:`LD_BYTES_TRAP` with a tape inserted. At that
    point the caller has set up, exactly as for a real tape read:

        IX = destination address        DE = number of data bytes wanted
        A' = expected flag byte         F' carry = 1 to LOAD, 0 to VERIFY

    The *shadow* AF holds the flag and carry because the routine's preamble put them
    there (``ex af,af'``) before the trap address is reached -- see the module
    docstring; a loader entering at 0x0562 itself has done the same.

    We read the whole block at once, copy (or verify) it, reproduce the parity/flag
    check the ROM would do, and finish the routine with a ``RET`` -- leaving the carry
    set on success, reset on failure, just like ``LD-BYTES`` itself. Returns True if it
    handled the call (and moved PC); False to let the ROM run the routine for real.
    """
    block = deck.current()
    if block is None or not block.data:
        return False  # no tape under the head -- let the ROM wait/time out itself

    regs = machine.cpu.regs
    expected_flag = regs.a2
    loading = bool(regs.f2 & FLAG_C)  # shadow carry set at entry = LOAD, reset = VERIFY

    # The ROM reads the flag byte first and checks it against the one requested. A
    # mismatch (it wanted a header, say, but this is a data block) is a failed read --
    # and the head still moves on, because on a real cassette the tape keeps rolling
    # whether or not the block was the one being looked for. That is exactly how
    # `LOAD ""` finds a program that isn't first on the tape: it reads, rejects, and
    # tries again on whatever comes next. Leaving the head parked instead would make the
    # ROM re-read the same rejected block forever.
    if block.data[0] != expected_flag:
        deck.advance()
        _finish_ld_bytes(machine, success=False)
        return True

    want = regs.de
    address = regs.ix
    payload = block.data[1:]          # data bytes followed by the single checksum byte
    available = len(payload) - 1      # how many real data bytes the block carries
    parity = block.data[0]
    copied = 0
    ok = True

    for n in range(want):
        if n >= available:
            ok = False  # tape block shorter than the loader asked for
            break
        byte = payload[n]
        parity ^= byte
        if loading:
            machine.memory.write_byte((address + n) & 0xFFFF, byte)
        elif machine.memory.read_byte((address + n) & 0xFFFF) != byte:
            ok = False  # VERIFY: memory doesn't match the tape
        copied += 1

    # A clean load also folds in the checksum byte; parity across flag+data+checksum
    # must come out zero, matching what the ROM's running XOR would find.
    if ok and copied == want:
        parity ^= payload[want]
        ok = parity == 0

    regs.ix = (address + copied) & 0xFFFF
    regs.de = (want - copied) & 0xFFFF
    _finish_ld_bytes(machine, success=ok)
    deck.advance()
    return True


def _finish_ld_bytes(machine, success: bool) -> None:
    """Reproduce ``LD-BYTES``'s exit: set the success carry in the main F, then RET.

    The routine returns with carry **set** on a good load and **reset** on error, in the
    *main* AF (the shadow set carried the request in). We pop the return address off the
    stack -- the ``RET`` that ends the routine.

    Interrupts are deliberately left as they are. Entering from BASIC, the address we
    return to is ``SA/LD-RET`` (0x053F), pushed by the preamble, which restores the
    border, checks BREAK and does the ``EI`` itself; a loader that called 0x0562 directly
    disabled interrupts for its own reasons and will re-enable them when it's ready.
    Forcing ``EI`` here would override both.
    """
    cpu = machine.cpu
    regs = cpu.regs
    if success:
        regs.f |= FLAG_C
    else:
        regs.f &= ~FLAG_C & 0xFF
    regs.pc = cpu.memory.read_word(regs.sp)
    regs.sp = (regs.sp + 2) & 0xFFFF
