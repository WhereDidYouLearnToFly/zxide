"""A Z80 disassembler: decode the bytes at an address into readable assembly.

Decoding uses the classic octal decomposition of an opcode byte into x/y/z (and
p/q), which turns the whole instruction set into a compact set of rules rather than
a 1500-entry table. It covers the unprefixed set plus the CB, ED, DD/FD and
DD-CB/FD-CB prefix groups (including the common undocumented forms).

The disassembler is pure Z80 and machine-agnostic -- it reads bytes through a
``memory`` object's ``read_byte`` and carries over unchanged to the 128K machine.

Output style: lowercase mnemonics, ``$`` hex, e.g. ``ld a,($5c00)`` / ``jr $8000``.
"""

from __future__ import annotations

_R = ["b", "c", "d", "e", "h", "l", "(hl)", "a"]
_RP = ["bc", "de", "hl", "sp"]
_RP2 = ["bc", "de", "hl", "af"]
_CC = ["nz", "z", "nc", "c", "po", "pe", "p", "m"]
_ALU = ["add a,{}", "adc a,{}", "sub {}", "sbc a,{}", "and {}", "xor {}", "or {}", "cp {}"]
_ROT = ["rlc", "rrc", "rl", "rr", "sla", "sra", "sll", "srl"]
_IM = ["0", "0", "1", "2", "0", "0", "1", "2"]
_BLOCK = [
    ["ldi", "cpi", "ini", "outi"],
    ["ldd", "cpd", "ind", "outd"],
    ["ldir", "cpir", "inir", "otir"],
    ["lddr", "cpdr", "indr", "otdr"],
]
_ED_X1Z7 = ["ld i,a", "ld r,a", "ld a,i", "ld a,r", "rrd", "rld", "nop", "nop"]
_X0Z7 = ["rlca", "rrca", "rla", "rra", "daa", "cpl", "scf", "ccf"]


class _Reader:
    """Reads consecutive bytes from memory, counting how many the instruction used."""

    def __init__(self, memory, address: int):
        self.memory = memory
        self.start = address & 0xFFFF
        self.count = 0

    def byte(self) -> int:
        value = self.memory.read_byte((self.start + self.count) & 0xFFFF)
        self.count += 1
        return value

    def signed(self) -> int:
        value = self.byte()
        return value - 256 if value >= 128 else value

    def word(self) -> int:
        lo = self.byte()
        return lo | (self.byte() << 8)


def _n(value: int) -> str:
    return f"${value & 0xFF:02X}"


def _nn(value: int) -> str:
    return f"${value & 0xFFFF:04X}"


def _rel(r: _Reader, disp: int) -> str:
    # Target of a relative jump: the address after this instruction, plus the offset.
    return _nn((r.start + r.count + disp) & 0xFFFF)


def _indexed(r: _Reader, idx: str) -> str:
    disp = r.signed()
    return f"({idx}{'+' if disp >= 0 else '-'}${abs(disp):02X})"


def _reg(r: _Reader, index: int, idx: str | None) -> str:
    """Register name for a single operand, applying DD/FD (IX/IY) substitution."""
    if idx is None:
        return _R[index]
    if index == 6:
        return _indexed(r, idx)
    if index == 4:
        return idx + "h"
    if index == 5:
        return idx + "l"
    return _R[index]


def _rp(index: int, idx: str | None) -> str:
    return idx if (index == 2 and idx) else _RP[index]


def _rp2(index: int, idx: str | None) -> str:
    return idx if (index == 2 and idx) else _RP2[index]


def _ld_pair(r: _Reader, y: int, z: int, idx: str | None) -> str:
    """The 'ld r,r'' operands, honouring the DD/FD quirk around (IX+d) vs H/L."""
    if idx is not None and (y == 6 or z == 6):
        # One operand is (IX+d); the register operand stays plain H/L, not IXH/IXL.
        mem = _indexed(r, idx)
        dst = mem if y == 6 else _R[y]
        src = mem if z == 6 else _R[z]
        return f"{dst},{src}"
    if idx is not None:
        return f"{_reg_hl(y, idx)},{_reg_hl(z, idx)}"
    return f"{_R[y]},{_R[z]}"


def _reg_hl(index: int, idx: str) -> str:
    if index == 4:
        return idx + "h"
    if index == 5:
        return idx + "l"
    return _R[index]


def disassemble_one(memory, address: int) -> tuple[str, int]:
    """Return ``(text, length_in_bytes)`` for the instruction at ``address``."""
    r = _Reader(memory, address)
    op = r.byte()
    if op == 0xCB:
        text = _decode_cb(r)
    elif op == 0xED:
        text = _decode_ed(r)
    elif op == 0xDD:
        text = _decode_indexed(r, "ix")
    elif op == 0xFD:
        text = _decode_indexed(r, "iy")
    else:
        text = _decode_base(r, op, None)
    return text, r.count


def disassemble(memory, address: int, count: int) -> list[tuple[int, bytes, str]]:
    """Disassemble ``count`` instructions; each item is (address, raw_bytes, text)."""
    out = []
    addr = address & 0xFFFF
    for _ in range(count):
        text, length = disassemble_one(memory, addr)
        raw = bytes(memory.read_byte((addr + i) & 0xFFFF) for i in range(length))
        out.append((addr, raw, text))
        addr = (addr + length) & 0xFFFF
    return out


def _decode_base(r: _Reader, op: int, idx: str | None) -> str:
    x, y, z = op >> 6, (op >> 3) & 7, op & 7
    p, q = y >> 1, y & 1
    hl = idx or "hl"

    if x == 0:
        if z == 0:
            if y == 0:
                return "nop"
            if y == 1:
                return "ex af,af'"
            if y == 2:
                return f"djnz {_rel(r, r.signed())}"
            if y == 3:
                return f"jr {_rel(r, r.signed())}"
            return f"jr {_CC[y - 4]},{_rel(r, r.signed())}"
        if z == 1:
            if q == 0:
                return f"ld {_rp(p, idx)},{_nn(r.word())}"
            return f"add {hl},{_rp(p, idx)}"
        if z == 2:
            if q == 0:
                if p == 0:
                    return "ld (bc),a"
                if p == 1:
                    return "ld (de),a"
                if p == 2:
                    return f"ld ({_nn(r.word())}),{hl}"
                return f"ld ({_nn(r.word())}),a"
            if p == 0:
                return "ld a,(bc)"
            if p == 1:
                return "ld a,(de)"
            if p == 2:
                return f"ld {hl},({_nn(r.word())})"
            return f"ld a,({_nn(r.word())})"
        if z == 3:
            return f"{'inc' if q == 0 else 'dec'} {_rp(p, idx)}"
        if z == 4:
            return f"inc {_reg(r, y, idx)}"
        if z == 5:
            return f"dec {_reg(r, y, idx)}"
        if z == 6:
            dest = _reg(r, y, idx)
            return f"ld {dest},{_n(r.byte())}"
        return _X0Z7[y]

    if x == 1:
        if y == 6 and z == 6:
            return "halt"
        return f"ld {_ld_pair(r, y, z, idx)}"

    if x == 2:
        return _ALU[y].format(_reg(r, z, idx))

    # x == 3
    if z == 0:
        return f"ret {_CC[y]}"
    if z == 1:
        if q == 0:
            return f"pop {_rp2(p, idx)}"
        if p == 0:
            return "ret"
        if p == 1:
            return "exx"
        if p == 2:
            return f"jp ({hl})"
        return f"ld sp,{hl}"
    if z == 2:
        return f"jp {_CC[y]},{_nn(r.word())}"
    if z == 3:
        if y == 0:
            return f"jp {_nn(r.word())}"
        if y == 2:
            return f"out ({_n(r.byte())}),a"
        if y == 3:
            return f"in a,({_n(r.byte())})"
        if y == 4:
            return f"ex (sp),{hl}"
        if y == 5:
            return "ex de,hl"
        if y == 6:
            return "di"
        if y == 7:
            return "ei"
        return "?"  # y == 1 is the CB prefix, handled before we reach here
    if z == 4:
        return f"call {_CC[y]},{_nn(r.word())}"
    if z == 5:
        if q == 0:
            return f"push {_rp2(p, idx)}"
        if p == 0:
            return f"call {_nn(r.word())}"
        return "?"  # DD/ED/FD prefixes, handled before we reach here
    if z == 6:
        return _ALU[y].format(_n(r.byte()))
    return f"rst ${y * 8:02X}"


def _decode_cb(r: _Reader) -> str:
    op = r.byte()
    x, y, z = op >> 6, (op >> 3) & 7, op & 7
    target = _R[z]
    if x == 0:
        return f"{_ROT[y]} {target}"
    return f"{('bit', 'res', 'set')[x - 1]} {y},{target}"


def _decode_ed(r: _Reader) -> str:
    op = r.byte()
    x, y, z = op >> 6, (op >> 3) & 7, op & 7
    p, q = y >> 1, y & 1
    if x == 1:
        if z == 0:
            return "in (c)" if y == 6 else f"in {_R[y]},(c)"
        if z == 1:
            return "out (c),0" if y == 6 else f"out (c),{_R[y]}"
        if z == 2:
            return f"{'sbc' if q == 0 else 'adc'} hl,{_RP[p]}"
        if z == 3:
            if q == 0:
                return f"ld ({_nn(r.word())}),{_RP[p]}"
            return f"ld {_RP[p]},({_nn(r.word())})"
        if z == 4:
            return "neg"
        if z == 5:
            return "reti" if y == 1 else "retn"
        if z == 6:
            return f"im {_IM[y]}"
        return _ED_X1Z7[y]
    if x == 2 and z <= 3 and y >= 4:
        return _BLOCK[y - 4][z]
    return "nop"  # invalid ED opcode


def _decode_indexed(r: _Reader, idx: str) -> str:
    op = r.byte()
    if op == 0xCB:
        mem = _indexed(r, idx)  # displacement comes before the CB opcode
        cb = r.byte()
        x, y, z = cb >> 6, (cb >> 3) & 7, cb & 7
        if x == 0:
            base = f"{_ROT[y]} {mem}"
            return base if z == 6 else f"{base},{_R[z]}"  # undocumented register store
        if x == 1:
            return f"bit {y},{mem}"
        base = f"{('res', 'set')[x - 2]} {y},{mem}"
        return base if z == 6 else f"{base},{_R[z]}"
    if op == 0xED:
        return _decode_ed(r)  # DD/FD before ED: the index prefix is ignored
    if op in (0xDD, 0xFD):
        return _decode_indexed(r, "ix" if op == 0xDD else "iy")  # last prefix wins
    return _decode_base(r, op, idx)
