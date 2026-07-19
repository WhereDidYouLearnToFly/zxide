"""The Z80 instruction set, one readable module per instruction family.

Every opcode the CPU can run is a small function here that says exactly what
that instruction does to the machine. They are grouped by family and -- apart
from the deliberately compact ``indexed_bit`` module -- spelled out one explicit
handler per opcode, so you can search for a mnemonic (say ``ADD A,B``) and read
its code directly, instead of it being synthesised by clever loops.

How dispatch works (how a byte becomes a running instruction):
Importing this package imports every family module below; each module's
``@base`` / ``@cb`` / ``@ed`` / ``@indexed`` decorators run at import time and
register their handlers into the dispatch tables held in ``_dispatch``. After
that the four tables are fully populated, and are re-exported here for the CPU
core (z80.py) to index by opcode byte.

Family modules (explicit handlers, mnemonic in each one's docstring):
    load8, load16, exchange, arith8, arith16, rotate_shift, bit,
    jump, call_return, control, blockio, indexed
plus indexed_bit -- the DDCB/FDCB decoder, kept intentionally compact to
demonstrate the table-driven code-generation technique as a contrast to the
explicit style used everywhere else.
"""

from __future__ import annotations

from ._dispatch import BASE_TABLE, CB_TABLE, ED_TABLE, INDEXED_TABLE

# Importing each family runs its @base/@cb/@ed/@indexed decorators, which is
# what actually fills the tables above. Order does not matter: every opcode is
# owned by exactly one module.
from . import (  # noqa: E402,F401  (imported for side effects: table registration)
    load8,
    load16,
    exchange,
    arith8,
    arith16,
    rotate_shift,
    bit,
    jump,
    call_return,
    control,
    blockio,
    indexed,
)
from .indexed_bit import execute_ddcb  # noqa: E402

__all__ = [
    "BASE_TABLE",
    "CB_TABLE",
    "ED_TABLE",
    "INDEXED_TABLE",
    "execute_ddcb",
]
