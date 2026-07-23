"""Unit tests for the .sna snapshot loader."""

import importlib.resources as res

import pytest

from zxemu_core.storage import snapshot
from zxemu_core.machine import Machine


def _rom() -> bytes:
    return (res.files("zxemu_core") / "roms" / "48.rom").read_bytes()


def _put_word(buf: bytearray, offset: int, value: int) -> None:
    buf[offset] = value & 0xFF
    buf[offset + 1] = (value >> 8) & 0xFF


def _make_48k_sna() -> bytes:
    """A synthetic 48K snapshot with distinctive, checkable field values."""
    header = bytearray(snapshot.HEADER_SIZE)
    header[0] = 0x3F  # I
    _put_word(header, 1, 0x1122)   # HL'
    _put_word(header, 3, 0x3344)   # DE'
    _put_word(header, 5, 0x5566)   # BC'
    _put_word(header, 7, 0x7788)   # AF'
    _put_word(header, 9, 0x99AA)   # HL
    _put_word(header, 11, 0xBBCC)  # DE
    _put_word(header, 13, 0xDDEE)  # BC
    _put_word(header, 15, 0x0102)  # IY
    _put_word(header, 17, 0x0304)  # IX
    header[19] = 0x04              # interrupts enabled (IFF)
    header[20] = 0x7E              # R
    _put_word(header, 21, 0xABCD)  # AF
    _put_word(header, 23, 0x8000)  # SP (points into RAM)
    header[25] = 2                 # interrupt mode
    header[26] = 5                 # border colour (cyan)

    ram = bytearray(3 * snapshot.BANK_SIZE)
    ram[0x0000] = 0xA5             # a marker at address 0x4000
    _put_word(ram, 0x8000 - 0x4000, 0x9000)  # PC sitting on the stack at SP=0x8000
    return bytes(header + ram)


def test_load_48k_sna_restores_registers_and_state():
    machine = Machine(_rom())
    snapshot.load_sna(machine, _make_48k_sna())
    regs = machine.cpu.regs

    assert regs.i == 0x3F
    assert (regs.hl2, regs.de2, regs.bc2, regs.af2) == (0x1122, 0x3344, 0x5566, 0x7788)
    assert (regs.hl, regs.de, regs.bc) == (0x99AA, 0xBBCC, 0xDDEE)
    assert (regs.iy, regs.ix) == (0x0102, 0x0304)
    assert regs.iff1 is True and regs.iff2 is True
    assert regs.r == 0x7E
    assert regs.af == 0xABCD
    assert regs.im == 2
    assert machine.ula.border_color == 5
    assert machine.memory.read_byte(0x4000) == 0xA5

    # PC comes off the stack (0x9000), and SP steps past it (0x8000 -> 0x8002).
    assert regs.pc == 0x9000
    assert regs.sp == 0x8002


def test_wrong_size_is_rejected():
    machine = Machine(_rom())
    with pytest.raises(ValueError):
        snapshot.load_sna(machine, b"\x00" * 1000)


def test_128k_snapshot_reports_not_implemented():
    machine = Machine(_rom())
    with pytest.raises(NotImplementedError):
        snapshot.load_sna(machine, b"\x00" * snapshot.SNA_128K_SIZE)


from zxemu_core.machine import Machine128


def _make_machine128() -> Machine128:
    return Machine128(bytes(0x4000), bytes(0x4000))


def _make_128k_sna(port_7ffd: int = 0x14, pc: int = 0x9000) -> bytes:
    """A synthetic 128K snapshot; each RAM bank is filled with its own bank number.

    port_7ffd's low bits pick the bank at $C000; 0x14 -> bank 4 (and ROM1), which is
    not 5 or 2, so the three fixed blocks (5, 2, 4) and the five remaining banks are
    all distinct -- the normal case the 131103-byte layout assumes.
    """
    header = bytearray(snapshot.HEADER_SIZE)
    header[0] = 0x11               # I
    header[19] = 0x04              # IFF enabled
    header[20] = 0x33              # R
    _put_word(header, 23, 0x8000)  # SP -- must be left untouched (PC is in the extra header)
    header[25] = 1                 # IM
    header[26] = 2                 # border (red)

    current = port_7ffd & 0x07
    data = bytearray(header)
    for bank in (5, 2, current):   # the three fixed blocks, in this order
        data += bytes([bank]) * snapshot.BANK_SIZE

    extra = bytearray(4)
    _put_word(extra, 0, pc)        # PC lives here, not on the stack
    extra[2] = port_7ffd
    extra[3] = 0                   # TR-DOS flag
    data += extra

    for bank in range(8):          # remaining banks, ascending, skipping the fixed three
        if bank in (5, 2, current):
            continue
        data += bytes([bank]) * snapshot.BANK_SIZE

    assert len(data) == snapshot.SNA_128K_SIZE
    return bytes(data)


def test_load_128k_sna_restores_all_banks_paging_and_pc():
    machine = _make_machine128()
    snapshot.load_sna(machine, _make_128k_sna(port_7ffd=0x14, pc=0x9000))
    regs = machine.cpu.regs

    assert regs.i == 0x11
    assert regs.iff1 is True and regs.iff2 is True
    assert regs.im == 1
    assert machine.ula.border_color == 2

    # Every RAM bank got its own sentinel byte, wherever it lived in the file.
    for bank in range(8):
        assert machine.ram_banks[bank].data[0] == bank

    # Paging restored from the saved 0x7FFD (bank 4 in slot 3, ROM1 in slot 0).
    assert machine.port_7ffd == 0x14
    assert machine.memory.slots[3] is machine.ram_banks[4]
    assert machine.memory.slots[0] is machine.rom_banks[1]

    # PC from the extra header; SP is NOT advanced (unlike the 48K stack-pop path).
    assert regs.pc == 0x9000
    assert regs.sp == 0x8000


def test_load_128k_sna_into_48k_machine_is_rejected():
    machine = Machine(_rom())
    with pytest.raises(NotImplementedError):
        snapshot.load_sna(machine, _make_128k_sna())


def test_load_48k_sna_into_128k_machine_is_rejected():
    machine = _make_machine128()
    with pytest.raises(ValueError):
        snapshot.load_sna(machine, _make_48k_sna())
