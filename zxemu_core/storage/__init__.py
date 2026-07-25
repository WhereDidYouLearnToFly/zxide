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
                 kept too. It reduces to ``tape.py``'s blocks for loading purposes.

The tape side is the interesting one. Rather than replaying the pulse train a real
cassette produces, it *traps* the ROM: when the CPU reaches ``LD-BYTES`` the whole
block is delivered at once and the routine is made to return as if it had spent
several seconds reading. That is why tapes load instantly here.

The honest trade is that a program using its own loader -- a turbo loader that
bypasses ``LD-BYTES`` -- gets no help from the trap, because the trap only knows
about the ROM's routine. Authentic edge-level replay (pulses on port 0xFE bit 6, with
the loading stripes and the sound) is the deferred alternative, and ``tape.py``'s
block model is deliberately the shared foundation both loaders would sit on.
"""

from __future__ import annotations

from zxemu_core.storage import snapshot, tape, tzx, z80

__all__ = ["snapshot", "tape", "tzx", "z80"]
