"""Tests for the 1-bit beeper's edge-list -> PCM resampling (zxemu_core.audio)."""

from __future__ import annotations

import math

import pytest

from zxemu_core.audio import Beeper

FRAME_TSTATES = 69888  # one 50Hz frame, matching the Machine


def rms(samples) -> float:
    """Root-mean-square level -- a simple 'how loud is this' measure."""
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


def render_tone(beeper: Beeper, half_period_tstates: int, frames: int) -> list[float]:
    """Drive a steady square wave for ``frames`` frames and collect every sample.

    The speaker is flipped every ``half_period_tstates`` T-states, with the phase
    carried continuously across frame boundaries, mimicking a CPU tone loop.
    """
    samples: list[float] = []
    absolute_t = 0
    level = 0
    next_flip = half_period_tstates
    for _frame in range(frames):
        frame_end = absolute_t + FRAME_TSTATES
        while next_flip < frame_end:
            level ^= 1
            beeper.set_level(next_flip - absolute_t, level)  # t-state within this frame
            next_flip += half_period_tstates
        beeper.end_frame(FRAME_TSTATES)
        absolute_t = frame_end
        samples.extend(beeper.take_samples())
    return samples


def test_rejects_sample_rate_not_divisible_by_frame_rate():
    with pytest.raises(ValueError):
        Beeper(sample_rate=44101, frame_rate=50)


def test_disabled_beeper_produces_no_samples():
    beeper = Beeper()  # enabled defaults to False
    beeper.set_level(0, 1)
    beeper.set_level(1000, 0)
    beeper.end_frame(FRAME_TSTATES)
    assert beeper.take_samples() == []


def test_one_frame_yields_exactly_samples_per_frame():
    beeper = Beeper(sample_rate=44100, frame_rate=50)
    beeper.enabled = True
    beeper.end_frame(FRAME_TSTATES)
    assert len(beeper.take_samples()) == 882  # 44100 / 50


def test_square_wave_is_audible():
    """A steady tone should produce a clearly non-silent signal."""
    beeper = Beeper(sample_rate=44100, frame_rate=50)
    beeper.enabled = True
    # ~1 kHz: one full cycle per millisecond -> half-period ~ FRAME/40.
    samples = render_tone(beeper, half_period_tstates=FRAME_TSTATES // 40, frames=10)
    assert rms(samples) > 0.05


def test_held_level_decays_to_silence():
    """A speaker held high (no flips) must fade out -- the DC blocker at work."""
    beeper = Beeper(sample_rate=44100, frame_rate=50)
    beeper.enabled = True
    beeper.set_level(0, 1)  # drive high once, then never flip again
    early = []
    late = []
    for frame in range(60):  # ~1.2 seconds
        beeper.end_frame(FRAME_TSTATES)
        chunk = beeper.take_samples()
        if frame < 3:
            early.extend(chunk)
        elif frame >= 57:
            late.extend(chunk)
    assert rms(late) < rms(early) * 0.1  # tail is far quieter than the onset


def test_samples_stay_in_range():
    beeper = Beeper(sample_rate=44100, frame_rate=50, volume=0.25)
    beeper.enabled = True
    samples = render_tone(beeper, half_period_tstates=FRAME_TSTATES // 40, frames=10)
    assert all(-1.0 <= s <= 1.0 for s in samples)


def test_take_samples_clears_the_queue():
    beeper = Beeper()
    beeper.enabled = True
    beeper.end_frame(FRAME_TSTATES)
    assert beeper.take_samples()  # non-empty
    assert beeper.take_samples() == []  # drained
