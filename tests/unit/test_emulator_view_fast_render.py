"""Cross-check the numpy fast renderer against the pure-Python reference.

render_frame_fast must produce byte-for-byte identical output to
render_bordered_frame for any screen contents and border/flash combination --
the fast path is purely an optimization, not a behavior change.
"""

import numpy as np
import pytest

from zxemu_ui.emulator_view import (
    BYTES_PER_PIXEL,
    FULL_HEIGHT,
    FULL_WIDTH,
    render_bordered_frame,
    render_frame_fast,
)


class BankBackedMemory:
    """Minimal memory exposing both read_byte (for the reference renderer) and a
    raw 16K screen bank at slot 1 (for the fast renderer)."""

    def __init__(self, screen_bank: bytearray):
        self.slots = [None, _Bank(screen_bank), None, None]

    def read_byte(self, address: int) -> int:
        # Only screen-area reads (0x4000-0x5AFF) are exercised by the renderers.
        return self.slots[1].data[address - 0x4000]


class _Bank:
    def __init__(self, data: bytearray):
        self.data = data


def _random_screen_bank(seed: int) -> bytearray:
    rng = np.random.default_rng(seed)
    bank = bytearray(0x4000)
    # fill the 6912-byte display file (bitmap + attributes) with noise
    bank[0:0x1B00] = bytes(rng.integers(0, 256, size=0x1B00, dtype=np.uint8))
    return bank


def _fast_bytes(screen_bank: bytearray, border: int, flash_on: bool) -> bytes:
    arr = np.frombuffer(screen_bank, dtype=np.uint8)
    return render_frame_fast(arr, border, flash_on=flash_on).tobytes()


@pytest.mark.parametrize("seed", [1, 2, 3])
@pytest.mark.parametrize("border", [0, 5, 7])
@pytest.mark.parametrize("flash_on", [False, True])
def test_fast_matches_reference(seed, border, flash_on):
    bank = _random_screen_bank(seed)
    memory = BankBackedMemory(bank)

    reference = render_bordered_frame(memory, border, flash_on=flash_on)
    fast = _fast_bytes(bank, border, flash_on)

    assert len(fast) == FULL_WIDTH * FULL_HEIGHT * BYTES_PER_PIXEL
    assert fast == bytes(reference)


def test_fast_render_shape_and_dtype():
    bank = _random_screen_bank(0)
    frame = render_frame_fast(np.frombuffer(bank, dtype=np.uint8), 0)
    assert frame.shape == (FULL_HEIGHT, FULL_WIDTH)
    assert frame.dtype == np.dtype("<u4")
