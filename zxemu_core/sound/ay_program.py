"""AY music that arrives as *Z80 code* rather than as notes.

Most Spectrum music files are tracker data: a list of what to play, which needs a player
program supplied separately (see the PT3 work). Two important kinds are not. A **compiled
module** is a tracker's output with its player welded on -- one blob you ``CALL`` -- and an
**.ay file** is a container of memory blocks plus the addresses to call. Neither can be
read as music at all; both are programs that make noise.

That sounds like a problem and is actually a shortcut, because this project already owns a
Z80 and an AY-3-8912. Playing one of these is: put the bytes where they belong, call the
initialise routine once, call the play routine fifty times a second, and listen to the
chip. No format knowledge, no per-tracker interpreter, and it works for music built with
trackers nobody here has heard of.

This module does the *reading* -- turning a file into an :class:`AyProgram` saying what to
load and what to call. Running it is ``ay_module_player.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Where a compiled module's entry points sit relative to its load address. Bulba's Vortex
#: Tracker II player -- overwhelmingly the one in the wild -- documents this layout in its
#: own source: ``CALL START`` to initialise, ``CALL START+5`` per frame, ``START+8`` to
#: silence the chip. Other players copy it, having been written against the same convention.
INIT_OFFSET = 0
PLAY_OFFSET = 5
MUTE_OFFSET = 8

#: Every tracker whose modules this can identify writes its name into the data. Finding one
#: is how the load address is *derived* rather than assumed -- see ``read_compiled``.
_MODULE_SIGNATURES = (b"ProTracker 3.", b"Vortex Tracker II")

_LD_HL_NN = 0x21  # the opcode a compiled module opens with, pointing at its own data


class NotACompiledModule(ValueError):
    """Raised when a file cannot be shown to be a compiled module.

    Loudly, and on purpose. Everything here is inference about a headerless blob, and the
    failure mode of guessing wrong is not an error message -- it is the emulated Z80
    executing whatever the bytes happen to mean, which can sound like anything or nothing.
    Refusing to play is the honest outcome; a wrong guess is not.
    """


@dataclass
class AyProgram:
    """A loadable, callable piece of music: what to put in memory, and what to call.

    ``blocks`` are ``(address, data)`` pairs. ``init`` runs once; ``play`` runs once per
    frame; ``mute`` silences the chip and may be None where a format doesn't define one.
    """

    blocks: list[tuple[int, bytes]]
    init: int
    play: int
    mute: int | None = None
    stack: int = 0xBFFF
    title: str = ""
    author: str = ""
    notes: str = ""  # how this was identified, for the UI to show and a human to sanity-check
    #: A 16-bit value to preload into every common register pair before ``init`` runs, or
    #: None to leave them alone. This looks like a formality and is not: an .ay file holding
    #: several tunes typically ships *one* block of code for all of them and selects between
    #: them by the value it is initialised with. Skip it and every song plays as song one.
    register_preload: int | None = None
    extras: dict = field(default_factory=dict)


def read_compiled(data: bytes) -> AyProgram:
    """Read a compiled module (conventionally ``.c``) by working out where it loads.

    A compiled module has no header at all -- no magic number, no load address, nothing
    that says what it is. What it does have is a first instruction of ``LD HL,nnnn``
    pointing at its own embedded module data, and module data that begins with the
    tracker's name in ASCII. Those two facts pin the load address down between them::

        ORG = (the address in LD HL,nnnn) - (offset of the tracker signature in the file)

    and, crucially, they *check* each other: if the arithmetic lands outside RAM, or the
    file has no signature, or it does not start with ``LD HL``, this is not a compiled
    module and no amount of confidence would make it play. Hence an exception rather than
    a default of 0xC000 -- which is right often enough to be dangerous and wrong silently.
    """
    if len(data) < 16:
        raise NotACompiledModule("too short to be a compiled module ({} bytes)".format(len(data)))
    if data[0] != _LD_HL_NN:
        raise NotACompiledModule("does not begin with LD HL,nnnn -- no way to locate its data")

    pointer = data[1] | (data[2] << 8)
    signature, offset = _find_signature(data)
    if signature is None:
        raise NotACompiledModule("no tracker signature found -- cannot confirm the load address")

    org = pointer - offset
    if org < 0x4000 or org + len(data) > 0x10000:
        raise NotACompiledModule(
            "implied load address 0x{:04X} does not fit in RAM (file is {} bytes)".format(org, len(data))
        )

    return AyProgram(
        blocks=[(org, data)],
        init=org + INIT_OFFSET,
        play=org + PLAY_OFFSET,
        mute=org + MUTE_OFFSET,
        title=_text_after(data, offset),
        notes="compiled module, loads at 0x{:04X} ({} at 0x{:04X})".format(org, signature.decode("ascii").strip(), pointer),
        extras={"org": org, "data_pointer": pointer, "signature": signature.decode("ascii")},
    )


def looks_compiled(data: bytes) -> bool:
    """Whether ``read_compiled`` would accept this, without raising if it wouldn't."""
    try:
        read_compiled(data)
    except NotACompiledModule:
        return False
    return True


def _find_signature(data: bytes):
    """The first known tracker signature in the file, with its offset -- or ``(None, -1)``."""
    for signature in _MODULE_SIGNATURES:
        offset = data.find(signature)
        if offset != -1:
            return signature, offset
    return None, -1


def _text_after(data: bytes, offset: int, length: int = 62) -> str:
    """The printable run starting at ``offset``, which is where a module keeps its title.

    Deliberately forgiving: this is a nicety for the UI, and a module whose title is in a
    Russian codepage (many are) should degrade to something readable rather than stop the
    file from playing.
    """
    raw = data[offset:offset + length]
    text = "".join(chr(b) if 32 <= b < 127 else " " for b in raw)
    return " ".join(text.split())
