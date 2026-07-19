"""Register exchanges: EX AF,AF' ; EXX ; EX DE,HL ; EX (SP),HL."""

from __future__ import annotations

from ._dispatch import base


## ─── EX AF,AF'  (0x08) ───

@base(0x08)
def ex_af_af2(cpu):
    "EX AF,AF'"
    cpu.regs.af, cpu.regs.af2 = cpu.regs.af2, cpu.regs.af


## ─── EXX  (0xD9) ───

@base(0xD9)
def exx(cpu):
    "EXX"
    cpu.regs.bc, cpu.regs.bc2 = cpu.regs.bc2, cpu.regs.bc
    cpu.regs.de, cpu.regs.de2 = cpu.regs.de2, cpu.regs.de
    cpu.regs.hl, cpu.regs.hl2 = cpu.regs.hl2, cpu.regs.hl


## ─── EX DE,HL  (0xEB) ───

@base(0xEB)
def ex_de_hl(cpu):
    "EX DE,HL"
    cpu.regs.de, cpu.regs.hl = cpu.regs.hl, cpu.regs.de


## ─── EX (SP),HL  (0xE3) ───

@base(0xE3)
def ex_sp_hl(cpu):
    "EX (SP),HL"
    lo = cpu.read_mem(cpu.regs.sp)
    hi = cpu.read_mem((cpu.regs.sp + 1) & 0xFFFF)
    old_hl = cpu.regs.hl
    cpu.write_mem((cpu.regs.sp + 1) & 0xFFFF, (old_hl >> 8) & 0xFF)
    cpu.write_mem(cpu.regs.sp, old_hl & 0xFF)
    cpu.regs.hl = (hi << 8) | lo
    cpu.add_t_states(3)
