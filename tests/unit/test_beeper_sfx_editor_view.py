"""Tests for the bar-chart beeper SFX editor (zxemu_ui.panels.beeper_sfx_editor_view).

One column is one video frame -- the shortest sound the format can express -- and there is
no setting for that. Length comes from how far you drag, which is why most of what follows
is about strokes rather than about clicks.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt5.QtCore import QPoint, Qt  # noqa: E402
from PyQt5.QtGui import QMouseEvent  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from zxemu_core.assets.beeper_sfx import REST, hz_to_period, parse_beeper_sfx, period_to_hz  # noqa: E402
from zxemu_core.assets.manifest import AssetKind  # noqa: E402
from zxemu_ui.panels.beeper_sfx_editor_view import (  # noqa: E402
    AXIS_WIDTH,
    FRAME_WIDTH,
    FRAMES_PER_SECOND,
    GRID_HEIGHT,
    MAX_HZ,
    MIN_HZ,
    OCTAVES,
    RULER_HEIGHT,
    BeeperSfxEditorView,
    format_hz,
    hz_for_y,
    octave_frequencies,
    y_for_hz,
)
from zxemu_ui.workspace.project import Project  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _project_with_sfx(tmp_path, text="3977,4\n0,2\n"):
    project = Project.create(tmp_path / "p", "P", "48k")
    path = project.folder / "boom.zxsfx"
    path.write_text(text)
    entry = project.add_asset("boom.zxsfx", AssetKind.BEEPER_SFX, symbol="boom")
    return project, entry, path


def _open(tmp_path, text="3977,4\n0,2\n"):
    project, entry, path = _project_with_sfx(tmp_path, text)
    editor = BeeperSfxEditorView()
    editor.show_asset(project, entry)
    # Park at the origin. Synthetic mouse events are in *widget* coordinates -- a real
    # click can only land on a visible point, but a hand-built one can land under the
    # pinned headers and be correctly ignored, which looks like a failure to draw.
    editor._scroll.verticalScrollBar().setValue(0)
    editor._scroll.horizontalScrollBar().setValue(0)
    return editor, path


# --- the frequency axis ----------------------------------------------------------------


def test_higher_frequencies_are_higher_up(qapp):
    """The whole premise of the chart: a taller bar is a higher tone."""
    assert y_for_hz(2000) < y_for_hz(200)


def test_the_axis_ends_are_the_top_and_bottom_of_the_grid(qapp):
    assert y_for_hz(MAX_HZ) == pytest.approx(RULER_HEIGHT)
    assert y_for_hz(MIN_HZ) == pytest.approx(RULER_HEIGHT + GRID_HEIGHT)


def test_the_axis_is_logarithmic_so_every_octave_is_the_same_height(qapp):
    """A linear axis would squash the whole low end -- where thuds live -- into a sliver."""
    octave = GRID_HEIGHT / OCTAVES
    for hz in (64, 128, 256, 512, 1024):
        assert y_for_hz(hz) - y_for_hz(hz * 2) == pytest.approx(octave)


def test_y_and_hz_are_inverses(qapp):
    for hz in (40, 100, 440, 1500, 4000):
        assert hz_for_y(y_for_hz(hz)) == pytest.approx(hz)


def test_the_axis_is_clamped_at_both_ends(qapp):
    assert y_for_hz(1) == y_for_hz(MIN_HZ)
    assert y_for_hz(100000) == y_for_hz(MAX_HZ)
    assert hz_for_y(-500) == pytest.approx(MAX_HZ)
    assert hz_for_y(99999) == pytest.approx(MIN_HZ)


def test_the_labelled_gridlines_are_octaves(qapp):
    lines = octave_frequencies()
    assert lines[0] == MIN_HZ and lines[-1] == MAX_HZ
    assert all(b == pytest.approx(a * 2) for a, b in zip(lines, lines[1:]))


@pytest.mark.parametrize("hz,label", [(32, "32"), (256, "256"), (1024, "1.0k"), (4096, "4.1k")])
def test_format_hz(hz, label):
    assert format_hz(hz) == label


# --- one column is one frame -----------------------------------------------------------


def test_a_column_is_one_video_frame(qapp, tmp_path):
    """No step setting: the grid is the finest thing the format can express."""
    editor, _path = _open(tmp_path, text="")
    assert editor.chart.x_for_frame(1) - editor.chart.x_for_frame(0) == FRAME_WIDTH
    assert not hasattr(editor, "frames_per_step")


def test_there_is_no_step_control(qapp, tmp_path):
    """It earned nothing -- length already comes from the drag."""
    editor, _path = _open(tmp_path, text="")
    assert not hasattr(editor, "_step_spin")
    assert not hasattr(editor, "set_frames_per_step")


def test_a_second_of_sound_is_fifty_columns(qapp, tmp_path):
    editor, _path = _open(tmp_path, text="")
    span = editor.chart.x_for_frame(FRAMES_PER_SECOND) - editor.chart.x_for_frame(0)
    assert span == FRAMES_PER_SECOND * FRAME_WIDTH


def test_setting_one_frame_writes_exactly_one_frame(qapp, tmp_path):
    editor, _path = _open(tmp_path, text="")
    editor.set_frequency(0, 440)
    assert editor.columns == [hz_to_period(440)]
    assert editor.entries() == [(hz_to_period(440), 1)]


# --- loading --------------------------------------------------------------------------


def test_show_asset_expands_entries_into_per_frame_columns(qapp, tmp_path):
    editor, _path = _open(tmp_path)
    assert editor._title_label.text() == "boom"
    assert editor.columns == [3977] * 4 + [REST] * 2
    # The trailing rest is dropped on the way back out -- silence at the end of a table
    # plays as nothing, and keeping it would mean erasing the last bar never shortens
    # the effect you can see. A rest *between* tones is kept (see below).
    assert editor.entries() == [(3977, 4)]


def test_summary_reports_duration_and_entries(qapp, tmp_path):
    editor, _path = _open(tmp_path, text="3977,50\n")
    assert "1.00s" in editor._summary_label.text()
    assert "50 frames" in editor._summary_label.text()
    assert "1 entry" in editor._summary_label.text()


def test_summary_reports_the_compiled_size_in_bytes(qapp, tmp_path):
    """One entry (3 bytes) plus the 3-byte sentinel -- what the effect costs in memory."""
    editor, _path = _open(tmp_path, text="3977,50\n")
    assert "6 bytes" in editor._summary_label.text()


def test_the_byte_count_follows_entries_not_length(qapp, tmp_path):
    """A sweep is priced per step; holding a tone is free however long you hold it."""
    editor, _path = _open(tmp_path, text="")
    for frame in range(10):
        editor.set_frequency(frame, 440)  # one held tone -> one entry
    assert "6 bytes" in editor._summary_label.text()

    for frame in range(10):
        editor.set_frequency(frame, 440 + frame * 20)  # ten different pitches -> ten entries
    assert "33 bytes" in editor._summary_label.text()


def test_an_empty_file_opens_empty(qapp, tmp_path):
    editor, _path = _open(tmp_path, text="")
    assert editor.columns == []
    assert editor.entries() == []


# --- drawing --------------------------------------------------------------------------


def test_the_frequency_drawn_is_the_frequency_stored(qapp, tmp_path):
    editor, _path = _open(tmp_path, text="")
    editor.set_frequency(0, 660)
    assert period_to_hz(editor.columns[0]) == pytest.approx(660, rel=0.001)


def test_adjacent_frames_at_one_frequency_become_a_single_entry(qapp, tmp_path):
    """A held tone is one wide bar on screen because it is one entry in the file."""
    editor, path = _open(tmp_path, text="")
    for frame in range(10):
        editor.set_frequency(frame, 880)
    editor.save()
    assert parse_beeper_sfx(path.read_text()) == [(hz_to_period(880), 10)]


def test_a_held_tone_is_drawn_as_one_bar(qapp, tmp_path):
    editor, _path = _open(tmp_path, text="")
    for frame in range(10):
        editor.set_frequency(frame, 880)
    assert editor.chart.note_runs() == [(0, 10, hz_to_period(880))]


def test_drawing_past_the_end_appends_silence_up_to_it(qapp, tmp_path):
    editor, _path = _open(tmp_path, text="")
    editor.set_frequency(3, 440)
    assert editor.entries() == [(0, 3), (hz_to_period(440), 1)]


def test_erasing_silences_one_frame(qapp, tmp_path):
    editor, path = _open(tmp_path, text="")
    for frame in range(3):
        editor.set_frequency(frame, 880)
    editor.set_rest(0)
    editor.save()
    assert parse_beeper_sfx(path.read_text()) == [(0, 1), (hz_to_period(880), 2)]


def test_erasing_the_tail_shortens_the_effect(qapp, tmp_path):
    editor, path = _open(tmp_path, text="")
    for frame in range(3):
        editor.set_frequency(frame, 880)
    editor.set_rest(2)
    editor.save()
    assert parse_beeper_sfx(path.read_text()) == [(hz_to_period(880), 2)]


def test_erasing_past_the_end_is_a_no_op(qapp, tmp_path):
    editor, _path = _open(tmp_path)
    before = list(editor.columns)
    editor.set_rest(999)
    assert editor.columns == before


def test_clear_empties_the_file(qapp, tmp_path):
    editor, path = _open(tmp_path)
    editor.clear()
    assert editor.columns == []
    assert path.read_text() == ""


# --- an unedited file survives untouched ----------------------------------------------


def test_an_arbitrary_period_is_not_rewritten_by_loading_and_saving(qapp, tmp_path):
    """No snapping anywhere: a hand-typed period keeps its exact value."""
    editor, path = _open(tmp_path, text="1234,6\n")
    editor.save()
    assert parse_beeper_sfx(path.read_text()) == [(1234, 6)]


def test_repainting_one_frame_leaves_the_rest_exact(qapp, tmp_path):
    editor, path = _open(tmp_path, text="1234,3\n")
    editor.set_frequency(1, 440)
    editor.save()
    assert parse_beeper_sfx(path.read_text()) == [(1234, 1), (hz_to_period(440), 1), (1234, 1)]


# --- strokes --------------------------------------------------------------------------


def _send(widget, kind, x, y, button, buttons, modifiers=Qt.NoModifier):
    QApplication.sendEvent(widget, QMouseEvent(kind, QPoint(x, y), button, buttons, modifiers))


def _frame_x(frame):
    return AXIS_WIDTH + frame * FRAME_WIDTH + FRAME_WIDTH // 2


def _drag(chart, points, button=Qt.LeftButton, modifiers=Qt.NoModifier):
    """Press at the first point, move through the rest, release at the last."""
    buttons = button
    _send(chart, QMouseEvent.MouseButtonPress, points[0][0], points[0][1], button, buttons, modifiers)
    for x, y in points[1:]:
        _send(chart, QMouseEvent.MouseMove, x, y, Qt.NoButton, buttons, modifiers)
    _send(chart, QMouseEvent.MouseButtonRelease, points[-1][0], points[-1][1], button, Qt.NoButton, modifiers)


def test_a_click_makes_the_shortest_possible_sound(qapp, tmp_path):
    editor, path = _open(tmp_path, text="")
    y = int(y_for_hz(440))
    _drag(editor.chart, [(_frame_x(0), y)])
    assert parse_beeper_sfx(path.read_text())[0][1] == 1  # one frame, 20ms


def test_dragging_sideways_makes_it_last_longer(qapp, tmp_path):
    """The whole reason there is no length setting."""
    editor, path = _open(tmp_path, text="")
    y = int(y_for_hz(440))
    _drag(editor.chart, [(_frame_x(frame), y) for frame in range(12)])

    entries = parse_beeper_sfx(path.read_text())
    assert len(entries) == 1        # one bar
    assert entries[0][1] == 12      # ...twelve frames long


def test_dragging_further_makes_it_longer_still(qapp, tmp_path):
    editor, path = _open(tmp_path, text="")
    y = int(y_for_hz(440))
    _drag(editor.chart, [(_frame_x(frame), y) for frame in range(30)])
    assert parse_beeper_sfx(path.read_text())[0][1] == 30


def test_a_fast_drag_leaves_no_gaps(qapp, tmp_path):
    """Mouse moves are sampled coarsely; without filling the gap this combs the bar."""
    editor, path = _open(tmp_path, text="")
    y = int(y_for_hz(440))
    # Two points 20 frames apart, as if the pointer jumped between reports.
    _drag(editor.chart, [(_frame_x(0), y), (_frame_x(20), y)])

    assert REST not in editor.columns[:21]
    assert parse_beeper_sfx(path.read_text())[0][1] == 21


def test_a_fast_diagonal_drag_sweeps_smoothly(qapp, tmp_path):
    """The skipped frames take interpolated pitches, so the sweep is a ramp not a step."""
    editor, _path = _open(tmp_path, text="")
    low, high = int(y_for_hz(200)), int(y_for_hz(1600))
    _drag(editor.chart, [(_frame_x(0), low), (_frame_x(20), high)])

    frequencies = [period_to_hz(period) for period in editor.columns[:21]]
    assert all(b >= a for a, b in zip(frequencies, frequencies[1:]))  # monotonically rising
    assert frequencies[0] == pytest.approx(200, rel=0.05)
    assert frequencies[-1] == pytest.approx(1600, rel=0.05)


def test_shift_holds_the_pitch_level_across_a_wobbly_drag(qapp, tmp_path):
    """Dragging "sideways" by hand is never level, and every wobble would be a new entry."""
    editor, path = _open(tmp_path, text="")
    y = int(y_for_hz(440))
    points = [(_frame_x(frame), y + wobble)
              for frame, wobble in zip(range(10), (0, -6, 4, -3, 5, -2, 3, -5, 2, 0))]
    _drag(editor.chart, points, modifiers=Qt.ShiftModifier)

    assert len(parse_beeper_sfx(path.read_text())) == 1  # one entry despite the wobble


def test_without_shift_a_wobble_really_does_change_the_tone(qapp, tmp_path):
    editor, _path = _open(tmp_path, text="")
    y = int(y_for_hz(440))
    _drag(editor.chart, [(_frame_x(0), y), (_frame_x(1), y - 20)])
    assert len(editor.entries()) > 1


def test_right_dragging_erases(qapp, tmp_path):
    editor, path = _open(tmp_path, text="")
    y = int(y_for_hz(440))
    for frame in range(6):
        editor.set_frequency(frame, 440)

    _drag(editor.chart, [(_frame_x(0), y), (_frame_x(2), y)], button=Qt.RightButton)
    assert parse_beeper_sfx(path.read_text()) == [(0, 3), (hz_to_period(440), 3)]


def test_a_click_on_the_frequency_axis_draws_nothing(qapp, tmp_path):
    editor, _path = _open(tmp_path, text="")
    _drag(editor.chart, [(AXIS_WIDTH // 2, int(y_for_hz(440)))])
    assert editor.columns == []


def test_a_click_on_the_time_ruler_draws_nothing(qapp, tmp_path):
    editor, _path = _open(tmp_path, text="")
    _drag(editor.chart, [(_frame_x(2), RULER_HEIGHT // 2)])
    assert editor.columns == []


def test_a_click_below_the_baseline_draws_nothing(qapp, tmp_path):
    editor, _path = _open(tmp_path, text="")
    _drag(editor.chart, [(_frame_x(2), editor.chart.baseline_y() + 5)])
    assert editor.columns == []


def test_the_chart_grows_wide_enough_to_hold_the_effect(qapp, tmp_path):
    editor, _path = _open(tmp_path, text="")
    editor.set_frequency(400, 440)
    assert editor.chart.frame_count() > 400


def test_the_chart_needs_no_vertical_scrolling(qapp, tmp_path):
    """Seven octaves fit at once, which is why there is no 'scroll to the notes' step."""
    editor, _path = _open(tmp_path, text="")
    assert editor.chart.sizeHint().height() == RULER_HEIGHT + GRID_HEIGHT + 1


# --- pinned headers ---------------------------------------------------------------------


def test_the_axis_is_pinned_to_the_scrolled_viewport(qapp, tmp_path):
    """A frequency scale that slides off the left labels bars you can no longer see."""
    editor, _path = _open(tmp_path, text="")
    editor.resize(400, 400)
    editor.set_frequency(400, 440)  # make the chart wider than the viewport
    QApplication.processEvents()
    editor._scroll.horizontalScrollBar().setValue(200)
    editor._scroll.verticalScrollBar().setValue(0)

    origin_x, origin_y = editor.chart._origin()
    assert origin_x > 0 and origin_y == 0
    y = int(y_for_hz(440))
    # A click where the pinned axis now sits must be rejected, not treated as grid.
    assert editor.chart._frame_at(origin_x + AXIS_WIDTH // 2, y) is None
    assert editor.chart._frame_at(origin_x + AXIS_WIDTH + 4, y) is not None


# --- playback -------------------------------------------------------------------------


def test_play_with_nothing_drawn_does_not_crash(qapp, tmp_path):
    editor, _path = _open(tmp_path, text="")
    editor._play()  # must not raise
    assert editor._preview_audio is None


def test_play_renders_audio(qapp, tmp_path):
    editor, _path = _open(tmp_path)
    editor._play()
    assert editor._preview_audio is not None
    assert editor._preview_audio.ok
