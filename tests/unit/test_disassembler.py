"""Unit tests for the Z80 disassembler, covering each prefix group."""

from zxemu_core.debug import disassembler


class Mem:
    """A flat 64K memory holding the test bytes at a chosen address."""

    def __init__(self, data: bytes, address: int = 0x8000):
        self.ram = bytearray(0x10000)
        self.ram[address:address + len(data)] = data

    def read_byte(self, addr: int) -> int:
        return self.ram[addr & 0xFFFF]


def dis(data: bytes, address: int = 0x8000):
    return disassembler.disassemble_one(Mem(data, address), address)


# (bytes, expected text, expected length) across all groups.
CASES = [
    (b"\x00", "nop", 1),
    (b"\x76", "halt", 1),
    (b"\x3e\x05", "ld a,$05", 2),
    (b"\x06\xff", "ld b,$FF", 2),
    (b"\x21\x00\x40", "ld hl,$4000", 3),
    (b"\x22\x00\x5c", "ld ($5C00),hl", 3),
    (b"\x2a\x00\x5c", "ld hl,($5C00)", 3),
    (b"\x40", "ld b,b", 1),
    (b"\x7e", "ld a,(hl)", 1),
    (b"\x80", "add a,b", 1),
    (b"\xb8", "cp b", 1),
    (b"\xc6\x10", "add a,$10", 2),
    (b"\xc3\x00\x80", "jp $8000", 3),
    (b"\xff", "rst $38", 1),
    (b"\xcb\x47", "bit 0,a", 2),        # CB group
    (b"\xcb\x06", "rlc (hl)", 2),
    (b"\xed\xb0", "ldir", 2),           # ED group
    (b"\xed\x43\x00\x40", "ld ($4000),bc", 4),
    (b"\xed\x4a", "adc hl,bc", 2),
    (b"\xed\x46", "im 0", 2),
    (b"\xdd\x21\x00\x40", "ld ix,$4000", 4),   # DD group
    (b"\xdd\x7e\x05", "ld a,(ix+$05)", 3),
    (b"\xdd\x36\x02\xff", "ld (ix+$02),$FF", 4),
    (b"\xdd\x29", "add ix,ix", 2),
    (b"\xdd\xcb\x02\x06", "rlc (ix+$02)", 4),   # DDCB group
    (b"\xdd\xcb\x02\x00", "rlc (ix+$02),b", 4),  # undocumented store form
    (b"\xfd\x7e\xfe", "ld a,(iy-$02)", 3),      # FD + negative displacement
]


def test_opcode_decoding():
    for data, expected, length in CASES:
        text, size = dis(data)
        assert (text, size) == (expected, length), f"{data.hex()} -> {text!r} ({size})"


def test_relative_jump_targets_are_absolute():
    # JR $-2 at 0x8000 loops to itself (target = next-instruction addr + offset).
    text, length = dis(b"\x18\xfe", 0x8000)
    assert (text, length) == ("jr $8000", 2)
    # JR forward.
    text, _ = dis(b"\x18\x0e", 0x8000)
    assert text == "jr $8010"


def test_disassemble_sequence_advances_by_length():
    # ld a,$05 ; nop ; jp $8000
    mem = Mem(b"\x3e\x05\x00\xc3\x00\x80", 0x8000)
    listing = disassembler.disassemble(mem, 0x8000, 3)
    addresses = [addr for addr, _, _ in listing]
    texts = [text for _, _, text in listing]
    assert addresses == [0x8000, 0x8002, 0x8003]
    assert texts == ["ld a,$05", "nop", "jp $8000"]
