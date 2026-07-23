"""The native ``.zxspr.json`` sprite format -- for sprites drawn in zxide, not imported.

An imported sprite's source of truth is a BMP file, which makes sense for artwork that
already exists (or that you'd rather draw in a real paint program) -- but a sprite
created *from scratch* in zxide's own pixel editor has no such file to begin with, and
routing every keystroke through BMP encode/decode would be needless overhead for data
the editor already holds as plain pixels and attributes. This format is that plain
shape, written as human-readable JSON (diffable, and hand-editable in a pinch):

    {
      "frame_width": 8, "frame_height": 8,
      "frames": [
        {"pixels": ["........", "..####..", ...],   # one string per row, '#'=ink, '.'=paper
         "attrs": [{"ink": 0, "paper": 7, "bright": false}]}  # one per 8x8 cell, row-major
      ]
    }

Deliberately no mask plane here (v1 -- hand-drawn sprites can add transparency later the
same way ``generate_mask`` was added to the BMP path, without changing this shape).
``attrs`` is not optional: attribute-level editing is the entire reason this format
exists rather than reusing the plain monochrome BMP path.
"""

from __future__ import annotations

from zxemu_core.assets.manifest import FrameSequence

NATIVE_SUFFIX = ".zxspr.json"

DEFAULT_INK = 0
DEFAULT_PAPER = 7


def blank_sprite_data(frame_width: int, frame_height: int, frame_count: int = 1) -> dict:
    """A fresh, all-paper sprite of the given size -- what "New Sprite Asset" writes to disk."""
    if frame_width % 8 != 0 or frame_height % 8 != 0:
        raise ValueError(f"sprite size must be a multiple of 8 in both dimensions, got {frame_width}x{frame_height}")
    attr_cols, attr_rows = frame_width // 8, frame_height // 8
    return {
        "frame_width": frame_width,
        "frame_height": frame_height,
        "frames": [_blank_frame(frame_width, frame_height, attr_cols, attr_rows) for _ in range(frame_count)],
    }


def _blank_frame(frame_width: int, frame_height: int, attr_cols: int, attr_rows: int) -> dict:
    return {
        "pixels": ["." * frame_width for _ in range(frame_height)],
        "attrs": [{"ink": DEFAULT_INK, "paper": DEFAULT_PAPER, "bright": False} for _ in range(attr_cols * attr_rows)],
    }


def parse_native_sprite(data: dict) -> FrameSequence:
    """The on-disk dict -> a :class:`FrameSequence`, ready for placement/build/preview."""
    frame_width, frame_height = data["frame_width"], data["frame_height"]
    if frame_width % 8 != 0 or frame_height % 8 != 0:
        raise ValueError(f"sprite size must be a multiple of 8 in both dimensions, got {frame_width}x{frame_height}")
    bytes_per_row = frame_width // 8
    attr_cols, attr_rows = frame_width // 8, frame_height // 8
    attr_count = attr_cols * attr_rows

    frames_data = data["frames"]
    parts = []
    for frame_index, frame in enumerate(frames_data):
        rows = frame["pixels"]
        if len(rows) != frame_height:
            raise ValueError(f"frame {frame_index}: expected {frame_height} pixel rows, got {len(rows)}")
        pixel_plane = bytearray(bytes_per_row * frame_height)
        for row_index, row in enumerate(rows):
            if len(row) != frame_width:
                raise ValueError(f"frame {frame_index} row {row_index}: expected {frame_width} chars, got {len(row)}")
            for byte_col in range(bytes_per_row):
                byte = 0
                for bit in range(8):
                    if row[byte_col * 8 + bit] != ".":
                        byte |= 0x80 >> bit
                pixel_plane[row_index * bytes_per_row + byte_col] = byte

        attrs = frame["attrs"]
        if len(attrs) != attr_count:
            raise ValueError(f"frame {frame_index}: expected {attr_count} attribute cells, got {len(attrs)}")
        attr_plane = bytearray(attr_count)
        for cell_index, cell in enumerate(attrs):
            ink, paper, bright = cell["ink"], cell["paper"], cell["bright"]
            if not (0 <= ink <= 7 and 0 <= paper <= 7):
                raise ValueError(f"frame {frame_index} cell {cell_index}: ink/paper must be 0-7")
            attr_plane[cell_index] = ((1 if bright else 0) << 6) | (paper << 3) | ink

        parts.append(bytes(pixel_plane) + bytes(attr_plane))

    return FrameSequence(frame_width, frame_height, len(frames_data), has_mask=False, data=b"".join(parts), has_attrs=True)
