"""Unit tests for .tap parsing and the fast (ROM-trap) tape loader."""

import importlib.resources as res

import pytest

from zxemu_core.storage import tape
from zxemu_core.cpu.registers import FLAG_C
from zxemu_core.machine import TAPE_TRAP_TSTATES, Machine, Machine128


def _rom() -> bytes:
    return (res.files("zxemu_core") / "roms" / "48.rom").read_bytes()


def _roms_128() -> tuple[bytes, bytes]:
    folder = res.files("zxemu_core") / "roms"
    return (folder / "128-0.rom").read_bytes(), (folder / "128-1.rom").read_bytes()


def _block(flag: int, payload: bytes) -> bytes:
    """A standard tape block: flag + payload + the XOR checksum that zeroes the whole."""
    body = bytes([flag]) + bytes(payload)
    checksum = 0
    for byte in body:
        checksum ^= byte
    return body + bytes([checksum])


def _tap(*blocks: bytes) -> bytes:
    """Wrap raw block bytes into .tap file form (each prefixed with its 2-byte length)."""
    out = bytearray()
    for block in blocks:
        out += bytes([len(block) & 0xFF, (len(block) >> 8) & 0xFF]) + block
    return bytes(out)


def _code_header(name: str, length: int, start: int) -> bytes:
    """The 17 data bytes of a standard 'Code' (type 3) header."""
    padded = name.encode("ascii")[:10].ljust(10)
    return bytes([3]) + padded + bytes([
        length & 0xFF, (length >> 8) & 0xFF,
        start & 0xFF, (start >> 8) & 0xFF,
        0x00, 0x80,  # unused second parameter
    ])


# --- parsing ------------------------------------------------------------------

def test_parse_tap_splits_blocks():
    data = _tap(_block(tape.FLAG_HEADER, _code_header("prog", 3, 0x8000)),
                _block(tape.FLAG_DATA, bytes([1, 2, 3])))
    blocks = tape.parse_tap(data)
    assert len(blocks) == 2
    assert blocks[0].flag == tape.FLAG_HEADER and blocks[0].is_header
    assert blocks[1].flag == tape.FLAG_DATA
    assert len(blocks[1].data) == 5  # flag + 3 data + checksum


def test_parse_tap_rejects_empty_or_junk():
    with pytest.raises(ValueError):
        tape.parse_tap(b"")
    with pytest.raises(ValueError):
        tape.parse_tap(b"\x00")  # a lone length byte -- no complete block


def test_parse_tap_stops_at_truncated_final_block():
    truncated = _tap(_block(tape.FLAG_DATA, bytes([9]))) + b"\x40\x00\x01\x02"  # claims 0x40 bytes, only 2 follow
    blocks = tape.parse_tap(truncated)
    assert len(blocks) == 1  # the intact block survives; the truncated tail is dropped


def test_header_describe_decodes_name_and_length():
    header = tape.TapeBlock(_block(tape.FLAG_HEADER, _code_header("hello", 6912, 0x4000)))
    text = header.describe()
    assert "hello" in text and "Code" in text and "6912" in text


# --- the deck -----------------------------------------------------------------

def test_deck_advances_and_ends():
    deck = tape.TapeDeck(tape.parse_tap(_tap(_block(0xFF, b"\x01"), _block(0xFF, b"\x02"))))
    assert not deck.at_end and deck.current().data[1] == 0x01
    deck.advance()
    assert deck.current().data[1] == 0x02
    deck.advance()
    assert deck.at_end and deck.current() is None
    deck.rewind()
    assert deck.index == 0 and not deck.at_end


# --- fast_load ----------------------------------------------------------------

def _prime_load(machine, *, flag: int, length: int, address: int, verify: bool = False):
    """Set the registers as the ROM does when it CALLs LD-BYTES."""
    regs = machine.cpu.regs
    regs.a = flag
    regs.de = length
    regs.ix = address
    if verify:
        regs.f &= ~FLAG_C & 0xFF
    else:
        regs.f |= FLAG_C


def test_fast_load_copies_block_and_sets_success():
    machine = Machine(_rom())
    payload = bytes([0xDE, 0xAD, 0xBE, 0xEF])
    deck = tape.TapeDeck(tape.parse_tap(_tap(_block(tape.FLAG_DATA, payload))))
    machine.insert_tape(deck)

    _prime_load(machine, flag=tape.FLAG_DATA, length=len(payload), address=0xC000)
    handled = tape.fast_load(machine, deck)

    assert handled is True
    assert bytes(machine.memory.read_byte(0xC000 + i) for i in range(4)) == payload
    assert machine.cpu.regs.f & FLAG_C  # carry set = load succeeded
    assert machine.cpu.regs.de == 0 and machine.cpu.regs.ix == 0xC004
    assert deck.at_end  # the single block was consumed


def test_fast_load_flag_mismatch_fails_without_advancing():
    machine = Machine(_rom())
    deck = tape.TapeDeck(tape.parse_tap(_tap(_block(tape.FLAG_DATA, bytes([1, 2, 3])))))
    machine.insert_tape(deck)

    _prime_load(machine, flag=tape.FLAG_HEADER, length=3, address=0xC000)  # wants a header
    tape.fast_load(machine, deck)

    assert not (machine.cpu.regs.f & FLAG_C)  # carry reset = failure
    assert deck.index == 0  # head not advanced -- the block wasn't what was asked for


def test_fast_load_bad_checksum_fails():
    machine = Machine(_rom())
    corrupt = bytearray(_block(tape.FLAG_DATA, bytes([1, 2, 3])))
    corrupt[-1] ^= 0xFF  # wreck the checksum byte
    deck = tape.TapeDeck(tape.parse_tap(_tap(bytes(corrupt))))
    machine.insert_tape(deck)

    _prime_load(machine, flag=tape.FLAG_DATA, length=3, address=0xC000)
    tape.fast_load(machine, deck)

    assert not (machine.cpu.regs.f & FLAG_C)  # parity != 0 -> failure


def test_fast_load_verify_matches_memory():
    machine = Machine(_rom())
    payload = bytes([7, 8, 9])
    for i, byte in enumerate(payload):
        machine.memory.write_byte(0xC000 + i, byte)  # memory already holds the tape's data
    deck = tape.TapeDeck(tape.parse_tap(_tap(_block(tape.FLAG_DATA, payload))))
    machine.insert_tape(deck)

    _prime_load(machine, flag=tape.FLAG_DATA, length=3, address=0xC000, verify=True)
    tape.fast_load(machine, deck)

    assert machine.cpu.regs.f & FLAG_C  # verify passed


# --- the CPU trap -------------------------------------------------------------

def test_ld_bytes_trap_loads_a_block_and_returns():
    machine = Machine(_rom())
    payload = bytes([0x11, 0x22, 0x33])
    machine.insert_tape(tape.TapeDeck(tape.parse_tap(_tap(_block(tape.FLAG_DATA, payload)))))

    regs = machine.cpu.regs
    regs.sp = 0x8000
    machine.memory.write_word(0x8000, 0x9000)  # the RET address the ROM would have pushed
    regs.pc = tape.LD_BYTES_ENTRY
    _prime_load(machine, flag=tape.FLAG_DATA, length=3, address=0xC000)

    billed = machine.cpu.step()

    assert billed == TAPE_TRAP_TSTATES
    assert regs.pc == 0x9000 and regs.sp == 0x8002  # the trap performed the RET
    assert bytes(machine.memory.read_byte(0xC000 + i) for i in range(3)) == payload
    assert regs.iff1 and regs.iff2  # interrupts re-enabled, as LD-BYTES does


def test_trap_declines_when_fast_load_disabled():
    machine = Machine(_rom())
    machine.insert_tape(tape.TapeDeck(tape.parse_tap(_tap(_block(tape.FLAG_DATA, b"\x01")))))
    machine.fast_load_enabled = False

    machine.cpu.regs.pc = tape.LD_BYTES_ENTRY
    machine.cpu.regs.d = 0
    machine.cpu.step()

    # The real instruction at 0x0556 is INC D, so it ran normally instead of trapping.
    assert machine.cpu.regs.pc == tape.LD_BYTES_ENTRY + 1
    assert machine.cpu.regs.d == 1


def test_trap_declines_without_a_tape():
    machine = Machine(_rom())  # no tape inserted
    machine.cpu.regs.pc = tape.LD_BYTES_ENTRY
    machine.cpu.regs.d = 0
    machine.cpu.step()
    assert machine.cpu.regs.pc == tape.LD_BYTES_ENTRY + 1  # INC D ran; no trap


# --- 128K: the trap must follow which ROM is paged ----------------------------

def test_trap_fires_on_128k_only_with_48basic_rom_paged():
    machine = Machine128(*_roms_128())
    payload = bytes([0xA1, 0xB2, 0xC3])
    machine.insert_tape(tape.TapeDeck(tape.parse_tap(_tap(_block(tape.FLAG_DATA, payload)))))
    regs = machine.cpu.regs

    # ROM0 (the 128 menu) paged: 0x0556 is not LD-BYTES, so the trap must decline and
    # leave the tape untouched -- we never want to fast-load inside the menu ROM.
    machine.set_paging(0x00, force=True)  # ROM0 in slot 0, RAM0 in slot 3 (0xC000)
    regs.pc = tape.LD_BYTES_ENTRY
    _prime_load(machine, flag=tape.FLAG_DATA, length=3, address=0xC000)
    machine.cpu.step()
    assert machine.tape.index == 0  # head not advanced -- no fast-load happened

    # ROM1 (48 BASIC) paged: 0x0556 *is* LD-BYTES, so the trap fires and loads.
    machine.set_paging(0x10, force=True)  # ROM1 in slot 0 (bit 4), RAM0 in slot 3
    regs.sp = 0xC800
    machine.memory.write_word(0xC800, 0x9000)
    regs.pc = tape.LD_BYTES_ENTRY
    _prime_load(machine, flag=tape.FLAG_DATA, length=3, address=0xC000)
    billed = machine.cpu.step()
    assert billed == TAPE_TRAP_TSTATES
    assert bytes(machine.memory.read_byte(0xC000 + i) for i in range(3)) == payload
    assert machine.tape.at_end
