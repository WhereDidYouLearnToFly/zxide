"""Jumps: JP nn ; JP cc,nn ; JR ; JR cc ; DJNZ ; JP (HL).

Condition codes are spelled out per handler (NZ/Z/NC/C/PO/PE/P/M) so a reader
can see exactly which flag each conditional tests.
"""

from __future__ import annotations

from ..registers import FLAG_C, FLAG_P, FLAG_S, FLAG_Z
from ._dispatch import base, signed8


## ─── JP nn  (0xC3) ───

@base(0xC3)
def jp_nn(cpu):
    "JP nn"
    cpu.regs.pc = cpu.fetch_word()


## ─── JP cc,nn  (0xC2-0xFA) ───
# The 16-bit target is always fetched; the jump is taken only if cc holds.

@base(0xC2)
def jp_nz_nn(cpu):
    "JP NZ,nn"
    addr = cpu.fetch_word()
    if not (cpu.regs.f & FLAG_Z):
        cpu.regs.pc = addr


@base(0xCA)
def jp_z_nn(cpu):
    "JP Z,nn"
    addr = cpu.fetch_word()
    if cpu.regs.f & FLAG_Z:
        cpu.regs.pc = addr


@base(0xD2)
def jp_nc_nn(cpu):
    "JP NC,nn"
    addr = cpu.fetch_word()
    if not (cpu.regs.f & FLAG_C):
        cpu.regs.pc = addr


@base(0xDA)
def jp_c_nn(cpu):
    "JP C,nn"
    addr = cpu.fetch_word()
    if cpu.regs.f & FLAG_C:
        cpu.regs.pc = addr


@base(0xE2)
def jp_po_nn(cpu):
    "JP PO,nn"
    addr = cpu.fetch_word()
    if not (cpu.regs.f & FLAG_P):
        cpu.regs.pc = addr


@base(0xEA)
def jp_pe_nn(cpu):
    "JP PE,nn"
    addr = cpu.fetch_word()
    if cpu.regs.f & FLAG_P:
        cpu.regs.pc = addr


@base(0xF2)
def jp_p_nn(cpu):
    "JP P,nn"
    addr = cpu.fetch_word()
    if not (cpu.regs.f & FLAG_S):
        cpu.regs.pc = addr


@base(0xFA)
def jp_m_nn(cpu):
    "JP M,nn"
    addr = cpu.fetch_word()
    if cpu.regs.f & FLAG_S:
        cpu.regs.pc = addr


## ─── JR e  (0x18) ───

@base(0x18)
def jr(cpu):
    "JR e"
    offset = signed8(cpu.fetch_byte())
    cpu.regs.pc = (cpu.regs.pc + offset) & 0xFFFF
    cpu.add_t_states(5)


## ─── JR cc,e  (0x20/0x28/0x30/0x38) ───
# The displacement is always fetched; +5 T-states only when the branch is taken.

@base(0x20)
def jr_nz(cpu):
    "JR NZ,e"
    offset = signed8(cpu.fetch_byte())
    if not (cpu.regs.f & FLAG_Z):
        cpu.regs.pc = (cpu.regs.pc + offset) & 0xFFFF
        cpu.add_t_states(5)


@base(0x28)
def jr_z(cpu):
    "JR Z,e"
    offset = signed8(cpu.fetch_byte())
    if cpu.regs.f & FLAG_Z:
        cpu.regs.pc = (cpu.regs.pc + offset) & 0xFFFF
        cpu.add_t_states(5)


@base(0x30)
def jr_nc(cpu):
    "JR NC,e"
    offset = signed8(cpu.fetch_byte())
    if not (cpu.regs.f & FLAG_C):
        cpu.regs.pc = (cpu.regs.pc + offset) & 0xFFFF
        cpu.add_t_states(5)


@base(0x38)
def jr_c(cpu):
    "JR C,e"
    offset = signed8(cpu.fetch_byte())
    if cpu.regs.f & FLAG_C:
        cpu.regs.pc = (cpu.regs.pc + offset) & 0xFFFF
        cpu.add_t_states(5)


## ─── DJNZ e  (0x10) ───

@base(0x10)
def djnz(cpu):
    "DJNZ e"
    cpu.add_t_states(1)
    cpu.regs.b = (cpu.regs.b - 1) & 0xFF
    offset = signed8(cpu.fetch_byte())
    if cpu.regs.b != 0:
        cpu.regs.pc = (cpu.regs.pc + offset) & 0xFFFF
        cpu.add_t_states(5)


## ─── JP (HL)  (0xE9) ───

@base(0xE9)
def jp_hl(cpu):
    "JP (HL)"
    cpu.regs.pc = cpu.regs.hl
