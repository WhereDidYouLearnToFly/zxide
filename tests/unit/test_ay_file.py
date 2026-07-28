"""Reading the ``.ay`` (ZXAYEMUL) container.

Two properties of this format break a reader quietly rather than loudly, and both have a
test here because "quietly wrong" is the expensive kind:

* **pointers are signed and relative to their own position**, not to the start of the file
* **the terminator of the block list is a zero *address* alone** -- requiring the length to
  be zero too walks off the end into a long tail of plausible-looking nonsense blocks

The fixture is built byte by byte rather than checked in: a real .ay is somebody's music,
and the structure is what is under test.
"""

import struct

import pytest

from zxemu_core.sound.ay_file import NotAnAyFile, program_for_song, read_ay


def _build(songs, author=b"A Composer", misc=b"(c) 1991"):
    """A minimal but genuine ZXAYEMUL file, with every pointer self-relative as required.

    Laid out in one pass with the variable-length parts appended as they are needed, which
    is how the real files are written and why every pointer has to be computed against its
    own position rather than a fixed base.
    """
    out = bytearray(20)
    out[0:8] = b"ZXAYEMUL"
    out[8], out[9] = 1, 0
    out[16] = len(songs) - 1  # "number of songs minus one"
    out[17] = 0

    def add(payload):
        offset = len(out)
        out.extend(payload)
        return offset

    def point(field, target):
        struct.pack_into(">h", out, field, target - field)

    point(10, 0)  # no special player
    point(12, add(author + b"\x00"))
    point(14, add(misc + b"\x00"))

    table = len(out)
    point(18, table)
    out.extend(bytes(4 * len(songs)))

    for index, song in enumerate(songs):
        entry = table + index * 4
        point(entry, add(song["name"] + b"\x00"))

        body = len(out)
        point(entry + 2, body)
        out.extend(bytes(14))
        struct.pack_into(">HH", out, body + 4, song.get("length", 0), song.get("fade", 0))
        out[body + 8], out[body + 9] = song.get("hi", 0), song.get("lo", 0)

        points = add(struct.pack(">HHH", song.get("stack", 0xBFFF), song["init"], song["interrupt"]))
        point(body + 10, points)

        addresses = len(out)
        point(body + 12, addresses)
        out.extend(bytes(6 * len(song["blocks"]) + 2))
        cursor = addresses
        for address, payload in song["blocks"]:
            struct.pack_into(">HH", out, cursor, address, len(payload))
            struct.pack_into(">h", out, cursor + 4, add(payload) - (cursor + 4))
            cursor += 6
        struct.pack_into(">H", out, cursor, 0)  # terminator: a zero address
    return bytes(out)


def _one(**overrides):
    song = {"name": b"Tune", "init": 0xC000, "interrupt": 0xC005, "blocks": [(0xC000, b"\xC9" * 16)]}
    song.update(overrides)
    return song


def test_metadata_and_song_names_are_read():
    catalogue = read_ay(_build([_one()]))
    assert catalogue["author"] == "A Composer"
    assert catalogue["misc"] == "(c) 1991"
    assert [song.name for song in catalogue["songs"]] == ["Tune"]


def test_every_song_in_a_multi_song_file_is_found():
    """Stored as "count minus one", which is exactly the kind of field that loses the last
    song to an off-by-one."""
    data = _build([_one(name=b"One"), _one(name=b"Two"), _one(name=b"Three")])
    assert [song.name for song in read_ay(data)["songs"]] == ["One", "Two", "Three"]


def test_the_points_record_gives_stack_init_and_interrupt():
    song = read_ay(_build([_one(init=0xBFFB, interrupt=0xBFF4, stack=0x1234)]))["songs"][0]
    assert (song.stack, song.init, song.interrupt) == (0x1234, 0xBFFB, 0xBFF4)


def test_blocks_are_read_with_their_contents():
    song = read_ay(_build([_one(blocks=[(0x8000, b"abc"), (0x9000, b"defg")])]))["songs"][0]
    assert song.blocks == [(0x8000, b"abc"), (0x9000, b"defg")]


def test_the_block_list_ends_at_a_zero_address_alone():
    """A zero *length* is legal and must not end the list. Getting this wrong produces a
    tail of nonsense blocks that all look almost real -- it is how this reader failed the
    first time it met a genuine file."""
    song = read_ay(_build([_one(blocks=[(0x8000, b""), (0x9000, b"xy")])]))["songs"][0]
    assert song.blocks == [(0x8000, b""), (0x9000, b"xy")]


def test_the_register_preload_is_assembled_from_hireg_and_loreg():
    """In a multi-song file this is usually the *only* difference between the tunes, so it
    is not a formality -- ignore it and every song plays as the same one."""
    song = read_ay(_build([_one(hi=0x02, lo=0x00)]))["songs"][0]
    assert song.register_preload == 0x0200
    assert program_for_song(song).register_preload == 0x0200


def test_a_song_that_drives_itself_from_the_interrupt_is_refused_for_now():
    """An interrupt address of zero means the tune installs its own IM 2 handler, which
    needs a machine left running rather than a routine called per frame. Refused rather
    than played wrongly."""
    song = read_ay(_build([_one(interrupt=0)]))["songs"][0]
    with pytest.raises(NotAnAyFile):
        program_for_song(song)


def test_a_file_that_is_not_a_container_is_refused():
    with pytest.raises(NotAnAyFile):
        read_ay(b"ProTracker 3.5 compilation of something else")


def test_the_program_carries_the_songs_own_stack_and_entry_points():
    song = read_ay(_build([_one(init=0xBFFB, interrupt=0xBFF4, stack=0x0000)]))["songs"][0]
    program = program_for_song(song)
    assert (program.init, program.play, program.stack) == (0xBFFB, 0xBFF4, 0x0000)
    assert program.mute is None  # the format defines none
