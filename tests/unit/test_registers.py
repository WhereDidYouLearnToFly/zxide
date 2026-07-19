from zxemu_core.cpu.registers import (
    FLAG_C,
    FLAG_H,
    FLAG_N,
    FLAG_P,
    FLAG_S,
    FLAG_X,
    FLAG_Y,
    FLAG_Z,
    Registers,
)


def test_pair_getter_combines_halves():
    regs = Registers()
    regs.b = 0x12
    regs.c = 0x34
    assert regs.bc == 0x1234


def test_pair_setter_splits_into_halves():
    regs = Registers()
    regs.hl = 0xBEEF
    assert regs.h == 0xBE
    assert regs.l == 0xEF


def test_pair_setter_masks_to_16_bits():
    regs = Registers()
    regs.de = 0x1_FFFF
    assert regs.de == 0xFFFF


def test_all_pairs_independent():
    regs = Registers()
    regs.af = 0x1122
    regs.bc = 0x3344
    regs.de = 0x5566
    regs.hl = 0x7788
    regs.af2 = 0x99AA
    regs.bc2 = 0xBBCC
    regs.de2 = 0xDDEE
    regs.hl2 = 0xFF00
    regs.ix = 0x1357
    regs.iy = 0x2468
    assert (regs.af, regs.bc, regs.de, regs.hl) == (0x1122, 0x3344, 0x5566, 0x7788)
    assert (regs.af2, regs.bc2, regs.de2, regs.hl2) == (0x99AA, 0xBBCC, 0xDDEE, 0xFF00)
    assert (regs.ix, regs.iy) == (0x1357, 0x2468)


def test_flag_masks_are_distinct_bits():
    masks = [FLAG_C, FLAG_N, FLAG_P, FLAG_X, FLAG_H, FLAG_Y, FLAG_Z, FLAG_S]
    assert len(set(masks)) == len(masks)
    combined = 0
    for mask in masks:
        combined |= mask
    assert combined == 0xFF


def test_set_flag_true_sets_bit_without_disturbing_others():
    regs = Registers()
    regs.f = FLAG_Z
    regs.set_flag(FLAG_C, True)
    assert regs.f == (FLAG_Z | FLAG_C)


def test_set_flag_false_clears_bit_without_disturbing_others():
    regs = Registers()
    regs.f = FLAG_Z | FLAG_C | FLAG_S
    regs.set_flag(FLAG_C, False)
    assert regs.f == (FLAG_Z | FLAG_S)


def test_get_flag_reflects_bit_state():
    regs = Registers()
    regs.f = FLAG_S | FLAG_H
    assert regs.get_flag(FLAG_S) is True
    assert regs.get_flag(FLAG_H) is True
    assert regs.get_flag(FLAG_C) is False
