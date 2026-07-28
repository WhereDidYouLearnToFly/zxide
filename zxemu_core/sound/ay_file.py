"""The ``.ay`` container (``ZXAYEMUL``): several tunes, as Z80 code plus where to call it.

This is the format the ZX music archive is distributed in, and it exists because playing
Spectrum music properly means running the author's own player rather than reinterpreting
their notes. A file holds metadata, one or more *songs*, and for each song a stack value,
an initialise address, an interrupt (per-frame) address, and the memory blocks to load.

Two things about it repay attention, because getting either wrong yields a file that plays
and is wrong rather than one that fails:

**Pointers are signed and relative to their own position.** Not to the start of the file --
to the address of the pointer field itself. Everything in the format is reached that way,
so an off-by-two in one place sends you somewhere plausible-looking and wrong.

**The register preload chooses the song.** Each song carries HiReg/LoReg, loaded into every
common register pair before ``init`` runs. In a multi-song file the songs routinely share a
single block of code and differ *only* in that value -- the Hero Quest file this was written
against has three tunes, one 8976-byte block, and HiReg 2, 1, 3. Treat it as a formality and
all three songs play as whichever one the code defaults to.

Layout per the published specification (big-endian throughout); see also
https://vgmrips.net/wiki/AY_File_Format
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from zxemu_core.sound.ay_program import AyProgram

_MAGIC = b"ZXAYEMUL"


class NotAnAyFile(ValueError):
    """The file is not a ZXAYEMUL container, or is too damaged to read."""


@dataclass
class AySong:
    """One tune inside a container: enough to describe it without loading anything."""

    name: str
    index: int
    init: int
    interrupt: int
    stack: int
    register_preload: int
    length_frames: int
    fade_frames: int
    blocks: list


def read_ay(data: bytes) -> dict:
    """Read the container: author, misc, and every song it holds.

    Returns a plain dict rather than a class because this is the *catalogue* -- what the
    Inspector lists and the player picks from -- and it is read once, whole.
    """
    if len(data) < 20 or not data.startswith(_MAGIC):
        raise NotAnAyFile("not a ZXAYEMUL container")

    songs = []
    table = _relative(data, 18)
    count = data[16] + 1  # stored as "number of songs minus one"
    for index in range(count):
        entry = table + index * 4
        if entry + 4 > len(data):
            break
        songs.append(_read_song(data, entry, index))

    return {
        "file_version": data[8],
        "player_version": data[9],
        "author": _string(data, _relative(data, 12)),
        "misc": _string(data, _relative(data, 14)),
        "first_song": data[17],
        "songs": songs,
    }


def program_for_song(song: AySong) -> AyProgram:
    """Turn one catalogued song into something the emulate-underneath engine can run."""
    if song.interrupt == 0:
        # The format allows an interrupt-address of zero, meaning "this tune installs its
        # own IM 2 handler and is driven by the interrupt itself". That needs the machine
        # left running with interrupts enabled rather than a routine called per frame, which
        # is a different driver -- so it is refused rather than silently played wrongly.
        raise NotAnAyFile("song '{}' is interrupt-driven, which is not supported yet".format(song.name))
    return AyProgram(
        blocks=list(song.blocks),
        init=song.init,
        play=song.interrupt,
        mute=None,  # the format defines none; stopping means throwing the machine away
        stack=song.stack,
        title=song.name,
        register_preload=song.register_preload,
        notes="AY container song {}, init 0x{:04X}, interrupt 0x{:04X}".format(song.index, song.init, song.interrupt),
        extras={"length_frames": song.length_frames, "fade_frames": song.fade_frames},
    )


def _read_song(data: bytes, entry: int, index: int) -> AySong:
    name = _string(data, _relative(data, entry))
    body = _relative(data, entry + 2)
    length, fade = struct.unpack_from(">HH", data, body + 4)
    high, low = data[body + 8], data[body + 9]
    points = _relative(data, body + 10)
    stack, init, interrupt = struct.unpack_from(">HHH", data, points)
    return AySong(
        name=name,
        index=index,
        init=init,
        interrupt=interrupt,
        stack=stack,
        register_preload=(high << 8) | low,
        length_frames=length,
        fade_frames=fade,
        blocks=_read_blocks(data, _relative(data, body + 12)),
    )


def _read_blocks(data: bytes, offset: int) -> list:
    """The memory blocks, until the terminating zero *address*.

    Only the address is the terminator -- a block may legitimately be zero-length, and
    requiring both fields to be zero walks off the end of the list into whatever follows,
    producing a long tail of nonsense blocks that all look almost plausible.
    """
    blocks = []
    while 0 <= offset <= len(data) - 6:
        address, length = struct.unpack_from(">HH", data, offset)
        if address == 0:
            break
        source = _relative(data, offset + 4)
        # Clamp rather than reject: the specification says a block running past the top of
        # memory is truncated, and files in the wild do overstate their length.
        length = min(length, 0x10000 - address, max(0, len(data) - source))
        blocks.append((address, data[source:source + length]))
        offset += 6
    return blocks


def _relative(data: bytes, offset: int) -> int:
    """Resolve one of the format's self-relative pointers (signed, from its own position)."""
    return offset + struct.unpack_from(">h", data, offset)[0]


def _string(data: bytes, offset: int) -> str:
    """A NUL-terminated string; latin-1 because these are 1990s demoscene credits."""
    if not 0 <= offset < len(data):
        return ""
    end = data.find(b"\x00", offset)
    return data[offset:end if end != -1 else len(data)].decode("latin-1").strip()
