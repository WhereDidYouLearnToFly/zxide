"""CPU control and accumulator housekeeping: NOP, HALT, DI, EI, DAA, CPL,
SCF, CCF, plus the ED-prefixed NEG, IM 0/1/2, and I/R register loads.
"""

from __future__ import annotations

from .. import flags as alu
from ..registers import (
    FLAG_C, FLAG_H, FLAG_N, FLAG_P, FLAG_S, FLAG_X, FLAG_Y, FLAG_Z,
)
from ._dispatch import base, ed


## ─── NOP (0x00) / HALT (0x76) ───

@base(0x00)
def nop(cpu):
    "NOP"
    pass


@base(0x76)
def halt(cpu):
    "HALT"
    # PC is left pointing just past the HALT. Z80.step() burns idle cycles while
    # halted; the waking interrupt pushes this address so execution resumes here.
    cpu.halted = True


## ─── Interrupt enable/disable (0xF3/0xFB) ───

@base(0xF3)
def di(cpu):
    "DI"
    cpu.regs.iff1 = False
    cpu.regs.iff2 = False


@base(0xFB)
def ei(cpu):
    "EI"
    # NOTE: known simplification -- real hardware defers the enable by one
    # instruction (interrupts can't fire immediately after EI); here it takes
    # effect at once.
    cpu.regs.iff1 = True
    cpu.regs.iff2 = True


## ─── DAA (0x27) ───

@base(0x27)
def daa(cpu):
    "DAA"
    cpu.regs.a, cpu.regs.f = alu.daa(cpu.regs.a, cpu.regs.f)


## ─── CPL (0x2F) ───

@base(0x2F)
def cpl(cpu):
    "CPL"
    result = (~cpu.regs.a) & 0xFF
    cpu.regs.a = result
    cpu.regs.f = (
        (cpu.regs.f & (FLAG_S | FLAG_Z | FLAG_P | FLAG_C))
        | FLAG_H
        | FLAG_N
        | (result & (FLAG_Y | FLAG_X))
    )


## ─── SCF (0x37) / CCF (0x3F) ───

@base(0x37)
def scf(cpu):
    "SCF"
    # NOTE: known simplification -- the undocumented X/Y flags are taken from A
    # here; real hardware ORs them with the previous F in some cases.
    a = cpu.regs.a
    cpu.regs.f = (cpu.regs.f & (FLAG_S | FLAG_Z | FLAG_P)) | FLAG_C | (a & (FLAG_Y | FLAG_X))


@base(0x3F)
def ccf(cpu):
    "CCF"
    # NOTE: known simplification -- undocumented X/Y flags taken from A (see SCF).
    a = cpu.regs.a
    old_c = cpu.regs.f & FLAG_C
    new_h = FLAG_H if old_c else 0
    new_c = 0 if old_c else FLAG_C
    cpu.regs.f = (cpu.regs.f & (FLAG_S | FLAG_Z | FLAG_P)) | new_h | new_c | (a & (FLAG_Y | FLAG_X))


## ─── ED  NEG  (duplicate slots) ───

@ed(0x44, 0x4C, 0x54, 0x5C, 0x64, 0x6C, 0x74, 0x7C)
def neg(cpu):
    "NEG"
    cpu.regs.a, cpu.regs.f = alu.sub8(0, cpu.regs.a, 0)


## ─── ED  IM 0/1/2  (with duplicate slots) ───

@ed(0x46, 0x4E, 0x66, 0x6E)
def im_0(cpu):
    "IM 0"
    cpu.regs.im = 0


@ed(0x56, 0x76)
def im_1(cpu):
    "IM 1"
    cpu.regs.im = 1


@ed(0x5E, 0x7E)
def im_2(cpu):
    "IM 2"
    cpu.regs.im = 2


## ─── ED  I/R register loads (0x47/0x4F/0x57/0x5F) ───

@ed(0x47)
def ld_i_a(cpu):
    "LD I,A"
    cpu.regs.i = cpu.regs.a
    cpu.add_t_states(1)


@ed(0x4F)
def ld_r_a(cpu):
    "LD R,A"
    cpu.regs.r = cpu.regs.a
    cpu.add_t_states(1)


@ed(0x57)
def ld_a_i(cpu):
    "LD A,I"
    cpu.regs.a = cpu.regs.i
    flags = alu.sz53_of(cpu.regs.i) | (FLAG_P if cpu.regs.iff2 else 0)
    cpu.regs.f = (cpu.regs.f & FLAG_C) | flags
    cpu.add_t_states(1)


@ed(0x5F)
def ld_a_r(cpu):
    "LD A,R"
    cpu.regs.a = cpu.regs.r
    flags = alu.sz53_of(cpu.regs.r) | (FLAG_P if cpu.regs.iff2 else 0)
    cpu.regs.f = (cpu.regs.f & FLAG_C) | flags
    cpu.add_t_states(1)
