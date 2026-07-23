"""Tests for the debugger's step-over and step-out logic in EmulatorController."""

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


def _run_frames(controller, count=1):
    for _ in range(count):
        if controller._run_one_frame():
            return True
    return False


def test_coverage_records_only_what_executed(qapp):
    m = _machine({0x00: bytes([0x00, 0x00, 0xC3, 0x00, 0x00])})  # NOP NOP JP $0000
    m.cpu.regs.pc = 0x0000
    controller = EmulatorController(m)
    controller.set_coverage_enabled(True)

    _run_frames(controller)

    assert controller.coverage.executed[0x0000]
    assert controller.coverage.executed[0x0002]  # the JP
    assert not controller.coverage.executed[0x0100]  # never reached


def test_coverage_is_off_by_default(qapp):
    m = _machine({0x00: bytes([0x00])})
    controller = EmulatorController(m)
    _run_frames(controller)
    assert controller.coverage.count() == 0


def test_trace_keeps_a_bounded_rolling_history(qapp):
    m = _machine({0x00: bytes([0x00, 0x00, 0xC3, 0x00, 0x00])})  # loops forever
    m.cpu.regs.pc = 0x0000
    controller = EmulatorController(m)
    controller.set_trace_enabled(True, length=10)

    _run_frames(controller)
    entries = controller.trace_entries()

    assert len(entries) == 10  # bounded: an unbounded trace would exhaust memory
    assert all(isinstance(address, int) and isinstance(sp, int) for address, sp in entries)


def test_trace_is_off_by_default(qapp):
    m = _machine({0x00: bytes([0x00])})
    controller = EmulatorController(m)
    _run_frames(controller)
    assert controller.trace_entries() == []


def test_run_to_stops_at_the_address_then_forgets_it(qapp):
    m = _machine({0x00: bytes([0x00, 0x00, 0x00, 0x00])})  # NOPs
    m.cpu.regs.pc = 0x0000
    controller = EmulatorController(m)
    hits = []
    controller.breakpoint_hit.connect(hits.append)

    controller.run_to(0x0002)
    assert _run_frames(controller) is True
    assert hits == [0x0002]
    assert m.cpu.regs.pc == 0x0002

    # One-shot: running on must not stop here a second time.
    hits.clear()
    controller.set_running(True)
    assert _run_frames(controller) is False
    assert hits == []


def test_conditional_breakpoint_does_not_stop_when_the_condition_is_false(qapp):
    m = _machine({0x00: bytes([0x3E, 0x01, 0x00])})  # LD A,1 ; NOP
    m.cpu.regs.pc = 0x0000
    controller = EmulatorController(m)
    controller.set_breakpoints({0x0002})
    controller.set_breakpoint_conditions({0x0002: "A == $FF"})  # A will be 1, not $FF
    hits = []
    controller.breakpoint_hit.connect(hits.append)

    assert _run_frames(controller) is False
    assert hits == []


def test_conditional_breakpoint_stops_when_the_condition_holds(qapp):
    m = _machine({0x00: bytes([0x3E, 0xFF, 0x00])})  # LD A,$FF ; NOP
    m.cpu.regs.pc = 0x0000
    controller = EmulatorController(m)
    controller.set_breakpoints({0x0002})
    controller.set_breakpoint_conditions({0x0002: "A == $FF"})
    hits = []
    controller.breakpoint_hit.connect(hits.append)

    assert _run_frames(controller) is True
    assert hits == [0x0002]


def test_a_broken_condition_stops_rather_than_being_ignored(qapp):
    """Failing open would be the worst outcome: you'd conclude the code never runs."""
    m = _machine({0x00: bytes([0x00, 0x00])})
    m.cpu.regs.pc = 0x0000
    controller = EmulatorController(m)
    controller.set_breakpoints({0x0001})
    controller.set_breakpoint_conditions({0x0001: "this is not an expression"})
    hits = []
    controller.breakpoint_hit.connect(hits.append)

    assert _run_frames(controller) is True
    assert hits == [0x0001]


def test_memory_write_watchpoint_pauses(qapp):
    # LD A,$99 ; LD ($9000),A ; then NOPs forever
    m = _machine({0x00: bytes([0x3E, 0x99, 0x32, 0x00, 0x90])})
    m.cpu.regs.pc = 0x0000
    controller = EmulatorController(m)
    controller.set_memory_watchpoints(writes={0x9000})
    hits = []
    controller.watchpoint_hit.connect(hits.append)

    assert _run_frames(controller) is True
    assert "wrote" in hits[0] and "9000" in hits[0] and "99" in hits[0]
    assert m.memory.read_byte(0x9000) == 0x99


def test_memory_write_watchpoint_catches_a_write_of_the_same_value(qapp):
    """True interception, not value comparison: storing the byte already there counts."""
    m = _machine({0x00: bytes([0x3E, 0x00, 0x32, 0x00, 0x90])})  # writes 0 over 0
    m.cpu.regs.pc = 0x0000
    controller = EmulatorController(m)
    controller.set_memory_watchpoints(writes={0x9000})
    hits = []
    controller.watchpoint_hit.connect(hits.append)

    assert _run_frames(controller) is True
    assert hits and "wrote" in hits[0]


def test_memory_read_watchpoint_pauses(qapp):
    """Reads were impossible under the old value-comparison approach."""
    m = _machine({0x00: bytes([0x3A, 0x00, 0x90])})  # LD A,($9000)
    m.cpu.regs.pc = 0x0000
    m.memory.write_byte(0x9000, 0x5A)
    controller = EmulatorController(m)
    controller.set_memory_watchpoints(reads={0x9000})
    hits = []
    controller.watchpoint_hit.connect(hits.append)

    assert _run_frames(controller) is True
    assert "read" in hits[0] and "9000" in hits[0] and "5A" in hits[0]


def test_clearing_memory_watchpoints_restores_the_plain_fast_memory(qapp):
    """The whole point of the class swap: no instrumentation left behind when unused."""
    from zxemu_core.memory import Memory, WatchedMemory

    m = _machine({})
    controller = EmulatorController(m)
    assert not isinstance(m.memory, WatchedMemory)

    controller.set_memory_watchpoints(writes={0x9000})
    assert isinstance(m.memory, WatchedMemory)

    controller.set_memory_watchpoints((), ())
    assert not isinstance(m.memory, WatchedMemory)
    assert isinstance(m.memory, Memory)


def test_watched_memory_keeps_its_identity_and_contents(qapp):
    """Swapping __class__ must not disturb the object the CPU and paging hold."""
    m = _machine({})
    before = m.memory
    m.memory.write_byte(0x9000, 0x77)

    EmulatorController(m).set_memory_watchpoints(writes={0x8000})

    assert m.memory is before          # same object
    assert m.cpu.memory is m.memory    # the CPU's reference still valid
    assert m.memory.read_byte(0x9000) == 0x77


def test_port_watchpoint_pauses_on_out(qapp):
    m = _machine({0x00: bytes([0x3E, 0x07, 0xD3, 0xFE])})  # LD A,7 ; OUT ($FE),A
    m.cpu.regs.pc = 0x0000
    controller = EmulatorController(m)
    controller.set_port_watchpoints(writes={0xFE})
    hits = []
    controller.watchpoint_hit.connect(hits.append)

    assert _run_frames(controller) is True
    assert len(hits) == 1
    assert "OUT" in hits[0] and "07" in hits[0]


def test_port_watchpoint_matches_on_the_low_byte(qapp):
    """OUT ($FE),A puts A in the high byte, so the full port is $07FE, not $00FE."""
    m = _machine({0x00: bytes([0x3E, 0x07, 0xD3, 0xFE])})
    m.cpu.regs.pc = 0x0000
    controller = EmulatorController(m)
    controller.set_port_watchpoints(writes={0xFE})
    hits = []
    controller.watchpoint_hit.connect(hits.append)

    _run_frames(controller)

    assert hits and "$07FE" in hits[0]  # matched despite the high byte


def test_no_watchpoints_leaves_the_fast_io_path_installed(qapp):
    """The whole point of the design: zero cost on the hot path when unused."""
    m = _machine({})
    assert m.cpu.io_write == m._io_write  # plain, uninstrumented

    m.set_port_watchpoints(writes={0xFE})
    assert m.cpu.io_write == m._io_write_watched

    m.set_port_watchpoints()  # cleared
    assert m.cpu.io_write == m._io_write


def test_step_out_returns_to_the_caller(qapp):
    m = _machine({
        0x00: bytes([0xCD, 0x00, 0x01, 0x00]),  # CALL 0x0100 ; NOP
        0x0100: bytes([0x3E, 0x42, 0xC9]),      # LD A,0x42 ; RET
    })
    m.cpu.regs.pc = 0x0100  # already inside the subroutine
    m.cpu.regs.sp = 0xFFFE
    m.memory.write_word(0xFFFE, 0x0003)  # the return address a CALL would have pushed

    EmulatorController(m).step_out()

    assert m.cpu.regs.pc == 0x0003   # back at the instruction after the call
    assert m.cpu.regs.a == 0x42      # the rest of the subroutine ran
    assert m.cpu.regs.sp == 0x0000   # the return address was popped


def test_step_out_ignores_epilogue_pops_and_stops_at_the_ret(qapp):
    """The SP test alone would stop early -- a routine's `pop` epilogue raises SP too.

    Regression guard for the reason step_out also requires a RET: here `pop hl` and
    `pop de` both push SP past where it started, and only the RET should end the step.
    """
    m = _machine({
        0x0200: bytes([0xE1, 0xD1, 0xC9]),  # POP HL ; POP DE ; RET
    })
    m.cpu.regs.pc = 0x0200
    m.cpu.regs.sp = 0xFFF8
    m.memory.write_word(0xFFF8, 0x1111)  # popped into HL
    m.memory.write_word(0xFFFA, 0x2222)  # popped into DE
    m.memory.write_word(0xFFFC, 0x0044)  # the actual return address

    EmulatorController(m).step_out()

    assert m.cpu.regs.hl == 0x1111   # both pops really did happen
    assert m.cpu.regs.de == 0x2222
    assert m.cpu.regs.pc == 0x0044   # and we stopped at the caller, not at a pop


def test_step_out_stops_on_a_breakpoint_before_returning(qapp):
    m = _machine({0x0100: bytes([0x00, 0x3E, 0x42, 0xC9])})  # NOP ; LD A,0x42 ; RET
    m.cpu.regs.pc = 0x0100
    m.cpu.regs.sp = 0xFFFE
    m.memory.write_word(0xFFFE, 0x0003)
    controller = EmulatorController(m)
    controller.set_breakpoints({0x0101})
    hits = []
    controller.breakpoint_hit.connect(hits.append)

    controller.step_out()

    assert m.cpu.regs.pc == 0x0101   # stopped inside the routine
    assert hits == [0x0101]
