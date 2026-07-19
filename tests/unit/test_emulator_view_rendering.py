"""Tests for the pure-Python rendering logic in emulator_view.py.

Most of these avoid constructing any actual Qt widgets -- they only exercise
the address-math and pixel-buffer functions, which need no display. A few
at the bottom construct the EmulatorView widget itself, using Qt's
"offscreen" platform plugin so no real display is required.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from zxemu_ui.emulator_view import (  # noqa: E402
    BORDER_MARGIN,
    BYTES_PER_PIXEL,
    FLASH_TOGGLE_FRAMES,
    FULL_HEIGHT,
    FULL_WIDTH,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    EmulatorView,
    attribute_address,
    bitmap_address,
    render_bordered_frame,
    render_screen_rgb,
)


class _Bank:
    def __init__(self, data: bytearray):
        self.data = data


class FakeMemory:
    def __init__(self):
        self.data = {}

    def read_byte(self, address: int) -> int:
        return self.data.get(address, 0)

    @property
    def slots(self):
        # Materialize a 16K screen bank (slot 1) from the sparse dict so the
        # widget's numpy fast path, which reads memory.slots[1].data, works.
        bank = bytearray(0x4000)
        for address, value in self.data.items():
            if 0x4000 <= address < 0x8000:
                bank[address - 0x4000] = value
        return [None, _Bank(bank), None, None]


class FakeUla:
    def __init__(self, border_color: int = 0):
        self.border_color = border_color


class FakeMachine:
    def __init__(self, memory=None, border_color: int = 0):
        self.memory = memory or FakeMemory()
        self.ula = FakeUla(border_color)


def test_bitmap_address_top_left_is_screen_base():
    assert bitmap_address(0, 0) == 0x4000


def test_bitmap_address_advances_by_char_row_within_a_third():
    assert bitmap_address(8, 0) == 0x4000 + 32  # second character row, first pixel line


def test_bitmap_address_advances_by_pixel_row_within_a_char_row():
    assert bitmap_address(1, 0) == 0x4000 + 256  # same char row, second pixel line


def test_bitmap_address_jumps_2k_at_each_third():
    assert bitmap_address(64, 0) == 0x4000 + 2048
    assert bitmap_address(128, 0) == 0x4000 + 4096


def test_bitmap_address_last_byte_of_screen():
    assert bitmap_address(191, 31) == 0x57FF


def test_attribute_address_is_linear_by_character_row():
    assert attribute_address(0, 0) == 0x5800
    assert attribute_address(8, 0) == 0x5800 + 32
    assert attribute_address(191, 31) == 0x5AFF


def _pixel_bgra(buffer: bytearray, x: int, y: int, width: int = SCREEN_WIDTH) -> bytes:
    offset = (y * width + x) * BYTES_PER_PIXEL
    return bytes(buffer[offset : offset + BYTES_PER_PIXEL])


RED_BGRA = bytes((0x00, 0x00, 0xD7, 0xFF))
BLUE_BGRA = bytes((0xD7, 0x00, 0x00, 0xFF))
BRIGHT_RED_BGRA = bytes((0x00, 0x00, 0xFF, 0xFF))


def test_render_screen_rgb_produces_correct_size_buffer():
    buffer = render_screen_rgb(FakeMemory())
    assert len(buffer) == SCREEN_WIDTH * SCREEN_HEIGHT * BYTES_PER_PIXEL


def test_render_screen_rgb_all_zero_is_black_on_black():
    buffer = render_screen_rgb(FakeMemory())
    assert _pixel_bgra(buffer, 0, 0) == bytes((0x00, 0x00, 0x00, 0xFF))


def test_render_screen_rgb_bit_pattern_selects_ink_vs_paper():
    memory = FakeMemory()
    memory.data[bitmap_address(0, 0)] = 0b10000000  # only the leftmost pixel is "ink"
    memory.data[attribute_address(0, 0)] = 0b000_001_010  # ink=red(2), paper=blue(1), not bright
    buffer = render_screen_rgb(memory)
    assert _pixel_bgra(buffer, 0, 0) == RED_BGRA  # bit set -> ink
    assert _pixel_bgra(buffer, 1, 0) == BLUE_BGRA  # bit clear -> paper


def test_render_screen_rgb_bright_bit_uses_bright_palette():
    memory = FakeMemory()
    memory.data[bitmap_address(0, 0)] = 0b10000000
    memory.data[attribute_address(0, 0)] = 0b0_1_000_010  # bright(bit6) + ink=red
    buffer = render_screen_rgb(memory)
    assert _pixel_bgra(buffer, 0, 0) == BRIGHT_RED_BGRA


def test_flash_off_leaves_ink_paper_unswapped_even_if_flash_bit_set():
    memory = FakeMemory()
    memory.data[bitmap_address(0, 0)] = 0b10000000
    memory.data[attribute_address(0, 0)] = 0b1_0_001_010  # FLASH(bit7) + ink=red, paper=blue
    buffer = render_screen_rgb(memory, flash_on=False)
    assert _pixel_bgra(buffer, 0, 0) == RED_BGRA
    assert _pixel_bgra(buffer, 1, 0) == BLUE_BGRA


def test_flash_on_swaps_ink_and_paper_when_flash_bit_set():
    memory = FakeMemory()
    memory.data[bitmap_address(0, 0)] = 0b10000000
    memory.data[attribute_address(0, 0)] = 0b1_0_001_010  # FLASH + ink=red, paper=blue
    buffer = render_screen_rgb(memory, flash_on=True)
    assert _pixel_bgra(buffer, 0, 0) == BLUE_BGRA  # swapped: "ink" pixel now shows paper color
    assert _pixel_bgra(buffer, 1, 0) == RED_BGRA


def test_flash_on_does_not_affect_cells_without_flash_bit():
    memory = FakeMemory()
    memory.data[bitmap_address(0, 0)] = 0b10000000
    memory.data[attribute_address(0, 0)] = 0b0_0_001_010  # no FLASH bit
    buffer = render_screen_rgb(memory, flash_on=True)
    assert _pixel_bgra(buffer, 0, 0) == RED_BGRA  # unswapped


def test_render_bordered_frame_size():
    buffer = render_bordered_frame(FakeMemory(), border_color=0)
    assert len(buffer) == FULL_WIDTH * FULL_HEIGHT * BYTES_PER_PIXEL


def test_render_bordered_frame_corner_is_border_color():
    buffer = render_bordered_frame(FakeMemory(), border_color=2)  # red
    assert _pixel_bgra(buffer, 0, 0, width=FULL_WIDTH) == RED_BGRA


def test_render_bordered_frame_screen_content_is_centered():
    memory = FakeMemory()
    memory.data[bitmap_address(0, 0)] = 0b10000000
    memory.data[attribute_address(0, 0)] = 0b000_001_010  # ink=red, paper=blue
    buffer = render_bordered_frame(memory, border_color=0)
    assert _pixel_bgra(buffer, BORDER_MARGIN, BORDER_MARGIN, width=FULL_WIDTH) == RED_BGRA
    assert _pixel_bgra(buffer, BORDER_MARGIN + 1, BORDER_MARGIN, width=FULL_WIDTH) == BLUE_BGRA


def test_border_ignores_bright_bit_since_border_has_no_bright():
    # border_color is masked to 3 bits regardless of any stray high bits
    buffer = render_bordered_frame(FakeMemory(), border_color=0xFA)  # 0xFA & 7 == 2 (red)
    assert _pixel_bgra(buffer, 0, 0, width=FULL_WIDTH) == RED_BGRA


@pytest.fixture(scope="module")
def qapp():
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def test_emulator_view_constructs_and_refreshes(qapp):
    machine = FakeMachine(border_color=0)
    view = EmulatorView(machine)
    view.refresh()
    assert view.size().width() >= FULL_WIDTH
    assert view.size().height() >= FULL_HEIGHT


def test_emulator_view_flash_toggles_every_16_frames(qapp):
    memory = FakeMemory()
    memory.data[bitmap_address(0, 0)] = 0b10000000
    memory.data[attribute_address(0, 0)] = 0b1_0_001_010  # FLASH + ink=red, paper=blue
    machine = FakeMachine(memory=memory, border_color=0)
    view = EmulatorView(machine)

    for _ in range(FLASH_TOGGLE_FRAMES):
        view.refresh()
    # after exactly FLASH_TOGGLE_FRAMES refreshes, flash phase has flipped once
    pixel = _pixel_bgra(view._buffer, BORDER_MARGIN, BORDER_MARGIN, width=FULL_WIDTH)
    assert pixel == BLUE_BGRA  # swapped
