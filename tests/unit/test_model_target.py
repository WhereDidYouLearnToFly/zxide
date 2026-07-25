"""The machine you're emulating and the machine your project builds for.

The Model menu switches the emulator *and* retargets the open project, deliberately: the
choice has to stick, or reopening the project would silently switch back and its build
template would no longer match. Settings ▸ Project ▸ Target machine sets the same field
without rebooting the emulator.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from zxemu_ui.controller import EmulatorController  # noqa: E402
from zxemu_ui.machine_factory import build_machine, machine_model  # noqa: E402
from zxemu_ui.main_window import MainWindow  # noqa: E402
from zxemu_ui.workspace.project import Project  # noqa: E402
from zxemu_ui.workspace.settings_dialog import SettingsDialog  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def _window_on_128k_project(qapp, tmp_path):
    project = Project.create(tmp_path / "p128", "P128", "128k")
    machine = build_machine("128k")
    window = MainWindow(machine, EmulatorController(machine))
    window._open_project(str(project.folder))
    window.output_console.clear_output()
    return window, project


def test_switching_the_model_retargets_the_open_project(qapp, tmp_path):
    """The switch has to stick: otherwise reopening the project switches back under you."""
    window, project = _window_on_128k_project(qapp, tmp_path)

    window._switch_model("48k")

    assert machine_model(window.machine) == "48k"
    assert Project(project.folder).model == "48k"


def test_switching_says_what_it_changed(qapp, tmp_path):
    """Writing to a project's manifest is not something to do quietly."""
    window, _project = _window_on_128k_project(qapp, tmp_path)

    window._switch_model("48k")

    log = window.output_console.toPlainText()
    assert "Switched to the 48K machine." in log
    assert "now targets 48K" in log


def test_switching_with_no_project_open_just_switches(qapp, tmp_path):
    machine = build_machine("128k")
    window = MainWindow(machine, EmulatorController(machine))
    window.project = None

    window._switch_model("48k")

    assert machine_model(window.machine) == "48k"


def test_re_selecting_the_current_model_does_not_reset_the_machine(qapp, tmp_path):
    window, _project = _window_on_128k_project(qapp, tmp_path)
    machine = window.machine

    window._switch_model("128k")

    assert window.machine is machine  # same object: no reboot, nothing lost


def test_the_settings_dialog_is_where_a_project_gets_retargeted(qapp, tmp_path):
    window, project = _window_on_128k_project(qapp, tmp_path)
    dialog = SettingsDialog(window.settings, project)

    index = dialog._model_combo.findData("48k")
    assert index >= 0
    dialog._model_combo.setCurrentIndex(index)
    dialog._accept()

    assert Project(project.folder).model == "48k"


def test_the_settings_dialog_shows_the_projects_current_target(qapp, tmp_path):
    window, project = _window_on_128k_project(qapp, tmp_path)
    dialog = SettingsDialog(window.settings, project)
    assert dialog._model_combo.currentData() == "128k"


def test_the_settings_dialog_copes_with_no_project_open(qapp, tmp_path):
    machine = build_machine("48k")
    window = MainWindow(machine, EmulatorController(machine))
    dialog = SettingsDialog(window.settings, None)
    assert dialog._model_combo is None
    dialog._accept()  # must not raise
