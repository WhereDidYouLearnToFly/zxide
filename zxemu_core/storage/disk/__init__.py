"""Disks: the Beta 128 interface, TR-DOS, and the images it reads.

Tape was how the West loaded software. Behind the Iron Curtain, and on the clones that
were built there, the machine you actually met was a **Pentagon with a Beta 128 disk
interface** running **TR-DOS** -- and that is where most of the demoscene, the disk
magazines and an enormous amount of software lives. None of it is on tape, so none of it
loads through ``storage/tape.py`` no matter how good that gets.

There is a second reason this package exists, and it matters more for where zxide is
going. A tape is a *consumption* format: you load somebody else's program from it. A disk
is a **development** format -- TR-DOS can ``SAVE``, so a build can be written onto an
image and run. That is the natural target for a game-authoring layer: your project
produces a disk, not just a snapshot.

The four modules, from the metal outwards::

    beta.py     The interface itself. Decodes its five ports, selects a drive, and pages
                TR-DOS in and out. The only module here that knows a machine exists.
    wd1793.py   The floppy controller chip, as a register-level state machine.
    trd.py      A .trd image: geometry, sectors, and the TR-DOS catalogue written into
                track 0.
    scl.py      .scl -- a packed file list, converted to a .trd image on load.

**The one trick worth knowing.** A real WD1793 works in MFM bit cells, and emulating it
at that level would be both slow and enormous. We don't: a .trd is a plain sector dump
with fixed geometry, so the controller is implemented at *sector* granularity -- a
command decoder plus a byte-serving buffer. That is what makes the whole thing a few
hundred readable lines instead of a few thousand.

It is also the limitation. Copy protection works by writing disks that a normal
controller *cannot* describe -- deliberate CRC errors, duplicate sector numbers,
non-standard track lengths -- and sector-granularity emulation has nowhere to put any of
that. Protected disks will not all work, and TRDOS.md says so plainly rather than
pretending otherwise.
"""

from __future__ import annotations

from zxemu_core.storage.disk import beta, scl, trd, wd1793

__all__ = ["beta", "scl", "trd", "wd1793"]
