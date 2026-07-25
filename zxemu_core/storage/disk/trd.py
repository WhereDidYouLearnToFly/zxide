"""``.trd`` disk images: raw sectors, and the TR-DOS catalogue written into track 0.

A ``.trd`` is the simplest disk format there is -- **every sector of the disk, in order,
with nothing in between**. No headers, no metadata, no gaps: 256 bytes per sector, 16
sectors per track, tracks in cylinder order with the two sides interleaved::

    file offset = ((cylinder * sides) + head) * 16 * 256 + (sector - 1) * 256

Sectors are numbered from **1** on the wire and stored from 0 in the file, which is the
single most common off-by-one in disk code and is why :func:`sector_offset` exists rather
than the arithmetic being inlined at each call site.

TR-DOS itself is a filesystem laid on top, occupying track 0 side 0:

    sectors 1-8   the catalogue: 128 entries of 16 bytes
    sector 9      the disk-information block (in its last 32 bytes)
    sector 10-16  unused by TR-DOS

Everything from track 1 onward is file data. Files are stored **contiguously** -- a file
is a start track, a start sector and a length, with no allocation table and no
fragmentation. That is why deleting a file in TR-DOS does not free its space until you
compact the disk, and why the catalogue can afford to be this small.

Truncated images are normal, not damaged
----------------------------------------
A 640K disk that holds 90K of files is very often distributed as a 90K file: the tail is
all zeros, so the copier stopped at the last used sector. Reading past the end therefore
returns a blank sector rather than raising -- a short image is a *complete* disk whose
empty part was not written down. Writing past the end grows the image instead.
"""

from __future__ import annotations

from dataclasses import dataclass

SECTOR_SIZE = 256
SECTORS_PER_TRACK = 16
TRACK_SIZE = SECTOR_SIZE * SECTORS_PER_TRACK

CATALOGUE_SECTORS = 8
CATALOGUE_ENTRIES = 128
CATALOGUE_ENTRY_SIZE = 16

#: The disk-information block lives at the end of sector 9 (the sector after the
#: catalogue), i.e. absolute offset 0x8E0 in the image.
INFO_SECTOR_INDEX = 8
INFO_OFFSET = INFO_SECTOR_INDEX * SECTOR_SIZE + 0xE0

#: Byte 0xE7 of the info block. TR-DOS writes 0x10 here and checks it on mount; it is the
#: closest thing the format has to a magic number.
TRDOS_ID = 0x10

#: Disk-type byte (0xE3 of the info block) -> (tracks, sides). The disk states its own
#: geometry, which is the only reliable source: file size cannot be trusted on a
#: truncated image, and truncated images are common.
DISK_TYPES = {
    0x16: (80, 2),
    0x17: (40, 2),
    0x18: (80, 1),
    0x19: (40, 1),
}
DEFAULT_GEOMETRY = (80, 2)

#: Catalogue entry byte 0. 0x00 ends the catalogue; 0x01 marks a deleted file whose
#: entry is still there (TR-DOS overwrites the first character rather than moving
#: everything up -- which is why undelete was a real utility people owned).
END_OF_CATALOGUE = 0x00
DELETED_MARKER = 0x01


def sector_offset(cylinder: int, head: int, sector: int, sides: int) -> int:
    """Byte offset of a sector in the image. ``sector`` is 1-based, as on the wire."""
    return ((cylinder * sides) + head) * TRACK_SIZE + (sector - 1) * SECTOR_SIZE


@dataclass(frozen=True)
class TrdFile:
    """One catalogue entry.

    ``start_track``/``start_sector`` are a position on the disk rather than a block
    number, because TR-DOS files are contiguous: everything about where a file lives is
    in these two numbers plus its length.
    """

    name: str
    extension: str
    start_address: int   # for a Code file, where it loads; other kinds reuse the field
    length: int          # in bytes
    sectors: int         # in sectors -- what the disk actually spends on it
    start_sector: int
    start_track: int
    deleted: bool = False

    @property
    def display_name(self) -> str:
        return f"{self.name}.{self.extension}" if self.extension.strip() else self.name


@dataclass(frozen=True)
class TrdInfo:
    """The disk-information block: what TR-DOS believes about the disk as a whole."""

    label: str
    file_count: int
    free_sectors: int
    first_free_track: int
    first_free_sector: int
    disk_type: int
    valid: bool          # did byte 0xE7 hold the TR-DOS id?

    @property
    def geometry(self) -> tuple[int, int]:
        return DISK_TYPES.get(self.disk_type, DEFAULT_GEOMETRY)


class TrdImage:
    """A mounted ``.trd``: sector access, the catalogue, and whether it has been changed.

    Held as a mutable ``bytearray`` because the whole point of disk support (as opposed
    to tape) is that the machine can write to it. :attr:`dirty` tracks whether anything
    has changed since the image was loaded or last saved, so the UI can offer to write it
    back rather than silently discarding a game's save file.
    """

    def __init__(self, data: bytes = b"", *, tracks: int | None = None,
                 sides: int | None = None, write_protected: bool = False, name: str = ""):
        self.data = bytearray(data)
        self.write_protected = write_protected
        self.name = name
        self.dirty = False
        info = self.info()
        # Trust the disk's own type byte when it looks like a TR-DOS disk; fall back to
        # what the file size implies, and finally to the commonest geometry. Explicit
        # arguments beat all of it, for images whose info block is damaged.
        guessed_tracks, guessed_sides = info.geometry if info.valid else self._geometry_from_size()
        self.tracks = tracks if tracks is not None else guessed_tracks
        self.sides = sides if sides is not None else guessed_sides

    # --- geometry -------------------------------------------------------------

    def _geometry_from_size(self) -> tuple[int, int]:
        """Infer (tracks, sides) from the file length, for images with no valid info block."""
        for candidate in ((80, 2), (40, 2), (80, 1), (40, 1)):
            if len(self.data) == candidate[0] * candidate[1] * TRACK_SIZE:
                return candidate
        return DEFAULT_GEOMETRY

    @property
    def full_size(self) -> int:
        return self.tracks * self.sides * TRACK_SIZE

    def has_track(self, cylinder: int, head: int) -> bool:
        return 0 <= cylinder < self.tracks and 0 <= head < self.sides

    # --- sectors --------------------------------------------------------------

    def read_sector(self, cylinder: int, head: int, sector: int) -> bytes | None:
        """A sector's 256 bytes, or None if the geometry has no such sector.

        A sector inside the geometry but past the end of a truncated file reads as
        zeros: it is a real, blank sector that simply was not written down.
        """
        if not self.has_track(cylinder, head) or not 1 <= sector <= SECTORS_PER_TRACK:
            return None
        start = sector_offset(cylinder, head, sector, self.sides)
        chunk = bytes(self.data[start:start + SECTOR_SIZE])
        return chunk.ljust(SECTOR_SIZE, b"\x00")

    def write_sector(self, cylinder: int, head: int, sector: int, payload: bytes) -> bool:
        """Write 256 bytes; False if the sector doesn't exist or the disk is protected."""
        if self.write_protected or not self.has_track(cylinder, head):
            return False
        if not 1 <= sector <= SECTORS_PER_TRACK:
            return False
        start = sector_offset(cylinder, head, sector, self.sides)
        if len(self.data) < start + SECTOR_SIZE:
            # Grow a truncated image on first write rather than refusing: the sector is
            # part of the disk, the file just stopped early.
            self.data.extend(b"\x00" * (start + SECTOR_SIZE - len(self.data)))
        self.data[start:start + SECTOR_SIZE] = bytes(payload).ljust(SECTOR_SIZE, b"\x00")[:SECTOR_SIZE]
        self.dirty = True
        return True

    # --- the filesystem -------------------------------------------------------

    def info(self) -> TrdInfo:
        """The disk-information block. ``valid`` is False if this isn't a TR-DOS disk."""
        block = bytes(self.data[INFO_OFFSET:INFO_OFFSET + 0x20]).ljust(0x20, b"\x00")
        label = block[0x15:0x1D].decode("ascii", "replace").rstrip("\x00 ")
        return TrdInfo(
            label=label,
            file_count=block[0x04],
            free_sectors=block[0x05] | (block[0x06] << 8),
            first_free_sector=block[0x01],
            first_free_track=block[0x02],
            disk_type=block[0x03],
            valid=block[0x07] == TRDOS_ID,
        )

    def catalogue(self, include_deleted: bool = False) -> list[TrdFile]:
        """The files on the disk, in catalogue order -- the same ones TR-DOS would list.

        Two things stop the scan, and it needs both:

        * an entry whose name begins with 0x00, the documented end marker (TR-DOS writes
          entries consecutively, so scanning all 128 slots would turn whatever follows
          into imaginary files);
        * the **file count in the disk-information block**, once that block looks like a
          real TR-DOS one.

        The second is not belt-and-braces. Disks exist whose unused catalogue slots hold
        *decorative text* -- a maker's signature typed into the empty entries, with zero
        length and a start position of track 0 sector 0. Those slots do not begin with
        0x00, so the end marker alone happily reports them as files: one real disk in the
        library listed 27 "files" where TR-DOS lists 12. The information block is the
        count TR-DOS itself trusts, so it is the count we agree with.

        Deleted entries are counted separately by TR-DOS ("N Del. File"), so they do not
        consume the live-file budget here either.
        """
        info = self.info()
        limit = info.file_count if info.valid else CATALOGUE_ENTRIES
        files: list[TrdFile] = []
        live = 0
        for index in range(CATALOGUE_ENTRIES):
            start = index * CATALOGUE_ENTRY_SIZE
            entry = bytes(self.data[start:start + CATALOGUE_ENTRY_SIZE])
            if len(entry) < CATALOGUE_ENTRY_SIZE or entry[0] == END_OF_CATALOGUE:
                break
            deleted = entry[0] == DELETED_MARKER
            if not deleted:
                if live >= limit:
                    break
                live += 1
            if deleted and not include_deleted:
                continue
            files.append(_parse_entry(entry, deleted))
        return files

    # --- persistence ----------------------------------------------------------

    def to_bytes(self, pad: bool = False) -> bytes:
        """The image as written to disk; ``pad`` fills a truncated image out to full size."""
        data = bytes(self.data)
        if pad and len(data) < self.full_size:
            data = data.ljust(self.full_size, b"\x00")
        return data


def _parse_entry(entry: bytes, deleted: bool) -> TrdFile:
    name = entry[0:8].decode("ascii", "replace").rstrip()
    return TrdFile(
        name=name,
        extension=chr(entry[8]) if 32 <= entry[8] < 127 else "?",
        start_address=entry[9] | (entry[10] << 8),
        length=entry[11] | (entry[12] << 8),
        sectors=entry[13],
        start_sector=entry[14],
        start_track=entry[15],
        deleted=deleted,
    )


def parse_trd(data: bytes, name: str = "") -> TrdImage:
    """Mount raw ``.trd`` bytes, raising ValueError if this cannot be a TR-DOS disk.

    The check is deliberately loose. The only thing insisted on is that the file is big
    enough to hold track 0 -- without that there is no catalogue to read and nothing that
    could work. A missing TR-DOS id byte is *reported* (``info().valid``) rather than
    refused, because unformatted and partly-formatted disks are legitimate things to
    mount: TR-DOS's own FORMAT command has to start somewhere.
    """
    if len(data) < TRACK_SIZE:
        raise ValueError(
            f"too short to be a .trd disk image: {len(data)} bytes, "
            f"track 0 alone is {TRACK_SIZE}"
        )
    return TrdImage(data, name=name)
