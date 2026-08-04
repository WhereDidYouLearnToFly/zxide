"""The project-wide memory plan (zxemu_ui.workspace.memory_plan).

Where ``test_asm_layout`` pins the parser, these pin the *combination*: the scan plus the
manifest's assets plus the last build's SLD, and the two things that combination exists to
produce -- a conflict list, and a free-space seed good enough that auto-locate stops
dropping an asset on top of hand-written code.
"""

from __future__ import annotations

from zxemu_core.assets.manifest import AssetKind
from zxemu_ui.workspace.asset_build import cache_path, resolve_auto_placements
from zxemu_ui.workspace.memory_plan import build_plan
from zxemu_ui.workspace.project import Project


def _project(tmp_path, main_source, model="48k"):
    project = Project.create(tmp_path / "p", "P", model)
    (project.folder / "main.asm").write_text(main_source, encoding="utf-8")
    return project


def _cached_asset(project, name, size, kind=AssetKind.BINARY):
    """An asset whose bytes are already cached, so its length is exact rather than a placeholder."""
    entry = project.add_asset(name, kind)
    (project.folder / name).write_bytes(b"\x00" * size)
    path = cache_path(project, entry.symbol)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * size)
    return entry


def test_plan_finds_the_regions_of_the_main_source(tmp_path):
    project = _project(tmp_path, "    org $8000\nstart:\n    ret\n")
    plan = build_plan(project)
    assert [(region.name, region.bank, region.offset, region.length) for region in plan.regions] == [("start", "ram2", 0, 1)]
    assert plan.conflicts == []
    assert not plan.built


def test_plan_follows_includes_from_main(tmp_path):
    project = _project(tmp_path, '    org $8000\nmain:\n    ret\n    include "extra.asm"\n')
    (project.folder / "extra.asm").write_text("    org $c000\ntable:\n    db 1,2,3\n", encoding="utf-8")
    plan = build_plan(project)
    assert [(region.name, region.origin) for region in plan.regions] == [("main", "main.asm"), ("table", "extra.asm")]


def test_unsaved_editor_text_wins_when_a_reader_is_supplied(tmp_path):
    """Refresh has to show the org you just typed, not the one you last saved."""
    project = _project(tmp_path, "    org $8000\nsaved:\n    ret\n")
    edited = {str(project.folder / "main.asm"): "    org $9000\nunsaved:\n    ret\n"}
    plan = build_plan(project, read_source=edited.get)
    assert [(region.name, region.address) for region in plan.regions] == [("unsaved", 0x9000)]


def test_placed_assets_become_claims_alongside_the_code(tmp_path):
    project = _project(tmp_path, "    org $8000\nstart:\n    ret\n")
    entry = _cached_asset(project, "hero.bin", 64)
    project.set_asset_placement(entry.id, "ram3", 0x100)
    plan = build_plan(project)
    assert [(asset.name, asset.kind, asset.bank, asset.length) for asset in plan.assets] == [("hero", "asset", "ram3", 64)]
    assert plan.conflicts == []


def test_an_asset_placed_on_the_code_is_reported_as_a_conflict(tmp_path):
    project = _project(tmp_path, "    org $8000\nstart:\n    ds 512\n")
    entry = _cached_asset(project, "hero.bin", 64)
    project.set_asset_placement(entry.id, "ram2", 0x10)
    conflicts = build_plan(project).conflicts
    assert len(conflicts) == 1
    assert (conflicts[0].first, conflicts[0].second, conflicts[0].length) == ("start", "hero", 64)
    assert "overlaps" in conflicts[0].describe()


def test_the_generated_asset_include_is_not_counted_twice(tmp_path):
    """Its blocks *are* the manifest's assets; counting both would have each overlap itself."""
    project = _project(tmp_path, '    org $8000\nstart:\n    ret\n    include "assets_generated.asm"\n')
    entry = _cached_asset(project, "hero.bin", 64)
    project.set_asset_placement(entry.id, "ram3", 0)
    (project.folder / "assets_generated.asm").write_text('    org $c000\nhero:\n    incbin "hero.bin"\n', encoding="utf-8")
    plan = build_plan(project)
    assert [region.name for region in plan.regions] == ["start"]
    assert plan.conflicts == []


def test_ambiguous_banks_stay_out_of_the_occupied_map(tmp_path):
    """Reserving a 128K slot-3 offset in all eight banks would cost a third of RAM on a guess."""
    project = _project(tmp_path, "    device zxspectrum128\n    org $c000\nlate:\n    ds 100\n", model="128k")
    plan = build_plan(project)
    assert plan.regions[0].ambiguous_bank
    assert plan.occupied() == {}


def test_occupied_lists_every_claim_by_bank(tmp_path):
    project = _project(tmp_path, "    org $8000\nstart:\n    ds 32\n")
    entry = _cached_asset(project, "hero.bin", 16)
    project.set_asset_placement(entry.id, "ram3", 0x40)
    assert build_plan(project).occupied() == {"ram2": [(0, 32)], "ram3": [(0x40, 16)]}


def test_auto_locate_avoids_scanned_code_before_any_build(tmp_path):
    """The point of the whole exercise: no .sld exists yet, and the asset still misses the code."""
    project = _project(tmp_path, "    org $8000\nstart:\n    ds 1024\n")
    entry = _cached_asset(project, "hero.bin", 256)
    resolve_auto_placements(project, build_plan(project).occupied())
    placement = project.assets()[0].placement
    assert placement != "auto"
    if placement["bank"] == "ram2":
        assert placement["offset"] >= 1024  # clear of the org $8000 block


def test_without_the_plan_auto_locate_would_have_collided(tmp_path):
    """Pins that the previous behaviour really was the collision, so the fix isn't a no-op."""
    project = _project(tmp_path, "    org $8000\nstart:\n    ds 1024\n")
    _cached_asset(project, "hero.bin", 256)
    resolve_auto_placements(project)  # no plan passed: the old, SLD-only seeding
    placement = project.assets()[0].placement
    assert (placement["bank"], placement["offset"]) == ("ram2", 0)


def test_sld_makes_an_estimated_region_exact(tmp_path, monkeypatch):
    from zxemu_ui.workspace import memory_plan

    project = _project(tmp_path, "    org $8000\nstart:\n    ret\n    DRAW_SOMETHING 1\n")
    assert build_plan(project).regions[0].estimated  # the macro call it cannot price

    monkeypatch.setattr(memory_plan.asset_build, "reserved_code_ranges", lambda _project: {"ram2": [(0, 300)]})
    plan = build_plan(project)
    assert plan.built
    assert (plan.regions[0].length, plan.regions[0].estimated) == (300, False)


def test_sld_extension_is_clamped_to_the_next_region(tmp_path, monkeypatch):
    from zxemu_ui.workspace import memory_plan

    project = _project(tmp_path, "    org $8000\nfirst:\n    ret\n    org $8100\nsecond:\n    ret\n")
    monkeypatch.setattr(memory_plan.asset_build, "reserved_code_ranges", lambda _project: {"ram2": [(0, 9999)]})
    first = build_plan(project).regions[0]
    assert first.length == 0x100  # not 9999, which would swallow `second`


def test_the_plan_follows_the_source_you_would_build(tmp_path):
    """A test program in tests/ has its own memory map, and running it moves the plan onto it."""
    project = _project(tmp_path, "    org $8000\ngame:\n    ret\n")
    (project.folder / "main.asm").write_text('    org $8000\ngame:\n    ret\n    savesna "main.sna", game\n', encoding="utf-8")
    (project.folder / "tests").mkdir()
    (project.folder / "tests" / "sound_test.asm").write_text('    org $9000\nsound:\n    ds 8\n    savesna "sound_test.sna", sound\n', encoding="utf-8")

    plan = build_plan(project, main="tests/sound_test.asm")
    assert [(region.name, region.address) for region in plan.regions] == [("sound", 0x9000)]
    assert plan.entries == ["tests/sound_test.asm"]


def test_an_include_you_are_editing_does_not_become_the_plan(tmp_path):
    """It has no savesna, so it is not a program -- scanning it alone would hide the rest."""
    project = _project(tmp_path, '    org $8000\ngame:\n    ret\n    include "part.asm"\n    savesna "main.sna", game\n')
    (project.folder / "part.asm").write_text("    org $9000\npart:\n    ds 4\n", encoding="utf-8")

    plan = build_plan(project, main="part.asm")
    assert [region.name for region in plan.regions] == ["game", "part"]
    assert plan.entries == ["main.asm"]


def test_a_missing_main_source_gives_an_empty_plan(tmp_path):
    project = Project.create(tmp_path / "p", "P", "48k")
    (project.folder / "main.asm").unlink()
    plan = build_plan(project)
    assert (plan.regions, plan.assets, plan.conflicts) == ([], [], [])
