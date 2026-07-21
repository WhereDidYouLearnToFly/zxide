"""Tests for the debugger's step-over logic in EmulatorController."""

from __future__ import annotations

import pytest

from zxemu_core.machine import Machine
from zxemu_ui.controller import EmulatorController


@pytest.fixture(scope="module")
def qapp():
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def _machine(program: dict) -> Machine:
    """A machine whose ROM holds the given {address: bytes} program fragments."""
    rom = bytearray(0x4000)
    for address, data in program.items():
        rom[address:address + len(data)] = data
    return Machine(bytes(rom))


def test_step_over_runs_a_whole_ldir_to_completion(qapp):
    m = _machine({0x09: bytes([0xED, 0xB0])})  # LDIR at 0x09, return addr 0x0B
    m.cpu.regs.pc = 0x09
    m.cpu.regs.bc = 3
    m.cpu.regs.hl = 0x8000
    m.cpu.regs.de = 0x9000
    for i, v in enumerate((0x11, 0x22, 0x33)):
        m.memory.write_byte(0x8000 + i, v)

    EmulatorController(m).step_over()

    assert m.cpu.regs.pc == 0x0B  # stepped past the whole block
    assert m.cpu.regs.bc == 0
    assert [m.memory.read_byte(0x9000 + i) for i in range(3)] == [0x11, 0x22, 0x33]


def test_step_over_runs_a_call_subroutine_to_completion(qapp):
    m = _machine({
        0x00: bytes([0xCD, 0x00, 0x01]),  # CALL 0x0100, return addr 0x03
        0x0100: bytes([0x3E, 0x42, 0xC9]),  # LD A,0x42 ; RET
    })
    m.cpu.regs.pc = 0x0000
    start_sp = m.cpu.regs.sp

    EmulatorController(m).step_over()

    assert m.cpu.regs.pc == 0x0003        # stopped at the instruction after CALL
    assert m.cpu.regs.a == 0x42           # the subroutine ran
    assert m.cpu.regs.sp == start_sp      # stack unwound


def test_step_over_of_a_plain_instruction_is_a_single_step(qapp):
    m = _machine({0x00: bytes([0x3E, 0x05])})  # LD A,5
    m.cpu.regs.pc = 0x0000

    EmulatorController(m).step_over()

    assert m.cpu.regs.pc == 0x0002
    assert m.cpu.regs.a == 0x05


def test_step_over_stops_on_a_breakpoint_inside_the_subroutine(qapp):
    m = _machine({
        0x00: bytes([0xCD, 0x00, 0x01]),  # CALL 0x0100
        0x0100: bytes([0x3E, 0x42, 0xC9]),  # LD A,0x42 ; RET  (breakpoint at 0x0100)
    })
    m.cpu.regs.pc = 0x0000
    controller = EmulatorController(m)
    controller.set_breakpoints({0x0100})
    hits = []
    controller.breakpoint_hit.connect(hits.append)

    controller.step_over()

    assert m.cpu.regs.pc == 0x0100  # stopped at the breakpoint, before running it
    assert hits == [0x0100]
    assert m.cpu.regs.a != 0x42     # the LD A hasn't executed yet
