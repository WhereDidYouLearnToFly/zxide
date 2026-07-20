"""Load ZX Spectrum snapshot (.sna) files into a Machine.

A .sna file is a raw dump of machine state. The 48K variant is 49179 bytes: a
27-byte header (the registers, interrupt state and border colour) followed by the
48K RAM image ($4000-$FFFF). The program counter is *not* in the header -- it sits
on the stack, so restoring is exactly what a RETN would do: PC = (SP), then SP += 2.

128K snapshots (131103 bytes, carrying the 0x7FFD paging byte and all 8 RAM banks)
need the 128K machine and aren't handled yet -- we raise a clear error for those.
"""

from __future__ import annotations

SNA_48K_SIZE = 49179
SNA_128K_SIZE = 131103
HEADER_SIZE = 27
BANK_SIZE = 0x4000


def _word(data: bytes, offset: int) -> int:
    return data[offset] | (data[offset + 1] << 8)


def load_sna(machine, data: bytes) -> None:
    """Restore a 48K .sna into ``machine`` (CPU registers, RAM, border, PC)."""
    if len(data) != SNA_48K_SIZE:
        if len(data) == SNA_128K_SIZE:
            raise NotImplementedError(
                "128K snapshots need the 128K machine, which isn't built yet"
            )
        raise ValueError(f"not a 48K .sna: expected {SNA_48K_SIZE} bytes, got {len(data)}")

    regs = machine.cpu.regs
    regs.i = data[0]
    regs.hl2 = _word(data, 1)
    regs.de2 = _word(data, 3)
    regs.bc2 = _word(data, 5)
    regs.af2 = _word(data, 7)
    regs.hl = _word(data, 9)
    regs.de = _word(data, 11)
    regs.bc = _word(data, 13)
    regs.iy = _word(data, 15)
    regs.ix = _word(data, 17)
    interrupts_enabled = bool(data[19] & 0x04)  # bit 2 = IFF2 (mirrors IFF1)
    regs.iff1 = interrupts_enabled
    regs.iff2 = interrupts_enabled
    regs.r = data[20]
    regs.af = _word(data, 21)
    regs.sp = _word(data, 23)
    regs.im = data[25]
    machine.ula.border_color = data[26] & 0x07

    # RAM image $4000-$FFFF straight into the three RAM banks (slots 1, 2, 3).
    ram = data[HEADER_SIZE:HEADER_SIZE + 3 * BANK_SIZE]
    for slot in (1, 2, 3):
        start = (slot - 1) * BANK_SIZE
        machine.memory.slots[slot].data[:] = ram[start:start + BANK_SIZE]

    # PC comes off the stack (as a RETN would), and SP steps past it.
    sp = regs.sp
    regs.pc = machine.memory.read_word(sp)
    regs.sp = (sp + 2) & 0xFFFF
