"""Unit tests for .tzx parsing (container -> the blocks the fast loader can serve)."""

import pytest

from zxemu_core.storage import tape, tzx


def _block(flag: int, payload: bytes) -> bytes:
    body = bytes([flag]) + bytes(payload)
    checksum = 0
    for byte in body:
        checksum ^= byte
    return body + bytes([checksum])


def _file(*chunks: bytes, version: bytes = b"\x01\x14") -> bytes:
    return tzx.TZX_SIGNATURE + version + b"".join(chunks)


def _standard(data: bytes, pause: int = 1000) -> bytes:
    """ID 0x10: pause word, length word, data."""
    return (bytes([0x10, pause & 0xFF, pause >> 8, len(data) & 0xFF, len(data) >> 8]) + data)


def _turbo(data: bytes) -> bytes:
    """ID 0x11: 15 bytes of pulse timings, a 3-byte length, then data."""
    timings = bytes(15)
    length = len(data)
    return (bytes([0x11]) + timings
            + bytes([length & 0xFF, (length >> 8) & 0xFF, (length >> 16) & 0xFF]) + data)


def _pure_data(data: bytes) -> bytes:
    """ID 0x14: zero/one pulse lengths, used bits, pause, 3-byte length, then data."""
    length = len(data)
    return (bytes([0x14]) + bytes(7)
            + bytes([length & 0xFF, (length >> 8) & 0xFF, (length >> 16) & 0xFF]) + data)


def _text(message: str) -> bytes:
    raw = message.encode("ascii")
    return bytes([0x30, len(raw)]) + raw


def _archive_info(title: str) -> bytes:
    raw = title.encode("ascii")
    entries = bytes([0x00, len(raw)]) + raw     # text id 0x00 = full title
    body = bytes([1]) + entries                  # one entry
    return bytes([0x32, len(body) & 0xFF, len(body) >> 8]) + body


# --- the parts that load ------------------------------------------------------

def test_standard_blocks_come_out_as_tape_blocks():
    header = _block(0x00, bytes(17))
    data = _block(0xFF, bytes([1, 2, 3]))
    blocks, _notes = tzx.parse_tzx(_file(_standard(header), _standard(data)))

    assert len(blocks) == 2
    assert blocks[0].is_header
    assert blocks[1].data == data


def test_turbo_and_pure_data_blocks_load_as_data():
    turbo = _block(0xFF, bytes([9, 9, 9]))
    pure = _block(0xFF, bytes([7, 7]))
    blocks, notes = tzx.parse_tzx(_file(_turbo(turbo), _pure_data(pure)))

    assert [b.data for b in blocks] == [turbo, pure]
    assert any("Turbo" in note for note in notes)
    assert any("Pure data" in note for note in notes)


def test_a_turbo_blocks_own_timings_are_read_out_of_its_header():
    """The whole reason a turbo tape is a separate block type. Every field here is a
    number the loader will time against; reading any of them from the wrong offset
    produces a tape that parses cleanly and then loads nothing at all."""
    payload = _block(0xFF, b"\x01")
    timings = (bytes([0x10, 0x27])      # pilot pulse    = 10000
               + bytes([0x20, 0x4E])    # sync first     = 20000
               + bytes([0x30, 0x75])    # sync second    = 30000
               + bytes([0x40, 0x9C])    # zero bit pulse = 40000
               + bytes([0x50, 0xC3])    # one bit pulse  = 50000
               + bytes([0x07, 0x00])    # pilot tone     = 7 pulses
               + bytes([5])             # used bits in the last byte
               + bytes([0xE8, 0x03]))   # pause          = 1000ms
    length = len(payload)
    raw = (bytes([0x11]) + timings
           + bytes([length & 0xFF, (length >> 8) & 0xFF, (length >> 16) & 0xFF]) + payload)

    items, _notes = tzx.parse_tzx(_file(raw))
    timing = items[0].timing

    assert timing.pilot_pulse == 10000
    assert (timing.sync_first, timing.sync_second) == (20000, 30000)
    assert (timing.zero_pulse, timing.one_pulse) == (40000, 50000)
    assert timing.pilot_count == 7
    assert timing.used_bits_last_byte == 5
    assert timing.pause_ms == 1000
    # ...and those numbers are what actually comes out on the wire.
    assert list(items[0].pulses())[:9] == [10000] * 7 + [20000, 30000]


def test_a_pure_data_block_knows_it_has_no_pilot_of_its_own():
    """It is meant to follow a 0x12 tone; generating a leader for it would put pulses on
    the wire the original tape never had."""
    payload = _block(0xFF, b"\x01")
    items, _notes = tzx.parse_tzx(_file(_pure_data(payload)))

    assert items[0].timing.has_pilot is False


def test_version_is_reported():
    blocks, notes = tzx.parse_tzx(_file(_standard(_block(0xFF, b"\x01")), version=b"\x01\x14"))
    assert blocks and notes[0] == "TZX version 1.20"


# --- walking past the parts that don't ----------------------------------------

def test_metadata_and_structure_blocks_are_stepped_over():
    """Every one of these has a different length rule; getting any wrong desynchronises
    the walk and turns the rest of the file into garbage."""
    payload = _block(0xFF, bytes([0x42]))
    data = _file(
        _text("Loading screen"),
        bytes([0x21, 0x04]) + b"main",                    # group start
        bytes([0x22]),                                    # group end
        bytes([0x24, 0x02, 0x00]), bytes([0x25]),         # loop start / end
        bytes([0x33, 0x01, 0x00, 0x00, 0x01]),            # hardware type: 1 entry
        bytes([0x2A, 0x00, 0x00, 0x00, 0x00]),            # stop the tape in 48K
        bytes([0x5A]) + bytes(9),                         # glue
        _standard(payload),                               # ...and the block that matters
    )

    items, notes = tzx.parse_tzx(data)

    assert len(items) == 1 and items[0].data == payload
    assert any("Loading screen" in note for note in notes)
    assert any("$21" in note for note in notes)


def test_tones_pulses_and_pauses_are_kept_in_running_order():
    """These carry no data, so the fast loader has no use for them -- but they are the
    signal a real loader listens to, and a pilot tone stored as its own entry is the
    only thing telling the block after it where to start."""
    payload = _block(0xFF, bytes([0x42]))
    data = _file(
        bytes([0x12, 0x00, 0x08, 0xE8, 0x03]),            # pure tone: 1000 x 2048T
        bytes([0x13, 0x02, 0x01, 0x00, 0x02, 0x00]),      # pulse sequence: 2 pulses
        bytes([0x20, 0xE8, 0x03]),                        # pause: 1000ms
        _standard(payload),
    )

    items, _notes = tzx.parse_tzx(data)

    assert [type(item).__name__ for item in items] == [
        "PureTone", "PulseSequence", "Silence", "TapeBlock"
    ]
    assert list(items[0].pulses()) == [0x0800] * 1000
    assert list(items[1].pulses()) == [1, 2]
    assert items[2].pause_ms == 1000
    # ...and only the last of the four is something a fast load could serve.
    assert [b.data for b in tape.data_blocks(items)] == [payload]


def test_archive_info_surfaces_the_title():
    blocks, notes = tzx.parse_tzx(_file(_archive_info("Aliens Neoplasma II"),
                                        _standard(_block(0xFF, b"\x01"))))
    assert blocks
    assert any("Aliens Neoplasma II" in note for note in notes)


def test_direct_recording_is_skipped_with_an_explanation():
    samples = bytes(20)
    direct = (bytes([0x15]) + bytes(5)
              + bytes([len(samples), 0, 0]) + samples)
    blocks, notes = tzx.parse_tzx(_file(direct, _standard(_block(0xFF, b"\x02"))))

    assert len(blocks) == 1  # the sampled audio isn't loadable, the data block is
    assert any("Direct recording" in note for note in notes)


def test_an_unknown_block_stops_the_walk_rather_than_guessing():
    good = _block(0xFF, b"\x01")
    data = _file(_standard(good), bytes([0x99, 0x11, 0x22]), _standard(_block(0xFF, b"\x02")))

    blocks, notes = tzx.parse_tzx(data)

    assert len(blocks) == 1  # everything after the unknown ID is unreachable
    assert any("$99" in note for note in notes)


def test_truncated_block_keeps_what_was_readable():
    good = _block(0xFF, b"\x01")
    data = _file(_standard(good)) + bytes([0x10, 0x00, 0x00, 0xFF, 0xFF]) + b"short"
    blocks, notes = tzx.parse_tzx(data)

    assert len(blocks) == 1
    assert any("file ends first" in note for note in notes)


# --- rejections ---------------------------------------------------------------

def test_a_non_tzx_is_rejected():
    with pytest.raises(ValueError, match="ZXTape"):
        tzx.parse_tzx(b"this is not a tape")


def test_a_tape_with_no_loadable_blocks_reports_what_it_did_hold():
    """A pulse-level recording (or a ZX81 tape, which is all generalized blocks) parses
    fine and yields nothing loadable -- the error has to say which, or it reads as a
    parser failure."""
    generalized = bytes([0x19, 0x08, 0x00, 0x00, 0x00]) + bytes(8)
    with pytest.raises(ValueError, match="generalized data x2"):
        tzx.parse_tzx(_file(_text("just a note"), generalized, generalized))
