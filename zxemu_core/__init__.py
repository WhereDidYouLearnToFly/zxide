"""zxemu_core -- a ZX Spectrum, rebuilt in software.

An emulator is a program that *pretends to be* a piece of hardware: it keeps
the same state the real machine would (CPU registers, 64K of memory, the bytes
that make up the screen) and, step by step, does exactly what the real chips
would do with that state. Run the original ROM and games on top of that
faithful pretence and they can't tell they aren't on real silicon.

This package is that pretence for the ZX Spectrum -- the 48K, the 128K, and the
Soviet-era **Pentagon 128** clone -- in pure Python with no GUI dependency (the user
interface lives separately in ``zxemu_ui``), so the emulator can be read, tested, and
reused entirely on its own.

The machine itself sits at the top level -- these six files *are* the Spectrum:


    machine.py   Wires everything below into a whole "Spectrum" and runs it one
                 frame (1/50th of a second) at a time. Three machines, each
                 subclassing the last: ``Machine`` is the 48K, ``Machine128`` adds
                 0x7FFD bank paging and the AY, and ``MachinePentagon`` adds the
                 clone's own frame timing, no memory contention, and a built-in
                 disk interface. **Start here**: it is the big picture in one file.
    memory.py    The 64K address space, modelled as four swappable 16K banks.
                 The 48K wires them statically; the 128K pages RAM and ROM banks
                 in and out through this same abstraction. Also holds the optional
                 instrumented variant the debugger's watchpoints switch on.
    ula.py       The ULA chip: video/frame timing, the border colour, the 1-bit
                 speaker, and the I/O port (0xFE) the keyboard and border share.
    keyboard.py  The Spectrum's 8x5 key matrix, which the ULA reads.
    mouse.py     The Kempston Mouse: a buttons byte and two free-running X/Y
                 counters, at 0xFADF/0xFBDF/0xFFDF and, because the interface
                 decodes only four address lines, at every other port with A0
                 set and A5 clear. Off by default -- see ``Machine.mouse.enabled``
                 -- so it stays invisible both to software probing for a mouse
                 that isn't fitted and to the neighbours it would sit on top of.
    joystick.py  The Kempston Joystick: switches in one byte at port 0x1F,
                 **active high**, so an absent interface reads as everything
                 pressed rather than as nothing. Eight bits, following the ZX
                 Spectrum Next: directions and two fires always, A and START
                 only in its MD 3-button mode (that masking is the whole
                 difference between the Next's two modes). Off by default and
                 mutually exclusive with the mouse -- both answer 0x1F, and on
                 real hardware the two fight over the data bus.

One more file sits alongside them, about the address space rather than the hardware:

    memlayout.py Where things *fit*: free-space tracking across the banks, reserved
                 ranges (screen, ROM, hand-written code) and the auto-locate search
                 that places an imported asset somewhere it won't collide.

Everything else is grouped by subsystem, each with its own overview:

    cpu/         The Z80 processor -- the "brain" that reads instructions out of
                 memory and executes them. The heart of the emulator.
    sound/       The beeper, the AY chip, and the mixer that sums them the way a
                 resistor network does in hardware.
    storage/     Getting somebody else's program in: .sna and .z80 snapshots,
                 .tap and .tzx tapes (loaded instantly *or* as real pulses), and
                 -- in ``storage/disk/`` -- the Beta 128 interface, a WD1793
                 floppy controller and TR-DOS .trd/.scl disks.
    assets/      Turning your source material into Spectrum bytes: bitmaps and
                 sprite sheets, fonts, tilemaps, binaries, PT3 tunes, beeper SFX --
                 plus the manifest that records them and the previews that draw them.
    debug/       Making sense of a running machine: disassembler, ROM routine
                 names, breakpoint expressions, and whole-program analysis.

Why ``debug/`` and ``assets/`` live here rather than in the UI: neither needs a
toolkit. They reason about bytes and machine state, so they stay testable -- and
reusable -- with no window in sight, and the panels in ``zxemu_ui`` are thin
presentation over them.

Learning path: machine.py first (how a frame runs), then cpu/ (start at cpu/z80.py),
then memory / ula / keyboard, then sound/. Leave storage/ and debug/ until last --
both assume you already know how the CPU and ROM interact. ``assets/`` and
``memlayout.py`` are independent of all of it: they are about your *build*, not about
the running machine, and can be read at any point.
"""
