"""Playing *raw* tracker data (``.pt2``, ``.pt3``) by pairing it with a player binary.

A compiled module carries its own player and an ``.ay`` file carries one too, so both just
run (see ``ay_program.py``). Raw tracker data carries nothing: it is a list of notes, and
something has to interpret it. That something is a small Z80 program, and zxide does not
ship one -- it finds one, the way it finds the assembler rather than bundling it. The
player is somebody else's work with its own terms; the calling convention is a fact about
the format, and facts are all this module contains.

**What a usable player binary looks like.** It is a compiled blob assembled for a known
address whose first bytes are a jump table::

    ORG+0   LD HL,<module address>  /  JR init      (5 bytes)
    ORG+5   JP play
    ORG+8   JP mute

and whose ``LD HL`` operand equals ``ORG + its own length`` -- meaning "the module goes
immediately after me". That last equality is the useful part: it is a checksum on the whole
assumption. If a file satisfies it, the file is a player laid out the way this expects and
we know where to put the song. If it does not, we have found something else and say so,
rather than loading a stranger's bytes and running them.

**The mode byte.** The common player is Bulba's universal PT2/PT3 one, which takes a setup
value in ``LD A,n`` at ORG+0x0B: 2 selects PT2, 32 selects PT3 (its wrapper's own choice,
``SETUP.TSPT3``), 0 is plain PT3. That byte is read to *report* which format a discovered
binary plays. It is deliberately never written: patching a third-party player to make it do
something its author did not build it to do is how you get music that almost works.
"""

from __future__ import annotations

from dataclasses import dataclass

from zxemu_core.sound.ay_program import AyProgram

#: The address these binaries are assembled for. Named "_c000" by convention, and checkable
#: rather than trusted -- see ``identify_player``.
PLAYER_ORG = 0xC000

_LD_HL_NN = 0x21
_JP_NN = 0xC3
_MODULE_POINTER = 1   # operand of the opening LD HL,nnnn
_PLAY_ENTRY = 5
_MUTE_ENTRY = 8
_SETUP_OPERAND = 0x0C  # operand of LD A,n at ORG+0x0B

#: Setup values, from the player's own source (``SETUP.PT2 EQU 2``, ``SETUP.TSPT3 EQU 32``).
_SETUP_FORMATS = {0x02: "pt2", 0x20: "pt3", 0x00: "pt3"}


@dataclass(frozen=True)
class PlayerBinary:
    """A player blob that passed identification, and what it can be used for."""

    data: bytes
    org: int
    module_address: int  # where this player expects the song: immediately after itself
    plays: str           # "pt2" or "pt3", read from the setup byte
    path: str = ""

    @property
    def init(self) -> int:
        return self.org

    @property
    def play(self) -> int:
        return self.org + _PLAY_ENTRY

    @property
    def mute(self) -> int:
        return self.org + _MUTE_ENTRY


def identify_player(data: bytes, org: int = PLAYER_ORG, path: str = "") -> PlayerBinary | None:
    """Whether ``data`` is a player laid out as described above -- ``None`` if it is not.

    Returns rather than raises: this is asked of arbitrary files while hunting for a player,
    where "no" is the ordinary answer and not an error.
    """
    if len(data) < 0x20:
        return None
    if data[0] != _LD_HL_NN or data[_PLAY_ENTRY] != _JP_NN or data[_MUTE_ENTRY] != _JP_NN:
        return None
    pointer = data[_MODULE_POINTER] | (data[_MODULE_POINTER + 1] << 8)
    if pointer != org + len(data):
        return None  # the self-check: it must expect its module immediately after itself
    plays = _SETUP_FORMATS.get(data[_SETUP_OPERAND])
    if plays is None:
        return None
    return PlayerBinary(data=data, org=org, module_address=pointer, plays=plays, path=path)


def program_for(player: PlayerBinary, module: bytes, title: str = "") -> AyProgram:
    """Combine a player and a song into something the emulate-underneath engine can run."""
    if player.module_address + len(module) > 0x10000:
        raise ValueError("module is too large to sit after the player ({} bytes)".format(len(module)))
    return AyProgram(
        blocks=[(player.org, player.data), (player.module_address, module)],
        init=player.init,
        play=player.play,
        mute=player.mute,
        title=title,
        notes="{} player at 0x{:04X}, module at 0x{:04X}".format(player.plays.upper(), player.org, player.module_address),
        extras={"player_path": player.path, "plays": player.plays},
    )
