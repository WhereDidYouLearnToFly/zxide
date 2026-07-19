"""Z80 register file: 8-bit halves stored directly, 16-bit pairs as computed properties."""

from __future__ import annotations

FLAG_C = 0x01
FLAG_N = 0x02
FLAG_P = 0x04  # P/V (parity or overflow, depending on instruction)
FLAG_X = 0x08  # undocumented, mirrors bit 3 of the result
FLAG_H = 0x10
FLAG_Y = 0x20  # undocumented, mirrors bit 5 of the result
FLAG_Z = 0x40
FLAG_S = 0x80


def _pair(hi_name: str, lo_name: str) -> property:
    def getter(self) -> int:
        return (getattr(self, hi_name) << 8) | getattr(self, lo_name)

    def setter(self, value: int) -> None:
        value &= 0xFFFF
        setattr(self, hi_name, value >> 8)
        setattr(self, lo_name, value & 0xFF)

    return property(getter, setter)


class Registers:
    """Plain 8-bit register halves; 16-bit pairs (bc, hl, ...) are properties over them."""

    def __init__(self) -> None:
        # Main set
        self.a = 0
        self.f = 0
        self.b = 0
        self.c = 0
        self.d = 0
        self.e = 0
        self.h = 0
        self.l = 0
        # Shadow (alternate) set
        self.a2 = 0
        self.f2 = 0
        self.b2 = 0
        self.c2 = 0
        self.d2 = 0
        self.e2 = 0
        self.h2 = 0
        self.l2 = 0
        # Index registers
        self.ixh = 0
        self.ixl = 0
        self.iyh = 0
        self.iyl = 0
        # Special purpose
        self.sp = 0
        self.pc = 0
        self.i = 0
        self.r = 0
        self.iff1 = False
        self.iff2 = False
        self.im = 0

    af = _pair("a", "f")
    bc = _pair("b", "c")
    de = _pair("d", "e")
    hl = _pair("h", "l")
    af2 = _pair("a2", "f2")
    bc2 = _pair("b2", "c2")
    de2 = _pair("d2", "e2")
    hl2 = _pair("h2", "l2")
    ix = _pair("ixh", "ixl")
    iy = _pair("iyh", "iyl")

    def get_flag(self, mask: int) -> bool:
        return bool(self.f & mask)

    def set_flag(self, mask: int, value: bool) -> None:
        if value:
            self.f |= mask
        else:
            self.f &= ~mask & 0xFF
