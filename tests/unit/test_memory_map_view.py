"""Tests for the memory map's Design mode / drag-drop placement (zxemu_ui.panels.memory_map_view)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt5.QtCore import QPoint, Qt  # noqa: E402
from PyQt5.QtGui import QMouseEvent  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from zxemu_core.assets.manifest import AssetKind  # noqa: E402
from zxemu_core.machine import Machine  # noqa: E402
from zxemu_core.machine import Machine128  # noqa: E402
from zxemu_ui.panels.memory_map_view import MemoryMapView  # noqa: E402
from zxemu_ui.workspace.project import Project  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _machine():
    return Machine(bytes(0x4000))


def _project(tmp_path):
    return Project.create(tmp_path / "p", "P", "48k")


def test_starts_in_debug_mode(qapp):
    view = MemoryMapView(_machine())
    assert view._canvas.mode == "debug"
    assert not view._auto_locate_button.isVisibleTo(view)


def test_toggling_design_switches_canvas_mode_and_shows_auto_locate(qapp):
    view = MemoryMapView(_machine())
    view._design_button.setChecked(True)
    assert view._canvas.mode == "design"
    assert view._auto_locate_button.isVisibleTo(view)


def test_set_project_propagates_to_canvas(qapp, tmp_path):
    view = MemoryMapView(_machine())
    project = _project(tmp_path)
    view.set_project(project)
    assert view.project is project
    assert view._canvas.project is project


def test_bank_id_for_slot_on_48k(qapp):
    view = MemoryMapView(_machine())
    paging = view.machine.paging_state()
    assert paging is None
    assert [view._canvas._bank_id_for_slot(i, paging) for i in range(4)] == ["rom", "ram1", "ram2", "ram3"]


def test_bank_id_for_slot_on_128k(qapp):
    view = MemoryMapView(Machine128(bytes(0x4000), bytes(0x4000)))
    paging = view.machine.paging_state()
    assert paging is not None
    ids = [view._canvas._bank_id_for_slot(i, paging) for i in range(4)]
    assert ids == ["rom0", "ram5", "ram2", "ram0"]  # power-on paging map


def test_design_mode_draws_a_placed_asset_rect(qapp, tmp_path):
    view = MemoryMapView(_machine())
    project = _project(tmp_path)
    entry = project.add_asset("a.bmp", AssetKind.BITMAP)
    project.set_asset_placement(entry.id, "ram2", 100)
    view.set_project(project)
    view._design_button.setChecked(True)
    view.resize(400, 200)

    paging, margin, gap, col_w, bar_top, bar_h, _bottom, _cols = view._canvas._geometry()
    rects = view._canvas._design_mode_rects(paging, margin, gap, col_w, bar_top, bar_h)
    assert entry.id in rects


def test_clicking_a_placed_asset_emits_asset_selected(qapp, tmp_path):
    view = MemoryMapView(_machine())
    project = _project(tmp_path)
    entry = project.add_asset("a.bmp", AssetKind.BITMAP)
    project.set_asset_placement(entry.id, "ram2", 100)
    view.set_project(project)
    view._design_button.setChecked(True)
    view.resize(400, 200)

    paging, margin, gap, col_w, bar_top, bar_h, _bottom, _cols = view._canvas._geometry()
    rect = view._canvas._design_mode_rects(paging, margin, gap, col_w, bar_top, bar_h)[entry.id]

    received = []
    view.asset_selected.connect(received.append)
    event = QMouseEvent(QMouseEvent.MouseButtonPress, rect.center().toPoint(), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(view._canvas, event)
    assert received == [entry.id]


def test_auto_locate_all_avoids_existing_placement(qapp, tmp_path):
    view = MemoryMapView(_machine())
    project = _project(tmp_path)
    placed = project.add_asset("a.bmp", AssetKind.BITMAP)
    project.set_asset_placement(placed.id, "ram2", 0)
    auto_asset = project.add_asset("b.bin", AssetKind.BINARY)
    view.set_project(project)

    view.auto_locate_all()

    updated = {e.id: e.placement for e in project.assets()}
    assert updated[placed.id] == {"bank": "ram2", "offset": 0}
    assert updated[auto_asset.id]["bank"] == "ram2"
    assert updated[auto_asset.id]["offset"] >= 32  # placeholder length of the already-placed asset


def test_auto_locate_all_does_nothing_without_a_project(qapp):
    view = MemoryMapView(_machine())
    view.auto_locate_all()  # must not raise
