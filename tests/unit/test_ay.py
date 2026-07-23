"""Tests for the AY-3-8912 sound chip (zxemu_core.ay) and its mixing."""

from __future__ import annotations

import math

import pytest

from zxemu_core.beeper import Beeper
from zxemu_core.mixer import SoundMixer
from zxemu_core.ay import AY8912

FRAME_128 = 70908  # one 128K frame, matching Machine128


def rms(samples) -> float:
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


def write_reg(ay: AY8912, reg: int, value: int, t: int = 0) -> None:
    ay.select_register(reg)
    ay.write_selected(t, value)


def render(ay: AY8912, frames: int) -> list[float]:
    out: list[float] = []
    for _ in range(frames):
        ay.end_frame(FRAME_128)
        out.extend(ay.take_samples())
    return out


def positive_crossings(samples) -> int:
    """Count rising zero-crossings -- one per waveform period."""
    return sum(1 for a, b in zip(samples, samples[1:]) if a <= 0.0 < b)


def test_rejects_sample_rate_not_divisible_by_frame_rate():
    with pytest.raises(ValueError):
        AY8912(sample_rate=44101, frame_rate=50)


def test_register_writes_are_masked_and_readable():
    ay = AY8912()
    write_reg(ay, 1, 0xFF)  # tone coarse: 4-bit
    ay.select_register(1)
    assert ay.read_selected() == 0x0F
    write_reg(ay, 6, 0xFF)  # noise period: 5-bit
    ay.select_register(6)
    assert ay.read_selected() == 0x1F
    ay.select_register(0x1F)  # register index itself is 4-bit
    assert ay.read_selected() == ay._reg[15]


def test_disabled_ay_produces_no_samples():
    ay = AY8912()  # enabled defaults False
    write_reg(ay, 8, 15)
    ay.end_frame(FRAME_128)
    assert ay.take_samples() == []


def test_one_frame_yields_samples_per_frame():
    ay = AY8912(sample_rate=44100, frame_rate=50)
    ay.enabled = True
    ay.end_frame(FRAME_128)
    assert len(ay.take_samples()) == 882


def test_tone_period_gives_expected_frequency():
    ay = AY8912()
    ay.enabled = True
    write_reg(ay, 0, 0xFC)          # TP low
    write_reg(ay, 1, 0x00)          # TP high -> TP = 0x00FC = 252 ~ 440 Hz
    write_reg(ay, 7, 0b00111110)    # mixer: enable tone A only (0 = on)
    write_reg(ay, 8, 15)            # channel A full volume
    samples = render(ay, 20)
    freq = positive_crossings(samples) / (20 / 50)  # crossings per second
    assert 380 <= freq <= 500       # ~440 Hz


def test_higher_period_lowers_frequency():
    def tone_freq(tp: int) -> float:
        ay = AY8912()
        ay.enabled = True
        write_reg(ay, 0, tp & 0xFF)
        write_reg(ay, 1, (tp >> 8) & 0x0F)
        write_reg(ay, 7, 0b00111110)
        write_reg(ay, 8, 15)
        return positive_crossings(render(ay, 20)) / (20 / 50)

    assert tone_freq(504) < tone_freq(252) * 0.7  # ~half the pitch


def test_zero_volume_is_silent():
    ay = AY8912()
    ay.enabled = True
    write_reg(ay, 0, 0xFC)
    write_reg(ay, 7, 0b00111110)
    write_reg(ay, 8, 0)  # volume 0
    assert rms(render(ay, 8)) < 1e-6


def test_continuous_envelope_sustains_but_oneshot_decays():
    def envelope_run(shape: int) -> list[float]:
        ay = AY8912()
        ay.enabled = True
        write_reg(ay, 7, 0b00111111)   # disable tone+noise on A -> raw level passthrough
        write_reg(ay, 8, 0x10)         # channel A follows the envelope (bit 4)
        write_reg(ay, 11, 0x01)        # envelope period low = fast ramps
        write_reg(ay, 12, 0x00)
        write_reg(ay, 13, shape)       # writing the shape (re)starts the envelope
        return render(ay, 30)

    saw = envelope_run(0x0C)    # continue+attack, no hold -> repeating ramp
    oneshot = envelope_run(0x00)  # decay once then silence
    assert rms(saw[-882 * 5:]) > 0.02          # still going near the end
    assert rms(oneshot[-882 * 5:]) < rms(oneshot[:882 * 5]) * 0.1  # faded out


def test_noise_is_audible_and_deterministic():
    def noise_run() -> list[float]:
        ay = AY8912()
        ay.enabled = True
        write_reg(ay, 6, 0x01)         # fast noise
        write_reg(ay, 7, 0b00110111)   # enable noise A only
        write_reg(ay, 8, 15)
        return render(ay, 10)

    first = noise_run()
    assert rms(first) > 0.02           # broadband hiss, clearly non-silent
    assert noise_run() == first        # LFSR seeded deterministically


def test_mixer_sums_sources_within_range():
    beeper = Beeper()
    ay = AY8912()
    mixer = SoundMixer()
    mixer.add_source(beeper)
    mixer.add_source(ay)
    mixer.enabled = True

    # A loud AY tone plus a beeper square wave, driven together for several frames.
    write_reg(ay, 0, 0x80)
    write_reg(ay, 7, 0b00111110)
    write_reg(ay, 8, 15)
    mixed_rms = []
    for frame in range(10):
        level = 0
        t = 0
        while t < FRAME_128:  # a beeper square wave this frame
            level ^= 1
            beeper.set_level(t, level)
            t += FRAME_128 // 40
        mixer.end_frame(FRAME_128)
        chunk = mixer.take_samples()
        assert all(-1.0 <= s <= 1.0 for s in chunk)  # clamp holds
        mixed_rms.append(rms(chunk))

    # Removing the AY leaves only the (quieter) beeper -> lower RMS: they truly mix.
    beeper_only = SoundMixer()
    beeper_only.add_source(Beeper())
    beeper_only.enabled = True
    b = beeper_only.sources[0]
    level, t = 0, 0
    while t < FRAME_128:
        level ^= 1
        b.set_level(t, level)
        t += FRAME_128 // 40
    beeper_only.end_frame(FRAME_128)
    assert rms(beeper_only.take_samples()) < max(mixed_rms)


def test_take_samples_clears_the_queue():
    ay = AY8912()
    ay.enabled = True
    ay.end_frame(FRAME_128)
    assert ay.take_samples()
    assert ay.take_samples() == []
