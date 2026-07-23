"""Tests for the project manifest's asset bookkeeping (zxemu_ui.workspace.project)."""

from __future__ import annotations

import pytest

from zxemu_core.assets.manifest import AssetKind
from zxemu_ui.workspace.project import Project


def test_new_project_has_no_assets(tmp_path):
    project = Project.create(tmp_path / "p", "P", "48k")
    assert project.assets() == []


def test_add_asset_derives_symbol_from_filename(tmp_path):
    project = Project.create(tmp_path / "p", "P", "48k")
    entry = project.add_asset("sprites/Hero Walk.bmp", AssetKind.SPRITE_SHEET)
    assert entry.symbol == "Hero_Walk"
    assert entry.placement == "auto"
    assert project.assets() == [entry]


def test_add_asset_sanitizes_symbol_starting_with_digit(tmp_path):
    project = Project.create(tmp_path / "p", "P", "48k")
    entry = project.add_asset("9lives.bmp", AssetKind.BITMAP)
    assert entry.symbol == "asset_9lives"


def test_add_asset_stores_params(tmp_path):
    project = Project.create(tmp_path / "p", "P", "48k")
    entry = project.add_asset(
        "hero.bmp", AssetKind.SPRITE_SHEET, params={"frame_width": 16, "frame_height": 16}
    )
    assert project.assets()[0].params == {"frame_width": 16, "frame_height": 16}
    assert entry.params == {"frame_width": 16, "frame_height": 16}


def test_add_asset_with_explicit_symbol(tmp_path):
    project = Project.create(tmp_path / "p", "P", "48k")
    entry = project.add_asset("a.bmp", AssetKind.BITMAP, symbol="my_screen")
    assert entry.symbol == "my_screen"


def test_add_asset_sequence_requires_explicit_symbol(tmp_path):
    project = Project.create(tmp_path / "p", "P", "48k")
    with pytest.raises(ValueError, match="explicit symbol"):
        project.add_asset(["a.bmp", "b.bmp"], AssetKind.SPRITE_SEQUENCE)


def test_add_asset_avoids_id_collision(tmp_path):
    project = Project.create(tmp_path / "p", "P", "48k")
    first = project.add_asset("hero.bmp", AssetKind.BITMAP)
    second = project.add_asset("hero.bin", AssetKind.BINARY, symbol="hero")
    assert first.id != second.id
    assert second.id == "hero_2"


def test_set_asset_placement_and_auto(tmp_path):
    project = Project.create(tmp_path / "p", "P", "48k")
    entry = project.add_asset("a.bmp", AssetKind.BITMAP)
    project.set_asset_placement(entry.id, "ram2", 100)
    assert project.assets()[0].placement == {"bank": "ram2", "offset": 100}
    project.set_asset_auto(entry.id)
    assert project.assets()[0].placement == "auto"


def test_set_asset_placement_unknown_id_raises(tmp_path):
    project = Project.create(tmp_path / "p", "P", "48k")
    with pytest.raises(ValueError, match="no asset"):
        project.set_asset_placement("missing", "ram2", 0)


def test_remove_asset(tmp_path):
    project = Project.create(tmp_path / "p", "P", "48k")
    entry = project.add_asset("a.bmp", AssetKind.BITMAP)
    project.remove_asset(entry.id)
    assert project.assets() == []


def test_remove_unknown_asset_raises(tmp_path):
    project = Project.create(tmp_path / "p", "P", "48k")
    with pytest.raises(ValueError, match="no asset"):
        project.remove_asset("missing")


def test_assets_persist_across_reload(tmp_path):
    project = Project.create(tmp_path / "p", "P", "48k")
    project.add_asset("a.bmp", AssetKind.BITMAP, symbol="a")
    reloaded = Project(tmp_path / "p")
    assert [e.symbol for e in reloaded.assets()] == ["a"]
