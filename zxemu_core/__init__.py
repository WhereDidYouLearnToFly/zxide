"""zxemu_core -- a ZX Spectrum, rebuilt in software.

An emulator is a program that *pretends to be* a piece of hardware: it keeps
the same state the real machine would (CPU registers, 64K of memory, the bytes
that make up the screen) and, step by step, does exactly what the real chips
would do with that state. Run the original ROM and games on top of that
faithful pretence and they can't tell they aren't on real silicon.

This package is that pretence for the ZX Spectrum -- both the 48K and the 128K --
in pure Python with no GUI dependency (the user interface lives separately in
``zxemu_ui``), so the emulator can be read, tested, and reused entirely on its own.

The machine itself sits at the top level -- these four files *are* the Spectrum:

    machine.py   Wires everything below into a whole "Spectrum" and runs it one
                 frame (1/50th of a second) at a time. ``Machine`` is the 48K;
                 ``Machine128`` subclasses it with 0x7FFD bank paging and the AY.
                 **Start here**: it is the big picture in one short file.
    memory.py    The 64K address space, modelled as four swappable 16K banks.
                 The 48K wires them statically; the 128K pages RAM and ROM banks
                 in and out through this same abstraction. Also holds the optional
                 instrumented variant the debugger's watchpoints switch on.
    ula.py       The ULA chip: video/frame timing, the border colour, the 1-bit
                 speaker, and the I/O port (0xFE) the keyboard and border share.
    keyboard.py  The Spectrum's 8x5 key matrix, which the ULA reads.

Everything else is grouped by subsystem, each with its own overview:

    cpu/         The Z80 processor -- the "brain" that reads instructions out of
                 memory and executes them. The heart of the emulator.
    sound/       The beeper, the AY chip, and the mixer that sums them the way a
                 resistor network does in hardware.
    storage/     Getting somebody else's program in: .sna snapshots and .tap tapes.
    debug/       Making sense of a running machine: disassembler, ROM routine
                 names, breakpoint expressions, and whole-program analysis.

Why ``debug/`` lives here rather than in the UI: none of it needs a toolkit. It
reasons about bytes and machine state, so it stays testable -- and reusable -- with
no window in sight, and the panels in ``zxemu_ui`` are thin presentation over it.

Learning path: machine.py first (how a frame runs), then cpu/ (start at cpu/z80.py),
then memory / ula / keyboard, then sound/. Leave storage/ and debug/ until last --
both assume you already know how the CPU and ROM interact.
"""
