"""zxemu_core -- a ZX Spectrum, rebuilt in software.

An emulator is a program that *pretends to be* a piece of hardware: it keeps
the same state the real machine would (CPU registers, 64K of memory, the bytes
that make up the screen) and, step by step, does exactly what the real chips
would do with that state. Run the original ROM and games on top of that
faithful pretence and they can't tell they aren't on real silicon.

This package is that pretence for the ZX Spectrum -- both the 48K and the 128K --
in pure Python with no GUI dependency (the user interface lives separately in
``zxemu_ui``), so the emulator can be read, tested, and reused entirely on its own.

The parts, and how they fit together:
    cpu/         The Z80 processor -- the "brain" that reads instructions out
                 of memory and executes them. The heart of the emulator.
    memory.py    The 64K address space, modelled as four swappable 16K banks.
                 The 48K wires them statically; the 128K pages RAM and ROM banks
                 in and out through this same abstraction. Also holds the optional
                 instrumented variant the debugger's watchpoints switch on.
    ula.py       The ULA chip: video/frame timing, the border colour, the 1-bit
                 speaker, and the I/O port (0xFE) the keyboard and border share.
    keyboard.py  The Spectrum's 8x5 key matrix, which the ULA reads.
    beeper.py    The 1-bit speaker: turns timestamped port-0xFE flips into PCM.
    ay.py        The AY-3-8912 sound chip -- three tone voices, noise and an
                 envelope generator -- the 128K's synthesiser.
    mixer.py     Sums the sound sources above into the one stream that gets played,
                 standing in for the resistor network that does the same job in
                 hardware. Each sound chip gets its own file, like ula/keyboard.
    machine.py   Wires the pieces above into a whole "Spectrum" and runs it one
                 frame (1/50th of a second) at a time. ``Machine`` is the 48K;
                 ``Machine128`` subclasses it with 0x7FFD bank paging and the AY.
    snapshot.py  Loads .sna memory-snapshot files (48K and 128K) into a machine.
    tape.py      Reads .tap cassette files into blocks, and fast-loads them by
                 trapping the ROM's own tape routine -- so ``LOAD ""`` completes
                 instantly instead of playing a tape in real time.
    disassembler.py  Turns bytes back into Z80 mnemonics, for the debugger.
    rom_symbols.py   Traditional names for well-known 48K ROM entry points, so a
                     disassembled ``call $15E6`` reads as ``; INPUT-AD``.
    debug_expr.py    The tiny expression language behind conditional breakpoints
                     ("stop here only when A == $FF").
    analysis.py      Questions about the program rather than its current state:
                     search memory, find what refers to an address, and record
                     which addresses have actually executed.

The last four are the debugger's supporting cast. They are here rather than in
``zxemu_ui`` because none of them needs a toolkit -- they reason about bytes and
machine state, so they stay testable (and reusable) without a window.

Learning path: read machine.py first (the big picture / how a frame runs), then
dive into cpu/ (start at cpu/z80.py), then memory / ula / keyboard, and finally
beeper / ay / mixer for how sound is made. snapshot.py and tape.py are best read last:
both are about getting *someone else's* program into the machine, and tape.py in
particular only makes sense once you know how the CPU and ROM interact.
"""
