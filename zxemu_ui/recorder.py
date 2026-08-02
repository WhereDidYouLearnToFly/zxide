"""FrameRecorder -- captures every emulated frame so gameplay can be exported as an animation.

The Screenshot button answers "what does the screen look like *now*". This answers "what did
the screen do over the last twenty seconds", which is a different problem: a Spectrum draws
fifty frames a second and an animation is only interesting if you have all of them, in order,
with none dropped in the busy moments you most wanted to capture.

Two decisions shape everything here.

**Capture screen memory, not pixels.** The obvious implementation stores the rendered image
of each frame -- 320x256 in 32-bit colour, 320KB a frame, 16MB a second, and it forces a full
render on every frame instead of on every repaint. Storing the 6912-byte screen file plus a
few bytes of border state costs ~7KB a frame (345KB/s), and is little more than a memcpy of
something the machine is holding anyway. Rendering is deferred to the moment you press Stop,
where taking a second or two costs nobody anything. The recording is also, as a side effect,
a sequence of real .scr files -- which is why exporting them is offered.

**Capture per emulated frame, not per repaint.** ``EmulatorController`` emits ``frame_ready``
once per *batch* of up to ``MAX_CATCHUP_FRAMES`` frames, so a recorder hung off that signal
silently drops frames exactly when the machine is struggling to keep up. Instead the
controller calls :meth:`capture` directly after each frame it completes (see its
``frame_observer`` hook), which is the only place that sees every frame.

The captured frames are rendered through the same :func:`render_frame_indexed` the live
screen uses, from the same per-frame border log, so what you export is what you watched --
including mid-frame border bands, and with FLASH blinking at the rate it really blinked
(hence storing each frame's emulated-frame number rather than assuming the recording starts
on a FLASH boundary).
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

import numpy as np

from zxemu_ui.panels.emulator_view import FLASH_TOGGLE_FRAMES, PALETTE_RGB, border_rows, render_frame_indexed

#: A classic Spectrum screen file: 6144 bytes of bitmap followed by 768 attribute bytes.
#: Also, not coincidentally, exactly as much of the display bank as rendering ever reads.
SCREEN_FILE_BYTES = 6912

#: 50 fps for 60 seconds. The cap exists because recording is trivially easy to start and
#: forget about, and an unbounded capture would quietly eat memory at 345KB/s until
#: something else broke. At this ceiling a full recording is ~21MB.
DEFAULT_MAX_FRAMES = 3000

FRAMES_PER_SECOND = 50

#: GIF stores frame delays in hundredths of a second, so a Spectrum's 50Hz is a delay of
#: exactly 2 -- no resampling, no drift, no compromise. This is in milliseconds because
#: that is the unit Pillow takes; it divides by ten on the way out.
GIF_FRAME_MS = 1000 // FRAMES_PER_SECOND


class CapturedFrame(NamedTuple):
    """One frame's worth of everything needed to redraw it exactly as it was shown.

    ``border_changes`` is copied rather than referenced because the ULA reuses its log
    every frame; a stored reference would leave the whole recording showing whatever the
    last frame happened to do. ``line_tstates``/``screen_start_tstate`` come along because
    they differ per model (a Pentagon's raster is not a 48K's) and the machine can be
    swapped between frames.
    """

    screen: bytes  # the 6912-byte screen file, exactly as .scr stores it
    border_color: int  # the live border colour, used when nothing changed mid-frame
    border_start: int  # the colour the frame began with
    border_changes: tuple  # ((t_state, colour), ...) logged during the frame
    line_tstates: int
    screen_start_tstate: int
    frame_number: int  # emulated-frame count, so FLASH keeps its real phase


class FrameRecorder:
    """Collects :class:`CapturedFrame`s while running, and exports them when stopped.

    Deliberately knows nothing about Qt, projects, or where files live -- it is handed a
    machine to sample and a path to write to. That keeps it testable headlessly and means
    the same recorder could serve a fullscreen session, a headless run, or a test.
    """

    def __init__(self, max_frames: int = DEFAULT_MAX_FRAMES):
        self.max_frames = max_frames
        self._frames: list[CapturedFrame] = []
        self._recording = False
        #: True when recording stopped because the cap was reached rather than because
        #: the user pressed Stop. The caller is expected to say so out loud -- a recording
        #: that silently ends early reads as a bug in whatever you were recording.
        self.stopped_at_limit = False

    # --- recording ------------------------------------------------------------

    @property
    def recording(self) -> bool:
        return self._recording

    @property
    def frame_count(self) -> int:
        return len(self._frames)

    @property
    def duration_seconds(self) -> float:
        return len(self._frames) / FRAMES_PER_SECOND

    @property
    def frames(self) -> list:
        return list(self._frames)

    def start(self) -> None:
        """Begin capturing, discarding anything from a previous take."""
        self._frames = []
        self.stopped_at_limit = False
        self._recording = True

    def stop(self) -> int:
        """Stop capturing and return how many frames were collected."""
        self._recording = False
        return len(self._frames)

    def clear(self) -> None:
        """Drop the captured frames (and the memory they hold)."""
        self._frames = []
        self.stopped_at_limit = False

    def capture(self, machine, frame_number: int) -> bool:
        """Record the frame the machine has just finished. Returns False once full.

        Called from the controller's per-frame hook, so this runs fifty times a second
        inside the emulation loop: it does the least possible work -- one 6912-byte copy
        and a tuple() of a short list -- and defers every pixel of rendering to export.
        """
        if not self._recording:
            return False
        if len(self._frames) >= self.max_frames:
            self._recording = False
            self.stopped_at_limit = True
            return False
        ula = machine.ula
        self._frames.append(CapturedFrame(
            screen=bytes(machine.display_memory()[:SCREEN_FILE_BYTES]),
            border_color=ula.border_color,
            border_start=ula.frame_border_start,
            border_changes=tuple(ula.frame_border_changes),
            line_tstates=machine.line_tstates,
            screen_start_tstate=machine.screen_start_tstate,
            frame_number=frame_number,
        ))
        return True

    # --- rendering ------------------------------------------------------------

    def render_indices(self, index: int) -> np.ndarray:
        """Frame ``index`` as a (FULL_HEIGHT, FULL_WIDTH) array of palette indices.

        Mirrors ``EmulatorView.refresh`` exactly, down to preferring the live border colour
        when a frame logged no changes -- so an exported animation is frame-for-frame what
        was on screen, not a second interpretation of the same data.
        """
        frame = self._frames[index]
        screen_bank = np.frombuffer(frame.screen, dtype=np.uint8)
        flash_on = (frame.frame_number // FLASH_TOGGLE_FRAMES) % 2 == 1
        rows = border_rows(frame.border_changes, frame.border_start, frame.line_tstates, frame.screen_start_tstate) if frame.border_changes else None
        return render_frame_indexed(screen_bank, frame.border_color, flash_on=flash_on, rows=rows)

    # --- export ---------------------------------------------------------------

    def export_gif(self, path, frame_step: int = 1) -> int:
        """Write the recording as an animated GIF and return the frame count written.

        GIF suits a Spectrum far better than it suits most sources: the machine's palette
        is 16 colours, so a paletted format is lossless here rather than a compromise, and
        GIF's hundredth-of-a-second delay unit divides 50Hz exactly. Frames go out as
        ready-made index arrays, so Pillow never has to quantise anything.

        ``frame_step`` drops frames for a smaller file -- 2 gives 25 fps at double the
        delay, which is honest about the timing rather than playing the animation fast.
        """
        image_module = _pillow()
        indices = range(0, len(self._frames), max(1, frame_step))
        images = [self._pillow_image(image_module, i) for i in indices]
        if not images:
            raise ValueError("nothing recorded")
        images[0].save(
            str(path),
            save_all=True,
            append_images=images[1:],
            duration=GIF_FRAME_MS * max(1, frame_step),
            loop=0,  # 0 means "repeat for ever", which is what a gameplay loop wants
            disposal=1,  # leave each frame in place; the next one overwrites it whole
            optimize=False,  # optimisation here means re-quantising, which can only lose colours
        )
        return len(images)

    def export_png_sequence(self, folder, stem: str = "frame") -> int:
        """Write one paletted PNG per frame into ``folder`` -- the route into ffmpeg."""
        image_module = _pillow()
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        for i in range(len(self._frames)):
            self._pillow_image(image_module, i).save(str(folder / "{}_{:05d}.png".format(stem, i)))
        return len(self._frames)

    def export_scr_sequence(self, folder, stem: str = "frame") -> int:
        """Write one .scr per frame -- the recording in its native, unrendered form.

        Free to produce (the bytes are already what a .scr holds) and the only export that
        keeps the data a Spectrum tool can read: you can load any frame back into an
        emulator, or feed the sequence to something that re-renders it differently.
        """
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        for i, frame in enumerate(self._frames):
            (folder / "{}_{:05d}.scr".format(stem, i)).write_bytes(frame.screen)
        return len(self._frames)

    def _pillow_image(self, image_module, index: int):
        """One frame as a Pillow 'P'-mode (paletted) image carrying the Spectrum palette."""
        image = image_module.fromarray(self.render_indices(index), mode="P")
        image.putpalette(_FLAT_PALETTE)
        return image


#: The 16 colours flattened to the r,g,b,r,g,b,... byte string PIL's putpalette wants.
_FLAT_PALETTE = [channel for rgb in PALETTE_RGB for channel in rgb]


def _pillow():
    """Pillow's Image module, imported late with an explanation if it is missing.

    Late because the emulator must start and run without it: image export is a corner of
    the IDE, and an optional dependency should cost you a clear message when you use that
    corner, not a failure to launch.
    """
    try:
        from PIL import Image
    except ImportError:
        raise RuntimeError("Recording export needs Pillow. Install it with: pip install Pillow")
    return Image
