"""8x5 ZX Spectrum keyboard matrix, read via port 0xFE (high byte of the port
address selects which half-row(s) to read). Standard, publicly documented
Spectrum hardware layout -- reimplemented independently.
"""

from __future__ import annotations

# Row index -> the 5 keys on that half-row, bit 0 (LSB) first. Row N's
# address line is bit N of the port's high byte (active low).
ROWS = [
    ("CAPS SHIFT", "Z", "X", "C", "V"),
    ("A", "S", "D", "F", "G"),
    ("Q", "W", "E", "R", "T"),
    ("1", "2", "3", "4", "5"),
    ("0", "9", "8", "7", "6"),
    ("P", "O", "I", "U", "Y"),
    ("ENTER", "L", "K", "J", "H"),
    ("SPACE", "SYM SHIFT", "M", "N", "B"),
]

_KEY_TO_POSITION = {
    key: (row_index, bit) for row_index, row in enumerate(ROWS) for bit, key in enumerate(row)
}


class Keyboard:
    """Active-low 8x5 matrix: row_state[i] bit b is 0 while that key is held down."""

    def __init__(self) -> None:
        self.row_state = [0x1F] * 8  # all released

    def press(self, key: str) -> None:
        row, bit = _KEY_TO_POSITION[key]
        self.row_state[row] &= ~(1 << bit) & 0x1F

    def release(self, key: str) -> None:
        row, bit = _KEY_TO_POSITION[key]
        self.row_state[row] |= 1 << bit

    def release_all(self) -> None:
        self.row_state = [0x1F] * 8

    def read(self, port: int) -> int:
        """AND together the row bits for every row whose address line is low in the port's high byte."""
        high_byte = (port >> 8) & 0xFF
        result = 0x1F
        for row_index in range(8):
            if not (high_byte & (1 << row_index)):
                result &= self.row_state[row_index]
        return result
