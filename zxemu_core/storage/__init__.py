"""Storage: getting somebody else's program *into* the machine.

Two formats, two completely different philosophies, which is why they are separate
files rather than one "loader":

    snapshot.py  ``.sna`` -- a photograph of the machine. Registers, and every byte
                 of RAM, captured mid-run. Loading one doesn't *run* anything; it
                 restores a machine that was already running and lets it continue.
    tape.py      ``.tap`` -- a recording of a cassette. Not machine state at all, but
                 a stream of blocks the ROM's own loading routine reads, exactly as
                 it would from real tape.

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

from zxemu_core.storage import snapshot, tape

__all__ = ["snapshot", "tape"]
