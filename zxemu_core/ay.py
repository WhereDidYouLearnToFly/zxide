"""AY-3-8912: the 128K Spectrum's 3-voice sound chip, rendered to PCM.

Where the 48K beeper is one bit the CPU wiggles by hand, the 128K adds a General
Instrument AY-3-8912 -- a real synthesiser the CPU only has to *configure*. It has:

* **three square-wave tone generators** (channels A/B/C), each with a 12-bit period;
* **one noise generator** (a pseudo-random bit stream from a 17-bit shift register);
* **one envelope generator** (a shared volume shape with 10 distinct patterns);
* a **mixer** deciding, per channel, whether tone and/or noise are heard;
* per-channel **volume**, either a fixed 4-bit level or "follow the envelope".

The chip is driven through 16 registers, written via two IO ports (0xFFFD selects a
register, 0xBFFD writes it). All the musicality lives in those register values and
*when* they change -- so, exactly like the :class:`~zxemu_core.audio.Beeper`, this
class records register writes stamped with their frame T-state and renders the whole
frame at once, keeping the AY and beeper aligned sample-for-sample in the mixer.

Why a logarithmic volume table? The AY's output stage is a resistor ladder whose
steps are spaced roughly -3 dB apart, so equal register steps sound like equal
*loudness* changes. A linear table would make the low levels almost inaudible and
the top few dominate; the measured 16-entry table below reproduces the real curve.

Behaviour (register semantics, envelope shapes, noise taps, clock divisors, the
amplitude curve) was cross-checked against the Fuse emulator's AY handling as a
reference only -- this is an independent implementation, not a port.
"""

from __future__ import annotations

# The AY on a 128K is clocked at half the 3.5469 MHz CPU clock.
AY_CLOCK_HZ = 1_773_400
AY_REGISTERS = 16

# Per-register write masks: bits that don't exist read back as 0. R1/R3/R5 (tone
# coarse) and R13 (envelope shape) are 4-bit; R6 (noise) and R8-R10 (volume) 5-bit.
REG_MASKS = (0xFF, 0x0F, 0xFF, 0x0F, 0xFF, 0x0F, 0x1F, 0xFF,
             0x1F, 0x1F, 0x1F, 0xFF, 0xFF, 0x0F, 0xFF, 0xFF)

# Measured logarithmic output levels (comp.sys.sinclair, 2001), normalised to [0,1].
AMPLITUDE_TABLE = tuple(level / 0xFFFF for level in (
    0x0000, 0x0385, 0x053D, 0x0770, 0x0AD7, 0x0FD5, 0x15B0, 0x230C,
    0x2B4C, 0x43C1, 0x5A4B, 0x732F, 0x9204, 0xAFF1, 0xD921, 0xFFFF))

# Envelope shape register (R13) bits.
ENV_HOLD = 0x01
ENV_ALT = 0x02
ENV_ATTACK = 0x04
ENV_CONT = 0x08

# One engine step = 16 AY clocks = 32 master T-states. At this granularity a tone
# gains two "half-period" ticks per step, so a full square wave spans 16*TP AY
# clocks -> f = AY_CLOCK / (16 * TP), the standard Spectrum tone formula (TP=252 ~ 440 Hz).
STEP_TSTATES = 32
TONE_TICKS_PER_STEP = 2


class AY8912:
    """An AY-3-8912 that turns timestamped register writes into mono float PCM.

    Mirrors :class:`~zxemu_core.audio.Beeper`: an ``enabled`` gate (off = free),
    ``end_frame(frame_tstates)`` renders one frame, ``take_samples()`` drains it.
    The register file is readable immediately (games poll it); the *audible* effect
    of a write is applied at its recorded T-state when the frame is rendered.
    """

    def __init__(self, sample_rate: int = 44100, frame_rate: int = 50, volume: float = 0.5):
        if sample_rate % frame_rate != 0:
            raise ValueError(
                f"sample_rate ({sample_rate}) must be a whole multiple of frame_rate ({frame_rate})"
            )
        self.sample_rate = sample_rate
        self.samples_per_frame = sample_rate // frame_rate
        self.volume = volume
        self._enabled = False

        self._selected = 0
        self._reg = [0] * AY_REGISTERS   # immediate, host-visible register file (for reads)
        self._writes: list[tuple[int, int, int]] = []  # (t_state, reg, value) recorded this frame

        # Output buffering + DC blocker, identical in spirit to the beeper's.
        self._buffer: list[float] = []
        self._max_buffered = sample_rate
        self._dc_prev_in = 0.0
        self._dc_prev_out = 0.0
        self._dc_pole = 0.995

        self._reset_engine()

    # --- enable gate ----------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """Whether the chip is producing audio. Toggling clears transient state."""
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        value = bool(value)
        if value != self._enabled:
            self._writes = []
            self._buffer = []
            self._dc_prev_in = 0.0
            self._dc_prev_out = 0.0
            self._reset_engine()
        self._enabled = value

    # --- register interface (called from Machine128 IO dispatch) --------------

    def select_register(self, reg: int) -> None:
        """Latch the register that the next read/write targets (port 0xFFFD)."""
        self._selected = reg & 0x0F

    def read_selected(self) -> int:
        """Return the currently selected register's value (IN from port 0xFFFD)."""
        return self._reg[self._selected]

    def write_selected(self, t_state: int, value: int) -> None:
        """Write the selected register (port 0xBFFD), stamped for frame rendering.

        The host-visible copy updates immediately so a subsequent read is correct;
        the value is also queued so the audio engine applies it at ``t_state`` when
        the frame is rendered (a note that changes mid-frame changes mid-frame).
        """
        reg = self._selected
        value &= REG_MASKS[reg]
        self._reg[reg] = value
        if self._enabled:
            self._writes.append((t_state, reg, value))

    # --- frame rendering ------------------------------------------------------

    def end_frame(self, frame_tstates: int) -> None:
        """Render this frame's sound to PCM and queue it; a no-op while disabled."""
        if not self._enabled:
            self._writes.clear()
            return
        n = self.samples_per_frame
        bucket_width = frame_tstates / n
        accum = [0.0] * n  # time-weighted sum of mixed amplitude per output bucket

        writes = self._writes
        count = len(writes)
        wi = 0
        t = 0
        while t < frame_tstates:
            while wi < count and writes[wi][0] <= t:  # apply writes that have come due
                self._apply_write(writes[wi][1], writes[wi][2])
                wi += 1
            level = self._engine_step()  # summed 3-channel amplitude, 0..1
            end = t + STEP_TSTATES
            if end > frame_tstates:
                end = frame_tstates
            if level:
                self._add_level_span(accum, t, end, level, bucket_width, n)
            t = end
        while wi < count:  # writes stamped at/after frame end carry into the next frame
            self._apply_write(writes[wi][1], writes[wi][2])
            wi += 1
        self._writes = []

        for a in accum:
            self._buffer.append(self._dc_block(a / bucket_width) * self.volume)
        if len(self._buffer) > self._max_buffered:
            del self._buffer[: len(self._buffer) - self._max_buffered]

    def take_samples(self) -> list[float]:
        """Return all queued samples and clear the queue (drained by the mixer)."""
        out = self._buffer
        self._buffer = []
        return out

    # --- engine ---------------------------------------------------------------

    def _reset_engine(self) -> None:
        """(Re)initialise the sound engine from the current register file.

        Re-derives the cached periods and clears the counters/LFSR/envelope. Called
        at construction and whenever ``enabled`` toggles, so the chip always starts
        a run coherent with its register values and free of stale phase.
        """
        self._eng = list(self._reg)  # engine's own copy, advanced as writes replay
        self._tp = [(self._eng[2 * c] | (self._eng[2 * c + 1] << 8)) or 1 for c in range(3)]
        self._np = (self._eng[6] & 0x1F) or 1
        self._ep = (self._eng[11] | (self._eng[12] << 8)) or 1
        self._tone_counter = [0, 0, 0]
        self._tone_high = [0, 0, 0]
        self._noise_counter = 0
        self._rng = 1  # 17-bit LFSR seed; any non-zero seed works
        self._noise_out = 0
        self._env_sub = 0
        self._start_envelope(self._eng[13])

    def _apply_write(self, reg: int, value: int) -> None:
        """Fold a due register write into the engine's cached state."""
        self._eng[reg] = value
        if reg <= 5:  # tone period (a pair of registers per channel)
            c = reg >> 1
            self._tp[c] = (self._eng[2 * c] | (self._eng[2 * c + 1] << 8)) or 1
        elif reg == 6:
            self._np = (value & 0x1F) or 1
        elif reg == 11 or reg == 12:
            self._ep = (self._eng[11] | (self._eng[12] << 8)) or 1
        elif reg == 13:
            self._start_envelope(value)  # writing the shape restarts the envelope

    def _engine_step(self) -> float:
        """Advance the chip by one step (16 AY clocks) and return the mixed level 0..1."""
        # Tone generators: each accrues ticks and flips its square output every TP ticks.
        tone_counter = self._tone_counter
        tone_high = self._tone_high
        for c in range(3):
            tone_counter[c] += TONE_TICKS_PER_STEP
            tp = self._tp[c]
            while tone_counter[c] >= tp:
                tone_counter[c] -= tp
                tone_high[c] ^= 1

        # Noise: clock the LFSR once every NP steps.
        self._noise_counter += 1
        while self._noise_counter >= self._np:
            self._noise_counter -= self._np
            self._clock_noise()

        # Envelope: one level change every 16*EP steps (EP counts at AY_CLOCK/256).
        self._env_sub += 1
        threshold = self._ep << 4
        while self._env_sub >= threshold:
            self._env_sub -= threshold
            self._step_envelope()

        # Mixer: R7 bits are *disable* flags (0 = enabled). A channel is heard when
        # its tone OR its tone-disable is set, AND its noise OR its noise-disable is
        # set -- so disabling both makes the level pass straight through (used for
        # sample/"digi" playback by writing the volume register directly).
        mixer = self._eng[7]
        noise = self._noise_out
        total = 0.0
        for c in range(3):
            tone_on = tone_high[c] | ((mixer >> c) & 1)
            noise_on = noise | ((mixer >> (c + 3)) & 1)
            if tone_on & noise_on:
                vol_reg = self._eng[8 + c]
                level = self._env_level if (vol_reg & 0x10) else (vol_reg & 0x0F)
                total += AMPLITUDE_TABLE[level]
        return total / 3.0

    def _clock_noise(self) -> None:
        """One step of the 17-bit noise LFSR (a cheap pseudo-random bit source).

        A Fibonacci shift register: XOR the taps at bits 0 and 3 to form the new top
        bit, shift right, and take the emitted bit as the noise output. Deterministic
        from the seed, but statistically white enough to sound like hiss.
        """
        feedback = (self._rng ^ (self._rng >> 3)) & 1
        self._rng = (self._rng >> 1) | (feedback << 16)
        self._noise_out = self._rng & 1

    def _start_envelope(self, shape: int) -> None:
        """Restart the envelope for a shape written to R13.

        Attack shapes climb from 0; the rest fall from 15. The end-of-ramp rules
        (continue / hold / alternate) are applied in :meth:`_step_envelope`.
        """
        self._env_shape = shape & 0x0F
        self._env_holding = False
        if shape & ENV_ATTACK:
            self._env_level = 0
            self._env_dir = 1
        else:
            self._env_level = 15
            self._env_dir = -1

    def _step_envelope(self) -> None:
        """Advance the envelope one level, applying the shape's end-of-ramp behaviour.

        The four R13 bits (continue/attack/alternate/hold) combine into the 10 audible
        shapes: single decay/attack to silence, repeating saws, triangles, and
        ramps-then-hold. See the branch comments for how each falls out.
        """
        if self._env_holding:
            return
        self._env_level += self._env_dir
        if 0 <= self._env_level <= 15:
            return  # still inside the ramp

        shape = self._env_shape
        hit_top = self._env_level > 15
        if not (shape & ENV_CONT):
            # Non-continuing: one ramp, then silence forever.
            self._env_level, self._env_holding = 0, True
        elif shape & ENV_HOLD:
            # Hold: freeze at a rail. ALTERNATE holds at the opposite rail.
            if shape & ENV_ALT:
                self._env_level = 0 if hit_top else 15
            else:
                self._env_level = 15 if hit_top else 0
            self._env_holding = True
        elif shape & ENV_ALT:
            # Continue + alternate: bounce off the rail (triangle wave).
            self._env_dir = -self._env_dir
            self._env_level = 15 if hit_top else 0
        else:
            # Continue, no alternate: wrap to the far rail (sawtooth).
            self._env_level = 0 if hit_top else 15

    @staticmethod
    def _add_level_span(accum, start, end, level, bucket_width, n) -> None:
        """Distribute a constant ``level`` over [start, end) across output buckets."""
        first = max(int(start / bucket_width), 0)
        last = min(int((end - 1e-9) / bucket_width), n - 1)
        for i in range(first, last + 1):
            bucket_start = i * bucket_width
            overlap = min(end, bucket_start + bucket_width) - max(start, bucket_start)
            if overlap > 0:
                accum[i] += level * overlap

    def _dc_block(self, x: float) -> float:
        """One-pole DC blocker -- removes the steady offset so a held level is silent."""
        y = x - self._dc_prev_in + self._dc_pole * self._dc_prev_out
        self._dc_prev_in = x
        self._dc_prev_out = y
        return y
