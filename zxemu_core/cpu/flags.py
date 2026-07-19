"""Flag-computation helpers for 8/16-bit ALU operations, shared across opcode tables.

Algorithms follow documented Z80 behavior (Zilog data sheet arithmetic/flag
rules, plus well-known community documentation of the undocumented X/Y flag
and DAA behavior) reimplemented independently -- not derived from fuse's C
source.
"""

from __future__ import annotations

from .registers import FLAG_C, FLAG_H, FLAG_N, FLAG_P, FLAG_S, FLAG_X, FLAG_Y, FLAG_Z


def sz53_of(value: int) -> int:
    """S, Y (bit 5), X (bit 3) flags mirror the result directly; Z is computed."""
    flags = value & (FLAG_S | FLAG_Y | FLAG_X)
    if (value & 0xFF) == 0:
        flags |= FLAG_Z
    return flags


def parity_even(value: int) -> bool:
    value &= 0xFF
    value ^= value >> 4
    value ^= value >> 2
    value ^= value >> 1
    return (value & 1) == 0


def add8(a: int, b: int, carry_in: int = 0) -> tuple[int, int]:
    result = a + b + carry_in
    flags = sz53_of(result & 0xFF)
    if (a & 0x0F) + (b & 0x0F) + carry_in > 0x0F:
        flags |= FLAG_H
    if result > 0xFF:
        flags |= FLAG_C
    if (a ^ result) & (b ^ result) & 0x80:
        flags |= FLAG_P
    return result & 0xFF, flags


def sub8(a: int, b: int, carry_in: int = 0) -> tuple[int, int]:
    result = a - b - carry_in
    flags = sz53_of(result & 0xFF) | FLAG_N
    if (a & 0x0F) - (b & 0x0F) - carry_in < 0:
        flags |= FLAG_H
    if result < 0:
        flags |= FLAG_C
    if (a ^ b) & (a ^ result) & 0x80:
        flags |= FLAG_P
    return result & 0xFF, flags


def cp8(a: int, b: int) -> int:
    """CP: flags as SUB, but the undocumented X/Y flags mirror the operand, not the result."""
    _, flags = sub8(a, b)
    flags = (flags & ~(FLAG_X | FLAG_Y)) | (b & (FLAG_X | FLAG_Y))
    return flags


def and8(a: int, b: int) -> tuple[int, int]:
    result = a & b
    flags = sz53_of(result) | FLAG_H
    if parity_even(result):
        flags |= FLAG_P
    return result, flags


def or8(a: int, b: int) -> tuple[int, int]:
    result = a | b
    flags = sz53_of(result)
    if parity_even(result):
        flags |= FLAG_P
    return result, flags


def xor8(a: int, b: int) -> tuple[int, int]:
    result = a ^ b
    flags = sz53_of(result)
    if parity_even(result):
        flags |= FLAG_P
    return result, flags


def inc8(a: int, old_flags: int) -> tuple[int, int]:
    result = (a + 1) & 0xFF
    flags = sz53_of(result) | (old_flags & FLAG_C)
    if (a & 0x0F) == 0x0F:
        flags |= FLAG_H
    if a == 0x7F:
        flags |= FLAG_P
    return result, flags


def dec8(a: int, old_flags: int) -> tuple[int, int]:
    result = (a - 1) & 0xFF
    flags = sz53_of(result) | FLAG_N | (old_flags & FLAG_C)
    if (a & 0x0F) == 0x00:
        flags |= FLAG_H
    if a == 0x80:
        flags |= FLAG_P
    return result, flags


def add16(a: int, b: int, old_flags: int) -> tuple[int, int]:
    """ADD HL,rr / ADD IX,rr etc: only H, N (reset), C, and undoc X/Y (from result high byte) change."""
    result = a + b
    flags = old_flags & (FLAG_S | FLAG_Z | FLAG_P)
    flags |= (result >> 8) & (FLAG_Y | FLAG_X)
    if (a & 0x0FFF) + (b & 0x0FFF) > 0x0FFF:
        flags |= FLAG_H
    if result > 0xFFFF:
        flags |= FLAG_C
    return result & 0xFFFF, flags


def adc16(a: int, b: int, carry_in: int) -> tuple[int, int]:
    """ADC HL,rr: like add16 but also sets S/Z/P from the 16-bit result (ED-prefixed, used later)."""
    result = a + b + carry_in
    result16 = result & 0xFFFF
    flags = 0
    if result16 & 0x8000:
        flags |= FLAG_S
    if result16 == 0:
        flags |= FLAG_Z
    flags |= (result16 >> 8) & (FLAG_Y | FLAG_X)
    if (a & 0x0FFF) + (b & 0x0FFF) + carry_in > 0x0FFF:
        flags |= FLAG_H
    if result > 0xFFFF:
        flags |= FLAG_C
    if (a ^ result16) & (b ^ result16) & 0x8000:
        flags |= FLAG_P
    return result16, flags


def sbc16(a: int, b: int, carry_in: int) -> tuple[int, int]:
    """SBC HL,rr (ED-prefixed, used later)."""
    result = a - b - carry_in
    result16 = result & 0xFFFF
    flags = FLAG_N
    if result16 & 0x8000:
        flags |= FLAG_S
    if result16 == 0:
        flags |= FLAG_Z
    flags |= (result16 >> 8) & (FLAG_Y | FLAG_X)
    if (a & 0x0FFF) - (b & 0x0FFF) - carry_in < 0:
        flags |= FLAG_H
    if result < 0:
        flags |= FLAG_C
    if (a ^ b) & (a ^ result16) & 0x8000:
        flags |= FLAG_P
    return result16, flags


def rlc(value: int) -> tuple[int, int]:
    carry = (value >> 7) & 1
    result = ((value << 1) | carry) & 0xFF
    flags = sz53_of(result) | carry
    if parity_even(result):
        flags |= FLAG_P
    return result, flags


def rrc(value: int) -> tuple[int, int]:
    carry = value & 1
    result = ((value >> 1) | (carry << 7)) & 0xFF
    flags = sz53_of(result) | carry
    if parity_even(result):
        flags |= FLAG_P
    return result, flags


def rl(value: int, carry_in: int) -> tuple[int, int]:
    carry = (value >> 7) & 1
    result = ((value << 1) | (carry_in & 1)) & 0xFF
    flags = sz53_of(result) | carry
    if parity_even(result):
        flags |= FLAG_P
    return result, flags


def rr_(value: int, carry_in: int) -> tuple[int, int]:
    carry = value & 1
    result = ((value >> 1) | ((carry_in & 1) << 7)) & 0xFF
    flags = sz53_of(result) | carry
    if parity_even(result):
        flags |= FLAG_P
    return result, flags


def sla(value: int) -> tuple[int, int]:
    carry = (value >> 7) & 1
    result = (value << 1) & 0xFF
    flags = sz53_of(result) | carry
    if parity_even(result):
        flags |= FLAG_P
    return result, flags


def sra(value: int) -> tuple[int, int]:
    carry = value & 1
    result = ((value >> 1) | (value & 0x80)) & 0xFF
    flags = sz53_of(result) | carry
    if parity_even(result):
        flags |= FLAG_P
    return result, flags


def sll(value: int) -> tuple[int, int]:
    """Undocumented SLL/SLI: shifts left, but bit 0 becomes 1 (not 0)."""
    carry = (value >> 7) & 1
    result = ((value << 1) | 1) & 0xFF
    flags = sz53_of(result) | carry
    if parity_even(result):
        flags |= FLAG_P
    return result, flags


def srl(value: int) -> tuple[int, int]:
    carry = value & 1
    result = (value >> 1) & 0xFF
    flags = sz53_of(result) | carry
    if parity_even(result):
        flags |= FLAG_P
    return result, flags


def bit(value: int, bit_index: int, old_flags: int) -> int:
    """BIT b,r (register form): undocumented X/Y flags mirror the tested value directly."""
    is_set = bool(value & (1 << bit_index))
    result_flags = old_flags & FLAG_C
    result_flags |= FLAG_H
    if not is_set:
        result_flags |= FLAG_Z | FLAG_P
    if bit_index == 7 and is_set:
        result_flags |= FLAG_S
    result_flags |= value & (FLAG_Y | FLAG_X)
    return result_flags


def bit_memory(value: int, bit_index: int, old_flags: int, address_high_byte: int) -> int:
    """BIT b,(HL)/(IX+d)/(IY+d): undoc X/Y flags mirror the high byte of the address used
    (the real Z80's internal MEMPTR/WZ register), not the tested value -- a documented quirk."""
    is_set = bool(value & (1 << bit_index))
    result_flags = old_flags & FLAG_C
    result_flags |= FLAG_H
    if not is_set:
        result_flags |= FLAG_Z | FLAG_P
    if bit_index == 7 and is_set:
        result_flags |= FLAG_S
    result_flags |= address_high_byte & (FLAG_Y | FLAG_X)
    return result_flags


def res(value: int, bit_index: int) -> int:
    return value & ~(1 << bit_index) & 0xFF


def set_bit(value: int, bit_index: int) -> int:
    return value | (1 << bit_index)


ROTATE_SHIFT_OPS = [rlc, rrc, None, None, sla, sra, sll, srl]  # index 2/3 (RL/RR) need carry_in, special-cased


def daa(a: int, old_flags: int) -> tuple[int, int]:
    carry = old_flags & FLAG_C
    half_carry = old_flags & FLAG_H
    negative = old_flags & FLAG_N

    correction = 0
    if half_carry or (a & 0x0F) > 9:
        correction |= 0x06
    if carry or a > 0x99:
        correction |= 0x60
        carry = FLAG_C

    if negative:
        new_half_carry = FLAG_H if (half_carry and (a & 0x0F) < 6) else 0
        result = (a - correction) & 0xFF
    else:
        new_half_carry = FLAG_H if (a & 0x0F) > 9 else 0
        result = (a + correction) & 0xFF

    flags = sz53_of(result) | new_half_carry | negative | carry
    if parity_even(result):
        flags |= FLAG_P
    return result, flags
