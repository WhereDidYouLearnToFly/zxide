"""Tests for the conditional-breakpoint expression language (zxemu_core.debug_expr)."""

from __future__ import annotations

import pytest

from zxemu_core import debug_expr
from zxemu_core.machine import Machine


def _machine() -> Machine:
    return Machine(bytes(0x4000))


def test_register_compared_to_hex():
    m = _machine()
    m.cpu.regs.a = 0xFF
    assert debug_expr.evaluate("A == $FF", m) is True
    assert debug_expr.evaluate("A == $FE", m) is False


def test_case_and_spacing_are_forgiving():
    m = _machine()
    m.cpu.regs.a = 0x10
    assert debug_expr.evaluate("a==$10", m) is True
    assert debug_expr.evaluate("  A   ==   16  ", m) is True  # decimal


def test_sixteen_bit_register_and_ordering():
    m = _machine()
    m.cpu.regs.hl = 0x9000
    assert debug_expr.evaluate("HL > $8000", m) is True
    assert debug_expr.evaluate("HL <= $8000", m) is False


def test_parentheses_read_memory_through_a_register():
    m = _machine()
    m.cpu.regs.hl = 0x8000
    m.memory.write_byte(0x8000, 0x42)
    assert debug_expr.evaluate("(HL) == $42", m) is True
    assert debug_expr.evaluate("(HL) == 0", m) is False


def test_parentheses_read_memory_at_a_literal_address():
    m = _machine()
    m.memory.write_byte(0x5C08, 0x20)  # LAST-K
    assert debug_expr.evaluate("($5C08) == $20", m) is True


def test_flags_read_as_zero_or_one():
    m = _machine()
    m.cpu.regs.f = 0x40  # Z set
    assert debug_expr.evaluate("FZ == 1", m) is True
    assert debug_expr.evaluate("FC == 1", m) is False


def test_and_or_with_conventional_precedence():
    m = _machine()
    m.cpu.regs.b = 1
    m.cpu.regs.c = 2
    m.cpu.regs.d = 9
    assert debug_expr.evaluate("B == 1 and C == 2", m) is True
    assert debug_expr.evaluate("B == 1 and C == 99", m) is False
    # 'or' binds loosest: (B==99 and C==99) or (D==9)
    assert debug_expr.evaluate("B == 99 and C == 99 or D == 9", m) is True


def test_binary_literals():
    m = _machine()
    m.cpu.regs.a = 0b1010
    assert debug_expr.evaluate("A == %1010", m) is True


def test_shadow_register_via_prime():
    m = _machine()
    m.cpu.regs.hl2 = 0x1234
    assert debug_expr.evaluate("HL' == $1234", m) is True


def test_nonsense_raises_rather_than_silently_failing():
    m = _machine()
    with pytest.raises(debug_expr.ExpressionError):
        debug_expr.evaluate("A", m)          # no comparison
    with pytest.raises(debug_expr.ExpressionError):
        debug_expr.evaluate("Q == 1", m)     # not a register
    with pytest.raises(debug_expr.ExpressionError):
        debug_expr.evaluate("A == ", m)      # missing value
