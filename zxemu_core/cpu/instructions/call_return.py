"""Calls and returns: CALL nn ; CALL cc,nn ; RET ; RET cc ; RST n ; RETN/RETI.

Condition codes are spelled out per handler (NZ/Z/NC/C/PO/PE/P/M).
"""

from __future__ import annotations

from ..registers import FLAG_C, FLAG_P, FLAG_S, FLAG_Z
from ._dispatch import base, ed


## ─── CALL nn  (0xCD) ───

@base(0xCD)
def call_nn(cpu):
    "CALL nn"
    addr = cpu.fetch_word()
    cpu.push_word(cpu.regs.pc)
    cpu.regs.pc = addr
    cpu.add_t_states(1)


## ─── CALL cc,nn  (0xC4-0xFC) ───
# The target is always fetched; the push+jump (+1 T-state) happen only if cc holds.

@base(0xC4)
def call_nz_nn(cpu):
    "CALL NZ,nn"
    addr = cpu.fetch_word()
    if not (cpu.regs.f & FLAG_Z):
        cpu.push_word(cpu.regs.pc)
        cpu.regs.pc = addr
        cpu.add_t_states(1)


@base(0xCC)
def call_z_nn(cpu):
    "CALL Z,nn"
    addr = cpu.fetch_word()
    if cpu.regs.f & FLAG_Z:
        cpu.push_word(cpu.regs.pc)
        cpu.regs.pc = addr
        cpu.add_t_states(1)


@base(0xD4)
def call_nc_nn(cpu):
    "CALL NC,nn"
    addr = cpu.fetch_word()
    if not (cpu.regs.f & FLAG_C):
        cpu.push_word(cpu.regs.pc)
        cpu.regs.pc = addr
        cpu.add_t_states(1)


@base(0xDC)
def call_c_nn(cpu):
    "CALL C,nn"
    addr = cpu.fetch_word()
    if cpu.regs.f & FLAG_C:
        cpu.push_word(cpu.regs.pc)
        cpu.regs.pc = addr
        cpu.add_t_states(1)


@base(0xE4)
def call_po_nn(cpu):
    "CALL PO,nn"
    addr = cpu.fetch_word()
    if not (cpu.regs.f & FLAG_P):
        cpu.push_word(cpu.regs.pc)
        cpu.regs.pc = addr
        cpu.add_t_states(1)


@base(0xEC)
def call_pe_nn(cpu):
    "CALL PE,nn"
    addr = cpu.fetch_word()
    if cpu.regs.f & FLAG_P:
        cpu.push_word(cpu.regs.pc)
        cpu.regs.pc = addr
        cpu.add_t_states(1)


@base(0xF4)
def call_p_nn(cpu):
    "CALL P,nn"
    addr = cpu.fetch_word()
    if not (cpu.regs.f & FLAG_S):
        cpu.push_word(cpu.regs.pc)
        cpu.regs.pc = addr
        cpu.add_t_states(1)


@base(0xFC)
def call_m_nn(cpu):
    "CALL M,nn"
    addr = cpu.fetch_word()
    if cpu.regs.f & FLAG_S:
        cpu.push_word(cpu.regs.pc)
        cpu.regs.pc = addr
        cpu.add_t_states(1)


## ─── RET  (0xC9) ───

@base(0xC9)
def ret(cpu):
    "RET"
    cpu.regs.pc = cpu.pop_word()


## ─── RET cc  (0xC0-0xF8) ───
# +1 T-state is spent evaluating the condition whether or not it holds.

@base(0xC0)
def ret_nz(cpu):
    "RET NZ"
    cpu.add_t_states(1)
    if not (cpu.regs.f & FLAG_Z):
        cpu.regs.pc = cpu.pop_word()


@base(0xC8)
def ret_z(cpu):
    "RET Z"
    cpu.add_t_states(1)
    if cpu.regs.f & FLAG_Z:
        cpu.regs.pc = cpu.pop_word()


@base(0xD0)
def ret_nc(cpu):
    "RET NC"
    cpu.add_t_states(1)
    if not (cpu.regs.f & FLAG_C):
        cpu.regs.pc = cpu.pop_word()


@base(0xD8)
def ret_c(cpu):
    "RET C"
    cpu.add_t_states(1)
    if cpu.regs.f & FLAG_C:
        cpu.regs.pc = cpu.pop_word()


@base(0xE0)
def ret_po(cpu):
    "RET PO"
    cpu.add_t_states(1)
    if not (cpu.regs.f & FLAG_P):
        cpu.regs.pc = cpu.pop_word()


@base(0xE8)
def ret_pe(cpu):
    "RET PE"
    cpu.add_t_states(1)
    if cpu.regs.f & FLAG_P:
        cpu.regs.pc = cpu.pop_word()


@base(0xF0)
def ret_p(cpu):
    "RET P"
    cpu.add_t_states(1)
    if not (cpu.regs.f & FLAG_S):
        cpu.regs.pc = cpu.pop_word()


@base(0xF8)
def ret_m(cpu):
    "RET M"
    cpu.add_t_states(1)
    if cpu.regs.f & FLAG_S:
        cpu.regs.pc = cpu.pop_word()


## ─── RST n  (0xC7-0xFF) ───

@base(0xC7)
def rst_00(cpu):
    "RST 00H"
    _rst(cpu, 0x00)


@base(0xCF)
def rst_08(cpu):
    "RST 08H"
    _rst(cpu, 0x08)


@base(0xD7)
def rst_10(cpu):
    "RST 10H"
    _rst(cpu, 0x10)


@base(0xDF)
def rst_18(cpu):
    "RST 18H"
    _rst(cpu, 0x18)


@base(0xE7)
def rst_20(cpu):
    "RST 20H"
    _rst(cpu, 0x20)


@base(0xEF)
def rst_28(cpu):
    "RST 28H"
    _rst(cpu, 0x28)


@base(0xF7)
def rst_30(cpu):
    "RST 30H"
    _rst(cpu, 0x30)


@base(0xFF)
def rst_38(cpu):
    "RST 38H"
    _rst(cpu, 0x38)


def _rst(cpu, target: int) -> None:
    cpu.push_word(cpu.regs.pc)
    cpu.regs.pc = target
    cpu.add_t_states(1)


## ─── ED  RETN / RETI  (duplicate slots) ───
# RETI differs from RETN only in the interrupt-daisy-chain signalling that this
# emulator (no chained peripherals) does not model, so both share one handler.

@ed(0x45, 0x4D, 0x55, 0x5D, 0x65, 0x6D, 0x75, 0x7D)
def retn(cpu):
    "RETN / RETI"
    cpu.regs.pc = cpu.pop_word()
    cpu.regs.iff1 = cpu.regs.iff2
