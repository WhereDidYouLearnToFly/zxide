"""Tests for deleting files and folders from the project tree (MainWindow.delete_path).

Deleting is three things at once -- the file, its editor tab, and its manifest asset
entry -- because leaving any of them behind produces a broken state that looks fine until
the next build: a tab over a file that isn't there, or an asset whose source can no longer
be read. These tests pin all three, plus the guards (confirmation, and refusing to delete
the project folder itself).
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt5.QtWidgets import QApplication, QMessageBox  # noqa: E402

from zxemu_core.assets.manifest import AssetKind  # noqa: E402
from zxemu_core.assets.native_sprite import blank_sprite  # noqa: E402
from zxemu_ui import main_window as main_window_module  # noqa: E402
from zxemu_ui.controller import EmulatorController  # noqa: E402
from zxemu_ui.machine_factory import build_machine  # noqa: E402
from zxemu_ui.main_window import MainWindow  # noqa: E402
from zxemu_ui.workspace import asset_build  # noqa: E402
from zxemu_ui.workspace.project import Project  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def confirm_yes(monkeypatch):
    """Answer every confirmation with Yes, and record what was asked."""
    asked = []

    def fake_warning(_parent, _title, text, *_args, **_kwargs):
        asked.append(text)
        return QMessageBox.Yes

    monkeypatch.setattr(main_window_module.QMessageBox, "warning", staticmethod(fake_warning))
    return asked


@pytest.fixture
def confirm_cancel(monkeypatch):
    monkeypatch.setattr(
        main_window_module.QMessageBox, "warning",
        staticmethod(lambda *_args, **_kwargs: QMessageBox.Cancel),
    )


def _window_on(project) -> MainWindow:
    machine = build_machine("48k")
    window = MainWindow(machine, EmulatorController(machine))
    window._open_project(str(project.folder))
    return window


def _project_with_files(tmp_path) -> Project:
    project = Project.create(tmp_path / "p", "P", "48k")
    (project.folder / "notes.txt").write_text("hello")
    (project.folder / "levels").mkdir()
    (project.folder / "levels" / "one.asm").write_text("nop\n")
    (project.folder / "levels" / "two.asm").write_text("nop\n")
    return project


# --- deleting a file ------------------------------------------------------------------


def test_delete_file_removes_it(qapp, tmp_path, confirm_yes):
    project = _project_with_files(tmp_path)
    window = _window_on(project)
    target = project.folder / "notes.txt"

    assert window.delete_path(str(target)) is True
    assert not target.exists()


def test_delete_closes_the_files_editor_tab(qapp, tmp_path, confirm_yes):
    project = _project_with_files(tmp_path)
    window = _window_on(project)
    target = project.folder / "notes.txt"
    window.editor.open_file(str(target))
    assert window.editor.current_path() is not None

    window.delete_path(str(target))
    open_paths = [window.editor.widget(i).property("file_path") for i in range(window.editor.count())]
    assert str(target.resolve()) not in open_paths


def test_delete_drops_the_matching_manifest_asset(qapp, tmp_path, confirm_yes):
    project = _project_with_files(tmp_path)
    sprite = project.folder / "hero.zx8x8"
    sprite.write_bytes(blank_sprite(8, 8).encode(with_header=False))
    project.add_asset("hero.zx8x8", AssetKind.SPRITE_SHEET, symbol="hero")
    window = _window_on(project)

    window.delete_path(str(sprite))
    assert [entry.symbol for entry in project.assets()] == []


def test_delete_removes_the_assets_cached_bytes(qapp, tmp_path, confirm_yes):
    project = _project_with_files(tmp_path)
    sprite = project.folder / "hero.zx8x8"
    sprite.write_bytes(blank_sprite(8, 8).encode(with_header=False))
    entry = project.add_asset("hero.zx8x8", AssetKind.SPRITE_SHEET, symbol="hero")
    cache = asset_build.cache_path(project, entry.symbol)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(b"stale")
    window = _window_on(project)

    window.delete_path(str(sprite))
    assert not cache.exists()


def test_delete_warns_that_an_asset_goes_with_it(qapp, tmp_path, confirm_yes):
    project = _project_with_files(tmp_path)
    sprite = project.folder / "hero.zx8x8"
    sprite.write_bytes(blank_sprite(8, 8).encode(with_header=False))
    project.add_asset("hero.zx8x8", AssetKind.SPRITE_SHEET, symbol="hero")
    window = _window_on(project)

    window.delete_path(str(sprite))
    assert "hero" in confirm_yes[0]
    assert "manifest" in confirm_yes[0]


def test_a_sprite_sequence_goes_if_any_of_its_frames_does(qapp, tmp_path, confirm_yes):
    project = _project_with_files(tmp_path)
    for name in ("f0.bmp", "f1.bmp"):
        (project.folder / name).write_bytes(b"\x00")
    project.add_asset(["f0.bmp", "f1.bmp"], AssetKind.SPRITE_SEQUENCE, symbol="walk")
    window = _window_on(project)

    window.delete_path(str(project.folder / "f1.bmp"))
    assert project.assets() == []


# --- deleting a folder ----------------------------------------------------------------


def test_delete_folder_removes_it_and_its_contents(qapp, tmp_path, confirm_yes):
    project = _project_with_files(tmp_path)
    window = _window_on(project)
    folder = project.folder / "levels"

    assert window.delete_path(str(folder)) is True
    assert not folder.exists()


def test_delete_folder_says_how_much_goes_with_it(qapp, tmp_path, confirm_yes):
    project = _project_with_files(tmp_path)
    window = _window_on(project)

    window.delete_path(str(project.folder / "levels"))
    assert "2 items inside it" in confirm_yes[0]


def test_delete_folder_closes_tabs_for_files_inside_it(qapp, tmp_path, confirm_yes):
    project = _project_with_files(tmp_path)
    window = _window_on(project)
    inner = project.folder / "levels" / "one.asm"
    window.editor.open_file(str(inner))

    window.delete_path(str(project.folder / "levels"))
    open_paths = [window.editor.widget(i).property("file_path") for i in range(window.editor.count())]
    assert str(inner.resolve()) not in open_paths


def test_delete_folder_drops_assets_sourced_from_inside_it(qapp, tmp_path, confirm_yes):
    project = _project_with_files(tmp_path)
    (project.folder / "levels" / "hero.zx8x8").write_bytes(blank_sprite(8, 8).encode(with_header=False))
    project.add_asset("levels/hero.zx8x8", AssetKind.SPRITE_SHEET, symbol="hero")
    window = _window_on(project)

    window.delete_path(str(project.folder / "levels"))
    assert project.assets() == []


# --- guards ---------------------------------------------------------------------------


def test_cancelling_the_confirmation_deletes_nothing(qapp, tmp_path, confirm_cancel):
    project = _project_with_files(tmp_path)
    window = _window_on(project)
    target = project.folder / "notes.txt"

    assert window.delete_path(str(target)) is False
    assert target.exists()


def test_the_project_folder_itself_is_refused(qapp, tmp_path, monkeypatch):
    project = _project_with_files(tmp_path)
    window = _window_on(project)
    monkeypatch.setattr(
        main_window_module.QMessageBox, "information", staticmethod(lambda *_a, **_k: QMessageBox.Ok)
    )
    monkeypatch.setattr(
        main_window_module.QMessageBox, "warning", staticmethod(lambda *_a, **_k: QMessageBox.Yes)
    )

    assert window.delete_path(str(project.folder)) is False
    assert project.folder.exists()


def test_deleting_something_that_is_already_gone_is_a_no_op(qapp, tmp_path, confirm_yes):
    project = _project_with_files(tmp_path)
    window = _window_on(project)
    assert window.delete_path(str(project.folder / "nope.txt")) is False
    assert confirm_yes == []  # never even asked


def test_unrelated_assets_survive(qapp, tmp_path, confirm_yes):
    project = _project_with_files(tmp_path)
    for name in ("a.zx8x8", "b.zx8x8"):
        (project.folder / name).write_bytes(blank_sprite(8, 8).encode(with_header=False))
        project.add_asset(name, AssetKind.SPRITE_SHEET, symbol=name.split(".")[0])
    window = _window_on(project)

    window.delete_path(str(project.folder / "a.zx8x8"))
    assert [entry.symbol for entry in project.assets()] == ["b"]
