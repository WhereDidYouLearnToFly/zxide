"""A minimal, dependency-free BMP reader.

zxide has no image-library dependency (no Pillow, and ``zxemu_core`` can't reach for
Qt's ``QImage`` without breaking the Qt-free core/UI split), so importing artwork needs
its own tiny parser. BMP is the pragmatic choice to parse by hand: it is old, simple,
and every pixel-art tool (Aseprite, GIMP, mtPaint, Photoshop) still exports it
losslessly with no compression to decode.

Only the common uncompressed case (``BI_RGB``) is supported, at 1/4/8-bit indexed and
24-bit true colour -- everything a pixel-art tool produces by default. RLE-compressed
BMPs raise :class:`BmpError` with a clear message rather than silently misreading, since
silently-wrong pixels would be a far worse failure mode for an asset pipeline than a
loud rejection.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path


class BmpError(ValueError):
    """A BMP file this reader can't (or won't) parse."""


@dataclass
class BmpImage:
    """A decoded BMP: top-down RGB pixels, one ``(r, g, b)`` triple per pixel."""

    width: int
    height: int
    pixels: bytes  # width * height * 3 bytes, row-major, top row first

    def get_pixel(self, x: int, y: int) -> tuple[int, int, int]:
        i = (y * self.width + x) * 3
        return self.pixels[i], self.pixels[i + 1], self.pixels[i + 2]


def read_bmp(data: bytes) -> BmpImage:
    if len(data) < 54 or data[0:2] != b"BM":
        raise BmpError("not a BMP file (missing 'BM' magic)")

    pixel_offset = struct.unpack_from("<I", data, 10)[0]
    header_size = struct.unpack_from("<I", data, 14)[0]
    if header_size < 40:
        raise BmpError(f"unsupported BMP DIB header (size {header_size}); need BITMAPINFOHEADER or newer")

    width, height_raw, _planes, bitcount, compression = struct.unpack_from("<iiHHI", data, 18)
    if compression != 0:
        raise BmpError(f"unsupported BMP compression mode {compression} (only uncompressed BI_RGB is supported)")
    if bitcount not in (1, 4, 8, 24):
        raise BmpError(f"unsupported BMP bit depth {bitcount} (supported: 1, 4, 8, 24)")

    top_down = height_raw < 0
    height = abs(height_raw)
    if width <= 0 or height <= 0:
        raise BmpError(f"invalid BMP dimensions {width}x{height}")

    palette: list[tuple[int, int, int]] = []
    if bitcount <= 8:
        colors_used = struct.unpack_from("<I", data, 14 + 32)[0]
        colors = colors_used or (1 << bitcount)
        palette_offset = 14 + header_size
        for i in range(colors):
            b, g, r, _reserved = data[palette_offset + i * 4 : palette_offset + i * 4 + 4]
            palette.append((r, g, b))

    row_size = ((bitcount * width + 31) // 32) * 4  # BMP rows are padded to a 4-byte boundary
    out = bytearray(width * height * 3)
    for row in range(height):
        # BMP pixel rows are bottom-to-top unless the height field was negative.
        src_row = row if top_down else (height - 1 - row)
        row_start = pixel_offset + src_row * row_size
        row_data = data[row_start : row_start + row_size]
        for x in range(width):
            if bitcount == 24:
                i = x * 3
                b, g, r = row_data[i], row_data[i + 1], row_data[i + 2]
            else:
                index = _packed_index(row_data, x, bitcount)
                r, g, b = palette[index] if index < len(palette) else (0, 0, 0)
            o = (row * width + x) * 3
            out[o], out[o + 1], out[o + 2] = r, g, b
    return BmpImage(width, height, bytes(out))


def read_bmp_file(path: str | Path) -> BmpImage:
    return read_bmp(Path(path).read_bytes())


def _packed_index(row_data: bytes, x: int, bitcount: int) -> int:
    if bitcount == 8:
        return row_data[x]
    pixels_per_byte = 8 // bitcount
    byte_index = x // pixels_per_byte
    bit_offset = (pixels_per_byte - 1 - (x % pixels_per_byte)) * bitcount
    mask = (1 << bitcount) - 1
    return (row_data[byte_index] >> bit_offset) & mask
