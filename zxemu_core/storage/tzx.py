"""Read ``.tzx`` tape images down to the blocks the fast loader can serve.

Where a ``.tap`` is nothing but data blocks back to back, a ``.tzx`` is a *container*:
each block is tagged with an ID byte, and only some of those blocks carry tape data at
all. The rest describe timings, structure (groups, loops, jumps, menus) or plain
metadata -- the game's title, the author, which hardware it wants.

What this module extracts is the subset the block-based fast loader can act on:

    0x10  standard speed data   -- exactly a .tap block
    0x11  turbo speed data      -- same bytes, custom pulse timings
    0x14  pure data             -- data with no pilot tone

The timings are deliberately discarded. Fast loading never generates pulses in the
first place (see ``tape.py``): it hands the ROM's loader a finished block, so how the
bits *would* have been timed on the wire makes no difference. That is why a turbo block
loads here at all -- but it is also the limit of the trick. A game whose loader does its
own bit-banging never calls the ROM routine, so no trap can help it, and it needs
authentic edge replay regardless of which container the tape came in.

Every other block is walked (a container has to be walked in order -- block lengths are
the only way to find the next one) and reported as a note rather than silently dropped,
because "your tape had 3 blocks" is confusing when the file plainly holds a dozen. An
unknown ID stops parsing: without knowing its length there is no way to find where the
next block begins, and guessing would turn junk into fake blocks.
"""

from __future__ import annotations

from .tape import TapeBlock

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


def parse_tzx(data: bytes) -> tuple[list[TapeBlock], list[str]]:
    """Split a ``.tzx`` into (loadable blocks, human-readable notes about the rest).

    Raises ValueError if the file isn't a TZX at all. A file that runs out mid-block --
    truncated, or holding a block type we can't measure -- yields the blocks found so
    far plus a note saying where it stopped, matching ``parse_tap``'s "a damaged tape
    still gives you what it does contain" behaviour.
    """
    if not data.startswith(TZX_SIGNATURE):
        raise ValueError("not a .tzx file (missing the ZXTape! signature)")
    notes = [f"TZX version {data[8]}.{data[9]}"]
    blocks: list[TapeBlock] = []
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
                notes.append(f"stopped: truncated ${block_id:02X} block header")
                break
            length = _int(data, body + length_at, width)
            start = body + params
            if start + length > len(data):
                notes.append(f"stopped: ${block_id:02X} block claims {length} bytes, file ends first")
                break
            blocks.append(TapeBlock(data[start:start + length]))
            if block_id == 0x11:
                notes.append(f"Turbo block ({length} bytes) -- loaded as data, custom timings ignored")
            elif block_id == 0x14:
                notes.append(f"Pure data block ({length} bytes) -- no pilot tone on the original tape")
            offset = start + length
            continue

        size = _body_size(data, block_id, body)
        if size is None:
            notes.append(f"stopped at an unknown block ID ${block_id:02X} -- "
                         "its length is unknown, so the rest of the file can't be walked")
            break
        if block_id in (0x30, 0x32):
            notes.append(_describe_text(data, block_id, body))
        elif block_id == 0x15:
            notes.append("Direct recording block skipped -- it is sampled audio, not data blocks")
        else:
            notes.append(f"Skipped ${block_id:02X} ({_BLOCK_NAMES.get(block_id, 'unknown')})")
        offset = body + size

    if not blocks:
        # Say what the file *did* contain. Tapes stored entirely as generalized (0x19)
        # or direct-recording (0x15) blocks are pulse-level recordings with no ROM-format
        # blocks to hand over -- as are ZX81 tapes, which use 0x19 throughout -- and
        # "no data blocks" alone leaves you guessing which of those you have.
        contents = ", ".join(
            f"{_BLOCK_NAMES.get(block_id, f'${block_id:02X}')} x{count}"
            for block_id, count in sorted(seen.items())
        )
        raise ValueError(f"no loadable data blocks in this .tzx -- it holds only: {contents}")
    return blocks, notes


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
