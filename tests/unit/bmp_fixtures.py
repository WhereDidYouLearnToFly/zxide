"""BMP-writing helpers for tests -- the inverse of ``zxemu_core.assets.bmp``.

Not a ``test_*`` module itself (pytest won't collect it); just synthesizes small BMP
files in memory so asset-conversion tests don't need real files on disk.
"""

from __future__ import annotations

import struct


def write_bmp24(width: int, height: int, get_pixel, top_down: bool = False) -> bytes:
    """A minimal uncompressed 24-bit BMP. ``get_pixel(x, y) -> (r, g, b)``."""
    row_size = ((24 * width + 31) // 32) * 4
    pixel_data = bytearray(row_size * height)
    for row in range(height):
        src_row = row if top_down else (height - 1 - row)
        for x in range(width):
            r, g, b = get_pixel(x, src_row)
            i = row * row_size + x * 3
            pixel_data[i], pixel_data[i + 1], pixel_data[i + 2] = b, g, r

    pixel_offset = 14 + 40
    file_size = pixel_offset + len(pixel_data)
    file_header = b"BM" + struct.pack("<IHHI", file_size, 0, 0, pixel_offset)
    height_field = -height if top_down else height
    dib_header = struct.pack(
        "<IiiHHIIiiII", 40, width, height_field, 1, 24, 0, len(pixel_data), 2835, 2835, 0, 0
    )
    return file_header + dib_header + bytes(pixel_data)


def write_bmp_indexed(width: int, height: int, bitcount: int, palette: list[tuple[int, int, int]], get_index) -> bytes:
    """A minimal uncompressed indexed BMP (1/4/8-bit). ``get_index(x, y) -> palette index``."""
    row_size = ((bitcount * width + 31) // 32) * 4
    pixel_data = bytearray(row_size * height)
    pixels_per_byte = 8 // bitcount
    for row in range(height):
        src_row = height - 1 - row  # bottom-up
        for x in range(width):
            index = get_index(x, src_row)
            if bitcount == 8:
                pixel_data[row * row_size + x] = index
            else:
                byte_index = x // pixels_per_byte
                bit_offset = (pixels_per_byte - 1 - (x % pixels_per_byte)) * bitcount
                pixel_data[row * row_size + byte_index] |= index << bit_offset

    palette_bytes = b"".join(bytes((b, g, r, 0)) for r, g, b in palette)
    pixel_offset = 14 + 40 + len(palette_bytes)
    file_size = pixel_offset + len(pixel_data)
    file_header = b"BM" + struct.pack("<IHHI", file_size, 0, 0, pixel_offset)
    dib_header = struct.pack(
        "<IiiHHIIiiII", 40, width, height, 1, bitcount, 0, len(pixel_data), 2835, 2835, len(palette), 0
    )
    return file_header + dib_header + palette_bytes + bytes(pixel_data)
