"""Loading somebody else's program: which format a file is, and what to say about it.

The window's job when you pick a file is orchestration -- reset the machine, repaint the
panels, move focus, write to the log. *Which* loader to call, and what the log should say,
is neither Qt's business nor the window's, so it lives here: no Qt import, so it can be
tested by asking questions rather than by driving a window.

The four formats fall into two kinds, and the difference is not cosmetic:

    snapshots (.sna, .z80)   A photograph of a machine mid-run. Loading one *is* the
                             program running; there is nothing to start.
    tapes (.tap, .tzx)       A cassette. Loading one only puts it in the deck -- the
                             emulated machine still has to be told to LOAD it, which is
                             why this module also produces the "now type LOAD" hint.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from zxemu_core.storage import snapshot, tape, tzx, z80

SNAPSHOT = "snapshot"
TAPE = "tape"


@dataclass(frozen=True)
class Format:
    """One loadable file format: how to name it, and which kind of thing it is."""

    suffix: str
    label: str        # what the menu item and dialog title call it
    description: str  # the file dialog's filter text, and the menu tooltip
    kind: str         # SNAPSHOT or TAPE

    @property
    def menu_label(self) -> str:
        return f"Load {self.label}…"

    @property
    def file_filter(self) -> str:
        return f"{self.description} (*{self.suffix})"


# The formats the Load menu offers, in menu order: tapes first (you load a game from
# one), then snapshots. Each gets its own menu item rather than sharing a "Load Tape"
# item behind a multi-extension filter -- the menu then says exactly what it will open,
# and the file dialog shows one format's files instead of a mixed list. Adding a format
# (.szx, say) means one entry here and nothing else.
FORMATS = (
    Format(".tap", "TAP", "TAP tape image", TAPE),
    Format(".tzx", "TZX", "TZX tape image", TAPE),
    Format(".sna", "SNA", "SNA snapshot", SNAPSHOT),
    Format(".z80", "Z80", "Z80 snapshot", SNAPSHOT),
)

FORMATS_BY_SUFFIX = {fmt.suffix: fmt for fmt in FORMATS}
SNAPSHOT_SUFFIXES = frozenset(f.suffix for f in FORMATS if f.kind == SNAPSHOT)
TAPE_SUFFIXES = frozenset(f.suffix for f in FORMATS if f.kind == TAPE)


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


def tape_summary(name: str, items, notes: list[str], model: str) -> list[str]:
    """The log lines describing a freshly inserted tape, including how to start it.

    Counts and lists only the *loadable* items: a pilot tone is part of the signal, not
    something you would ever call a block on the tape.

    The instruction differs by model because the 128K boots to its own menu: there is no
    ``LOAD ""`` prompt until you have chosen a BASIC from it.
    """
    blocks = tape.data_blocks(items)
    lines = [f"Inserted {name} — {len(blocks)} loadable block(s):"]
    lines += [f"    {block.describe()}" for block in blocks]
    lines += [f"    · {note}" for note in notes]
    if model == "128k":
        lines.append('Choose "128 BASIC" (or "48 BASIC"), then type LOAD "" ⏎ to load.')
    else:
        lines.append('Type LOAD "" ⏎ (the J key gives LOAD) to load.')
    return lines
