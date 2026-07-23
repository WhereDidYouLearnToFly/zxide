"""The Spectrum's 15-colour hardware palette, shared by conversion and preview.

Duplicated from ``zxemu_ui.panels.emulator_view`` rather than imported from it --
``zxemu_core`` must stay Qt-free and independently testable, and that module pulls in
PyQt5 at import time. Keep the two RGB tables in sync by hand; they are small and
change essentially never (this *is* the hardware palette).
"""

from __future__ import annotations

NORMAL_RGB = [
    (0x00, 0x00, 0x00),
    (0x00, 0x00, 0xD7),
    (0xD7, 0x00, 0x00),
    (0xD7, 0x00, 0xD7),
    (0x00, 0xD7, 0x00),
    (0x00, 0xD7, 0xD7),
    (0xD7, 0xD7, 0x00),
    (0xD7, 0xD7, 0xD7),
]
BRIGHT_RGB = [
    (0x00, 0x00, 0x00),
    (0x00, 0x00, 0xFF),
    (0xFF, 0x00, 0x00),
    (0xFF, 0x00, 0xFF),
    (0x00, 0xFF, 0x00),
    (0x00, 0xFF, 0xFF),
    (0xFF, 0xFF, 0x00),
    (0xFF, 0xFF, 0xFF),
]

SCREEN_WIDTH = 256
SCREEN_HEIGHT = 192
BYTES_PER_ROW = 32
SCREEN_BITMAP_BYTES = 6144
SCREEN_ATTR_BYTES = 768


def _sq_error(a: tuple[int, int, int], b: tuple[int, int, int]) -> int:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2


def nearest_index(rgb: tuple[int, int, int], bright: bool) -> tuple[int, int]:
    """Nearest palette index for ``rgb`` in the given brightness, plus its error."""
    table = BRIGHT_RGB if bright else NORMAL_RGB
    best_index, best_error = 0, None
    for index, candidate in enumerate(table):
        error = _sq_error(rgb, candidate)
        if best_error is None or error < best_error:
            best_index, best_error = index, error
    return best_index, best_error


def bitmap_offset(y: int, x_byte: int) -> int:
    """Byte offset within the 6144-byte bitmap plane for pixel row/byte-column.

    Mirrors ``emulator_view.bitmap_address`` minus its ``0x4000`` base -- the Spectrum
    screen file interleaves thirds of the screen rather than running top-to-bottom, and
    a ``bitmap`` asset must reproduce that layout exactly since it is meant to be
    ``incbin``'d straight into display memory.
    """
    return (y & 0xC0) * 32 + (y & 0x07) * 256 + (y & 0x38) * 4 + x_byte


def attribute_offset(y: int, x_byte: int) -> int:
    """Byte offset within the 768-byte attribute plane, mirroring ``emulator_view.attribute_address``."""
    return (y // 8) * 32 + x_byte


def attr_colors(attr_byte: int) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """(ink_rgb, paper_rgb) for a standard Spectrum attribute byte (FLASH bit ignored)."""
    ink, paper = attr_byte & 0x07, (attr_byte >> 3) & 0x07
    table = BRIGHT_RGB if (attr_byte & 0x40) else NORMAL_RGB
    return table[ink], table[paper]
