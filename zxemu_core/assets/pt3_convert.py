"""PT3 (Pro Tracker 3) AY-music files: a sanity-checked passthrough.

PT3 playback is a separate, much larger backlog item (a player routine has to walk the
tracker's pattern/ornament/sample tables and drive the AY chip register-by-register
every frame). All this milestone needs is to get the bytes into the project safely, so
this converter is passthrough plus a header check -- catching "this isn't actually a
PT3 file" at import time is far friendlier than discovering it at playback time, later,
with no player built yet to blame.
"""

from __future__ import annotations

_PT3_MAGIC = b"PT3"


def convert_pt3(data: bytes) -> bytes:
    if data[:3] != _PT3_MAGIC:
        raise ValueError("not a PT3 file (missing 'PT3' header)")
    return bytes(data)
