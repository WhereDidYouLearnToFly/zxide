"""Imports assets into a scratch project, builds it with the real sjasmplus, and
confirms the emitted snapshot places the converted bytes at the expected address.

This is the end-to-end proof the unit tests (converters, placement, asm generation)
can't give individually: that the whole chain -- import, convert, cache, place,
generate assets_generated.asm, assemble, snapshot -- actually agrees on where bytes
end up. Skipped if sjasmplus isn't on PATH, since it's an external tool this project
doesn't bundle (matching how the builder itself reports "not found" rather than
failing hard when it's missing).
"""

from __future__ import annotations

import shutil

import pytest

from tests.unit.bmp_fixtures import write_bmp24
from zxemu_core.assets.manifest import AssetKind
from zxemu_core.machine import Machine, Machine128
from zxemu_core.storage.snapshot import load_sna, load_sna_128k
from zxemu_ui.workspace import builder
from zxemu_ui.workspace.project import Project

pytestmark = pytest.mark.skipif(shutil.which("sjasmplus") is None, reason="sjasmplus not on PATH")


class _FakeSettings:
    def get(self, key, default=None):
        return default


def test_48k_bitmap_and_binary_assets_land_at_the_expected_address(tmp_path):
    project = Project.create(tmp_path / "p48", "P48", "48k")

    (project.folder / "sprite.bmp").write_bytes(write_bmp24(8, 8, lambda x, y: (0, 0, 0)))  # solid black -> all-ink
    sprite = project.add_asset(
        "sprite.bmp", AssetKind.SPRITE_SHEET, symbol="sprite",
        params={"frame_width": 8, "frame_height": 8, "layout": {"grid": {"cols": 1, "rows": 1}}},
    )
    project.set_asset_placement(sprite.id, "ram2", 100)

    (project.folder / "data.bin").write_bytes(bytes([1, 2, 3, 4]))
    data = project.add_asset("data.bin", AssetKind.BINARY, symbol="mydata")
    project.set_asset_placement(data.id, "ram3", 50)

    result = builder.build(project, _FakeSettings())
    assert result.ok, result.output

    machine = Machine(bytes(0x4000))
    load_sna(machine, result.snapshot.read_bytes())
    # ram2 is slot 2 (0x8000-0xBFFF); offset 100 -> 0x8064.
    assert [machine.memory.read_byte(0x8064 + i) for i in range(8)] == [0xFF] * 8
    # ram3 is slot 3 (0xC000-0xFFFF); offset 50 -> 0xC032.
    assert [machine.memory.read_byte(0xC032 + i) for i in range(4)] == [1, 2, 3, 4]


def test_128k_asset_lands_in_the_correct_physical_bank_regardless_of_paging(tmp_path):
    project = Project.create(tmp_path / "p128", "P128", "128k")

    (project.folder / "data.bin").write_bytes(bytes([9, 8, 7, 6]))
    entry = project.add_asset("data.bin", AssetKind.BINARY, symbol="mydata")
    project.set_asset_placement(entry.id, "ram3", 200)  # bank 3, never paged in at runtime by this build

    result = builder.build(project, _FakeSettings())
    assert result.ok, result.output

    machine = Machine128(bytes(0x4000), bytes(0x4000))
    load_sna_128k(machine, result.snapshot.read_bytes())
    assert list(machine.ram_banks[3].data[200:204]) == [9, 8, 7, 6]


def test_regenerating_after_moving_an_asset_updates_its_address(tmp_path):
    # Offsets deliberately clear of the template's own hand-written code (org $8000,
    # a few dozen bytes at the base of ram2) and the screen (the base of ram1) -- a
    # real collision there is the documented v1 limitation (memlayout doesn't know
    # where hand-written code lives), not what this test is checking.
    project = Project.create(tmp_path / "p48b", "P48b", "48k")
    (project.folder / "data.bin").write_bytes(bytes([1, 2, 3, 4]))
    entry = project.add_asset("data.bin", AssetKind.BINARY, symbol="mydata")
    project.set_asset_placement(entry.id, "ram3", 0)

    first = builder.build(project, _FakeSettings())
    assert first.ok, first.output
    machine = Machine(bytes(0x4000))
    load_sna(machine, first.snapshot.read_bytes())
    assert [machine.memory.read_byte(0xC000 + i) for i in range(4)] == [1, 2, 3, 4]

    project.set_asset_placement(entry.id, "ram2", 1000)
    second = builder.build(project, _FakeSettings())
    assert second.ok, second.output
    machine2 = Machine(bytes(0x4000))
    load_sna(machine2, second.snapshot.read_bytes())
    assert [machine2.memory.read_byte(0x8000 + 1000 + i) for i in range(4)] == [1, 2, 3, 4]


def test_hand_drawn_native_sprite_builds_with_correct_pixels_and_attrs(tmp_path):
    """Draw a sprite through the real editor's paint_pixel, then build it for real.

    This is the sprite-editor feature's own end-to-end proof: editor -> .zxspr.json ->
    convert -> place -> assemble -> snapshot, with the actual pixel and attribute
    bytes verified in the resulting memory image.
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtWidgets import QApplication

    _app = QApplication.instance() or QApplication([])  # keep a reference -- an unbound QApplication is GC'd

    from zxemu_core.assets.native_sprite import NATIVE_SUFFIX, blank_sprite_data
    from zxemu_ui.panels.sprite_editor_view import SpriteEditorView

    project = Project.create(tmp_path / "p48c", "P48c", "48k")
    path = project.folder / f"hero{NATIVE_SUFFIX}"
    path.write_text(__import__("json").dumps(blank_sprite_data(8, 8)))
    entry = project.add_asset(f"hero{NATIVE_SUFFIX}", AssetKind.SPRITE_SHEET, symbol="hero")
    project.set_asset_placement(entry.id, "ram3", 300)  # clear of the template's own code/screen

    editor = SpriteEditorView()
    editor.show_asset(project, entry)
    editor._ink_row._select(2)  # red
    editor._paper_row._select(5)  # cyan
    editor._bright_check.setChecked(True)
    editor.paint_pixel(0, 0, ink=True)  # top-left pixel: ink, claiming the cell's attribute
    editor.paint_pixel(7, 0, ink=False)  # top-right pixel: explicitly paper

    result = builder.build(project, _FakeSettings())
    assert result.ok, result.output

    machine = Machine(bytes(0x4000))
    load_sna(machine, result.snapshot.read_bytes())
    pixel_byte = machine.memory.read_byte(0xC000 + 300)  # ram3 offset 300 -> slot3 base + 300
    assert pixel_byte == 0x80  # only bit 7 (x=0) set
    attr_byte = machine.memory.read_byte(0xC000 + 300 + 8)  # attrs start right after the 8-byte pixel plane
    assert attr_byte & 0x07 == 2  # ink = red
    assert (attr_byte >> 3) & 0x07 == 5  # paper = cyan
    assert attr_byte & 0x40 == 0x40  # bright
