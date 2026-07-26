"""A tiny beeper sound-effect format: a list of (tone period, duration) pairs.

The 1-bit beeper (see ``zxemu_core.sound.beeper``) only ever does one thing: hold the
speaker at a period for some number of frames. So the whole "sound effect" concept for
v1 is just a short table of those two numbers, hand-authored as plain text (one pair
per line, ``#`` starts a comment) and compiled to a compact binary table a Z80 routine
can walk: 2-byte period, 1-byte duration, repeated, ending in a 3-byte sentinel
(``$FFFF, $00``) that can't collide with a real entry since a duration of zero frames
is meaningless for any real entry.

The editor draws that table as a bar chart of frequency over time, which needs one more
thing this module is the right home for: the run-length coding that turns a per-frame
pitch track back into entries and vice versa (:func:`expand_to_frames`,
:func:`pack_frames`). Keeping it here rather than in the panel means the format owns its
own arithmetic -- the panel just draws rectangles.

(An earlier editor snapped pitches to a chromatic scale, and this module carried the note
grid for it. That went when the editor did: a beeper effect is a swoop or a thud, not a
melody, and snapping a swoop to semitones fights it.)
"""

from __future__ import annotations

SUFFIX = ".zxsfx"  # zx-prefixed so it doesn't collide with generic .sfx files from other tools

MAX_PERIOD = 0xFFFE  # 0xFFFF is reserved for the end-of-table sentinel
MAX_DURATION = 0xFF
_SENTINEL_PERIOD = 0xFFFF
_SENTINEL_DURATION = 0x00

ENTRY_BYTES = 3     # 2-byte period + 1-byte duration
SENTINEL_BYTES = 3  # the $FFFF,$00 end marker, which every table carries

CPU_CLOCK_HZ = 3_500_000  # the 48K/128K Z80 clock; period is T-states between speaker flips

REST = 0  # a period of zero: silence for the entry's duration


def period_to_hz(period: int) -> float:
    """The tone frequency a given period produces, or 0.0 for a rest (period 0)."""
    return CPU_CLOCK_HZ / (2 * period) if period > 0 else 0.0


def hz_to_period(frequency_hz: float) -> int:
    """The period closest to ``frequency_hz``, or 0 (a rest) for a non-positive frequency."""
    if frequency_hz <= 0:
        return 0
    period = round(CPU_CLOCK_HZ / (2 * frequency_hz))
    return max(1, min(MAX_PERIOD, period))


# --- entries <-> a per-frame pitch track ---------------------------------------------


def expand_to_frames(entries: list[tuple[int, int]]) -> list[int]:
    """Entries -> one period per frame, which is what a piano roll actually draws.

    An entry is a period held for N frames, so the drawing is a run of N identical
    columns; expanding first means the canvas has no run-length arithmetic in it.
    """
    frames: list[int] = []
    for period, duration in entries:
        frames.extend([period] * duration)
    return frames


def pack_frames(frames: list[int]) -> list[tuple[int, int]]:
    """The inverse: a per-frame pitch track -> entries, run-length coded.

    Trailing silence is dropped (it would play as nothing, and only lengthens the table),
    and a run longer than a duration byte can hold is split across repeated entries
    rather than being clipped -- so a long held tone survives a round trip intact.
    """
    while frames and frames[-1] == REST:
        frames = frames[:-1]

    entries: list[tuple[int, int]] = []
    for period in frames:
        if entries and entries[-1][0] == period and entries[-1][1] < MAX_DURATION:
            entries[-1] = (period, entries[-1][1] + 1)
        else:
            entries.append((period, 1))
    return entries


# --- the text format -------------------------------------------------------------------


def format_beeper_sfx(entries: list[tuple[int, int]]) -> str:
    """The inverse of ``parse_beeper_sfx`` -- entries back to the plain text format."""
    return "".join("{},{}\n".format(period, duration) for period, duration in entries)


def parse_beeper_sfx(text: str) -> list[tuple[int, int]]:
    pairs: list[tuple[int, int]] = []
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split(",")
        if len(parts) != 2:
            raise ValueError("line {}: expected 'period,duration', got {!r}".format(line_no, raw_line))
        period, duration = (int(p.strip()) for p in parts)
        if not 0 <= period <= MAX_PERIOD:
            raise ValueError("line {}: period {} out of range (0..{})".format(line_no, period, MAX_PERIOD))
        if not 0 <= duration <= MAX_DURATION:
            raise ValueError("line {}: duration {} out of range (0..{})".format(line_no, duration, MAX_DURATION))
        pairs.append((period, duration))
    return pairs


def table_size(entries: list[tuple[int, int]]) -> int:
    """How many bytes the compiled table costs in the Z80's memory, sentinel included.

    The editor shows this while you draw, because "how long does it sound" and "how much
    room does it take" are different questions and only the second one competes with the
    rest of the program for space. Derived here rather than in the panel so it cannot
    drift from what :func:`convert_beeper_sfx` actually emits.
    """
    return len(entries) * ENTRY_BYTES + SENTINEL_BYTES


def convert_beeper_sfx(text: str) -> bytes:
    out = bytearray()
    for period, duration in parse_beeper_sfx(text):
        out += period.to_bytes(2, "little") + bytes([duration])
    out += _SENTINEL_PERIOD.to_bytes(2, "little") + bytes([_SENTINEL_DURATION])
    return bytes(out)
