"""Beeper: the Spectrum's 1-bit sound, turned into PCM audio samples.

The 48K Spectrum makes sound with a *single bit*. Port 0xFE bit 4 pushes the
speaker cone in or out; there is no volume control, no waveform generator,
nothing else. Every note, every explosion, every bar of in-game music is the CPU
*flipping that one bit* on a carefully timed schedule -- toggle it 440 times a
second and you hear a concert A. All the "information" in beeper sound therefore
lives in the *timing* of the flips, which is exactly why this module cares so
much about *when* each flip happened (its T-state within the frame) and not just
the value.

`Beeper` is the audio-output pipeline's first stage and is deliberately UI- and
toolkit-agnostic: it consumes timestamped 1-bit level changes and produces plain
floating-point PCM samples in [-1.0, 1.0]. A UI layer feeds those to a real sound
device; when the 128K's AY chip arrives it will mix into this same sample stream.

How a 1-bit square wave becomes samples
---------------------------------------
Within one 50Hz frame the speaker level is a piecewise-constant signal: it holds
a value, flips at some T-state, holds again, and so on. To turn that into audio
at, say, 44100 Hz we split the frame into a fixed number of equal time buckets --
882 of them at 44100 Hz -- and set each output sample to the *time-weighted
average* level across its bucket. That average is simply the fraction of the
bucket during which the speaker was high (its duty cycle); averaging box-filters
the signal and tames the worst of the aliasing a raw square wave would cause.

A held (unchanging) level averages to a constant -- a DC offset. A real speaker
is AC-coupled and cannot reproduce DC: hold the bit steady and you hear silence,
not a click that lasts forever. We mirror that with a one-pole DC blocker on the
output, so a static level decays to silence just as the hardware does.
"""

from __future__ import annotations


class Beeper:
    """Converts timestamped 1-bit speaker flips into floating-point PCM samples.

    Driven by the :class:`~zxemu_core.machine.Machine`, one frame at a time::

        beeper.set_level(t_state, level)   # whenever port 0xFE bit 4 changes
        beeper.end_frame(frame_tstates)    # once per emulated 50Hz frame
        samples = beeper.take_samples()    # drained by the audio backend

    Samples are mono floats in [-1.0, 1.0]. Audio is opt-in via :attr:`enabled`
    so a headless or test run pays nothing: while disabled, flips and frames are
    ignored and no samples accumulate.
    """

    def __init__(self, sample_rate: int = 44100, frame_rate: int = 50, volume: float = 0.25):
        # We emit a whole number of samples per frame; every common rate (44100,
        # 48000, 22050) divides 50 exactly, so we require it rather than carry a
        # fractional-sample remainder between frames.
        if sample_rate % frame_rate != 0:
            raise ValueError(
                f"sample_rate ({sample_rate}) must be a whole multiple of frame_rate ({frame_rate})"
            )
        self.sample_rate = sample_rate
        self.samples_per_frame = sample_rate // frame_rate
        self.volume = volume
        self._enabled = False

        # Signal state that must persist across frame boundaries.
        self._level = 0  # current speaker level (0/1), carried into the next frame
        self._edges: list[tuple[int, int]] = []  # (t_state, new_level) recorded this frame

        # One-pole DC blocker state (see module docstring). The pole sits just
        # inside the unit circle: close to 1 keeps bass, far from 1 kills DC fast.
        self._dc_prev_in = 0.0
        self._dc_prev_out = 0.0
        self._dc_pole = 0.995

        # Finished samples awaiting the audio backend, capped so a buffer that is
        # never drained (no sound device present) can't grow without bound.
        self._buffer: list[float] = []
        self._max_buffered = sample_rate  # ~1 second of slack

    @property
    def enabled(self) -> bool:
        """Whether audio is being produced. Toggling clears transient state.

        Flushing edges, the pending sample buffer, and the DC-blocker history on
        every on/off transition means switching audio back on never replays a
        stale burst, and switching it off (e.g. while paused at a breakpoint)
        can't let recorded-but-never-rendered flips pile up.
        """
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        value = bool(value)
        if value != self._enabled:
            self._edges.clear()
            self._buffer.clear()
            self._level = 0
            self._dc_prev_in = 0.0
            self._dc_prev_out = 0.0
        self._enabled = value

    def set_level(self, t_state: int, level: int) -> None:
        """Record that the speaker bit changed to ``level`` at ``t_state`` in this frame."""
        if self._enabled:
            self._edges.append((t_state, level & 0x01))

    def end_frame(self, frame_tstates: int) -> None:
        """Resample this frame's 1-bit waveform to PCM and queue the samples."""
        if not self._enabled:
            self._edges.clear()
            return
        self._buffer.extend(self._render_frame(frame_tstates))
        if len(self._buffer) > self._max_buffered:
            # Drop the oldest overflow -- a brief glitch beats unbounded memory.
            del self._buffer[: len(self._buffer) - self._max_buffered]
        self._edges.clear()

    def take_samples(self) -> list[float]:
        """Return all queued samples and clear the queue (called by the audio backend)."""
        out = self._buffer
        self._buffer = []
        return out

    # --- internals ------------------------------------------------------------

    def _render_frame(self, frame_tstates: int) -> list[float]:
        """Turn this frame's held levels + flips into ``samples_per_frame`` PCM samples."""
        n = self.samples_per_frame
        bucket_width = frame_tstates / n
        # For each output bucket, the total T-states the speaker spent *high*.
        high_tstates = [0.0] * n

        cursor = 0
        level = self._level
        # A sentinel segment carries the final level out to the frame's end, so the
        # last real span is accounted for without special-casing the loop tail.
        for edge_t, new_level in (*self._edges, (frame_tstates, level)):
            end = edge_t if edge_t < frame_tstates else frame_tstates
            if end > cursor:
                if level:  # only 'high' spans contribute to the duty cycle
                    self._add_high_span(high_tstates, cursor, end, bucket_width, n)
                cursor = end
            level = new_level
        self._level = level  # hold the final level into the next frame

        samples = []
        for high in high_tstates:
            duty = high / bucket_width        # fraction of the bucket spent high, in [0, 1]
            centered = duty * 2.0 - 1.0       # map to a [-1, 1] swing
            samples.append(self._dc_block(centered) * self.volume)
        return samples

    @staticmethod
    def _add_high_span(high_tstates, start, end, bucket_width, n) -> None:
        """Distribute a 'high' span [start, end) across the buckets it overlaps."""
        first = max(int(start / bucket_width), 0)
        last = min(int((end - 1e-9) / bucket_width), n - 1)
        for i in range(first, last + 1):
            bucket_start = i * bucket_width
            overlap = min(end, bucket_start + bucket_width) - max(start, bucket_start)
            if overlap > 0:
                high_tstates[i] += overlap

    def _dc_block(self, x: float) -> float:
        """One-pole DC blocker: y[n] = x[n] - x[n-1] + pole*y[n-1].

        Removes the constant component so a steady speaker level fades to silence,
        the way an AC-coupled speaker physically does.
        """
        y = x - self._dc_prev_in + self._dc_pole * self._dc_prev_out
        self._dc_prev_in = x
        self._dc_prev_out = y
        return y


class SoundMixer:
    """Sums several sound sources into the single PCM stream the audio backend plays.

    A 48K Spectrum has one voice (the beeper); a 128K adds the AY sound chip. Both
    are "sources" that speak the same tiny contract -- an ``enabled`` flag, an
    ``end_frame(frame_tstates)`` that renders one frame, and a ``take_samples()``
    that drains the rendered PCM. The mixer holds an ordered list of them and, each
    frame, adds their outputs sample-for-sample.

    Keeping the mixer separate from the sources means the ``Beeper`` stays completely
    unaware of the AY -- the 48K machine reuses it verbatim -- and the summing lives
    in one small, testable place. The machine exposes the mixer as ``machine.audio``;
    the controller drives *that* rather than any individual source.
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
        beeper/AY volumes calibrated for headroom it should rarely engage.
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
