"""Harness to run the classic zexall/zexdoc Z80 exercisers against zxemu_core's CPU.

These are CP/M .com programs (loaded at 0x0100) that print pass/fail lines
via simulated BDOS calls -- function 2 (register C) prints the character in
E, function 9 prints a $-terminated string pointed to by DE -- and return
control to address 0x0000 when finished. This harness intercepts both by
watching PC before each instruction, rather than modeling real CP/M.

Place zexdoc.com / zexall.com in tests/zexall/fixtures/ before running (see
fixtures/README.md); files not present are skipped rather than failing.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from zxemu_core.cpu.z80 import Z80  # noqa: E402
from zxemu_core.memory import Bank, Memory  # noqa: E402

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
LOAD_ADDRESS = 0x0100
BDOS_ADDRESS = 0x0005
EXIT_ADDRESS = 0x0000


def make_flat_memory() -> Memory:
    """A full 64K of writable RAM -- CP/M .com programs expect flat memory, not the ROM/RAM split."""
    return Memory([Bank(), Bank(), Bank(), Bank()])


def _handle_bdos_call(cpu: Z80, output_parts: list, stream: bool) -> None:
    function = cpu.regs.c
    text = ""
    if function == 2:
        text = chr(cpu.regs.e)
    elif function == 9:
        addr = cpu.regs.de
        chars = []
        while True:
            byte = cpu.memory.read_byte(addr)
            if byte == ord("$"):
                break
            chars.append(chr(byte))
            addr = (addr + 1) & 0xFFFF
        text = "".join(chars)
    if text:
        output_parts.append(text)
        if stream:
            sys.stdout.write(text)
            sys.stdout.flush()
    # Simulate the RET for the "CALL 5" the test program issued.
    cpu.regs.pc = cpu.pop_word()


def run_com_file(
    path: Path,
    max_instructions: int = 5_000_000_000,
    *,
    stream: bool = False,
    heartbeat_every: int = 20_000_000,
) -> str:
    memory = make_flat_memory()
    data = path.read_bytes()
    for offset, byte in enumerate(data):
        memory.write_byte(LOAD_ADDRESS + offset, byte)

    cpu = Z80(memory)
    cpu.reset()
    cpu.regs.sp = 0xFFFE
    cpu.regs.pc = LOAD_ADDRESS

    output_parts: list = []
    instructions = 0
    start = time.perf_counter()
    next_heartbeat = heartbeat_every

    while cpu.regs.pc != EXIT_ADDRESS:
        if cpu.regs.pc == BDOS_ADDRESS:
            _handle_bdos_call(cpu, output_parts, stream)
            continue
        cpu.step()
        instructions += 1
        if stream and instructions >= next_heartbeat:
            elapsed = time.perf_counter() - start
            sys.stderr.write(
                f"\n[heartbeat] {instructions:,} instructions, {elapsed:.1f}s elapsed, "
                f"{instructions / elapsed:,.0f} instr/sec, PC=0x{cpu.regs.pc:04X}\n"
            )
            sys.stderr.flush()
            next_heartbeat += heartbeat_every
        if instructions > max_instructions:
            raise RuntimeError(f"{path.name}: exceeded {max_instructions} instructions without finishing")

    if stream:
        elapsed = time.perf_counter() - start
        sys.stderr.write(f"\n[done] {instructions:,} instructions in {elapsed:.1f}s\n")
        sys.stderr.flush()

    return "".join(output_parts)


def main() -> int:
    exit_code = 0
    ran_any = False
    for name in ("zexdoc.com", "zexall.com"):
        path = FIXTURES_DIR / name
        if not path.exists():
            print(f"SKIP {name}: not found at {path}")
            continue
        ran_any = True
        print(f"--- running {name} ---")
        output = run_com_file(path, stream=True)
        if "error" in output.lower():
            exit_code = 1
    if not ran_any:
        print("No zexall/zexdoc fixtures found; see tests/zexall/fixtures/README.md")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
