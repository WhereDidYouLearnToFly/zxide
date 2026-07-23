"""Tests for the asset Inspector panel (zxemu_ui.panels.inspector_view)."""

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from tests.unit.bmp_fixtures import write_bmp24  # noqa: E402
from zxemu_core.assets.manifest import AssetKind  # noqa: E402
from zxemu_ui.panels.inspector_view import InspectorView  # noqa: E402
from zxemu_ui.workspace.project import Project  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _project(tmp_path, model="48k"):
    return Project.create(tmp_path / "p", "P", model)


def test_starts_with_placeholder_message(qapp):
    view = InspectorView()
    assert view._message_label.isVisibleTo(view)
    assert view.entry is None


def test_show_asset_bitmap(qapp, tmp_path):
    project = _project(tmp_path)
    (project.folder / "screen.bmp").write_bytes(write_bmp24(256, 192, lambda x, y: (0, 0, 0)))
    entry = project.add_asset("screen.bmp", AssetKind.BITMAP, symbol="screen")
    project.set_asset_placement(entry.id, "ram1", 0)

    view = InspectorView()
    view.show_asset(project, entry)
    assert view._title_label.text() == "screen"
    assert not view._error_label.text()
    assert not view._preview_label.pixmap().isNull()


def test_show_asset_sprite_sheet_shows_frame_scrubber(qapp, tmp_path):
    project = _project(tmp_path)
    (project.folder / "hero.bmp").write_bytes(write_bmp24(16, 8, lambda x, y: (0, 0, 0)))
    entry = project.add_asset(
        "hero.bmp", AssetKind.SPRITE_SHEET, symbol="hero",
        params={"frame_width": 8, "frame_height": 8, "layout": {"grid": {"cols": 2, "rows": 1}}},
    )
    project.set_asset_placement(entry.id, "ram2", 0)

    view = InspectorView()
    view.show_asset(project, entry)
    assert view._frame_spin.isVisibleTo(view)
    assert view._frame_spin.maximum() == 1
    assert not view._error_label.text()


def test_show_asset_tilemap_shows_tileset_link_and_navigates(qapp, tmp_path):
    project = _project(tmp_path)
    (project.folder / "tiles.bmp").write_bytes(write_bmp24(16, 8, lambda x, y: (0, 0, 0)))
    tileset = project.add_asset(
        "tiles.bmp", AssetKind.SPRITE_SHEET, symbol="tileset",
        params={"frame_width": 8, "frame_height": 8, "layout": {"grid": {"cols": 2, "rows": 1}}},
    )
    project.set_asset_placement(tileset.id, "ram3", 0)
    level = {"tileset": "tileset", "width": 2, "height": 1, "tiles": [[0, 1]]}
    (project.folder / "level1.map.json").write_text(json.dumps(level))
    level_entry = project.add_asset("level1.map.json", AssetKind.TILEMAP, symbol="level1")
    project.set_asset_placement(level_entry.id, "ram3", 200)

    view = InspectorView()
    view.show_asset(project, level_entry)
    assert view._tileset_button.isVisibleTo(view)
    assert not view._error_label.text()

    view._goto_tileset()
    assert view._title_label.text() == "tileset"


def test_broken_asset_shows_error_not_crash(qapp, tmp_path):
    project = _project(tmp_path)
    entry = project.add_asset("missing.pt3", AssetKind.PT3, symbol="song")
    project.set_asset_placement(entry.id, "ram2", 0)

    view = InspectorView()
    view.show_asset(project, entry)  # missing.pt3 doesn't exist -- no preview attempted for PT3, no crash
    assert not view._error_label.text()


def test_broken_bitmap_shows_error_label(qapp, tmp_path):
    project = _project(tmp_path)
    entry = project.add_asset("missing.bmp", AssetKind.BITMAP, symbol="screen")
    project.set_asset_placement(entry.id, "ram1", 0)

    view = InspectorView()
    view.show_asset(project, entry)
    assert "Couldn't preview" in view._error_label.text()


def test_show_path_matches_asset_by_source(qapp, tmp_path):
    project = _project(tmp_path)
    (project.folder / "hero.bmp").write_bytes(write_bmp24(8, 8, lambda x, y: (0, 0, 0)))
    project.add_asset("hero.bmp", AssetKind.BITMAP, symbol="hero")

    view = InspectorView()
    view.show_path(project, "hero.bmp")
    assert view._title_label.text() == "hero"


def test_show_path_clears_for_non_asset_file(qapp, tmp_path):
    project = _project(tmp_path)
    view = InspectorView()
    view.show_path(project, "not_an_asset.txt")
    assert view._message_label.isVisibleTo(view)
    assert view.entry is None


def test_auto_locate_button_only_shown_for_auto_placement(qapp, tmp_path):
    project = _project(tmp_path)
    placed = project.add_asset("a.bin", AssetKind.BINARY, symbol="a")
    project.set_asset_placement(placed.id, "ram2", 0)
    project.add_asset("b.bin", AssetKind.BINARY, symbol="b")

    view = InspectorView()
    # Re-fetch from the project rather than reusing `placed` -- it's a snapshot from
    # before set_asset_placement mutated the manifest, so its .placement is stale.
    updated_placed, auto_entry = project.assets()
    view.show_asset(project, updated_placed)
    assert not view._auto_locate_button.isVisibleTo(view)
    view.show_asset(project, auto_entry)
    assert view._auto_locate_button.isVisibleTo(view)


def test_auto_locate_button_places_the_asset(qapp, tmp_path):
    project = _project(tmp_path)
    entry = project.add_asset("a.bin", AssetKind.BINARY, symbol="a")

    view = InspectorView()
    view.show_asset(project, entry)
    view._auto_locate()
    updated = project.assets()[0]
    assert isinstance(updated.placement, dict)
    assert not view._auto_locate_button.isVisibleTo(view)


def test_clear_resets_to_placeholder(qapp, tmp_path):
    project = _project(tmp_path)
    entry = project.add_asset("a.bin", AssetKind.BINARY, symbol="a")
    project.set_asset_placement(entry.id, "ram2", 0)

    view = InspectorView()
    view.show_asset(project, entry)
    view.clear()
    assert view._message_label.isVisibleTo(view)
    assert view.entry is None


def test_play_button_only_shown_for_beeper_sfx(qapp, tmp_path):
    project = _project(tmp_path)
    bin_entry = project.add_asset("a.bin", AssetKind.BINARY, symbol="a")
    project.set_asset_placement(bin_entry.id, "ram2", 0)
    (project.folder / "boom.zxsfx").write_text("440,4\n")
    sfx_entry = project.add_asset("boom.zxsfx", AssetKind.BEEPER_SFX, symbol="boom")
    project.set_asset_placement(sfx_entry.id, "ram3", 0)

    view = InspectorView()
    view.show_asset(project, bin_entry)
    assert not view._play_button.isVisibleTo(view)
    view.show_asset(project, sfx_entry)
    assert view._play_button.isVisibleTo(view)


def test_play_beeper_sfx_renders_and_pushes_audio_without_error(qapp, tmp_path):
    project = _project(tmp_path)
    (project.folder / "boom.zxsfx").write_text("440,4\n220,4\n")
    entry = project.add_asset("boom.zxsfx", AssetKind.BEEPER_SFX, symbol="boom")
    project.set_asset_placement(entry.id, "ram2", 0)

    view = InspectorView()
    view.show_asset(project, entry)
    view._play_beeper_sfx()
    assert not view._error_label.text()
    assert view._preview_audio is not None


def test_play_beeper_sfx_missing_file_shows_error_not_crash(qapp, tmp_path):
    project = _project(tmp_path)
    entry = project.add_asset("missing.zxsfx", AssetKind.BEEPER_SFX, symbol="boom")
    project.set_asset_placement(entry.id, "ram2", 0)

    view = InspectorView()
    view.show_asset(project, entry)
    view._play_beeper_sfx()
    assert "Couldn't play" in view._error_label.text()
