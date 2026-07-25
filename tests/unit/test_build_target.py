"""Tests for *which* source a build assembles.

The entry point follows the file open in the editor rather than a fixed ``main.asm``,
because a folder zxide didn't scaffold names its entry point whatever it names it
(``fallout/fallout.asm``). Two halves are covered here: ``MainWindow._compile_target``
(deciding what the editor is pointing at) and ``builder.build`` (honouring it, and
deriving the snapshot name from that source's own ``savesna``).
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import subprocess  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import pytest  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from zxemu_ui.controller import EmulatorController  # noqa: E402
from zxemu_ui.machine_factory import build_machine  # noqa: E402
from zxemu_ui.main_window import MainWindow  # noqa: E402
from zxemu_ui.workspace import builder  # noqa: E402
from zxemu_ui.workspace.project import Project  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def _window_on(project) -> MainWindow:
    machine = build_machine("48k")
    window = MainWindow(machine, EmulatorController(machine))
    window._open_project(str(project.folder))
    return window


class _FakeSettings:
    def get(self, key, default=None):
        return default


# --- what the editor is pointing at ------------------------------------------------


def test_the_focused_source_file_is_the_build_entry_point(qapp, tmp_path):
    project = Project.create(tmp_path / "p", "P", "48k")
    (project.folder / "fallout.asm").write_text('savesna "fallout.sna", start\n', encoding="utf-8")
    window = _window_on(project)

    window.editor.open_file(str(project.folder / "fallout.asm"))

    assert window._compile_target() == "fallout.asm"


def test_a_source_in_a_subfolder_is_reported_project_relative(qapp, tmp_path):
    project = Project.create(tmp_path / "p", "P", "48k")
    (project.folder / "src").mkdir()
    (project.folder / "src" / "game.asm").write_text("nop\n", encoding="utf-8")
    window = _window_on(project)

    window.editor.open_file(str(project.folder / "src" / "game.asm"))

    assert window._compile_target() == os.path.join("src", "game.asm")


def test_a_non_source_text_tab_falls_back_to_the_manifest(qapp, tmp_path):
    """zxide.json is editable text but not assembleable -- don't try to build it."""
    project = Project.create(tmp_path / "p", "P", "48k")
    window = _window_on(project)

    window.editor.open_file(str(project.manifest_path))

    assert window._compile_target() is None


def test_an_include_file_is_not_a_build_target(qapp, tmp_path):
    """.inc is meant to be included by something else; assembling it directly is a mistake."""
    project = Project.create(tmp_path / "p", "P", "48k")
    (project.folder / "macros.inc").write_text("; macros\n", encoding="utf-8")
    window = _window_on(project)

    window.editor.open_file(str(project.folder / "macros.inc"))

    assert window._compile_target() is None


def test_a_source_outside_the_project_is_not_a_build_target(qapp, tmp_path):
    project = Project.create(tmp_path / "p", "P", "48k")
    stray = tmp_path / "elsewhere.asm"
    stray.write_text("nop\n", encoding="utf-8")
    window = _window_on(project)

    window.editor.open_file(str(stray))

    assert window._compile_target() is None


# --- the builder honouring it ------------------------------------------------------


@pytest.fixture
def fake_assembler(monkeypatch):
    """Stand in for sjasmplus: record the command, create whatever .sna is expected."""
    calls = []

    def fake_run(command, cwd=None, capture_output=False, text=False):
        calls.append(SimpleNamespace(command=command, cwd=cwd))
        expected = next((arg.split("=", 1)[1] for arg in command if arg.startswith("--sld=")), None)
        if expected:  # write both the snapshot and the SLD the real assembler would
            from pathlib import Path
            sld = Path(expected)
            sld.write_text("|SLD data|\n", encoding="utf-8")
            sld.with_suffix(".sna").write_bytes(bytes(49179))
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def test_build_assembles_the_requested_source_not_the_manifests_main(tmp_path, fake_assembler):
    project = Project.create(tmp_path / "p", "P", "48k")
    (project.folder / "fallout.asm").write_text('savesna "fallout.sna", start\n', encoding="utf-8")

    result = builder.build(project, _FakeSettings(), "fallout.asm")

    assert "fallout.asm" in fake_assembler[0].command
    assert "main.asm" not in fake_assembler[0].command
    assert result.ok
    # The output name comes from the source's own savesna, not the manifest's main.sna.
    assert result.snapshot.name == "fallout.sna"
    assert result.sld.name == "fallout.sld"


def test_build_without_an_explicit_source_still_uses_the_manifests_main(tmp_path, fake_assembler):
    project = Project.create(tmp_path / "p", "P", "48k")

    result = builder.build(project, _FakeSettings())

    assert "main.asm" in fake_assembler[0].command
    assert result.ok


def test_a_missing_source_is_reported_clearly_without_running_the_assembler(tmp_path, fake_assembler):
    project = Project.create(tmp_path / "p", "P", "48k")

    result = builder.build(project, _FakeSettings(), "nope.asm")

    assert not fake_assembler  # never got as far as the assembler
    assert result.returncode == 1
    assert "nope.asm" in result.output and "does not exist" in result.output


def test_a_source_with_no_savesna_says_so_instead_of_failing_silently(tmp_path, monkeypatch):
    """Assembling cleanly but writing no snapshot used to read as an unexplained failure."""
    project = Project.create(tmp_path / "p", "P", "48k")
    (project.folder / "fragment.asm").write_text("    nop\n", encoding="utf-8")
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    result = builder.build(project, _FakeSettings(), "fragment.asm")

    assert not result.ok
    assert "no snapshot" in result.output
    assert "savesna" in result.output
