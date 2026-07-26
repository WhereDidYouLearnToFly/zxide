"""Tests for the beeper SFX text->binary converter (zxemu_core.assets.beeper_sfx)."""

from __future__ import annotations

import math

import pytest

from zxemu_core.assets.beeper_sfx import (
    MAX_DURATION,
    SUFFIX,
    convert_beeper_sfx,
    expand_to_frames,
    format_beeper_sfx,
    hz_to_period,
    pack_frames,
    parse_beeper_sfx,
    period_to_hz,
    table_size,
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


@pytest.mark.parametrize("text", ["", "256,10\n", "256,10\n0,5\n1000,255\n"])
def test_table_size_is_what_the_converter_actually_emits(text):
    """The editor quotes this number, so it must be measured against the real output."""
    assert table_size(parse_beeper_sfx(text)) == len(convert_beeper_sfx(text))


def test_an_empty_effect_still_costs_the_sentinel():
    assert table_size([]) == 3


def test_a_held_tone_costs_the_same_as_a_short_one():
    """One entry is one entry: the size follows the shape, not the duration."""
    assert table_size([(400, 1)]) == table_size([(400, 200)])


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


# --- frequency round-trips ---------------------------------------------------------------


@pytest.mark.parametrize("hz", [40, 110, 440, 1000, 2500, 4000])
def test_a_frequency_survives_the_trip_through_a_period(hz):
    """The editor stores what you drew as a period, and draws the bar back from it.

    A period is a whole number of T-states, so the round trip is lossy. The error is
    stated in *cents* rather than as a percentage because that is the unit that says
    whether it matters: pitch discrimination runs out around 5 cents, and the worst case
    here -- the top of the range, where a period is only a few hundred T-states -- is
    about 2. Expressed as a percentage the same error is 0.11%, which is small but is
    *not* the "well under a tenth of a percent" it would be easy to assume.
    """
    error_cents = abs(1200 * math.log2(period_to_hz(hz_to_period(hz)) / hz))
    assert error_cents < 3


def test_the_worst_rounding_error_in_the_range_is_still_inaudible():
    """Swept across the whole usable range, not just at the round numbers above."""
    worst = max(
        abs(1200 * math.log2(period_to_hz(hz_to_period(hz)) / hz))
        for hz in range(32, 4097, 8)
    )
    assert worst < 3, f"worst tuning error is {worst:.2f} cents"


# --- entries <-> a per-frame pitch track ---------------------------------------------


def test_expand_repeats_each_entry_for_its_duration():
    assert expand_to_frames([(100, 3), (0, 2)]) == [100, 100, 100, 0, 0]


def test_expand_of_an_empty_table_is_an_empty_track():
    assert expand_to_frames([]) == []


def test_pack_run_length_codes_identical_columns():
    assert pack_frames([100, 100, 100, 200]) == [(100, 3), (200, 1)]


def test_pack_keeps_rests_that_sit_between_tones():
    assert pack_frames([100, 0, 0, 200]) == [(100, 1), (0, 2), (200, 1)]


def test_pack_drops_trailing_silence():
    assert pack_frames([100, 0, 0, 0]) == [(100, 1)]


def test_pack_of_pure_silence_is_an_empty_table():
    assert pack_frames([0, 0, 0]) == []


def test_pack_splits_a_run_longer_than_a_duration_byte():
    entries = pack_frames([100] * 300)
    assert entries == [(100, MAX_DURATION), (100, 300 - MAX_DURATION)]
    assert sum(duration for _period, duration in entries) == 300


def test_expand_and_pack_round_trip():
    entries = [(3977, 4), (0, 2), (1989, 10)]
    assert pack_frames(expand_to_frames(entries)) == entries


def test_pack_does_not_mutate_its_input():
    frames = [100, 0, 0]
    pack_frames(frames)
    assert frames == [100, 0, 0]
