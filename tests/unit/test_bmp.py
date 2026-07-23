"""Tests for the minimal BMP reader (zxemu_core.assets.bmp)."""

from __future__ import annotations

import pytest

from tests.unit.bmp_fixtures import write_bmp24, write_bmp_indexed
from zxemu_core.assets.bmp import BmpError, read_bmp


def test_reads_24bit_bottom_up():
    data = write_bmp24(4, 3, lambda x, y: (x * 10, y * 20, 5))
    image = read_bmp(data)
    assert (image.width, image.height) == (4, 3)
    assert image.get_pixel(2, 1) == (20, 20, 5)
    assert image.get_pixel(0, 0) == (0, 0, 5)


def test_reads_24bit_top_down():
    data = write_bmp24(2, 2, lambda x, y: (x, y, 0), top_down=True)
    image = read_bmp(data)
    assert image.get_pixel(1, 0) == (1, 0, 0)
    assert image.get_pixel(0, 1) == (0, 1, 0)


def test_reads_1bit_indexed():
    palette = [(0, 0, 0), (255, 255, 255)]
    data = write_bmp_indexed(8, 2, 1, palette, lambda x, y: 1 if x % 2 == 0 else 0)
    image = read_bmp(data)
    assert image.get_pixel(0, 0) == (255, 255, 255)
    assert image.get_pixel(1, 0) == (0, 0, 0)


def test_reads_8bit_indexed():
    palette = [(10, 20, 30), (40, 50, 60), (70, 80, 90)]
    data = write_bmp_indexed(3, 1, 8, palette, lambda x, y: x)
    image = read_bmp(data)
    assert image.get_pixel(0, 0) == (10, 20, 30)
    assert image.get_pixel(2, 0) == (70, 80, 90)


def test_rejects_missing_magic():
    with pytest.raises(BmpError, match="not a BMP"):
        read_bmp(b"not a bmp file at all, but at least 54 bytes long padding")


def test_rejects_compressed_bmp():
    data = bytearray(write_bmp24(2, 2, lambda x, y: (0, 0, 0)))
    # Compression field is 4 bytes at offset 30.
    data[30:34] = (1).to_bytes(4, "little")
    with pytest.raises(BmpError, match="compression"):
        read_bmp(bytes(data))
