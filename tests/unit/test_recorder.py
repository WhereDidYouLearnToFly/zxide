"""Tests for FrameRecorder -- frame-by-frame capture and animation export.

The load-bearing claim here is that the export is *lossless*: a Spectrum picture is 16
colours, GIF is a paletted format, so every exported pixel should be the exact palette
index the screen showed. That is checked by round-tripping a GIF back through Pillow and
comparing indices, rather than by asserting it in a docstring.
"""

import numpy as np
import pytest

from zxemu_ui.machine_factory import build_machine
from zxemu_ui.panels.emulator_view import FULL_HEIGHT, FULL_WIDTH, PALETTE_RGB, render_frame_indexed
from zxemu_ui.recorder import SCREEN_FILE_BYTES, FrameRecorder

Image = pytest.importorskip("PIL.Image")


def _machine_with_pattern(seed: int = 1):
    """A machine whose screen holds recognisable, definitely-not-blank content."""
    machine = build_machine("48k")
    bank = machine.display_memory()
    rng = np.random.default_rng(seed)
    bank[:SCREEN_FILE_BYTES] = bytearray(rng.integers(0, 256, SCREEN_FILE_BYTES, dtype=np.uint8).tobytes())
    return machine


def _capture(recorder, machine, count, first_frame=0):
    for i in range(count):
        recorder.capture(machine, first_frame + i)


def _capture_varying(recorder, machine, count):
    """Capture ``count`` frames whose *rendered output* actually differs.

    Poking bitmap bytes is not enough on its own: a cell whose attribute has ink equal to
    paper draws the same however its bits are set, so a random attribute can silently make
    a "changed" frame render identically. The top-left cell is pinned to ink 7 on paper 0
    first, so the varying byte is guaranteed to be visible.
    """
    bank = machine.display_memory()
    bank[6144] = 0x07
    for i in range(count):
        bank[0] = (i * 37) & 0xFF
        recorder.capture(machine, i)


# --- capture -----------------------------------------------------------------


def test_capture_does_nothing_until_start():
    recorder = FrameRecorder()
    recorder.capture(_machine_with_pattern(), 0)
    assert recorder.frame_count == 0


def test_capture_stores_the_screen_file_verbatim():
    machine = _machine_with_pattern()
    recorder = FrameRecorder()
    recorder.start()
    recorder.capture(machine, 0)
    assert recorder.frames[0].screen == bytes(machine.display_memory()[:SCREEN_FILE_BYTES])
    assert len(recorder.frames[0].screen) == SCREEN_FILE_BYTES


def test_each_frame_is_an_independent_copy_not_a_live_view():
    # The whole recording would otherwise show whatever the machine last drew.
    machine = _machine_with_pattern()
    recorder = FrameRecorder()
    recorder.start()
    recorder.capture(machine, 0)
    first = recorder.frames[0].screen
    machine.display_memory()[:SCREEN_FILE_BYTES] = bytearray(SCREEN_FILE_BYTES)
    recorder.capture(machine, 1)
    assert recorder.frames[0].screen == first
    assert recorder.frames[1].screen != first


def test_border_changes_are_copied_not_referenced():
    # The ULA reuses its change log every frame, so a stored reference would mutate.
    machine = _machine_with_pattern()
    machine.ula.frame_border_changes = [(100, 2)]
    recorder = FrameRecorder()
    recorder.start()
    recorder.capture(machine, 0)
    machine.ula.frame_border_changes.append((200, 5))
    assert recorder.frames[0].border_changes == ((100, 2),)


def test_recording_stops_at_the_frame_cap_and_says_so():
    machine = _machine_with_pattern()
    recorder = FrameRecorder(max_frames=3)
    recorder.start()
    _capture(recorder, machine, 10)
    assert recorder.frame_count == 3
    assert not recorder.recording
    assert recorder.stopped_at_limit


def test_start_discards_a_previous_take():
    machine = _machine_with_pattern()
    recorder = FrameRecorder()
    recorder.start()
    _capture(recorder, machine, 5)
    recorder.start()
    assert recorder.frame_count == 0
    assert not recorder.stopped_at_limit


def test_duration_counts_at_fifty_frames_a_second():
    machine = _machine_with_pattern()
    recorder = FrameRecorder()
    recorder.start()
    _capture(recorder, machine, 75)
    assert recorder.duration_seconds == pytest.approx(1.5)


# --- rendering ---------------------------------------------------------------


def test_rendered_frame_matches_what_the_view_would_draw():
    machine = _machine_with_pattern()
    recorder = FrameRecorder()
    recorder.start()
    recorder.capture(machine, 0)

    expected = render_frame_indexed(np.frombuffer(recorder.frames[0].screen, dtype=np.uint8), machine.ula.border_color)
    assert np.array_equal(recorder.render_indices(0), expected)


def test_flash_phase_follows_the_emulated_frame_number_not_the_recording_start():
    # Frame 16 is mid-FLASH; a recording that started there must not reset the blink.
    machine = _machine_with_pattern()
    bank = machine.display_memory()
    bank[6144:SCREEN_FILE_BYTES] = bytes([0x80 | 0x07] * 768)  # FLASH set on every cell
    recorder = FrameRecorder()
    recorder.start()
    recorder.capture(machine, 0)
    recorder.capture(machine, 16)
    assert not np.array_equal(recorder.render_indices(0), recorder.render_indices(1))


def test_render_uses_per_row_border_colours_when_the_frame_logged_changes():
    machine = _machine_with_pattern()
    machine.ula.frame_border_start = 0
    machine.ula.frame_border_changes = [(machine.screen_start_tstate, 2)]
    recorder = FrameRecorder()
    recorder.start()
    recorder.capture(machine, 0)

    frame = recorder.render_indices(0)
    assert frame[0, 0] == 0  # above the change: the colour the frame began with
    assert frame[FULL_HEIGHT - 1, 0] == 2  # below it: the new colour


# --- export ------------------------------------------------------------------


def test_export_gif_is_pixel_identical_to_the_rendered_frames(tmp_path):
    """The claim that GIF costs no quality, verified by reading the file back."""
    machine = _machine_with_pattern()
    recorder = FrameRecorder()
    recorder.start()
    _capture_varying(recorder, machine, 4)

    path = tmp_path / "take.gif"
    assert recorder.export_gif(path) == 4

    palette = np.array(PALETTE_RGB, dtype=np.uint8)
    with Image.open(str(path)) as gif:
        assert gif.n_frames == 4
        for i in range(4):
            gif.seek(i)
            # Compared as colours rather than as raw indices: GIF may store a later frame
            # against its own local palette (and only the rectangle that changed), so the
            # index under a pixel is an encoding detail. The claim being tested is that no
            # pixel comes back a different colour from the one the machine displayed.
            written = np.array(gif.convert("RGB"))
            assert written.shape == (FULL_HEIGHT, FULL_WIDTH, 3)
            assert np.array_equal(written, palette[recorder.render_indices(i)]), "frame {} differs".format(i)


def test_export_gif_carries_the_spectrum_palette_and_a_50hz_delay(tmp_path):
    machine = _machine_with_pattern()
    recorder = FrameRecorder()
    recorder.start()
    _capture_varying(recorder, machine, 3)

    path = tmp_path / "take.gif"
    recorder.export_gif(path)

    with Image.open(str(path)) as gif:
        palette = gif.getpalette()[: 3 * len(PALETTE_RGB)]
        assert palette == [channel for rgb in PALETTE_RGB for channel in rgb]
        assert gif.info["duration"] == 20  # 1/50s, exactly


def test_export_gif_frame_step_thins_the_animation_and_slows_the_delay(tmp_path):
    machine = _machine_with_pattern()
    recorder = FrameRecorder()
    recorder.start()
    _capture_varying(recorder, machine, 10)

    path = tmp_path / "take.gif"
    assert recorder.export_gif(path, frame_step=2) == 5
    with Image.open(str(path)) as gif:
        assert gif.info["duration"] == 40  # half the rate, so twice the delay -- not fast-forward


def test_a_still_picture_collapses_to_one_gif_frame_without_losing_running_time(tmp_path):
    # Pillow merges identical consecutive frames and sums their delays. Worth pinning
    # down: it is what keeps a paused or static screen from costing a frame each 50th of
    # a second, and it must not shorten the animation.
    machine = _machine_with_pattern()
    recorder = FrameRecorder()
    recorder.start()
    _capture(recorder, machine, 5)  # five captures of an unchanging screen

    path = tmp_path / "still.gif"
    recorder.export_gif(path)
    with Image.open(str(path)) as gif:
        assert gif.n_frames == 1
        assert gif.info["duration"] == 5 * 20  # still five frames' worth of running time


def test_export_gif_refuses_an_empty_recording(tmp_path):
    with pytest.raises(ValueError):
        FrameRecorder().export_gif(tmp_path / "empty.gif")


def test_export_scr_sequence_writes_real_screen_files(tmp_path):
    machine = _machine_with_pattern()
    recorder = FrameRecorder()
    recorder.start()
    _capture(recorder, machine, 3)

    assert recorder.export_scr_sequence(tmp_path / "frames") == 3
    written = sorted((tmp_path / "frames").glob("*.scr"))
    assert len(written) == 3
    assert all(path.stat().st_size == SCREEN_FILE_BYTES for path in written)
    assert written[0].read_bytes() == recorder.frames[0].screen


def test_export_png_sequence_writes_one_file_per_frame(tmp_path):
    machine = _machine_with_pattern()
    recorder = FrameRecorder()
    recorder.start()
    _capture(recorder, machine, 3)

    assert recorder.export_png_sequence(tmp_path / "frames") == 3
    written = sorted((tmp_path / "frames").glob("*.png"))
    assert len(written) == 3
    with Image.open(str(written[0])) as png:
        assert np.array_equal(np.array(png.convert("P")), recorder.render_indices(0))
