"""Render a beeper_sfx tone/duration sequence to PCM, without any live machine.

A ``beeper_sfx`` asset (``zxemu_core.assets.beeper_sfx``) is exactly the same kind of
input the real :class:`~zxemu_core.sound.beeper.Beeper` already knows how to turn into
samples -- timestamped speaker flips -- so previewing one is just driving a standalone
``Beeper`` with a synthetic flip schedule instead of a running CPU, the same "one
frame at a time" contract the machine itself uses.
"""

from __future__ import annotations

from zxemu_core.sound.beeper import Beeper

FRAME_TSTATES = 69888  # one 50Hz frame, matching Machine.run_frame


def render_tone_sequence(entries: list[tuple[int, int]], sample_rate: int = 44100) -> list[float]:
    """``(period_tstates, duration_frames)`` pairs -> PCM samples, via a real ``Beeper``.

    ``period`` is the T-states between speaker flips (so the audible tone is roughly
    ``3500000 / (2 * period)`` Hz); a period of 0 is a rest -- silence for that entry's
    duration, since a period-0 "flip every 0 T-states" has no meaningful waveform.
    Phase carries across entries (no click at the joins), matching how a real tone
    routine would chain notes without re-zeroing the speaker between them.
    """
    beeper = Beeper(sample_rate)
    beeper.enabled = True
    samples: list[float] = []
    absolute_t = 0
    level = 0
    next_flip: int | None = None

    for period, duration_frames in entries:
        if period <= 0:
            for _ in range(duration_frames):
                beeper.end_frame(FRAME_TSTATES)
                samples.extend(beeper.take_samples())
                absolute_t += FRAME_TSTATES
            next_flip = None  # a rest breaks phase continuity; the next tone starts fresh
            continue
        if next_flip is None:
            next_flip = absolute_t + period
        for _ in range(duration_frames):
            frame_end = absolute_t + FRAME_TSTATES
            while next_flip < frame_end:
                level ^= 1
                beeper.set_level(next_flip - absolute_t, level)
                next_flip += period
            beeper.end_frame(FRAME_TSTATES)
            samples.extend(beeper.take_samples())
            absolute_t = frame_end

    return samples
