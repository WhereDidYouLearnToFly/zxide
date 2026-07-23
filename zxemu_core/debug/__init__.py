"""Debug support: making sense of a running machine, without needing a window.

Everything here answers a question *about* the program rather than helping it run.
None of it is required to emulate a Spectrum -- delete this package and the machine
still boots -- and none of it imports Qt, which is the point: the reasoning is
testable on its own, and the UI panels in ``zxemu_ui`` are thin presentation over it.

    disassembler.py  Bytes back into Z80 mnemonics. Decodes via the classic octal
                     split of the opcode byte, so the whole instruction set is a
                     handful of rules rather than a 1500-entry table.
    rom_symbols.py   Traditional names for 48K ROM entry points, so ``call $15E6``
                     reads as ``; INPUT-AD`` and stepping through the ROM tells you
                     which routine you are in.
    debug_expr.py    The tiny expression language behind conditional breakpoints:
                     ``A == $FF``, ``(HL) == 0``, ``B == 0 and C == 0``.
    analysis.py      Whole-program questions: search memory, find what refers to an
                     address, record which addresses have actually executed.

A theme worth noticing while reading these: **they differ in how much they can
promise, and each says so.** The disassembler is exact. Search is exact.
Cross-references are a static scan that can be fooled by data resembling code and
cannot follow computed jumps. Coverage never lies about what ran but only knows what
has run *so far*. ROM names are a curated subset, left blank rather than guessed.

That honesty is not decoration. A debugging tool that hides its uncertainty sends you
looking in the wrong place while feeling confident, which is worse than a tool that
tells you nothing.
"""

from __future__ import annotations

from zxemu_core.debug import analysis, debug_expr, disassembler, rom_symbols

__all__ = ["analysis", "debug_expr", "disassembler", "rom_symbols"]
