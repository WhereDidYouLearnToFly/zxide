"""The Z80 CPU -- the heart of the emulator.

A CPU does one thing, forever, in a loop:
    1. FETCH   the next instruction byte from memory (at the address in PC),
    2. DECODE  it to work out which operation it means,
    3. EXECUTE it -- change registers, memory, and flags accordingly,
then repeat with the following instruction. Emulating a CPU is really just
writing that loop honestly, plus a faithful body for every instruction.

Files, in a sensible reading order:
    z80.py         The fetch-decode-execute loop itself, plus interrupt
                   handling and HALT. Read this first -- it ties it all
                   together and is the shortest way to see how a CPU "ticks".
    registers.py   The Z80's registers (A, F, BC, DE, HL, IX, IY, SP, PC, the
                   shadow set) and the individual flag bits (S Z H P/V N C).
    flags.py       The arithmetic/flag math -- how ADD, SUB, INC, rotates, DAA
                   and friends compute their result *and* their flags. This is
                   where most of the fiddly detail of a CPU actually lives.
    instructions/  One module per instruction family; each opcode's behaviour
                   is spelled out as an explicit little function. This is where
                   "what does opcode 0x80 do?" is answered directly.
"""
