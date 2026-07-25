"""The real 48K ROM loading a real tape from nothing but pulses.

Every other tape test checks a piece: that the right pulse lengths come out, that the
level flips when it should, that bit 6 carries it. None of them can tell you the thing
that actually matters, because the only judge of a tape signal is a loader -- and the
loader is 150 bytes of somebody else's Z80 in the ROM, timing edges against counters
that were tuned for a cassette deck in 1982.

So this test hands the job to that code. No trap, no shortcut: fast loading is switched
off, ``LD-BYTES`` is called the way BASIC calls it, and the ROM is left to sample port
0xFE until it either decodes the block or gives up. If any of the pilot length, the
sync pair, the bit timings, the byte order or the parity byte were wrong, it gives up.

It costs a couple of seconds, and that is not overhead -- it is the feature. Loading at
real tape speed is what edge replay *is*, and 16 bytes taking two seconds is the same
two seconds they took on a Spectrum.
"""

from __future__ import annotations

import importlib.resources as res

from zxemu_core.machine import Machine
from zxemu_core.storage import tape

LD_BYTES_ENTRY = 0x0556
# Generous: the loader needs ~1s of leader before it will even look for the sync, and
# the block itself then plays in real time. A working load lands near 105.
FRAME_BUDGET = 400


def _rom() -> bytes:
    return (res.files("zxemu_core") / "roms" / "48.rom").read_bytes()


def _block(flag: int, payload: bytes) -> bytes:
    body = bytes([flag]) + bytes(payload)
    checksum = 0
    for byte in body:
        checksum ^= byte
    return body + bytes([checksum])


def _tap(*blocks: bytes) -> bytes:
    return b"".join(bytes([len(b) & 0xFF, len(b) >> 8]) + b for b in blocks)


def _call_ld_bytes(machine, *, flag: int, length: int, address: int) -> None:
    """Set up the call exactly as BASIC's LOAD does, at the routine's real entry point.

    IX/DE say where and how much; A and the carry say *what* -- which block flag is
    wanted, and whether this is a LOAD or a VERIFY. They go in the main AF because the
    routine's own preamble is what moves them to the shadow set.
    """
    regs = machine.cpu.regs
    regs.pc = LD_BYTES_ENTRY
    regs.ix = address
    regs.de = length
    regs.a = flag
    regs.f |= 0x01          # carry set = LOAD (reset would be VERIFY)
    regs.sp = 0x7FF0
    machine.memory.write_word(regs.sp, 0xFFFF)  # a return address we can recognise


def _run_until_the_loader_returns(machine) -> int:
    """Frames until PC leaves the loader, or the budget. Stopping *at* the return is the
    point: past it the CPU runs whatever 0xFFFF happens to hold and will scribble over
    the very buffer we are about to check."""
    regs = machine.cpu.regs
    for frame in range(FRAME_BUDGET):
        machine.run_frame()
        if not 0x0500 <= regs.pc <= 0x0600:
            return frame
    return FRAME_BUDGET


def test_the_rom_loads_a_block_from_pulses_with_fast_load_off():
    payload = bytes(range(16))
    machine = Machine(_rom())
    machine.fast_load_enabled = False        # no trap: the ROM must do the work itself
    machine.insert_tape(tape.TapeDeck(tape.parse_tap(_tap(_block(tape.FLAG_DATA, payload)))))
    _call_ld_bytes(machine, flag=tape.FLAG_DATA, length=len(payload), address=0x8000)

    frames = _run_until_the_loader_returns(machine)

    assert frames < FRAME_BUDGET, "the loader never returned -- it never found the block"
    assert machine.cpu.regs.f & 0x01, "the ROM reported a load error (bad parity or timing)"
    loaded = bytes(machine.memory.read_byte(0x8000 + i) for i in range(len(payload)))
    assert loaded == payload
    # The motor ran itself: nothing in this test ever pressed Play. The player saw the
    # machine sampling port 0xFE and started the tape (see pulse.py). It is still
    # running here, part-way through the pause that follows the block.
    assert machine.tape_player.motor


def test_fast_load_and_edge_replay_agree_on_the_bytes():
    """Two completely different routes to the same 16 bytes: one fakes the ROM's result,
    the other makes the ROM earn it. They are only interchangeable if they agree."""
    payload = bytes(range(16))
    image = _tap(_block(tape.FLAG_DATA, payload))

    fast = Machine(_rom())
    fast.insert_tape(tape.TapeDeck(tape.parse_tap(image)))
    _call_ld_bytes(fast, flag=tape.FLAG_DATA, length=len(payload), address=0x8000)
    for _ in range(20):                      # the trap resolves it within a few steps
        fast.cpu.step()

    slow = Machine(_rom())
    slow.fast_load_enabled = False
    slow.insert_tape(tape.TapeDeck(tape.parse_tap(image)))
    _call_ld_bytes(slow, flag=tape.FLAG_DATA, length=len(payload), address=0x8000)
    _run_until_the_loader_returns(slow)

    got_fast = bytes(fast.memory.read_byte(0x8000 + i) for i in range(len(payload)))
    got_slow = bytes(slow.memory.read_byte(0x8000 + i) for i in range(len(payload)))
    assert got_fast == got_slow == payload
