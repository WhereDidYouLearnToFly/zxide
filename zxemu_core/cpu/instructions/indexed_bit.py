"""DDCB/FDCB rotate/shift/BIT/RES/SET on (IX+d)/(IY+d).

DELIBERATELY COMPACT / TABLE-DRIVEN
-----------------------------------
Unlike every other family module in this package (which spells out one explicit
handler per opcode), this one is intentionally left as a single dispatch
function keyed on the opcode's group/field/target bit-fields. It is kept this
way on purpose to DEMONSTRATE the code-generation / bit-field decoding technique
as a contrast to the explicit style used elsewhere.

It also genuinely fits the hardware: every DDCB/FDCB opcode operates on the
*same* (idx+d) memory location regardless of its register field, and when that
field is not 6 the result is *also* copied into that (plain, not IXH/IXL)
register -- a well-documented undocumented quirk exercised heavily by zexall.
Because of that shared-memory-operand behaviour it is not a flat 256-entry table
like the CB group; one decoded function serves all 256 sub-opcodes.
"""

from __future__ import annotations

from .. import flags as alu

_R8_ATTR = ["b", "c", "d", "e", "h", "l", None, "a"]


def execute_ddcb(cpu, displacement: int, opcode: int) -> None:
    addr = (getattr(cpu.regs, cpu._idx_pair) + displacement) & 0xFFFF
    group = (opcode >> 6) & 3
    field = (opcode >> 3) & 7
    target = opcode & 7

    value = cpu.read_mem(addr)

    if group == 0:  # rotate/shift
        if field == 2:
            result, f = alu.rl(value, cpu.regs.f & 0x01)
        elif field == 3:
            result, f = alu.rr_(value, cpu.regs.f & 0x01)
        else:
            result, f = alu.ROTATE_SHIFT_OPS[field](value)
        cpu.write_mem(addr, result)
        cpu.regs.f = f
        if target != 6:
            setattr(cpu.regs, _R8_ATTR[target], result)
        cpu.add_t_states(3)
    elif group == 1:  # BIT
        cpu.regs.f = alu.bit_memory(value, field, cpu.regs.f, (addr >> 8) & 0xFF)
        cpu.add_t_states(3)
    else:  # RES (group 2) / SET (group 3)
        result = alu.res(value, field) if group == 2 else alu.set_bit(value, field)
        cpu.write_mem(addr, result)
        if target != 6:
            setattr(cpu.regs, _R8_ATTR[target], result)
        cpu.add_t_states(3)
