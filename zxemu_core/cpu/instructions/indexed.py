"""DD/FD-prefixed (indexed) instructions.

Only opcodes that touch HL / H / L / (HL) change under a DD/FD prefix:
HL becomes IX/IY, H/L become IXH/IXL (or IYH/IYL), and (HL) becomes
(IX+d)/(IY+d). Every other opcode behaves as the unprefixed instruction, so
only the affected opcodes live in INDEXED_TABLE; Z80._step_indexed falls back
to BASE_TABLE otherwise.

Which index register is active (IX vs IY) is read at runtime from
cpu._idx_pair / cpu._idx_hi / cpu._idx_lo, set by Z80._step_indexed, so one
table serves both prefixes. Mnemonics below are written with IX for brevity.
"""

from __future__ import annotations

from .. import flags as alu
from ._dispatch import indexed, signed8
from .arith8 import ALU_OPS


def _idx_addr(cpu, displacement: int) -> int:
    return (getattr(cpu.regs, cpu._idx_pair) + displacement) & 0xFFFF



## ─── LD r,r' forms touched by the index prefix ───

@indexed(0x44)
def ld_b_idxh(cpu):
    "LD B,IXH"
    cpu.regs.b = getattr(cpu.regs, cpu._idx_hi)


@indexed(0x45)
def ld_b_idxl(cpu):
    "LD B,IXL"
    cpu.regs.b = getattr(cpu.regs, cpu._idx_lo)


@indexed(0x46)
def ld_b_memidx(cpu):
    "LD B,(IX+d)"
    d = signed8(cpu.fetch_byte())
    cpu.regs.b = cpu.read_mem(_idx_addr(cpu, d))


@indexed(0x4C)
def ld_c_idxh(cpu):
    "LD C,IXH"
    cpu.regs.c = getattr(cpu.regs, cpu._idx_hi)


@indexed(0x4D)
def ld_c_idxl(cpu):
    "LD C,IXL"
    cpu.regs.c = getattr(cpu.regs, cpu._idx_lo)


@indexed(0x4E)
def ld_c_memidx(cpu):
    "LD C,(IX+d)"
    d = signed8(cpu.fetch_byte())
    cpu.regs.c = cpu.read_mem(_idx_addr(cpu, d))


@indexed(0x54)
def ld_d_idxh(cpu):
    "LD D,IXH"
    cpu.regs.d = getattr(cpu.regs, cpu._idx_hi)


@indexed(0x55)
def ld_d_idxl(cpu):
    "LD D,IXL"
    cpu.regs.d = getattr(cpu.regs, cpu._idx_lo)


@indexed(0x56)
def ld_d_memidx(cpu):
    "LD D,(IX+d)"
    d = signed8(cpu.fetch_byte())
    cpu.regs.d = cpu.read_mem(_idx_addr(cpu, d))


@indexed(0x5C)
def ld_e_idxh(cpu):
    "LD E,IXH"
    cpu.regs.e = getattr(cpu.regs, cpu._idx_hi)


@indexed(0x5D)
def ld_e_idxl(cpu):
    "LD E,IXL"
    cpu.regs.e = getattr(cpu.regs, cpu._idx_lo)


@indexed(0x5E)
def ld_e_memidx(cpu):
    "LD E,(IX+d)"
    d = signed8(cpu.fetch_byte())
    cpu.regs.e = cpu.read_mem(_idx_addr(cpu, d))


@indexed(0x60)
def ld_idxh_b(cpu):
    "LD IXH,B"
    setattr(cpu.regs, cpu._idx_hi, cpu.regs.b & 0xFF)


@indexed(0x61)
def ld_idxh_c(cpu):
    "LD IXH,C"
    setattr(cpu.regs, cpu._idx_hi, cpu.regs.c & 0xFF)


@indexed(0x62)
def ld_idxh_d(cpu):
    "LD IXH,D"
    setattr(cpu.regs, cpu._idx_hi, cpu.regs.d & 0xFF)


@indexed(0x63)
def ld_idxh_e(cpu):
    "LD IXH,E"
    setattr(cpu.regs, cpu._idx_hi, cpu.regs.e & 0xFF)


@indexed(0x64)
def ld_idxh_idxh(cpu):
    "LD IXH,IXH"
    setattr(cpu.regs, cpu._idx_hi, getattr(cpu.regs, cpu._idx_hi) & 0xFF)


@indexed(0x65)
def ld_idxh_idxl(cpu):
    "LD IXH,IXL"
    setattr(cpu.regs, cpu._idx_hi, getattr(cpu.regs, cpu._idx_lo) & 0xFF)


@indexed(0x66)
def ld_h_memidx(cpu):
    "LD H,(IX+d)"
    d = signed8(cpu.fetch_byte())
    cpu.regs.h = cpu.read_mem(_idx_addr(cpu, d))


@indexed(0x67)
def ld_idxh_a(cpu):
    "LD IXH,A"
    setattr(cpu.regs, cpu._idx_hi, cpu.regs.a & 0xFF)


@indexed(0x68)
def ld_idxl_b(cpu):
    "LD IXL,B"
    setattr(cpu.regs, cpu._idx_lo, cpu.regs.b & 0xFF)


@indexed(0x69)
def ld_idxl_c(cpu):
    "LD IXL,C"
    setattr(cpu.regs, cpu._idx_lo, cpu.regs.c & 0xFF)


@indexed(0x6A)
def ld_idxl_d(cpu):
    "LD IXL,D"
    setattr(cpu.regs, cpu._idx_lo, cpu.regs.d & 0xFF)


@indexed(0x6B)
def ld_idxl_e(cpu):
    "LD IXL,E"
    setattr(cpu.regs, cpu._idx_lo, cpu.regs.e & 0xFF)


@indexed(0x6C)
def ld_idxl_idxh(cpu):
    "LD IXL,IXH"
    setattr(cpu.regs, cpu._idx_lo, getattr(cpu.regs, cpu._idx_hi) & 0xFF)


@indexed(0x6D)
def ld_idxl_idxl(cpu):
    "LD IXL,IXL"
    setattr(cpu.regs, cpu._idx_lo, getattr(cpu.regs, cpu._idx_lo) & 0xFF)


@indexed(0x6E)
def ld_l_memidx(cpu):
    "LD L,(IX+d)"
    d = signed8(cpu.fetch_byte())
    cpu.regs.l = cpu.read_mem(_idx_addr(cpu, d))


@indexed(0x6F)
def ld_idxl_a(cpu):
    "LD IXL,A"
    setattr(cpu.regs, cpu._idx_lo, cpu.regs.a & 0xFF)


@indexed(0x70)
def ld_memidx_b(cpu):
    "LD (IX+d),B"
    d = signed8(cpu.fetch_byte())
    cpu.write_mem(_idx_addr(cpu, d), cpu.regs.b)


@indexed(0x71)
def ld_memidx_c(cpu):
    "LD (IX+d),C"
    d = signed8(cpu.fetch_byte())
    cpu.write_mem(_idx_addr(cpu, d), cpu.regs.c)


@indexed(0x72)
def ld_memidx_d(cpu):
    "LD (IX+d),D"
    d = signed8(cpu.fetch_byte())
    cpu.write_mem(_idx_addr(cpu, d), cpu.regs.d)


@indexed(0x73)
def ld_memidx_e(cpu):
    "LD (IX+d),E"
    d = signed8(cpu.fetch_byte())
    cpu.write_mem(_idx_addr(cpu, d), cpu.regs.e)


@indexed(0x74)
def ld_memidx_h(cpu):
    "LD (IX+d),H"
    d = signed8(cpu.fetch_byte())
    cpu.write_mem(_idx_addr(cpu, d), cpu.regs.h)


@indexed(0x75)
def ld_memidx_l(cpu):
    "LD (IX+d),L"
    d = signed8(cpu.fetch_byte())
    cpu.write_mem(_idx_addr(cpu, d), cpu.regs.l)


@indexed(0x77)
def ld_memidx_a(cpu):
    "LD (IX+d),A"
    d = signed8(cpu.fetch_byte())
    cpu.write_mem(_idx_addr(cpu, d), cpu.regs.a)


@indexed(0x7C)
def ld_a_idxh(cpu):
    "LD A,IXH"
    cpu.regs.a = getattr(cpu.regs, cpu._idx_hi)


@indexed(0x7D)
def ld_a_idxl(cpu):
    "LD A,IXL"
    cpu.regs.a = getattr(cpu.regs, cpu._idx_lo)


@indexed(0x7E)
def ld_a_memidx(cpu):
    "LD A,(IX+d)"
    d = signed8(cpu.fetch_byte())
    cpu.regs.a = cpu.read_mem(_idx_addr(cpu, d))



## ─── ALU A,r forms touched by the index prefix (src = IXH/IXL/(IX+d)) ───

@indexed(0x84)
def alu0_idxh(cpu):
    "ADD A,IXH"
    ALU_OPS[0](cpu, getattr(cpu.regs, cpu._idx_hi))


@indexed(0x85)
def alu0_idxl(cpu):
    "ADD A,IXL"
    ALU_OPS[0](cpu, getattr(cpu.regs, cpu._idx_lo))


@indexed(0x86)
def alu0_memidx(cpu):
    "ADD A,(IX+d)"
    d = signed8(cpu.fetch_byte())
    ALU_OPS[0](cpu, cpu.read_mem(_idx_addr(cpu, d)))


@indexed(0x8C)
def alu1_idxh(cpu):
    "ADC A,IXH"
    ALU_OPS[1](cpu, getattr(cpu.regs, cpu._idx_hi))


@indexed(0x8D)
def alu1_idxl(cpu):
    "ADC A,IXL"
    ALU_OPS[1](cpu, getattr(cpu.regs, cpu._idx_lo))


@indexed(0x8E)
def alu1_memidx(cpu):
    "ADC A,(IX+d)"
    d = signed8(cpu.fetch_byte())
    ALU_OPS[1](cpu, cpu.read_mem(_idx_addr(cpu, d)))


@indexed(0x94)
def alu2_idxh(cpu):
    "SUB,IXH"
    ALU_OPS[2](cpu, getattr(cpu.regs, cpu._idx_hi))


@indexed(0x95)
def alu2_idxl(cpu):
    "SUB,IXL"
    ALU_OPS[2](cpu, getattr(cpu.regs, cpu._idx_lo))


@indexed(0x96)
def alu2_memidx(cpu):
    "SUB,(IX+d)"
    d = signed8(cpu.fetch_byte())
    ALU_OPS[2](cpu, cpu.read_mem(_idx_addr(cpu, d)))


@indexed(0x9C)
def alu3_idxh(cpu):
    "SBC A,IXH"
    ALU_OPS[3](cpu, getattr(cpu.regs, cpu._idx_hi))


@indexed(0x9D)
def alu3_idxl(cpu):
    "SBC A,IXL"
    ALU_OPS[3](cpu, getattr(cpu.regs, cpu._idx_lo))


@indexed(0x9E)
def alu3_memidx(cpu):
    "SBC A,(IX+d)"
    d = signed8(cpu.fetch_byte())
    ALU_OPS[3](cpu, cpu.read_mem(_idx_addr(cpu, d)))


@indexed(0xA4)
def alu4_idxh(cpu):
    "AND,IXH"
    ALU_OPS[4](cpu, getattr(cpu.regs, cpu._idx_hi))


@indexed(0xA5)
def alu4_idxl(cpu):
    "AND,IXL"
    ALU_OPS[4](cpu, getattr(cpu.regs, cpu._idx_lo))


@indexed(0xA6)
def alu4_memidx(cpu):
    "AND,(IX+d)"
    d = signed8(cpu.fetch_byte())
    ALU_OPS[4](cpu, cpu.read_mem(_idx_addr(cpu, d)))


@indexed(0xAC)
def alu5_idxh(cpu):
    "XOR,IXH"
    ALU_OPS[5](cpu, getattr(cpu.regs, cpu._idx_hi))


@indexed(0xAD)
def alu5_idxl(cpu):
    "XOR,IXL"
    ALU_OPS[5](cpu, getattr(cpu.regs, cpu._idx_lo))


@indexed(0xAE)
def alu5_memidx(cpu):
    "XOR,(IX+d)"
    d = signed8(cpu.fetch_byte())
    ALU_OPS[5](cpu, cpu.read_mem(_idx_addr(cpu, d)))


@indexed(0xB4)
def alu6_idxh(cpu):
    "OR,IXH"
    ALU_OPS[6](cpu, getattr(cpu.regs, cpu._idx_hi))


@indexed(0xB5)
def alu6_idxl(cpu):
    "OR,IXL"
    ALU_OPS[6](cpu, getattr(cpu.regs, cpu._idx_lo))


@indexed(0xB6)
def alu6_memidx(cpu):
    "OR,(IX+d)"
    d = signed8(cpu.fetch_byte())
    ALU_OPS[6](cpu, cpu.read_mem(_idx_addr(cpu, d)))


@indexed(0xBC)
def alu7_idxh(cpu):
    "CP,IXH"
    ALU_OPS[7](cpu, getattr(cpu.regs, cpu._idx_hi))


@indexed(0xBD)
def alu7_idxl(cpu):
    "CP,IXL"
    ALU_OPS[7](cpu, getattr(cpu.regs, cpu._idx_lo))


@indexed(0xBE)
def alu7_memidx(cpu):
    "CP,(IX+d)"
    d = signed8(cpu.fetch_byte())
    ALU_OPS[7](cpu, cpu.read_mem(_idx_addr(cpu, d)))



## ─── INC/DEC/LD-immediate for IXH/IXL/(IX+d) ───

@indexed(0x24)
def inc_idxh(cpu):
    "INC IXH"
    result, f = alu.inc8(getattr(cpu.regs, cpu._idx_hi), cpu.regs.f)
    setattr(cpu.regs, cpu._idx_hi, result)
    cpu.regs.f = f


@indexed(0x25)
def dec_idxh(cpu):
    "DEC IXH"
    result, f = alu.dec8(getattr(cpu.regs, cpu._idx_hi), cpu.regs.f)
    setattr(cpu.regs, cpu._idx_hi, result)
    cpu.regs.f = f


@indexed(0x26)
def ld_idxh_n(cpu):
    "LD IXH,n"
    setattr(cpu.regs, cpu._idx_hi, cpu.fetch_byte())


@indexed(0x2C)
def inc_idxl(cpu):
    "INC IXL"
    result, f = alu.inc8(getattr(cpu.regs, cpu._idx_lo), cpu.regs.f)
    setattr(cpu.regs, cpu._idx_lo, result)
    cpu.regs.f = f


@indexed(0x2D)
def dec_idxl(cpu):
    "DEC IXL"
    result, f = alu.dec8(getattr(cpu.regs, cpu._idx_lo), cpu.regs.f)
    setattr(cpu.regs, cpu._idx_lo, result)
    cpu.regs.f = f


@indexed(0x2E)
def ld_idxl_n(cpu):
    "LD IXL,n"
    setattr(cpu.regs, cpu._idx_lo, cpu.fetch_byte())


@indexed(0x34)
def inc_memidx(cpu):
    "INC (IX+d)"
    d = signed8(cpu.fetch_byte())
    addr = _idx_addr(cpu, d)
    result, f = alu.inc8(cpu.read_mem(addr), cpu.regs.f)
    cpu.write_mem(addr, result)
    cpu.add_t_states(1)
    cpu.regs.f = f


@indexed(0x35)
def dec_memidx(cpu):
    "DEC (IX+d)"
    d = signed8(cpu.fetch_byte())
    addr = _idx_addr(cpu, d)
    result, f = alu.dec8(cpu.read_mem(addr), cpu.regs.f)
    cpu.write_mem(addr, result)
    cpu.add_t_states(1)
    cpu.regs.f = f


@indexed(0x36)
def ld_memidx_n(cpu):
    "LD (IX+d),n"
    d = signed8(cpu.fetch_byte())
    addr = _idx_addr(cpu, d)
    n = cpu.fetch_byte()
    cpu.write_mem(addr, n)



## ─── 16-bit index-register ops ───

@indexed(0x09)
def add_idx_bc(cpu):
    "ADD IX,BC"
    result, cpu.regs.f = alu.add16(getattr(cpu.regs, cpu._idx_pair), cpu.regs.bc, cpu.regs.f)
    setattr(cpu.regs, cpu._idx_pair, result)
    cpu.add_t_states(7)


@indexed(0x19)
def add_idx_de(cpu):
    "ADD IX,DE"
    result, cpu.regs.f = alu.add16(getattr(cpu.regs, cpu._idx_pair), cpu.regs.de, cpu.regs.f)
    setattr(cpu.regs, cpu._idx_pair, result)
    cpu.add_t_states(7)


@indexed(0x29)
def add_idx_idx(cpu):
    "ADD IX,IX"
    idx = getattr(cpu.regs, cpu._idx_pair)
    result, cpu.regs.f = alu.add16(idx, idx, cpu.regs.f)
    setattr(cpu.regs, cpu._idx_pair, result)
    cpu.add_t_states(7)


@indexed(0x39)
def add_idx_sp(cpu):
    "ADD IX,SP"
    result, cpu.regs.f = alu.add16(getattr(cpu.regs, cpu._idx_pair), cpu.regs.sp, cpu.regs.f)
    setattr(cpu.regs, cpu._idx_pair, result)
    cpu.add_t_states(7)


@indexed(0x21)
def ld_idx_nn(cpu):
    "LD IX,nn"
    setattr(cpu.regs, cpu._idx_pair, cpu.fetch_word())


@indexed(0x22)
def ld_nn_idx(cpu):
    "LD (nn),IX"
    addr = cpu.fetch_word()
    idx = getattr(cpu.regs, cpu._idx_pair)
    cpu.write_mem(addr, idx & 0xFF)
    cpu.write_mem((addr + 1) & 0xFFFF, (idx >> 8) & 0xFF)


@indexed(0x2A)
def ld_idx_nn_mem(cpu):
    "LD IX,(nn)"
    addr = cpu.fetch_word()
    lo = cpu.read_mem(addr)
    hi = cpu.read_mem((addr + 1) & 0xFFFF)
    setattr(cpu.regs, cpu._idx_pair, (hi << 8) | lo)


@indexed(0x23)
def inc_idx(cpu):
    "INC IX"
    setattr(cpu.regs, cpu._idx_pair, (getattr(cpu.regs, cpu._idx_pair) + 1) & 0xFFFF)
    cpu.add_t_states(2)


@indexed(0x2B)
def dec_idx(cpu):
    "DEC IX"
    setattr(cpu.regs, cpu._idx_pair, (getattr(cpu.regs, cpu._idx_pair) - 1) & 0xFFFF)
    cpu.add_t_states(2)


@indexed(0xE5)
def push_idx(cpu):
    "PUSH IX"
    cpu.push_word(getattr(cpu.regs, cpu._idx_pair))
    cpu.add_t_states(1)


@indexed(0xE1)
def pop_idx(cpu):
    "POP IX"
    setattr(cpu.regs, cpu._idx_pair, cpu.pop_word())


@indexed(0xE3)
def ex_sp_idx(cpu):
    "EX (SP),IX"
    lo = cpu.read_mem(cpu.regs.sp)
    hi = cpu.read_mem((cpu.regs.sp + 1) & 0xFFFF)
    old = getattr(cpu.regs, cpu._idx_pair)
    cpu.write_mem((cpu.regs.sp + 1) & 0xFFFF, (old >> 8) & 0xFF)
    cpu.write_mem(cpu.regs.sp, old & 0xFF)
    setattr(cpu.regs, cpu._idx_pair, (hi << 8) | lo)
    cpu.add_t_states(3)


@indexed(0xE9)
def jp_idx(cpu):
    "JP (IX)"
    cpu.regs.pc = getattr(cpu.regs, cpu._idx_pair)


@indexed(0xF9)
def ld_sp_idx(cpu):
    "LD SP,IX"
    cpu.regs.sp = getattr(cpu.regs, cpu._idx_pair)
    cpu.add_t_states(2)


