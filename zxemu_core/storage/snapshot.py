"""Load ZX Spectrum snapshot (.sna) files into a Machine.

A .sna file is a raw dump of machine state, in one of two variants:

* **48K** (49179 bytes): a 27-byte header (registers, interrupt state, border) then
  the 48K RAM image ($4000-$FFFF). The program counter is *not* in the header -- it
  sits on the stack, so restoring is exactly what a RETN does: PC = (SP), SP += 2.
* **128K** (131103 bytes): the same 27-byte header, then three 16K blocks (RAM bank
  5, RAM bank 2, and whatever bank is paged at $C000), a 4-byte extra header (PC,
  the 0x7FFD paging byte, a TR-DOS flag), and the remaining RAM banks in ascending
  order. Here the PC comes from the extra header, and the paging byte is applied so
  the machine resumes with the exact bank/screen/ROM layout that was saved.

Loading a 128K image requires the 128K machine (it needs the eight-bank pool); a
48K machine, or a size that is neither, raises a clear error.
"""

from __future__ import annotations

SNA_48K_SIZE = 49179
SNA_128K_SIZE = 131103
HEADER_SIZE = 27
BANK_SIZE = 0x4000


def _word(data: bytes, offset: int) -> int:
    return data[offset] | (data[offset + 1] << 8)


def _load_registers(machine, data: bytes) -> None:
    """Parse the shared 27-byte header (registers, interrupt state, border).

    Common to both .sna variants. Note it does *not* set PC: the 48K recovers PC
    from the stack, the 128K from its extra header, so each caller finishes the job.
    """
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


def load_sna(machine, data: bytes) -> None:
    """Restore a .sna (48K or 128K) into ``machine``, dispatching on file size."""
    if len(data) == SNA_48K_SIZE:
        _load_sna_48k(machine, data)
    elif len(data) == SNA_128K_SIZE:
        load_sna_128k(machine, data)
    else:
        raise ValueError(
            f"not a .sna: expected {SNA_48K_SIZE} or {SNA_128K_SIZE} bytes, got {len(data)}"
        )


def _load_sna_48k(machine, data: bytes) -> None:
    """Restore a 48K .sna: header, the 48K RAM image, and PC popped off the stack."""
    if hasattr(machine, "ram_banks"):
        raise ValueError("a 48K snapshot cannot be loaded into the 128K machine")
    _load_registers(machine, data)

    # RAM image $4000-$FFFF straight into the three RAM banks (slots 1, 2, 3).
    ram = data[HEADER_SIZE:HEADER_SIZE + 3 * BANK_SIZE]
    for slot in (1, 2, 3):
        start = (slot - 1) * BANK_SIZE
        machine.memory.slots[slot].data[:] = ram[start:start + BANK_SIZE]

    # PC comes off the stack (as a RETN would), and SP steps past it.
    sp = machine.cpu.regs.sp
    machine.cpu.regs.pc = machine.memory.read_word(sp)
    machine.cpu.regs.sp = (sp + 2) & 0xFFFF


def load_sna_128k(machine, data: bytes) -> None:
    """Restore a 128K .sna into the 128K machine (all 8 banks + paging + PC)."""
    if not hasattr(machine, "ram_banks"):
        raise NotImplementedError("a 128K snapshot needs the 128K machine")
    _load_registers(machine, data)

    # The extra header sits after the header + three fixed 16K blocks.
    extra = HEADER_SIZE + 3 * BANK_SIZE
    pc = _word(data, extra)
    port_7ffd = data[extra + 2]
    # data[extra + 3] is the TR-DOS ROM flag -- we don't emulate TR-DOS, so ignore it.

    current = port_7ffd & 0x07  # the bank that was paged at $C000 when saved
    # The three fixed blocks, in order, are banks 5, 2, then the current $C000 bank.
    fixed_order = (5, 2, current)
    for i, bank in enumerate(fixed_order):
        start = HEADER_SIZE + i * BANK_SIZE
        machine.ram_banks[bank].data[:] = data[start:start + BANK_SIZE]

    # The remaining banks follow the extra header, in ascending bank number.
    offset = extra + 4
    for bank in range(8):
        if bank in fixed_order:
            continue
        machine.ram_banks[bank].data[:] = data[offset:offset + BANK_SIZE]
        offset += BANK_SIZE

    # Restore the exact paging (bank in slot 3, ROM, screen, lock) and the saved PC.
    machine.set_paging(port_7ffd, force=True)
    machine.cpu.regs.pc = pc
