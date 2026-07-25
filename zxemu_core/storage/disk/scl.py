"""``.scl`` images: a list of files, converted to a real disk on load.

Where a ``.trd`` is a disk, an ``.scl`` is a **parcel of files**. It stores only what
somebody wanted to keep::

    "SINCLAIR"          8-byte signature
    N                   one byte: how many files
    N x 14 bytes        a catalogue entry per file, *without* its position on the disk
    ...                 every file's data, back to back, each padded to whole sectors
    4 bytes             a checksum

There is no free-space map, no track 0, no disk label -- because there is no disk. That
makes SCL far smaller than TRD for a half-empty disk, which is why most things you
download arrive as one, and it is also why loading one is a *conversion* rather than a
read: we have to build the disk the files were going to live on.

Laying it out is easy, and the reason is worth knowing: **TR-DOS files are contiguous and
allocated strictly in order**, with no fragmentation and no allocation table. So a file's
position is completely determined by the lengths of the files before it. Start at track 1
sector 1 (track 0 belongs to the catalogue) and hand out sectors in a line.

Each catalogue entry here is 14 bytes against TR-DOS's 16. The two missing bytes are
exactly the start sector and start track -- the position -- which is the whole difference
between a file list and a disk.

The result is an ordinary :class:`~zxemu_core.storage.disk.trd.TrdImage`, so everything
downstream (the controller, the catalogue view, saving) neither knows nor cares that the
file on disk was an SCL. Edits live in the TRD; writing back an SCL is not supported and
would lose the free-space information we just invented.
"""

from __future__ import annotations

from .trd import (
    DISK_TYPES,
    INFO_OFFSET,
    SECTOR_SIZE,
    SECTORS_PER_TRACK,
    TRDOS_ID,
    TrdImage,
)

SIGNATURE = b"SINCLAIR"
ENTRY_SIZE = 14          # the TR-DOS entry minus its two position bytes
HEADER_SIZE = len(SIGNATURE) + 1

#: Files start on track 1: track 0 is the catalogue and the disk-information block.
FIRST_DATA_TRACK = 1

#: SCL carries no geometry, so we build the disk everything else assumes: 80 tracks,
#: double sided. A file list that would not fit on one is rejected rather than silently
#: truncated.
DEFAULT_TRACKS, DEFAULT_SIDES = 80, 2
DISK_TYPE_80_2 = 0x16


def parse_scl(data: bytes, name: str = "") -> TrdImage:
    """Convert ``.scl`` bytes into a mounted disk image.

    Raises ValueError if this isn't an SCL, if the file count doesn't fit the data, or
    if the files wouldn't fit on a disk.
    """
    if not data.startswith(SIGNATURE):
        raise ValueError("not a .scl file (missing the SINCLAIR signature)")
    if len(data) < HEADER_SIZE:
        raise ValueError("truncated .scl: no file count")

    count = data[len(SIGNATURE)]
    entries_end = HEADER_SIZE + count * ENTRY_SIZE
    if entries_end > len(data):
        raise ValueError(
            f"truncated .scl: claims {count} files, but the catalogue runs past the file end"
        )

    image = TrdImage(bytes(DEFAULT_TRACKS * DEFAULT_SIDES * SECTORS_PER_TRACK * SECTOR_SIZE),
                     tracks=DEFAULT_TRACKS, sides=DEFAULT_SIDES, name=name)
    total_sectors = DEFAULT_TRACKS * DEFAULT_SIDES * SECTORS_PER_TRACK

    # Hand out sectors in a line from track 1, in catalogue order. `cursor` counts
    # sectors from the start of the disk, so track 0's sixteen come first and are skipped.
    cursor = FIRST_DATA_TRACK * SECTORS_PER_TRACK
    source = entries_end
    catalogue = bytearray()

    for index in range(count):
        entry = data[HEADER_SIZE + index * ENTRY_SIZE:HEADER_SIZE + (index + 1) * ENTRY_SIZE]
        sectors = entry[13]
        if cursor + sectors > total_sectors:
            raise ValueError(
                f"the files in this .scl need more than a {DEFAULT_TRACKS}-track disk holds"
            )
        track, sector = divmod(cursor, SECTORS_PER_TRACK)
        # The TR-DOS entry is the SCL entry plus the position we just chose for it.
        catalogue += entry + bytes([sector, track])

        payload = data[source:source + sectors * SECTOR_SIZE]
        _place(image, cursor, payload)
        source += sectors * SECTOR_SIZE
        cursor += sectors

    image.data[0:len(catalogue)] = catalogue
    _write_info(image, count, cursor, total_sectors, name)
    # Freshly built from a file that is not itself a disk: there is nothing to save back
    # to, so it starts clean and only becomes dirty if the machine writes to it.
    image.dirty = False
    return image


def _place(image: TrdImage, first_sector: int, payload: bytes) -> None:
    """Write ``payload`` across consecutive sectors starting at a linear sector number."""
    for offset in range(0, len(payload), SECTOR_SIZE):
        absolute = (first_sector * SECTOR_SIZE) + offset
        chunk = payload[offset:offset + SECTOR_SIZE].ljust(SECTOR_SIZE, b"\x00")
        image.data[absolute:absolute + SECTOR_SIZE] = chunk


def _write_info(image: TrdImage, file_count: int, used_sectors: int,
                total_sectors: int, name: str) -> None:
    """Fill in the disk-information block TR-DOS reads before it will believe the disk.

    Without this -- specifically without the id byte -- TR-DOS reports "No disk" for an
    image whose catalogue is perfectly intact.
    """
    track, sector = divmod(used_sectors, SECTORS_PER_TRACK)
    block = bytearray(0x20)
    block[0x01] = sector                       # first free sector
    block[0x02] = track                        # first free track
    block[0x03] = DISK_TYPE_80_2
    block[0x04] = file_count
    free = max(0, total_sectors - used_sectors)
    block[0x05] = free & 0xFF
    block[0x06] = (free >> 8) & 0xFF
    block[0x07] = TRDOS_ID
    label = _label_from(name)
    block[0x15:0x1D] = label
    image.data[INFO_OFFSET:INFO_OFFSET + 0x20] = block


def _label_from(name: str) -> bytes:
    """An 8-character disk label taken from the file's own name.

    SCL has nowhere to store one, and a blank label in the CAT header looks like a
    half-built disk. The filename is the only thing we know about it.
    """
    stem = name.rsplit(".", 1)[0] if name else ""
    ascii_only = "".join(ch for ch in stem if 32 <= ord(ch) < 127)
    return ascii_only[:8].ljust(8).encode("ascii", "replace")


assert DISK_TYPE_80_2 in DISK_TYPES  # keep the geometry we claim in step with trd.py
