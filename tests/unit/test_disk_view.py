"""The Disk Drives panel: what is mounted, what is on it, and whether it is at risk.

The panel exists for the questions a menu cannot answer, so the tests are about those:
does it show the catalogue without the machine's help, does it surface the "modified,
unsaved" state that costs you work if missed, and does it ask the window to act rather
than acting itself.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from zxemu_core.storage.disk.scl import parse_scl  # noqa: E402
from zxemu_ui.machine_factory import build_machine  # noqa: E402
from zxemu_ui.panels.disk_view import DiskView  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def _disk(*files):
    """files: (name, sectors, fill)."""
    entries, payload = b"", b""
    for name, sectors, fill in files:
        entries += (name.ljust(8).encode() + b"C" + b"\x00\x80" + b"\x00\x03"
                    + bytes([sectors]))
        payload += bytes([fill]) * (sectors * 256)
    scl = b"SINCLAIR" + bytes([len(files)]) + entries + payload + b"\x00\x00\x00\x00"
    return parse_scl(scl, "TESTDISK.scl")


def test_an_empty_drive_says_so(qapp):
    view = DiskView(build_machine("pentagon"))
    assert "No disk" in view._summary.text()
    assert view._table.rowCount() == 0


def test_a_machine_without_an_interface_explains_itself(qapp):
    """A 48K has nowhere to put a disk, and "No disk" would be a misleading answer to
    the question the user is actually asking."""
    view = DiskView(build_machine("48k"))
    assert "no disk interface" in view._summary.text()


def test_it_lists_the_catalogue_straight_from_the_image(qapp):
    """Without asking the machine -- which is the point. TR-DOS's own CAT needs a healthy
    machine, and the moment you most want the catalogue is when a load has just failed."""
    machine = build_machine("pentagon")
    machine.beta_drives[0] = _disk(("HELLO", 3, 0x11), ("WORLD", 2, 0x22))
    view = DiskView(machine)

    assert view._table.rowCount() == 2
    assert view._table.item(0, 0).text() == "HELLO.C"
    assert view._table.item(1, 0).text() == "WORLD.C"
    assert "2 file(s)" in view._summary.text()


def test_it_shows_when_a_disk_has_unsaved_changes(qapp):
    """The one piece of state available nowhere else, and the one that loses work."""
    machine = build_machine("pentagon")
    image = _disk(("HELLO", 1, 0x11))
    machine.beta_drives[0] = image
    view = DiskView(machine)
    assert "unsaved" not in view._summary.text()

    image.write_sector(1, 0, 1, b"\xFF" * 256)
    view.refresh()

    assert "unsaved" in view._summary.text()


def test_the_write_protect_box_follows_the_disk(qapp):
    machine = build_machine("pentagon")
    image = _disk(("HELLO", 1, 0x11))
    image.write_protected = True
    machine.beta_drives[0] = image
    view = DiskView(machine)

    assert view._protect_box.isChecked()


def test_toggling_write_protect_asks_rather_than_acts(qapp):
    """The panel owns no policy: the window holds the machine and the dialogs, so this
    stays a view instead of becoming a second implementation of the Disk Drive menu."""
    machine = build_machine("pentagon")
    machine.beta_drives[0] = _disk(("HELLO", 1, 0x11))
    view = DiskView(machine)
    seen = []
    view.write_protect_changed.connect(lambda drive, on: seen.append((drive, on)))

    view._protect_box.setChecked(True)

    assert seen == [(0, True)]


def test_refreshing_after_a_disk_is_mounted_does_not_re_emit(qapp):
    """refresh() sets the checkbox from the image; if that fed back out as a user action
    the panel would fight whatever set it."""
    machine = build_machine("pentagon")
    image = _disk(("HELLO", 1, 0x11))
    image.write_protected = True
    machine.beta_drives[0] = image
    view = DiskView(machine)
    seen = []
    view.write_protect_changed.connect(lambda drive, on: seen.append((drive, on)))

    view.refresh()

    assert seen == []


def test_switching_drive_shows_the_other_bay(qapp):
    machine = build_machine("pentagon")
    machine.beta_drives[0] = _disk(("INDRIVEA", 1, 0x11))
    machine.beta_drives[1] = _disk(("INDRIVEB", 1, 0x22))
    view = DiskView(machine)
    assert view._table.item(0, 0).text() == "INDRIVEA.C"

    view._drive_box.setCurrentIndex(1)

    assert view._table.item(0, 0).text() == "INDRIVEB.C"
