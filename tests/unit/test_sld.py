"""Unit tests for the SLD (source-level debug) parser."""

from zxemu_ui.workspace import sld

# A small SLD sample: a metadata (Z) record, two executable (T) records, and a
# define (D) record that must be ignored.
SAMPLE = (
    "|SLD.data.version|1\n"
    "main.asm|1||0|-1|-1|Z|meta\n"
    "main.asm|18||0|2|32768|T|\n"
    "main.asm|21||0|2|32772|T|\n"
    "zxspectrum.asm|3||0|-1|654|D|SOME_DEF\n"
)


def test_lines_map_to_addresses(tmp_path):
    (tmp_path / "main.asm").write_text("x")
    source_map = sld.parse(SAMPLE, base_dir=tmp_path)
    main = str(tmp_path / "main.asm")

    assert source_map.address_for(main, 18) == 32768
    assert source_map.address_for(main, 21) == 32772
    assert source_map.address_for(main, 99) is None  # no code on that line


def test_only_trace_records_are_used(tmp_path):
    (tmp_path / "main.asm").write_text("x")
    source_map = sld.parse(SAMPLE, base_dir=tmp_path)
    # 654 came from a D (define) record, not executable code -> not mapped.
    assert source_map.line_for(654) is None
    assert source_map.line_for(32768) == (str((tmp_path / "main.asm").resolve()), 18)


def test_breakpoint_addresses(tmp_path):
    (tmp_path / "main.asm").write_text("x")
    source_map = sld.parse(SAMPLE, base_dir=tmp_path)
    main = str(tmp_path / "main.asm")
    assert source_map.breakpoint_addresses(main, {18, 21, 99}) == {32768, 32772}


def test_addresses_by_slot_groups_trace_records_by_slot(tmp_path):
    (tmp_path / "main.asm").write_text("x")
    source_map = sld.parse(SAMPLE, base_dir=tmp_path)
    assert source_map.addresses_by_slot == {2: {32768, 32772}}


def test_addresses_by_slot_ignores_non_trace_records(tmp_path):
    # The Z (metadata) record has slot -1 and must not pollute addresses_by_slot.
    (tmp_path / "main.asm").write_text("x")
    source_map = sld.parse(SAMPLE, base_dir=tmp_path)
    assert -1 not in source_map.addresses_by_slot


def test_addresses_by_slot_separates_multiple_slots(tmp_path):
    text = SAMPLE + "main.asm|30||0|3|49152|T|\n"
    (tmp_path / "main.asm").write_text("x")
    source_map = sld.parse(text, base_dir=tmp_path)
    assert source_map.addresses_by_slot == {2: {32768, 32772}, 3: {49152}}
