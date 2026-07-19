"""16-bit loads: LD rr,nn ; LD (nn),HL / HL,(nn) ; LD SP,HL ; PUSH/POP ;
plus the ED-prefixed LD (nn),rr / LD rr,(nn) forms.

Pair order for LD/INC/DEC-style opcodes is BC,DE,HL,SP; PUSH/POP swap SP for AF.
"""

from __future__ import annotations

from ._dispatch import base, ed


## ─── LD rr,nn  (0x01/0x11/0x21/0x31) ───

@base(0x01)
def ld_bc_nn(cpu):
    "LD BC,nn"
    cpu.regs.bc = cpu.fetch_word()


@base(0x11)
def ld_de_nn(cpu):
    "LD DE,nn"
    cpu.regs.de = cpu.fetch_word()


@base(0x21)
def ld_hl_nn(cpu):
    "LD HL,nn"
    cpu.regs.hl = cpu.fetch_word()


@base(0x31)
def ld_sp_nn(cpu):
    "LD SP,nn"
    cpu.regs.sp = cpu.fetch_word()


## ─── LD (nn),HL / LD HL,(nn)  (0x22/0x2A) ───

@base(0x22)
def ld_nn_mem_hl(cpu):
    "LD (nn),HL"
    addr = cpu.fetch_word()
    cpu.write_mem(addr, cpu.regs.l)
    cpu.write_mem((addr + 1) & 0xFFFF, cpu.regs.h)


@base(0x2A)
def ld_hl_nn_mem(cpu):
    "LD HL,(nn)"
    addr = cpu.fetch_word()
    lo = cpu.read_mem(addr)
    hi = cpu.read_mem((addr + 1) & 0xFFFF)
    cpu.regs.hl = (hi << 8) | lo


## ─── LD SP,HL  (0xF9) ───

@base(0xF9)
def ld_sp_hl(cpu):
    "LD SP,HL"
    cpu.regs.sp = cpu.regs.hl
    cpu.add_t_states(2)


## ─── PUSH rr  (0xC5/0xD5/0xE5/0xF5) ───

@base(0xC5)
def push_bc(cpu):
    "PUSH BC"
    cpu.push_word(cpu.regs.bc)
    cpu.add_t_states(1)


@base(0xD5)
def push_de(cpu):
    "PUSH DE"
    cpu.push_word(cpu.regs.de)
    cpu.add_t_states(1)


@base(0xE5)
def push_hl(cpu):
    "PUSH HL"
    cpu.push_word(cpu.regs.hl)
    cpu.add_t_states(1)


@base(0xF5)
def push_af(cpu):
    "PUSH AF"
    cpu.push_word(cpu.regs.af)
    cpu.add_t_states(1)


## ─── POP rr  (0xC1/0xD1/0xE1/0xF1) ───

@base(0xC1)
def pop_bc(cpu):
    "POP BC"
    cpu.regs.bc = cpu.pop_word()


@base(0xD1)
def pop_de(cpu):
    "POP DE"
    cpu.regs.de = cpu.pop_word()


@base(0xE1)
def pop_hl(cpu):
    "POP HL"
    cpu.regs.hl = cpu.pop_word()


@base(0xF1)
def pop_af(cpu):
    "POP AF"
    cpu.regs.af = cpu.pop_word()


## ─── ED  LD (nn),rr  (0x43/0x53/0x63/0x73) ───

@ed(0x43)
def ld_nn_mem_bc(cpu):
    "LD (nn),BC"
    _store_pair(cpu, cpu.regs.bc)


@ed(0x53)
def ld_nn_mem_de(cpu):
    "LD (nn),DE"
    _store_pair(cpu, cpu.regs.de)


@ed(0x63)
def ld_nn_mem_hl_ed(cpu):
    "LD (nn),HL"
    _store_pair(cpu, cpu.regs.hl)


@ed(0x73)
def ld_nn_mem_sp(cpu):
    "LD (nn),SP"
    _store_pair(cpu, cpu.regs.sp)


def _store_pair(cpu, value: int) -> None:
    addr = cpu.fetch_word()
    cpu.write_mem(addr, value & 0xFF)
    cpu.write_mem((addr + 1) & 0xFFFF, (value >> 8) & 0xFF)


## ─── ED  LD rr,(nn)  (0x4B/0x5B/0x6B/0x7B) ───

@ed(0x4B)
def ld_bc_nn_mem(cpu):
    "LD BC,(nn)"
    cpu.regs.bc = _load_pair(cpu)


@ed(0x5B)
def ld_de_nn_mem(cpu):
    "LD DE,(nn)"
    cpu.regs.de = _load_pair(cpu)


@ed(0x6B)
def ld_hl_nn_mem_ed(cpu):
    "LD HL,(nn)"
    cpu.regs.hl = _load_pair(cpu)


@ed(0x7B)
def ld_sp_nn_mem(cpu):
    "LD SP,(nn)"
    cpu.regs.sp = _load_pair(cpu)


def _load_pair(cpu) -> int:
    addr = cpu.fetch_word()
    lo = cpu.read_mem(addr)
    hi = cpu.read_mem((addr + 1) & 0xFFFF)
    return (hi << 8) | lo
