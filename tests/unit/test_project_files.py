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


# --- renaming ----------------------------------------------------------------------
#
# The failure this guards against is not "the rename did not happen" -- it is a rename that
# happens and leaves the manifest pointing at the old name, so the next build fails on a
# file that is right there under a different name. Every test below is really about the
# manifest keeping up with the disk.


def test_a_plain_file_is_renamed(project):
    project_files.rename(project, project.folder / "notes.txt", "readme.txt")
    assert (project.folder / "readme.txt").read_text() == "hello"
    assert not (project.folder / "notes.txt").exists()


def test_an_assets_source_follows_its_file(project):
    entry = _add_sprite(project, "hero.zx8x8", "hero")

    affected = project_files.rename(project, project.folder / "hero.zx8x8", "player.zx8x8")

    assert [e.id for e in affected] == [entry.id]
    moved = next(e for e in project.assets() if e.id == entry.id)
    assert project_files.normalise(moved.source) == project_files.normalise("player.zx8x8")


def test_the_symbol_is_left_alone(project):
    """The symbol is what the assembler sees. Renaming a file must not silently rename a
    label that somebody's source already refers to."""
    entry = _add_sprite(project, "hero.zx8x8", "hero")

    project_files.rename(project, project.folder / "hero.zx8x8", "player.zx8x8")

    assert next(e for e in project.assets() if e.id == entry.id).symbol == "hero"


def test_renaming_a_folder_repoints_everything_inside_it(project):
    """A folder rename moves a whole subtree, so every asset sourced from inside has to
    move with it -- not just the folder being mentioned once."""
    _add_sprite(project, "art/hero.zx8x8", "hero")
    _add_sprite(project, "art/deep/boss.zx8x8", "boss")

    project_files.rename(project, project.folder / "art", "graphics")

    sources = sorted(project_files.normalise(e.source) for e in project.assets())
    assert sources == sorted([
        project_files.normalise("graphics/hero.zx8x8"),
        project_files.normalise("graphics/deep/boss.zx8x8"),
    ])


def test_every_frame_of_a_sequence_is_repointed(project):
    """A sprite_sequence names several files. Repointing the first and forgetting the rest
    leaves an asset that cannot be converted."""
    for name in ("a.zx8x8", "b.zx8x8"):
        path = project.folder / "frames" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blank_sprite(8, 8).encode(with_header=False))
    entry = project.add_asset(["frames/a.zx8x8", "frames/b.zx8x8"], AssetKind.SPRITE_SHEET, symbol="walk")

    project_files.rename(project, project.folder / "frames", "anim")

    moved = next(e for e in project.assets() if e.id == entry.id)
    assert [project_files.normalise(s) for s in moved.source] == [
        project_files.normalise("anim/a.zx8x8"),
        project_files.normalise("anim/b.zx8x8"),
    ]


def test_the_build_cache_survives_a_rename(project):
    """It is keyed by symbol, and the bytes did not change -- only where they came from.
    Invalidating it here would mean a needless rebuild after every tidy-up."""
    entry = _add_sprite(project, "hero.zx8x8", "hero")
    cache = asset_build.cache_path(project, entry.symbol)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(b"converted")

    project_files.rename(project, project.folder / "hero.zx8x8", "player.zx8x8")

    assert cache.read_bytes() == b"converted"


def test_an_empty_name_is_refused(project):
    with pytest.raises(project_files.RenameProblem):
        project_files.rename(project, project.folder / "notes.txt", "   ")


def test_a_name_with_a_separator_is_refused(project):
    """Renaming is not moving. Accepting a path here would quietly turn one into the
    other, and "../elsewhere/x" would leave the project entirely."""
    with pytest.raises(project_files.RenameProblem):
        project_files.rename(project, project.folder / "notes.txt", os.path.join("sub", "notes.txt"))
    assert (project.folder / "notes.txt").exists()


def test_an_existing_name_is_refused(project):
    with pytest.raises(project_files.RenameProblem):
        project_files.rename(project, project.folder / "levels" / "one.asm", "two.asm")
    assert (project.folder / "levels" / "one.asm").exists()
    assert (project.folder / "levels" / "two.asm").read_text() == "nop\n"


def test_renaming_to_the_same_name_is_refused_rather_than_a_no_op(project):
    """Silently succeeding would report "renamed" in the log for something that did not
    happen, which is worse than saying so."""
    with pytest.raises(project_files.RenameProblem):
        project_files.rename(project, project.folder / "notes.txt", "notes.txt")


def test_a_case_only_rename_is_allowed(project):
    """It looks like a collision on Windows, where the destination "exists" because it is
    the source -- but changing hero.asm to Hero.asm is a legitimate thing to want."""
    project_files.check_rename(project.folder / "notes.txt", "Notes.txt")  # must not raise
