from zxemu_core.ula import (
    CONTENDED_WINDOW_TSTATES,
    FRAME_TSTATES,
    LINE_TSTATES,
    SCREEN_LINES,
    SCREEN_START_TSTATE,
    Ula,
    contention_delay,
)


def test_frame_tstates_matches_48k_pal_budget():
    assert FRAME_TSTATES == 69888
    assert FRAME_TSTATES == 312 * LINE_TSTATES


def test_no_contention_before_screen_area_starts():
    assert contention_delay(0) == 0
    assert contention_delay(SCREEN_START_TSTATE - 1) == 0


def test_contention_pattern_at_start_of_first_screen_line():
    base = SCREEN_START_TSTATE
    expected = [6, 5, 4, 3, 2, 1, 0, 0]
    actual = [contention_delay(base + i) for i in range(8)]
    assert actual == expected


def test_contention_pattern_repeats_within_fetch_window():
    base = SCREEN_START_TSTATE + 64  # still within the 128 T-state fetch window
    assert contention_delay(base) == 6
    assert contention_delay(base + 7) == 0


def test_no_contention_in_line_tail_after_fetch_window():
    base = SCREEN_START_TSTATE + CONTENDED_WINDOW_TSTATES
    assert contention_delay(base) == 0
    assert contention_delay(base + LINE_TSTATES - CONTENDED_WINDOW_TSTATES - 1) == 0


def test_no_contention_on_second_screen_line_tail_but_present_at_its_start():
    line1_start = SCREEN_START_TSTATE + LINE_TSTATES
    assert contention_delay(line1_start) == 6
    assert contention_delay(line1_start + CONTENDED_WINDOW_TSTATES) == 0


def test_no_contention_after_last_screen_line():
    after_screen = SCREEN_START_TSTATE + SCREEN_LINES * LINE_TSTATES
    assert contention_delay(after_screen) == 0
    assert contention_delay(FRAME_TSTATES - 1) == 0


def test_contention_wraps_across_frame_boundary():
    assert contention_delay(FRAME_TSTATES + SCREEN_START_TSTATE) == contention_delay(SCREEN_START_TSTATE)


def test_ula_write_port_sets_border_color_masked_to_3_bits():
    ula = Ula()
    ula.write_port(0xFE, 0xFF)
    assert ula.border_color == 0x07


def test_ula_write_port_ignores_odd_ports():
    ula = Ula()
    ula.border_color = 3
    ula.write_port(0xFF, 0x05)
    assert ula.border_color == 3


def test_ula_read_port_with_no_keyboard_reads_all_released():
    ula = Ula()
    assert ula.read_port(0xFE) == 0xFF


def test_ula_read_port_combines_keyboard_row_bits():
    class FakeKeyboard:
        def read(self, port: int) -> int:
            return 0b11110  # bit 0 "pressed" (low)

    ula = Ula(keyboard=FakeKeyboard())
    assert ula.read_port(0xFE) == 0xFE  # 0xE0 | 0b11110


def test_ula_read_port_odd_port_is_floating_bus_stub():
    ula = Ula()
    assert ula.read_port(0xFF) == 0xFF
