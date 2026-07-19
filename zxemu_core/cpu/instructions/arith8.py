"""8-bit arithmetic/logic on A (ADD/ADC/SUB/SBC/AND/XOR/OR/CP) plus INC/DEC r.

Each ALU family has one explicit operation function (add_a, sub_a, ...) that
does the flag math via flags.py; the per-source handlers just fetch the
operand (register, (HL), or immediate n) and call it.
"""

from __future__ import annotations

from .. import flags as alu
from ..registers import FLAG_C
from ._dispatch import base


## ─── ALU operations (operate on A with a supplied value) ───

def add_a(cpu, value: int) -> None:
    cpu.regs.a, cpu.regs.f = alu.add8(cpu.regs.a, value, 0)


def adc_a(cpu, value: int) -> None:
    cpu.regs.a, cpu.regs.f = alu.add8(cpu.regs.a, value, cpu.regs.f & FLAG_C)


def sub_a(cpu, value: int) -> None:
    cpu.regs.a, cpu.regs.f = alu.sub8(cpu.regs.a, value, 0)


def sbc_a(cpu, value: int) -> None:
    cpu.regs.a, cpu.regs.f = alu.sub8(cpu.regs.a, value, cpu.regs.f & FLAG_C)


def and_a(cpu, value: int) -> None:
    cpu.regs.a, cpu.regs.f = alu.and8(cpu.regs.a, value)


def xor_a(cpu, value: int) -> None:
    cpu.regs.a, cpu.regs.f = alu.xor8(cpu.regs.a, value)


def or_a(cpu, value: int) -> None:
    cpu.regs.a, cpu.regs.f = alu.or8(cpu.regs.a, value)


def cp_a(cpu, value: int) -> None:
    cpu.regs.f = alu.cp8(cpu.regs.a, value)


# Indexed handlers (DD/FD) reuse these by ALU-op index.
ALU_OPS = [add_a, adc_a, sub_a, sbc_a, and_a, xor_a, or_a, cp_a]



## ─── ALU A,r  (0x80-0xBF) and ALU A,n  (0xC6|op<<3) ───

@base(0x80)
def add_a_b(cpu):
    "ADD A,B"
    add_a(cpu, cpu.regs.b)


@base(0x81)
def add_a_c(cpu):
    "ADD A,C"
    add_a(cpu, cpu.regs.c)


@base(0x82)
def add_a_d(cpu):
    "ADD A,D"
    add_a(cpu, cpu.regs.d)


@base(0x83)
def add_a_e(cpu):
    "ADD A,E"
    add_a(cpu, cpu.regs.e)


@base(0x84)
def add_a_h(cpu):
    "ADD A,H"
    add_a(cpu, cpu.regs.h)


@base(0x85)
def add_a_l(cpu):
    "ADD A,L"
    add_a(cpu, cpu.regs.l)


@base(0x86)
def add_a_hl(cpu):
    "ADD A,(HL)"
    add_a(cpu, cpu.read_mem(cpu.regs.hl))


@base(0x87)
def add_a_a(cpu):
    "ADD A,A"
    add_a(cpu, cpu.regs.a)


@base(0xC6)
def add_a_n(cpu):
    "ADD A,n"
    add_a(cpu, cpu.fetch_byte())


@base(0x88)
def adc_a_b(cpu):
    "ADC A,B"
    adc_a(cpu, cpu.regs.b)


@base(0x89)
def adc_a_c(cpu):
    "ADC A,C"
    adc_a(cpu, cpu.regs.c)


@base(0x8A)
def adc_a_d(cpu):
    "ADC A,D"
    adc_a(cpu, cpu.regs.d)


@base(0x8B)
def adc_a_e(cpu):
    "ADC A,E"
    adc_a(cpu, cpu.regs.e)


@base(0x8C)
def adc_a_h(cpu):
    "ADC A,H"
    adc_a(cpu, cpu.regs.h)


@base(0x8D)
def adc_a_l(cpu):
    "ADC A,L"
    adc_a(cpu, cpu.regs.l)


@base(0x8E)
def adc_a_hl(cpu):
    "ADC A,(HL)"
    adc_a(cpu, cpu.read_mem(cpu.regs.hl))


@base(0x8F)
def adc_a_a(cpu):
    "ADC A,A"
    adc_a(cpu, cpu.regs.a)


@base(0xCE)
def adc_a_n(cpu):
    "ADC A,n"
    adc_a(cpu, cpu.fetch_byte())


@base(0x90)
def sub_a_b(cpu):
    "SUB,B"
    sub_a(cpu, cpu.regs.b)


@base(0x91)
def sub_a_c(cpu):
    "SUB,C"
    sub_a(cpu, cpu.regs.c)


@base(0x92)
def sub_a_d(cpu):
    "SUB,D"
    sub_a(cpu, cpu.regs.d)


@base(0x93)
def sub_a_e(cpu):
    "SUB,E"
    sub_a(cpu, cpu.regs.e)


@base(0x94)
def sub_a_h(cpu):
    "SUB,H"
    sub_a(cpu, cpu.regs.h)


@base(0x95)
def sub_a_l(cpu):
    "SUB,L"
    sub_a(cpu, cpu.regs.l)


@base(0x96)
def sub_a_hl(cpu):
    "SUB,(HL)"
    sub_a(cpu, cpu.read_mem(cpu.regs.hl))


@base(0x97)
def sub_a_a(cpu):
    "SUB,A"
    sub_a(cpu, cpu.regs.a)


@base(0xD6)
def sub_a_n(cpu):
    "SUB,n"
    sub_a(cpu, cpu.fetch_byte())


@base(0x98)
def sbc_a_b(cpu):
    "SBC A,B"
    sbc_a(cpu, cpu.regs.b)


@base(0x99)
def sbc_a_c(cpu):
    "SBC A,C"
    sbc_a(cpu, cpu.regs.c)


@base(0x9A)
def sbc_a_d(cpu):
    "SBC A,D"
    sbc_a(cpu, cpu.regs.d)


@base(0x9B)
def sbc_a_e(cpu):
    "SBC A,E"
    sbc_a(cpu, cpu.regs.e)


@base(0x9C)
def sbc_a_h(cpu):
    "SBC A,H"
    sbc_a(cpu, cpu.regs.h)


@base(0x9D)
def sbc_a_l(cpu):
    "SBC A,L"
    sbc_a(cpu, cpu.regs.l)


@base(0x9E)
def sbc_a_hl(cpu):
    "SBC A,(HL)"
    sbc_a(cpu, cpu.read_mem(cpu.regs.hl))


@base(0x9F)
def sbc_a_a(cpu):
    "SBC A,A"
    sbc_a(cpu, cpu.regs.a)


@base(0xDE)
def sbc_a_n(cpu):
    "SBC A,n"
    sbc_a(cpu, cpu.fetch_byte())


@base(0xA0)
def and_a_b(cpu):
    "AND,B"
    and_a(cpu, cpu.regs.b)


@base(0xA1)
def and_a_c(cpu):
    "AND,C"
    and_a(cpu, cpu.regs.c)


@base(0xA2)
def and_a_d(cpu):
    "AND,D"
    and_a(cpu, cpu.regs.d)


@base(0xA3)
def and_a_e(cpu):
    "AND,E"
    and_a(cpu, cpu.regs.e)


@base(0xA4)
def and_a_h(cpu):
    "AND,H"
    and_a(cpu, cpu.regs.h)


@base(0xA5)
def and_a_l(cpu):
    "AND,L"
    and_a(cpu, cpu.regs.l)


@base(0xA6)
def and_a_hl(cpu):
    "AND,(HL)"
    and_a(cpu, cpu.read_mem(cpu.regs.hl))


@base(0xA7)
def and_a_a(cpu):
    "AND,A"
    and_a(cpu, cpu.regs.a)


@base(0xE6)
def and_a_n(cpu):
    "AND,n"
    and_a(cpu, cpu.fetch_byte())


@base(0xA8)
def xor_a_b(cpu):
    "XOR,B"
    xor_a(cpu, cpu.regs.b)


@base(0xA9)
def xor_a_c(cpu):
    "XOR,C"
    xor_a(cpu, cpu.regs.c)


@base(0xAA)
def xor_a_d(cpu):
    "XOR,D"
    xor_a(cpu, cpu.regs.d)


@base(0xAB)
def xor_a_e(cpu):
    "XOR,E"
    xor_a(cpu, cpu.regs.e)


@base(0xAC)
def xor_a_h(cpu):
    "XOR,H"
    xor_a(cpu, cpu.regs.h)


@base(0xAD)
def xor_a_l(cpu):
    "XOR,L"
    xor_a(cpu, cpu.regs.l)


@base(0xAE)
def xor_a_hl(cpu):
    "XOR,(HL)"
    xor_a(cpu, cpu.read_mem(cpu.regs.hl))


@base(0xAF)
def xor_a_a(cpu):
    "XOR,A"
    xor_a(cpu, cpu.regs.a)


@base(0xEE)
def xor_a_n(cpu):
    "XOR,n"
    xor_a(cpu, cpu.fetch_byte())


@base(0xB0)
def or_a_b(cpu):
    "OR,B"
    or_a(cpu, cpu.regs.b)


@base(0xB1)
def or_a_c(cpu):
    "OR,C"
    or_a(cpu, cpu.regs.c)


@base(0xB2)
def or_a_d(cpu):
    "OR,D"
    or_a(cpu, cpu.regs.d)


@base(0xB3)
def or_a_e(cpu):
    "OR,E"
    or_a(cpu, cpu.regs.e)


@base(0xB4)
def or_a_h(cpu):
    "OR,H"
    or_a(cpu, cpu.regs.h)


@base(0xB5)
def or_a_l(cpu):
    "OR,L"
    or_a(cpu, cpu.regs.l)


@base(0xB6)
def or_a_hl(cpu):
    "OR,(HL)"
    or_a(cpu, cpu.read_mem(cpu.regs.hl))


@base(0xB7)
def or_a_a(cpu):
    "OR,A"
    or_a(cpu, cpu.regs.a)


@base(0xF6)
def or_a_n(cpu):
    "OR,n"
    or_a(cpu, cpu.fetch_byte())


@base(0xB8)
def cp_a_b(cpu):
    "CP,B"
    cp_a(cpu, cpu.regs.b)


@base(0xB9)
def cp_a_c(cpu):
    "CP,C"
    cp_a(cpu, cpu.regs.c)


@base(0xBA)
def cp_a_d(cpu):
    "CP,D"
    cp_a(cpu, cpu.regs.d)


@base(0xBB)
def cp_a_e(cpu):
    "CP,E"
    cp_a(cpu, cpu.regs.e)


@base(0xBC)
def cp_a_h(cpu):
    "CP,H"
    cp_a(cpu, cpu.regs.h)


@base(0xBD)
def cp_a_l(cpu):
    "CP,L"
    cp_a(cpu, cpu.regs.l)


@base(0xBE)
def cp_a_hl(cpu):
    "CP,(HL)"
    cp_a(cpu, cpu.read_mem(cpu.regs.hl))


@base(0xBF)
def cp_a_a(cpu):
    "CP,A"
    cp_a(cpu, cpu.regs.a)


@base(0xFE)
def cp_a_n(cpu):
    "CP,n"
    cp_a(cpu, cpu.fetch_byte())



## ─── INC r  (0x04|r<<3) ───

@base(0x04)
def inc_b(cpu):
    "INC B"
    cpu.regs.b, cpu.regs.f = alu.inc8(cpu.regs.b, cpu.regs.f)


@base(0x0C)
def inc_c(cpu):
    "INC C"
    cpu.regs.c, cpu.regs.f = alu.inc8(cpu.regs.c, cpu.regs.f)


@base(0x14)
def inc_d(cpu):
    "INC D"
    cpu.regs.d, cpu.regs.f = alu.inc8(cpu.regs.d, cpu.regs.f)


@base(0x1C)
def inc_e(cpu):
    "INC E"
    cpu.regs.e, cpu.regs.f = alu.inc8(cpu.regs.e, cpu.regs.f)


@base(0x24)
def inc_h(cpu):
    "INC H"
    cpu.regs.h, cpu.regs.f = alu.inc8(cpu.regs.h, cpu.regs.f)


@base(0x2C)
def inc_l(cpu):
    "INC L"
    cpu.regs.l, cpu.regs.f = alu.inc8(cpu.regs.l, cpu.regs.f)


@base(0x34)
def inc_hl(cpu):
    "INC (HL)"
    result, f = alu.inc8(cpu.read_mem(cpu.regs.hl), cpu.regs.f)
    cpu.write_mem(cpu.regs.hl, result)
    cpu.regs.f = f


@base(0x3C)
def inc_a(cpu):
    "INC A"
    cpu.regs.a, cpu.regs.f = alu.inc8(cpu.regs.a, cpu.regs.f)



## ─── DEC r  (0x05|r<<3) ───

@base(0x05)
def dec_b(cpu):
    "DEC B"
    cpu.regs.b, cpu.regs.f = alu.dec8(cpu.regs.b, cpu.regs.f)


@base(0x0D)
def dec_c(cpu):
    "DEC C"
    cpu.regs.c, cpu.regs.f = alu.dec8(cpu.regs.c, cpu.regs.f)


@base(0x15)
def dec_d(cpu):
    "DEC D"
    cpu.regs.d, cpu.regs.f = alu.dec8(cpu.regs.d, cpu.regs.f)


@base(0x1D)
def dec_e(cpu):
    "DEC E"
    cpu.regs.e, cpu.regs.f = alu.dec8(cpu.regs.e, cpu.regs.f)


@base(0x25)
def dec_h(cpu):
    "DEC H"
    cpu.regs.h, cpu.regs.f = alu.dec8(cpu.regs.h, cpu.regs.f)


@base(0x2D)
def dec_l(cpu):
    "DEC L"
    cpu.regs.l, cpu.regs.f = alu.dec8(cpu.regs.l, cpu.regs.f)


@base(0x35)
def dec_hl(cpu):
    "DEC (HL)"
    result, f = alu.dec8(cpu.read_mem(cpu.regs.hl), cpu.regs.f)
    cpu.write_mem(cpu.regs.hl, result)
    cpu.regs.f = f


@base(0x3D)
def dec_a(cpu):
    "DEC A"
    cpu.regs.a, cpu.regs.f = alu.dec8(cpu.regs.a, cpu.regs.f)


