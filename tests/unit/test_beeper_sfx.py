"""Tests for the beeper SFX text->binary converter (zxemu_core.assets.beeper_sfx)."""

from __future__ import annotations

import pytest

from zxemu_core.assets.beeper_sfx import (
    SUFFIX,
    convert_beeper_sfx,
    format_beeper_sfx,
    hz_to_period,
    parse_beeper_sfx,
    period_to_hz,
)


def test_parses_pairs_ignoring_comments_and_blank_lines():
    text = """
    # a comment
    440,4
    220,8  # trailing comment ok too

    110,2
    """
    assert parse_beeper_sfx(text) == [(440, 4), (220, 8), (110, 2)]


def test_convert_emits_entry_bytes_plus_sentinel():
    data = convert_beeper_sfx("256,10\n")
    assert data == (256).to_bytes(2, "little") + bytes([10]) + b"\xff\xff\x00"


def test_convert_empty_table_is_just_the_sentinel():
    assert convert_beeper_sfx("") == b"\xff\xff\x00"


def test_rejects_period_out_of_range():
    with pytest.raises(ValueError, match="period"):
        parse_beeper_sfx("70000,4")


def test_rejects_duration_out_of_range():
    with pytest.raises(ValueError, match="duration"):
        parse_beeper_sfx("100,300")


def test_rejects_malformed_line():
    with pytest.raises(ValueError, match="expected"):
        parse_beeper_sfx("just one number")


def test_suffix_is_zx_prefixed():
    assert SUFFIX == ".zxsfx"


def test_period_to_hz_of_a_rest_is_zero():
    assert period_to_hz(0) == 0.0


def test_hz_to_period_of_a_rest_is_zero():
    assert hz_to_period(0) == 0
    assert hz_to_period(-10) == 0


def test_hz_and_period_round_trip_approximately():
    period = hz_to_period(440.0)
    assert abs(period_to_hz(period) - 440.0) < 1.0  # within 1 Hz, limited by integer T-state periods


def test_hz_to_period_is_clamped_to_valid_range():
    assert hz_to_period(1_000_000) >= 1  # absurdly high frequency still yields a valid period


def test_format_beeper_sfx_is_the_inverse_of_parse():
    entries = [(3977, 4), (0, 2), (1989, 10)]
    assert parse_beeper_sfx(format_beeper_sfx(entries)) == entries


def test_format_beeper_sfx_empty_list_is_empty_text():
    assert format_beeper_sfx([]) == ""
