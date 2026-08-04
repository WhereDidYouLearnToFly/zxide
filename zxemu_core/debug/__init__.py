"""Debug support: making sense of a running machine, without needing a window.

Everything here answers a question *about* the program rather than helping it run.
None of it is required to emulate a Spectrum -- delete this package and the machine
still boots -- and none of it imports Qt, which is the point: the reasoning is
testable on its own, and the UI panels in ``zxemu_ui`` are thin presentation over it.

    disassembler.py  Bytes back into Z80 mnemonics. Decodes via the classic octal
                     split of the opcode byte, so the whole instruction set is a
                     handful of rules rather than a 1500-entry table.
    asm_meter.py     The opposite direction, and the only module here that reads
                     *source* rather than memory: how many bytes and T-states a run
                     of assembly costs, so "does this fit" and "does this finish
                     inside a frame" are answerable by selecting the code.
    asm_layout.py    The same direction again, one level up: not what a run of source
                     *costs* but where it *lands*. Reads the directives that decide
                     layout -- org, MODULE, SLOT/PAGE, include, incbin -- so the memory
                     map can show where your code lives before a build has ever run,
                     which is what stops auto-locate dropping an asset on top of it.
    asm_hidden.py    The characters that are in a file, mean something to the
                     assembler, and draw nothing -- a file-type marker that has
                     drifted off line 1, a pasted non-breaking space, a zero-width
                     space inside a label. Named so the editor can mark them and
                     refuse to paste them, because the failure mode is an error
                     message about a character nobody can see.
    asm_defs.py      Where a name comes from: labels, ``equ`` constants, macros and
                     modules, indexed across the whole include tree so "go to
                     definition" reaches the one of a dozen files it actually lives
                     in. Names inside a ``MODULE`` are indexed twice, bare and
                     qualified, because that is how the two halves of a project
                     spell the same label.
    asm_help.py      What an instruction is *for*, in one line, plus the flags it
                     disturbs -- the editor's hover help. Prices the exact operand
                     form under the cursor through ``asm_meter``'s tables rather
                     than repeating them.
    asm_symbols.py   The constants a source file defines with ``equ``, and what they
                     come to, so hover help can answer ``ld hl,SCREEN`` with the
                     address. Reads source, not a build, so the values are there
                     while you type -- and says nothing rather than guess when an
                     expression needs the assembler (``$``, macro arguments).
    rom_symbols.py   Traditional names for 48K ROM entry points, so ``call $15E6``
                     reads as ``; INPUT-AD`` and stepping through the ROM tells you
                     which routine you are in.
    debug_expr.py    The tiny expression language behind conditional breakpoints:
                     ``A == $FF``, ``(HL) == 0``, ``B == 0 and C == 0``.
    analysis.py      Whole-program questions: search memory, find what refers to an
                     address, record which addresses have actually executed.
    dumper.py        The consumer of all of the above: memory back into *source*.
                     Coverage decides what is code (an address that executed is code,
                     observed rather than guessed); everything else stays bytes, which
                     assembles to the same program either way. Arranged so the dump can
                     be reassembled and compared byte-for-byte against the memory it
                     came from -- the only thing that makes a disassembly trustworthy.

A theme worth noticing while reading these: **they differ in how much they can
promise, and each says so.** The disassembler is exact *as a decoding* -- though not
reversible, which ``dumper.py`` has to work around: several byte patterns print as the
same mnemonic, so it keeps those as raw bytes rather than let a rebuild change them.
Search is exact. Cross-references are a static scan that can be fooled by data
resembling code and cannot follow computed jumps. Coverage never lies about what ran
but only knows what has run *so far*. ROM names are a curated subset, left blank
rather than guessed.

That honesty is not decoration. A debugging tool that hides its uncertainty sends you
looking in the wrong place while feeling confident, which is worse than a tool that
tells you nothing.
"""

from __future__ import annotations

from zxemu_core.debug import analysis, asm_defs, asm_hidden, asm_help, asm_layout, asm_meter, asm_symbols, debug_expr, disassembler, dumper, rom_symbols

__all__ = ["analysis", "asm_defs", "asm_hidden", "asm_help", "asm_layout", "asm_meter", "asm_symbols", "debug_expr", "disassembler", "dumper", "rom_symbols"]
