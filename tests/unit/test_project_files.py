"""Tests for removing files from a project (zxemu_ui.workspace.project_files).

No Qt here on purpose -- this is the half of "delete" that is about the project rather
than about a window, and being testable without a ``QApplication`` is the point of it
living in ``workspace`` at all.
"""

from __future__ import annotations

import os

import pytest

from zxemu_core.assets.manifest import AssetKind
from zxemu_core.assets.native_sprite import blank_sprite
from zxemu_ui.workspace import asset_build, project_files
from zxemu_ui.workspace.project import Project


@pytest.fixture
def project(tmp_path) -> Project:
    project = Project.create(tmp_path / "p", "P", "48k")
    (project.folder / "notes.txt").write_text("hello")
    (project.folder / "levels").mkdir()
    (project.folder / "levels" / "one.asm").write_text("nop\n")
    (project.folder / "levels" / "two.asm").write_text("nop\n")
    return project


def _add_sprite(project, relative_path: str, symbol: str):
    path = project.folder / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(blank_sprite(8, 8).encode(with_header=False))
    return project.add_asset(relative_path, AssetKind.SPRITE_SHEET, symbol=symbol)


# --- path comparison ---------------------------------------------------------------


def test_normalise_collapses_separator_differences(tmp_path):
    assert project_files.normalise("a/b/c") == project_files.normalise(os.path.join("a", "b", "c"))


def test_normalise_collapses_redundant_segments():
    assert project_files.normalise("a/./b/../b/c") == project_files.normalise("a/b/c")


@pytest.mark.skipif(os.name != "nt", reason="only Windows compares paths case-insensitively")
def test_normalise_collapses_case_on_windows():
    assert project_files.normalise("A/B.TXT") == project_files.normalise("a/b.txt")


def test_a_path_is_within_itself(tmp_path):
    assert project_files.is_within(tmp_path / "x", tmp_path / "x")


def test_a_child_is_within_its_folder(tmp_path):
    assert project_files.is_within(tmp_path / "levels", tmp_path / "levels" / "deep" / "one.asm")


def test_a_sibling_is_not_within(tmp_path):
    assert not project_files.is_within(tmp_path / "levels", tmp_path / "other" / "one.asm")


def test_a_name_that_merely_starts_the_same_is_not_within(tmp_path):
    """`levels2/x` must not count as inside `levels` just because the string starts alike."""
    assert not project_files.is_within(tmp_path / "levels", tmp_path / "levels2" / "one.asm")


# --- which assets a deletion takes with it ------------------------------------------


def test_assets_under_a_file_is_just_that_file(project):
    _add_sprite(project, "hero.zx8x8", "hero")
    _add_sprite(project, "villain.zx8x8", "villain")
    matched = project_files.assets_under(project, project.folder / "hero.zx8x8")
    assert [entry.symbol for entry in matched] == ["hero"]


def test_assets_under_a_folder_finds_everything_inside(project):
    _add_sprite(project, "levels/hero.zx8x8", "hero")
    _add_sprite(project, "levels/deep/boss.zx8x8", "boss")
    _add_sprite(project, "outside.zx8x8", "outside")
    matched = project_files.assets_under(project, project.folder / "levels")
    assert sorted(entry.symbol for entry in matched) == ["boss", "hero"]


def test_a_sprite_sequence_matches_on_any_one_of_its_frames(project):
    for name in ("f0.bmp", "f1.bmp"):
        (project.folder / name).write_bytes(b"\x00")
    project.add_asset(["f0.bmp", "f1.bmp"], AssetKind.SPRITE_SEQUENCE, symbol="walk")
    matched = project_files.assets_under(project, project.folder / "f1.bmp")
    assert [entry.symbol for entry in matched] == ["walk"]


def test_a_file_that_backs_no_asset_matches_nothing(project):
    assert project_files.assets_under(project, project.folder / "notes.txt") == []


# --- counting what a folder holds ------------------------------------------------------


def test_count_contents_counts_recursively(project):
    assert project_files.count_contents(project.folder / "levels") == 2


def test_count_contents_of_an_empty_folder_is_zero(project):
    (project.folder / "empty").mkdir()
    assert project_files.count_contents(project.folder / "empty") == 0


def test_count_contents_includes_nested_folders_themselves(project):
    (project.folder / "levels" / "deep").mkdir()
    (project.folder / "levels" / "deep" / "three.asm").write_text("nop\n")
    assert project_files.count_contents(project.folder / "levels") == 4  # 2 files + deep/ + its file


# --- deleting -----------------------------------------------------------------------------


def test_delete_removes_a_file(project):
    target = project.folder / "notes.txt"
    project_files.delete(project, target)
    assert not target.exists()


def test_delete_removes_a_folder_and_its_contents(project):
    target = project.folder / "levels"
    project_files.delete(project, target)
    assert not target.exists()


def test_delete_drops_the_matching_asset_and_reports_it(project):
    _add_sprite(project, "hero.zx8x8", "hero")
    removed = project_files.delete(project, project.folder / "hero.zx8x8")
    assert [entry.symbol for entry in removed] == ["hero"]
    assert project.assets() == []


def test_delete_leaves_unrelated_assets_alone(project):
    _add_sprite(project, "hero.zx8x8", "hero")
    _add_sprite(project, "villain.zx8x8", "villain")
    project_files.delete(project, project.folder / "hero.zx8x8")
    assert [entry.symbol for entry in project.assets()] == ["villain"]


def test_delete_removes_the_assets_cached_bytes(project):
    entry = _add_sprite(project, "hero.zx8x8", "hero")
    cache = asset_build.cache_path(project, entry.symbol)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(b"stale")

    project_files.delete(project, project.folder / "hero.zx8x8")
    assert not cache.exists()


def test_delete_tolerates_an_asset_that_was_never_converted(project):
    _add_sprite(project, "hero.zx8x8", "hero")  # no cache file exists
    project_files.delete(project, project.folder / "hero.zx8x8")  # must not raise
    assert project.assets() == []


def test_delete_of_a_folder_drops_every_asset_inside_it(project):
    _add_sprite(project, "levels/hero.zx8x8", "hero")
    _add_sprite(project, "levels/boss.zx8x8", "boss")
    _add_sprite(project, "keep.zx8x8", "keep")

    removed = project_files.delete(project, project.folder / "levels")
    assert sorted(entry.symbol for entry in removed) == ["boss", "hero"]
    assert [entry.symbol for entry in project.assets()] == ["keep"]


def test_delete_of_a_plain_file_reports_no_assets(project):
    assert project_files.delete(project, project.folder / "notes.txt") == []


def test_delete_raises_when_the_file_is_not_there(project):
    with pytest.raises(OSError):
        project_files.delete(project, project.folder / "nope.txt")
