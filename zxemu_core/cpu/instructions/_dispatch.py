"""Dispatch tables and registration decorators for the instruction families.

Each family module (load8, arith8, ...) imports the decorator it needs and
registers its handlers by opcode right at the point of definition, e.g.::

    @base(0x00)
    def nop(cpu):
        "NOP"
        pass

Importing every family module (see instructions/__init__.py) runs those
decorators and fills the four tables below. Z80.step() then indexes them.

Table shapes mirror the historical layout so dispatch behaviour is identical:
  * BASE_TABLE  -- 256 slots, None at unimplemented/prefix bytes (0xCB/0xDD/0xED/0xFD).
  * CB_TABLE    -- 256 slots, fully populated.
  * ED_TABLE    -- 256 slots, defaulting to a shared no-op so undocumented ED
                   bytes behave as harmless 8T NOPs (real hardware never traps).
  * INDEXED_TABLE -- a dict holding ONLY the opcodes a DD/FD prefix changes.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

Handler = Callable[["object"], None]


def ed_nop(cpu) -> None:
    """Undocumented ED opcode: behaves as a no-op (documented safe default)."""
    pass


BASE_TABLE: List[Optional[Handler]] = [None] * 256
CB_TABLE: List[Optional[Handler]] = [None] * 256
ED_TABLE: List[Handler] = [ed_nop] * 256
INDEXED_TABLE: Dict[int, Handler] = {}


def base(*opcodes: int):
    """Register a handler in BASE_TABLE at each given opcode."""
    def register(handler: Handler) -> Handler:
        for opcode in opcodes:
            BASE_TABLE[opcode] = handler
        return handler
    return register


def cb(*opcodes: int):
    """Register a handler in CB_TABLE at each given opcode."""
    def register(handler: Handler) -> Handler:
        for opcode in opcodes:
            CB_TABLE[opcode] = handler
        return handler
    return register


def ed(*opcodes: int):
    """Register a handler in ED_TABLE at each given opcode (duplicates allowed)."""
    def register(handler: Handler) -> Handler:
        for opcode in opcodes:
            ED_TABLE[opcode] = handler
        return handler
    return register


def indexed(*opcodes: int):
    """Register a handler in INDEXED_TABLE (DD/FD) at each given opcode."""
    def register(handler: Handler) -> Handler:
        for opcode in opcodes:
            INDEXED_TABLE[opcode] = handler
        return handler
    return register


def signed8(value: int) -> int:
    """Interpret a byte as a signed two's-complement displacement (-128..127)."""
    return value - 0x100 if value & 0x80 else value
