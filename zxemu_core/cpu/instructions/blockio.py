"""ED block transfer/compare/I-O groups plus port I/O.

The block groups (LDI/LDD/..., CPI/..., INI/..., OUTI/...) each have one
explicit operation function parameterised by direction (step +1/-1) and whether
it repeats; the 16 opcode handlers just call it with the right arguments.

Also here: IN r,(C) / OUT (C),r and the immediate-port IN A,(n) / OUT (n),A.
"""

from __future__ import annotations

from .. import flags as alu
from ..registers import FLAG_C, FLAG_H, FLAG_N, FLAG_P, FLAG_S, FLAG_Z
from ._dispatch import base, ed


## ─── Block transfer operation: LDI/LDD/LDIR/LDDR ───

def _block_copy_undoc_flags(cpu, transferred: int, bc_after: int) -> int:
    n = (cpu.regs.a + transferred) & 0xFF
    flags = cpu.regs.f & (FLAG_S | FLAG_Z | FLAG_C)
    flags |= n & 0x08  # X = bit 3 of n
    flags |= ((n >> 1) & 1) << 5  # Y = bit 1 of n
    if bc_after != 0:
        flags |= FLAG_P
    return flags


def _block_copy(cpu, step: int, repeat: bool) -> None:
    # One iteration per step(). A repeating op (LDIR/LDDR) that isn't done rewinds PC
    # by 2 so the next step() re-fetches and re-runs it -- exactly how the real Z80
    # repeats (it never "finishes" until BC hits 0). Running one iteration per step,
    # rather than looping the whole block atomically, keeps the CPU inside the frame
    # loop: a huge block move can't overshoot the frame by millions of T-states (which
    # desynced audio and starved interrupts), and each re-fetch is correctly billed the
    # 21 vs 16 T-states real hardware charges for a repeated vs final iteration.
    value = cpu.read_mem(cpu.regs.hl)
    cpu.write_mem(cpu.regs.de, value)
    cpu.regs.hl = (cpu.regs.hl + step) & 0xFFFF
    cpu.regs.de = (cpu.regs.de + step) & 0xFFFF
    cpu.regs.bc = (cpu.regs.bc - 1) & 0xFFFF
    cpu.regs.f = _block_copy_undoc_flags(cpu, value, cpu.regs.bc)
    cpu.add_t_states(2)
    if repeat and cpu.regs.bc != 0:
        cpu.regs.pc = (cpu.regs.pc - 2) & 0xFFFF  # repeat: re-execute next step
        cpu.add_t_states(5)


@ed(0xA0)
def ldi(cpu):
    "LDI"
    _block_copy(cpu, 1, False)


@ed(0xA8)
def ldd(cpu):
    "LDD"
    _block_copy(cpu, -1, False)


@ed(0xB0)
def ldir(cpu):
    "LDIR"
    _block_copy(cpu, 1, True)


@ed(0xB8)
def lddr(cpu):
    "LDDR"
    _block_copy(cpu, -1, True)


## ─── Block compare operation: CPI/CPD/CPIR/CPDR ───

def _block_compare(cpu, step: int, repeat: bool) -> None:
    # One iteration per step(); CPIR/CPDR also stop early on a match (result == 0).
    # See _block_copy for why the repeat rewinds PC rather than looping internally.
    value = cpu.read_mem(cpu.regs.hl)
    a = cpu.regs.a
    result = (a - value) & 0xFF
    half_carry = 1 if (a & 0x0F) - (value & 0x0F) < 0 else 0
    cpu.regs.hl = (cpu.regs.hl + step) & 0xFFFF
    cpu.regs.bc = (cpu.regs.bc - 1) & 0xFFFF

    flags = alu.sz53_of(result) & (FLAG_S | FLAG_Z)
    flags |= FLAG_N
    if half_carry:
        flags |= FLAG_H
    if cpu.regs.bc != 0:
        flags |= FLAG_P
    flags |= cpu.regs.f & FLAG_C
    n = (result - half_carry) & 0xFF
    flags |= n & 0x08
    flags |= ((n >> 1) & 1) << 5
    cpu.regs.f = flags

    cpu.add_t_states(5)
    if repeat and cpu.regs.bc != 0 and result != 0:
        cpu.regs.pc = (cpu.regs.pc - 2) & 0xFFFF  # repeat: re-execute next step
        cpu.add_t_states(5)


@ed(0xA1)
def cpi(cpu):
    "CPI"
    _block_compare(cpu, 1, False)


@ed(0xA9)
def cpd(cpu):
    "CPD"
    _block_compare(cpu, -1, False)


@ed(0xB1)
def cpir(cpu):
    "CPIR"
    _block_compare(cpu, 1, True)


@ed(0xB9)
def cpdr(cpu):
    "CPDR"
    _block_compare(cpu, -1, True)


## ─── Block I/O flag helper (shared by IN/OUT block groups) ───

def _io_block_flags(cpu, value: int, b_after: int, k: int) -> int:
    flags = alu.sz53_of(b_after)
    flags |= FLAG_N if (value & 0x80) else 0
    k &= 0x1FF
    if k > 0xFF:
        flags |= FLAG_H | FLAG_C
    if alu.parity_even((k & 0x07) ^ b_after):
        flags |= FLAG_P
    return flags


## ─── Block input: INI/IND/INIR/INDR ───

def _block_in(cpu, step: int, repeat: bool) -> None:
    # One iteration per step(); INIR/INDR repeat until B hits 0 (see _block_copy).
    value = cpu.io_read(cpu.regs.bc) & 0xFF
    cpu.write_mem(cpu.regs.hl, value)
    cpu.regs.hl = (cpu.regs.hl + step) & 0xFFFF
    b_after = (cpu.regs.b - 1) & 0xFF
    cpu.regs.b = b_after
    k = value + ((cpu.regs.c + step) & 0xFF)
    cpu.regs.f = _io_block_flags(cpu, value, b_after, k)
    cpu.add_t_states(1)
    if repeat and b_after != 0:
        cpu.regs.pc = (cpu.regs.pc - 2) & 0xFFFF  # repeat: re-execute next step
        cpu.add_t_states(5)


@ed(0xA2)
def ini(cpu):
    "INI"
    _block_in(cpu, 1, False)


@ed(0xAA)
def ind(cpu):
    "IND"
    _block_in(cpu, -1, False)


@ed(0xB2)
def inir(cpu):
    "INIR"
    _block_in(cpu, 1, True)


@ed(0xBA)
def indr(cpu):
    "INDR"
    _block_in(cpu, -1, True)


## ─── Block output: OUTI/OUTD/OTIR/OTDR ───

def _block_out(cpu, step: int, repeat: bool) -> None:
    # One iteration per step(); OTIR/OTDR repeat until B hits 0 (see _block_copy).
    value = cpu.read_mem(cpu.regs.hl)
    cpu.regs.hl = (cpu.regs.hl + step) & 0xFFFF
    b_after = (cpu.regs.b - 1) & 0xFF
    cpu.regs.b = b_after
    cpu.io_write(cpu.regs.bc, value)
    k = value + cpu.regs.l
    cpu.regs.f = _io_block_flags(cpu, value, b_after, k)
    cpu.add_t_states(1)
    if repeat and b_after != 0:
        cpu.regs.pc = (cpu.regs.pc - 2) & 0xFFFF  # repeat: re-execute next step
        cpu.add_t_states(5)


@ed(0xA3)
def outi(cpu):
    "OUTI"
    _block_out(cpu, 1, False)


@ed(0xAB)
def outd(cpu):
    "OUTD"
    _block_out(cpu, -1, False)


@ed(0xB3)
def otir(cpu):
    "OTIR"
    _block_out(cpu, 1, True)


@ed(0xBB)
def otdr(cpu):
    "OTDR"
    _block_out(cpu, -1, True)


## ─── IN r,(C)  (0x40|r<<3) ───

def _in_c(cpu) -> int:
    """Read port BC, set S/Z/5/3/P flags (H,N cleared, C preserved); return the byte."""
    value = cpu.io_read(cpu.regs.bc) & 0xFF
    flags = alu.sz53_of(value)
    if alu.parity_even(value):
        flags |= FLAG_P
    cpu.regs.f = (cpu.regs.f & FLAG_C) | flags
    cpu.add_t_states(4)
    return value


@ed(0x40)
def in_b_c(cpu):
    "IN B,(C)"
    cpu.regs.b = _in_c(cpu)


@ed(0x48)
def in_c_c(cpu):
    "IN C,(C)"
    cpu.regs.c = _in_c(cpu)


@ed(0x50)
def in_d_c(cpu):
    "IN D,(C)"
    cpu.regs.d = _in_c(cpu)


@ed(0x58)
def in_e_c(cpu):
    "IN E,(C)"
    cpu.regs.e = _in_c(cpu)


@ed(0x60)
def in_h_c(cpu):
    "IN H,(C)"
    cpu.regs.h = _in_c(cpu)


@ed(0x68)
def in_l_c(cpu):
    "IN L,(C)"
    cpu.regs.l = _in_c(cpu)


@ed(0x70)
def in_f_c(cpu):
    "IN (C)"
    # Undocumented: sets flags from the port byte but discards the value itself.
    _in_c(cpu)


@ed(0x78)
def in_a_c(cpu):
    "IN A,(C)"
    cpu.regs.a = _in_c(cpu)


## ─── OUT (C),r  (0x41|r<<3) ───

def _out_c(cpu, value: int) -> None:
    cpu.io_write(cpu.regs.bc, value)
    cpu.add_t_states(4)


@ed(0x41)
def out_c_b(cpu):
    "OUT (C),B"
    _out_c(cpu, cpu.regs.b)


@ed(0x49)
def out_c_c(cpu):
    "OUT (C),C"
    _out_c(cpu, cpu.regs.c)


@ed(0x51)
def out_c_d(cpu):
    "OUT (C),D"
    _out_c(cpu, cpu.regs.d)


@ed(0x59)
def out_c_e(cpu):
    "OUT (C),E"
    _out_c(cpu, cpu.regs.e)


@ed(0x61)
def out_c_h(cpu):
    "OUT (C),H"
    _out_c(cpu, cpu.regs.h)


@ed(0x69)
def out_c_l(cpu):
    "OUT (C),L"
    _out_c(cpu, cpu.regs.l)


@ed(0x71)
def out_c_0(cpu):
    "OUT (C),0"
    # Undocumented: outputs 0 (no source register in this slot).
    _out_c(cpu, 0)


@ed(0x79)
def out_c_a(cpu):
    "OUT (C),A"
    _out_c(cpu, cpu.regs.a)


## ─── Immediate-port I/O: IN A,(n) / OUT (n),A  (0xDB/0xD3) ───

@base(0xDB)
def in_a_n(cpu):
    "IN A,(n)"
    n = cpu.fetch_byte()
    port = (cpu.regs.a << 8) | n
    cpu.regs.a = cpu.io_read(port) & 0xFF
    cpu.add_t_states(4)


@base(0xD3)
def out_n_a(cpu):
    "OUT (n),A"
    n = cpu.fetch_byte()
    port = (cpu.regs.a << 8) | n
    cpu.io_write(port, cpu.regs.a)
    cpu.add_t_states(4)
