"""Tests for the pixel/attribute sprite editor (zxemu_ui.panels.sprite_editor_view)."""

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt5.QtCore import QPoint, Qt  # noqa: E402
from PyQt5.QtGui import QMouseEvent  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from zxemu_core.assets.manifest import AssetKind  # noqa: E402
from zxemu_core.assets.native_sprite import (  # noqa: E402
    attr_byte,
    attr_parts,
    blank_sprite,
    blank_sprite_data,
    load_sprite_file,
    suffix_for,
)
from zxemu_ui.panels.sprite_editor_view import (  # noqa: E402
    PIXEL_SIZE,
    SWATCH_CELL,
    SpriteEditorView,
)
from zxemu_ui.workspace.project import Project  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _project_with_sprite(tmp_path, width=8, height=8, frame_count=1, has_attrs=True):
    project = Project.create(tmp_path / "p", "P", "48k")
    suffix = suffix_for(width, height, has_attrs)
    name = f"hero{suffix}"
    document = blank_sprite(width, height, frame_count, has_attrs=has_attrs)
    (project.folder / name).write_bytes(document.encode(with_header=suffix.startswith(".zxsprite")))
    entry = project.add_asset(name, AssetKind.SPRITE_SHEET, symbol="hero")
    return project, entry, project.folder / name


def _reload(path):
    return load_sprite_file(path.name, path.read_bytes())


def _open(tmp_path, **kwargs):
    project, entry, path = _project_with_sprite(tmp_path, **kwargs)
    editor = SpriteEditorView()
    editor.show_asset(project, entry)
    return editor, path


def _send(widget, kind, x, y, button, buttons, modifiers=Qt.NoModifier):
    QApplication.sendEvent(widget, QMouseEvent(kind, QPoint(x, y), button, buttons, modifiers))


def _pixel_point(x, y):
    return x * PIXEL_SIZE + PIXEL_SIZE // 2, y * PIXEL_SIZE + PIXEL_SIZE // 2


# --- loading -------------------------------------------------------------------------


def test_show_asset_loads_document_and_frame_range(qapp, tmp_path):
    editor, _path = _open(tmp_path, width=16, height=16, frame_count=3)
    assert editor._title_label.text() == "hero"
    assert editor._frame_spin.maximum() == 2
    assert editor.document.width == 16
    assert "16x16" in editor._format_label.text()
    assert "3 frames" in editor._format_label.text()


def test_show_asset_reads_an_arbitrary_size_file_from_its_header(qapp, tmp_path):
    editor, path = _open(tmp_path, width=24, height=8)
    assert path.name.endswith(".zxsprite")
    assert editor.document.width == 24 and editor.document.height == 8


# --- drawing claims the cell's colours -------------------------------------------------


def test_drawing_a_pixel_saves_it(qapp, tmp_path):
    editor, path = _open(tmp_path)
    editor.paint_pixel(2, 3, 1)
    assert _reload(path).frames[0].pixels[3][2] == 1


def test_drawing_a_pixel_claims_its_cell_for_the_selected_colours(qapp, tmp_path):
    editor, path = _open(tmp_path)
    editor._ink_bar.select(4)
    editor._paper_bar.select(1)
    editor._bright_check.setChecked(True)
    editor.paint_pixel(0, 0, 1)

    assert attr_parts(_reload(path).frames[0].attrs[0]) == (4, 1, True)


def test_only_the_pixels_own_cell_is_claimed(qapp, tmp_path):
    editor, path = _open(tmp_path, width=16, height=16)
    editor._ink_bar.select(4)
    editor.paint_pixel(9, 2, 1)  # inside the top-right 8x8 cell

    attrs = _reload(path).frames[0].attrs
    assert attr_parts(attrs[1])[0] == 4
    assert attr_parts(attrs[0]) == (0, 7, False)  # neighbouring cells untouched


def test_a_later_paint_in_the_same_cell_re_claims_it(qapp, tmp_path):
    editor, path = _open(tmp_path)
    editor._ink_bar.select(2)
    editor.paint_pixel(0, 0, 1)
    editor._ink_bar.select(6)
    editor.paint_pixel(5, 5, 1)  # still within the same 8x8 cell

    assert _reload(path).frames[0].attrs[0] & 0x07 == 6  # the most recent paint wins


def test_erasing_also_claims_the_cell(qapp, tmp_path):
    """Erasing is drawing too -- one rule, so a cell can never end up with a third colour."""
    editor, path = _open(tmp_path)
    editor._ink_bar.select(3)
    editor.paint_pixel(0, 0, 0)
    assert _reload(path).frames[0].attrs[0] & 0x07 == 3


# --- toggling means you never switch colour to erase -----------------------------------


def test_toggle_turns_a_pixel_on_then_off(qapp, tmp_path):
    editor, path = _open(tmp_path)
    editor.toggle_pixel(2, 3)
    assert _reload(path).frames[0].pixels[3][2] == 1
    editor.toggle_pixel(2, 3)
    assert _reload(path).frames[0].pixels[3][2] == 0


def test_a_click_erases_without_changing_the_selected_colour(qapp, tmp_path):
    editor, path = _open(tmp_path)
    editor.paint_pixel(1, 1, 1)
    selected = editor.selected_attr()

    x, y = _pixel_point(1, 1)
    _send(editor.canvas, QMouseEvent.MouseButtonPress, x, y, Qt.LeftButton, Qt.LeftButton)
    _send(editor.canvas, QMouseEvent.MouseButtonRelease, x, y, Qt.LeftButton, Qt.NoButton)

    assert _reload(path).frames[0].pixels[1][1] == 0
    assert editor.selected_attr() == selected  # the palette never had to move


def test_a_drag_paints_one_value_rather_than_alternating(qapp, tmp_path):
    """Press decides the stroke's value, so dragging back over a pixel doesn't undo it."""
    editor, path = _open(tmp_path)

    _send(editor.canvas, QMouseEvent.MouseButtonPress, *_pixel_point(0, 0), Qt.LeftButton, Qt.LeftButton)
    for x in (1, 2, 1, 0):  # drag right, then back over pixels already set
        _send(editor.canvas, QMouseEvent.MouseMove, *_pixel_point(x, 0), Qt.NoButton, Qt.LeftButton)
    _send(editor.canvas, QMouseEvent.MouseButtonRelease, *_pixel_point(0, 0), Qt.LeftButton, Qt.NoButton)

    assert list(_reload(path).frames[0].pixels[0][:3]) == [1, 1, 1]


def test_a_drag_that_starts_on_a_set_pixel_erases_the_whole_run(qapp, tmp_path):
    editor, path = _open(tmp_path)
    for x in range(3):
        editor.paint_pixel(x, 0, 1)

    _send(editor.canvas, QMouseEvent.MouseButtonPress, *_pixel_point(0, 0), Qt.LeftButton, Qt.LeftButton)
    for x in (1, 2):
        _send(editor.canvas, QMouseEvent.MouseMove, *_pixel_point(x, 0), Qt.NoButton, Qt.LeftButton)
    _send(editor.canvas, QMouseEvent.MouseButtonRelease, *_pixel_point(2, 0), Qt.LeftButton, Qt.NoButton)

    assert list(_reload(path).frames[0].pixels[0][:3]) == [0, 0, 0]


# --- the two escape hatches ------------------------------------------------------------


def test_right_drag_recolours_without_touching_pixels(qapp, tmp_path):
    editor, path = _open(tmp_path)
    editor.paint_pixel(0, 0, 1)
    editor._ink_bar.select(5)

    x, y = _pixel_point(3, 3)
    _send(editor.canvas, QMouseEvent.MouseButtonPress, x, y, Qt.RightButton, Qt.RightButton)
    _send(editor.canvas, QMouseEvent.MouseButtonRelease, x, y, Qt.RightButton, Qt.NoButton)

    reloaded = _reload(path)
    assert reloaded.frames[0].attrs[0] & 0x07 == 5  # recoloured
    assert reloaded.frames[0].pixels[0][0] == 1     # art untouched


def test_alt_click_picks_the_cells_colours_up(qapp, tmp_path):
    editor, _path = _open(tmp_path)
    editor.document.frames[0].attrs[0] = attr_byte(3, 6, True)

    x, y = _pixel_point(4, 4)
    _send(editor.canvas, QMouseEvent.MouseButtonPress, x, y, Qt.LeftButton, Qt.LeftButton, Qt.AltModifier)

    assert editor.selected_attr() == attr_byte(3, 6, True)


def test_alt_click_draws_nothing(qapp, tmp_path):
    editor, path = _open(tmp_path)
    before = path.read_bytes()
    x, y = _pixel_point(4, 4)
    _send(editor.canvas, QMouseEvent.MouseButtonPress, x, y, Qt.LeftButton, Qt.LeftButton, Qt.AltModifier)
    assert path.read_bytes() == before


def test_pick_attribute_updates_both_bars_and_bright(qapp, tmp_path):
    editor, _path = _open(tmp_path)
    editor.document.frames[0].attrs[0] = attr_byte(3, 6, True)
    editor.pick_attribute(4, 4)

    assert editor._ink_bar.selected_index == 3
    assert editor._paper_bar.selected_index == 6
    assert editor._bright_check.isChecked()


# --- the palette shows what is selected -------------------------------------------------


def test_the_palette_starts_on_black_ink_over_white_paper(qapp, tmp_path):
    editor, _path = _open(tmp_path)
    assert editor.selected_attr() == attr_byte(0, 7, False)


def test_clicking_a_swatch_selects_that_colour(qapp, tmp_path):
    editor, _path = _open(tmp_path)
    _send(editor._ink_bar, QMouseEvent.MouseButtonPress,
          5 * SWATCH_CELL + SWATCH_CELL // 2, SWATCH_CELL // 2, Qt.LeftButton, Qt.LeftButton)
    assert editor._ink_bar.selected_index == 5
    assert editor.selected_attr() & 0x07 == 5


def _painted_bar(bar):
    bar.resize(bar.sizeHint())
    return bar.grab().toImage()


def _pixel(image, x, y):
    colour = image.pixelColor(x, y)
    return colour.red(), colour.green(), colour.blue()


def test_the_selection_ring_never_paints_inside_the_colour_area(qapp, tmp_path):
    """The selected swatch's colour area is a *solid* block, indicator entirely outside it.

    This is the rule an earlier version broke -- it rang the swatch from the inside, so
    selecting black produced a mostly-white square, the indicator hiding the one thing it
    pointed at. The invariant is stated positively rather than as a reproduction of that
    layout: it says where the indicator may go, which is what a future change needs to
    respect, and is checked against black and white because those are the two colours the
    ring's own white/near-black could hide.
    """
    from zxemu_core.assets.palette import NORMAL_RGB
    from zxemu_ui.panels.sprite_editor_view import SELECTED_INSET

    editor, _path = _open(tmp_path)
    for index in (0, 7):  # black and white: the two the ring's own colours could hide
        editor._ink_bar.select(index)
        image = _painted_bar(editor._ink_bar)

        size = SWATCH_CELL - 2 * SELECTED_INSET
        left = index * SWATCH_CELL + SELECTED_INSET
        strays = [
            (x, y)
            for x in range(left + 1, left + size)
            for y in range(SELECTED_INSET + 1, SELECTED_INSET + size)
            if _pixel(image, x, y) != NORMAL_RGB[index]
        ]
        assert not strays, f"colour {index}: {len(strays)} pixel(s) of indicator inside the swatch"


def test_every_selectable_colour_survives_its_own_selection_ring(qapp, tmp_path):
    from zxemu_core.assets.palette import NORMAL_RGB

    editor, _path = _open(tmp_path)
    for index in range(8):
        editor._ink_bar.select(index)
        image = _painted_bar(editor._ink_bar)
        centre = _pixel(image, index * SWATCH_CELL + SWATCH_CELL // 2, SWATCH_CELL // 2)
        assert centre == NORMAL_RGB[index], f"colour {index} was obscured by its own ring"


def test_the_selected_swatch_is_drawn_larger_than_the_others(qapp, tmp_path):
    """Size is the second signal, so selection reads even where the ring is low-contrast."""
    from zxemu_core.assets.palette import NORMAL_RGB
    from zxemu_ui.panels.sprite_editor_view import SELECTED_INSET, UNSELECTED_INSET

    editor, _path = _open(tmp_path)
    editor._ink_bar.select(4)  # green, distinct from the panel background
    image = _painted_bar(editor._ink_bar)

    # A point inside the selected swatch's colour area but outside an unselected one's.
    probe = (SELECTED_INSET + UNSELECTED_INSET) // 2
    assert SELECTED_INSET < probe < UNSELECTED_INSET
    assert _pixel(image, 4 * SWATCH_CELL + probe, SWATCH_CELL // 2) == NORMAL_RGB[4]
    assert _pixel(image, 5 * SWATCH_CELL + probe, SWATCH_CELL // 2) != NORMAL_RGB[5]


def test_the_selected_swatch_is_ringed_in_white(qapp, tmp_path):
    editor, _path = _open(tmp_path)
    editor._ink_bar.select(2)
    image = _painted_bar(editor._ink_bar)
    # The ring sits in the margin above the colour area, centred on SELECTED_INSET - 2.
    assert _pixel(image, 2 * SWATCH_CELL + SWATCH_CELL // 2, 2) == (255, 255, 255)


def test_an_unselected_swatch_has_no_ring(qapp, tmp_path):
    editor, _path = _open(tmp_path)
    editor._ink_bar.select(2)
    image = _painted_bar(editor._ink_bar)
    assert _pixel(image, 5 * SWATCH_CELL + SWATCH_CELL // 2, 2) != (255, 255, 255)


def test_selecting_a_colour_repaints_the_preview(qapp, tmp_path):
    editor, _path = _open(tmp_path)
    editor._paper_bar.select(2)
    assert attr_parts(editor.selected_attr())[1] == 2


def test_bright_switches_both_bars_to_the_bright_table(qapp, tmp_path):
    from zxemu_core.assets.palette import BRIGHT_RGB, NORMAL_RGB

    editor, _path = _open(tmp_path)
    assert editor._ink_bar._table == NORMAL_RGB
    editor._bright_check.setChecked(True)
    assert editor._ink_bar._table == BRIGHT_RGB
    assert editor._paper_bar._table == BRIGHT_RGB


def test_dragging_across_the_palette_keeps_selecting(qapp, tmp_path):
    editor, _path = _open(tmp_path)
    _send(editor._ink_bar, QMouseEvent.MouseButtonPress,
          SWATCH_CELL // 2, SWATCH_CELL // 2, Qt.LeftButton, Qt.LeftButton)
    _send(editor._ink_bar, QMouseEvent.MouseMove,
          6 * SWATCH_CELL + SWATCH_CELL // 2, SWATCH_CELL // 2, Qt.NoButton, Qt.LeftButton)
    assert editor._ink_bar.selected_index == 6


# --- pixel-only sprites ---------------------------------------------------------------


def test_pixel_only_sprite_hides_every_colour_control(qapp, tmp_path):
    editor, _path = _open(tmp_path, has_attrs=False)
    assert editor.document.has_attrs is False
    assert not editor._ink_bar.isVisible()
    assert not editor._paper_bar.isVisible()
    assert not editor._preview.isVisible()
    assert not editor._bright_check.isVisible()


def test_pixel_only_sprite_says_there_are_no_colours(qapp, tmp_path):
    editor, _path = _open(tmp_path, has_attrs=False)
    assert "pixels only" in editor._hint_label.text()


def test_pixel_only_sprite_still_draws(qapp, tmp_path):
    editor, path = _open(tmp_path, width=16, height=16, has_attrs=False)
    editor.paint_pixel(15, 15, 1)
    reloaded = _reload(path)
    assert reloaded.frames[0].pixels[15][15] == 1
    assert reloaded.frames[0].attrs == []


def test_pixel_only_sprite_ignores_recolouring(qapp, tmp_path):
    editor, path = _open(tmp_path, has_attrs=False)
    editor.apply_attribute(0, 0)  # must be a no-op, not a crash
    editor.pick_attribute(0, 0)
    assert path.stat().st_size == 8  # still just the one 8-byte pixel plane


# --- frames ---------------------------------------------------------------------------


def test_frame_navigation_edits_independent_frames(qapp, tmp_path):
    editor, path = _open(tmp_path, frame_count=2)
    editor.paint_pixel(0, 0, 1)
    editor._frame_spin.setValue(1)
    assert editor.frame_index == 1
    editor.paint_pixel(1, 1, 1)

    frames = _reload(path).frames
    assert frames[0].pixels[0][0] == 1 and frames[0].pixels[1][1] == 0
    assert frames[1].pixels[1][1] == 1 and frames[1].pixels[0][0] == 0


# --- the canvas ----------------------------------------------------------------------


def test_click_beyond_the_canvas_is_ignored(qapp, tmp_path):
    editor, path = _open(tmp_path)
    before = path.read_bytes()

    far = PIXEL_SIZE * 100  # well outside an 8x8 sprite
    _send(editor.canvas, QMouseEvent.MouseButtonPress, far, far, Qt.LeftButton, Qt.LeftButton)

    assert path.read_bytes() == before  # no write happened


# --- the legacy .zxspr.json shape ----------------------------------------------------


def test_a_legacy_json_sprite_still_opens_and_saves_as_json(qapp, tmp_path):
    project = Project.create(tmp_path / "p", "P", "48k")
    path = project.folder / "hero.zxspr.json"
    path.write_text(json.dumps(blank_sprite_data(8, 8)))
    entry = project.add_asset("hero.zxspr.json", AssetKind.SPRITE_SHEET, symbol="hero")

    editor = SpriteEditorView()
    editor.show_asset(project, entry)
    editor.paint_pixel(2, 3, 1)

    saved = json.loads(path.read_text())  # still JSON -- nothing was silently rewritten
    assert saved["frames"][0]["pixels"][3][2] == "#"
