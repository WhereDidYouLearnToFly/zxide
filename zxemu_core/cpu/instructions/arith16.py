"""16-bit arithmetic: ADD HL,rr ; INC rr ; DEC rr ; and the ED-prefixed
ADC HL,rr / SBC HL,rr. Pair order is BC,DE,HL,SP."""

from __future__ import annotations

from .. import flags as alu
from ..registers import FLAG_C
from ._dispatch import base, ed


## ─── ADD HL,rr  (0x09/0x19/0x29/0x39) ───

@base(0x09)
def add_hl_bc(cpu):
    "ADD HL,BC"
    cpu.regs.hl, cpu.regs.f = alu.add16(cpu.regs.hl, cpu.regs.bc, cpu.regs.f)
    cpu.add_t_states(7)


@base(0x19)
def add_hl_de(cpu):
    "ADD HL,DE"
    cpu.regs.hl, cpu.regs.f = alu.add16(cpu.regs.hl, cpu.regs.de, cpu.regs.f)
    cpu.add_t_states(7)


@base(0x29)
def add_hl_hl(cpu):
    "ADD HL,HL"
    cpu.regs.hl, cpu.regs.f = alu.add16(cpu.regs.hl, cpu.regs.hl, cpu.regs.f)
    cpu.add_t_states(7)


@base(0x39)
def add_hl_sp(cpu):
    "ADD HL,SP"
    cpu.regs.hl, cpu.regs.f = alu.add16(cpu.regs.hl, cpu.regs.sp, cpu.regs.f)
    cpu.add_t_states(7)


## ─── INC rr  (0x03/0x13/0x23/0x33) ───

@base(0x03)
def inc_bc(cpu):
    "INC BC"
    cpu.regs.bc = (cpu.regs.bc + 1) & 0xFFFF
    cpu.add_t_states(2)


@base(0x13)
def inc_de(cpu):
    "INC DE"
    cpu.regs.de = (cpu.regs.de + 1) & 0xFFFF
    cpu.add_t_states(2)


@base(0x23)
def inc_hl(cpu):
    "INC HL"
    cpu.regs.hl = (cpu.regs.hl + 1) & 0xFFFF
    cpu.add_t_states(2)


@base(0x33)
def inc_sp(cpu):
    "INC SP"
    cpu.regs.sp = (cpu.regs.sp + 1) & 0xFFFF
    cpu.add_t_states(2)


## ─── DEC rr  (0x0B/0x1B/0x2B/0x3B) ───

@base(0x0B)
def dec_bc(cpu):
    "DEC BC"
    cpu.regs.bc = (cpu.regs.bc - 1) & 0xFFFF
    cpu.add_t_states(2)


@base(0x1B)
def dec_de(cpu):
    "DEC DE"
    cpu.regs.de = (cpu.regs.de - 1) & 0xFFFF
    cpu.add_t_states(2)


@base(0x2B)
def dec_hl(cpu):
    "DEC HL"
    cpu.regs.hl = (cpu.regs.hl - 1) & 0xFFFF
    cpu.add_t_states(2)


@base(0x3B)
def dec_sp(cpu):
    "DEC SP"
    cpu.regs.sp = (cpu.regs.sp - 1) & 0xFFFF
    cpu.add_t_states(2)


## ─── ED  ADC HL,rr  (0x4A/0x5A/0x6A/0x7A) ───

@ed(0x4A)
def adc_hl_bc(cpu):
    "ADC HL,BC"
    cpu.regs.hl, cpu.regs.f = alu.adc16(cpu.regs.hl, cpu.regs.bc, cpu.regs.f & FLAG_C)
    cpu.add_t_states(7)


@ed(0x5A)
def adc_hl_de(cpu):
    "ADC HL,DE"
    cpu.regs.hl, cpu.regs.f = alu.adc16(cpu.regs.hl, cpu.regs.de, cpu.regs.f & FLAG_C)
    cpu.add_t_states(7)


@ed(0x6A)
def adc_hl_hl(cpu):
    "ADC HL,HL"
    cpu.regs.hl, cpu.regs.f = alu.adc16(cpu.regs.hl, cpu.regs.hl, cpu.regs.f & FLAG_C)
    cpu.add_t_states(7)


@ed(0x7A)
def adc_hl_sp(cpu):
    "ADC HL,SP"
    cpu.regs.hl, cpu.regs.f = alu.adc16(cpu.regs.hl, cpu.regs.sp, cpu.regs.f & FLAG_C)
    cpu.add_t_states(7)


## ─── ED  SBC HL,rr  (0x42/0x52/0x62/0x72) ───

@ed(0x42)
def sbc_hl_bc(cpu):
    "SBC HL,BC"
    cpu.regs.hl, cpu.regs.f = alu.sbc16(cpu.regs.hl, cpu.regs.bc, cpu.regs.f & FLAG_C)
    cpu.add_t_states(7)


@ed(0x52)
def sbc_hl_de(cpu):
    "SBC HL,DE"
    cpu.regs.hl, cpu.regs.f = alu.sbc16(cpu.regs.hl, cpu.regs.de, cpu.regs.f & FLAG_C)
    cpu.add_t_states(7)


@ed(0x62)
def sbc_hl_hl(cpu):
    "SBC HL,HL"
    cpu.regs.hl, cpu.regs.f = alu.sbc16(cpu.regs.hl, cpu.regs.hl, cpu.regs.f & FLAG_C)
    cpu.add_t_states(7)


@ed(0x72)
def sbc_hl_sp(cpu):
    "SBC HL,SP"
    cpu.regs.hl, cpu.regs.f = alu.sbc16(cpu.regs.hl, cpu.regs.sp, cpu.regs.f & FLAG_C)
    cpu.add_t_states(7)
