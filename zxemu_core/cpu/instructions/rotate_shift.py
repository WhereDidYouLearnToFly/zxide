"""Rotates and shifts: accumulator RLCA/RRCA/RLA/RRA, the CB rotate/shift
grid (0x00-0x3F), and the ED digit-rotate pair RRD/RLD.

The CB grid applies one of 8 operations (RLC RRC RL RR SLA SRA SLL SRL) to
a register or (HL); flags.py holds the actual bit math.
"""

from __future__ import annotations

from .. import flags as alu
from ..registers import FLAG_C, FLAG_P, FLAG_S, FLAG_X, FLAG_Y, FLAG_Z
from ._dispatch import base, cb, ed


## ─── Accumulator rotates (0x07/0x0F/0x17/0x1F) ───

@base(0x07)
def rlca(cpu):
    "RLCA"
    a = cpu.regs.a
    carry = (a >> 7) & 1
    result = ((a << 1) | carry) & 0xFF
    cpu.regs.a = result
    cpu.regs.f = (cpu.regs.f & (FLAG_S | FLAG_Z | FLAG_P)) | (result & (FLAG_Y | FLAG_X)) | carry


@base(0x0F)
def rrca(cpu):
    "RRCA"
    a = cpu.regs.a
    carry = a & 1
    result = ((a >> 1) | (carry << 7)) & 0xFF
    cpu.regs.a = result
    cpu.regs.f = (cpu.regs.f & (FLAG_S | FLAG_Z | FLAG_P)) | (result & (FLAG_Y | FLAG_X)) | carry


@base(0x17)
def rla(cpu):
    "RLA"
    a = cpu.regs.a
    old_carry = cpu.regs.f & FLAG_C
    new_carry = (a >> 7) & 1
    result = ((a << 1) | old_carry) & 0xFF
    cpu.regs.a = result
    cpu.regs.f = (cpu.regs.f & (FLAG_S | FLAG_Z | FLAG_P)) | (result & (FLAG_Y | FLAG_X)) | new_carry


@base(0x1F)
def rra(cpu):
    "RRA"
    a = cpu.regs.a
    old_carry = cpu.regs.f & FLAG_C
    new_carry = a & 1
    result = ((a >> 1) | (old_carry << 7)) & 0xFF
    cpu.regs.a = result
    cpu.regs.f = (cpu.regs.f & (FLAG_S | FLAG_Z | FLAG_P)) | (result & (FLAG_Y | FLAG_X)) | new_carry



## ─── CB RLC r  (0x00-0x07) ───

@cb(0x00)
def rlc_b(cpu):
    "RLC B"
    cpu.regs.b, cpu.regs.f = alu.rlc(cpu.regs.b)


@cb(0x01)
def rlc_c(cpu):
    "RLC C"
    cpu.regs.c, cpu.regs.f = alu.rlc(cpu.regs.c)


@cb(0x02)
def rlc_d(cpu):
    "RLC D"
    cpu.regs.d, cpu.regs.f = alu.rlc(cpu.regs.d)


@cb(0x03)
def rlc_e(cpu):
    "RLC E"
    cpu.regs.e, cpu.regs.f = alu.rlc(cpu.regs.e)


@cb(0x04)
def rlc_h(cpu):
    "RLC H"
    cpu.regs.h, cpu.regs.f = alu.rlc(cpu.regs.h)


@cb(0x05)
def rlc_l(cpu):
    "RLC L"
    cpu.regs.l, cpu.regs.f = alu.rlc(cpu.regs.l)


@cb(0x06)
def rlc_hl(cpu):
    "RLC (HL)"
    value = cpu.read_mem(cpu.regs.hl)
    result, cpu.regs.f = alu.rlc(value)
    cpu.write_mem(cpu.regs.hl, result)
    cpu.add_t_states(1)


@cb(0x07)
def rlc_a(cpu):
    "RLC A"
    cpu.regs.a, cpu.regs.f = alu.rlc(cpu.regs.a)



## ─── CB RRC r  (0x08-0x0F) ───

@cb(0x08)
def rrc_b(cpu):
    "RRC B"
    cpu.regs.b, cpu.regs.f = alu.rrc(cpu.regs.b)


@cb(0x09)
def rrc_c(cpu):
    "RRC C"
    cpu.regs.c, cpu.regs.f = alu.rrc(cpu.regs.c)


@cb(0x0A)
def rrc_d(cpu):
    "RRC D"
    cpu.regs.d, cpu.regs.f = alu.rrc(cpu.regs.d)


@cb(0x0B)
def rrc_e(cpu):
    "RRC E"
    cpu.regs.e, cpu.regs.f = alu.rrc(cpu.regs.e)


@cb(0x0C)
def rrc_h(cpu):
    "RRC H"
    cpu.regs.h, cpu.regs.f = alu.rrc(cpu.regs.h)


@cb(0x0D)
def rrc_l(cpu):
    "RRC L"
    cpu.regs.l, cpu.regs.f = alu.rrc(cpu.regs.l)


@cb(0x0E)
def rrc_hl(cpu):
    "RRC (HL)"
    value = cpu.read_mem(cpu.regs.hl)
    result, cpu.regs.f = alu.rrc(value)
    cpu.write_mem(cpu.regs.hl, result)
    cpu.add_t_states(1)


@cb(0x0F)
def rrc_a(cpu):
    "RRC A"
    cpu.regs.a, cpu.regs.f = alu.rrc(cpu.regs.a)



## ─── CB RL r  (0x10-0x17) ───

@cb(0x10)
def rl_b(cpu):
    "RL B"
    cpu.regs.b, cpu.regs.f = alu.rl(cpu.regs.b, cpu.regs.f & FLAG_C)


@cb(0x11)
def rl_c(cpu):
    "RL C"
    cpu.regs.c, cpu.regs.f = alu.rl(cpu.regs.c, cpu.regs.f & FLAG_C)


@cb(0x12)
def rl_d(cpu):
    "RL D"
    cpu.regs.d, cpu.regs.f = alu.rl(cpu.regs.d, cpu.regs.f & FLAG_C)


@cb(0x13)
def rl_e(cpu):
    "RL E"
    cpu.regs.e, cpu.regs.f = alu.rl(cpu.regs.e, cpu.regs.f & FLAG_C)


@cb(0x14)
def rl_h(cpu):
    "RL H"
    cpu.regs.h, cpu.regs.f = alu.rl(cpu.regs.h, cpu.regs.f & FLAG_C)


@cb(0x15)
def rl_l(cpu):
    "RL L"
    cpu.regs.l, cpu.regs.f = alu.rl(cpu.regs.l, cpu.regs.f & FLAG_C)


@cb(0x16)
def rl_hl(cpu):
    "RL (HL)"
    value = cpu.read_mem(cpu.regs.hl)
    result, cpu.regs.f = alu.rl(value, cpu.regs.f & FLAG_C)
    cpu.write_mem(cpu.regs.hl, result)
    cpu.add_t_states(1)


@cb(0x17)
def rl_a(cpu):
    "RL A"
    cpu.regs.a, cpu.regs.f = alu.rl(cpu.regs.a, cpu.regs.f & FLAG_C)



## ─── CB RR r  (0x18-0x1F) ───

@cb(0x18)
def rr_b(cpu):
    "RR B"
    cpu.regs.b, cpu.regs.f = alu.rr_(cpu.regs.b, cpu.regs.f & FLAG_C)


@cb(0x19)
def rr_c(cpu):
    "RR C"
    cpu.regs.c, cpu.regs.f = alu.rr_(cpu.regs.c, cpu.regs.f & FLAG_C)


@cb(0x1A)
def rr_d(cpu):
    "RR D"
    cpu.regs.d, cpu.regs.f = alu.rr_(cpu.regs.d, cpu.regs.f & FLAG_C)


@cb(0x1B)
def rr_e(cpu):
    "RR E"
    cpu.regs.e, cpu.regs.f = alu.rr_(cpu.regs.e, cpu.regs.f & FLAG_C)


@cb(0x1C)
def rr_h(cpu):
    "RR H"
    cpu.regs.h, cpu.regs.f = alu.rr_(cpu.regs.h, cpu.regs.f & FLAG_C)


@cb(0x1D)
def rr_l(cpu):
    "RR L"
    cpu.regs.l, cpu.regs.f = alu.rr_(cpu.regs.l, cpu.regs.f & FLAG_C)


@cb(0x1E)
def rr_hl(cpu):
    "RR (HL)"
    value = cpu.read_mem(cpu.regs.hl)
    result, cpu.regs.f = alu.rr_(value, cpu.regs.f & FLAG_C)
    cpu.write_mem(cpu.regs.hl, result)
    cpu.add_t_states(1)


@cb(0x1F)
def rr_a(cpu):
    "RR A"
    cpu.regs.a, cpu.regs.f = alu.rr_(cpu.regs.a, cpu.regs.f & FLAG_C)



## ─── CB SLA r  (0x20-0x27) ───

@cb(0x20)
def sla_b(cpu):
    "SLA B"
    cpu.regs.b, cpu.regs.f = alu.sla(cpu.regs.b)


@cb(0x21)
def sla_c(cpu):
    "SLA C"
    cpu.regs.c, cpu.regs.f = alu.sla(cpu.regs.c)


@cb(0x22)
def sla_d(cpu):
    "SLA D"
    cpu.regs.d, cpu.regs.f = alu.sla(cpu.regs.d)


@cb(0x23)
def sla_e(cpu):
    "SLA E"
    cpu.regs.e, cpu.regs.f = alu.sla(cpu.regs.e)


@cb(0x24)
def sla_h(cpu):
    "SLA H"
    cpu.regs.h, cpu.regs.f = alu.sla(cpu.regs.h)


@cb(0x25)
def sla_l(cpu):
    "SLA L"
    cpu.regs.l, cpu.regs.f = alu.sla(cpu.regs.l)


@cb(0x26)
def sla_hl(cpu):
    "SLA (HL)"
    value = cpu.read_mem(cpu.regs.hl)
    result, cpu.regs.f = alu.sla(value)
    cpu.write_mem(cpu.regs.hl, result)
    cpu.add_t_states(1)


@cb(0x27)
def sla_a(cpu):
    "SLA A"
    cpu.regs.a, cpu.regs.f = alu.sla(cpu.regs.a)



## ─── CB SRA r  (0x28-0x2F) ───

@cb(0x28)
def sra_b(cpu):
    "SRA B"
    cpu.regs.b, cpu.regs.f = alu.sra(cpu.regs.b)


@cb(0x29)
def sra_c(cpu):
    "SRA C"
    cpu.regs.c, cpu.regs.f = alu.sra(cpu.regs.c)


@cb(0x2A)
def sra_d(cpu):
    "SRA D"
    cpu.regs.d, cpu.regs.f = alu.sra(cpu.regs.d)


@cb(0x2B)
def sra_e(cpu):
    "SRA E"
    cpu.regs.e, cpu.regs.f = alu.sra(cpu.regs.e)


@cb(0x2C)
def sra_h(cpu):
    "SRA H"
    cpu.regs.h, cpu.regs.f = alu.sra(cpu.regs.h)


@cb(0x2D)
def sra_l(cpu):
    "SRA L"
    cpu.regs.l, cpu.regs.f = alu.sra(cpu.regs.l)


@cb(0x2E)
def sra_hl(cpu):
    "SRA (HL)"
    value = cpu.read_mem(cpu.regs.hl)
    result, cpu.regs.f = alu.sra(value)
    cpu.write_mem(cpu.regs.hl, result)
    cpu.add_t_states(1)


@cb(0x2F)
def sra_a(cpu):
    "SRA A"
    cpu.regs.a, cpu.regs.f = alu.sra(cpu.regs.a)



## ─── CB SLL r  (0x30-0x37) ───

@cb(0x30)
def sll_b(cpu):
    "SLL B"
    cpu.regs.b, cpu.regs.f = alu.sll(cpu.regs.b)


@cb(0x31)
def sll_c(cpu):
    "SLL C"
    cpu.regs.c, cpu.regs.f = alu.sll(cpu.regs.c)


@cb(0x32)
def sll_d(cpu):
    "SLL D"
    cpu.regs.d, cpu.regs.f = alu.sll(cpu.regs.d)


@cb(0x33)
def sll_e(cpu):
    "SLL E"
    cpu.regs.e, cpu.regs.f = alu.sll(cpu.regs.e)


@cb(0x34)
def sll_h(cpu):
    "SLL H"
    cpu.regs.h, cpu.regs.f = alu.sll(cpu.regs.h)


@cb(0x35)
def sll_l(cpu):
    "SLL L"
    cpu.regs.l, cpu.regs.f = alu.sll(cpu.regs.l)


@cb(0x36)
def sll_hl(cpu):
    "SLL (HL)"
    value = cpu.read_mem(cpu.regs.hl)
    result, cpu.regs.f = alu.sll(value)
    cpu.write_mem(cpu.regs.hl, result)
    cpu.add_t_states(1)


@cb(0x37)
def sll_a(cpu):
    "SLL A"
    cpu.regs.a, cpu.regs.f = alu.sll(cpu.regs.a)



## ─── CB SRL r  (0x38-0x3F) ───

@cb(0x38)
def srl_b(cpu):
    "SRL B"
    cpu.regs.b, cpu.regs.f = alu.srl(cpu.regs.b)


@cb(0x39)
def srl_c(cpu):
    "SRL C"
    cpu.regs.c, cpu.regs.f = alu.srl(cpu.regs.c)


@cb(0x3A)
def srl_d(cpu):
    "SRL D"
    cpu.regs.d, cpu.regs.f = alu.srl(cpu.regs.d)


@cb(0x3B)
def srl_e(cpu):
    "SRL E"
    cpu.regs.e, cpu.regs.f = alu.srl(cpu.regs.e)


@cb(0x3C)
def srl_h(cpu):
    "SRL H"
    cpu.regs.h, cpu.regs.f = alu.srl(cpu.regs.h)


@cb(0x3D)
def srl_l(cpu):
    "SRL L"
    cpu.regs.l, cpu.regs.f = alu.srl(cpu.regs.l)


@cb(0x3E)
def srl_hl(cpu):
    "SRL (HL)"
    value = cpu.read_mem(cpu.regs.hl)
    result, cpu.regs.f = alu.srl(value)
    cpu.write_mem(cpu.regs.hl, result)
    cpu.add_t_states(1)


@cb(0x3F)
def srl_a(cpu):
    "SRL A"
    cpu.regs.a, cpu.regs.f = alu.srl(cpu.regs.a)



## ─── ED digit rotates RRD/RLD (0x67/0x6F) ───

@ed(0x67)
def rrd(cpu):
    "RRD"
    m = cpu.read_mem(cpu.regs.hl)
    a = cpu.regs.a
    new_a_lo = m & 0x0F
    new_m = ((a & 0x0F) << 4) | ((m >> 4) & 0x0F)
    cpu.write_mem(cpu.regs.hl, new_m)
    cpu.regs.a = (a & 0xF0) | new_a_lo
    flags = alu.sz53_of(cpu.regs.a)
    if alu.parity_even(cpu.regs.a):
        flags |= FLAG_P
    cpu.regs.f = (cpu.regs.f & FLAG_C) | flags
    cpu.add_t_states(4)


@ed(0x6F)
def rld(cpu):
    "RLD"
    m = cpu.read_mem(cpu.regs.hl)
    a = cpu.regs.a
    new_a_lo = (m >> 4) & 0x0F
    new_m = ((m & 0x0F) << 4) | (a & 0x0F)
    cpu.write_mem(cpu.regs.hl, new_m)
    cpu.regs.a = (a & 0xF0) | new_a_lo
    flags = alu.sz53_of(cpu.regs.a)
    if alu.parity_even(cpu.regs.a):
        flags |= FLAG_P
    cpu.regs.f = (cpu.regs.f & FLAG_C) | flags
    cpu.add_t_states(4)


