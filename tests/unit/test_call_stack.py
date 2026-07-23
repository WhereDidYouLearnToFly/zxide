"""Tests for inferring a call stack from raw stack contents (zxemu_ui.call_stack_view).

The Z80 records nothing about call frames, so these check the *inference*: that real
return addresses are recognised by the call instruction that must have pushed them,
and that unrelated pushed data is not mistaken for a frame.
"""

from __future__ import annotations

from zxemu_core.machine import Machine
from zxemu_ui.call_stack_view import call_frames


def _machine(program: dict) -> Machine:
    rom = bytearray(0x4000)
    for address, data in program.items():
        rom[address:address + len(data)] = data
    return Machine(bytes(rom))


def test_recognises_a_nested_call_chain():
    # main calls $0100, which calls $0200. Return addresses are $0003 and $0103.
    m = _machine({
        0x0000: bytes([0xCD, 0x00, 0x01]),  # CALL $0100  -> returns to $0003
        0x0100: bytes([0xCD, 0x00, 0x02]),  # CALL $0200  -> returns to $0103
    })
    m.cpu.regs.sp = 0x8000
    m.memory.write_word(0x8000, 0x0103)  # innermost frame
    m.memory.write_word(0x8002, 0x0003)  # outer frame

    frames = call_frames(m.memory, sp=0x8000, pc=0x0200)

    assert [f[1] for f in frames][:2] == [0x0103, 0x0003]  # innermost first
    assert [f[2] for f in frames][:2] == [0x0100, 0x0000]  # the CALL sites
    assert frames[0][3] == "call $0200"
    assert frames[1][3] == "call $0100"


def test_recognises_an_rst_frame():
    m = _machine({0x0000: bytes([0xD7])})  # RST $10 at $0000 -> returns to $0001
    m.cpu.regs.sp = 0x8000
    m.memory.write_word(0x8000, 0x0001)

    frames = call_frames(m.memory, sp=0x8000, pc=0x0010)

    assert frames[0][1] == 0x0001
    assert frames[0][2] == 0x0000
    assert frames[0][3] == "rst $10"


def test_skips_pushed_data_that_is_not_a_return_address():
    """Saved registers sit on the stack too and must not be reported as frames."""
    m = _machine({0x0000: bytes([0xCD, 0x00, 0x01])})  # CALL $0100 -> returns to $0003
    m.cpu.regs.sp = 0x8000
    m.memory.write_word(0x8000, 0x1234)  # a pushed HL: nothing call-like precedes $1234
    m.memory.write_word(0x8002, 0x0003)  # the genuine return address

    frames = call_frames(m.memory, sp=0x8000, pc=0x0100)

    assert 0x1234 not in [f[1] for f in frames]
    assert frames[0][1] == 0x0003


def test_conditional_call_is_recognised():
    m = _machine({0x0000: bytes([0xC4, 0x00, 0x01])})  # CALL NZ,$0100 -> returns to $0003
    m.cpu.regs.sp = 0x8000
    m.memory.write_word(0x8000, 0x0003)

    frames = call_frames(m.memory, sp=0x8000, pc=0x0100)

    assert frames[0][3] == "call cc $0100"


def test_rst_38_is_not_treated_as_a_call():
    """$FF is the commonest filler byte, so trusting it floods the view with noise.

    Regression guard: against the real 48K ROM, accepting RST $38 turned 3 genuine
    frames into 14. It also costs nothing to exclude -- $0038 is the IM 1 vector, and
    an interrupt pushes PC without executing an RST, so those frames were never
    detectable this way regardless.
    """
    m = _machine({0x3BFF: bytes([0xFF])})  # a stray $FF, as found throughout ROM font data
    m.memory.write_word(0x8000, 0x3C00)    # a word that "follows" it

    assert call_frames(m.memory, sp=0x8000, pc=0x0000) == []


def test_rst_10_is_still_recognised():
    """Excluding $FF must not throw away the RSTs real code actually uses."""
    m = _machine({0x1000: bytes([0xD7])})  # RST $10 (PRINT-A) -- everyday Spectrum code
    m.memory.write_word(0x8000, 0x1001)

    frames = call_frames(m.memory, sp=0x8000, pc=0x0010)

    assert frames and frames[0][3] == "rst $10"


def test_empty_stack_yields_no_frames():
    m = _machine({})  # ROM is all zeros: nothing looks like a call
    frames = call_frames(m.memory, sp=0x8000, pc=0x0000)
    assert frames == []
