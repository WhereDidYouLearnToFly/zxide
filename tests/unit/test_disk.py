"""Unit tests for TR-DOS disk images and the WD1793 controller.

The controller's tests lean on one hard-won lesson, recorded here because it cost a
debugging session: the chip's *handshake lines* matter as much as its data. TR-DOS
watches INTRQ and DRQ on port 0xFF and never reads the status register during a
transfer, so getting a flag's lifetime wrong produces "No disk" for a disk that is
mounted, readable, and correct in every other respect.
"""

import pytest

from zxemu_core.storage.disk import beta as beta_module
from zxemu_core.storage.disk.scl import parse_scl
from zxemu_core.storage.disk.trd import (
    INFO_OFFSET,
    SECTOR_SIZE,
    SECTORS_PER_TRACK,
    TRACK_SIZE,
    TRDOS_ID,
    TrdImage,
    parse_trd,
    sector_offset,
)
from zxemu_core.storage.disk.wd1793 import (
    IDLE,
    S_NOT_READY,
    S_RECORD_NOT_FOUND,
    WD1793,
)


def _blank(tracks: int = 80, sides: int = 2) -> bytes:
    return bytes(tracks * sides * TRACK_SIZE)


def _formatted(label: str = "TESTDISK", files: int = 0, free: int = 2544) -> TrdImage:
    """A disk with a plausible information block, as TR-DOS would leave one."""
    image = TrdImage(_blank())
    block = bytearray(0x20)
    block[0x03] = 0x16          # 80 tracks, double sided
    block[0x04] = files
    block[0x05] = free & 0xFF
    block[0x06] = free >> 8
    block[0x07] = TRDOS_ID
    block[0x15:0x1D] = label.ljust(8).encode()
    image.data[INFO_OFFSET:INFO_OFFSET + 0x20] = block
    return image


# --- geometry -------------------------------------------------------------------

def test_the_sector_formula_interleaves_the_two_sides():
    """Cylinder 0 side 1 comes *between* cylinder 0 side 0 and cylinder 1 side 0. Getting
    this wrong reads the right bytes from the wrong half of the disk."""
    assert sector_offset(0, 0, 1, sides=2) == 0
    assert sector_offset(0, 0, 16, sides=2) == 15 * SECTOR_SIZE
    assert sector_offset(0, 1, 1, sides=2) == TRACK_SIZE
    assert sector_offset(1, 0, 1, sides=2) == 2 * TRACK_SIZE
    # Single-sided disks have no interleave to do.
    assert sector_offset(1, 0, 1, sides=1) == TRACK_SIZE


def test_sectors_are_numbered_from_one():
    """The off-by-one this format invites: sector 1 is at offset 0."""
    image = TrdImage(_blank())
    image.write_sector(0, 0, 1, b"\xAA" * SECTOR_SIZE)
    assert image.data[0] == 0xAA


def test_geometry_comes_from_the_disks_own_type_byte():
    """Not from the file size, which a truncated image makes a liar of."""
    image = _formatted()
    image.data[INFO_OFFSET + 0x03] = 0x19       # 40 tracks, single sided
    reread = TrdImage(bytes(image.data))
    assert (reread.tracks, reread.sides) == (40, 1)


def test_a_truncated_image_still_reads_as_a_whole_disk():
    """Images routinely stop after the last used sector. The rest of the disk is blank,
    not missing -- refusing to read it would reject most of a real collection."""
    image = TrdImage(bytes(TRACK_SIZE), tracks=80, sides=2)
    assert image.read_sector(40, 0, 1) == b"\x00" * SECTOR_SIZE
    assert image.read_sector(79, 1, 16) is not None


def test_writing_past_the_end_grows_the_image():
    image = TrdImage(bytes(TRACK_SIZE), tracks=80, sides=2)
    assert image.write_sector(40, 0, 1, b"\x5A" * SECTOR_SIZE)
    assert image.read_sector(40, 0, 1) == b"\x5A" * SECTOR_SIZE


def test_a_sector_outside_the_geometry_is_refused():
    image = TrdImage(_blank(tracks=40, sides=1), tracks=40, sides=1)
    assert image.read_sector(40, 0, 1) is None      # past the last track
    assert image.read_sector(0, 1, 1) is None       # second side of a one-sided disk
    assert image.read_sector(0, 0, 17) is None      # 17 sectors on a 16-sector track


def test_too_short_to_hold_track_zero_is_not_a_disk():
    with pytest.raises(ValueError, match="too short"):
        parse_trd(b"\x00" * 100)


# --- the catalogue ---------------------------------------------------------------

def _entry(name, ext, length, sectors, track, sector):
    return (name.ljust(8).encode() + ext.encode()
            + bytes([0x00, 0x80])                       # start address
            + bytes([length & 0xFF, length >> 8, sectors, sector, track]))


def test_the_catalogue_stops_at_the_end_marker():
    """A zero first byte ends it. Scanning all 128 slots would invent files out of
    whatever junk happens to follow."""
    image = _formatted(files=2)
    image.data[0:16] = _entry("FIRST", "C", 512, 2, 1, 0)
    image.data[16:32] = _entry("SECOND", "B", 300, 2, 1, 2)
    image.data[48:64] = _entry("GHOST", "C", 999, 4, 9, 0)   # after the terminator

    names = [f.name for f in image.catalogue()]
    assert names == ["FIRST", "SECOND"]


def test_deleted_files_are_hidden_but_findable():
    image = _formatted(files=2)
    image.data[0:16] = _entry("GONE", "C", 512, 2, 1, 0)
    image.data[0] = 0x01                                    # TR-DOS's deleted marker
    image.data[16:32] = _entry("KEPT", "B", 300, 2, 1, 2)

    assert [f.name for f in image.catalogue()] == ["KEPT"]
    both = image.catalogue(include_deleted=True)
    assert [f.deleted for f in both] == [True, False]


def test_decorative_entries_past_the_file_count_are_not_files():
    """Found by boot-sweeping the library: one real disk lists 27 "files" by the end
    marker alone, where TR-DOS lists 12. The slots past the count hold a maker's
    signature -- zero length, start position track 0 sector 0 -- and they do not begin
    with the 0x00 terminator, so only the information block's count rules them out."""
    image = _formatted(files=2)
    image.data[0:16] = _entry("REAL1", "C", 512, 2, 1, 0)
    image.data[16:32] = _entry("REAL2", "C", 512, 2, 1, 2)
    image.data[32:48] = _entry("BY ME!", "?", 0, 0, 0, 0)      # signature, not a file
    image.data[48:64] = _entry("GREETZ", "?", 0, 0, 0, 0)

    assert [f.name for f in image.catalogue()] == ["REAL1", "REAL2"]


def test_an_unreadable_information_block_falls_back_to_the_end_marker():
    """With no trustworthy count, the terminator is all there is -- better to list a
    signature as a file than to list nothing at all."""
    image = TrdImage(_blank())                                  # no TR-DOS id
    image.data[0:16] = _entry("ONLY", "C", 512, 2, 1, 0)
    assert [f.name for f in image.catalogue()] == ["ONLY"]


def test_an_unformatted_disk_mounts_and_says_so():
    """FORMAT has to start somewhere, so a disk with no TR-DOS id is mountable -- but
    the caller is told, because it is also what a corrupt image looks like."""
    image = parse_trd(_blank())
    assert image.info().valid is False


# --- SCL --------------------------------------------------------------------------

def _scl(*files) -> bytes:
    """files: (name, ext, sectors, payload_byte)."""
    entries, payload = b"", b""
    for name, ext, sectors, fill in files:
        entries += (name.ljust(8).encode() + ext.encode() + b"\x00\x80"
                    + b"\x00\x01" + bytes([sectors]))
        payload += bytes([fill]) * (sectors * SECTOR_SIZE)
    return b"SINCLAIR" + bytes([len(files)]) + entries + payload + b"\x00\x00\x00\x00"


def test_scl_lays_files_out_contiguously_from_track_one():
    """SCL stores no positions, because TR-DOS files are contiguous and allocated in
    order -- so each file's place is fixed by the lengths of the ones before it."""
    image = parse_scl(_scl(("ONE", "C", 3, 0x11), ("TWO", "C", 2, 0x22)))

    first, second = image.catalogue()
    assert (first.start_track, first.start_sector) == (1, 0)
    assert (second.start_track, second.start_sector) == (1, 3)
    # A catalogue "track" is a *logical* track, folding the two sides together, so
    # logical track 1 is cylinder 0 side 1 -- not cylinder 1. TR-DOS does the same split
    # before it talks to the controller (cylinder = track // sides, head = track % sides),
    # which is exactly why the TRD layout interleaves the sides in the first place.
    assert image.read_sector(0, 1, 1) == bytes([0x11]) * SECTOR_SIZE
    assert image.read_sector(0, 1, 4) == bytes([0x22]) * SECTOR_SIZE


def test_scl_writes_an_information_block_or_tr_dos_rejects_the_disk():
    image = parse_scl(_scl(("ONE", "C", 3, 0x11)), name="demo.scl")
    info = image.info()
    assert info.valid                       # the id byte TR-DOS checks
    assert info.file_count == 1
    assert info.first_free_track == 1 and info.first_free_sector == 3
    assert info.label == "demo"             # SCL has no label; the filename stands in


def test_a_converted_scl_starts_clean():
    """It was built, not loaded, so there is nothing to save back until the machine
    writes something."""
    assert parse_scl(_scl(("ONE", "C", 1, 0x11))).dirty is False


def test_a_non_scl_is_rejected():
    with pytest.raises(ValueError, match="SINCLAIR"):
        parse_scl(b"not a disk at all")


def test_an_scl_claiming_more_files_than_it_holds_is_rejected():
    truncated = b"SINCLAIR" + bytes([50])    # 50 files, no catalogue behind them
    with pytest.raises(ValueError, match="truncated"):
        parse_scl(truncated)


# --- the controller ---------------------------------------------------------------

def _controller(image=None):
    drives = [image, None, None, None]
    clock = {"t": 0}
    fdc = WD1793(drives, clock=lambda: clock["t"])
    return fdc, clock


def test_reading_a_sector_serves_its_bytes_one_at_a_time():
    image = _formatted()
    image.write_sector(0, 0, 9, bytes(range(256)))
    fdc, _ = _controller(image)
    fdc.track, fdc.sector = 0, 9

    fdc.write_command(0x80)                  # Read Sector
    got = bytes(fdc.read_data() for _ in range(SECTOR_SIZE))

    assert got == bytes(range(256))
    assert fdc.intrq and not fdc.drq         # transfer over, interrupt raised


def test_writing_a_command_clears_intrq():
    """The regression that produced "No disk" against a perfectly good image. TR-DOS
    polls INTRQ on port 0xFF to spot a finished transfer and never reads the status
    register while one is running -- so a stale INTRQ ends the next read after one byte.
    The datasheet clears it on a command write; so do we."""
    fdc, _ = _controller(_formatted())
    fdc.write_command(0x00)                  # Restore -> completes, raises INTRQ
    assert fdc.intrq

    fdc.sector = 1
    fdc.write_command(0x80)                  # Read Sector

    assert not fdc.intrq
    assert fdc.drq


def test_reading_the_status_register_also_clears_intrq():
    fdc, _ = _controller(_formatted())
    fdc.write_command(0x00)
    assert fdc.intrq
    fdc.read_status()
    assert not fdc.intrq


def test_an_empty_drive_reports_not_ready():
    fdc, _ = _controller(None)
    fdc.write_command(0x00)
    assert fdc.read_status() & S_NOT_READY


def test_a_missing_sector_is_a_record_not_found():
    fdc, _ = _controller(_formatted())
    fdc.sector = 17                          # tracks hold 16
    fdc.write_command(0x80)
    assert fdc.read_status() & S_RECORD_NOT_FOUND


def test_the_index_pulse_comes_and_goes_with_the_clock():
    """TR-DOS uses it to decide a drive is spinning. A bit that never changes reads as a
    dead drive no matter what is mounted."""
    fdc, clock = _controller(_formatted())
    fdc.write_command(0x00)                  # a type I command, so status shows INDEX

    clock["t"] = 0
    assert fdc.read_status() & beta_module.STATUS_DRQ == 0  # (type I: bit 1 is INDEX)
    assert fdc._index_pulse()
    clock["t"] = 300_000
    assert not fdc._index_pulse()


def test_a_seek_moves_the_head_and_restore_brings_it_back():
    fdc, _ = _controller(_formatted())
    fdc.data = 40
    fdc.write_command(0x10)                  # Seek
    assert fdc.position == 40 and fdc.track == 40

    fdc.write_command(0x00)                  # Restore
    assert fdc.position == 0 and fdc.track == 0


def test_read_address_reports_where_the_head_really_is():
    """Not where the track register claims -- that is the disagreement TR-DOS uses this
    command to detect."""
    fdc, _ = _controller(_formatted())
    fdc.data = 12
    fdc.write_command(0x10)                  # seek to 12
    fdc.track = 99                           # ...then lie about it in the register

    fdc.write_command(0xC0)                  # Read Address
    assert fdc.read_data() == 12


def test_writing_a_sector_reaches_the_image_and_marks_it_dirty():
    image = _formatted()
    fdc, _ = _controller(image)
    fdc.sector = 5

    fdc.write_command(0xA0)                  # Write Sector
    for byte in bytes(range(256)):
        fdc.write_data(byte)

    assert image.read_sector(0, 0, 5) == bytes(range(256))
    assert image.dirty


def test_a_write_protected_disk_refuses_writes():
    image = _formatted()
    image.write_protected = True
    fdc, _ = _controller(image)
    fdc.sector = 5

    fdc.write_command(0xA0)
    for byte in b"\xFF" * SECTOR_SIZE:
        fdc.write_data(byte)

    assert image.read_sector(0, 0, 5) == b"\x00" * SECTOR_SIZE
    assert not image.dirty


def test_a_multiple_sector_read_rolls_on_into_the_next_sector():
    """The whole difference between commands 0x80 and 0x90, and how a loader pulls a
    file without issuing a command per 256 bytes. Unimplemented, it hangs mid-file."""
    image = _formatted()
    image.write_sector(0, 0, 1, b"\x11" * SECTOR_SIZE)
    image.write_sector(0, 0, 2, b"\x22" * SECTOR_SIZE)
    fdc, _ = _controller(image)
    fdc.sector = 1

    fdc.write_command(0x90)                  # Read Sector, multiple
    first = bytes(fdc.read_data() for _ in range(SECTOR_SIZE))
    second = bytes(fdc.read_data() for _ in range(SECTOR_SIZE))

    assert first == b"\x11" * SECTOR_SIZE
    assert second == b"\x22" * SECTOR_SIZE
    # Still live, with the next sector already under the head -- a multi-sector read
    # runs until the host aborts it with a Force Interrupt, so having moved on to
    # sector 3 is the command working, not overrunning.
    assert fdc._state == "reading" and fdc.sector == 3
    fdc.write_command(0xD0)                  # Force Interrupt: the normal way out
    assert fdc._state == IDLE and not fdc.drq


def test_a_single_sector_read_stops_after_one():
    image = _formatted()
    image.write_sector(0, 0, 1, b"\x11" * SECTOR_SIZE)
    fdc, _ = _controller(image)
    fdc.sector = 1

    fdc.write_command(0x80)                  # Read Sector, single
    for _ in range(SECTOR_SIZE):
        fdc.read_data()

    assert fdc.intrq and not fdc.drq
    assert fdc.sector == 1                   # the head did not move on


def test_a_multiple_sector_write_rolls_on_too():
    image = _formatted()
    fdc, _ = _controller(image)
    fdc.sector = 1

    fdc.write_command(0xB0)                  # Write Sector, multiple
    for _ in range(SECTOR_SIZE):
        fdc.write_data(0xAA)
    for _ in range(SECTOR_SIZE):
        fdc.write_data(0xBB)

    assert image.read_sector(0, 0, 1) == b"\xAA" * SECTOR_SIZE
    assert image.read_sector(0, 0, 2) == b"\xBB" * SECTOR_SIZE


def test_write_track_finishes_instead_of_waiting_to_be_fed():
    """The hang that made the whole machine unrecoverable. TR-DOS issues 0xFF -- which
    decodes to Write Track -- while probing at start-up, and an earlier version parked
    with DRQ raised waiting for 6250 bytes that never came. No INTRQ, no error, and the
    Reset button could not rescue it either."""
    fdc, _ = _controller(_formatted())

    fdc.write_command(0xFF)

    assert fdc._state == IDLE
    assert fdc.intrq and not fdc.drq


def test_formatting_a_track_blanks_it():
    image = _formatted()
    for sector in range(1, SECTORS_PER_TRACK + 1):
        image.write_sector(3, 0, sector, b"\xEE" * SECTOR_SIZE)
    fdc, _ = _controller(image)
    fdc.data = 3
    fdc.write_command(0x10)                  # seek to track 3

    fdc.write_command(0xF0)                  # Write Track

    assert image.read_sector(3, 0, 1) == b"\x00" * SECTOR_SIZE
