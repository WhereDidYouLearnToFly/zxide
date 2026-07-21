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
                 in and out through this same abstraction.
    ula.py       The ULA chip: video/frame timing, the border colour, the 1-bit
                 speaker, and the I/O port (0xFE) the keyboard and border share.
    keyboard.py  The Spectrum's 8x5 key matrix, which the ULA reads.
    audio.py     Turns the beeper's 1-bit speaker flips into PCM sound, plus the
                 SoundMixer that blends the beeper with the 128K's AY chip.
    ay.py        The AY-3-8912 sound chip -- three tone voices, noise and an
                 envelope generator -- the 128K's synthesiser.
    machine.py   Wires the pieces above into a whole "Spectrum" and runs it one
                 frame (1/50th of a second) at a time. ``Machine`` is the 48K;
                 ``Machine128`` subclasses it with 0x7FFD bank paging and the AY.
    snapshot.py  Loads .sna memory-snapshot files (48K and 128K) into a machine.
    disassembler.py  Turns bytes back into Z80 mnemonics, for the debugger.

Learning path: read machine.py first (the big picture / how a frame runs), then
dive into cpu/ (start at cpu/z80.py), then memory / ula / keyboard, and finally
audio / ay for how sound is made.
"""
