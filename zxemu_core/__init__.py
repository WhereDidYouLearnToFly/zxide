"""zxemu_core -- a ZX Spectrum, rebuilt in software.

An emulator is a program that *pretends to be* a piece of hardware: it keeps
the same state the real machine would (CPU registers, 64K of memory, the bytes
that make up the screen) and, step by step, does exactly what the real chips
would do with that state. Run the original ROM and games on top of that
faithful pretence and they can't tell they aren't on real silicon.

This package is that pretence for the 48K ZX Spectrum, in pure Python with no
GUI dependency (the user interface lives separately in ``zxemu_ui``), so the
emulator can be read, tested, and reused entirely on its own.

The parts, and how they fit together:
    cpu/         The Z80 processor -- the "brain" that reads instructions out
                 of memory and executes them. The heart of the emulator.
    memory.py    The 64K address space (16K ROM + 48K RAM), modelled as
                 swappable 16K banks (already paging-ready for a future 128K).
    ula.py       The ULA chip: video/frame timing, the border colour, and the
                 I/O port (0xFE) that the keyboard and border share.
    keyboard.py  The Spectrum's 8x5 key matrix, which the ULA reads.
    machine.py   Wires the pieces above into a whole "Spectrum" and runs it one
                 frame (1/50th of a second of Spectrum time) at a time.

Learning path: read machine.py first (the big picture / how a frame runs),
then dive into cpu/ (start at cpu/z80.py), then memory / ula / keyboard.
"""
