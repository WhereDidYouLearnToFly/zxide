"""The catch-all converter: raw bytes in, raw bytes out.

Not every asset needs interpreting -- a pre-compiled data table, a compressed blob, or
any file format zxide doesn't understand yet all just need to end up at some address
with a label. This is also the building block a couple of other converters borrow: a
pre-packed raw-binary font is "binary passthrough plus some metadata", not a separate
packing routine.
"""

from __future__ import annotations


def convert_binary(data: bytes, expected_length: int | None = None) -> bytes:
    if expected_length is not None and len(data) != expected_length:
        raise ValueError(f"expected {expected_length} bytes, got {len(data)}")
    return bytes(data)
