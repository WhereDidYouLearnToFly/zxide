"""AudioOutput -- plays the beeper's PCM through the system sound device.

This is layer 2 of the audio pipeline; layer 1 is the toolkit-agnostic
:class:`~zxemu_core.audio.Beeper`, which produces float samples in [-1, 1]. This
thin adapter is the *only* place that knows about Qt's sound API. It opens a
``QAudioOutput`` in "push" mode -- Qt hands back a device we write bytes to -- and
converts each batch of float samples to signed 16-bit PCM on the way out.

Two deliberate choices keep it robust:

* **Fail quiet, never fail loud.** If the machine has no usable output device or
  can't provide our exact format, the adapter simply reports ``ok == False`` and
  drops every push. Sound is a nicety; it must never stop the IDE from starting.
* **Drop, don't lag.** The emulator can briefly outrun real time (catch-up
  frames). Rather than let samples queue into ever-growing latency, ``push`` only
  writes what currently fits in the device buffer and discards the rest -- a
  momentary glitch is far less jarring than audio that drifts seconds behind the
  picture.
"""

from __future__ import annotations

import array
import sys

from PyQt5.QtCore import QObject
from PyQt5.QtMultimedia import QAudioDeviceInfo, QAudioFormat, QAudioOutput

_BYTES_PER_SAMPLE = 2  # signed 16-bit, mono


class AudioOutput(QObject):
    """A push-mode sound sink for mono 16-bit PCM. Silent (ok=False) if unavailable."""

    def __init__(self, sample_rate: int = 44100, buffer_ms: int = 120, parent: QObject | None = None):
        super().__init__(parent)
        self.sample_rate = sample_rate
        self.ok = False
        self._audio: QAudioOutput | None = None
        self._device = None  # the QIODevice Qt gives us in push mode

        fmt = self._pcm_format(sample_rate)
        device_info = QAudioDeviceInfo.defaultOutputDevice()
        # No device, or the device can't do plain 44.1k/16-bit/mono: stay silent.
        # (That exact format is near-universally supported, so falling back to a
        # different sample rate -- which would mis-pitch the beeper -- isn't worth
        # the complexity here.)
        if device_info.isNull() or not device_info.isFormatSupported(fmt):
            return

        self._audio = QAudioOutput(fmt, self)
        self._audio.setBufferSize(int(sample_rate * buffer_ms / 1000) * _BYTES_PER_SAMPLE)
        self._device = self._audio.start()
        self.ok = self._device is not None

    @staticmethod
    def _pcm_format(sample_rate: int) -> QAudioFormat:
        fmt = QAudioFormat()
        fmt.setSampleRate(sample_rate)
        fmt.setChannelCount(1)
        fmt.setSampleSize(16)
        fmt.setCodec("audio/pcm")
        fmt.setByteOrder(QAudioFormat.LittleEndian)
        fmt.setSampleType(QAudioFormat.SignedInt)
        return fmt

    def push(self, samples) -> None:
        """Write float samples ([-1, 1]) to the device, dropping any that don't fit."""
        if not self.ok or not samples:
            return
        room = self._audio.bytesFree() // _BYTES_PER_SAMPLE
        if room <= 0:
            return
        if len(samples) > room:
            samples = samples[:room]  # keep the newest audio flowing; drop the overflow
        pcm = array.array("h", (self._to_int16(s) for s in samples))
        if sys.byteorder != "little":  # our format declares little-endian
            pcm.byteswap()
        self._device.write(pcm.tobytes())

    @staticmethod
    def _to_int16(sample: float) -> int:
        value = int(sample * 32767)
        return 32767 if value > 32767 else -32768 if value < -32768 else value

    def suspend(self) -> None:
        """Pause playback (e.g. while the emulator is paused), silencing immediately."""
        if self.ok:
            self._audio.suspend()

    def resume(self) -> None:
        if self.ok:
            self._audio.resume()

    def stop(self) -> None:
        if self._audio is not None:
            self._audio.stop()
