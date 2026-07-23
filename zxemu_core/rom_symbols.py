"""Names for well-known 48K ROM entry points, for annotating disassembly.

``call $15E6`` tells you almost nothing; ``call $15E6  ; INPUT-AD`` tells you what the
program is *doing*. This module is the lookup that turns one into the other.

These are the traditional names from the published 48K ROM disassembly (Logan &
O'Hara, *The Complete Spectrum ROM Disassembly*) -- the vocabulary Spectrum
programmers have used for forty years, so they are what you will find in any book,
magazine listing, or forum post.

Deliberately partial
--------------------
This is a curated subset -- the restarts, the routines you actually meet while
debugging, and the ones a beginner is likely to call on purpose. It is not the full
ROM map, because a debugger label that is *wrong* is worse than no label at all: it
sends you looking in the wrong place with false confidence. Everything here is a
well-attested address; the rest is left blank rather than guessed at.

Validity
--------
These names describe the **48K BASIC ROM**. They are correct on a 48K machine, and on
a 128K *only while the 48-BASIC ROM (ROM 1) is paged in* -- with ROM 0 (the 128
editor) paged, the same addresses hold entirely different code. ``Machine`` answers
that question via ``rom_symbols_valid``; callers should honour it rather than
labelling blindly.
"""

from __future__ import annotations

# The eight restarts. RST is a one-byte call, which is why the ROM spends its
# lowest addresses on the operations BASIC performs most often.
_RESTARTS = {
    0x0000: "START",        # power-on / RST 0
    0x0008: "ERROR-1",      # RST 8: report an error, code in the byte that follows
    0x0010: "PRINT-A",      # RST 16: print the character in A
    0x0018: "GET-CHAR",     # RST 24: current character from the BASIC line
    0x0020: "NEXT-CHAR",    # RST 32: advance to the next character
    0x0028: "FP-CALC",      # RST 40: enter the floating-point calculator
    0x0030: "BC-SPACES",    # RST 48: make BC bytes of workspace
    0x0038: "MASK-INT",     # RST 56: the IM 1 interrupt handler (keyboard + frames)
}

_ROUTINES = {
    0x0066: "RESET",        # the NMI entry
    0x028E: "KEY-SCAN",     # scan the key matrix
    0x02BF: "KEYBOARD",     # the interrupt's keyboard handler, with repeat/debounce
    0x04C2: "SA-BYTES",     # save a block to tape
    0x0556: "LD-BYTES",     # load a block from tape (the address the fast-load trap uses)
    0x0D6B: "CLS",          # clear the screen
    0x0F2C: "EDITOR",       # the BASIC line editor
    0x10A8: "KEY-INPUT",    # fetch a keypress for the editor
    0x11CB: "START-NEW",    # RAM check and cold start
    0x11DC: "RAM-FILL",     # the RAM-check fill loop
    0x12A2: "MAIN-EXEC",    # the BASIC main execution loop
    0x15D4: "WAIT-KEY",     # wait for a key
    0x15DE: "WAIT-KEY1",
    0x15E6: "INPUT-AD",     # input a character from the current channel
    0x15F2: "PRINT-A-2",    # where RST 16 (PRINT-A) actually lands
    0x1601: "CHAN-OPEN",    # open a channel (screen / printer / stream)
    0x1B17: "LINE-RUN",     # run a BASIC line
    0x2048: "SCANNING",     # evaluate a BASIC expression
    0x28B2: "LOOK-VARS",    # find a variable
    0x2D28: "STACK-BC",     # put BC on the calculator stack
    0x2DE3: "PRINT-FP",     # print a floating-point number
    0x33B4: "STK-STORE",    # store a value on the calculator stack
    0x3D00: "CHAR-SET",     # the character bitmaps (data, not code)
}

SYMBOLS: dict[int, str] = {**_RESTARTS, **_ROUTINES}

ROM_TOP = 0x4000  # symbols only ever describe addresses inside the ROM


def name_for(address: int) -> str | None:
    """The traditional name for a ROM address, or None if it isn't a known entry point."""
    return SYMBOLS.get(address & 0xFFFF)


# How far past a known entry point we still claim to be "inside" it. The table is
# sparse -- 30-odd names across 16K -- so without a limit the nearest preceding symbol
# could be thousands of bytes back and the claim would be pure invention. A debugger
# that confidently names the wrong routine is worse than one that says nothing.
ENCLOSING_LIMIT = 0x100


def enclosing(address: int, limit: int = ENCLOSING_LIMIT):
    """The routine ``address`` falls inside, as (name, offset), or None.

    Where :func:`name_for` answers "is this an entry point?", this answers "which
    routine am I *in*?" -- the question you have while stepping, when PC is somewhere
    in the middle of a routine rather than at its first instruction.

    Returns None when nothing plausible is within ``limit`` bytes; see the constant.
    """
    address &= 0xFFFF
    if address >= ROM_TOP:
        return None
    best = None
    for symbol_address, name in SYMBOLS.items():
        if symbol_address <= address and (best is None or symbol_address > best[0]):
            best = (symbol_address, name)
    if best is None:
        return None
    offset = address - best[0]
    return None if offset > limit else (best[1], offset)


def annotate(text: str, enabled: bool = True) -> str:
    """Append ``; NAME`` to a disassembled line if it references a known ROM routine.

    Scans the line for a ``$xxxx`` operand and looks it up, so ``call $15E6`` becomes
    ``call $15E6  ; INPUT-AD`` without the disassembler needing to know anything about
    the ROM. Returns the text unchanged when nothing matches, or when ``enabled`` is
    False (see the module docstring on 128K paging).
    """
    if not enabled:
        return text
    for token in text.replace(",", " ").replace("(", " ").replace(")", " ").split():
        if token.startswith("$") and len(token) == 5:
            try:
                address = int(token[1:], 16)
            except ValueError:
                continue
            if address < ROM_TOP:
                name = name_for(address)
                if name is not None:
                    return f"{text}  ; {name}"
    return text
