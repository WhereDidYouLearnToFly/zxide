"""Tests for the record/stop buttons and how MainWindow wires them to the FrameRecorder.

The recorder itself is tested headlessly in test_recorder.py. What matters here is the
wiring: that the red dot attaches the recorder to the *emulation loop* (not to the repaint
signal), that stopping writes a file where the user will find it, and that nothing is
silently swallowed -- an empty take, a failed export, or a run that ended at the frame cap
all have to say so in the output console.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from zxemu_ui.controller import EmulatorController  # noqa: E402
from zxemu_ui.machine_factory import build_machine  # noqa: E402
from zxemu_ui.main_window import MainWindow  # noqa: E402
from zxemu_ui.workspace.project import Project  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _window_with_project(qapp, tmp_path):
    machine = build_machine("48k")
    window = MainWindow(machine, EmulatorController(machine))
    project = Project.create(tmp_path / "p", "P", "48k")
    window._open_project(str(project.folder))
    return window, project


def _record_frames(window, count):
    """Run ``count`` frames through the paused machine, as the emulation loop would."""
    for _ in range(count):
        window.controller.step_frame()


# --- starting and stopping ---------------------------------------------------


def test_record_attaches_the_recorder_to_the_emulation_loop(qapp, tmp_path):
    window, _ = _window_with_project(qapp, tmp_path)

    window._start_recording()

    # The hook the controller calls per *frame* -- not frame_ready, which batches.
    assert window.controller.frame_observer == window.recorder.capture
    assert window.recorder.recording


def test_the_buttons_swap_over_while_recording(qapp, tmp_path):
    window, _ = _window_with_project(qapp, tmp_path)
    panel = window.emulator_panel

    window._start_recording()
    assert not panel.record_action.isEnabled()
    assert panel.stop_record_action.isEnabled()

    window._stop_recording()
    assert panel.record_action.isEnabled()
    assert not panel.stop_record_action.isEnabled()


def test_stopping_detaches_the_hook_so_a_finished_take_costs_nothing(qapp, tmp_path):
    window, _ = _window_with_project(qapp, tmp_path)
    window._start_recording()
    window._stop_recording()
    assert window.controller.frame_observer is None


def test_every_stepped_frame_is_captured(qapp, tmp_path):
    window, _ = _window_with_project(qapp, tmp_path)
    window._start_recording()
    _record_frames(window, 7)
    assert window.recorder.frame_count == 7


# --- what lands on disk ------------------------------------------------------


def test_stopping_writes_a_gif_into_the_projects_recordings_folder(qapp, tmp_path):
    window, project = _window_with_project(qapp, tmp_path)
    window._start_recording()
    _record_frames(window, 5)

    window._stop_recording()

    written = list((project.folder / "recordings").glob("*.gif"))
    assert len(written) == 1
    assert written[0].stat().st_size > 0
    assert "Saved recording:" in window.output_console.toPlainText()


def test_the_captured_frames_are_released_after_export(qapp, tmp_path):
    # A minute of capture is ~21MB; holding it after the file is written is pure waste.
    window, _ = _window_with_project(qapp, tmp_path)
    window._start_recording()
    _record_frames(window, 5)
    window._stop_recording()
    assert window.recorder.frame_count == 0


def test_stopping_an_empty_take_writes_nothing_but_still_reports(qapp, tmp_path):
    window, project = _window_with_project(qapp, tmp_path)
    window._start_recording()

    window._stop_recording()

    assert not (project.folder / "recordings").exists()
    assert "no frames captured" in window.output_console.toPlainText()


def test_a_failed_gif_export_still_saves_the_frames_as_scr(qapp, tmp_path, monkeypatch):
    # Losing a recording to a missing optional dependency would be the worst outcome.
    window, project = _window_with_project(qapp, tmp_path)
    window._start_recording()
    _record_frames(window, 3)

    def boom(*args, **kwargs):
        raise RuntimeError("no Pillow here")

    monkeypatch.setattr(window.recorder, "export_gif", boom)
    window._stop_recording()

    rescued = list((project.folder / "recordings").rglob("*.scr"))
    assert len(rescued) == 3
    assert "saved 3 frames as .scr" in window.output_console.toPlainText()


def test_recording_without_a_project_falls_back_to_the_app_folder(qapp, tmp_path, monkeypatch):
    machine = build_machine("48k")
    window = MainWindow(machine, EmulatorController(machine))
    assert window.project is None

    import zxemu_ui.main_window as main_window_module

    fake_app_root = tmp_path / "app_root"
    (fake_app_root / "zxemu_ui").mkdir(parents=True)
    monkeypatch.setattr(main_window_module, "__file__", str(fake_app_root / "zxemu_ui" / "main_window.py"))

    window._start_recording()
    _record_frames(window, 3)
    window._stop_recording()

    assert len(list((fake_app_root / "recordings").glob("*.gif"))) == 1


# --- the frame cap -----------------------------------------------------------


def test_hitting_the_frame_cap_stops_the_take_and_says_so(qapp, tmp_path):
    window, project = _window_with_project(qapp, tmp_path)
    window.recorder.max_frames = 4
    window._start_recording()
    _record_frames(window, 10)  # step_frame emits frame_ready, which polls the progress

    assert window.recorder.frame_count == 0  # stopped, exported and cleared
    assert not window.emulator_panel.stop_record_action.isEnabled()
    log = window.output_console.toPlainText()
    assert "hit the 4-frame limit" in log
    assert "Saved recording:" in log
    assert len(list((project.folder / "recordings").glob("*.gif"))) == 1


def test_the_readout_shows_frames_and_seconds_while_recording(qapp, tmp_path):
    window, _ = _window_with_project(qapp, tmp_path)
    window._start_recording()
    _record_frames(window, 25)

    label = window.emulator_panel._record_label
    assert label.isVisibleTo(window.emulator_panel)
    assert "25 frames" in label.text()
    assert "0.5s" in label.text()
