"""Tests for the project tree's asset badges (zxemu_ui.project_tree_model).

The property that matters: a file the manifest calls an asset must be distinguishable
in the tree from a file of the *same type* that it doesn't. Without that, ``hero.zx8x8``
(converted, placed, addressable from code) and a stray file beside it look identical,
and telling them apart means opening ``zxide.json``.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtGui import QIcon  # noqa: E402
from PyQt5.QtWidgets import QApplication, QMessageBox  # noqa: E402

from zxemu_core.assets.manifest import AssetKind  # noqa: E402
from zxemu_core.assets.native_sprite import blank_sprite  # noqa: E402
from zxemu_ui import main_window as main_window_module  # noqa: E402
from zxemu_ui.controller import EmulatorController  # noqa: E402
from zxemu_ui.machine_factory import build_machine  # noqa: E402
from zxemu_ui.main_window import MainWindow  # noqa: E402
from zxemu_ui.project_tree_model import ProjectFilesModel  # noqa: E402
from zxemu_ui.workspace.project import Project  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def _project_with_assets(tmp_path) -> Project:
    project = Project.create(tmp_path / "p", "P", "48k")
    (project.folder / "hero.zx8x8").write_bytes(blank_sprite(8, 8).encode(with_header=False))
    project.add_asset("hero.zx8x8", AssetKind.SPRITE_SHEET, symbol="hero")
    (project.folder / "boom.zxsfx").write_text("3977,4\n")
    project.add_asset("boom.zxsfx", AssetKind.BEEPER_SFX, symbol="boom")
    # Same file type as hero, but never added to the project.
    (project.folder / "stray.zx8x8").write_bytes(blank_sprite(8, 8).encode(with_header=False))
    return project


def _model_on(project) -> ProjectFilesModel:
    model = ProjectFilesModel()
    model.setRootPath(str(project.folder))
    model.set_project(project)
    return model


# --- the lookup ------------------------------------------------------------------------


def test_a_registered_file_resolves_to_its_asset(qapp, tmp_path):
    project = _project_with_assets(tmp_path)
    model = _model_on(project)
    entry = model.asset_for(project.folder / "hero.zx8x8")
    assert entry is not None and entry.symbol == "hero"
    assert entry.kind is AssetKind.SPRITE_SHEET


def test_an_unregistered_file_of_the_same_type_does_not(qapp, tmp_path):
    project = _project_with_assets(tmp_path)
    model = _model_on(project)
    assert model.asset_for(project.folder / "stray.zx8x8") is None


def test_a_plain_source_file_is_not_an_asset(qapp, tmp_path):
    project = _project_with_assets(tmp_path)
    model = _model_on(project)
    assert model.asset_for(project.folder / "main.asm") is None


def test_the_lookup_survives_separator_and_case_differences(qapp, tmp_path):
    """The manifest stores `levels\\hero.zx8x8`; Qt hands back `C:/p/levels/hero.zx8x8`."""
    project = Project.create(tmp_path / "p", "P", "48k")
    (project.folder / "levels").mkdir()
    (project.folder / "levels" / "hero.zx8x8").write_bytes(blank_sprite(8, 8).encode(with_header=False))
    project.add_asset(str(project.relative(project.folder / "levels" / "hero.zx8x8")),
                      AssetKind.SPRITE_SHEET, symbol="hero")
    model = _model_on(project)

    forward_slashes = f"{project.folder.as_posix()}/levels/hero.zx8x8"
    assert model.asset_for(forward_slashes) is not None


def test_every_frame_of_a_sprite_sequence_is_badged(qapp, tmp_path):
    project = Project.create(tmp_path / "p", "P", "48k")
    for name in ("f0.bmp", "f1.bmp"):
        (project.folder / name).write_bytes(b"\x00")
    project.add_asset(["f0.bmp", "f1.bmp"], AssetKind.SPRITE_SEQUENCE, symbol="walk")
    model = _model_on(project)

    assert model.asset_for(project.folder / "f0.bmp").symbol == "walk"
    assert model.asset_for(project.folder / "f1.bmp").symbol == "walk"


def test_with_no_project_nothing_is_an_asset(qapp, tmp_path):
    model = ProjectFilesModel()
    assert model.asset_for(tmp_path / "anything.zx8x8") is None


# --- the decoration ---------------------------------------------------------------------


def _row_for(model, project, name):
    root = model.index(str(project.folder))
    model.fetchMore(root)
    QApplication.processEvents()
    for row in range(model.rowCount(root)):
        index = model.index(row, 0, root)
        if model.data(index, Qt.DisplayRole) == name:
            return index
    raise AssertionError(f"{name} not listed in the tree")


def test_every_file_is_listed_asset_or_not(qapp, tmp_path):
    """The badge is a decoration, never a filter -- a project folder shows what's in it."""
    project = _project_with_assets(tmp_path)
    model = _model_on(project)
    for name in ("hero.zx8x8", "boom.zxsfx", "stray.zx8x8", "main.asm", "zxide.json"):
        assert _row_for(model, project, name).isValid()


def test_a_registered_asset_gets_a_kind_tooltip(qapp, tmp_path):
    project = _project_with_assets(tmp_path)
    model = _model_on(project)
    index = _row_for(model, project, "hero.zx8x8")
    assert model.data(index, Qt.ToolTipRole) == "hero — sprite_sheet asset"


def test_an_unregistered_file_keeps_the_plain_tooltip(qapp, tmp_path):
    project = _project_with_assets(tmp_path)
    model = _model_on(project)
    index = _row_for(model, project, "stray.zx8x8")
    assert model.data(index, Qt.ToolTipRole) != "hero — sprite_sheet asset"


def test_a_registered_asset_is_decorated_with_its_kind_icon(qapp, tmp_path):
    project = _project_with_assets(tmp_path)
    model = _model_on(project)
    index = _row_for(model, project, "hero.zx8x8")
    icon = model.data(index, Qt.DecorationRole)
    assert isinstance(icon, QIcon) and not icon.isNull()


def test_two_kinds_get_two_different_icons(qapp, tmp_path):
    project = _project_with_assets(tmp_path)
    model = _model_on(project)
    sprite = model.data(_row_for(model, project, "hero.zx8x8"), Qt.DecorationRole)
    sfx = model.data(_row_for(model, project, "boom.zxsfx"), Qt.DecorationRole)
    assert sprite.cacheKey() != sfx.cacheKey()


def test_refresh_assets_picks_up_a_newly_added_asset(qapp, tmp_path):
    project = _project_with_assets(tmp_path)
    model = _model_on(project)
    assert model.asset_for(project.folder / "stray.zx8x8") is None

    project.add_asset("stray.zx8x8", AssetKind.SPRITE_SHEET, symbol="stray")
    model.refresh_assets()
    assert model.asset_for(project.folder / "stray.zx8x8").symbol == "stray"


# --- adopting a file that isn't an asset yet ----------------------------------------------


def _window_on(project) -> MainWindow:
    machine = build_machine("48k")
    window = MainWindow(machine, EmulatorController(machine))
    window._open_project(str(project.folder))
    return window


@pytest.fixture
def answer_yes(monkeypatch):
    asked = []

    def fake_question(_parent, _title, text, *_args, **_kwargs):
        asked.append(text)
        return QMessageBox.Yes

    monkeypatch.setattr(main_window_module.QMessageBox, "question", staticmethod(fake_question))
    return asked


def test_opening_a_registered_asset_needs_no_prompt(qapp, tmp_path, answer_yes):
    project = _project_with_assets(tmp_path)
    window = _window_on(project)
    assert window._open_asset_editor_for_path(str(project.folder / "hero.zx8x8")) is True
    assert answer_yes == []  # never asked


def test_opening_an_unregistered_sprite_offers_to_add_it(qapp, tmp_path, answer_yes):
    project = _project_with_assets(tmp_path)
    window = _window_on(project)

    assert window._open_asset_editor_for_path(str(project.folder / "stray.zx8x8")) is True
    assert "isn't one of this project's assets yet" in answer_yes[0]
    assert "stray" in [entry.symbol for entry in project.assets()]


def test_the_newly_added_asset_is_badged_immediately(qapp, tmp_path, answer_yes):
    project = _project_with_assets(tmp_path)
    window = _window_on(project)
    window._open_asset_editor_for_path(str(project.folder / "stray.zx8x8"))
    assert window._fs_model.asset_for(project.folder / "stray.zx8x8") is not None


def test_declining_leaves_the_project_alone(qapp, tmp_path, monkeypatch):
    project = _project_with_assets(tmp_path)
    window = _window_on(project)
    monkeypatch.setattr(
        main_window_module.QMessageBox, "question",
        staticmethod(lambda *_a, **_k: QMessageBox.Cancel),
    )

    assert window._open_asset_editor_for_path(str(project.folder / "stray.zx8x8")) is False
    assert "stray" not in [entry.symbol for entry in project.assets()]


def test_a_file_type_no_editor_handles_is_declined_without_asking(qapp, tmp_path, answer_yes):
    project = _project_with_assets(tmp_path)
    window = _window_on(project)
    assert window._open_asset_editor_for_path(str(project.folder / "main.asm")) is False
    assert answer_yes == []


def test_an_unregistered_sfx_file_is_offered_as_a_beeper_asset(qapp, tmp_path, answer_yes):
    project = _project_with_assets(tmp_path)
    (project.folder / "zap.zxsfx").write_text("100,4\n")
    window = _window_on(project)

    assert window._open_asset_editor_for_path(str(project.folder / "zap.zxsfx")) is True
    entry = next(e for e in project.assets() if e.symbol == "zap")
    assert entry.kind is AssetKind.BEEPER_SFX


def test_a_file_outside_the_project_says_so_rather_than_adding_it(qapp, tmp_path, monkeypatch):
    project = _project_with_assets(tmp_path)
    outside = tmp_path / "elsewhere.zx8x8"
    outside.write_bytes(blank_sprite(8, 8).encode(with_header=False))
    window = _window_on(project)

    told = []
    monkeypatch.setattr(
        main_window_module.QMessageBox, "information",
        staticmethod(lambda _p, _t, text, *_a, **_k: told.append(text) or QMessageBox.Ok),
    )

    assert window._open_asset_editor_for_path(str(outside)) is False
    assert "outside the project folder" in told[0]
    assert len(project.assets()) == 2  # unchanged
