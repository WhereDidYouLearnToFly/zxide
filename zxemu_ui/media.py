"""Loading somebody else's program: which format a file is, and what to say about it.

The window's job when you pick a file is orchestration -- reset the machine, repaint the
panels, move focus, write to the log. *Which* loader to call, and what the log should say,
is neither Qt's business nor the window's, so it lives here: no Qt import, so it can be
tested by asking questions rather than by driving a window.

The formats fall into three kinds, and the differences are not cosmetic:

    snapshots (.sna, .z80)   A photograph of a machine mid-run. Loading one *is* the
                             program running; there is nothing to start.
    tapes (.tap, .tzx)       A cassette. Loading one only puts it in the deck -- the
                             emulated machine still has to be told to LOAD it, which is
                             why this module also produces the "now type LOAD" hint.
    disks (.trd, .scl)       A TR-DOS floppy. Like a tape it only gets mounted, but
                             unlike either of the others it needs a machine that *has* a
                             disk interface -- so loading one implies a Pentagon.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from zxemu_core.storage import snapshot, tape, tzx, z80
from zxemu_core.storage.disk import scl, trd

SNAPSHOT = "snapshot"
TAPE = "tape"
DISK = "disk"


@dataclass(frozen=True)
class Format:
    """One loadable file format: how to name it, and which kind of thing it is."""

    suffix: str
    label: str        # what the menu item and dialog title call it
    description: str  # the file dialog's filter text, and the menu tooltip
    kind: str         # SNAPSHOT or TAPE

    @property
    def menu_label(self) -> str:
        return "Load {}…".format(self.label)

    @property
    def file_filter(self) -> str:
        return "{} (*{})".format(self.description, self.suffix)


# The formats the Load menu offers, in menu order: tapes first (you load a game from
# one), then snapshots. Each gets its own menu item rather than sharing a "Load Tape"
# item behind a multi-extension filter -- the menu then says exactly what it will open,
# and the file dialog shows one format's files instead of a mixed list. Adding a format
# (.szx, say) means one entry here and nothing else.
FORMATS = (
    Format(".tap", "TAP", "TAP tape image", TAPE),
    Format(".tzx", "TZX", "TZX tape image", TAPE),
    Format(".trd", "TRD", "TR-DOS disk image", DISK),
    Format(".scl", "SCL", "SCL disk image", DISK),
    Format(".sna", "SNA", "SNA snapshot", SNAPSHOT),
    Format(".z80", "Z80", "Z80 snapshot", SNAPSHOT),
)

FORMATS_BY_SUFFIX = {fmt.suffix: fmt for fmt in FORMATS}
SNAPSHOT_SUFFIXES = frozenset(f.suffix for f in FORMATS if f.kind == SNAPSHOT)
TAPE_SUFFIXES = frozenset(f.suffix for f in FORMATS if f.kind == TAPE)
DISK_SUFFIXES = frozenset(f.suffix for f in FORMATS if f.kind == DISK)


def format_of(path: str | Path) -> Format | None:
    """The :class:`Format` for a path's suffix, or None if we have no loader for it."""
    return FORMATS_BY_SUFFIX.get(Path(path).suffix.lower())


def kind_of(path: str | Path) -> str | None:
    """:data:`SNAPSHOT`, :data:`TAPE`, or None for a file we have no loader for."""
    fmt = format_of(path)
    return fmt.kind if fmt is not None else None


def load_snapshot(machine, path: str | Path) -> None:
    """Restore a snapshot into ``machine``, picking the loader by suffix.

    Raises ValueError / NotImplementedError / OSError, all of which the caller reports
    as one "could not load" line -- a snapshot for the wrong machine model is a normal
    thing to click on by mistake, not an internal error.
    """
    path = Path(path)
    data = path.read_bytes()
    if path.suffix.lower() == ".z80":
        z80.load_z80(machine, data)
    else:
        snapshot.load_sna(machine, data)


def read_tape(path: str | Path) -> tuple[list, list[str]]:
    """Parse a tape into ``(items, notes)``; notes are the .tzx parser's remarks.

    The items are everything on the tape that makes a sound, in order -- blocks, and
    for a ``.tzx`` also the bare tones and silences between them. A ``.tap`` is only
    blocks, so its notes are always empty. A ``.tzx`` is a container whose remaining
    entries (groups, menus, credits) carry no signal but shouldn't vanish silently
    either -- "3 blocks" is a confusing answer for a file that plainly holds a dozen.
    """
    path = Path(path)
    data = path.read_bytes()
    if path.suffix.lower() == ".tzx":
        return tzx.parse_tzx(data)
    return tape.parse_tap(data), []


def make_deck(items) -> tape.TapeDeck:
    return tape.TapeDeck(items)


def read_disk(path: str | Path):
    """Mount a ``.trd`` or ``.scl`` as a disk image, picking the reader by suffix.

    An ``.scl`` is *converted* rather than read (see ``storage/disk/scl.py``): it holds a
    list of files with no disk around them, so one has to be built. Both end up as the
    same TrdImage, so nothing downstream needs to care which arrived.
    """
    path = Path(path)
    data = path.read_bytes()
    if path.suffix.lower() == ".scl":
        return scl.parse_scl(data, path.name)
    return trd.parse_trd(data, path.name)


def disk_summary(name: str, image, drive_letter: str = "A") -> list[str]:
    """Log lines describing a freshly mounted disk, and how to get at it.

    Lists the catalogue because that is the question you actually have -- "what is on
    this disk?" -- and because it is TR-DOS's own first move too.
    """
    info = image.info()
    label = info.label or "(unlabelled)"
    lines = ["Mounted {} in drive {}: {} — "
             "{} file(s), {} free sector(s)".format(name, drive_letter, label, info.file_count, info.free_sectors)]
    for entry in image.catalogue()[:24]:
        lines.append("    {:<14} <{}> "
                     "{:>6} bytes, {} sector(s)".format(entry.display_name, entry.extension, entry.length, entry.sectors))
    remaining = len(image.catalogue()) - 24
    if remaining > 0:
        lines.append("    …and {} more".format(remaining))
    if not info.valid:
        # Not fatal: an unformatted disk is a legitimate thing to mount, and TR-DOS's
        # own FORMAT has to start from one.
        lines.append("    · no TR-DOS identifier on this disk — it may be unformatted.")
    lines.append('Choose "TR-DOS" from the menu (or RANDOMIZE USR 15616), then CAT to list it.')
    return lines


def tape_summary(name: str, items, notes: list[str], model: str) -> list[str]:
    """The log lines describing a freshly inserted tape, including how to start it.

    Counts and lists only the *loadable* items: a pilot tone is part of the signal, not
    something you would ever call a block on the tape.

    The instruction differs by model because the 128K and Pentagon boot to their own
    menu: there is no ``LOAD ""`` prompt until you have chosen a BASIC from it.
    """
    blocks = tape.data_blocks(items)
    lines = ["Inserted {} — {} loadable block(s):".format(name, len(blocks))]
    lines += ["    {}".format(block.describe()) for block in blocks]
    lines += ["    · {}".format(note) for note in notes]
    if model in ("128k", "pentagon"):
        lines.append('Choose "128 BASIC" (or "48 BASIC"), then type LOAD "" ⏎ to load.')
    else:
        lines.append('Type LOAD "" ⏎ (the J key gives LOAD) to load.')
    return lines
