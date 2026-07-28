"""Sound: one file per thing that makes a noise, plus the thing that adds them up.

A 48K Spectrum has a single voice -- one bit the CPU wiggles by hand. A 128K adds a
proper sound chip. On real hardware those two signals are not "mixed" by anything;
their voltages simply add at a resistor network on the way to the speaker. This
package mirrors that shape:

    beeper.py           The 1-bit speaker (port 0xFE bit 4). All the information in
                        beeper sound lives in the *timing* of the flips, so this is
                        really a resampler: timestamped level changes in, PCM out.
    beeper_preview.py   Renders a ``beeper_sfx`` asset's tone/duration list to PCM via
                        a standalone ``Beeper``, with no live machine -- what the
                        Inspector's "Play" button drives.
    ay.py               The AY-3-8912: three tone channels, a noise source and an
                        envelope generator -- the 128K's synthesiser.
    mixer.py            Sums whatever sources exist into the one stream that gets
                        played. The software stand-in for that resistor network.

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

**Playing somebody's music file** is a second, separate concern living alongside the chips,
and its shape follows from one fact: most AY music is distributed as *Z80 code*, not as
notes. A compiled module has its tracker's player welded on; an ``.ay`` container holds
blocks of code plus the addresses to call. Neither can be read as music -- both must be
run -- and running Z80 code is something this project already does well, so that is how
they are played:

    music_file.py       The one entry point: a path and its bytes in, something playable
                        out, or a sentence explaining why not. Everything below is detail.
    ay_module_player.py The engine: a private Machine128 (never the one on screen), the
                        blob loaded, init called once, play called once per frame, and the
                        AY drained to PCM. Nothing Qt, so tests render at full speed.
    ay_program.py       What to load and what to call -- plus reading compiled modules,
                        whose load address is *derived* from the file and cross-checked
                        rather than assumed.
    ay_file.py          The ``.ay`` (ZXAYEMUL) container: self-relative pointers, several
                        songs, and the register preload that chooses between them.
    tracker_player.py   Raw ``.pt2``/``.pt3`` data carries no player, so one is found
                        rather than bundled (it is someone else's work). Candidates are
                        identified by shape, never by filename.
"""

from __future__ import annotations

from zxemu_core.sound.ay import AY8912
from zxemu_core.sound.beeper import Beeper
from zxemu_core.sound.beeper_preview import render_tone_sequence
from zxemu_core.sound.mixer import SoundMixer

__all__ = ["AY8912", "Beeper", "SoundMixer", "render_tone_sequence"]
