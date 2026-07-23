"""SoundMixer: sums the machine's sound sources into one PCM stream.

What this stands for in hardware
--------------------------------
There is no "mixer chip" in a ZX Spectrum. On a 128K the AY's three channel pins
and the ULA's beeper line each reach a common node through their own resistor, and
the voltages simply *add* there -- that summed signal drives the internal speaker
(and the tape and monitor outputs). Mixing is a property of the wiring, not a
component.

This class is the software stand-in for that resistor network, which is why it is
deliberately source-agnostic: it knows nothing about beepers or sound chips, only
that it has a list of things which produce samples. Relative loudness, which on real
hardware falls out of the resistor values, is here just each source's own ``volume``.

The source contract
-------------------
A "sound source" is anything exposing three members:

    source.enabled                  # bool, settable -- off means it costs nothing
    source.end_frame(frame_tstates) # render one 50Hz frame into an internal queue
    source.take_samples()           # drain and return that queue

:class:`~zxemu_core.beeper.Beeper` and :class:`~zxemu_core.ay.AY8912` each implement
exactly that and nothing more, so neither has any idea the other exists. A 48K
machine registers one source, a 128K registers two, and nothing else in the codebase
has to care which -- ``machine.audio`` is always a mixer, and the UI drives *it*
rather than any individual voice.

That is the payoff for keeping this separate: adding a future source (a second AY,
say, or the tape's own audible replay) means writing those three members and calling
``add_source``, with no edit here and none in the beeper.
"""

from __future__ import annotations


class SoundMixer:
    """Sums several sound sources into the single PCM stream the audio backend plays.

    Holds an ordered list of sources and, each frame, adds their outputs
    sample-for-sample. The machine exposes it as ``machine.audio``.
    """

    def __init__(self, sample_rate: int = 44100, frame_rate: int = 50):
        self.sample_rate = sample_rate
        self.frame_rate = frame_rate
        self.sources: list = []

    def add_source(self, source) -> None:
        """Register a sound source (must expose enabled / end_frame / take_samples)."""
        self.sources.append(source)

    @property
    def enabled(self) -> bool:
        """True if audio is on. Sources are muted/unmuted together (see the setter)."""
        return any(source.enabled for source in self.sources)

    @enabled.setter
    def enabled(self, value: bool) -> None:
        # One switch for the whole machine: pause/debug mutes every voice at once, and
        # each source clears its own transient state on the transition (no stale burst).
        for source in self.sources:
            source.enabled = value

    def end_frame(self, frame_tstates: int) -> None:
        """Render this frame on every source (each queues its own samples)."""
        for source in self.sources:
            source.end_frame(frame_tstates)

    def take_samples(self) -> list[float]:
        """Drain every source and return their per-sample sum, clamped to [-1, 1].

        Sources emit the same number of samples per frame when enabled, so they line
        up; a shorter buffer is simply treated as trailing silence. The final clamp is
        a safety net against a mix that momentarily exceeds full scale -- with the
        beeper/AY volumes calibrated for headroom it should rarely engage. (Real
        hardware has no such clamp; it just distorts, which is the analogue equivalent.)
        """
        buffers = [source.take_samples() for source in self.sources]
        if not any(buffers):
            return []
        length = max(len(buffer) for buffer in buffers)
        mixed = [0.0] * length
        for buffer in buffers:
            for i, sample in enumerate(buffer):
                mixed[i] += sample
        return [1.0 if s > 1.0 else -1.0 if s < -1.0 else s for s in mixed]
