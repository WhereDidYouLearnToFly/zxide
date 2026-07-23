"""Tests for standalone beeper_sfx playback rendering (zxemu_core.sound.beeper_preview)."""

from __future__ import annotations

from zxemu_core.sound.beeper_preview import FRAME_TSTATES, render_tone_sequence


def test_render_tone_sequence_produces_samples_per_frame():
    samples = render_tone_sequence([(100, 2)], sample_rate=44100)
    assert len(samples) == 2 * (44100 // 50)  # 2 frames' worth


def test_render_tone_sequence_rest_decays_to_silence():
    # A steady (held, unflipped) level isn't instantly 0.0 sample-by-sample -- the DC
    # blocker converges toward silence rather than snapping to it (see beeper.py's own
    # docstring) -- so check convergence, not an exact 0.0 from the very first sample.
    samples = render_tone_sequence([(0, 4)], sample_rate=44100)
    assert len(samples) == 4 * (44100 // 50)
    assert abs(samples[-1]) < 1e-3


def test_render_tone_sequence_tone_is_not_silent():
    samples = render_tone_sequence([(100, 2)], sample_rate=44100)
    assert any(s != 0.0 for s in samples)


def test_render_tone_sequence_multiple_entries_concatenate():
    one_entry = render_tone_sequence([(200, 3)], sample_rate=44100)
    two_entries = render_tone_sequence([(200, 3), (400, 2)], sample_rate=44100)
    assert len(two_entries) == len(one_entry) + 2 * (44100 // 50)


def test_render_tone_sequence_empty_list_is_empty():
    assert render_tone_sequence([], sample_rate=44100) == []


def test_frame_tstates_matches_a_real_50hz_frame():
    assert FRAME_TSTATES == 69888
