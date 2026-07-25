# Pentagon 128 + Beta 128 / TR-DOS + TRD/SCL disks

The design record for zxide's disk support. `DEV_PLAN.md` points here rather than
duplicating it; `dev-support/STATUS.md` carries the session-by-session narrative.

**Status: working.** A Pentagon boots, TR-DOS 5.03 runs, `CAT` lists a real disk, and the
machine can write back. All seven phases below are done. What is *not* claimed is at the
end, under Limitations.

**Verified against the local library, two ways:**

* **1852 images parse, 0 refused** — 946 `.trd` and 906 `.scl`, all 80-track double
  sided, one unformatted (reported as such rather than refused).
* **60 of them boot-swept**: a random sample, each one booting a Pentagon, entering
  TR-DOS, running `CAT`, and having the screen decoded back to text — then comparing the
  file count TR-DOS printed against the one our parser found. **59/60 agreed on the first
  run**; the 60th found a real bug (below). Sample drawn with a fixed seed, so it repeats.

Parsing is not running: no claim is made that all 1852 boot. What the sweep does show is
that TR-DOS can read an arbitrary disk off the shelf, not just the three used in
development.

### What the sweep caught

One disk, *Spectrum Progress 01*, reported 27 files where TR-DOS reported 12. Neither
side was misreading the bytes — they were answering different questions. Catalogue slots
12 to 27 held a maker's **signature** ("CONVERT.", "4 TR-DOS", "by:"), zero length, start
position track 0 sector 0. Those slots do not begin with the 0x00 end marker, so a scan
that trusts only the terminator reports them as files.

The fix is to agree with the machine: when the disk-information block looks genuine, its
**file count** bounds the catalogue, because that is the number TR-DOS itself trusts. The
end marker still applies, and still rules alone on a disk with no readable information
block. Pinned by `test_decorative_entries_past_the_file_count_are_not_files`.

---

## Why

zxide emulates the Sinclair line — 48K and 128K, loading from tape. The entire Soviet and
post-Soviet Spectrum world, which is where most of the demoscene, the disk magazines and a
very large slice of the software actually lives, ran on **Pentagon** clones with a
**Beta 128** disk interface and **TR-DOS**. None of it loads today, because none of it is on
tape.

There is a second reason, and it matters more for where this project is going. Tape is a
*consumption* format: you load someone else's program from it. Disk is a **development**
format — TR-DOS can `SAVE`, so a build can be written onto a disk image and run. That is the
natural target for the Milestone 5 "Unity" layer: your project produces a disk, not just a
snapshot. Which is why this work includes the write path and not only reads.

**Outcome:** a Pentagon 128 machine that boots to a TR-DOS-capable 128 menu, mounts `.trd`
and `.scl` images in two drives, runs what is on them, and can write back.

---

## Established facts

Verified during planning rather than assumed, because each of these would be expensive to get
wrong and cheap to check.

### The ROM set

`128p-0.rom`, `128p-1.rom`, `trdos.rom`, 16384 bytes each, now in `zxemu_core/roms/`.

That `128p` really is Pentagon and not some other 128 variant is worth showing, since the
name alone does not say so:

* `128p-1.rom` is **byte-identical** to `128-1.rom` (MD5 `6e09e5d3c4aef166601669feaaadc01c`).
  Pentagon leaves 48 BASIC alone.
* `128p-0.rom` differs from `128-0.rom` in only **65 bytes**, in three clusters:
  * `@0x2785` — the menu string `"Tape Tester"` becomes `"TR-DOS"`;
  * `@0x2817` — four bytes, the menu table entry beside it;
  * `@0x3BEC` — new code containing the literal text `"15616"`.

`RANDOMIZE USR 15616` is how you enter TR-DOS, and **15616 = 0x3D00** — which is exactly the
address the Beta 128 hardware watches for to page its ROM in. The ROM patch and the interface
agree, which is the confirmation.

Licensing is set out honestly in `zxemu_core/roms/LICENSE-roms.txt`: the Amstrad permission
covers `48.rom`/`128-*.rom`/`128p-1.rom`, and **no distribution statement could be located**
for `128p-0.rom`'s patch or for `trdos.rom`.

### What a Pentagon actually is

For our purposes a Pentagon 128 is a Sinclair 128K with three changes, and only three:

| | Sinclair 128K | Pentagon 128 |
|---|---|---|
| frame length | 70908 T (311 lines x 228 T) | **71680 T** (224 lines x 320 T) |
| memory contention | odd RAM banks contend with the ULA | **none at all** |
| disk interface | none | **Beta 128 built in, active from reset** |

Paging (port 0x7FFD), the AY, the bank pool and the screen are identical. So `Machine128` is
the right base class and the Pentagon subclass is small.

The absence of contention is not a simplification — it is what the hardware does. It makes us
*more* accurate on Pentagon than on the Sinclair models, where contention is modelled but not
applied to every access.

### The Beta 128 ROM paging rule

The interface has no port for paging its ROM. It watches the address bus during **instruction
fetch** and swaps itself in and out:

* page **in** when TR-DOS is not currently paged, `(PC & 0xFF00) == 0x3D00`, and ROM 1
  (48 BASIC) is selected;
* page **out** when TR-DOS is paged, ROM 1 is selected, and `PC >= 0x4000`.

Both conditions look only at the M1 address. This is why `RANDOMIZE USR 15616` works from
BASIC and why TR-DOS vanishes the moment control returns to RAM.

### Beta 128 ports

Decoded on the **low byte** of the port address:

| low byte | write | read |
|---|---|---|
| `0x1F` | command | status |
| `0x3F` | track | track |
| `0x5F` | sector | sector |
| `0x7F` | data | data |
| `0xFF` | system (drive, side, reset, density) | INTRQ / DRQ |

---

## Architecture

Mirrors the existing `storage/` split: Qt-free core, one concern per module, each
`__init__.py` an educational overview.

```
zxemu_core/storage/disk/          (new package)
  trd.py      TrdImage -- geometry, sector read/write, catalogue, disk-info sector.
              Tolerates truncated images: real .trd files routinely stop after the
              last used sector rather than padding to 640K.
  scl.py      SCL -> TrdImage in memory. SCL is a file list plus concatenated data
              with no free-space map, so loading it means *building* a catalogue and
              laying the files out from track 1. A source format; edits live in the TRD.
  wd1793.py   The floppy controller, as a register-level state machine.
  beta.py     The Beta 128 interface: port decode, drive select, ROM paging rule.
              The only part of the package that knows a machine exists.
zxemu_core/machine.py             MachinePentagon(Machine128)
zxemu_core/cpu/z80.py             m1_hook, for the paging rule
zxemu_ui/panels/disk_view.py      drives, mounted image, catalogue, write-protect
```

### The one CPU change

The paging rule has to see every instruction fetch. The existing `Z80.set_trap` is a
single-address compare and cannot express it, so `Z80` gains an `m1_hook`, default `None`,
called with PC at the top of `step()`.

Machines other than Pentagon never install one and pay a single `is not None` per
instruction — the same class of cost as the `_trap_pc` compare already sitting beside it.

**Measured**, since the plan promised a number rather than a hope:

| model | ms/frame | m1_hook |
|---|---|---|
| 48K | 11.0 | no |
| 128K | 15.3 | no |
| Pentagon | 16.6 | yes |

So the hook costs about **8%, on Pentagon only** — a Python call per instruction, which is
what it is — and nothing at all on the other two. 16.6ms is comfortably inside the 20ms
frame budget, so it stands. If it ever needs to come down, the move is to inline the
condition rather than to make the hook conditional: the Beta is always present on a
Pentagon, so there is no "only while attached" to fall back to.

### Why the controller is tractable in pure Python

A real WD1793 works in MFM bit cells, and emulating it at that level would be both slow and
enormous. We do not: a TRD is a plain sector dump with fixed geometry, so the controller is
implemented at **sector granularity** — a command decoder plus a byte-serving buffer.
`Write Track` (format) recognises the standard TR-DOS format stream and initialises the image
rather than parsing gap bytes.

This is the single biggest scope saving in the design, and the reason the whole thing is a
few hundred lines. It is also the reason for the main limitation below.

### The one piece of timing that cannot be faked

The **index pulse**. TR-DOS uses it for drive-ready detection and seek timeouts, so a
controller that never pulses index reads as an empty drive no matter what is mounted. It is
synthesised from the machine clock at 5 revolutions per second.

DRQ, by contrast, is served immediately. TR-DOS polls for it, and nothing short of a
bit-level emulator paces it.

---

## Phases — all delivered

1. ✅ **Pentagon machine.** ROMs, `MachinePentagon`, model plumbing. Boots to the 128 menu
   reading **TR-DOS** where a Sinclair says Tape Tester.
2. ✅ **Beta paging.** `m1_hook` and the address-bus rule. `RANDOMIZE USR 15616` works.
3. ✅ **`trd.py`.** Catalogues of real disks parse; verified against the library.
4. ✅ **WD1793 read path.** **`CAT` inside TR-DOS lists a real disk.**
5. ✅ **`scl.py`.** `CAT` works on converted `.scl` images.
6. ✅ **Write path.** Sectors written through the controller are read back by TR-DOS.
7. ✅ **UI, tests, docs.** Load ▸ TRD/SCL and Load ▸ Disk Drive; 43 new tests.

The decisive test was phase 4's, and it is now
`tests/integration/test_trdos.py::test_tr_dos_reads_the_catalogue_of_a_disk_we_built`:
TR-DOS boots, `CAT` is typed on the emulated keyboard, and the screen is decoded back to
text by matching cells against the ROM's own font. Every number on that screen came out of
TR-DOS driving our controller — not out of our parser. It is the disk equivalent of
`test_edge_replay.py` handing tape timing to the ROM's own loader.

### Three bugs found by actually using the IDE

None of these showed up in 762 passing tests, and all three came from a few minutes of
driving the thing by hand. Worth recording as a set, because they share a shape: each was
a *state machine with no way out*.

1. **`RUN` wedged the machine solid.** TR-DOS writes `0xFF` to the command register while
   probing at start-up. That decodes to **Write Track**, and the implementation parked in a
   formatting state with DRQ raised, waiting to be fed a track's worth of bytes that were
   never coming — no completion condition at all. Write Track now blanks the track and
   finishes immediately, which costs nothing since the incoming stream was being discarded
   anyway.
2. **Reset could not rescue it.** `Machine128.reset()` re-pages slot 0 through
   `rom_for_slot0()`, which answers *"TR-DOS"* while the interface is paged in — so
   resetting from inside TR-DOS restarted the CPU **executing the disk operating system
   from address 0**. Hence the garbage screen. The reset line reaches the Beta 128 on real
   hardware; now it does here too.
3. **Multi-sector transfers were unimplemented.** The `_multiple` flag was decoded from the
   command and then never used, so commands `0x90`/`0xB0` served exactly one sector and
   stopped. That is how a loader reads a whole file without issuing a command per 256
   bytes, so anything larger than a sector would have stalled.

Plus one in the UI: **switching model left the new machine unbooted**. A freshly built
machine has never executed an instruction, so switching while paused gave a black screen
and a dead keyboard — indistinguishable from "the new model is broken". Swapping the
machine is a power-cycle, and now behaves like one.

With those fixed, **Spectrofon N1 (1994) boots from a `.trd` and runs**, and Reset returns
to a clean Pentagon menu.

### The bug that test was worth catching

The first `CAT` against a perfectly good disk said **"No disk"**. The image was fine, the
catalogue parsed, the sector arithmetic was right; TR-DOS had even seeked to track 0 and
asked for sector 9. Tracing the port traffic showed it: TR-DOS polls **port 0xFF** for DRQ
and INTRQ and *never reads the status register during a transfer*. INTRQ was still set from
the previous Restore, so the very first Read Sector looked like it had already finished —
TR-DOS took one byte and gave up.

The datasheet clears INTRQ on a status read **or a command write**. Only the first was
implemented. One line, and it is now pinned by
`test_writing_a_command_clears_intrq`, because nothing about the symptom points at the
cause.

---

## Using it

* **Load ▸ Load TRD… / Load SCL…** mounts a disk in drive A. Neither a 48K nor a Sinclair
  128 has anywhere to put one, so doing this on either **switches the machine to a
  Pentagon** and says so in the Output — clicking "Load TRD" is an unambiguous statement of
  intent, and the alternative is an error telling you to go and do the obvious thing.
* **Load ▸ Disk Drive** operates the disk you already mounted: mount in drive B, write
  protect, **Save Disk As…**, eject. Ejecting a disk the machine has written to asks first,
  because that is exactly how you would lose a game's save file.
* Saving always writes `.trd`, never `.scl`, even for a disk that arrived as one: an SCL
  cannot express free space or a disk label, both of which exist by the time anything has
  been written.
* Inside the machine: choose **TR-DOS** from the Pentagon menu (or `RANDOMIZE USR 15616`),
  then `CAT` — extended mode, then symbol-shift 9.

## Limitations, stated up front

* **Copy-protected disks will not all work.** Sector-granularity emulation cannot represent
  non-standard geometry or deliberate CRC errors, which is precisely what protection schemes
  use. `.fdi` — a format that *can* represent them — was considered and deliberately dropped.
  Every image in the local library *parses*, but parsing is not running: no claim is made
  here that all 1852 of them boot.
* **`Read Track` is approximate and `Write Track` is a stub.** The first returns the track's
  sectors back to back with none of the gaps and address marks a real one would produce;
  the second blanks the track and discards the format stream. Enough for TR-DOS's `FORMAT`,
  not enough for a disk copier that inspects the format itself.
* **Custom TR-DOS replacements** — fast loaders that drive the FDC directly instead of calling
  TR-DOS — may depend on timing we do not model. Same class of problem as turbo tape loaders,
  and likely the same resolution: make the timing real where it is cheap to.
* **Pentagon timing is not cycle-exact.** No contention is correct, but per-scanline border
  effects remain unmodelled, so the most timing-critical demos may still misbehave.
