"""Boots the real bundled 48K ROM and checks it reaches BASIC's idle main loop.

Expected values below were captured from an observed-correct run (see dev
notes) and cross-checked against well-known real-hardware 48K boot behavior:
PC parks at 0x11DC during the ROM's RAM-check delay loop (waiting on the
once-per-frame interrupt), screen memory gets transient "noise" from the RAM
check scanning over the display file (a well-known real-hardware visual
artifact), that noise clears, and execution settles into oscillating between
0x15DE/0x162C -- the keyboard-scan idle loop entered once the copyright
screen has been printed and BASIC is waiting for input.
"""

import importlib.resources as res

from zxemu_core.machine import Machine

STABLE_LOOP_ADDRESSES = {0x15DE, 0x162C}
FRAMES_TO_REACH_STABLE_LOOP = 110


def _load_48_rom_bytes() -> bytes:
    return (res.files("zxemu_core") / "roms" / "48.rom").read_bytes()


def _screen_nonzero_byte_count(machine: Machine) -> int:
    return sum(1 for addr in range(0x4000, 0x5B00) if machine.memory.read_byte(addr) != 0)


def test_boot_reaches_stable_keyboard_scan_loop():
    machine = Machine(_load_48_rom_bytes())

    for _ in range(FRAMES_TO_REACH_STABLE_LOOP):
        machine.run_frame()  # raises if any opcode the ROM hits isn't implemented

    assert machine.cpu.regs.pc in STABLE_LOOP_ADDRESSES
    # confirm it's genuinely oscillating in the loop, not coincidentally parked
    seen_pcs = set()
    for _ in range(4):
        machine.run_frame()
        seen_pcs.add(machine.cpu.regs.pc)
    assert seen_pcs == STABLE_LOOP_ADDRESSES

    assert _screen_nonzero_byte_count(machine) == 902
