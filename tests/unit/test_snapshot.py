"""Unit tests for the .sna snapshot loader."""

import importlib.resources as res

import pytest

from zxemu_core import snapshot
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
