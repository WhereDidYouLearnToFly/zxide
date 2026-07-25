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

from pathlib import Path

from zxemu_core.storage import snapshot, tape, tzx, z80

SNAPSHOT_SUFFIXES = {".sna", ".z80"}
TAPE_SUFFIXES = {".tap", ".tzx"}

SNAPSHOT = "snapshot"
TAPE = "tape"


def kind_of(path: str | Path) -> str | None:
    """:data:`SNAPSHOT`, :data:`TAPE`, or None for a file we have no loader for."""
    suffix = Path(path).suffix.lower()
    if suffix in SNAPSHOT_SUFFIXES:
        return SNAPSHOT
    if suffix in TAPE_SUFFIXES:
        return TAPE
    return None


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
    """Parse a tape into ``(blocks, notes)``; notes are the .tzx parser's remarks.

    A ``.tap`` is only blocks, so its notes are always empty. A ``.tzx`` is a container
    whose other blocks (timings, groups, menus, credits) can't be loaded but shouldn't
    vanish silently either -- "3 blocks" is a confusing answer for a file that plainly
    holds a dozen.
    """
    path = Path(path)
    data = path.read_bytes()
    if path.suffix.lower() == ".tzx":
        return tzx.parse_tzx(data)
    return tape.parse_tap(data), []


def make_deck(blocks) -> tape.TapeDeck:
    return tape.TapeDeck(blocks)


def tape_summary(name: str, blocks, notes: list[str], model: str) -> list[str]:
    """The log lines describing a freshly inserted tape, including how to start it.

    The instruction differs by model because the 128K boots to its own menu: there is no
    ``LOAD ""`` prompt until you have chosen a BASIC from it.
    """
    lines = [f"Inserted {name} — {len(blocks)} loadable block(s):"]
    lines += [f"    {block.describe()}" for block in blocks]
    lines += [f"    · {note}" for note in notes]
    if model == "128k":
        lines.append('Choose "128 BASIC" (or "48 BASIC"), then type LOAD "" ⏎ to load.')
    else:
        lines.append('Type LOAD "" ⏎ (the J key gives LOAD) to load.')
    return lines
