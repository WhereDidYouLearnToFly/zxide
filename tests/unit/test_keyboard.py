from zxemu_core.keyboard import Keyboard


def test_all_released_reads_all_ones():
    kb = Keyboard()
    assert kb.read(0xFEFE) == 0x1F


def test_press_clears_the_correct_bit_in_its_row():
    kb = Keyboard()
    kb.press("Z")  # row 0, bit 1
    assert kb.read(0xFEFE) == 0b11101


def test_press_does_not_affect_other_rows():
    kb = Keyboard()
    kb.press("Z")  # row 0
    assert kb.read(0xFDFE) == 0x1F  # row 1 (A,S,D,F,G) untouched


def test_release_restores_the_bit():
    kb = Keyboard()
    kb.press("Z")
    kb.release("Z")
    assert kb.read(0xFEFE) == 0x1F


def test_release_all_clears_every_row():
    kb = Keyboard()
    kb.press("Z")
    kb.press("ENTER")
    kb.release_all()
    assert kb.read(0xFEFE) == 0x1F
    assert kb.read(0xBFFE) == 0x1F


def test_reading_with_multiple_address_lines_low_ands_rows_together():
    kb = Keyboard()
    kb.press("CAPS SHIFT")  # row 0, bit 0
    kb.press("A")  # row 1, bit 0
    # high byte 0xFC = 0b11111100 -> bits 0 and 1 both low -> rows 0 and 1 combined
    assert kb.read(0xFCFE) == 0b11110


def test_all_eight_rows_combined_when_full_high_byte_is_zero():
    kb = Keyboard()
    kb.press("SPACE")  # row 7, bit 0
    assert kb.read(0x00FE) == 0b11110


def test_known_row_layout_matches_spectrum_keyboard():
    kb = Keyboard()
    kb.press("ENTER")
    assert kb.read(0xBFFE) == 0b11110  # row 6, bit 0
    kb.press("1")
    assert kb.read(0xF7FE) == 0b11110  # row 3, bit 0
