"""Storage: getting somebody else's program *into* the machine.

Two kinds of file, two completely different philosophies, which is why they are
separate modules rather than one "loader":

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

from zxemu_core.storage import pulse, snapshot, tape, tzx, z80

__all__ = ["pulse", "snapshot", "tape", "tzx", "z80"]
