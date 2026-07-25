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


def test_the_head_winds_past_items_a_fast_load_cannot_serve():
    """A .tzx can put a bare pilot tone between blocks. Fast loading has nothing to do
    with one, and stopping on it would park the head for ever -- a real cassette runs
    unusable signal past the head rather than stopping at it."""
    from zxemu_core.storage.pulse import PureTone

    blocks = tape.parse_tap(_tap(_block(0xFF, b"\x01")))
    deck = tape.TapeDeck([PureTone(2168, 100), PureTone(2168, 100), blocks[0]])

    assert deck.current() is blocks[0]
    assert deck.index == 2          # the head moved over both tones to get there


def test_data_blocks_counts_only_what_can_be_loaded():
    from zxemu_core.storage.pulse import PureTone, Silence

    blocks = tape.parse_tap(_tap(_block(0xFF, b"\x01"), _block(0x00, b"\x02")))
    items = [PureTone(2168, 10), blocks[0], Silence(500), blocks[1]]

    assert tape.data_blocks(items) == blocks


def test_a_tap_block_is_played_with_the_roms_own_timings():
    """Nothing in a .tap says how fast it was recorded, because there is only one answer:
    the speed the ROM's own SAVE routine writes at."""
    from zxemu_core.storage.pulse import PILOT_PULSE, ROM_TIMING

    block = tape.parse_tap(_tap(_block(0xFF, b"\x01")))[0]

    assert block.timing == ROM_TIMING
    assert next(iter(block.pulses())) == PILOT_PULSE


# --- fast_load ----------------------------------------------------------------

def _prime_load(machine, *, flag: int, length: int, address: int, verify: bool = False):
    """Set the registers as they stand at the trap address (0x0562).

    The wanted flag byte and the LOAD/VERIFY carry live in the **shadow** AF there: the
    routine's preamble moved them with ``ex af,af'`` before the trap point, and a loader
    that calls 0x0562 directly has to do the same.
    """
    regs = machine.cpu.regs
    regs.a2 = flag
    regs.de = length
    regs.ix = address
    if verify:
        regs.f2 &= ~FLAG_C & 0xFF
    else:
        regs.f2 |= FLAG_C


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


def test_fast_load_flag_mismatch_fails_but_the_tape_still_moves_on():
    """A rejected block is still a block that played: the head advances, as a real
    cassette would. Parking it there instead livelocks the ROM, which simply asks
    again -- that is how LOAD "" searches for a header past unwanted blocks."""
    machine = Machine(_rom())
    deck = tape.TapeDeck(tape.parse_tap(_tap(_block(tape.FLAG_DATA, bytes([1, 2, 3])))))
    machine.insert_tape(deck)

    _prime_load(machine, flag=tape.FLAG_HEADER, length=3, address=0xC000)  # wants a header
    tape.fast_load(machine, deck)

    assert not (machine.cpu.regs.f & FLAG_C)  # carry reset = failure
    assert deck.index == 1


def test_load_searches_past_unwanted_blocks_for_the_header_it_wants():
    """The 1942 case: the program being loaded isn't the first thing on the tape."""
    machine = Machine(_rom())
    wanted = _code_header("game", 3, 0x8000)
    deck = tape.TapeDeck(tape.parse_tap(_tap(
        _block(tape.FLAG_DATA, bytes([9, 9])),      # somebody else's data block
        _block(tape.FLAG_DATA, bytes([8, 8, 8])),   # and another
        _block(tape.FLAG_HEADER, wanted),           # the header LOAD is looking for
    )))
    machine.insert_tape(deck)

    for _ in range(3):  # the ROM re-reads until a header turns up
        _prime_load(machine, flag=tape.FLAG_HEADER, length=17, address=0xC000)
        tape.fast_load(machine, deck)

    assert machine.cpu.regs.f & FLAG_C  # the third read succeeded
    assert bytes(machine.memory.read_byte(0xC000 + i) for i in range(17)) == wanted


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


# --- edge replay, as the machine wires it up ----------------------------------

def test_inserting_a_tape_creates_a_player_and_ejecting_clears_the_wire():
    machine = Machine(_rom())
    machine.insert_tape(tape.TapeDeck(tape.parse_tap(_tap(_block(0xFF, b"\x01")))))
    assert machine.tape_player is not None

    machine.eject_tape()

    assert machine.tape_player is None
    assert machine.ula.ear_level == 1  # back to the idle read, not stuck wherever it was


def test_reading_port_0xfe_puts_the_tape_signal_on_bit_6():
    machine = Machine(_rom())
    machine.insert_tape(tape.TapeDeck(tape.parse_tap(_tap(_block(0xFF, b"\x01")))))
    machine.tape_player.start()

    first = machine._io_read(0x7FFE)
    # Half a pilot pulse later the level has not flipped yet; a whole one later it has.
    machine.frame_t_state = 1000
    assert (machine._io_read(0x7FFE) & 0x40) == (first & 0x40)
    machine.frame_t_state = 2200
    assert (machine._io_read(0x7FFE) & 0x40) != (first & 0x40)


def test_a_tape_with_no_player_leaves_port_reads_exactly_as_they_were():
    """The common case is no tape at all, and it must cost nothing and change nothing."""
    machine = Machine(_rom())
    assert machine._io_read(0x7FFE) == 0xFF


def test_the_tape_clock_keeps_running_across_frame_boundaries():
    """A pilot pulse is a fortieth of a frame but a pause is fifty of them, so the
    player cannot be measured against a clock that restarts every 20ms."""
    machine = Machine(_rom())
    machine.run_frame()
    after_one = machine.tape_tstate
    machine.run_frame()

    assert after_one >= machine.frame_tstates
    assert machine.tape_tstate - after_one == pytest.approx(machine.frame_tstates, abs=64)


def test_the_tape_signal_reaches_the_speaker_so_loading_is_audible():
    """On real hardware EAR is summed into the same amplifier as the beeper -- that is
    the loading screech. Silence during a load would be the wrong kind of authentic."""
    machine = Machine(_rom())
    machine.beeper.enabled = True
    machine.insert_tape(tape.TapeDeck(tape.parse_tap(_tap(_block(0xFF, b"\x01")))))
    machine.tape_player.start()

    for t in range(0, 20000, 500):     # sample across a few pilot pulses
        machine.frame_t_state = t
        machine._io_read(0x7FFE)

    assert machine.beeper._edges, "the tape produced no speaker activity"

    # Muting the tape settles the speaker once and then stays quiet, rather than
    # continuing to follow the signal at zero volume.
    machine.tape_audible = False
    machine._io_read(0x7FFE)
    machine.beeper._edges.clear()
    for t in range(20000, 40000, 500):
        machine.frame_t_state = t
        machine._io_read(0x7FFE)
    assert not machine.beeper._edges


def test_the_128k_reads_the_tape_too():
    """Its IO decode is overridden for the AY and paging, and it would be easy to answer
    the ULA directly there and silently leave the 128 with no tape input."""
    machine = Machine128(*_roms_128())
    machine.insert_tape(tape.TapeDeck(tape.parse_tap(_tap(_block(0xFF, b"\x01")))))
    machine.tape_player.start()

    machine._io_read(0x7FFE)
    machine.frame_t_state = 2200
    machine._io_read(0x7FFE)

    assert machine.tape_player.motor  # it rolled, rather than being ignored


# --- the CPU trap -------------------------------------------------------------

def test_ld_bytes_trap_loads_a_block_and_returns():
    machine = Machine(_rom())
    payload = bytes([0x11, 0x22, 0x33])
    machine.insert_tape(tape.TapeDeck(tape.parse_tap(_tap(_block(tape.FLAG_DATA, payload)))))

    regs = machine.cpu.regs
    regs.sp = 0x8000
    machine.memory.write_word(0x8000, 0x9000)  # the RET address the ROM would have pushed
    regs.pc = tape.LD_BYTES_TRAP
    _prime_load(machine, flag=tape.FLAG_DATA, length=3, address=0xC000)

    billed = machine.cpu.step()

    assert billed == TAPE_TRAP_TSTATES
    assert regs.pc == 0x9000 and regs.sp == 0x8002  # the trap performed the RET
    assert bytes(machine.memory.read_byte(0xC000 + i) for i in range(3)) == payload


def test_trap_leaves_the_interrupt_state_alone():
    """The caller owns interrupts: BASIC returns via SA/LD-RET (which does the EI), and a
    loader that called 0x0562 itself disabled them deliberately."""
    machine = Machine(_rom())
    machine.insert_tape(tape.TapeDeck(tape.parse_tap(_tap(_block(tape.FLAG_DATA, b"\x01")))))

    regs = machine.cpu.regs
    regs.sp = 0x8000
    machine.memory.write_word(0x8000, 0x9000)
    regs.pc = tape.LD_BYTES_TRAP
    regs.iff1 = regs.iff2 = False  # as the routine's own DI (or the loader's) left them
    _prime_load(machine, flag=tape.FLAG_DATA, length=1, address=0xC000)

    machine.cpu.step()

    assert not regs.iff1 and not regs.iff2


def test_basic_style_entry_at_0x0556_still_loads_through_the_preamble():
    """Entering the routine normally must still fast-load: the preamble runs (moving the
    flag into AF' itself) and falls through to the trap a few instructions later."""
    machine = Machine(_rom())
    payload = bytes([0xAA, 0xBB])
    machine.insert_tape(tape.TapeDeck(tape.parse_tap(_tap(_block(tape.FLAG_DATA, payload)))))

    regs = machine.cpu.regs
    regs.sp = 0x8000
    machine.memory.write_word(0x8000, 0x9000)  # what BASIC's CALL pushed
    regs.pc = tape.LD_BYTES_ENTRY
    regs.a = tape.FLAG_DATA   # at 0x0556 the request is in the MAIN AF...
    regs.f |= FLAG_C          # ...and ex af,af' in the preamble moves it to the shadow
    regs.de = len(payload)
    regs.ix = 0xC000

    for _ in range(12):  # preamble (8 instructions) then the trap
        machine.cpu.step()
        if machine.tape.at_end:
            break

    assert machine.tape.at_end  # the block was consumed
    assert bytes(machine.memory.read_byte(0xC000 + i) for i in range(2)) == payload
    # The trap RETs to SA/LD-RET (0x053F), pushed by the preamble -- not straight to BASIC.
    assert regs.pc == 0x053F


def test_a_game_loader_calling_0x0562_directly_is_intercepted():
    """The regression this trap address exists for.

    Multi-part 128K loaders commonly do the LD-BYTES preamble themselves and ``CALL``
    straight to the sampling entry. With the trap on 0x0556 those calls were never
    intercepted, and the game sat in the ROM's edge-sampling loop forever waiting for
    pulses fast loading doesn't produce -- which is what Aliens: Neoplasma II did.
    """
    machine = Machine128(*_roms_128())
    payload = bytes([0x5A, 0x6B, 0x7C, 0x8D])
    machine.insert_tape(tape.TapeDeck(tape.parse_tap(_tap(_block(tape.FLAG_DATA, payload)))))
    machine.set_paging(0x10, force=True)  # 48-BASIC ROM paged in, as such a loader arranges

    # A loader in RAM: CALL $0562, then HALT.
    for offset, byte in enumerate([0xCD, 0x62, 0x05, 0x76]):
        machine.memory.write_byte(0x8000 + offset, byte)
    regs = machine.cpu.regs
    regs.pc = 0x8000
    regs.sp = 0xC800
    regs.iff1 = regs.iff2 = False  # it DI'd, as these loaders do
    _prime_load(machine, flag=tape.FLAG_DATA, length=len(payload), address=0xC000)

    machine.cpu.step()  # the CALL
    machine.cpu.step()  # lands on 0x0562 -> trap

    assert machine.tape.at_end  # the block was consumed
    assert bytes(machine.memory.read_byte(0xC000 + i) for i in range(4)) == payload
    assert regs.pc == 0x8003 and regs.f & FLAG_C  # returned to the loader, carry = success
    assert not regs.iff1  # its own interrupt state survived


def test_trap_declines_when_fast_load_disabled():
    machine = Machine(_rom())
    machine.insert_tape(tape.TapeDeck(tape.parse_tap(_tap(_block(tape.FLAG_DATA, b"\x01")))))
    machine.fast_load_enabled = False

    machine.cpu.regs.pc = tape.LD_BYTES_TRAP
    machine.cpu.step()

    # The real instruction at 0x0562 is IN A,($FE) -- two bytes -- so it ran for real.
    assert machine.cpu.regs.pc == tape.LD_BYTES_TRAP + 2
    assert machine.tape.index == 0


def test_trap_declines_without_a_tape():
    machine = Machine(_rom())  # no tape inserted
    machine.cpu.regs.pc = tape.LD_BYTES_TRAP
    machine.cpu.step()
    assert machine.cpu.regs.pc == tape.LD_BYTES_TRAP + 2  # IN A,($FE) ran; no trap


# --- 128K: the trap must follow which ROM is paged ----------------------------

def test_trap_fires_on_128k_only_with_48basic_rom_paged():
    machine = Machine128(*_roms_128())
    payload = bytes([0xA1, 0xB2, 0xC3])
    machine.insert_tape(tape.TapeDeck(tape.parse_tap(_tap(_block(tape.FLAG_DATA, payload)))))
    regs = machine.cpu.regs

    # ROM0 (the 128 menu) paged: this isn't LD-BYTES, so the trap must decline and
    # leave the tape untouched -- we never want to fast-load inside the menu ROM.
    machine.set_paging(0x00, force=True)  # ROM0 in slot 0, RAM0 in slot 3 (0xC000)
    regs.pc = tape.LD_BYTES_TRAP
    _prime_load(machine, flag=tape.FLAG_DATA, length=3, address=0xC000)
    machine.cpu.step()
    assert machine.tape.index == 0  # head not advanced -- no fast-load happened

    # ROM1 (48 BASIC) paged: this *is* LD-BYTES, so the trap fires and loads.
    machine.set_paging(0x10, force=True)  # ROM1 in slot 0 (bit 4), RAM0 in slot 3
    regs.sp = 0xC800
    machine.memory.write_word(0xC800, 0x9000)
    regs.pc = tape.LD_BYTES_TRAP
    _prime_load(machine, flag=tape.FLAG_DATA, length=3, address=0xC000)
    billed = machine.cpu.step()
    assert billed == TAPE_TRAP_TSTATES
    assert bytes(machine.memory.read_byte(0xC000 + i) for i in range(3)) == payload
    assert machine.tape.at_end
