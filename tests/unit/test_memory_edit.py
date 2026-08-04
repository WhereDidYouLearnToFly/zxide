"""Relocating a region by rewriting the one line that decides its address.

The risk this module carries is not "does the arithmetic work" but "does it edit the right
line, and only that line". A tool that rewrites a project's memory-map table has to be
surgical and has to refuse when it isn't sure, so most of what is pinned here is the shape
of the edit and the cases where it declines.
"""

from __future__ import annotations

import pytest

from zxemu_ui.workspace.memory_edit import Anchor, NotMovable, anchor_for, arrange, plan_bank_change, rewrite, snap
from zxemu_ui.workspace.memory_plan import build_plan
from zxemu_ui.workspace.project import Project

MEMMAP = "Workplace   equ $6000\nAttributes  equ $8300       ; 00D7\nGame        equ $8C50       ; 179;\n"


def _project(tmp_path, main_source, files=None):
    project = Project.create(tmp_path / "p", "P", "48k")
    (project.folder / "main.asm").write_text(main_source, encoding="utf-8")
    for name, text in (files or {}).items():
        path = project.folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return project


def _region(project, name):
    return next(region for region in build_plan(project).regions if region.name == name)


# --- finding the line ----------------------------------------------------------------


def test_a_symbol_org_anchors_on_the_equ_that_defines_it(tmp_path):
    project = _project(
        tmp_path,
        '    include "sys/memmap.i"\n    org Attributes\n    MODULE attribs\n    ds 16\n    ENDMODULE\n',
        {"sys/memmap.i": MEMMAP},
    )
    anchor = anchor_for(project, _region(project, "attribs"))
    assert (anchor.kind, anchor.symbol, anchor.line) == ("equ", "Attributes", 2)
    assert anchor.display == "memmap.i:2"
    assert anchor.path.endswith("memmap.i")


def test_a_literal_org_anchors_on_its_own_line(tmp_path):
    project = _project(tmp_path, "    org $8181\n    MODULE im2\n    ds 16\n    ENDMODULE\n")
    anchor = anchor_for(project, _region(project, "im2"))
    assert (anchor.kind, anchor.line, anchor.display) == ("org", 1, "main.asm:1")


def test_an_expression_org_refuses_rather_than_guesses(tmp_path):
    project = _project(
        tmp_path,
        '    include "sys/memmap.i"\n    org Attributes + 32\n    MODULE late\n    ds 4\n    ENDMODULE\n',
        {"sys/memmap.i": MEMMAP},
    )
    with pytest.raises(NotMovable, match="expression"):
        anchor_for(project, _region(project, "late"))


def test_an_unknown_symbol_refuses(tmp_path):
    project = _project(tmp_path, "Nowhere equ $9000\n    org Nowhere\n    MODULE m\n    ds 4\n    ENDMODULE\n")
    region = _region(project, "m")
    region.org_expression = "Missing"
    with pytest.raises(NotMovable, match="cannot find"):
        anchor_for(project, region)


# --- rewriting it --------------------------------------------------------------------


def test_rewrite_keeps_alignment_and_the_trailing_comment():
    anchor = Anchor(path="x", line=2, kind="equ", symbol="Attributes", display="memmap.i:2")
    assert rewrite("Attributes  equ $8300       ; 00D7", anchor, 0x9000) == "Attributes  equ $9000       ; 00D7"


def test_rewrite_keeps_the_notation_it_found():
    equ = Anchor(path="x", line=1, kind="equ", symbol="A", display="d")
    assert rewrite("A equ $8300", equ, 0x9abc) == "A equ $9ABC"
    assert rewrite("A equ $8300 ", equ, 0x9abc).endswith(" ")
    assert rewrite("A equ #8300", equ, 0x9ABC) == "A equ #9ABC"
    assert rewrite("A equ 0x8300", equ, 0x9ABC) == "A equ 0x9ABC"
    assert rewrite("A equ 8300h", equ, 0x9ABC) == "A equ 9ABCh"
    assert rewrite("A equ 33536", equ, 0x9ABC) == "A equ 39612"


def test_rewrite_handles_the_colon_and_equals_forms():
    anchor = Anchor(path="x", line=1, kind="equ", symbol="A", display="d")
    assert rewrite("A: equ $8300", anchor, 0x4000) == "A: equ $4000"
    assert rewrite("A = $8300", anchor, 0x4000) == "A = $4000"


def test_rewrite_an_org_line_keeps_its_comment():
    anchor = Anchor(path="x", line=1, kind="org", symbol="", display="d")
    assert rewrite("    org $8181                ; the IM2 routine", anchor, 0x8200) == "    org $8200                ; the IM2 routine"


def test_rewrite_refuses_a_line_that_changed_underneath_it():
    anchor = Anchor(path="x", line=1, kind="equ", symbol="A", display="memmap.i:1")
    with pytest.raises(NotMovable, match="no longer looks like"):
        rewrite("    ld a,1", anchor, 0x8000)


# --- moving a block into another bank -------------------------------------------------


def test_bank_change_inserts_slot_and_page_above_the_org():
    lines = ["    include \"x.i\"", "    org $C000", "    MODULE late"]
    change = plan_bank_change(lines, 2, "ram3", "128k")
    assert change.edits == []
    assert (change.insert_at, change.inserted) == (2, ["    SLOT 3", "    PAGE 3"])


def test_inserted_directives_copy_the_orgs_indentation():
    lines = ["\t\torg $C000"]
    assert plan_bank_change(lines, 1, "ram7", "128k").inserted == ["\t\tSLOT 3", "\t\tPAGE 7"]


def test_an_existing_slot_page_pair_is_updated_not_duplicated():
    lines = ["    SLOT 3", "    PAGE 1", "    org $C000"]
    change = plan_bank_change(lines, 3, "ram6", "128k")
    assert change.edits == [(1, "    SLOT 3"), (2, "    PAGE 6")]
    assert change.inserted == []


def test_directives_far_above_the_org_are_left_alone():
    """They belong to some earlier block; rewriting them would move that one instead."""
    lines = ["    SLOT 3", "    PAGE 1"] + ["    nop"] * 8 + ["    org $C000"]
    change = plan_bank_change(lines, 11, "ram6", "128k")
    assert change.edits == []
    assert change.inserted == ["    SLOT 3", "    PAGE 6"]


def test_an_unpaged_machine_needs_no_directives_at_all():
    """A 48K's banks are its slots -- the address alone already says which one."""
    assert plan_bank_change(["    org $C000"], 1, "ram3", "48k").empty


def test_moving_into_the_fixed_banks_still_states_their_slot():
    assert plan_bank_change(["    org $4000"], 1, "ram5", "128k").inserted == ["    SLOT 1", "    PAGE 5"]
    assert plan_bank_change(["    org $8000"], 1, "ram2", "128k").inserted == ["    SLOT 2", "    PAGE 2"]


# --- where a drag lands --------------------------------------------------------------


class _Block:
    def __init__(self, bank, offset, length):
        self.bank, self.offset, self.length = bank, offset, length

    @property
    def end(self):
        return self.offset + self.length


def test_a_drag_rounds_to_the_grid_when_nothing_is_near():
    dragged = _Block("ram2", 0, 256)
    assert snap(0x8C37, dragged, []) == 0x8C00


def test_a_drag_snaps_flush_after_a_neighbour():
    neighbour = _Block("ram2", 0x100, 0x80)   # ends at $8180
    dragged = _Block("ram2", 0x1000, 0x40)
    assert snap(0x8190, dragged, [neighbour]) == 0x8180


def test_a_drag_snaps_flush_before_a_neighbour():
    neighbour = _Block("ram2", 0x400, 0x100)  # starts at $8400
    dragged = _Block("ram2", 0x1000, 0x40)
    assert snap(0x83d0, dragged, [neighbour]) == 0x83C0  # its end meets $8400


def test_a_neighbour_in_another_bank_does_not_attract():
    elsewhere = _Block("ram3", 0x100, 0x80)
    dragged = _Block("ram2", 0x1000, 0x40)
    assert snap(0x8190, dragged, [elsewhere]) == 0x8100  # grid, not magnet


# --- arrange -------------------------------------------------------------------------


def test_arrange_packs_a_bank_tight_in_order():
    blocks = [_Block("ram2", 0, 100), _Block("ram2", 500, 50), _Block("ram2", 900, 25)]
    for block in blocks:
        block.slot, block.bank = 2, "ram2"
    moves = arrange(blocks, {id(block) for block in blocks})
    assert [moves.get(id(block)) for block in blocks] == [None, 0x8064, 0x8096]


def test_arrange_leaves_immovable_blocks_alone_and_steps_over_them():
    movable_a = _Block("ram2", 0, 100)
    fixed = _Block("ram2", 100, 100)
    movable_b = _Block("ram2", 900, 50)
    blocks = [movable_a, fixed, movable_b]
    for block in blocks:
        block.slot, block.bank = 2, "ram2"
    moves = arrange(blocks, {id(movable_a), id(movable_b)})
    assert id(fixed) not in moves
    assert moves[id(movable_b)] == 0x8000 + 200  # placed after the fixed block, not on it


def test_arrange_reports_nothing_when_everything_already_fits_tight():
    blocks = [_Block("ram2", 0, 100), _Block("ram2", 100, 50)]
    for block in blocks:
        block.slot, block.bank = 2, "ram2"
    assert arrange(blocks, {id(block) for block in blocks}) == {}


def test_arrange_stops_rather_than_wrapping_past_the_end_of_a_bank():
    big = _Block("ram2", 0, 16000)
    spill = _Block("ram2", 16100, 1000)
    for block in (big, spill):
        block.slot, block.bank = 2, "ram2"
    moves = arrange([big, spill], {id(big), id(spill)})
    assert id(spill) not in moves  # would not fit after `big`, so it is left where it is


# --- constraints the source states ---------------------------------------------------


class _Pinned:
    """The shape anchor_for/snap/arrange care about, without a whole project behind it."""

    def __init__(self, name="im2routine", pinned=False, align=0, bank="ram2", offset=0, length=43):
        self.name, self.pinned, self.align = name, pinned, align
        self.bank, self.offset, self.length = bank, offset, length
        self.slot, self.org_expression, self.origin, self.line = 2, "$8181", "interrupt.asm", 55

    @property
    def end(self):
        return self.offset + self.length


def test_a_pinned_block_refuses_to_move(tmp_path):
    project = _project(tmp_path, "    org $8181\n    ds 4\n")
    with pytest.raises(NotMovable, match="pinned"):
        anchor_for(project, _Pinned(pinned=True))


def test_an_aligned_block_snaps_to_its_boundary_not_to_a_neighbour():
    """An IM2 table magneted flush against its neighbour stops being addressable at all."""
    table = _Pinned(name="im2table", align=256, offset=0x200, length=257)
    neighbour = _Block("ram2", 0x340, 16)  # would be a magnet target without the alignment
    assert snap(0x8347, table, [neighbour]) == 0x8300


def test_arrange_keeps_an_aligned_block_on_its_boundary():
    fixed = _Pinned(name="im2routine", pinned=True, offset=0x181, length=43)
    table = _Pinned(name="im2table", align=256, offset=0x200, length=257)
    for block in (fixed, table):
        block.slot, block.bank = 2, "ram2"
    moves = arrange([fixed, table], {id(table)})
    assert moves == {}  # $200 is already the first aligned slot clear of the pinned handler


def test_arrange_moves_an_aligned_block_only_between_boundaries():
    table = _Pinned(name="tbl", align=256, offset=0x900, length=257)
    table.slot, table.bank = 2, "ram2"
    moves = arrange([table], {id(table)}, start=0x140)
    assert moves[id(table)] % 256 == 0


def test_arrange_realigns_after_stepping_over_a_pinned_block():
    """Skipping an obstacle can land off the boundary; rounding up can land on another.
    Getting this wrong leaves an IM2 table one byte out, which is silently fatal."""
    pinned_low = _Pinned(name="a", pinned=True, offset=0x000, length=0x150)
    pinned_high = _Pinned(name="b", pinned=True, offset=0x200, length=0x010)
    table = _Pinned(name="tbl", align=256, offset=0x900, length=64)
    for block in (pinned_low, pinned_high, table):
        block.slot, block.bank = 2, "ram2"
    moves = arrange([pinned_low, pinned_high, table], {id(table)})
    landed = moves[id(table)] - 0x8000
    assert landed % 256 == 0                       # still on a boundary...
    assert landed >= pinned_high.end               # ...and clear of the block it had to step over
