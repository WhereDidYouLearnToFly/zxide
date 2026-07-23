"""PyQt5 widget rendering the Spectrum's display: screen bitmap/attributes,
a solid per-frame border color, and FLASH-attribute ink/paper swapping.

Screen memory addressing, the 8-color palette, and the border margin are
standard, publicly documented Spectrum hardware/emulation conventions,
reimplemented independently. Per-scanline border effects (mid-frame color
changes) aren't modeled -- one border color is used for the whole frame.
"""

from __future__ import annotations

import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QImage, QPainter
from PyQt5.QtWidgets import QWidget

# A 1px frame signalling keyboard focus: green when the view has focus (typing reaches
# the Spectrum), a faint gray otherwise -- so it's always obvious whether the machine
# is "listening" to the keyboard.
_FOCUS_ON = QColor("#4ec96b")
_FOCUS_OFF = QColor("#4a4a4a")

SCREEN_WIDTH = 256
SCREEN_HEIGHT = 192
BYTES_PER_ROW = 32  # 256 pixels / 8 bits per bitmap byte
BYTES_PER_PIXEL = 4  # QImage.Format_RGB32

BORDER_MARGIN = 32
FULL_WIDTH = SCREEN_WIDTH + 2 * BORDER_MARGIN
FULL_HEIGHT = SCREEN_HEIGHT + 2 * BORDER_MARGIN

FLASH_TOGGLE_FRAMES = 16  # ink/paper swap alternates every 16 frames, matching the real ROM's flash rate

_NORMAL_RGB = [
    (0x00, 0x00, 0x00),
    (0x00, 0x00, 0xD7),
    (0xD7, 0x00, 0x00),
    (0xD7, 0x00, 0xD7),
    (0x00, 0xD7, 0x00),
    (0x00, 0xD7, 0xD7),
    (0xD7, 0xD7, 0x00),
    (0xD7, 0xD7, 0xD7),
]
_BRIGHT_RGB = [
    (0x00, 0x00, 0x00),
    (0x00, 0x00, 0xFF),
    (0xFF, 0x00, 0x00),
    (0xFF, 0x00, 0xFF),
    (0x00, 0xFF, 0x00),
    (0x00, 0xFF, 0xFF),
    (0xFF, 0xFF, 0x00),
    (0xFF, 0xFF, 0xFF),
]


def _bgra_bytes(rgb: tuple) -> bytes:
    r, g, b = rgb
    return bytes((b, g, r, 0xFF))  # little-endian memory order for QImage.Format_RGB32 (0xffRRGGBB)


# attr byte -> (ink_bgra, paper_bgra); FLASH swap is applied by the caller, since it's
# time-dependent rather than a property of the attribute byte alone.
_ATTR_COLORS = []
for _attr in range(256):
    _ink = _attr & 0x07
    _paper = (_attr >> 3) & 0x07
    _palette = _BRIGHT_RGB if (_attr & 0x40) else _NORMAL_RGB
    _ATTR_COLORS.append((_bgra_bytes(_palette[_ink]), _bgra_bytes(_palette[_paper])))

# The border can only ever be one of the 8 non-bright colors (port 0xFE has no bright bit).
_BORDER_COLORS = [_bgra_bytes(rgb) for rgb in _NORMAL_RGB]


def bitmap_address(y: int, x_byte: int) -> int:
    """Address of the bitmap byte covering pixel row y (0-191), byte column x_byte (0-31).

    The Spectrum's screen file isn't laid out linearly top-to-bottom; each
    third of the screen (64 rows) is a contiguous 2K block, and within a
    third, pixel rows of the same position-within-character-cell are
    grouped together before advancing to the next character row.
    """
    return 0x4000 + (y & 0xC0) * 32 + (y & 0x07) * 256 + (y & 0x38) * 4 + x_byte


def attribute_address(y: int, x_byte: int) -> int:
    return 0x5800 + (y // 8) * 32 + x_byte


def render_screen_rgb(memory, flash_on: bool = False) -> bytearray:
    """Render the 256x192 display file to a flat BGRA byte buffer for QImage.Format_RGB32.

    flash_on swaps ink/paper for every character cell whose attribute FLASH
    bit (0x80) is set -- the caller decides when that's true (see
    EmulatorView.refresh's frame counter).
    """
    buffer = bytearray(SCREEN_WIDTH * SCREEN_HEIGHT * BYTES_PER_PIXEL)
    row_stride = SCREEN_WIDTH * BYTES_PER_PIXEL
    for y in range(SCREEN_HEIGHT):
        row_offset = y * row_stride
        for x_byte in range(BYTES_PER_ROW):
            bitmap_byte = memory.read_byte(bitmap_address(y, x_byte))
            attr_byte = memory.read_byte(attribute_address(y, x_byte))
            ink, paper = _ATTR_COLORS[attr_byte]
            if flash_on and (attr_byte & 0x80):
                ink, paper = paper, ink
            pixel_offset = row_offset + x_byte * 8 * BYTES_PER_PIXEL
            for bit in range(8):
                color = ink if (bitmap_byte & (0x80 >> bit)) else paper
                start = pixel_offset + bit * BYTES_PER_PIXEL
                buffer[start : start + 4] = color
    return buffer


def render_bordered_frame(memory, border_color: int, flash_on: bool = False) -> bytearray:
    """Render the full FULL_WIDTH x FULL_HEIGHT frame: border color everywhere, screen content centered."""
    buffer = bytearray(FULL_WIDTH * FULL_HEIGHT * BYTES_PER_PIXEL)
    border_row = _BORDER_COLORS[border_color & 0x07] * FULL_WIDTH
    row_bytes = FULL_WIDTH * BYTES_PER_PIXEL
    for y in range(FULL_HEIGHT):
        buffer[y * row_bytes : (y + 1) * row_bytes] = border_row

    screen_buffer = render_screen_rgb(memory, flash_on=flash_on)
    screen_row_bytes = SCREEN_WIDTH * BYTES_PER_PIXEL
    for y in range(SCREEN_HEIGHT):
        src_start = y * screen_row_bytes
        dst_row = BORDER_MARGIN + y
        dst_start = (dst_row * FULL_WIDTH + BORDER_MARGIN) * BYTES_PER_PIXEL
        buffer[dst_start : dst_start + screen_row_bytes] = screen_buffer[src_start : src_start + screen_row_bytes]
    return buffer


# --- numpy fast path (used by the live widget) -------------------------------
#
# The pure-Python renderers above touch every one of 256*192 = 49,152 pixels in
# an interpreted loop -- fine for tests, far too slow for 50 fps. The functions
# below do the identical work with whole-array numpy operations instead, which
# run in native C, turning a ~34 ms/frame render into ~1-2 ms. render_frame_fast
# is cross-checked byte-for-byte against render_bordered_frame in the tests.

# 32-bit 0xAARRGGBB palette, little-endian (so tobytes() yields B,G,R,A per pixel,
# matching QImage.Format_RGB32). Index 0-7 = normal colors, 8-15 = bright.
_PALETTE_U32 = np.array(
    [0xFF000000 | (r << 16) | (g << 8) | b for (r, g, b) in _NORMAL_RGB + _BRIGHT_RGB],
    dtype="<u4",
)


def _build_screen_index_tables():
    """Precompute, for every (pixel row, byte column), the byte's offset inside the
    16K screen bank -- so a whole frame's worth of bytes can be gathered at once."""
    y = np.arange(SCREEN_HEIGHT).reshape(SCREEN_HEIGHT, 1)
    xb = np.arange(BYTES_PER_ROW).reshape(1, BYTES_PER_ROW)
    bitmap = (y & 0xC0) * 32 + (y & 0x07) * 256 + (y & 0x38) * 4 + xb  # offset from 0x4000
    attr = 0x1800 + (y // 8) * 32 + xb  # attributes start 0x1800 into the bank
    broadcast = np.broadcast_arrays(bitmap, attr)
    return broadcast[0].astype(np.intp), broadcast[1].astype(np.intp)


_BITMAP_INDEX, _ATTR_INDEX = _build_screen_index_tables()


def render_frame_fast(screen_bank: np.ndarray, border_color: int, flash_on: bool = False) -> np.ndarray:
    """Vectorized equivalent of render_bordered_frame, operating on the raw 16K screen
    bank as a uint8 array. Returns a (FULL_HEIGHT, FULL_WIDTH) uint32 image array."""
    bitmap = screen_bank[_BITMAP_INDEX]  # (192, 32) bitmap bytes
    attr = screen_bank[_ATTR_INDEX]  # (192, 32) attribute bytes

    bits = np.unpackbits(bitmap, axis=1)  # (192, 256): 1 per lit pixel, MSB-first
    attr_px = np.repeat(attr, 8, axis=1)  # (192, 256): attribute spread over its 8 pixels

    ink = attr_px & 0x07
    paper = (attr_px >> 3) & 0x07
    bright = (attr_px >> 6) & 0x01
    if flash_on:
        swap = (attr_px & 0x80) != 0
        ink, paper = np.where(swap, paper, ink), np.where(swap, ink, paper)

    color_index = np.where(bits != 0, ink, paper) + bright * 8
    screen_rgb = _PALETTE_U32[color_index]  # (192, 256) uint32

    frame = np.empty((FULL_HEIGHT, FULL_WIDTH), dtype="<u4")
    frame[:] = _PALETTE_U32[border_color & 0x07]
    frame[BORDER_MARGIN : BORDER_MARGIN + SCREEN_HEIGHT, BORDER_MARGIN : BORDER_MARGIN + SCREEN_WIDTH] = screen_rgb
    return frame


# Qt key -> the single Spectrum matrix key it presses. Letters/digits enter the ROM's
# usual BASIC-keyword/letter editor modes exactly as on real hardware -- this widget
# only needs to deliver correct raw key-matrix presses, not know about editor modes.
_SINGLE_KEY_MAP = {
    Qt.Key_Return: "ENTER",
    Qt.Key_Enter: "ENTER",
    Qt.Key_Space: "SPACE",
    Qt.Key_Shift: "CAPS SHIFT",
    Qt.Key_Control: "SYM SHIFT",
}
for _letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    _SINGLE_KEY_MAP[getattr(Qt, f"Key_{_letter}")] = _letter
for _digit in "0123456789":
    _SINGLE_KEY_MAP[getattr(Qt, f"Key_{_digit}")] = _digit

# Qt key -> multiple Spectrum matrix keys pressed together. Two purposes:
#  - Editing keys the Spectrum places on CAPS SHIFT + a digit (delete, cursors)
#    so PC Backspace / arrow keys "just work".
#  - Punctuation the Spectrum only has via SYMBOL SHIFT combinations, mapped
#    from the equivalent PC punctuation key so typing feels natural.
_CHORD_KEY_MAP = {
    # --- editing keys (CAPS SHIFT + digit on real hardware) ---
    Qt.Key_Backspace: ("CAPS SHIFT", "0"),  # DELETE
    Qt.Key_Left: ("CAPS SHIFT", "5"),
    Qt.Key_Down: ("CAPS SHIFT", "6"),
    Qt.Key_Up: ("CAPS SHIFT", "7"),
    Qt.Key_Right: ("CAPS SHIFT", "8"),
    # --- SYMBOL SHIFT punctuation ---
    Qt.Key_Exclam: ("SYM SHIFT", "1"),  # !
    Qt.Key_At: ("SYM SHIFT", "2"),  # @
    Qt.Key_NumberSign: ("SYM SHIFT", "3"),  # #
    Qt.Key_Dollar: ("SYM SHIFT", "4"),  # $
    Qt.Key_Percent: ("SYM SHIFT", "5"),  # %
    Qt.Key_Ampersand: ("SYM SHIFT", "6"),  # &
    Qt.Key_Apostrophe: ("SYM SHIFT", "7"),  # '
    Qt.Key_ParenLeft: ("SYM SHIFT", "8"),  # (
    Qt.Key_ParenRight: ("SYM SHIFT", "9"),  # )
    Qt.Key_Underscore: ("SYM SHIFT", "0"),  # _
    Qt.Key_QuoteDbl: ("SYM SHIFT", "P"),  # "
    Qt.Key_Less: ("SYM SHIFT", "R"),  # <
    Qt.Key_Greater: ("SYM SHIFT", "T"),  # >
    Qt.Key_Semicolon: ("SYM SHIFT", "O"),  # ;
    Qt.Key_Colon: ("SYM SHIFT", "Z"),  # :
    Qt.Key_Equal: ("SYM SHIFT", "L"),  # =
    Qt.Key_Plus: ("SYM SHIFT", "K"),  # +
    Qt.Key_Minus: ("SYM SHIFT", "J"),  # -
    Qt.Key_Asterisk: ("SYM SHIFT", "B"),  # *
    Qt.Key_Slash: ("SYM SHIFT", "V"),  # /
    Qt.Key_Question: ("SYM SHIFT", "C"),  # ?
    Qt.Key_Comma: ("SYM SHIFT", "N"),  # ,
    Qt.Key_Period: ("SYM SHIFT", "M"),  # .
}


class EmulatorView(QWidget):
    """Renders a Machine's display (border + screen); call refresh() once per frame to repaint."""

    def __init__(self, machine, parent=None):
        super().__init__(parent)
        self.machine = machine
        self._frame_counter = 0
        self._held_keys: dict[int, int] = {}  # physical-key id -> logical Qt key at press time
        self._buffer = bytearray(FULL_WIDTH * FULL_HEIGHT * BYTES_PER_PIXEL)
        self._image = QImage(self._buffer, FULL_WIDTH, FULL_HEIGHT, FULL_WIDTH * BYTES_PER_PIXEL, QImage.Format_RGB32)
        # A low floor only: the paint path scales the image to whatever size the host
        # gives us (the IDE's EmulatorStage sizes this relative to the window), so we
        # don't pin the native 320x256 -- that would stop the view scaling down.
        self.setMinimumSize(FULL_WIDTH // 2, FULL_HEIGHT // 2)
        self.setFocusPolicy(Qt.StrongFocus)

    def refresh(self, frame_count: int | None = None) -> None:
        # frame_count, when given, is the count of emulated frames elapsed (real
        # time), used for FLASH timing so the blink rate is independent of how
        # often we repaint. Without it, fall back to counting repaints.
        if frame_count is None:
            self._frame_counter += 1
            frame_count = self._frame_counter
        flash_on = (frame_count // FLASH_TOGGLE_FRAMES) % 2 == 1
        # Ask the machine which 16K bank the ULA displays: slot 1 on 48K, but RAM5 or
        # (shadow) RAM7 on 128K depending on port 0x7FFD -- even if RAM7 isn't slotted in.
        screen_bank = np.frombuffer(self.machine.display_memory(), dtype=np.uint8)
        frame = render_frame_fast(screen_bank, self.machine.ula.border_color, flash_on=flash_on)
        # tobytes() gives an immutable copy the QImage can safely reference for its lifetime.
        self._buffer = frame.tobytes()
        self._image = QImage(self._buffer, FULL_WIDTH, FULL_HEIGHT, FULL_WIDTH * BYTES_PER_PIXEL, QImage.Format_RGB32)
        self.update()

    def current_image(self) -> QImage:
        """The last-rendered frame at its native FULL_WIDTHxFULL_HEIGHT resolution.

        Distinct from grabbing the widget itself, which would capture whatever size
        the dock happens to be scaling the picture to right now -- a screenshot
        should be crisp at the Spectrum's real resolution, not whatever arbitrary
        size the window was when you clicked the button.
        """
        return self._image.copy()

    def focusInEvent(self, event) -> None:  # noqa: N802 (Qt override name)
        super().focusInEvent(event)
        self.update()  # repaint so the focus border turns green

    def focusOutEvent(self, event) -> None:  # noqa: N802 (Qt override name)
        super().focusOutEvent(event)
        self.update()  # repaint so the focus border goes gray

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.drawImage(self.rect(), self._image, self._image.rect())
        # A thin frame showing whether we currently hold keyboard focus.
        painter.setPen(_FOCUS_ON if self.hasFocus() else _FOCUS_OFF)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(0, 0, self.width() - 1, self.height() - 1)

    @staticmethod
    def _key_identity(event) -> int:
        """Stable per-physical-key id for tracking held keys.

        The logical key() changes with Shift state -- e.g. the ' key reports
        Qt.Key_QuoteDbl while Shift is down but Qt.Key_Apostrophe once Shift
        is released -- so tracking presses/releases by key() lets a key whose
        Shift is lifted first get "stuck". The hardware scan code is constant
        for a physical key regardless of modifiers, so we key on that (falling
        back to key() in synthetic events that carry no scan code, e.g. tests).
        """
        return event.nativeScanCode() or event.key()

    def keyPressEvent(self, event) -> None:
        if event.isAutoRepeat():
            return
        self._held_keys[self._key_identity(event)] = event.key()
        self._rebuild_matrix()

    def keyReleaseEvent(self, event) -> None:
        if event.isAutoRepeat():
            return
        self._held_keys.pop(self._key_identity(event), None)
        self._rebuild_matrix()

    def _rebuild_matrix(self) -> None:
        """Recompute the whole Spectrum key matrix from the set of held PC keys.

        Rebuilding from scratch (rather than pressing/releasing individually)
        avoids stuck keys, and lets us resolve the physical-Shift conflict:
        pressing e.g. PC Shift+1 to get "!" sends both a Shift key event
        (which we'd map to CAPS SHIFT) and a "!" key event (SYM SHIFT + 1).
        Holding CAPS+SYM SHIFT together is "extended mode" on a Spectrum, not
        "!", so when a SYM-SHIFT symbol chord is active we drop the CAPS SHIFT
        that came only from the bare physical Shift key.
        """
        matrix_keys: set[str] = set()
        symbol_chord_active = False
        caps_from_bare_shift = False

        for qt_key in self._held_keys.values():
            chord = _CHORD_KEY_MAP.get(qt_key)
            if chord is not None:
                matrix_keys.update(chord)
                if "SYM SHIFT" in chord:
                    symbol_chord_active = True
                continue
            single = _SINGLE_KEY_MAP.get(qt_key)
            if single is not None:
                matrix_keys.add(single)
                if qt_key == Qt.Key_Shift:
                    caps_from_bare_shift = True

        if symbol_chord_active and caps_from_bare_shift:
            matrix_keys.discard("CAPS SHIFT")

        self.machine.keyboard.release_all()
        for name in matrix_keys:
            self.machine.keyboard.press(name)
