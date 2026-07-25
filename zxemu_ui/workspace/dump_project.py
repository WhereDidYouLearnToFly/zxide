"""Write a memory dump out as a real zxide project.

``zxemu_core.debug.dumper`` decides *what* the memory is -- which stretches are code,
which are data, what to call the branch targets. This module turns that into files on
disk, and specifically into a **project**: a folder with a ``zxide.json`` that zxide can
open, build with F5, set breakpoints in, and step through.

That distinction is the whole requirement. A pile of ``.asm`` files would be an export;
what makes the dump useful is that it comes back as somewhere you can *work*. So the
manifest carries the model of the machine it came from (open it and the right machine
boots, with the right banks in the memory map), the entry point is the generated
``main.asm``, and the build writes a snapshot exactly as a hand-written project does.

Note it does **not** go through ``Project.create``: that scaffolds the starter template's
demo ``main.asm``, which is precisely what a dump must not contain. The manifest is
written directly instead.

Layout, chosen so it reads as a project rather than as output::

    dumped-game/
      zxide.json              model carried over from the live machine
      main.asm                device, ROM equates, the includes, savesna
      regions/ram_8000.asm    one file per region -- 48K in one file is unreadable
      data/ram_c000.bin       large blobs, incbin'd from their region file
"""

from __future__ import annotations

import json
from pathlib import Path

from zxemu_core.debug import dumper
from zxemu_core.memlayout import PAGED_MODELS
from zxemu_ui.workspace.project import MANIFEST_NAME, Project, default_manifest

#: sjasmplus device per model. There is no Pentagon device -- and none is needed, because
#: what DEVICE selects is the memory layout available to the assembler, and a Pentagon's
#: is a 128K's exactly (see zxemu_core/machine.py). The clone's differences are timing and
#: a disk interface, neither of which an assembler has an opinion about.
DEVICES = {"48k": "zxspectrum48", "128k": "zxspectrum128", "pentagon": "zxspectrum128"}

SNAPSHOT_NAME = "main.sna"
#: The raw RAM image the build also writes, used to prove the dump reassembles exactly.
IMAGE_NAME = "main.bin"


def dump_to_project(machine, folder, *, model: str, coverage_executed=None,
                    coverage=None, name: str | None = None,
                    start_address: int | None = None) -> Project:
    """Write ``machine``'s RAM out as a buildable project in ``folder``; return it.

    ``coverage_executed`` is the flag array from a
    :class:`~zxemu_core.debug.analysis.CoverageMap`, or None for an all-data dump -- which
    is a perfectly valid result, just one you have not taught anything yet.
    """
    folder = Path(folder)
    (folder / "regions").mkdir(parents=True, exist_ok=True)
    (folder / "data").mkdir(parents=True, exist_ok=True)

    regions = dumper.plan_regions(coverage_executed, memory=machine.memory)
    dumper.check_regions_tile(regions, dumper.RAM_BASE, dumper.ADDRESS_SPACE)
    labels = dumper.collect_labels(machine.memory, regions)
    rom_names = dumper.rom_symbols_used(machine.memory, regions)

    for region in regions:
        _write_region(machine.memory, folder, region, labels, rom_names)

    hidden = _write_hidden_banks(machine, folder, model, coverage)

    state = dumper.capture_state(machine)
    if start_address is not None:
        state["pc"] = start_address
    entry = state["pc"]
    paging = machine.paging_state() if hasattr(machine, "paging_state") else None
    live_bank = paging.ram_bank if paging else None
    (folder / "main.asm").write_text(
        _render_main(regions, rom_names, model, entry, hidden, live_bank, state),
        encoding="utf-8"
    )

    manifest = default_manifest(name or folder.name, model)
    manifest["build"]["output"] = SNAPSHOT_NAME
    # Record exactly which bytes of the recovered program are *not* the original's. The
    # restore stub has to live in the program's own memory, so it overwrites something;
    # saying precisely what keeps the byte-identity claim honest and checkable, instead
    # of quietly weakening it to "nearly identical".
    manifest["dump"] = {"entry": entry, "stub": None}
    (folder / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return Project(folder)


def _default_entry(regions) -> int:
    """Where the rebuilt snapshot should start.

    The first executed region, because that is the earliest thing we *know* is code. With
    no coverage at all there is nothing to go on, so the dump starts at the base of RAM --
    which will not run, and is honest about it in the generated comment rather than
    picking an address that merely looks plausible.
    """
    for region in regions:
        if region.kind == dumper.CODE:
            return region.start
    return dumper.RAM_BASE


def _write_region(memory, folder: Path, region, labels, rom_names) -> None:
    path = folder / "regions" / f"{region.label}.asm"
    header = [
        f"; {region.label} -- ${region.start:04x}-${region.end - 1:04x} "
        f"({region.size} bytes, {region.kind})",
        "",
        f"    org ${region.start:04x}",
        "",
    ]
    if region.kind == dumper.CODE:
        body = dumper.render_code(memory, region, labels, rom_names)
    elif region.size >= dumper.INCBIN_THRESHOLD:
        # Big blobs go out as binary and come back by reference: 40K of `db` is unreadable
        # and slow to assemble, and nobody annotates it anyway.
        blob = folder / "data" / f"{region.label}.bin"
        blob.write_bytes(dumper.region_bytes(memory, region))
        body = [f"{region.label}:", f'    incbin "data/{region.label}.bin"']
    else:
        body = dumper.render_data(memory, region)
    path.write_text("\n".join(header + body) + "\n", encoding="utf-8")


#: Which RAM banks a 128K/Pentagon always has in the address space: RAM5 in slot 1 and
#: RAM2 in slot 2 never move. Slot 3 holds whichever bank port 0x7FFD last selected.
_FIXED_BANKS = (5, 2)
_PAGED_SLOT_BASE = 0xC000


def _write_hidden_banks(machine, folder: Path, model: str, coverage=None) -> list[int]:
    """Dump the RAM banks that are *not* in the address space, as data. Returns them.

    On real hardware this would be the awkward part -- you can only read memory through
    the CPU's address space, so you would have to halt the machine, page each bank in,
    read it, and carefully page back what was there before. In an emulator none of that
    is necessary: a bank is a plain bytearray we can read whether or not it is mapped.
    ``Machine128.display_memory`` already leans on the same thing, returning the shadow
    screen from RAM7 even when nothing has it paged in.

    Classifying them needs one more thing, and it is the reason ``CoverageMap`` grew a
    per-bank record: an address at 0xC000 belongs to whichever bank was mapped at the
    time, which no later analysis can recover. With that recorded as it happens, a
    paged-out bank is disassembled exactly like the visible window; without it (an older
    coverage map, or none) the bank still comes out, as data.
    """
    banks = getattr(machine, "ram_banks", None)
    if model not in PAGED_MODELS or not banks:
        return []
    paging = machine.paging_state()
    visible = set(_FIXED_BANKS) | {paging.ram_bank if paging else 0}
    written = []
    for number, bank in enumerate(banks):
        if number in visible:
            continue      # already captured through the address space, with its coverage
        _write_one_bank(folder, number, bank, coverage)
        written.append(number)
    return written


def _write_one_bank(folder: Path, number: int, bank, coverage) -> None:
    """One paged-out bank: disassembled where it was seen to run, bytes elsewhere.

    Coverage for the paged window is kept per bank (see
    :class:`~zxemu_core.debug.analysis.CoverageMap`), which is the only reason this can be
    anything more than a blob: an address at 0xC000 belongs to whichever bank was mapped at
    the time, and that is recorded as it happens because it cannot be recovered later.
    """
    flags = coverage.executed_in_bank(number) if coverage is not None else None
    header = [
        f"; RAM bank {number} -- paged out at the moment of the dump, so read straight",
        "; from the bank rather than through the address space.",
    ]
    if flags is None or not any(flags):
        # Never ran with this bank mapped. "Not yet", not "never" -- run the part of the
        # program that uses it and dump again.
        (folder / "data" / f"bank{number}.bin").write_bytes(bytes(bank.data))
        body = [
            "; Nothing was recorded executing while it was mapped, so it is kept as data.",
            "",
            "    SLOT 3",
            f"    PAGE {number}",
            f"    org ${_PAGED_SLOT_BASE:04x}",
            "",
            f"bank{number}:",
            f'    incbin "data/bank{number}.bin"',
        ]
        (folder / "regions" / f"bank{number}.asm").write_text(
            "\n".join(header + body) + "\n", encoding="utf-8")
        return

    window = dumper.BankWindow(bank.data, _PAGED_SLOT_BASE)
    regions = dumper.plan_regions(
        dumper.flags_for_bank(flags, _PAGED_SLOT_BASE),
        start=_PAGED_SLOT_BASE, end=dumper.ADDRESS_SPACE, bank=f"bank{number}",
        memory=window,
    )
    dumper.check_regions_tile(regions, _PAGED_SLOT_BASE, dumper.ADDRESS_SPACE)
    labels = dumper.collect_labels(window, regions, prefix=f"b{number}_")
    rom_names = dumper.rom_symbols_used(window, regions)

    body = [
        "; Disassembled where the CPU was observed to run with this bank mapped in.",
        "",
        "    SLOT 3",
        f"    PAGE {number}",
        f"    org ${_PAGED_SLOT_BASE:04x}",
        "",
    ]
    for region in regions:
        if region.kind == dumper.CODE:
            body += dumper.render_code(window, region, labels, rom_names)
        elif region.size >= dumper.INCBIN_THRESHOLD:
            blob = folder / "data" / f"{region.label}.bin"
            blob.write_bytes(dumper.region_bytes(window, region))
            body += [f"{region.label}:", f'    incbin "data/{region.label}.bin"']
        else:
            body += dumper.render_data(window, region)
    (folder / "regions" / f"bank{number}.asm").write_text(
        "\n".join(header + body) + "\n", encoding="utf-8")


def _render_main(regions, rom_names, model: str, entry: int, hidden=(),
                 live_bank: int | None = None, state: dict | None = None) -> str:
    device = DEVICES.get(model, DEVICES["48k"])
    code_bytes = sum(r.size for r in regions if r.kind == dumper.CODE)
    data_bytes = sum(r.size for r in regions if r.kind == dumper.DATA)

    lines = [
        "; main.asm -- generated by zxide's memory dumper.",
        ";",
        "; This is somebody else's program, recovered from RAM. Everything the CPU was",
        "; observed to execute is disassembled; everything else is kept as bytes, which",
        "; assembles to exactly the same program either way.",
        ";",
        f"; {code_bytes} bytes of code, {data_bytes} bytes of data.",
        ";",
        "; Two things worth knowing before you trust it:",
        ";   * a region left as data is not necessarily data -- it may simply be code you",
        ";     have not run yet. Exercise more of the program and dump again.",
        ";   * only what was *resident* is here. A game that streams levels from disk or",
        ";     tape has just the part that was loaded at the moment of the dump.",
        "",
    ]
    if model in PAGED_MODELS:
        banks = ", ".join(str(n) for n in hidden) or "none"
        lines += [
            "; This machine has eight RAM banks, and all of them are here. The ones mapped",
            "; into the address space at the moment of the dump are above; the ones paged",
            f"; out ({banks}) follow, read straight from the bank.",
            ";",
            "; Every bank is disassembled wherever the CPU was seen to run with that bank",
            "; mapped in -- coverage records which bank was selected at the time, because",
            "; that is not something any later analysis could work out. A bank you never",
            "; ran anything from stays as data: 'not yet', rather than 'not code'.",
            "",
        ]
    lines += [
        f"    device {device}",
        "",
    ]
    if rom_names:
        lines += ["; ROM routines this code calls. The ROM itself is not dumped -- it is",
                  "; the same 16K on every machine -- so these are named, not defined.",
                  ""]
        lines += [f"{name:<24} equ ${address:04x}"
                  for address, name in sorted(rom_names.items(), key=lambda kv: kv[0])]
        lines.append("")
    if live_bank is not None:
        lines += [
            "; The machine had this bank in slot 3, so the 0xC000-0xFFFF part of the dump",
            "; below belongs in it. sjasmplus starts a zxspectrum128 device with bank 0",
            "; mapped there, so without this the top 16K would be assembled into the wrong",
            "; bank -- and the bank that was actually mapped would come out empty.",
            "    SLOT 3",
            f"    PAGE {live_bank}",
            "",
        ]
    lines += [f'    include "regions/{region.label}.asm"' for region in regions]
    lines += [f'    include "regions/bank{number}.asm"' for number in hidden]

    if live_bank is not None:
        lines += [
            "",
            "; Put the mapping back the way the machine had it before saving. The bank",
            "; includes above each leave their own PAGE in effect, and both SAVEBIN and",
            "; SAVESNA write whatever is mapped *now* -- so without this the top 16K of",
            "; the output is whichever bank happened to be included last, and the",
            "; byte-for-byte check silently compares against the wrong memory.",
            "    SLOT 3",
            f"    PAGE {live_bank}",
        ]
    lines += [
        "",
        "; The raw memory image, and the reason it is here: it is what proves the dump is",
        "; faithful. Assemble this project and compare main.bin against the memory it came",
        "; from -- byte-identical means the source provably represents the program, and",
        "; every region promoted from bytes to disassembly stays checkable the same way.",
        ";",
        "; The snapshot cannot serve that purpose. A 48K .sna has no field for PC: the",
        "; loader RETs to an address pushed on the stack, so saving one necessarily",
        "; overwrites two bytes of the program at SP-2. Fine for running it, useless as a",
        "; reference for comparison.",
        f"    savebin \"{IMAGE_NAME}\", ${dumper.RAM_BASE:04x}, "
        f"{dumper.ADDRESS_SPACE - dumper.RAM_BASE}",
        "",
    ]
    if state is not None:
        lines += dumper.render_snapshot_lua(state, model in PAGED_MODELS, SNAPSHOT_NAME)
    else:
        lines += [f"    savesna \"{SNAPSHOT_NAME}\", ${entry:04x}"]
    lines.append("")
    return "\n".join(lines)
