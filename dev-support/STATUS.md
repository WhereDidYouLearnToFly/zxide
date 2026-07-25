# zxide — project status & handoff

_Last updated: 2026-07-24._ A snapshot to make it easy to pick the project back up.

## Latest session (2026-07-24) — build target, tape trap, new formats, editor navigation

**658 tests pass** (`pytest tests/unit tests/integration`).

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
6. **Two test-infrastructure repairs**, both pre-existing and both worth knowing about:
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

**342 tests pass** *(at the time of that session — 658 now)*.

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
- **Turbo tape loaders don't load.** Fast loading intercepts the ROM's routine, so a
  loader that times its own bits and never calls it gets no help — it needs edge-level
  replay (deferred). Affects many commercial `.tzx` releases (Speedlock and friends);
  they stop after a block or two. Not a bug in the trap.

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
