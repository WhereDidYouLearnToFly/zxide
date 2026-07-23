"""Boots the real bundled 48K ROM and checks it reaches BASIC's idle main loop.

Expected values below were captured from an observed-correct run (see dev
notes) and cross-checked against well-known real-hardware 48K boot behavior:
PC parks at 0x11DC during the ROM's RAM-check delay loop (waiting on the
once-per-frame interrupt), screen memory gets transient "noise" from the RAM
check scanning over the display file (a well-known real-hardware visual
artifact), that noise clears, and execution settles into the idle loop the ROM
runs once the copyright screen has been printed and BASIC is waiting for input.

That idle state alternates between the main editor loop (MAIN-EXEC, ~0x10AC)
and the keyboard-scan wait (WAIT-KEY / KEY-SCAN, ~0x15DE-0x162C). *Which*
instruction of those loops a frame boundary happens to land on is a function of
exact T-state pacing, so this test asserts the region and that execution stays
looping there -- not one pinned address. (It previously pinned 0x15DE/0x162C,
which broke when run_frame stopped overrunning each frame by a few T-states.)
"""

import importlib.resources as res

from zxemu_core.machine import Machine

# (start, end) address ranges of the two ROM loops that make up the BASIC idle state.
IDLE_LOOP_REGIONS = ((0x10A0, 0x10C0), (0x15D0, 0x1640))
KEYBOARD_SCAN_REGION = IDLE_LOOP_REGIONS[1]
FRAMES_TO_REACH_STABLE_LOOP = 110
FRAMES_TO_CONFIRM_STABLE = 40


def _load_48_rom_bytes() -> bytes:
    return (res.files("zxemu_core") / "roms" / "48.rom").read_bytes()


def _screen_nonzero_byte_count(machine: Machine) -> int:
    return sum(1 for addr in range(0x4000, 0x5B00) if machine.memory.read_byte(addr) != 0)


def _in_idle_loop(pc: int) -> bool:
    return any(start <= pc < end for start, end in IDLE_LOOP_REGIONS)


def test_boot_reaches_stable_keyboard_scan_loop():
    machine = Machine(_load_48_rom_bytes())

    for _ in range(FRAMES_TO_REACH_STABLE_LOOP):
        machine.run_frame()  # raises if any opcode the ROM hits isn't implemented

    assert _in_idle_loop(machine.cpu.regs.pc), f"PC 0x{machine.cpu.regs.pc:04X} not idling"

    # Confirm it's genuinely looping there -- not passing through, and not parked on a
    # single instruction (which would mean it had wedged rather than settled).
    seen_pcs = set()
    for _ in range(FRAMES_TO_CONFIRM_STABLE):
        machine.run_frame()
        pc = machine.cpu.regs.pc
        assert _in_idle_loop(pc), f"left the idle loop at 0x{pc:04X}"
        seen_pcs.add(pc)
    assert 1 < len(seen_pcs) <= 16  # a tight loop, sampled at different points
    start, end = KEYBOARD_SCAN_REGION
    assert any(start <= pc < end for pc in seen_pcs)  # really waiting on the keyboard

    assert _screen_nonzero_byte_count(machine) == 902
