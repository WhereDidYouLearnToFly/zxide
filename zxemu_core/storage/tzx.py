"""Read ``.tzx`` tape images into the ordered signal a Spectrum would hear.

Where a ``.tap`` is nothing but data blocks back to back, a ``.tzx`` is a *container*:
each block is tagged with an ID byte, and only some of those blocks carry tape data at
all. The rest describe timings, structure (groups, loops, jumps, menus) or plain
metadata -- the game's title, the author, which hardware it wants.

What this module extracts is everything that makes a *sound*, in order:

    0x10  standard speed data   -- exactly a .tap block
    0x11  turbo speed data      -- same bytes, its own pulse timings
    0x14  pure data             -- data with no pilot tone in front of it
    0x12  pure tone             -- a leader stored on its own
    0x13  pulse sequence        -- a hand-written list of pulse lengths
    0x20  pause / stop the tape

**The timings are the point of the format, and they are kept.** An earlier version of
this module threw them away, which was defensible while the only loader was the fast
one: it hands the ROM a finished block, so how the bits *would* have been timed makes
no difference to it. But that also fixed the ceiling. A turbo loader bit-bangs its own
sampling loop and never calls the ROM routine, so no trap can serve it -- it needs the
real pulse train, at the real speed, which means the numbers in these headers.

The non-data entries matter for the same reason. A tape that stores a pilot as a 0x12
tone and its payload as a 0x14 "pure data" block is *one load split across two entries*:
drop the tone and the loader has nothing to lock onto. So the parser keeps the running
order of everything audible and lets :class:`~zxemu_core.storage.tape.TapeDeck` sort out
which entries a fast load can shortcut.

Everything else is walked (a container has to be walked in order -- block lengths are
the only way to find the next one) and reported as a note rather than silently dropped,
because "your tape had 3 blocks" is confusing when the file plainly holds a dozen. An
unknown ID stops parsing: without knowing its length there is no way to find where the
next block begins, and guessing would turn junk into fake blocks.
"""

from __future__ import annotations

from .pulse import ROM_TIMING, BlockTiming, PulseSequence, PureTone, Silence
from .tape import TapeBlock, data_blocks

TZX_SIGNATURE = b"ZXTape!\x1a"
HEADER_SIZE = 10  # signature + major/minor version bytes

# Fixed-size blocks: ID -> how many bytes follow the ID byte.
_FIXED_SIZE = {
    0x12: 4,   # pure tone
    0x20: 2,   # pause / stop the tape
    0x22: 0,   # group end
    0x23: 2,   # jump to block
    0x24: 2,   # loop start
    0x25: 0,   # loop end
    0x27: 0,   # return from sequence
    0x5A: 9,   # glue block (concatenation marker)
}

# Blocks whose body length is a counted field: ID -> (offset of the count, its width in
# bytes, bytes per counted item, fixed bytes that precede the counted part).
_COUNTED = {
    0x13: (0, 1, 2, 1),    # pulse sequence: N then N words
    0x26: (0, 2, 2, 2),    # call sequence: N then N words
    0x33: (0, 1, 3, 1),    # hardware type: N then N 3-byte entries
}

# Blocks with a plain length prefix: ID -> (width of the length field, bytes before it).
_LENGTH_PREFIXED = {
    0x21: (1, 0),   # group start: name
    0x28: (2, 0),   # select block
    0x2A: (4, 0),   # stop the tape in 48K mode
    0x2B: (4, 0),   # set signal level
    0x30: (1, 0),   # text description
    0x31: (1, 1),   # message: a display-time byte, then the text
    0x32: (2, 0),   # archive info
    0x35: (4, 16),  # custom info block: a 16-byte identifier, then the data
    0x18: (4, 0),   # CSW recording
    0x19: (4, 0),   # generalized data block
}

_BLOCK_NAMES = {
    0x12: "pure tone", 0x13: "pulse sequence", 0x15: "direct recording",
    0x18: "CSW recording", 0x19: "generalized data", 0x20: "pause/stop",
    0x21: "group start", 0x22: "group end", 0x23: "jump", 0x24: "loop start",
    0x25: "loop end", 0x26: "call sequence", 0x27: "return", 0x28: "select",
    0x2A: "stop the tape (48K)", 0x2B: "set signal level", 0x30: "text",
    0x31: "message", 0x32: "archive info", 0x33: "hardware type",
    0x35: "custom info", 0x5A: "glue",
}

# The data-bearing blocks: ID -> (size of the block's parameter area, offset of the
# 3-byte data length within it).
_DATA_BLOCKS = {
    0x10: (4, 2),      # pause word, then a 2-byte length (read as 3 with a zero top byte)
    0x11: (18, 15),    # 15 bytes of pulse timings, then a 3-byte length
    0x14: (10, 7),     # zero/one pulse lengths, used bits, pause, then a 3-byte length
}


def _int(data: bytes, offset: int, width: int) -> int:
    return int.from_bytes(data[offset:offset + width], "little")


def _timing_for(block_id: int, data: bytes, body: int) -> BlockTiming:
    """Read a data block's pulse timings out of its own header.

    Each of the three data IDs lays its parameters out differently, and the layout is
    the only documentation the file carries -- an off-by-two here produces a tape that
    parses perfectly and then loads nothing, because every pulse is the wrong length.

    A standard (0x10) block states only its trailing pause; the rest of its shape is
    the ROM's, by definition of "standard speed".
    """
    if block_id == 0x10:
        return BlockTiming(pause_ms=_int(data, body, 2))
    if block_id == 0x11:
        return BlockTiming(
            pilot_pulse=_int(data, body, 2),
            sync_first=_int(data, body + 2, 2),
            sync_second=_int(data, body + 4, 2),
            zero_pulse=_int(data, body + 6, 2),
            one_pulse=_int(data, body + 8, 2),
            # Turbo blocks state the pilot length outright rather than inferring it
            # from the flag byte, since a custom loader need not use flag bytes at all.
            pilot_count=_int(data, body + 10, 2),
            used_bits_last_byte=data[body + 12],
            pause_ms=_int(data, body + 13, 2),
        )
    # 0x14 pure data: the payload with no leader and no sync at all -- the loader is
    # expected to be in sync already, usually from a 0x12 tone just before it.
    return BlockTiming(
        has_pilot=False,
        zero_pulse=_int(data, body, 2),
        one_pulse=_int(data, body + 2, 2),
        used_bits_last_byte=data[body + 4],
        pause_ms=_int(data, body + 5, 2),
    )


def parse_tzx(data: bytes) -> tuple[list, list[str]]:
    """Split a ``.tzx`` into (the audible items in order, notes about the rest).

    The items are tape blocks, tones, pulse sequences and silences -- everything that
    would make a sound, in the order it makes it. Use
    :func:`~zxemu_core.storage.tape.data_blocks` to narrow that to the entries a fast
    load can serve.

    Raises ValueError if the file isn't a TZX at all. A file that runs out mid-block --
    truncated, or holding a block type we can't measure -- yields the items found so
    far plus a note saying where it stopped, matching ``parse_tap``'s "a damaged tape
    still gives you what it does contain" behaviour.
    """
    if not data.startswith(TZX_SIGNATURE):
        raise ValueError("not a .tzx file (missing the ZXTape! signature)")
    notes = ["TZX version {}.{}".format(data[8], data[9])]
    items: list = []
    seen: dict[int, int] = {}

    offset = HEADER_SIZE
    while offset < len(data):
        block_id = data[offset]
        seen[block_id] = seen.get(block_id, 0) + 1
        body = offset + 1
        if block_id in _DATA_BLOCKS:
            params, length_at = _DATA_BLOCKS[block_id]
            width = 2 if block_id == 0x10 else 3
            if body + params > len(data):
                notes.append("stopped: truncated ${:02X} block header".format(block_id))
                break
            length = _int(data, body + length_at, width)
            start = body + params
            if start + length > len(data):
                notes.append("stopped: ${:02X} block claims {} bytes, file ends first".format(block_id, length))
                break
            timing = _timing_for(block_id, data, body)
            items.append(TapeBlock(data[start:start + length], timing))
            if block_id == 0x11:
                notes.append("Turbo block ({} bytes) -- {}/"
                             "{}T bits, replayed at its own speed".format(length, timing.zero_pulse, timing.one_pulse))
            elif block_id == 0x14:
                notes.append("Pure data block ({} bytes) -- no pilot tone of its own".format(length))
            offset = start + length
            continue

        size = _body_size(data, block_id, body)
        if size is None:
            notes.append("stopped at an unknown block ID ${:02X} -- "
                         "its length is unknown, so the rest of the file can't be walked".format(block_id))
            break
        item = _pulse_item(data, block_id, body)
        if item is not None:
            items.append(item)
            notes.append(item.describe())
        elif block_id in (0x30, 0x32):
            notes.append(_describe_text(data, block_id, body))
        elif block_id == 0x15:
            notes.append("Direct recording block skipped -- it is sampled audio, not data blocks")
        else:
            notes.append("Skipped ${:02X} ({})".format(block_id, _BLOCK_NAMES.get(block_id, 'unknown')))
        offset = body + size

    if not data_blocks(items):
        # Say what the file *did* contain. Tapes stored entirely as generalized (0x19)
        # or direct-recording (0x15) blocks are pulse-level recordings with no ROM-format
        # blocks to hand over -- as are ZX81 tapes, which use 0x19 throughout -- and
        # "no data blocks" alone leaves you guessing which of those you have.
        contents = ", ".join(
            "{} x{}".format(_BLOCK_NAMES.get(block_id, "${:02X}".format(block_id)), count)
            for block_id, count in sorted(seen.items())
        )
        raise ValueError("no loadable data blocks in this .tzx -- it holds only: {}".format(contents))
    return items, notes


def _pulse_item(data: bytes, block_id: int, body: int):
    """The audible-but-dataless entries, or None if this ID isn't one of them.

    These three carry no bytes to load, only signal, so the fast loader has nothing to
    do with them -- but a loader listening to the wire hears them, and some tapes rely
    on that. The commonest case is a 0x12 tone acting as the pilot for a 0x14 block.
    """
    if block_id == 0x12:
        return PureTone(_int(data, body, 2), _int(data, body + 2, 2))
    if block_id == 0x13:
        count = data[body]
        return PulseSequence(_int(data, body + 1 + i * 2, 2) for i in range(count))
    if block_id == 0x20:
        return Silence(_int(data, body, 2))
    return None


def _body_size(data: bytes, block_id: int, body: int) -> int | None:
    """How many bytes this block's body occupies, or None if we can't tell."""
    if block_id in _FIXED_SIZE:
        return _FIXED_SIZE[block_id]
    if block_id == 0x15:  # direct recording: 8 fixed bytes then a 3-byte data length
        return 8 + _int(data, body + 5, 3)
    if block_id in _COUNTED:
        count_at, count_width, item_size, fixed = _COUNTED[block_id]
        return fixed + _int(data, body + count_at, count_width) * item_size
    if block_id in _LENGTH_PREFIXED:
        width, before = _LENGTH_PREFIXED[block_id]
        return before + width + _int(data, body + before, width)
    return None


def _describe_text(data: bytes, block_id: int, body: int) -> str:
    """Surface the tape's own words -- the title and credits are genuinely useful.

    Archive info is a little list of (kind, length, text) entries; the first is the
    title by convention, which is the one worth putting in the log.
    """
    if block_id == 0x30:
        length = data[body]
        return "Tape text: " + _text(data[body + 1:body + 1 + length])
    count = data[body + 2] if body + 2 < len(data) else 0
    if count == 0:
        return "Archive info (empty)"
    text_length = data[body + 4]
    return "Tape title: " + _text(data[body + 5:body + 5 + text_length])


def _text(raw: bytes) -> str:
    """TZX text is ASCII with the odd stray byte; keep it readable, never raise."""
    cleaned = "".join(chr(b) if 32 <= b < 127 else " " for b in raw)
    return " ".join(cleaned.split())[:120]
