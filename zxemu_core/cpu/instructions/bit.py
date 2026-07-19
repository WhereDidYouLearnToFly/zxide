"""CB bit operations: BIT b,r (0x40-0x7F), RES b,r (0x80-0xBF), SET b,r (0xC0-0xFF).

b is the bit number (0-7), r selects the register or (HL). The three
operations (test / reset / set) are explicit; there is one handler per
opcode so any instruction is directly findable by its mnemonic.
"""

from __future__ import annotations

from .. import flags as alu
from ._dispatch import cb


## ─── BIT 0,r  (0x40-0x47) ───

@cb(0x40)
def bit_0_b(cpu):
    "BIT 0,B"
    cpu.regs.f = alu.bit(cpu.regs.b, 0, cpu.regs.f)


@cb(0x41)
def bit_0_c(cpu):
    "BIT 0,C"
    cpu.regs.f = alu.bit(cpu.regs.c, 0, cpu.regs.f)


@cb(0x42)
def bit_0_d(cpu):
    "BIT 0,D"
    cpu.regs.f = alu.bit(cpu.regs.d, 0, cpu.regs.f)


@cb(0x43)
def bit_0_e(cpu):
    "BIT 0,E"
    cpu.regs.f = alu.bit(cpu.regs.e, 0, cpu.regs.f)


@cb(0x44)
def bit_0_h(cpu):
    "BIT 0,H"
    cpu.regs.f = alu.bit(cpu.regs.h, 0, cpu.regs.f)


@cb(0x45)
def bit_0_l(cpu):
    "BIT 0,L"
    cpu.regs.f = alu.bit(cpu.regs.l, 0, cpu.regs.f)


@cb(0x46)
def bit_0_hl(cpu):
    "BIT 0,(HL)"
    addr = cpu.regs.hl
    value = cpu.read_mem(addr)
    # NOTE: known simplification -- for BIT b,(HL) the undocumented X/Y
    # flags come from (addr+1)>>8 (the internal MEMPTR high byte); real
    # hardware's MEMPTR update is more nuanced.
    cpu.regs.f = alu.bit_memory(value, 0, cpu.regs.f, ((addr + 1) >> 8) & 0xFF)
    cpu.add_t_states(1)


@cb(0x47)
def bit_0_a(cpu):
    "BIT 0,A"
    cpu.regs.f = alu.bit(cpu.regs.a, 0, cpu.regs.f)



## ─── BIT 1,r  (0x48-0x4F) ───

@cb(0x48)
def bit_1_b(cpu):
    "BIT 1,B"
    cpu.regs.f = alu.bit(cpu.regs.b, 1, cpu.regs.f)


@cb(0x49)
def bit_1_c(cpu):
    "BIT 1,C"
    cpu.regs.f = alu.bit(cpu.regs.c, 1, cpu.regs.f)


@cb(0x4A)
def bit_1_d(cpu):
    "BIT 1,D"
    cpu.regs.f = alu.bit(cpu.regs.d, 1, cpu.regs.f)


@cb(0x4B)
def bit_1_e(cpu):
    "BIT 1,E"
    cpu.regs.f = alu.bit(cpu.regs.e, 1, cpu.regs.f)


@cb(0x4C)
def bit_1_h(cpu):
    "BIT 1,H"
    cpu.regs.f = alu.bit(cpu.regs.h, 1, cpu.regs.f)


@cb(0x4D)
def bit_1_l(cpu):
    "BIT 1,L"
    cpu.regs.f = alu.bit(cpu.regs.l, 1, cpu.regs.f)


@cb(0x4E)
def bit_1_hl(cpu):
    "BIT 1,(HL)"
    addr = cpu.regs.hl
    value = cpu.read_mem(addr)
    # NOTE: known simplification -- for BIT b,(HL) the undocumented X/Y
    # flags come from (addr+1)>>8 (the internal MEMPTR high byte); real
    # hardware's MEMPTR update is more nuanced.
    cpu.regs.f = alu.bit_memory(value, 1, cpu.regs.f, ((addr + 1) >> 8) & 0xFF)
    cpu.add_t_states(1)


@cb(0x4F)
def bit_1_a(cpu):
    "BIT 1,A"
    cpu.regs.f = alu.bit(cpu.regs.a, 1, cpu.regs.f)



## ─── BIT 2,r  (0x50-0x57) ───

@cb(0x50)
def bit_2_b(cpu):
    "BIT 2,B"
    cpu.regs.f = alu.bit(cpu.regs.b, 2, cpu.regs.f)


@cb(0x51)
def bit_2_c(cpu):
    "BIT 2,C"
    cpu.regs.f = alu.bit(cpu.regs.c, 2, cpu.regs.f)


@cb(0x52)
def bit_2_d(cpu):
    "BIT 2,D"
    cpu.regs.f = alu.bit(cpu.regs.d, 2, cpu.regs.f)


@cb(0x53)
def bit_2_e(cpu):
    "BIT 2,E"
    cpu.regs.f = alu.bit(cpu.regs.e, 2, cpu.regs.f)


@cb(0x54)
def bit_2_h(cpu):
    "BIT 2,H"
    cpu.regs.f = alu.bit(cpu.regs.h, 2, cpu.regs.f)


@cb(0x55)
def bit_2_l(cpu):
    "BIT 2,L"
    cpu.regs.f = alu.bit(cpu.regs.l, 2, cpu.regs.f)


@cb(0x56)
def bit_2_hl(cpu):
    "BIT 2,(HL)"
    addr = cpu.regs.hl
    value = cpu.read_mem(addr)
    # NOTE: known simplification -- for BIT b,(HL) the undocumented X/Y
    # flags come from (addr+1)>>8 (the internal MEMPTR high byte); real
    # hardware's MEMPTR update is more nuanced.
    cpu.regs.f = alu.bit_memory(value, 2, cpu.regs.f, ((addr + 1) >> 8) & 0xFF)
    cpu.add_t_states(1)


@cb(0x57)
def bit_2_a(cpu):
    "BIT 2,A"
    cpu.regs.f = alu.bit(cpu.regs.a, 2, cpu.regs.f)



## ─── BIT 3,r  (0x58-0x5F) ───

@cb(0x58)
def bit_3_b(cpu):
    "BIT 3,B"
    cpu.regs.f = alu.bit(cpu.regs.b, 3, cpu.regs.f)


@cb(0x59)
def bit_3_c(cpu):
    "BIT 3,C"
    cpu.regs.f = alu.bit(cpu.regs.c, 3, cpu.regs.f)


@cb(0x5A)
def bit_3_d(cpu):
    "BIT 3,D"
    cpu.regs.f = alu.bit(cpu.regs.d, 3, cpu.regs.f)


@cb(0x5B)
def bit_3_e(cpu):
    "BIT 3,E"
    cpu.regs.f = alu.bit(cpu.regs.e, 3, cpu.regs.f)


@cb(0x5C)
def bit_3_h(cpu):
    "BIT 3,H"
    cpu.regs.f = alu.bit(cpu.regs.h, 3, cpu.regs.f)


@cb(0x5D)
def bit_3_l(cpu):
    "BIT 3,L"
    cpu.regs.f = alu.bit(cpu.regs.l, 3, cpu.regs.f)


@cb(0x5E)
def bit_3_hl(cpu):
    "BIT 3,(HL)"
    addr = cpu.regs.hl
    value = cpu.read_mem(addr)
    # NOTE: known simplification -- for BIT b,(HL) the undocumented X/Y
    # flags come from (addr+1)>>8 (the internal MEMPTR high byte); real
    # hardware's MEMPTR update is more nuanced.
    cpu.regs.f = alu.bit_memory(value, 3, cpu.regs.f, ((addr + 1) >> 8) & 0xFF)
    cpu.add_t_states(1)


@cb(0x5F)
def bit_3_a(cpu):
    "BIT 3,A"
    cpu.regs.f = alu.bit(cpu.regs.a, 3, cpu.regs.f)



## ─── BIT 4,r  (0x60-0x67) ───

@cb(0x60)
def bit_4_b(cpu):
    "BIT 4,B"
    cpu.regs.f = alu.bit(cpu.regs.b, 4, cpu.regs.f)


@cb(0x61)
def bit_4_c(cpu):
    "BIT 4,C"
    cpu.regs.f = alu.bit(cpu.regs.c, 4, cpu.regs.f)


@cb(0x62)
def bit_4_d(cpu):
    "BIT 4,D"
    cpu.regs.f = alu.bit(cpu.regs.d, 4, cpu.regs.f)


@cb(0x63)
def bit_4_e(cpu):
    "BIT 4,E"
    cpu.regs.f = alu.bit(cpu.regs.e, 4, cpu.regs.f)


@cb(0x64)
def bit_4_h(cpu):
    "BIT 4,H"
    cpu.regs.f = alu.bit(cpu.regs.h, 4, cpu.regs.f)


@cb(0x65)
def bit_4_l(cpu):
    "BIT 4,L"
    cpu.regs.f = alu.bit(cpu.regs.l, 4, cpu.regs.f)


@cb(0x66)
def bit_4_hl(cpu):
    "BIT 4,(HL)"
    addr = cpu.regs.hl
    value = cpu.read_mem(addr)
    # NOTE: known simplification -- for BIT b,(HL) the undocumented X/Y
    # flags come from (addr+1)>>8 (the internal MEMPTR high byte); real
    # hardware's MEMPTR update is more nuanced.
    cpu.regs.f = alu.bit_memory(value, 4, cpu.regs.f, ((addr + 1) >> 8) & 0xFF)
    cpu.add_t_states(1)


@cb(0x67)
def bit_4_a(cpu):
    "BIT 4,A"
    cpu.regs.f = alu.bit(cpu.regs.a, 4, cpu.regs.f)



## ─── BIT 5,r  (0x68-0x6F) ───

@cb(0x68)
def bit_5_b(cpu):
    "BIT 5,B"
    cpu.regs.f = alu.bit(cpu.regs.b, 5, cpu.regs.f)


@cb(0x69)
def bit_5_c(cpu):
    "BIT 5,C"
    cpu.regs.f = alu.bit(cpu.regs.c, 5, cpu.regs.f)


@cb(0x6A)
def bit_5_d(cpu):
    "BIT 5,D"
    cpu.regs.f = alu.bit(cpu.regs.d, 5, cpu.regs.f)


@cb(0x6B)
def bit_5_e(cpu):
    "BIT 5,E"
    cpu.regs.f = alu.bit(cpu.regs.e, 5, cpu.regs.f)


@cb(0x6C)
def bit_5_h(cpu):
    "BIT 5,H"
    cpu.regs.f = alu.bit(cpu.regs.h, 5, cpu.regs.f)


@cb(0x6D)
def bit_5_l(cpu):
    "BIT 5,L"
    cpu.regs.f = alu.bit(cpu.regs.l, 5, cpu.regs.f)


@cb(0x6E)
def bit_5_hl(cpu):
    "BIT 5,(HL)"
    addr = cpu.regs.hl
    value = cpu.read_mem(addr)
    # NOTE: known simplification -- for BIT b,(HL) the undocumented X/Y
    # flags come from (addr+1)>>8 (the internal MEMPTR high byte); real
    # hardware's MEMPTR update is more nuanced.
    cpu.regs.f = alu.bit_memory(value, 5, cpu.regs.f, ((addr + 1) >> 8) & 0xFF)
    cpu.add_t_states(1)


@cb(0x6F)
def bit_5_a(cpu):
    "BIT 5,A"
    cpu.regs.f = alu.bit(cpu.regs.a, 5, cpu.regs.f)



## ─── BIT 6,r  (0x70-0x77) ───

@cb(0x70)
def bit_6_b(cpu):
    "BIT 6,B"
    cpu.regs.f = alu.bit(cpu.regs.b, 6, cpu.regs.f)


@cb(0x71)
def bit_6_c(cpu):
    "BIT 6,C"
    cpu.regs.f = alu.bit(cpu.regs.c, 6, cpu.regs.f)


@cb(0x72)
def bit_6_d(cpu):
    "BIT 6,D"
    cpu.regs.f = alu.bit(cpu.regs.d, 6, cpu.regs.f)


@cb(0x73)
def bit_6_e(cpu):
    "BIT 6,E"
    cpu.regs.f = alu.bit(cpu.regs.e, 6, cpu.regs.f)


@cb(0x74)
def bit_6_h(cpu):
    "BIT 6,H"
    cpu.regs.f = alu.bit(cpu.regs.h, 6, cpu.regs.f)


@cb(0x75)
def bit_6_l(cpu):
    "BIT 6,L"
    cpu.regs.f = alu.bit(cpu.regs.l, 6, cpu.regs.f)


@cb(0x76)
def bit_6_hl(cpu):
    "BIT 6,(HL)"
    addr = cpu.regs.hl
    value = cpu.read_mem(addr)
    # NOTE: known simplification -- for BIT b,(HL) the undocumented X/Y
    # flags come from (addr+1)>>8 (the internal MEMPTR high byte); real
    # hardware's MEMPTR update is more nuanced.
    cpu.regs.f = alu.bit_memory(value, 6, cpu.regs.f, ((addr + 1) >> 8) & 0xFF)
    cpu.add_t_states(1)


@cb(0x77)
def bit_6_a(cpu):
    "BIT 6,A"
    cpu.regs.f = alu.bit(cpu.regs.a, 6, cpu.regs.f)



## ─── BIT 7,r  (0x78-0x7F) ───

@cb(0x78)
def bit_7_b(cpu):
    "BIT 7,B"
    cpu.regs.f = alu.bit(cpu.regs.b, 7, cpu.regs.f)


@cb(0x79)
def bit_7_c(cpu):
    "BIT 7,C"
    cpu.regs.f = alu.bit(cpu.regs.c, 7, cpu.regs.f)


@cb(0x7A)
def bit_7_d(cpu):
    "BIT 7,D"
    cpu.regs.f = alu.bit(cpu.regs.d, 7, cpu.regs.f)


@cb(0x7B)
def bit_7_e(cpu):
    "BIT 7,E"
    cpu.regs.f = alu.bit(cpu.regs.e, 7, cpu.regs.f)


@cb(0x7C)
def bit_7_h(cpu):
    "BIT 7,H"
    cpu.regs.f = alu.bit(cpu.regs.h, 7, cpu.regs.f)


@cb(0x7D)
def bit_7_l(cpu):
    "BIT 7,L"
    cpu.regs.f = alu.bit(cpu.regs.l, 7, cpu.regs.f)


@cb(0x7E)
def bit_7_hl(cpu):
    "BIT 7,(HL)"
    addr = cpu.regs.hl
    value = cpu.read_mem(addr)
    # NOTE: known simplification -- for BIT b,(HL) the undocumented X/Y
    # flags come from (addr+1)>>8 (the internal MEMPTR high byte); real
    # hardware's MEMPTR update is more nuanced.
    cpu.regs.f = alu.bit_memory(value, 7, cpu.regs.f, ((addr + 1) >> 8) & 0xFF)
    cpu.add_t_states(1)


@cb(0x7F)
def bit_7_a(cpu):
    "BIT 7,A"
    cpu.regs.f = alu.bit(cpu.regs.a, 7, cpu.regs.f)



## ─── RES 0,r  (0x80-0x87) ───

@cb(0x80)
def res_0_b(cpu):
    "RES 0,B"
    cpu.regs.b = alu.res(cpu.regs.b, 0)


@cb(0x81)
def res_0_c(cpu):
    "RES 0,C"
    cpu.regs.c = alu.res(cpu.regs.c, 0)


@cb(0x82)
def res_0_d(cpu):
    "RES 0,D"
    cpu.regs.d = alu.res(cpu.regs.d, 0)


@cb(0x83)
def res_0_e(cpu):
    "RES 0,E"
    cpu.regs.e = alu.res(cpu.regs.e, 0)


@cb(0x84)
def res_0_h(cpu):
    "RES 0,H"
    cpu.regs.h = alu.res(cpu.regs.h, 0)


@cb(0x85)
def res_0_l(cpu):
    "RES 0,L"
    cpu.regs.l = alu.res(cpu.regs.l, 0)


@cb(0x86)
def res_0_hl(cpu):
    "RES 0,(HL)"
    result = alu.res(cpu.read_mem(cpu.regs.hl), 0)
    cpu.write_mem(cpu.regs.hl, result)
    cpu.add_t_states(1)


@cb(0x87)
def res_0_a(cpu):
    "RES 0,A"
    cpu.regs.a = alu.res(cpu.regs.a, 0)



## ─── RES 1,r  (0x88-0x8F) ───

@cb(0x88)
def res_1_b(cpu):
    "RES 1,B"
    cpu.regs.b = alu.res(cpu.regs.b, 1)


@cb(0x89)
def res_1_c(cpu):
    "RES 1,C"
    cpu.regs.c = alu.res(cpu.regs.c, 1)


@cb(0x8A)
def res_1_d(cpu):
    "RES 1,D"
    cpu.regs.d = alu.res(cpu.regs.d, 1)


@cb(0x8B)
def res_1_e(cpu):
    "RES 1,E"
    cpu.regs.e = alu.res(cpu.regs.e, 1)


@cb(0x8C)
def res_1_h(cpu):
    "RES 1,H"
    cpu.regs.h = alu.res(cpu.regs.h, 1)


@cb(0x8D)
def res_1_l(cpu):
    "RES 1,L"
    cpu.regs.l = alu.res(cpu.regs.l, 1)


@cb(0x8E)
def res_1_hl(cpu):
    "RES 1,(HL)"
    result = alu.res(cpu.read_mem(cpu.regs.hl), 1)
    cpu.write_mem(cpu.regs.hl, result)
    cpu.add_t_states(1)


@cb(0x8F)
def res_1_a(cpu):
    "RES 1,A"
    cpu.regs.a = alu.res(cpu.regs.a, 1)



## ─── RES 2,r  (0x90-0x97) ───

@cb(0x90)
def res_2_b(cpu):
    "RES 2,B"
    cpu.regs.b = alu.res(cpu.regs.b, 2)


@cb(0x91)
def res_2_c(cpu):
    "RES 2,C"
    cpu.regs.c = alu.res(cpu.regs.c, 2)


@cb(0x92)
def res_2_d(cpu):
    "RES 2,D"
    cpu.regs.d = alu.res(cpu.regs.d, 2)


@cb(0x93)
def res_2_e(cpu):
    "RES 2,E"
    cpu.regs.e = alu.res(cpu.regs.e, 2)


@cb(0x94)
def res_2_h(cpu):
    "RES 2,H"
    cpu.regs.h = alu.res(cpu.regs.h, 2)


@cb(0x95)
def res_2_l(cpu):
    "RES 2,L"
    cpu.regs.l = alu.res(cpu.regs.l, 2)


@cb(0x96)
def res_2_hl(cpu):
    "RES 2,(HL)"
    result = alu.res(cpu.read_mem(cpu.regs.hl), 2)
    cpu.write_mem(cpu.regs.hl, result)
    cpu.add_t_states(1)


@cb(0x97)
def res_2_a(cpu):
    "RES 2,A"
    cpu.regs.a = alu.res(cpu.regs.a, 2)



## ─── RES 3,r  (0x98-0x9F) ───

@cb(0x98)
def res_3_b(cpu):
    "RES 3,B"
    cpu.regs.b = alu.res(cpu.regs.b, 3)


@cb(0x99)
def res_3_c(cpu):
    "RES 3,C"
    cpu.regs.c = alu.res(cpu.regs.c, 3)


@cb(0x9A)
def res_3_d(cpu):
    "RES 3,D"
    cpu.regs.d = alu.res(cpu.regs.d, 3)


@cb(0x9B)
def res_3_e(cpu):
    "RES 3,E"
    cpu.regs.e = alu.res(cpu.regs.e, 3)


@cb(0x9C)
def res_3_h(cpu):
    "RES 3,H"
    cpu.regs.h = alu.res(cpu.regs.h, 3)


@cb(0x9D)
def res_3_l(cpu):
    "RES 3,L"
    cpu.regs.l = alu.res(cpu.regs.l, 3)


@cb(0x9E)
def res_3_hl(cpu):
    "RES 3,(HL)"
    result = alu.res(cpu.read_mem(cpu.regs.hl), 3)
    cpu.write_mem(cpu.regs.hl, result)
    cpu.add_t_states(1)


@cb(0x9F)
def res_3_a(cpu):
    "RES 3,A"
    cpu.regs.a = alu.res(cpu.regs.a, 3)



## ─── RES 4,r  (0xA0-0xA7) ───

@cb(0xA0)
def res_4_b(cpu):
    "RES 4,B"
    cpu.regs.b = alu.res(cpu.regs.b, 4)


@cb(0xA1)
def res_4_c(cpu):
    "RES 4,C"
    cpu.regs.c = alu.res(cpu.regs.c, 4)


@cb(0xA2)
def res_4_d(cpu):
    "RES 4,D"
    cpu.regs.d = alu.res(cpu.regs.d, 4)


@cb(0xA3)
def res_4_e(cpu):
    "RES 4,E"
    cpu.regs.e = alu.res(cpu.regs.e, 4)


@cb(0xA4)
def res_4_h(cpu):
    "RES 4,H"
    cpu.regs.h = alu.res(cpu.regs.h, 4)


@cb(0xA5)
def res_4_l(cpu):
    "RES 4,L"
    cpu.regs.l = alu.res(cpu.regs.l, 4)


@cb(0xA6)
def res_4_hl(cpu):
    "RES 4,(HL)"
    result = alu.res(cpu.read_mem(cpu.regs.hl), 4)
    cpu.write_mem(cpu.regs.hl, result)
    cpu.add_t_states(1)


@cb(0xA7)
def res_4_a(cpu):
    "RES 4,A"
    cpu.regs.a = alu.res(cpu.regs.a, 4)



## ─── RES 5,r  (0xA8-0xAF) ───

@cb(0xA8)
def res_5_b(cpu):
    "RES 5,B"
    cpu.regs.b = alu.res(cpu.regs.b, 5)


@cb(0xA9)
def res_5_c(cpu):
    "RES 5,C"
    cpu.regs.c = alu.res(cpu.regs.c, 5)


@cb(0xAA)
def res_5_d(cpu):
    "RES 5,D"
    cpu.regs.d = alu.res(cpu.regs.d, 5)


@cb(0xAB)
def res_5_e(cpu):
    "RES 5,E"
    cpu.regs.e = alu.res(cpu.regs.e, 5)


@cb(0xAC)
def res_5_h(cpu):
    "RES 5,H"
    cpu.regs.h = alu.res(cpu.regs.h, 5)


@cb(0xAD)
def res_5_l(cpu):
    "RES 5,L"
    cpu.regs.l = alu.res(cpu.regs.l, 5)


@cb(0xAE)
def res_5_hl(cpu):
    "RES 5,(HL)"
    result = alu.res(cpu.read_mem(cpu.regs.hl), 5)
    cpu.write_mem(cpu.regs.hl, result)
    cpu.add_t_states(1)


@cb(0xAF)
def res_5_a(cpu):
    "RES 5,A"
    cpu.regs.a = alu.res(cpu.regs.a, 5)



## ─── RES 6,r  (0xB0-0xB7) ───

@cb(0xB0)
def res_6_b(cpu):
    "RES 6,B"
    cpu.regs.b = alu.res(cpu.regs.b, 6)


@cb(0xB1)
def res_6_c(cpu):
    "RES 6,C"
    cpu.regs.c = alu.res(cpu.regs.c, 6)


@cb(0xB2)
def res_6_d(cpu):
    "RES 6,D"
    cpu.regs.d = alu.res(cpu.regs.d, 6)


@cb(0xB3)
def res_6_e(cpu):
    "RES 6,E"
    cpu.regs.e = alu.res(cpu.regs.e, 6)


@cb(0xB4)
def res_6_h(cpu):
    "RES 6,H"
    cpu.regs.h = alu.res(cpu.regs.h, 6)


@cb(0xB5)
def res_6_l(cpu):
    "RES 6,L"
    cpu.regs.l = alu.res(cpu.regs.l, 6)


@cb(0xB6)
def res_6_hl(cpu):
    "RES 6,(HL)"
    result = alu.res(cpu.read_mem(cpu.regs.hl), 6)
    cpu.write_mem(cpu.regs.hl, result)
    cpu.add_t_states(1)


@cb(0xB7)
def res_6_a(cpu):
    "RES 6,A"
    cpu.regs.a = alu.res(cpu.regs.a, 6)



## ─── RES 7,r  (0xB8-0xBF) ───

@cb(0xB8)
def res_7_b(cpu):
    "RES 7,B"
    cpu.regs.b = alu.res(cpu.regs.b, 7)


@cb(0xB9)
def res_7_c(cpu):
    "RES 7,C"
    cpu.regs.c = alu.res(cpu.regs.c, 7)


@cb(0xBA)
def res_7_d(cpu):
    "RES 7,D"
    cpu.regs.d = alu.res(cpu.regs.d, 7)


@cb(0xBB)
def res_7_e(cpu):
    "RES 7,E"
    cpu.regs.e = alu.res(cpu.regs.e, 7)


@cb(0xBC)
def res_7_h(cpu):
    "RES 7,H"
    cpu.regs.h = alu.res(cpu.regs.h, 7)


@cb(0xBD)
def res_7_l(cpu):
    "RES 7,L"
    cpu.regs.l = alu.res(cpu.regs.l, 7)


@cb(0xBE)
def res_7_hl(cpu):
    "RES 7,(HL)"
    result = alu.res(cpu.read_mem(cpu.regs.hl), 7)
    cpu.write_mem(cpu.regs.hl, result)
    cpu.add_t_states(1)


@cb(0xBF)
def res_7_a(cpu):
    "RES 7,A"
    cpu.regs.a = alu.res(cpu.regs.a, 7)



## ─── SET 0,r  (0xC0-0xC7) ───

@cb(0xC0)
def set_0_b(cpu):
    "SET 0,B"
    cpu.regs.b = alu.set_bit(cpu.regs.b, 0)


@cb(0xC1)
def set_0_c(cpu):
    "SET 0,C"
    cpu.regs.c = alu.set_bit(cpu.regs.c, 0)


@cb(0xC2)
def set_0_d(cpu):
    "SET 0,D"
    cpu.regs.d = alu.set_bit(cpu.regs.d, 0)


@cb(0xC3)
def set_0_e(cpu):
    "SET 0,E"
    cpu.regs.e = alu.set_bit(cpu.regs.e, 0)


@cb(0xC4)
def set_0_h(cpu):
    "SET 0,H"
    cpu.regs.h = alu.set_bit(cpu.regs.h, 0)


@cb(0xC5)
def set_0_l(cpu):
    "SET 0,L"
    cpu.regs.l = alu.set_bit(cpu.regs.l, 0)


@cb(0xC6)
def set_0_hl(cpu):
    "SET 0,(HL)"
    result = alu.set_bit(cpu.read_mem(cpu.regs.hl), 0)
    cpu.write_mem(cpu.regs.hl, result)
    cpu.add_t_states(1)


@cb(0xC7)
def set_0_a(cpu):
    "SET 0,A"
    cpu.regs.a = alu.set_bit(cpu.regs.a, 0)



## ─── SET 1,r  (0xC8-0xCF) ───

@cb(0xC8)
def set_1_b(cpu):
    "SET 1,B"
    cpu.regs.b = alu.set_bit(cpu.regs.b, 1)


@cb(0xC9)
def set_1_c(cpu):
    "SET 1,C"
    cpu.regs.c = alu.set_bit(cpu.regs.c, 1)


@cb(0xCA)
def set_1_d(cpu):
    "SET 1,D"
    cpu.regs.d = alu.set_bit(cpu.regs.d, 1)


@cb(0xCB)
def set_1_e(cpu):
    "SET 1,E"
    cpu.regs.e = alu.set_bit(cpu.regs.e, 1)


@cb(0xCC)
def set_1_h(cpu):
    "SET 1,H"
    cpu.regs.h = alu.set_bit(cpu.regs.h, 1)


@cb(0xCD)
def set_1_l(cpu):
    "SET 1,L"
    cpu.regs.l = alu.set_bit(cpu.regs.l, 1)


@cb(0xCE)
def set_1_hl(cpu):
    "SET 1,(HL)"
    result = alu.set_bit(cpu.read_mem(cpu.regs.hl), 1)
    cpu.write_mem(cpu.regs.hl, result)
    cpu.add_t_states(1)


@cb(0xCF)
def set_1_a(cpu):
    "SET 1,A"
    cpu.regs.a = alu.set_bit(cpu.regs.a, 1)



## ─── SET 2,r  (0xD0-0xD7) ───

@cb(0xD0)
def set_2_b(cpu):
    "SET 2,B"
    cpu.regs.b = alu.set_bit(cpu.regs.b, 2)


@cb(0xD1)
def set_2_c(cpu):
    "SET 2,C"
    cpu.regs.c = alu.set_bit(cpu.regs.c, 2)


@cb(0xD2)
def set_2_d(cpu):
    "SET 2,D"
    cpu.regs.d = alu.set_bit(cpu.regs.d, 2)


@cb(0xD3)
def set_2_e(cpu):
    "SET 2,E"
    cpu.regs.e = alu.set_bit(cpu.regs.e, 2)


@cb(0xD4)
def set_2_h(cpu):
    "SET 2,H"
    cpu.regs.h = alu.set_bit(cpu.regs.h, 2)


@cb(0xD5)
def set_2_l(cpu):
    "SET 2,L"
    cpu.regs.l = alu.set_bit(cpu.regs.l, 2)


@cb(0xD6)
def set_2_hl(cpu):
    "SET 2,(HL)"
    result = alu.set_bit(cpu.read_mem(cpu.regs.hl), 2)
    cpu.write_mem(cpu.regs.hl, result)
    cpu.add_t_states(1)


@cb(0xD7)
def set_2_a(cpu):
    "SET 2,A"
    cpu.regs.a = alu.set_bit(cpu.regs.a, 2)



## ─── SET 3,r  (0xD8-0xDF) ───

@cb(0xD8)
def set_3_b(cpu):
    "SET 3,B"
    cpu.regs.b = alu.set_bit(cpu.regs.b, 3)


@cb(0xD9)
def set_3_c(cpu):
    "SET 3,C"
    cpu.regs.c = alu.set_bit(cpu.regs.c, 3)


@cb(0xDA)
def set_3_d(cpu):
    "SET 3,D"
    cpu.regs.d = alu.set_bit(cpu.regs.d, 3)


@cb(0xDB)
def set_3_e(cpu):
    "SET 3,E"
    cpu.regs.e = alu.set_bit(cpu.regs.e, 3)


@cb(0xDC)
def set_3_h(cpu):
    "SET 3,H"
    cpu.regs.h = alu.set_bit(cpu.regs.h, 3)


@cb(0xDD)
def set_3_l(cpu):
    "SET 3,L"
    cpu.regs.l = alu.set_bit(cpu.regs.l, 3)


@cb(0xDE)
def set_3_hl(cpu):
    "SET 3,(HL)"
    result = alu.set_bit(cpu.read_mem(cpu.regs.hl), 3)
    cpu.write_mem(cpu.regs.hl, result)
    cpu.add_t_states(1)


@cb(0xDF)
def set_3_a(cpu):
    "SET 3,A"
    cpu.regs.a = alu.set_bit(cpu.regs.a, 3)



## ─── SET 4,r  (0xE0-0xE7) ───

@cb(0xE0)
def set_4_b(cpu):
    "SET 4,B"
    cpu.regs.b = alu.set_bit(cpu.regs.b, 4)


@cb(0xE1)
def set_4_c(cpu):
    "SET 4,C"
    cpu.regs.c = alu.set_bit(cpu.regs.c, 4)


@cb(0xE2)
def set_4_d(cpu):
    "SET 4,D"
    cpu.regs.d = alu.set_bit(cpu.regs.d, 4)


@cb(0xE3)
def set_4_e(cpu):
    "SET 4,E"
    cpu.regs.e = alu.set_bit(cpu.regs.e, 4)


@cb(0xE4)
def set_4_h(cpu):
    "SET 4,H"
    cpu.regs.h = alu.set_bit(cpu.regs.h, 4)


@cb(0xE5)
def set_4_l(cpu):
    "SET 4,L"
    cpu.regs.l = alu.set_bit(cpu.regs.l, 4)


@cb(0xE6)
def set_4_hl(cpu):
    "SET 4,(HL)"
    result = alu.set_bit(cpu.read_mem(cpu.regs.hl), 4)
    cpu.write_mem(cpu.regs.hl, result)
    cpu.add_t_states(1)


@cb(0xE7)
def set_4_a(cpu):
    "SET 4,A"
    cpu.regs.a = alu.set_bit(cpu.regs.a, 4)



## ─── SET 5,r  (0xE8-0xEF) ───

@cb(0xE8)
def set_5_b(cpu):
    "SET 5,B"
    cpu.regs.b = alu.set_bit(cpu.regs.b, 5)


@cb(0xE9)
def set_5_c(cpu):
    "SET 5,C"
    cpu.regs.c = alu.set_bit(cpu.regs.c, 5)


@cb(0xEA)
def set_5_d(cpu):
    "SET 5,D"
    cpu.regs.d = alu.set_bit(cpu.regs.d, 5)


@cb(0xEB)
def set_5_e(cpu):
    "SET 5,E"
    cpu.regs.e = alu.set_bit(cpu.regs.e, 5)


@cb(0xEC)
def set_5_h(cpu):
    "SET 5,H"
    cpu.regs.h = alu.set_bit(cpu.regs.h, 5)


@cb(0xED)
def set_5_l(cpu):
    "SET 5,L"
    cpu.regs.l = alu.set_bit(cpu.regs.l, 5)


@cb(0xEE)
def set_5_hl(cpu):
    "SET 5,(HL)"
    result = alu.set_bit(cpu.read_mem(cpu.regs.hl), 5)
    cpu.write_mem(cpu.regs.hl, result)
    cpu.add_t_states(1)


@cb(0xEF)
def set_5_a(cpu):
    "SET 5,A"
    cpu.regs.a = alu.set_bit(cpu.regs.a, 5)



## ─── SET 6,r  (0xF0-0xF7) ───

@cb(0xF0)
def set_6_b(cpu):
    "SET 6,B"
    cpu.regs.b = alu.set_bit(cpu.regs.b, 6)


@cb(0xF1)
def set_6_c(cpu):
    "SET 6,C"
    cpu.regs.c = alu.set_bit(cpu.regs.c, 6)


@cb(0xF2)
def set_6_d(cpu):
    "SET 6,D"
    cpu.regs.d = alu.set_bit(cpu.regs.d, 6)


@cb(0xF3)
def set_6_e(cpu):
    "SET 6,E"
    cpu.regs.e = alu.set_bit(cpu.regs.e, 6)


@cb(0xF4)
def set_6_h(cpu):
    "SET 6,H"
    cpu.regs.h = alu.set_bit(cpu.regs.h, 6)


@cb(0xF5)
def set_6_l(cpu):
    "SET 6,L"
    cpu.regs.l = alu.set_bit(cpu.regs.l, 6)


@cb(0xF6)
def set_6_hl(cpu):
    "SET 6,(HL)"
    result = alu.set_bit(cpu.read_mem(cpu.regs.hl), 6)
    cpu.write_mem(cpu.regs.hl, result)
    cpu.add_t_states(1)


@cb(0xF7)
def set_6_a(cpu):
    "SET 6,A"
    cpu.regs.a = alu.set_bit(cpu.regs.a, 6)



## ─── SET 7,r  (0xF8-0xFF) ───

@cb(0xF8)
def set_7_b(cpu):
    "SET 7,B"
    cpu.regs.b = alu.set_bit(cpu.regs.b, 7)


@cb(0xF9)
def set_7_c(cpu):
    "SET 7,C"
    cpu.regs.c = alu.set_bit(cpu.regs.c, 7)


@cb(0xFA)
def set_7_d(cpu):
    "SET 7,D"
    cpu.regs.d = alu.set_bit(cpu.regs.d, 7)


@cb(0xFB)
def set_7_e(cpu):
    "SET 7,E"
    cpu.regs.e = alu.set_bit(cpu.regs.e, 7)


@cb(0xFC)
def set_7_h(cpu):
    "SET 7,H"
    cpu.regs.h = alu.set_bit(cpu.regs.h, 7)


@cb(0xFD)
def set_7_l(cpu):
    "SET 7,L"
    cpu.regs.l = alu.set_bit(cpu.regs.l, 7)


@cb(0xFE)
def set_7_hl(cpu):
    "SET 7,(HL)"
    result = alu.set_bit(cpu.read_mem(cpu.regs.hl), 7)
    cpu.write_mem(cpu.regs.hl, result)
    cpu.add_t_states(1)


@cb(0xFF)
def set_7_a(cpu):
    "SET 7,A"
    cpu.regs.a = alu.set_bit(cpu.regs.a, 7)


