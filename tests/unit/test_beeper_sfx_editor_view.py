"""Tests for the Hz/frames beeper SFX editor (zxemu_ui.panels.beeper_sfx_editor_view)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from zxemu_core.assets.manifest import AssetKind  # noqa: E402
from zxemu_ui.panels.beeper_sfx_editor_view import BeeperSfxEditorView  # noqa: E402
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


def test_show_asset_loads_existing_entries_as_rows(qapp, tmp_path):
    project, entry, _path = _project_with_sfx(tmp_path)
    editor = BeeperSfxEditorView()
    editor.show_asset(project, entry)
    assert editor._title_label.text() == "boom"
    assert editor.entries() == [(3977, 4), (0, 2)]


def test_add_tone_row_autosaves(qapp, tmp_path):
    project, entry, path = _project_with_sfx(tmp_path, text="")
    editor = BeeperSfxEditorView()
    editor.show_asset(project, entry)

    editor._add_row(440.0, 4)
    saved = path.read_text()
    assert saved.strip() != ""
    period, duration = (int(x) for x in saved.strip().split(","))
    assert duration == 4
    assert abs(period - 3977) <= 1  # 440Hz rounds to this period


def test_add_rest_row_has_zero_period(qapp, tmp_path):
    project, entry, path = _project_with_sfx(tmp_path, text="")
    editor = BeeperSfxEditorView()
    editor.show_asset(project, entry)
    editor._add_row(0.0, 8)
    assert editor.entries() == [(0, 8)]


def test_remove_row_autosaves(qapp, tmp_path):
    project, entry, path = _project_with_sfx(tmp_path)
    editor = BeeperSfxEditorView()
    editor.show_asset(project, entry)

    first_row = editor._rows()[0]
    editor._remove_row(first_row)
    assert editor.entries() == [(0, 2)]
    assert path.read_text().strip() == "0,2"


def test_editing_a_row_field_autosaves(qapp, tmp_path):
    project, entry, path = _project_with_sfx(tmp_path, text="100,4\n")
    editor = BeeperSfxEditorView()
    editor.show_asset(project, entry)

    row = editor._rows()[0]
    row.duration_spin.setValue(20)
    assert "100,20" in path.read_text()


def test_play_with_no_rows_does_not_crash(qapp, tmp_path):
    project, entry, _path = _project_with_sfx(tmp_path, text="")
    editor = BeeperSfxEditorView()
    editor.show_asset(project, entry)
    editor._play()  # must not raise
    assert editor._preview_audio is None


def test_play_renders_audio(qapp, tmp_path):
    project, entry, _path = _project_with_sfx(tmp_path)
    editor = BeeperSfxEditorView()
    editor.show_asset(project, entry)
    editor._play()
    assert editor._preview_audio is not None
    assert editor._preview_audio.ok
