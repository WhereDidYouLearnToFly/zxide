# zxide — project status & handoff

_Last updated: 2026-07-25._ A snapshot to make it easy to pick the project back up.

## Latest session (2026-07-25, later) — Pentagon 128, Beta 128, TR-DOS, disks

**760 tests pass**, up from 727. Design document: **[../TRDOS.md](../TRDOS.md)** — read that
for the architecture and the hardware facts; this is the narrative.

A third machine model, and with it a whole storage medium. `Load ▸ Load TRD…` mounts a disk,
the Pentagon menu's TR-DOS entry works, `CAT` lists the disk, and the machine can write back.
**1852 images from the local library parse, 0 refused** (946 `.trd`, 906 `.scl`).

**Three things worth knowing before touching this code again:**

1. **The ROM identification was checked, not assumed.** `128p-0.rom` differs from the stock
   `128-0.rom` in **65 bytes**: the menu string `"Tape Tester"` becomes `"TR-DOS"`, and new
   code appears containing the literal `"15616"`. `RANDOMIZE USR 15616` is 0x3D00 — the exact
   address the Beta 128 watches for. The ROM patch and the interface agree, which is what
   confirms the pair. `128p-1.rom` is byte-identical to `128-1.rom`.
2. **`LICENSE-roms.txt` now separates three cases** rather than implying one. Amstrad's
   permission covers `48.rom`/`128-*.rom`/`128p-1.rom`. **No distribution statement could be
   located** for `trdos.rom` or `128p-0.rom`'s patch — they are in the fuse checkout but in
   neither its `Makefile.am` nor its `README.copyright`. Bundled deliberately, with the
   position stated.
3. **The CPU gained an `m1_hook`** because the Beta pages its ROM by watching the *address
   bus* during instruction fetch, which neither a port write nor the single-address trap can
   express. Measured cost: **48K 11.0ms, 128K 15.3ms, Pentagon 16.6ms per frame** — ~8% on
   Pentagon only, nothing elsewhere (the hook is `None`). Inside the 20ms budget, so it stands.

**The bug worth remembering.** The first `CAT` on a good disk said **"No disk"**. Everything
checked out: the catalogue parsed, the geometry was right, TR-DOS had seeked to track 0 and
asked for sector 9. Port tracing found it — TR-DOS polls **port 0xFF** for DRQ/INTRQ and never
reads the status register mid-transfer, so a **stale INTRQ from the previous Restore** made the
first Read Sector look already-finished. It took one byte and gave up. The datasheet clears
INTRQ on a status read *or a command write*; only the first was implemented. One line, now
pinned by `test_writing_a_command_clears_intrq` — nothing about the symptom points at the cause.

**Also worth knowing:** a catalogue "track" is a *logical* track with the two sides folded in
(cylinder = track // sides, head = track % sides), which is why the TRD layout interleaves
sides. My own first test asserted otherwise and was wrong, not the code.

**The boot sweep, and what it was worth.** 60 disks sampled at random from the library, each
booted into TR-DOS with `CAT` typed on the emulated keyboard and the screen decoded back to
text; TR-DOS's file count compared against the parser's. **59/60 agreed immediately.** The
60th (*Spectrum Progress 01*) said 27 against TR-DOS's 12 — catalogue slots past the file
count held a maker's **signature** rather than files, with zero length and a start position
of track 0 sector 0, and no 0x00 terminator in front of them. `catalogue()` now bounds itself
by the information block's file count when that block is genuine, which is the number TR-DOS
trusts, falling back to the terminator when it isn't. Worth noting the shape of this: three
disks by hand all passed, and it took an arbitrary sample to turn up a disk built by someone
with a sense of humour.

**Then four bugs turned up in minutes of hands-on use, none of which 762 tests had caught.**
They share a shape worth remembering — each was *a state machine with no way out*:

* **`RUN` wedged the machine.** TR-DOS writes `0xFF` to the command register while probing;
  that decodes to **Write Track**, which parked with DRQ raised waiting for a track's worth
  of bytes that never came. No completion condition existed at all. It now blanks the track
  and finishes at once — free, since the stream was discarded anyway.
* **Reset couldn't rescue it.** `Machine128.reset()` re-pages slot 0 via `rom_for_slot0()`,
  which answers "TR-DOS" while the Beta is paged — so resetting from inside TR-DOS restarted
  the CPU *executing TR-DOS from address 0*. That was the garbage screen. The reset line
  reaches the interface now, as it does in hardware.
* **Multi-sector transfers were never implemented.** `_multiple` was decoded and then unused,
  so `0x90`/`0xB0` served one sector and stopped — anything bigger than 256 bytes would stall.
* **Switching model left the new machine unbooted**, so doing it while paused gave a black
  screen and a dead keyboard that read as a broken model. `set_machine` now power-cycles.

**Spectrofon N1 (1994) now boots from a `.trd` and runs**, and Reset returns to a clean
Pentagon menu. 770 tests, with a regression test per bug.

The lesson to carry: the automated tests all drove the *controller* correctly, so they never
issued the malformed command a real ROM issues, and never reset from a state a person can
easily reach. Hands-on use found in minutes what a test suite built from my own assumptions
could not.

**Deliberately not done:** `.fdi` (needs bit-level geometry), a dedicated disk *panel* (the
menu plus the Output catalogue listing covers the function), and `Write Track` beyond blanking
a track — enough for `FORMAT`, not for a copier that inspects the format.

## Latest session (2026-07-25) — tape edge replay, and Milestone 3 finally closes

**716 tests pass** (`pytest tests/unit tests/integration`), up from 682.

The last deferred item in Milestone 3 is done: tapes can now be replayed **as pulses**
rather than shortcut through the ROM. New module `zxemu_core/storage/pulse.py`.

**Why it was worth doing.** Fast loading works by trapping the ROM's `LD-BYTES`. A
commercial game's own turbo loader never calls that routine — it bit-bangs its own
sampling loop — so *no trap can ever serve it*. Measured across the 20 `.tzx` files in
the library on this machine: **4 use genuinely non-ROM bit timings** (Renegade is a
Speedlock 4 release, plus Barbarian II, Ms. Pacman, The Untouchables), and separately
**35 blocks are `0x14` "pure data" with no pilot of their own** — those depend entirely
on the preceding `0x12` tone that the parser used to discard. That was the ceiling, and
it is now gone.

*(Careful with the numbers: 15 more tapes differ from `ROM_TIMING` only in `pause_ms`,
which is not turbo. An early draft of this note counted those as turbo and claimed 19/20;
what makes a tape turbo is the pilot/sync/bit lengths, not the gap after a block.)*

Two things came free with it: the **loading stripes** (nobody draws them — the loader is
OUT-ing to the border between samples, so once it's genuinely running you see what it
really does) and the **tape sound** (EAR is summed into the speaker on real hardware; we
model it as an OR of the two 1-bit sources in `Machine._refresh_speaker`).

**What changed, and why each file had to move:**

1. **`pulse.py`** (new) — `BlockTiming`, `data_pulses()` (pilot → sync pair → two pulses
   per bit), the dataless items (`PureTone`/`PulseSequence`/`Silence`), and `TapePlayer`.
   Pulses are generated *lazily*: a 48K game is on the order of a million of them, which
   as a list is tens of megabytes for something played once, in order.
2. **`tape.py`** — this is not a TZX-only feature, which is the thing worth remembering.
   A `.tap` needs replay too (it just uses the ROM's timings), so `TapeBlock` gained
   `timing`/`pulses()`. More importantly `TapeDeck` now holds **mixed items** and both
   loaders share **one play head**: a commercial multi-part tape starts under the ROM
   loader and hands over to its own turbo loader partway through, and separate heads
   would disagree about where the tape is.
3. **`tzx.py`** — now *keeps* the per-block timings it used to throw away, and keeps the
   dataless entries in running order. A `0x12` tone in front of a `0x14` "pure data"
   block is **one load split across two container entries**; dropping the tone loses the
   load. `parse_tzx` therefore returns all audible items, and `tape.data_blocks()`
   narrows to the ones a fast load can serve.
4. **`ula.py` / `machine.py`** — bit 6 of port 0xFE is the whole of tape input. It idles
   high, so a machine with an empty deck reads exactly what it always did. The machine
   owns the clock (`tape_tstate`, which unlike `frame_t_state` never restarts — a pause
   runs for fifty frames), feeds the player from `_io_read`, and `Machine128._io_read`
   now delegates to `super()` instead of answering the ULA directly, which would have
   silently left the 128K with no tape input at all.
5. **UI** — **Load ▸ Tape Deck**: Fast Load (on), Tape Sound, Play/Stop/Rewind/Eject.
   Fast Load has a real "off" position now, which is exactly why it was deliberately
   absent before (with no replay, "off" would just hang the ROM). Deck preferences live
   on the window, not the machine, so switching model doesn't silently re-enable them.

**The one genuinely opinionated decision: the motor does not free-run.** A real cassette
spools whether or not the Spectrum is listening, and copying that would be actively
wrong here — you spend seconds typing `LOAD ""`, and a multi-load game spends *minutes*
playing part one before asking for part two; both would eat the rest of the tape. So the
motor **starts when the machine is plainly sampling** (≥200 reads of port 0xFE in one
frame, against a few dozen for a keyboard poll — the two regimes are orders of magnitude
apart, so the threshold barely matters) and **stops at the pause ending each block**,
which is both where a person would have hit stop and what the TZX spec means by "pause".
Play/Stop/Rewind override it.

**A subtlety that bit once and would bite again:** the motor stops only at a *real* pause
(`pause_ms > 0`), never merely at an item boundary. A bare `0x12` pilot tone exists solely
to introduce the block after it and is stored with no pause between the two; stopping
there dropped up to a frame of silence into exactly the gap where the loader was hunting
for its sync pulses. `test_an_item_with_no_pause_runs_straight_into_the_next_one` pins it.

**Where it stands against real tapes** (cold boot, `LOAD ""` typed in, fast load off):
* **1942 (Elite)** — loads **completely**, all 7 blocks, ~287s emulated, screen drawn and
  game code running. This is the headline result: a commercial tape loading from nothing
  but pulses.
* **Renegade (Speedlock 4)** — plays through all 392 items and does **not** come up, but it
  gets meaningfully further than it did: before the zero-pause fix above it drew *nothing*
  (0 of 6144 screen bytes); after it, 794. The loader is clearly running rather than the
  tape spooling past it — items are consumed at their real durations — so this is a
  timing/protection detail, not a structural failure. **Next suspects**, in order: the
  `0x2A` "stop the tape in 48K mode" and `0x2B` "set signal level" blocks, which are
  currently only logged and not acted on (`0x2B` in particular sets the *starting polarity*,
  and Speedlock is exactly the kind of loader that would care); then the one-item-per-frame
  jump visible in the trace around block 389, which suggests an item occasionally being
  stepped over inside a single frame.

So: **turbo tapes are now reachable, and one class of them demonstrably works end to end.**
Speedlock specifically is not claimed.

**Testing note worth keeping.** `tests/integration/test_edge_replay.py` hands the
judgement to the ROM itself: fast load off, `LD-BYTES` called the way BASIC calls it, and
150 bytes of Sinclair's Z80 left to decode the signal. Nothing else can tell you the
timings are right. It takes ~105 frames — that isn't overhead, that's the feature; 16
bytes took two seconds on real hardware too.

*(A debugging detour worth recording: the first scratch harness ran 600 frames past the
loader's return, so the CPU executed whatever address 0xFFFF held and overwrote the very
buffer being checked — it reported a total failure while the load had been working all
along. `_run_until_the_loader_returns` stops at the return for exactly that reason.)*

## Latest session (2026-07-24) — build target, tape trap, new formats, editor navigation

**682 tests pass** (`pytest tests/unit tests/integration`).

1. **F5 assembles the file you have open**, not a hard-coded `main.asm`. The manifest's
   `main` is only a fallback now, because a folder zxide didn't scaffold names its entry
   point whatever it names it. The snapshot's name follows the source's own `savesna`
   directive too — sjasmplus has no `--sna` flag, so believing the manifest meant hunting
   for a file the assembler never wrote. See `_compile_target` in `main_window.py`.
2. **The tape trap moved to 0x0562** — see the TAP section below. This is the fix that
   made Aliens: Neoplasma II load.
3. **`.z80` and `.tzx` loading** — see item 4 of Milestone 3 below.
4. **Editor navigation**: Find in Project (Ctrl+F, results as clickable Output lines),
   Go to Line (Ctrl+G), Show in Explorer (project-tree menu), and Clear on the Output
   console's right-click menu.
5. **`main_window.py` broken up** — it had reached 1463 lines and 82 methods, owning docks,
   menus, project state, builds, media loading, debug bookkeeping and screenshots. Now
   ~1180, with three focused modules beside it: `menu_builder.py` (the menu bar as data --
   its 200 lines of `QAction` plumbing were the single biggest lump), `debug_session.py`
   (the six loose debug attributes as one object), `media.py` (format dispatch and log
   wording, Qt-free). Also deduplicated: `Project.relative()` replaced seven copies of the
   same try/except, `_refresh_all_panels()` three copies of a six-line refresh, and
   `_reveal_dock()` seven `show()`+`raise_()` pairs. 37 new tests came with it, including a
   menu-shape test — nothing about a menu fails loudly, so a dropped shortcut or an
   unconnected handler would otherwise look like a working IDE until you reached for it.
6. **Three bugs found by using the IDE, none of which raised anything:**
   * **Loading a snapshot left a paused machine paused** while logging "— running". After a
     Build & Debug breakpoint or a Pause, a loaded `.z80`/`.sna` showed its screen and then
     did nothing — which reads as a dead keyboard, not a paused emulator. It resumes now,
     as the tape path always did.
   * **The emulated keyboard was completely dead under a non-Latin keyboard layout.**
     The key maps were keyed on `event.key()`, which is layout-dependent: with a Cyrillic
     layout active the physical J key reports Cyrillic О, matching no Spectrum key, so
     *nothing* worked — you could not even type `LOAD ""` to start a tape. There is now a
     physical-position fallback (`_SCANCODE_TO_QT_KEY`), used only when the logical key
     means nothing to a Spectrum, so Latin layouts behave exactly as before. The scan-code
     offset is chosen per platform, not guessed: X11 keycodes are set-1 codes +8 and the
     ranges overlap (X11's J is set-1's Z), so trying both would hand Linux users the wrong
     letters; macOS numbering is unrelated, so the fallback is disabled there.
   * **Keys held when the emulator lost focus were never released.** A widget that loses
     focus gets no key-*release*, so pressing a menu shortcut or opening a file dialog over
     the emulator could leave a key down in the matrix forever: the ROM auto-repeats it and
     `LOAD ""` becomes untypable. `focusOutEvent` now clears the held keys.
   * The Model menu retargets the open project's manifest as well as switching the
     emulator — kept deliberately (the choice has to stick, or reopening the project
     switches back), but it now logs exactly what it changed, and the same field is
     settable directly in **Settings ▸ Project ▸ Target machine**.

   Also new: an inserted tape that goes unread for ~8s now explains itself in the Output —
   either "type LOAD ''" (nothing loaded yet) or "this game has its own turbo loader, fast
   load can't feed it" (some blocks loaded, then it stopped). A stalled tape looks identical
   either way, and the two need opposite actions.
7. **Two test-infrastructure repairs**, both pre-existing and both worth knowing about:
   `tests/` now has `__init__.py` files (an unrelated `tests` package in site-packages was
   shadowing it, so five test modules couldn't even be collected), and `tests/conftest.py`
   redirects `MainWindow`'s settings path — every MainWindow test used to write the
   developer's real `settings.json`, leaving `last_project` pointing at a deleted pytest
   tmp folder.

## Earlier session (2026-07-22) — audio bug hunt, then the debugger

**Three real emulator bugs**, all found by chasing a "loud farting noise" over beeper
music and all verified by headless capture rather than by ear:

1. `beeper.py` — the speaker level never carried across frames (the flush sentinel
   reassigned it back to the frame's *starting* value, so it was permanently 0). Every
   frame restarted from low, injecting a full-amplitude pulse at each boundary: a 50Hz
   buzz that was **68% of the output's total energy**.
2. `machine.py` — `run_frame` computed its target relative to the carried remainder, so
   the remainder accumulated every frame's overshoot forever. Once non-zero, flips in
   the frame's tail were timestamped past `frame_tstates` and clamped onto one instant:
   **36,350 of ~670,000 flips destroyed per 1000 frames**, worsening the longer you
   listened. Fixed by making the target absolute.
3. `cpu/instructions/indexed.py` — forming `(IX+d)` was treated as free, so **every**
   indexed instruction ran 5 T-states short (2 for `LD (IX+d),n`). Engine-independent;
   affects anything that paces itself by instruction cycles.

**Audio modules split** one-per-chip, matching `ula.py`/`keyboard.py`: `beeper.py`
(Beeper), `ay.py` (AY8912), `mixer.py` (SoundMixer). `audio.py` is gone.

**The debugger is now complete** — see DEV_PLAN's debugger track. Panels:
disassembly (with ROM routine names and your own SLD labels), call stack, analysis.
Stepping: into / over / out, run-to-cursor. Stopping: conditional breakpoints,
watchpoints on memory reads *and* writes and on I/O ports. Editing: poke memory,
click a register to set it. Plus coverage recording, a bounded execution trace,
memory search and cross-references.

Two design decisions worth knowing, both about not taxing the fast path:
* **port watchpoints** swap `cpu.io_read`/`io_write` for instrumented versions only
  while watches exist — Danterrifik does 80k OUTs a frame, so even an empty-set check
  would have cost milliseconds;
* **memory watchpoints** rebind `memory.__class__` to an instrumented subclass rather
  than building a replacement object, because the CPU, the machine and the 128K paging
  code all hold that same reference.

**342 tests pass** *(at the time of that session — 682 now)*.

## Where we are

**Milestone 1 (emulator core + live PyQt5 view) is complete and working.**
- Pure-Python Z80 CPU (full instruction set incl. undocumented behaviour),
  48K memory, ULA (timing/contention/border), 8x5 keyboard.
- PyQt5 view renders the screen (bitmap + attributes + border + FLASH) via a
  numpy fast path, driven by a real-time-paced frame loop at ~50 fps.
- Boots the real 48K ROM to the 1982 copyright screen; BASIC runs; typing
  `PRINT "HELLO"` works end to end.

**Milestones 2, 3 and 4 followed** — the IDE shell and debugger, hardware and audio, and
the asset workflow. `DEV_PLAN.md` is the authority on the phase-by-phase state; this file
keeps the session-by-session narrative and the reasoning that didn't fit there.

## How it's structured

```
main.py            entry point + frame loop (QTimer, real-time catch-up pacing)
zxemu_core/        emulator core, no Qt dependency
  cpu/
    z80.py         fetch/decode/execute loop, interrupts, HALT
    registers.py   registers + flag bits
    flags.py       ALU/flag math
    instructions/  one explicit handler per opcode, grouped by family
                   (load8/16, arith8/16, logic in arith8, rotate_shift, bit,
                    jump, call_return, control, blockio, exchange, indexed)
                   + indexed_bit.py (DDCB/FDCB, kept compact as a loop demo)
                   + _dispatch.py (tables + @base/@cb/@ed/@indexed decorators)
  machine.py       wires it together; run_frame() = one 50Hz frame  <- read first
  memory.py        16K-bank paged model (paging-ready for 128K) + the instrumented
                   variant memory watchpoints switch on
  ula.py           port 0xFE (border/keyboard), frame timing, contention table
  keyboard.py      8x5 matrix
  memlayout.py     free space per bank, reserved ranges, and the auto-locate search
                   that places an asset where it won't collide
  sound/           beeper.py + ay.py, summed by mixer.py (the resistor network's
                   software stand-in). Sources share a 3-member contract.
                   + beeper_preview.py (audition an effect with no live machine)
  storage/         tape.py (.tap + the ROM-trap fast loader), tzx.py,
                   pulse.py (edge-level replay: blocks -> the pulse train on port 0xFE
                   bit 6, and the motor policy that decides when the tape rolls),
                   snapshot.py (.sna), z80.py (.z80 v1/v2/v3)
  assets/          manifest.py + one converter per kind (bmp/tilemap/binary/pt3/
                   beeper_sfx/native_sprite), registry.py to pick one by suffix,
                   preview.py to draw them
  debug/           disassembler.py, rom_symbols.py, debug_expr.py, analysis.py
                   -- no Qt, so the debugger's reasoning is testable headless
zxemu_ui/          shell at top level: main_window (docks + wiring), menu_builder
                   (the menu bar as data), debug_session (source map, breakpoints,
                   conditions, watchpoints), media (which loader a file needs),
                   controller, editor, theme, system_open, asset_icons, ...
  panels/          the dockable views: emulator, registers, memory cells, memory
                   map, disassembly, call stack, analysis, inspector, output_console
                   + the in-app editors (sprite_editor_view, beeper_sfx_editor_view)
  workspace/       project.py, settings*, builder.py, asset_build.py, search.py,
                   sld.py -- your project and how it gets built, as opposed to
                   the machine
  templates/       project48 / project128 starter projects; addons/ (ZX0)
tests/             unit, integration (ROM boot), zexall harness. A package (see
                   tests/__init__.py for why), with conftest.py isolating settings.
dev-support/       this file, screenshots, ZEXALL binaries (git-ignored .com)
```

Design intent: the core is UI-agnostic and the instruction handlers are
spelled out explicitly for **educational readability** (a learner can search a
mnemonic and read its code). Each package `__init__.py` is an educational
overview — start there. `main.py` is now the composition root and the emulator view
is one dockable panel among many, as this section originally predicted.

## Key decisions made

- **Fresh pure-Python emulator**, not a port of FUSE. FUSE (`E:/github/fuse`,
  GPLv2) is used only as a reference. Only the ROM binaries are reused.
- **PyQt5** UI; **numpy** for fast rendering.
- **48K first, designed for 128K** (paged memory abstraction already in place).
  *Since done: the 128K is wired up, `Machine128` + both ROMs + the AY.*
- ~~**No built-in code editor** planned — the IDE will open sources in an external
  editor.~~ **Reversed in Milestone 2:** the editor is in-app, central and multi-tab,
  with a breakpoint gutter. Only the *assembler* stayed external.
- Instruction tables refactored to explicit per-family files; DDCB/FDCB kept
  generated on purpose as a contrast/demo.

## Known limitations / deferred (not bugs)

- **zexdoc/zexall not fully run** — impractically slow in CPython (~5B
  instructions / ~3h and still not done, zero errors seen). A FUSE
  cross-audit confirmed no observable-behaviour bugs. Full pass would need
  PyPy or an overnight run.
- **3 undocumented-flag simplifications** (don't affect real software; marked
  with `# NOTE:` in code): SCF/CCF X/Y sourced from A (no `Q` register);
  BIT b,(HL) X/Y from `(HL+1)>>8` instead of MEMPTR; EI enables interrupts
  immediately (no 1-instruction delay).
- **Block instructions run one iteration per step()** (LDIR/CPIR/INIR/OTIR/... rewind
  PC by 2 to repeat, like real hardware) — *changed from the old atomic loop*, which
  overshot the frame by ~1.2M T-states on the 128K boot RAM-clear and desynced audio.
  Now each iteration is correctly billed 21/16 T-states and the frame loop keeps control.
- **Beeper models one bit, not two.** Real hardware sums port 0xFE bit 4 (EAR) *and*
  bit 3 (MIC) into the speaker through different resistors, giving four output levels;
  `ula.py` keeps only bit 4, so we produce two. Engines that use MIC for extra dynamic
  range will sound flatter here than on hardware. No game tested so far uses MIC, so
  this is theoretical for now rather than an observed problem.
- **Timing** is functional, not cycle-accurate: contention is modelled/tested
  but not applied to every memory access; no per-scanline border effects.
- ~~**Turbo tape loaders don't load.**~~ **Fixed** by edge replay (see the 2026-07-25
  session). Fast loading still can't serve them — a loader that times its own bits never
  calls the ROM routine — but turning **Load ▸ Tape Deck ▸ Fast Load** off gives them the
  real pulse train instead. The cost is real tape speed: minutes for a full game, exactly
  as on hardware. Fast load stays the default because most of the time you want the bytes,
  not the ceremony.

## Performance notes

- ~12 ms to emulate one frame + ~0.5 ms to render → comfortable 50 fps.
- **Run without a debugger.** Under VS Code's debugger (F5) the per-line trace
  hook makes the CPU loop ~6x slower (~13 fps). Use `python main.py` or
  Ctrl+F5 ("Run Without Debugging"). The window title shows a live
  fps / timer / emulate-ms readout.

## Likely next steps

**Milestone 2 (the IDE shell) is substantially done** — the "Full IDE" commit
shipped the dock layout, an in-app editor (Z80 highlighting + breakpoint gutter),
a folder project system + `zxide.json`, sjasmplus settings, a sjasmplus build →
.sna load pipeline, and a v1 debugger (registers + step + breakpoints + live hex).
See DEV_PLAN.md for the phase-by-phase state. The one deferred piece is Phase E,
the visual drag-drop memory management.

**Milestone 3 — hardware & audio** (core work; make the machine complete):

1. **Beeper (1-bit sound)** ✅ *done* — port 0xFE bit 4. Two-layer audio pipeline:
   `zxemu_core/beeper.py` (`Beeper`: timestamped speaker flips → float PCM, duty-
   cycle resample + DC blocker) and `zxemu_ui/audio_output.py` (`AudioOutput`:
   QtMultimedia 16-bit push sink, fails quiet). Machine timestamps flips at the
   frame T-state; controller pushes samples per tick, mutes on pause/debug.
   Sound sources live one-per-file (`beeper.py`, `ay.py`) and are summed by
   `mixer.py` (`SoundMixer`) — the software stand-in for the resistor network that
   does the mixing in hardware. Sources share a three-member contract (`enabled` /
   `end_frame` / `take_samples`) and know nothing about each other.
2. **128K machine + AY-3-8912** ✅ *done* — `Machine128(Machine)` on the existing paging
   abstraction: port 0x7FFD (RAM→slot3, ROM select, screen bank 5/7, paging lock),
   the two bundled 128 ROMs, 70908-T frame. `create_128k_memory` builds the 8-RAM +
   2-ROM pool. Shadow screen via `machine.display_memory()`. 128K `.sna` load added
   (`load_sna_128k`). The **AY-3-8912** (`zxemu_core/ay.py`: 3 tone + noise + 10-shape
   envelope, log amplitude table) mixes into the beeper stream through
   `SoundMixer` (`machine.audio`). Machine model is per-project (`zxide.json` `model`
   field); chosen at New Project, swapped on project open via `MainWindow.set_machine`
   / `controller.set_machine` / `machine_factory.build_machine`. Memory-map pane shows
   bank identities + a live 0x7FFD readout. `project128` sjasmplus template added.
   fuse (E:/github/fuse) was the behavioural reference (reference-only, GPLv2).
3. **TAP support** — *fast (ROM-trap) load done*. `zxemu_core/storage/tape.py` parses `.tap`
   into blocks (`parse_tap`/`TapeBlock`/`TapeDeck`) and `fast_load()` emulates the ROM's
   `LD-BYTES` by delivering a whole block at once. Hooked via a generic
   `Z80.set_trap(pc, handler)` (near-zero-cost: one int compare per step) and
   `Machine._tape_trap`, which guards on a `LD-BYTES` byte signature so it fires on the
   48K ROM and only when the 128K's 48-BASIC ROM (ROM1) is paged — correct for both
   models. **The trap address is `0x0562`, the routine's first tape sample, not its entry
   at `0x0556`** — multi-part game loaders do the preamble themselves and `CALL 0x0562`,
   so a trap on the entry never sees them and the game hangs in the ROM's edge loop
   (found via Aliens: Neoplasma II). Consequences worth knowing: the flag byte and
   LOAD/VERIFY carry are read from the **shadow `AF'`** (the preamble's `ex af,af'` put
   them there), and the trap no longer forces `EI` — BASIC's path returns through
   `SA/LD-RET` (0x053F) which does that itself, which also means pressing BREAK/SPACE
   during a load now raises `D BREAK` as on real hardware. A second fix from the same
   session: a **flag mismatch now advances the play head**. It used to leave it parked, so
   a `LOAD ""` searching for a header past somebody else's data block re-read the same
   rejected block forever (~320k times in 1942 before we caught it) — a real cassette keeps
   rolling, and that is how LOAD finds a program that isn't first on the tape.
4. **`.z80` and `.tzx` loading** ✅ — `storage/z80.py` reads v1/v2/v3 snapshots (48K and 128K,
   RLE-compressed pages, border/paging/AY restored; strict about machine model, like `.sna`).
   `storage/tzx.py` reduces the TZX container to the blocks the fast loader can serve and
   logs what it skipped. Both wired into Load Snapshot… / Load Tape… / Load Recent.
   Validated against the whole library on disk: 74/74 `.z80` load, 44/45 `.tzx` parse (the
   45th is a ZX81 tape, correctly refused by name). Turbo-loader games still need edge replay. UI: a dedicated **Build ▸ Load Tape…** item (beside Load Snapshot…) inserts a
   `.tap` (insert + reset + log; dev then types `LOAD ""`); also on Load-Recent. Fast
   load is always on for now — the core flag `Machine.fast_load_enabled` exists but there
   is deliberately **no UI toggle** yet, because with edge replay deferred "off" would
   just hang the ROM (it would poll for tape pulses that nothing generates); reintroduce
   the toggle when edge replay lands. Verified end-to-end: a real 48K boot + `LOAD ""`
   loads a BASIC program into PROG with no error. **Deferred:** authentic edge-level replay
   (pilot/sync/data pulses on port 0xFE bit 6 → loading stripes + tape sound); the block
   model is the shared foundation for it.

Order: beeper ✅ → 128K+AY ✅ → TAP fast-load ✅ → (optional TAP edge replay) → then
Phase E (visual memory management).

Still-optional backlog: full zexall pass under PyPy; the 3 undocumented-flag
items; disassembly/watchpoint debugger polish.
