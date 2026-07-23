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
    ``LD-BYTES`` routine (at :data:`LD_BYTES_ENTRY`) by copying a whole block into
    memory in one go and setting the success flag the ROM would, so a tape loads with
    no waiting. The machine installs this behind a CPU trap; see ``Machine._tape_trap``.

Only fast loading is implemented. Authentic edge-level replay -- turning each block
back into the pilot/sync/data pulse train the ULA samples on port 0xFE bit 6, so you
see the loading stripes and hear the tape -- is a possible later addition; the block
model here is deliberately the shared foundation both loaders would sit on.
"""

from __future__ import annotations

from ..cpu.registers import FLAG_C

# The ROM's LD-BYTES routine lives here. The fast-load trap fires when the CPU
# reaches this address *and* the bytes there are LD-BYTES (see the signature check in
# Machine._tape_trap) -- which is true for the 48K ROM and the 128K's 48-BASIC ROM.
LD_BYTES_ENTRY = 0x0556

FLAG_HEADER = 0x00
FLAG_DATA = 0xFF

# A standard header's 17 data bytes start with a type byte; these name it for logging.
_HEADER_TYPES = {0: "Program", 1: "Number array", 2: "Character array", 3: "Code"}


class TapeBlock:
    """One tape block: its raw bytes (flag, payload, checksum) plus friendly decoding."""

    def __init__(self, data: bytes):
        self.data = bytes(data)

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
            kind = _HEADER_TYPES.get(self.data[1], f"type {self.data[1]}")
            name = bytes(self.data[2:12]).decode("ascii", "replace").rstrip()
            length = self.data[12] | (self.data[13] << 8)
            return f'Header "{name}" ({kind}, {length} bytes)'
        flag = self.flag
        label = "data" if flag == FLAG_DATA else "header" if flag == FLAG_HEADER else f"flag ${flag:02X}"
        return f"Block ({label}, {len(self.data)} bytes)"


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


class TapeDeck:
    """A loaded tape plus a play head: which block the next ``LD-BYTES`` will read."""

    def __init__(self, blocks: list[TapeBlock]):
        self.blocks = list(blocks)
        self.index = 0  # the next block to load

    @property
    def at_end(self) -> bool:
        return self.index >= len(self.blocks)

    def current(self) -> TapeBlock | None:
        """The block under the play head, or None once the tape has run out."""
        return None if self.at_end else self.blocks[self.index]

    def advance(self) -> None:
        """Move the play head to the next block."""
        self.index += 1

    def rewind(self) -> None:
        """Wind back to the start (e.g. to reload the same tape)."""
        self.index = 0


def fast_load(machine, deck: TapeDeck) -> bool:
    """Instantly satisfy one ROM ``LD-BYTES`` call from the deck's current block.

    Called when the CPU reaches :data:`LD_BYTES_ENTRY` with a tape inserted. At that
    point the ROM has set up, exactly as for a real tape read:

        IX = destination address        DE = number of data bytes wanted
        A  = expected flag byte          F carry = 1 to LOAD, 0 to VERIFY

    We read the whole block at once, copy (or verify) it, reproduce the parity/flag
    check the ROM would do, and finish the routine with a ``RET`` -- leaving the carry
    set on success, reset on failure, just like ``LD-BYTES`` itself. Returns True if it
    handled the call (and moved PC); False to let the ROM run the routine for real.
    """
    block = deck.current()
    if block is None or not block.data:
        return False  # no tape under the head -- let the ROM wait/time out itself

    regs = machine.cpu.regs
    expected_flag = regs.a
    loading = bool(regs.f & FLAG_C)  # carry set at entry = LOAD, reset = VERIFY

    # The ROM reads the flag byte first and checks it against the one requested. A
    # mismatch (e.g. it wanted a header but the head sits on a data block) is a failed
    # read: report it and leave the head where it is so the caller can decide.
    if block.data[0] != expected_flag:
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
    """Reproduce ``LD-BYTES``'s exit: set the success carry, re-enable interrupts, RET.

    The routine returns with carry **set** on a good load and **reset** on error, and
    it re-enables interrupts (it ran with them disabled) before returning. We then pop
    the caller's return address off the stack -- the ``RET`` that ends the routine.
    """
    cpu = machine.cpu
    regs = cpu.regs
    if success:
        regs.f |= FLAG_C
    else:
        regs.f &= ~FLAG_C & 0xFF
    regs.iff1 = regs.iff2 = True
    regs.pc = cpu.memory.read_word(regs.sp)
    regs.sp = (regs.sp + 2) & 0xFFFF
