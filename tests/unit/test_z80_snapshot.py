"""Unit tests for the .z80 snapshot loader (all three versions, 48K and 128K)."""

import importlib.resources as res

import pytest

from zxemu_core.machine import Machine, Machine128
from zxemu_core.storage import z80


def _rom() -> bytes:
    return (res.files("zxemu_core") / "roms" / "48.rom").read_bytes()


def _roms_128() -> tuple[bytes, bytes]:
    folder = res.files("zxemu_core") / "roms"
    return (folder / "128-0.rom").read_bytes(), (folder / "128-1.rom").read_bytes()


def _header(*, pc: int, flags1: int = 0x00, sp: int = 0x7000) -> bytearray:
    """The 30-byte header every version starts with, filled with recognisable values."""
    h = bytearray(30)
    h[0] = 0x12          # A
    h[1] = 0x34          # F
    h[2], h[3] = 0x56, 0x78   # BC = 0x7856
    h[4], h[5] = 0x9A, 0xBC   # HL = 0xBC9A
    h[6], h[7] = pc & 0xFF, pc >> 8
    h[8], h[9] = sp & 0xFF, sp >> 8
    h[10] = 0x3F         # I
    h[11] = 0x7E         # R (7 bits)
    h[12] = flags1
    h[13], h[14] = 0x11, 0x22  # DE = 0x2211
    h[15], h[16] = 0x33, 0x44  # BC'
    h[17], h[18] = 0x55, 0x66  # DE'
    h[19], h[20] = 0x77, 0x88  # HL'
    h[21] = 0x99         # A'
    h[22] = 0xAA         # F'
    h[23], h[24] = 0xBB, 0xCC  # IY
    h[25], h[26] = 0xDD, 0xEE  # IX
    h[27] = 1            # IFF1
    h[28] = 1            # IFF2
    h[29] = 0x02         # IM 2
    return h


def _compress(data: bytes) -> bytes:
    """Encode every byte as its own ED ED run -- valid, if wasteful, and easy to verify."""
    out = bytearray()
    for byte in data:
        out += bytes([0xED, 0xED, 1, byte])
    return bytes(out)


def _rle(byte: int, count: int) -> bytes:
    """The same run encoded properly, in chunks of at most 255 (the count is one byte)."""
    out = bytearray()
    while count:
        chunk = min(count, 255)
        out += bytes([0xED, 0xED, chunk, byte])
        count -= chunk
    return bytes(out)


# --- v1 (48K, flat) -----------------------------------------------------------

def test_v1_uncompressed_restores_registers_and_ram():
    machine = Machine(_rom())
    image = bytes(range(256)) * 192  # exactly 48K of recognisable data
    data = bytes(_header(pc=0x8000, flags1=0x0E)) + image  # border 7 (bits 1-3)

    z80.load_z80(machine, data)

    regs = machine.cpu.regs
    assert regs.pc == 0x8000 and regs.sp == 0x7000
    assert regs.a == 0x12 and regs.f == 0x34
    assert regs.bc == 0x7856 and regs.hl == 0xBC9A and regs.de == 0x2211
    assert regs.bc2 == 0x4433 and regs.de2 == 0x6655 and regs.hl2 == 0x8877
    assert regs.a2 == 0x99 and regs.f2 == 0xAA
    assert regs.ix == 0xEEDD and regs.iy == 0xCCBB
    assert regs.i == 0x3F and regs.im == 2 and regs.iff1 and regs.iff2
    assert machine.ula.border_color == 7
    assert machine.memory.read_byte(0x4000) == image[0]
    assert machine.memory.read_byte(0xFFFF) == image[-1]


def test_v1_compressed_expands_runs_and_stops_at_the_end_marker():
    machine = Machine(_rom())
    image = bytes([0xAB]) * (3 * 0x4000)
    body = _compress(image) + bytes([0x00, 0xED, 0xED, 0x00]) + b"trailing junk"
    data = bytes(_header(pc=0x9000, flags1=0x20)) + body  # bit 5 = compressed

    z80.load_z80(machine, data)

    assert machine.memory.read_byte(0x4000) == 0xAB
    assert machine.memory.read_byte(0xFFFF) == 0xAB


def test_r_register_high_bit_comes_from_flags1():
    machine = Machine(_rom())
    data = bytes(_header(pc=0x8000, flags1=0x01)) + bytes(3 * 0x4000)  # bit 0 = R bit 7
    z80.load_z80(machine, data)
    assert machine.cpu.regs.r == 0x7E | 0x80


def test_flags1_of_255_is_read_as_1():
    """A documented quirk of old files: 255 in that byte means 1."""
    machine = Machine(_rom())
    data = bytes(_header(pc=0x8000, flags1=255)) + bytes(3 * 0x4000)
    z80.load_z80(machine, data)
    assert machine.cpu.regs.r == 0x7E | 0x80  # bit 0 of the corrected value
    assert machine.ula.border_color == 0      # not 7, as a raw 255 would have given


# --- v2 / v3 (paged) ----------------------------------------------------------

def _paged(*, extra_length: int, mode: int, pc: int, pages: dict[int, bytes],
           port_7ffd: int = 0x00, ay: bytes = b"") -> bytes:
    """Build a v2/v3 file: header with PC=0, extra header, then one block per page."""
    extra = bytearray(extra_length)
    extra[0], extra[1] = pc & 0xFF, pc >> 8
    extra[2] = mode
    extra[3] = port_7ffd
    for i, value in enumerate(ay):
        extra[7 + i] = value  # AY registers: extra-header offset 7 == file offset 39
    out = bytearray(_header(pc=0)) + bytes([extra_length & 0xFF, extra_length >> 8]) + extra
    for page, content in pages.items():
        out += bytes([0xFF, 0xFF, page]) + content  # 0xFFFF = stored uncompressed
    return bytes(out)


def test_v2_48k_pages_land_at_the_right_addresses():
    machine = Machine(_rom())
    pages = {8: bytes([0x11]) * 0x4000,   # 0x4000
             4: bytes([0x22]) * 0x4000,   # 0x8000
             5: bytes([0x33]) * 0x4000}   # 0xC000
    z80.load_z80(machine, _paged(extra_length=23, mode=0, pc=0x6543, pages=pages))

    assert machine.cpu.regs.pc == 0x6543
    assert machine.memory.read_byte(0x4000) == 0x11
    assert machine.memory.read_byte(0x8000) == 0x22
    assert machine.memory.read_byte(0xC000) == 0x33


def test_v3_128k_pages_are_ram_banks_and_paging_is_restored():
    machine = Machine128(*_roms_128())
    pages = {page: bytes([page]) * 0x4000 for page in range(3, 11)}  # banks 0..7
    data = _paged(extra_length=54, mode=4, pc=0x7000, pages=pages,
                  port_7ffd=0x07, ay=bytes(range(1, 17)))

    z80.load_z80(machine, data)

    assert machine.cpu.regs.pc == 0x7000
    for bank in range(8):
        assert machine.ram_banks[bank].data[0] == bank + 3
    assert machine.port_7ffd == 0x07          # bank 7 paged at 0xC000
    assert machine.memory.read_byte(0xC000) == 10  # page 10 == bank 7


def test_v3_restores_the_ay_registers():
    machine = Machine128(*_roms_128())
    pages = {page: bytes(0x4000) for page in range(3, 11)}
    values = bytes(range(16))
    data = _paged(extra_length=54, mode=4, pc=0x7000, pages=pages, ay=values)
    # The selected-register byte sits at file offset 38 = extra-header offset 5.
    data = bytearray(data)
    data[38] = 5
    z80.load_z80(machine, bytes(data))

    assert machine.ay._selected == 5  # the register the tune was mid-write to
    for reg in range(16):
        machine.ay.select_register(reg)
        assert machine.ay.read_selected() == values[reg]


def test_compressed_pages_are_expanded():
    machine = Machine(_rom())
    body = _rle(0x5A, 0x4000)
    data = bytearray(_header(pc=0)) + bytes([23, 0]) + bytearray(23)
    data[32], data[33] = 0x00, 0x80   # PC = 0x8000
    data[34] = 0                      # 48K
    data += bytes([len(body) & 0xFF, len(body) >> 8, 8]) + body

    z80.load_z80(machine, bytes(data))

    assert machine.memory.read_byte(0x4000) == 0x5A
    assert machine.memory.read_byte(0x7FFF) == 0x5A


# --- rejections ---------------------------------------------------------------

def test_128k_snapshot_needs_the_128k_machine():
    machine = Machine(_rom())
    pages = {page: bytes(0x4000) for page in range(3, 11)}
    with pytest.raises(NotImplementedError):
        z80.load_z80(machine, _paged(extra_length=54, mode=4, pc=0x7000, pages=pages))


def test_48k_snapshot_is_refused_by_the_128k_machine():
    machine = Machine128(*_roms_128())
    with pytest.raises(ValueError):
        z80.load_z80(machine, bytes(_header(pc=0x8000)) + bytes(3 * 0x4000))


def test_samram_and_unknown_hardware_are_named_not_guessed():
    machine = Machine(_rom())
    pages = {8: bytes(0x4000)}
    with pytest.raises(ValueError, match="SamRam"):
        z80.load_z80(machine, _paged(extra_length=23, mode=2, pc=0x8000, pages=pages))
    with pytest.raises(ValueError, match="hardware mode"):
        z80.load_z80(machine, _paged(extra_length=23, mode=99, pc=0x8000, pages=pages))


def test_junk_is_rejected():
    machine = Machine(_rom())
    with pytest.raises(ValueError):
        z80.load_z80(machine, b"nope")
    with pytest.raises(ValueError, match="extra header"):
        machine2 = Machine(_rom())
        z80.load_z80(machine2, bytes(_header(pc=0)) + bytes([99, 0]) + bytes(99))
