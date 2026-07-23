"""Sound: one file per thing that makes a noise, plus the thing that adds them up.

A 48K Spectrum has a single voice -- one bit the CPU wiggles by hand. A 128K adds a
proper sound chip. On real hardware those two signals are not "mixed" by anything;
their voltages simply add at a resistor network on the way to the speaker. This
package mirrors that shape:

    beeper.py   The 1-bit speaker (port 0xFE bit 4). All the information in beeper
                sound lives in the *timing* of the flips, so this is really a
                resampler: timestamped level changes in, PCM out.
    ay.py       The AY-3-8912: three tone channels, a noise source and an envelope
                generator -- the 128K's synthesiser.
    mixer.py    Sums whatever sources exist into the one stream that gets played.
                The software stand-in for that resistor network.

The point of the split is that neither source knows the other exists. Both satisfy
the same three-member contract -- ``enabled`` / ``end_frame(frame_tstates)`` /
``take_samples()`` -- and the mixer holds a list of them. A 48K registers one source,
a 128K registers two, and nothing else in the codebase has to care which: the machine
exposes ``machine.audio`` (always a mixer) and the UI drives that.

Adding a future source means writing those three members and calling ``add_source``,
with no edit to the beeper, the AY, or the mixer.

Reading order: beeper.py first (it explains how 1-bit sound becomes samples, and is
honest about where its resampling approximation breaks down), then mixer.py for the
contract, then ay.py.
"""

from __future__ import annotations

from zxemu_core.sound.ay import AY8912
from zxemu_core.sound.beeper import Beeper
from zxemu_core.sound.mixer import SoundMixer

__all__ = ["AY8912", "Beeper", "SoundMixer"]
