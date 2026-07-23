"""Tests for MainWindow._save_screenshot (the .scr + .bmp screenshot feature)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt5.QtGui import QImage  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from zxemu_ui.controller import EmulatorController  # noqa: E402
from zxemu_ui.machine_factory import build_machine  # noqa: E402
from zxemu_ui.main_window import MainWindow  # noqa: E402
from zxemu_ui.panels.emulator_view import FULL_HEIGHT, FULL_WIDTH  # noqa: E402
from zxemu_ui.workspace.project import Project  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _window(qapp):
    machine = build_machine("48k")
    controller = EmulatorController(machine)
    return MainWindow(machine, controller)


def test_save_screenshot_writes_both_files_to_project_folder(qapp, tmp_path):
    window = _window(qapp)
    project = Project.create(tmp_path / "p", "P", "48k")
    window._open_project(str(project.folder))

    window._save_screenshot()

    shots = list((project.folder / "screenshots").iterdir())
    suffixes = sorted(p.suffix for p in shots)
    assert suffixes == [".bmp", ".scr"]


def test_scr_file_is_exactly_6912_bytes_and_matches_display_memory(qapp, tmp_path):
    window = _window(qapp)
    project = Project.create(tmp_path / "p", "P", "48k")
    window._open_project(str(project.folder))

    window._save_screenshot()

    scr_path = next((project.folder / "screenshots").glob("*.scr"))
    data = scr_path.read_bytes()
    assert len(data) == 6912
    assert data == bytes(window.machine.display_memory()[:6912])


def test_bmp_file_is_native_resolution_not_scaled_widget_size(qapp, tmp_path):
    window = _window(qapp)
    project = Project.create(tmp_path / "p", "P", "48k")
    window._open_project(str(project.folder))
    window.resize(1200, 900)  # a widget size that doesn't match the native emulator resolution

    window._save_screenshot()

    bmp_path = next((project.folder / "screenshots").glob("*.bmp"))
    image = QImage(str(bmp_path))
    assert (image.width(), image.height()) == (FULL_WIDTH, FULL_HEIGHT)


def test_two_screenshots_in_the_same_second_get_distinct_or_overwritten_files_safely(qapp, tmp_path):
    # Whether or not two rapid saves collide on the same timestamped name, this must
    # never raise -- overwriting a screenshot from the same second is an acceptable
    # outcome, crashing is not.
    window = _window(qapp)
    project = Project.create(tmp_path / "p", "P", "48k")
    window._open_project(str(project.folder))

    window._save_screenshot()
    window._save_screenshot()

    shots = list((project.folder / "screenshots").iterdir())
    assert len(shots) >= 2


def test_save_screenshot_without_a_project_falls_back_to_app_folder(qapp, tmp_path, monkeypatch):
    window = _window(qapp)
    assert window.project is None

    # Redirect the app-folder fallback to a scratch directory so this test doesn't
    # write into the real repo.
    import zxemu_ui.main_window as main_window_module

    fake_app_root = tmp_path / "app_root"
    fake_app_root.mkdir()
    monkeypatch.setattr(main_window_module, "__file__", str(fake_app_root / "zxemu_ui" / "main_window.py"))
    (fake_app_root / "zxemu_ui").mkdir()

    window._save_screenshot()

    shots = list((fake_app_root / "screenshots").iterdir())
    assert len(shots) == 2


def test_save_screenshot_logs_to_output_console(qapp, tmp_path):
    window = _window(qapp)
    project = Project.create(tmp_path / "p", "P", "48k")
    window._open_project(str(project.folder))

    window._save_screenshot()

    assert "Saved screenshot:" in window.output_console.toPlainText()
