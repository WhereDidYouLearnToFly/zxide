"""8-bit loads: LD r,r' grid, LD r,n, and A <-> (BC)/(DE)/(nn) transfers.

Register order matches the Z80 opcode encoding (B,C,D,E,H,L,(HL),A).
The (HL) forms go through memory; everything else is a register copy.
"""

from __future__ import annotations

from ._dispatch import base


## ─── LD r,r'  (0x40-0x7F, excluding 0x76 = HALT) ───

@base(0x40)
def ld_b_b(cpu):
    "LD B,B"
    cpu.regs.b = cpu.regs.b


@base(0x41)
def ld_b_c(cpu):
    "LD B,C"
    cpu.regs.b = cpu.regs.c


@base(0x42)
def ld_b_d(cpu):
    "LD B,D"
    cpu.regs.b = cpu.regs.d


@base(0x43)
def ld_b_e(cpu):
    "LD B,E"
    cpu.regs.b = cpu.regs.e


@base(0x44)
def ld_b_h(cpu):
    "LD B,H"
    cpu.regs.b = cpu.regs.h


@base(0x45)
def ld_b_l(cpu):
    "LD B,L"
    cpu.regs.b = cpu.regs.l


@base(0x46)
def ld_b_hl(cpu):
    "LD B,(HL)"
    cpu.regs.b = cpu.read_mem(cpu.regs.hl)


@base(0x47)
def ld_b_a(cpu):
    "LD B,A"
    cpu.regs.b = cpu.regs.a


@base(0x48)
def ld_c_b(cpu):
    "LD C,B"
    cpu.regs.c = cpu.regs.b


@base(0x49)
def ld_c_c(cpu):
    "LD C,C"
    cpu.regs.c = cpu.regs.c


@base(0x4A)
def ld_c_d(cpu):
    "LD C,D"
    cpu.regs.c = cpu.regs.d


@base(0x4B)
def ld_c_e(cpu):
    "LD C,E"
    cpu.regs.c = cpu.regs.e


@base(0x4C)
def ld_c_h(cpu):
    "LD C,H"
    cpu.regs.c = cpu.regs.h


@base(0x4D)
def ld_c_l(cpu):
    "LD C,L"
    cpu.regs.c = cpu.regs.l


@base(0x4E)
def ld_c_hl(cpu):
    "LD C,(HL)"
    cpu.regs.c = cpu.read_mem(cpu.regs.hl)


@base(0x4F)
def ld_c_a(cpu):
    "LD C,A"
    cpu.regs.c = cpu.regs.a


@base(0x50)
def ld_d_b(cpu):
    "LD D,B"
    cpu.regs.d = cpu.regs.b


@base(0x51)
def ld_d_c(cpu):
    "LD D,C"
    cpu.regs.d = cpu.regs.c


@base(0x52)
def ld_d_d(cpu):
    "LD D,D"
    cpu.regs.d = cpu.regs.d


@base(0x53)
def ld_d_e(cpu):
    "LD D,E"
    cpu.regs.d = cpu.regs.e


@base(0x54)
def ld_d_h(cpu):
    "LD D,H"
    cpu.regs.d = cpu.regs.h


@base(0x55)
def ld_d_l(cpu):
    "LD D,L"
    cpu.regs.d = cpu.regs.l


@base(0x56)
def ld_d_hl(cpu):
    "LD D,(HL)"
    cpu.regs.d = cpu.read_mem(cpu.regs.hl)


@base(0x57)
def ld_d_a(cpu):
    "LD D,A"
    cpu.regs.d = cpu.regs.a


@base(0x58)
def ld_e_b(cpu):
    "LD E,B"
    cpu.regs.e = cpu.regs.b


@base(0x59)
def ld_e_c(cpu):
    "LD E,C"
    cpu.regs.e = cpu.regs.c


@base(0x5A)
def ld_e_d(cpu):
    "LD E,D"
    cpu.regs.e = cpu.regs.d


@base(0x5B)
def ld_e_e(cpu):
    "LD E,E"
    cpu.regs.e = cpu.regs.e


@base(0x5C)
def ld_e_h(cpu):
    "LD E,H"
    cpu.regs.e = cpu.regs.h


@base(0x5D)
def ld_e_l(cpu):
    "LD E,L"
    cpu.regs.e = cpu.regs.l


@base(0x5E)
def ld_e_hl(cpu):
    "LD E,(HL)"
    cpu.regs.e = cpu.read_mem(cpu.regs.hl)


@base(0x5F)
def ld_e_a(cpu):
    "LD E,A"
    cpu.regs.e = cpu.regs.a


@base(0x60)
def ld_h_b(cpu):
    "LD H,B"
    cpu.regs.h = cpu.regs.b


@base(0x61)
def ld_h_c(cpu):
    "LD H,C"
    cpu.regs.h = cpu.regs.c


@base(0x62)
def ld_h_d(cpu):
    "LD H,D"
    cpu.regs.h = cpu.regs.d


@base(0x63)
def ld_h_e(cpu):
    "LD H,E"
    cpu.regs.h = cpu.regs.e


@base(0x64)
def ld_h_h(cpu):
    "LD H,H"
    cpu.regs.h = cpu.regs.h


@base(0x65)
def ld_h_l(cpu):
    "LD H,L"
    cpu.regs.h = cpu.regs.l


@base(0x66)
def ld_h_hl(cpu):
    "LD H,(HL)"
    cpu.regs.h = cpu.read_mem(cpu.regs.hl)


@base(0x67)
def ld_h_a(cpu):
    "LD H,A"
    cpu.regs.h = cpu.regs.a


@base(0x68)
def ld_l_b(cpu):
    "LD L,B"
    cpu.regs.l = cpu.regs.b


@base(0x69)
def ld_l_c(cpu):
    "LD L,C"
    cpu.regs.l = cpu.regs.c


@base(0x6A)
def ld_l_d(cpu):
    "LD L,D"
    cpu.regs.l = cpu.regs.d


@base(0x6B)
def ld_l_e(cpu):
    "LD L,E"
    cpu.regs.l = cpu.regs.e


@base(0x6C)
def ld_l_h(cpu):
    "LD L,H"
    cpu.regs.l = cpu.regs.h


@base(0x6D)
def ld_l_l(cpu):
    "LD L,L"
    cpu.regs.l = cpu.regs.l


@base(0x6E)
def ld_l_hl(cpu):
    "LD L,(HL)"
    cpu.regs.l = cpu.read_mem(cpu.regs.hl)


@base(0x6F)
def ld_l_a(cpu):
    "LD L,A"
    cpu.regs.l = cpu.regs.a


@base(0x70)
def ld_hl_b(cpu):
    "LD (HL),B"
    cpu.write_mem(cpu.regs.hl, cpu.regs.b)


@base(0x71)
def ld_hl_c(cpu):
    "LD (HL),C"
    cpu.write_mem(cpu.regs.hl, cpu.regs.c)


@base(0x72)
def ld_hl_d(cpu):
    "LD (HL),D"
    cpu.write_mem(cpu.regs.hl, cpu.regs.d)


@base(0x73)
def ld_hl_e(cpu):
    "LD (HL),E"
    cpu.write_mem(cpu.regs.hl, cpu.regs.e)


@base(0x74)
def ld_hl_h(cpu):
    "LD (HL),H"
    cpu.write_mem(cpu.regs.hl, cpu.regs.h)


@base(0x75)
def ld_hl_l(cpu):
    "LD (HL),L"
    cpu.write_mem(cpu.regs.hl, cpu.regs.l)


@base(0x77)
def ld_hl_a(cpu):
    "LD (HL),A"
    cpu.write_mem(cpu.regs.hl, cpu.regs.a)


@base(0x78)
def ld_a_b(cpu):
    "LD A,B"
    cpu.regs.a = cpu.regs.b


@base(0x79)
def ld_a_c(cpu):
    "LD A,C"
    cpu.regs.a = cpu.regs.c


@base(0x7A)
def ld_a_d(cpu):
    "LD A,D"
    cpu.regs.a = cpu.regs.d


@base(0x7B)
def ld_a_e(cpu):
    "LD A,E"
    cpu.regs.a = cpu.regs.e


@base(0x7C)
def ld_a_h(cpu):
    "LD A,H"
    cpu.regs.a = cpu.regs.h


@base(0x7D)
def ld_a_l(cpu):
    "LD A,L"
    cpu.regs.a = cpu.regs.l


@base(0x7E)
def ld_a_hl(cpu):
    "LD A,(HL)"
    cpu.regs.a = cpu.read_mem(cpu.regs.hl)


@base(0x7F)
def ld_a_a(cpu):
    "LD A,A"
    cpu.regs.a = cpu.regs.a



## ─── LD r,n  (0x06 | r<<3 ; r=6 is LD (HL),n) ───

@base(0x06)
def ld_b_n(cpu):
    "LD B,n"
    cpu.regs.b = cpu.fetch_byte()


@base(0x0E)
def ld_c_n(cpu):
    "LD C,n"
    cpu.regs.c = cpu.fetch_byte()


@base(0x16)
def ld_d_n(cpu):
    "LD D,n"
    cpu.regs.d = cpu.fetch_byte()


@base(0x1E)
def ld_e_n(cpu):
    "LD E,n"
    cpu.regs.e = cpu.fetch_byte()


@base(0x26)
def ld_h_n(cpu):
    "LD H,n"
    cpu.regs.h = cpu.fetch_byte()


@base(0x2E)
def ld_l_n(cpu):
    "LD L,n"
    cpu.regs.l = cpu.fetch_byte()


@base(0x36)
def ld_hl_n(cpu):
    "LD (HL),n"
    cpu.write_mem(cpu.regs.hl, cpu.fetch_byte())


@base(0x3E)
def ld_a_n(cpu):
    "LD A,n"
    cpu.regs.a = cpu.fetch_byte()



## ─── A <-> (BC)/(DE)  (0x02/0x0A/0x12/0x1A) ───

@base(0x02)
def ld_bc_mem_a(cpu):
    "LD (BC),A"
    cpu.write_mem(cpu.regs.bc, cpu.regs.a)


@base(0x0A)
def ld_a_bc_mem(cpu):
    "LD A,(BC)"
    cpu.regs.a = cpu.read_mem(cpu.regs.bc)


@base(0x12)
def ld_de_mem_a(cpu):
    "LD (DE),A"
    cpu.write_mem(cpu.regs.de, cpu.regs.a)


@base(0x1A)
def ld_a_de_mem(cpu):
    "LD A,(DE)"
    cpu.regs.a = cpu.read_mem(cpu.regs.de)



## ─── A <-> (nn)  (0x32/0x3A) ───

@base(0x32)
def ld_nn_mem_a(cpu):
    "LD (nn),A"
    addr = cpu.fetch_word()
    cpu.write_mem(addr, cpu.regs.a)


@base(0x3A)
def ld_a_nn_mem(cpu):
    "LD A,(nn)"
    addr = cpu.fetch_word()
    cpu.regs.a = cpu.read_mem(addr)


