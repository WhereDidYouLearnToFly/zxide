"""Tests for the pixel/attribute sprite editor (zxemu_ui.panels.sprite_editor_view)."""

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from zxemu_core.assets.manifest import AssetKind  # noqa: E402
from zxemu_core.assets.native_sprite import blank_sprite_data  # noqa: E402
from zxemu_ui.panels.sprite_editor_view import SpriteEditorView  # noqa: E402
from zxemu_ui.workspace.project import Project  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _project_with_sprite(tmp_path, width=8, height=8, frame_count=1):
    project = Project.create(tmp_path / "p", "P", "48k")
    path = project.folder / "hero.zxspr.json"
    path.write_text(json.dumps(blank_sprite_data(width, height, frame_count)))
    entry = project.add_asset("hero.zxspr.json", AssetKind.SPRITE_SHEET, symbol="hero")
    return project, entry, path


def test_show_asset_loads_data_and_frame_range(qapp, tmp_path):
    project, entry, _path = _project_with_sprite(tmp_path, 16, 16, frame_count=3)
    editor = SpriteEditorView()
    editor.show_asset(project, entry)
    assert editor._title_label.text() == "hero"
    assert editor._frame_spin.maximum() == 2
    assert editor.data["frame_width"] == 16


def test_paint_pixel_sets_ink_and_saves(qapp, tmp_path):
    project, entry, path = _project_with_sprite(tmp_path)
    editor = SpriteEditorView()
    editor.show_asset(project, entry)

    editor.paint_pixel(2, 3, ink=True)
    saved = json.loads(path.read_text())
    assert saved["frames"][0]["pixels"][3][2] == "#"


def test_paint_pixel_paper_clears_bit(qapp, tmp_path):
    project, entry, path = _project_with_sprite(tmp_path)
    editor = SpriteEditorView()
    editor.show_asset(project, entry)

    editor.paint_pixel(2, 3, ink=True)
    editor.paint_pixel(2, 3, ink=False)
    saved = json.loads(path.read_text())
    assert saved["frames"][0]["pixels"][3][2] == "."


def test_painting_claims_the_whole_cell_attribute(qapp, tmp_path):
    project, entry, path = _project_with_sprite(tmp_path)
    editor = SpriteEditorView()
    editor.show_asset(project, entry)

    editor._ink_row._select(4)  # green
    editor._paper_row._select(1)  # blue
    editor._bright_check.setChecked(True)
    editor.paint_pixel(0, 0, ink=True)

    saved = json.loads(path.read_text())
    attr = saved["frames"][0]["attrs"][0]
    assert attr == {"ink": 4, "paper": 1, "bright": True}


def test_painting_a_second_pixel_in_the_same_cell_re_claims_attribute(qapp, tmp_path):
    project, entry, path = _project_with_sprite(tmp_path)
    editor = SpriteEditorView()
    editor.show_asset(project, entry)

    editor._ink_row._select(2)
    editor.paint_pixel(0, 0, ink=True)
    editor._ink_row._select(6)  # repaint with a different colour
    editor.paint_pixel(5, 5, ink=True)  # still within the same 8x8 cell

    saved = json.loads(path.read_text())
    assert saved["frames"][0]["attrs"][0]["ink"] == 6  # the most recent paint wins


def test_frame_navigation_edits_independent_frames(qapp, tmp_path):
    project, entry, path = _project_with_sprite(tmp_path, frame_count=2)
    editor = SpriteEditorView()
    editor.show_asset(project, entry)

    editor.paint_pixel(0, 0, ink=True)
    editor._frame_spin.setValue(1)
    assert editor.frame_index == 1
    editor.paint_pixel(1, 1, ink=True)

    saved = json.loads(path.read_text())
    assert saved["frames"][0]["pixels"][0][0] == "#"
    assert saved["frames"][0]["pixels"][1][1] == "."
    assert saved["frames"][1]["pixels"][1][1] == "#"
    assert saved["frames"][1]["pixels"][0][0] == "."


def test_click_beyond_the_canvas_is_ignored(qapp, tmp_path):
    from PyQt5.QtCore import QPoint, Qt
    from PyQt5.QtGui import QMouseEvent
    from zxemu_ui.panels.sprite_editor_view import PIXEL_SIZE

    project, entry, path = _project_with_sprite(tmp_path)
    editor = SpriteEditorView()
    editor.show_asset(project, entry)
    before = path.read_text()

    far_beyond = QPoint(PIXEL_SIZE * 100, PIXEL_SIZE * 100)  # well outside an 8x8 sprite
    event = QMouseEvent(QMouseEvent.MouseButtonPress, far_beyond, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(editor.canvas, event)

    assert path.read_text() == before  # no write happened


def test_bright_toggle_switches_palette_table(qapp, tmp_path):
    project, entry, _path = _project_with_sprite(tmp_path)
    editor = SpriteEditorView()
    editor.show_asset(project, entry)
    assert editor._ink_row._table is not None
    from zxemu_core.assets.palette import BRIGHT_RGB, NORMAL_RGB

    assert editor._ink_row._table == NORMAL_RGB
    editor._bright_check.setChecked(True)
    assert editor._ink_row._table == BRIGHT_RGB
    assert editor._paper_row._table == BRIGHT_RGB
