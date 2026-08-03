"""Constant scanning and expression evaluation behind the editor's hover help."""

from pathlib import Path

from zxemu_core.debug import asm_help, asm_symbols


def test_finds_both_definition_styles():
    table = asm_symbols.collect("SCREEN: equ $4000\nATTRS equ 22528\n")
    assert table["screen"].value == 0x4000
    assert table["attrs"].value == 22528


def test_reassignable_and_define_forms():
    table = asm_symbols.collect("COUNT = 3\nSTEP: defl 8\nDEFINE WIDTH 32\n")
    assert (table["count"].value, table["step"].value, table["width"].value) == (3, 8, 32)


def test_number_notations():
    source = "A1: equ $4000\nA2: equ #4000\nA3: equ 4000h\nA4: equ %1010\nA5: equ 1010b\nA6: equ 0x10\nA7: equ 'A'\n"
    values = [constant.value for _, constant in sorted(asm_symbols.collect(source).items())]
    assert values == [0x4000, 0x4000, 0x4000, 10, 10, 16, 65]


def test_expressions_and_forward_references():
    source = "END: equ SCREEN + LENGTH\nSCREEN: equ $4000\nLENGTH: equ 6144\nMASK: equ (1 << 3) | %1\nHALF: equ LENGTH / 2\n"
    table = asm_symbols.collect(source)
    assert table["end"].value == 0x5800  # defined before the names it uses, as assemblers allow
    assert table["mask"].value == 9
    assert table["half"].value == 3072


def test_unresolvable_expressions_keep_their_text():
    table = asm_symbols.collect("HERE: equ $\nOTHER: equ UNKNOWN+1\nLOOP: equ LOOP+1\n")
    assert table["here"].value is None      # `$` is the assembler's address, not ours to know
    assert table["other"].value is None     # names we never saw defined
    assert table["loop"].value is None      # self-reference gives up rather than recursing
    assert table["other"].expression == "UNKNOWN+1"


def test_comments_and_quotes_do_not_define_constants():
    table = asm_symbols.collect('; FAKE: equ 1\n    db "REAL: equ 2"\nREAL: equ 3\n')
    assert "fake" not in table
    assert table["real"].value == 3


def test_registers_are_never_constants():
    """A file may define `c`; a `jr c,loop` still must not report it."""
    table = asm_symbols.collect("c: equ 5\n")
    assert table == {}


def test_references_finds_names_in_order_ignoring_strings():
    table = asm_symbols.collect("SCREEN: equ $4000\nSTEP: equ 2\n")
    assert [c.name for c in asm_symbols.references("    ld hl,SCREEN+STEP", table)] == ["SCREEN", "STEP"]
    assert asm_symbols.references('    db "SCREEN"', table) == []
    assert asm_symbols.references("    ld hl,SCREEN  ; STEP", table)[0].name == "SCREEN"


def test_includes_are_followed_through_the_reader():
    files = {"consts.asm": "SCREEN: equ $4000\n", "more.asm": "STEP: equ SCREEN/2\n"}
    read = lambda path: files.get(Path(path).name.lower())  # resolve() anchors to a drive on Windows
    source = 'include "consts.asm"\ninclude "more.asm"\n    ld hl,SCREEN\n'
    table = asm_symbols.collect(source, base_dir="/p", read_source=read)
    assert table["screen"].value == 0x4000
    assert table["step"].value == 0x2000
    assert table["screen"].origin == "consts.asm"  # shown in the tooltip so you know where to look


def test_local_definition_wins_over_an_include():
    read = lambda path: "SCREEN: equ $4000\n"
    table = asm_symbols.collect('include "consts.asm"\nSCREEN: equ $C000\n', base_dir="/p", read_source=read)
    assert table["screen"].value == 0xC000


def test_include_cycle_terminates():
    read = lambda path: 'include "a.asm"\ninclude "b.asm"\nVALUE: equ 7\n'
    table = asm_symbols.collect('include "a.asm"\n', base_dir="/p", read_source=read)
    assert table["value"].value == 7


def test_hover_appends_constants_to_instruction_help():
    table = asm_symbols.collect("SCREEN: equ $4000\n")
    text = asm_help.describe("    ld hl,SCREEN", 6, table).as_text()
    assert "Copy a value" in text          # the instruction help is still the headline
    assert "SCREEN = 16384 ($4000)" in text


def test_hover_shows_the_working_for_a_derived_constant():
    table = asm_symbols.collect("SCREEN: equ $4000\nEND: equ SCREEN + 6144\n")
    assert "END = SCREEN + 6144 = 22528 ($5800)" in asm_help.describe("    ld de,END", 6, table).as_text()


def test_hover_answers_a_line_with_no_instruction():
    table = asm_symbols.collect("WIDTH: equ 32\n")
    help_text = asm_help.describe("    drawSprite WIDTH", 6, table)
    assert help_text is not None and help_text.as_text().endswith("WIDTH = 32 ($0020)")


def test_hover_without_a_symbol_table_is_unchanged():
    assert asm_help.describe("    ld hl,SCREEN", 6).as_text().count("\n") == 3  # no constants line
    assert asm_help.describe("    drawSprite WIDTH", 6) is None
