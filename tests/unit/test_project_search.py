"""Tests for project-wide search (zxemu_ui.workspace.search) -- Qt-free."""

from __future__ import annotations

import os

from zxemu_ui.workspace.search import DEFAULT_RESULT_LIMIT, search_project


def _project(tmp_path):
    folder = tmp_path / "proj"
    (folder / "core").mkdir(parents=True)
    (folder / "main.asm").write_text(
        "    org $8000\nstart:\n    call player_init\n    jp start\n", encoding="utf-8"
    )
    (folder / "core" / "player.asm").write_text(
        "player_init:\n    ld a,0\n    ret\n", encoding="utf-8"
    )
    return folder


def test_finds_matches_across_files_with_line_numbers(tmp_path):
    folder = _project(tmp_path)
    hits, truncated = search_project(folder, "player_init")

    assert not truncated
    # Sorted by path, so the subfolder comes first; relative paths use the OS separator
    # because they are shown next to files the OS also names that way.
    assert [(h.relative, h.line) for h in hits] == [
        (os.path.join("core", "player.asm"), 1),
        ("main.asm", 3),
    ]
    assert hits[1].text == "call player_init"  # stripped, ready to display
    assert hits[1].column == 9                 # where the match starts in the raw line
    assert hits[0].path == folder / "core" / "player.asm"  # absolute, for the editor


def test_search_is_case_insensitive_by_default_and_can_be_exact(tmp_path):
    folder = _project(tmp_path)
    assert search_project(folder, "PLAYER_INIT")[0]
    assert not search_project(folder, "PLAYER_INIT", case_sensitive=True)[0]


def test_assets_and_build_output_are_not_searched(tmp_path):
    """Reading a 131 KB snapshot as text gives line numbers that mean nothing."""
    folder = _project(tmp_path)
    (folder / "sprite.bmp").write_bytes(b"BM" + b"start:" + bytes(200))
    (folder / "game.sna").write_bytes(b"start:" + bytes(1000))
    (folder / "assets_generated.asm").write_text("start: ; generated\n", encoding="utf-8")
    # A dumped SLD lists every label again, with absolute paths and no line worth jumping
    # to -- found by running Find on a real project and reading the noise it produced.
    (folder / "out").mkdir()
    (folder / "out" / "fallout.sld.txt").write_text("path|18||0|5|31507|F|start:\n", encoding="utf-8")

    hits, _ = search_project(folder, "start:")

    assert [h.relative for h in hits] == ["main.asm"]  # not the bmp, .sna, generated asm or SLD dump


def test_skipped_folders_are_not_walked(tmp_path):
    folder = _project(tmp_path)
    (folder / ".git").mkdir()
    (folder / ".git" / "COMMIT_EDITMSG").write_text("start: fix\n", encoding="utf-8")
    (folder / "screenshots").mkdir()
    (folder / "screenshots" / "notes.txt").write_text("start:\n", encoding="utf-8")

    hits, _ = search_project(folder, "start:")

    assert [h.relative for h in hits] == ["main.asm"]


def test_the_result_limit_is_reported_not_hidden(tmp_path):
    folder = tmp_path / "big"
    folder.mkdir()
    (folder / "many.asm").write_text("nop\n" * (DEFAULT_RESULT_LIMIT + 50), encoding="utf-8")

    hits, truncated = search_project(folder, "nop", limit=10)

    assert len(hits) == 10 and truncated


def test_an_empty_query_finds_nothing(tmp_path):
    assert search_project(_project(tmp_path), "") == ([], False)


def test_undecodable_bytes_do_not_break_the_search(tmp_path):
    """A .txt holding stray binary is replaced-decoded, not fatal."""
    folder = _project(tmp_path)
    (folder / "notes.txt").write_bytes(b"start: \xff\xfe ok\n")

    hits, _ = search_project(folder, "start:")

    assert {h.relative for h in hits} == {"main.asm", "notes.txt"}
