"""A tiny beeper sound-effect format: a list of (tone period, duration) pairs.

The 1-bit beeper (see ``zxemu_core.sound.beeper``) only ever does one thing: hold the
speaker at a period for some number of frames. So the whole "sound effect" concept for
v1 is just a short table of those two numbers, hand-authored as plain text (one pair
per line, ``#`` starts a comment) and compiled to a compact binary table a Z80 routine
can walk: 2-byte period, 1-byte duration, repeated, ending in a 3-byte sentinel
(``$FFFF, $00``) that can't collide with a real entry since a duration of zero frames
is meaningless for any real entry.
"""

from __future__ import annotations

SUFFIX = ".zxsfx"  # zx-prefixed so it doesn't collide with generic .sfx files from other tools

MAX_PERIOD = 0xFFFE  # 0xFFFF is reserved for the end-of-table sentinel
MAX_DURATION = 0xFF
_SENTINEL_PERIOD = 0xFFFF
_SENTINEL_DURATION = 0x00

CPU_CLOCK_HZ = 3_500_000  # the 48K/128K Z80 clock; period is T-states between speaker flips


def period_to_hz(period: int) -> float:
    """The tone frequency a given period produces, or 0.0 for a rest (period 0)."""
    return CPU_CLOCK_HZ / (2 * period) if period > 0 else 0.0


def hz_to_period(frequency_hz: float) -> int:
    """The period closest to ``frequency_hz``, or 0 (a rest) for a non-positive frequency."""
    if frequency_hz <= 0:
        return 0
    period = round(CPU_CLOCK_HZ / (2 * frequency_hz))
    return max(1, min(MAX_PERIOD, period))


def format_beeper_sfx(entries: list[tuple[int, int]]) -> str:
    """The inverse of ``parse_beeper_sfx`` -- entries back to the plain text format."""
    return "".join(f"{period},{duration}\n" for period, duration in entries)


def parse_beeper_sfx(text: str) -> list[tuple[int, int]]:
    pairs: list[tuple[int, int]] = []
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split(",")
        if len(parts) != 2:
            raise ValueError(f"line {line_no}: expected 'period,duration', got {raw_line!r}")
        period, duration = (int(p.strip()) for p in parts)
        if not 0 <= period <= MAX_PERIOD:
            raise ValueError(f"line {line_no}: period {period} out of range (0..{MAX_PERIOD})")
        if not 0 <= duration <= MAX_DURATION:
            raise ValueError(f"line {line_no}: duration {duration} out of range (0..{MAX_DURATION})")
        pairs.append((period, duration))
    return pairs


def convert_beeper_sfx(text: str) -> bytes:
    out = bytearray()
    for period, duration in parse_beeper_sfx(text):
        out += period.to_bytes(2, "little") + bytes([duration])
    out += _SENTINEL_PERIOD.to_bytes(2, "little") + bytes([_SENTINEL_DURATION])
    return bytes(out)
