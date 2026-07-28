"""One question, asked of any music file: can this be played, and how?

Four kinds of AY music turn up in a ZX project and they need different handling, but a UI
should not have to know that. It has a path; it wants either something playable or a
sentence explaining why not. That is this module: dispatch, and nothing else.

    .c              a compiled module -- player and song in one blob, just run it
    .pt3 / .pt2     raw tracker data -- needs a player binary supplied from outside
    .ay             a container of blocks plus addresses to call (not yet supported)

The interesting asymmetry is the middle row. Compiled modules and .ay files are
self-sufficient; raw tracker data is not, and zxide does not ship a player because the good
ones are somebody else's work under their own terms (see ``tracker_player.py``). So playing
a ``.pt3`` depends on a player having been found, and *that is a normal thing to fail* --
hence :class:`CannotPlay` carrying a sentence a user can act on, rather than a stack trace.
"""

from __future__ import annotations

from pathlib import Path

from zxemu_core.sound import ay_file, ay_program, tracker_player

#: Suffixes worth offering a Play button for. Compiled modules conventionally use ``.c``,
#: which collides with C source -- content decides, never the extension (see ``describe``).
MUSIC_SUFFIXES = (".pt3", ".pt2", ".c", ".ay")

_RAW_TRACKER_SUFFIXES = {".pt3": "pt3", ".pt2": "pt2"}


class CannotPlay(Exception):
    """Why this file cannot be played, in a sentence meant for a human.

    Not a programming error: "no player binary found" and "this .c really is C source" are
    both ordinary answers, and both need saying rather than swallowing.
    """


def describe(path: str, data: bytes, players=()) -> dict:
    """What is known about a music file without playing it -- for the Inspector.

    Always answers, even for a file that cannot be played, because "this is C source, not
    music" is exactly what someone staring at a dead Play button needs told.

    ``players`` is passed for the same reason ``open_music`` takes it: whether a raw module
    is playable is not a property of the file. Describing it without them would have the
    Inspector say "needs a PT3 player" beside a Play button that works perfectly.
    """
    suffix = Path(path).suffix.lower()
    info = {"path": path, "size": len(data), "kind": "unknown", "title": "", "playable": False, "detail": ""}

    if suffix == ".ay":
        try:
            catalogue = ay_file.read_ay(data)
        except ay_file.NotAnAyFile as problem:
            info.update(kind="AY container", detail=str(problem))
            return info
        names = [song.name for song in catalogue["songs"]]
        info.update(
            kind="AY container",
            title=names[0] if names else "",
            playable=bool(names),
            detail="{} song(s){}".format(len(names), ", " + catalogue["misc"] if catalogue["misc"] else ""),
        )
        info["songs"] = names
        info["author"] = catalogue["author"]
        return info

    compiled = _try_compiled(data)
    if compiled is not None:
        info.update(kind="compiled module", title=compiled.title, playable=True, detail=compiled.notes)
        return info

    wanted = _RAW_TRACKER_SUFFIXES.get(suffix)
    if wanted is not None:
        found = _player_for(wanted, players)
        info.update(kind="{} module".format(wanted.upper()), title=_tracker_title(data))
        info["needs_player"] = wanted
        info["playable"] = found is not None
        if found is None:
            info["detail"] = "needs a {} player binary".format(wanted.upper())
        else:
            info["detail"] = "plays with {}".format(Path(found.path).name or "the detected player")
        return info

    if suffix == ".c":
        info.update(kind="C source", detail="not a compiled AY module")
    return info


def open_music(path: str, data: bytes, players=(), song: int = 0) -> ay_program.AyProgram:
    """Turn a file into something runnable, or raise :class:`CannotPlay` saying why not.

    ``players`` is whatever player binaries have been found (see
    ``tracker_player.identify_player``); it is only consulted for raw tracker data.
    ``song`` picks between the tunes in an .ay container and is ignored by every other
    format, none of which can hold more than one.
    """
    suffix = Path(path).suffix.lower()

    if suffix == ".ay":
        try:
            catalogue = ay_file.read_ay(data)
            songs = catalogue["songs"]
            if not songs:
                raise CannotPlay("that .ay container holds no songs")
            return ay_file.program_for_song(songs[min(song, len(songs) - 1)])
        except ay_file.NotAnAyFile as problem:
            raise CannotPlay(str(problem))

    compiled = _try_compiled(data)
    if compiled is not None:
        return compiled

    wanted = _RAW_TRACKER_SUFFIXES.get(suffix)
    if wanted is None:
        raise CannotPlay("{} holds no AY music this can play".format(Path(path).name))

    found = _player_for(wanted, players)
    if found is None:
        # Worth spelling out. This is not a missing dependency of zxide -- nothing needs
        # installing -- it is that a .pt3 file contains notes and no way to play them, so a
        # small Z80 program has to come from somewhere. Saying "no player binary found"
        # reads like a broken installation; saying what the file lacks does not.
        raise CannotPlay(
            "A .{0} file is only note data -- playing it needs a small {1} player program, "
            "which zxide does not ship. Use “Find player…” to pick one (a file like "
            "{0}_c000.bin), or drop it beside your project.".format(wanted, wanted.upper())
        )
    return tracker_player.program_for(found, data, title=_tracker_title(data) or Path(path).name)


def _player_for(wanted: str, players):
    """The first found player that plays this format, or None."""
    for player in players:
        if player is not None and player.plays == wanted:
            return player
    return None


def _try_compiled(data: bytes):
    """A compiled module, or None. Content decides: a ``.c`` may be either music or C."""
    try:
        return ay_program.read_compiled(data)
    except ay_program.NotACompiledModule:
        return None


def _tracker_title(data: bytes) -> str:
    """A module's own title, for files that carry one in plain ASCII near the start."""
    signature, offset = ay_program._find_signature(data)
    if signature is None:
        return ""
    return ay_program._text_after(data, offset)
