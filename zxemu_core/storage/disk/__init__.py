"""Disks: the Beta 128 interface, TR-DOS, and the images it reads.

Tape was how the West loaded software. Behind the Iron Curtain, and on the clones built
there, the machine you actually met was a **Pentagon with a Beta 128 disk interface**
running **TR-DOS** -- and that is where most of the demoscene, the disk magazines and an
enormous amount of software lives. None of it is on tape, so none of it loads through
``storage/tape.py`` no matter how good that gets.

There is a second reason this package exists, and it matters more for where zxide is
going. A tape is a *consumption* format: you load somebody else's program from it. A disk
is a **development** format -- TR-DOS can ``SAVE``, so a build can be written onto an
image and run. That is the natural target for a game-authoring layer: your project
produces a disk, not just a snapshot.

===========================================================================
PART ONE -- WHAT TR-DOS IS
===========================================================================

If you have only ever met the Spectrum through tapes, nearly everything below is new, so
this section is the primer. The code in this package is the second half of the story and
assumes it.

The hardware
------------
The **Beta Disk Interface** (Technology Research Ltd, UK, 1984-86) is a cartridge holding
three things: a **WD1793** floppy controller, connectors for up to four drives, and a 16K
ROM containing **TR-DOS** -- "TR" for Technology Research. On a Sinclair machine it is an
add-on you plug in. On a Pentagon it is soldered onto the motherboard and live from
power-on, which is why the clone and the disk system are effectively one subject.

Getting into it
---------------
TR-DOS is not resident. Its ROM only appears when the interface swaps itself into
0x0000-0x3FFF, and the trigger is famous::

    RANDOMIZE USR 15616

15616 is 0x3D00. The interface watches the address bus during instruction *fetch*, and
the moment the CPU fetches from anywhere in that 256-byte page it pages its ROM in --
over the top of the 48K ROM's tape routines, which is exactly the point. Fetching from
0x4000 or above pages it back out again, so returning to a BASIC program in RAM removes
it without anything having to remember to. See ``beta.py``; this is the mechanism the
CPU's ``m1_hook`` exists for.

The Pentagon's menu ROM has a **TR-DOS** entry that does this for you (the 65 bytes that
distinguish it from a Sinclair 128 ROM are that menu item and the code behind it).

The prompt
----------
TR-DOS greets you with its banner and a prompt naming the current drive::

    A>

Drives are **A** to **D**. Commands are typed as ordinary Spectrum BASIC keywords, which
means the keyword-entry rules apply and catch everybody out at least once:

    ``CAT``      extended mode (CAPS SHIFT + SYMBOL SHIFT), then SYMBOL SHIFT + 9
    ``RUN``      the R key, in normal keyword mode
    ``LOAD``     the J key
    ``SAVE``     the S key

The commands worth knowing
--------------------------
    ``CAT``                  list the disk: title, file count, deleted count, and every
                             file with its type and length in sectors.
    ``RUN``                  load and run the file called **boot** -- the convention every
                             self-starting disk follows. A disk with no ``boot`` needs
                             ``RUN "name"`` instead, which is a real distinction: most
                             magazine disks hold a single ``.B`` file named after the
                             issue and are started that way.
    ``LOAD "name"``          load a file; the type decides what that means.
    ``LOAD "name" CODE``     load a CODE file, optionally to a given address.
    ``SAVE "name"``          save the BASIC program.
    ``SAVE "name" CODE a,l`` save a block of memory.
    ``ERASE "name"``         delete a file.
    ``MOVE``                 compact the disk, reclaiming deleted files' space.
    ``FORMAT "label"``       initialise a disk and give it a name.
    ``COPY``                 duplicate a disk or file.
    ``NEW``                  return to BASIC.

File types
----------
The one-character extension is a *type*, not a filename suffix, and it changes what
loading does:

    ``B``   BASIC program. Its catalogue entry records both the program length and the
            program-plus-variables length, which is why a ``.B`` file's byte length and
            its length in sectors often disagree wildly -- the sectors cover the whole
            file, including anything appended after the BASIC.
    ``C``   CODE: a raw memory block, with the address it loads to stored in the entry.
    ``D``   a saved data array.
    ``#``   a sequential (print/stream) file.

How the disk is laid out
------------------------
Geometry is fixed and small enough to hold in your head:

    256 bytes           per sector
    16 sectors          per track, numbered **1-16** on the wire
    80 (or 40) tracks   per side, and usually two sides
    640K                a full double-sided 80-track disk

**Track 0 side 0 is the filesystem**, and nothing else:

    sectors 1-8     the catalogue: 128 entries of 16 bytes
    sector 9        the disk-information block, in its last 32 bytes
    sectors 10-16   unused

Everything from track 1 onward is file data.

The idea that explains the rest
-------------------------------
**Files are contiguous, and allocated strictly in order.** There is no allocation table
and no fragmentation: a file is a start track, a start sector and a length, so its
position is completely determined by the lengths of the files before it. Three
consequences follow, and they all look strange until you know this:

  * the catalogue can afford to be tiny -- 16 bytes per file is enough;
  * ``ERASE`` does not free space. It marks the entry deleted (by overwriting the first
    character of the name) and leaves the data where it is, because moving everything
    after it is the only alternative. ``MOVE`` is the command that actually compacts,
    and undelete utilities were a thing people owned;
  * a file list with no disk around it -- which is what an ``.scl`` is -- can be turned
    back into a real disk simply by laying the files out in order. See ``scl.py``.

Two numbering traps
-------------------
Both of these have cost time in this project, so they are worth stating plainly:

  * **Sectors are 1-based on the wire and 0-based in the catalogue.** The controller's
    sector register counts 1-16; a catalogue entry's start sector counts 0-15. TR-DOS
    adds one when it issues the read.
  * **A catalogue "track" is a logical track, with the two sides folded together.**
    Logical track = ``cylinder * sides + head``, so on a double-sided disk logical track
    1 is *cylinder 0, side 1* -- not cylinder 1. This is also why a ``.trd`` image
    interleaves the sides rather than storing one whole side after the other. TR-DOS
    splits the logical track back into a cylinder to seek to and a side to select before
    it talks to the controller.

The information block
---------------------
Sector 9 of track 0 carries what TR-DOS believes about the disk as a whole: the first
free sector and track, the disk type (which states the geometry -- more reliable than the
file's size, since images are routinely truncated after the last used sector), the file
count, the free-sector count, an 8-character label, and at offset 0xE7 the byte **0x10**,
which is the closest thing the format has to a magic number. TR-DOS checks it before it
will believe a disk at all: without it you get *"No disk"* however intact the catalogue
is. Exact offsets are in ``trd.py``, which is the authority.

Loading, end to end
-------------------
Putting it together, ``RUN`` on a disk with a boot file does roughly this:

  1. seek to track 0 and read sector 9 -- is this a TR-DOS disk?
  2. read the catalogue from sectors 1-8, and find the entry named ``boot``;
  3. split its logical start track into a cylinder and a side, select the side, seek;
  4. read its sectors -- usually with a *multiple*-sector read, which keeps going into
     the following sectors rather than needing a command each;
  5. hand the bytes to BASIC and run them.

Every step there is visible in the port traffic if you watch ports 0x1F/0x3F/0x5F/0x7F,
which is how most of the bugs in this package were found.

===========================================================================
PART TWO -- HOW THIS PACKAGE IMPLEMENTS IT
===========================================================================

Four modules, from the metal outwards::

    beta.py     The interface itself. Decodes its five ports, selects a drive, and pages
                TR-DOS in and out. The only module here that knows a machine exists.
    wd1793.py   The floppy controller chip, as a register-level state machine.
    trd.py      A ``.trd`` image: geometry, sectors, and the TR-DOS catalogue described
                above. The authority on every offset.
    scl.py      ``.scl`` -- a packed file list, converted to a ``.trd`` image on load.

**The one trick worth knowing.** A real WD1793 works in MFM bit cells, and emulating it
at that level would be both slow and enormous. We don't: a ``.trd`` is a plain sector
dump with fixed geometry, so the controller is implemented at *sector* granularity -- a
command decoder plus a byte-serving buffer. That is what makes the whole thing a few
hundred readable lines instead of a few thousand.

It is also the limitation. Copy protection works by writing disks that a normal
controller *cannot* describe -- deliberate CRC errors, duplicate sector numbers,
non-standard track lengths -- and sector-granularity emulation has nowhere to put any of
that. Protected disks will not all work, and TRDOS.md says so plainly rather than
pretending otherwise.

**The rule this package learned the hard way**, written here because it outranks any
individual feature: *a command we cannot interpret faithfully must not be allowed to
modify the disk.* Write Track (format) is the case -- we cannot reproduce its raw MFM
stream, so it writes nothing at all, because loaders issue it while probing and the head
is usually parked on track 0. An unimplemented format is a missing feature; an erased
catalogue is lost work. See ``wd1793.py``.
"""

from __future__ import annotations

from zxemu_core.storage.disk import beta, scl, trd, wd1793

__all__ = ["beta", "scl", "trd", "wd1793"]
