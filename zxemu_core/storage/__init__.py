"""Storage: getting somebody else's program *into* the machine.

Three kinds of medium, three completely different philosophies, which is why these are
separate modules rather than one "loader". A snapshot restores a machine; a tape is a
signal the machine has to listen to; a disk is a filesystem it can read *and write*.

    snapshot.py  ``.sna`` -- a photograph of the machine. Registers, and every byte
                 of RAM, captured mid-run. Loading one doesn't *run* anything; it
                 restores a machine that was already running and lets it continue.
    z80.py       ``.z80`` -- the same idea, better dressed: versioned, compressed, and
                 explicit about which machine it came from (which ``.sna`` can only
                 infer from its file size).
    tape.py      ``.tap`` -- a recording of a cassette. Not machine state at all, but
                 a stream of blocks the ROM's own loading routine reads, exactly as
                 it would from real tape.
    tzx.py       ``.tzx`` -- a cassette recording with the *timings and structure*
                 kept too: which blocks were recorded fast, where the bare tones and
                 silences fall. It reduces to ``tape.py``'s blocks for loading, and
                 keeps everything else for playing.
    pulse.py     the same tape as a *signal*: blocks turned back into the pilot, sync
                 and bit pulses a real ULA samples on port 0xFE bit 6.
    disk/        ``.trd``/``.scl`` -- TR-DOS floppies, plus the Beta 128 interface and
                 the WD1793 controller that read them. A subpackage rather than a
                 module because a disk brings its own *hardware* with it: the other
                 formats here are read by the machine we already have, while a disk
                 needs a controller, drives, and a ROM that pages itself in. See its
                 own overview. Only a Pentagon has one.

The tape side is the interesting one, because it is loaded **two entirely different
ways** and the choice is the user's (Load ▸ Tape Deck ▸ Fast Load):

* **The trap.** When the CPU reaches ``LD-BYTES`` the whole block is delivered at once
  and the routine is made to return as if it had spent several seconds reading. Tapes
  load instantly. The catch is that it only knows about *the ROM's* routine, so a game
  with its own turbo loader -- which bypasses ``LD-BYTES`` entirely -- gets no help.
* **Edge replay.** The pulses are generated for real, in real time, and the loader
  works the bytes out by timing them. Slow, and the only thing a turbo loader will
  accept. The loading stripes and the tape sound come with it, because both are things
  the machine genuinely does while loading rather than effects we draw.

They share ``tape.py``'s block model and, importantly, a single play head -- a
commercial multi-part tape often starts under the ROM loader and hands over to its own
loader partway through.
"""

from __future__ import annotations

from zxemu_core.storage import disk, pulse, snapshot, tape, tzx, z80

__all__ = ["disk", "pulse", "snapshot", "tape", "tzx", "z80"]
