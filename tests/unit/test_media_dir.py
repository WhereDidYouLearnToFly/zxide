"""The Load dialogs remember where you last got media from.

Tapes, disks and snapshots live in a collection folder and almost never inside the project
you have open, so opening every dialog at the project meant walking the same long path
again for each format. One remembered folder, shared across all of them, because a .tzx and
a .trd from the same collection sit side by side.
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
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp):
    machine = build_machine("48k")
    return MainWindow(machine, EmulatorController(machine))


def _tap(folder, name="game.tap"):
    """A minimal but genuinely loadable .tap: one block of (flag, payload, checksum)."""
    folder.mkdir(parents=True, exist_ok=True)
    body = bytes([0xFF, 0x01]) + bytes([0xFF ^ 0x01])
    path = folder / name
    path.write_bytes(bytes([len(body) & 0xFF, len(body) >> 8]) + body)
    return path


def test_loading_media_remembers_its_folder(window, tmp_path):
    tape = _tap(tmp_path / "collection")

    window._load_media(str(tape))

    assert window.settings.get("last_media_dir") == str(tmp_path / "collection")
    assert window._media_dir() == str(tmp_path / "collection")


def test_every_load_dialog_shares_the_one_folder(window, tmp_path, monkeypatch):
    """The point of the feature: loading a tape from somewhere makes the *disk* dialog
    open there too. One folder, not one per format."""
    window._load_media(str(_tap(tmp_path / "collection")))
    seen = []

    class _FakeFileDialog:
        @staticmethod
        def getOpenFileName(*args):  # noqa: N802 (Qt naming)
            seen.append(args[2])     # the start directory
            return "", ""

    monkeypatch.setattr("zxemu_ui.main_window.QFileDialog", _FakeFileDialog)

    from zxemu_ui import media
    for fmt in media.FORMATS:
        window._load_format_dialog(fmt)
    window._mount_disk_dialog(1)

    assert seen == [str(tmp_path / "collection")] * (len(media.FORMATS) + 1)


def test_it_falls_back_to_the_project_before_anything_is_loaded(window, tmp_path):
    project = Project.create(tmp_path / "proj", "Proj", "48k")
    window._open_project(str(project.folder))

    assert window._media_dir() == str(project.folder)


def test_a_folder_that_has_since_vanished_is_not_offered(window, tmp_path):
    """Media collections live on removable drives and get moved. Opening a dialog at a
    path that no longer exists is worse than opening at the default."""
    gone = tmp_path / "gone"
    window._load_media(str(_tap(gone)))
    assert window._media_dir() == str(gone)

    for item in gone.iterdir():
        item.unlink()
    gone.rmdir()

    assert window._media_dir() == ""      # no project open either, so the plain default
