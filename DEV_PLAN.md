# zxide — Development Plan (Milestone 2: the IDE shell)

zxide is becoming a **"Unity for ZX Spectrum"**: an IDE built around the Milestone-1
emulator core. Milestone 1 (a working pure-Python Z80 core + live PyQt5 view) is done — see
`dev-support/STATUS.md`. This document plans Milestone 2, where the single emulator window
grows into a full IDE shell, and records the architecture decisions behind it so intent
survives between work sessions.

The raw original vision notes are preserved verbatim at the end ("Appendix: original vision").

---

## The shape of the IDE

A dockable, rearrangeable shell, Visual-Studio-style. A `File` menu owns project entry
(New / Open Project / Open Folder / Recent); the emulator carries its own control strip.

```
┌────────────────────────────────────────────────────────────────────┐
│ File  View  Build  Debug  Help                              (menu)  │
├──────────┬─────────────────────────────────┬───────────────────────┤
│ PROJECT  │  main.asm │ notes.txt   (tabs)  │  ▶ ⏸ ⏭ ⭮   EMULATOR  │
│ ▾ Source │                                 │  ┌─────────────────┐  │
│  main.asm│        EDITOR (central,         │  │  screen (48K)   │  │
│ ▾ Assets │        multi-view / split)      │  └─────────────────┘  │
│  hero.bmp│                                 ├───────────────────────┤
│  map.bin │                                 │  MEMORY CELLS (hex)   │
│  song.pt3│                                 │  [Memory|Output|Disasm]│
│          ├─────────────────────────────────┼───────────────────────┤
│          │  INSPECTOR (floatable)          │  REGISTERS / FLAGS    │
│          │                                 ├───────────────────────┤
│          │                                 │  MEMORY MAP  [Des|Dbg]│
├──────────┴─────────────────────────────────┴───────────────────────┤
│  50 fps | timer 100Hz | emulate 12ms/frame             (status bar) │
└────────────────────────────────────────────────────────────────────┘
```

Left = code work · Center = editor · Right = the running machine. See the live mockup for
proportions and interactions.

## Window & docking model

Built on stock Qt `QMainWindow` + `QDockWidget` — no third-party docking library
(evaluated the Qt Advanced Docking System / PyQtAds for full VS-style floating + auto-hide
pins, but the model below needs no extra dependency, and the core stays pure Python).

- **Editor = the central widget** — the fixed anchor everything docks around; being central
  it is inherently non-floatable. It is a **multi-view split area** (nested `QSplitter`s of
  tab groups) so files can sit side-by-side, VSCode-style (ship single-pane first, enable
  splitting once open/edit/save + Z80 highlighting + the breakpoint gutter work). Two views
  of one file share a single `QTextDocument` so edits and debugger markers stay in sync.
- **Project tree = a locked dock** on the left (movable/floatable features off) — always
  where you expect it.
- **Every other panel is a floatable `QDockWidget`** — emulator, memory cells (hex),
  registers/flags, memory map, inspector, output — so users can drag them, **tab them
  together** (drop one onto another), float them as windows, or hide them (each dock gives a
  View-menu toggle for free).
- **Layout persistence & presets:** `saveState()`/`restoreState()` serialise the whole
  arrangement; named presets give us the **Design** and **Debug** workspaces (Design
  foregrounds the memory map + inspector + assets; Debug foregrounds registers +
  disassembly + memory).
- **Emulator** keeps its own control strip (Run/Pause/Step/Reset) and scales responsively
  inside whatever dock size it's given.
- Trade-off accepted vs. full Visual Studio: no auto-hide "pushpin" (could adopt PyQtAds
  later if wanted).

---

## Load-bearing decision: memory is modeled as banks

The core is already paging-ready: `Memory` is four 16K slots, each backed by a swappable
`Bank`, with a `page(slot, bank)` hook (`zxemu_core/memory.py`). 48K wires it statically
(1 ROM + 3 RAM); 128K becomes a bank *pool* paged via port 0x7FFD. The UI must mirror this
**from day one**, even while we are 48K-only:

- **Model memory as banks (16K each), not a flat 64K array.** The 64K address space is a
  *projection* — whichever banks are currently paged into slots 0–3.
- The memory panel offers two views:
  - **"As the CPU sees it"** — the live 64K window (what PC/SP point at, what the ULA reads).
    The debugging default.
  - **"By bank"** — every bank (ROM0/1, RAM0–7), including ones *not* currently mapped in, so
    a paged-out bank is still inspectable and editable.
- **Assets and addresses are identified as `(bank, offset)`, not a bare 16-bit address**, so
  placement survives paging on 128K. On 48K this degenerates to the fixed map — nothing lost.
- The memory view surfaces the **current paging state** (the 0x7FFD value / which bank sits
  where).

The payoff: 128K becomes a *data* change, not a UI rewrite, and it costs essentially nothing
now because 48K is the trivial case.

---

## The memory view: two modes, one widget

A single bank-oriented widget with a **Design ⇄ Debug** toggle:

- **Design (before build)** — *where do assets live?* Drag-drop an asset onto a
  `(bank, offset)`, or hit **auto-locate** to place it in free space; this generates the
  `ORG` / `incbin` directives (or a memory manifest) the assembler consumes.
- **Debug (at run-time)** — *what is memory doing right now?* Live values, PC/SP markers,
  edit-a-byte, watch the screen bank change. The visual map is the overview you click into
  for hex detail.

---

## The debugger track

Cheap to build, because the core already exposes the pieces:

- `cpu.step()` runs exactly one instruction and returns its T-states → **single-step is
  nearly free**.
- `cpu.regs` holds every register (PC, SP, AF, BC/DE/HL + primes, IX, IY, I, R, IM) → a
  **registers/flags panel** is a read-out.
- `memory.read_byte` / `write_byte` → a **live, editable hex/memory view**.
- The **one real core addition** is a *debug run mode*: step instruction-by-instruction and
  check breakpoints (halt when `PC == bp`), instead of the fast atomic `run_frame()`. So the
  emulator controller carries two modes — **normal** (fast, frame-at-a-time) and **debug**
  (slower, can stop mid-frame).

v1 debugger minimum-viable = **registers + single-step + live memory view**; breakpoints,
disassembly, and watchpoints follow.

---

## Milestone 2 roadmap (phased)

Milestone 2 (the IDE shell) is **substantially complete** — the "Full IDE" commit landed
Phases A–D plus the editor and debugger tracks. What remains of the original plan is the
visual-memory centerpiece (Phase E), now deferred behind a new **Milestone 3: hardware &
audio** (128K, AY, beeper, TAP) — see below.

- **Phase A — IDE shell layout** ✅ *done*: the dockable `QMainWindow` per the **Window &
  docking model** above — editor central, Project a locked left dock, and emulator /
  memory-cells / registers / memory-map / inspector / output as floatable docks; File / View /
  Build menus; layout save/restore. The frame pump lives in an `EmulatorController`
  (run/pause/reset/step + breakpoints, `frame_ready` / `status_changed` / `breakpoint_hit`
  signals); the emulator has its own control strip and the fps readout is in the status bar.
- **Editor track** ✅ *done* *(supersedes "no built-in editor")*: an in-app multi-tab text
  editor (`editor.py`), Z80 syntax highlighting (`z80_highlighter.py`), a breakpoint gutter,
  and an execution-line marker that tracks PC. Doubles as the debugger's source view.
- **Phase B — Project & asset system** ✅ *core done*: a folder-based project with a
  `zxide.json` manifest (`project.py`), a starter `main.asm` template, and the left tree bound
  to the real folder with New File / New Folder. *Remaining:* first-class **asset import**
  (bmp / binary / pt3 / beeper sfx) — folds into Phase E.
- **Phase C — External tools** ✅ *done*: sjasmplus auto-detected on `PATH` (overridable) via
  app `Settings` + a `SettingsDialog`; per-project build args in the manifest. (VS-Code "open
  in external editor" not wired — the in-app editor made it optional, as planned.)
- **Phase D — Build pipeline** ✅ *done*: `builder.py` shells out to sjasmplus, streams output
  to the Output console, and on success loads the emitted **.sna** (`zxemu_core/snapshot.py`)
  and runs. Source-level debug info (`sld.py` + `zxemu_core/disassembler.py`) maps source
  lines ⇆ addresses for breakpoints. *Later formats:* .szx / .tap / raw binary.
- **Debugger track** ✅ *v1 done*: registers/flags panel, live hex memory view, **breakpoints**
  (Build & Debug = F5 honours them; Build & Run = Ctrl+F5 ignores them) with the execution line
  highlighted in the editor, and **Step Into (F11) / Step Over (F10) / Step Out (Shift+F11)** —
  step-over runs CALLs, RSTs and repeating block ops (LDIR/...) to completion; step-out runs to
  the current subroutine's RET. Both honour breakpoints hit inside, and share one
  `_run_until` engine. A **live disassembly panel** (`disassembly_view.py`, own Disassembly menu)
  decodes around PC as you step. **Watchpoints** (own Watch menu) pause on a memory
  value changing or on IN/OUT of a port — ports by true interception (the CPU's io hooks
  are swapped, so the fast path is untouched when unused), memory by value comparison in
  the debug loop rather than by instrumenting the emulator's hottest methods.
  A **call stack** panel infers the caller chain from raw stack contents (the Z80 records
  no frames), **conditional breakpoints** (`debug_expr.py`) gate a stop on an expression,
  **ROM routine names** (`rom_symbols.py`) annotate disassembly and call stack, and the
  registers panel carries a **T-state read-out** (frame position, cost of the last step).
  Memory watchpoints cover **reads as well as writes** via an instrumented `Memory`
  subclass swapped in only while watches exist. **Run to Cursor / Run to Address**
  (one-shot breakpoints), plus **editing**: poke a byte in the Memory panel, click a
  register to set it. The **RE toolkit** landed too (`analysis.py` + `analysis_view.py`,
  own Reversing menu): memory search, cross-references, a coverage map, and a bounded
  execution trace; plus a **symbol database** — `sld.py` now reads the SLD's label
  records, so your own names appear in the disassembly and Go-to-Label works.
- **Phase E — Visual memory management** ⏸ *deferred* *(the centerpiece)*: the bank-oriented
  memory map (`memory_map_view.py`) and hex cells (`memory_cells_view.py`) exist as debug
  read-outs; the **drag-drop asset placement + auto-locate** design step (generating
  `ORG` / `incbin`) is not built yet. Picked up after Milestone 3.

---

## Milestone 3 roadmap: hardware & audio *(current)*

The next push makes the emulated machine *complete* — sound, the 128K model, and tape
loading — before returning to the Phase-E visual tooling. All of this is **core** work
(`zxemu_core/`), UI-agnostic, with thin UI hooks. Chosen order and why:

- **1. Beeper (1-bit sound)** ✅ *done* — port `0xFE` bit 4 drives the speaker. Establishes
  the **audio output pipeline**, built in two layers: `zxemu_core/beeper.py` (`Beeper`, a
  UI-agnostic stage that resamples timestamped 1-bit speaker flips → float PCM via time-
  weighted duty-cycle averaging + a DC blocker so held levels fall silent), and
  `zxemu_ui/audio_output.py` (`AudioOutput`, a QtMultimedia push-mode 16-bit sink that fails
  quiet and drops-rather-than-lags). The `Machine` timestamps each speaker flip at its frame
  T-state and calls `beeper.end_frame()`; the `EmulatorController` pushes samples each tick
  and mutes during pause/debug. Audio is opt-in (`beeper.enabled`) so tests/headless pay
  nothing. **This is the stream the AY mixes into.**
- **2. 128K machine + AY-3-8912** ✅ *done* — `Machine128(Machine)` on the existing paging
  abstraction: port `0x7FFD` (RAM bank→slot 3, ROM select, screen bank 5/7, paging lock),
  the two bundled 128 ROMs, the 70908-T frame. `create_128k_memory` builds the 8-RAM + 2-ROM
  pool; shadow screen via `machine.display_memory()`; 128K `.sna` loading via `load_sna_128k`.
  The **AY-3-8912** (`zxemu_core/ay.py`: 3 tone gens, 17-bit noise LFSR, 10-shape envelope,
  logarithmic amplitude table, timestamp-then-render like the beeper) mixes into the beeper
  stream through a new `SoundMixer` exposed as `machine.audio`. Machine model is per-project
  (`zxide.json` `model`), chosen at New Project and swapped **on project open** via
  `MainWindow.set_machine`/`EmulatorController.set_machine`/`machine_factory.build_machine`.
  The memory-map pane shows per-slot bank identity + a live `0x7FFD` readout; a `project128`
  sjasmplus template (`device zxspectrum128`, demonstrates paging + AY) was added. All
  behaviours cross-checked against fuse (E:/github/fuse) as a **reference only** (GPLv2,
  independent reimplementation — no code copied), the same policy used for the CPU.
- **3. TAP support** *(next)* — load `.tap` tape images: either the fast **ROM-trap** LOAD
  (intercept the ROM loader for instant loads) or real edge-level replay through port `0xFE`
  bit 6. Complements the existing .sna path; also a candidate build output.

*Deferred to Milestone 4:* Phase E visual memory management (drag-drop asset placement +
auto-locate + asset import), disassembly/watchpoint debugger polish, .szx/.pt3 playback.

Rough order: **beeper → 128K+AY → TAP**, then back to Phase E.

---

## Future directions (the full backlog)

The agreed roadmap of where zxide can go after Milestone 3. **★ marks the educational
wins** -- the north star is "a learner can search a name, step through real code, and
understand what the machine is doing." Grouped by theme, not strictly ordered; the
**recommended sequence** is at the end.

### 1. Debugging & reverse-engineering (the RE toolkit)
- **★ Live disassembly panel** -- disassemble around PC as you step; the foundation for
  everything else here (the core `disassembler.py` already exists).
- **★ Annotated ROM source for debugging** -- when PC is in ROM, show the *labelled*
  disassembly (`KEY-SCAN`, `PRINT-A`, `CHAN-OPEN`, ...) from a public ROM map, with
  comments, so stepping through the ROM shows *which routine you're in*. The standout
  educational feature.
- **Symbol / label database** -- labels from the build's SLD + the ROM map + user-defined,
  surfaced everywhere (disasm, memory, breakpoints); go-to-label / go-to-address.
- **Cross-references** -- "what calls this address / reads this byte?" (static scan + trace).
- **Execution trace / history** -- a rolling log of executed instructions; step *backwards*.
- **Coverage map** -- highlight which addresses have actually executed.
- **Conditional & data breakpoints / watchpoints** -- break on `A==5`, or on a read/write to
  an address (not only PC).
- **Call-stack view** -- reconstruct the return-address chain.
- **Memory search** -- find bytes / text / patterns; mark regions as code vs data.
- **★ Register/flag tooltips & a T-state (cycle) counter** -- hover a flag to learn what it
  means; show the selected instruction's cycle cost.

### 1b. Memory → sources: turn a running program into a debuggable project ★

*Menu home: **Reversing**, alongside the RE toolkit above — the dumper consumes exactly
those results (coverage decides what is code, cross-references supply the labels), so
they belong under one heading rather than as a separate feature.*

Dump a machine's RAM into `.asm` sources plus a `zxide.json`, so an existing program
becomes a project you can build, step through, and annotate. The educational payoff is
large — "here is a game, here is its source, now step through it" is a far better
on-ramp than an empty `main.asm` — and it is the natural consumer of the RE toolkit
above rather than a separate feature.

**The whole difficulty is telling code from data**, which is undecidable statically:
the same bytes are a valid instruction stream *and* a valid bitmap. So don't decide
statically.

- **Coverage is the ground truth.** An address that executed *is* code — observed, not
  inferred. Load the snapshot, run it while recording coverage (play the menu, trigger
  the thing you care about), then dump: executed regions become disassembly, everything
  else stays `db`. The more you exercise, the better the source gets.
- **Degrade gracefully.** A region wrongly left as `db` still assembles to the right
  bytes and still runs — you just have a blob you have not understood yet. So v1 can
  dump *everything* as `db`: correct, useless, and a complete foundation.
- **The invariant that makes it trustworthy: assemble the dump and compare bytes with
  the original memory.** Byte-identical means the source provably represents the
  program. Build this check *first* — it works from day one against an all-`db` dump,
  before any classification exists, and then every promotion of a region from `db` to
  disassembly is individually verifiable by the same test.
- Labels come from cross-references (anything called/jumped to becomes `label_8123:`)
  and `rom_symbols` for ROM targets.

Known traps: skip the ROM (`$0000-$3FFF` is not yours); self-modifying code makes a
mid-run dump differ from a load-time one (dump both and diff); a 128K dump must record
which bank each region came from; 48K of RAM is too much for one file, so split by
region.

**Classifying the leftover blobs** — in cost order, cheapest first, because the early
steps do most of the work:

1. **Where it is copied to.** A block `LDIR`'d to `$4000-$57FF` is a screen bitmap; to
   `$5800-$5AFF`, attributes. That is the hardware memory map, not a guess, and
   cross-references already tell us what loads a pointer to the region.
2. **Render it.** Draw the blob as a 1bpp Spectrum bitmap in the Inspector and a human
   recognises a sprite sheet or a font instantly. The screen renderer already exists;
   pointing it at an arbitrary address is nearly free. Nothing beats eyes here.
3. **Cheap statistics.** Attribute bytes cluster in a narrow range; text is ASCII-ish;
   ZX0-compressed data is high-entropy; a region where many bytes decode to illegal
   opcodes is not code.
4. **ML, last.** Its real niche is the residue — "a structured table, 6 bytes per entry,
   but of what?" — which is stride/field-regularity detection. Smallest slice, and it
   needs labelled examples from already-disassembled games to train on.

**The dump should be *runnable*, not just readable** — it is a snapshot, expressed as
assembly. That means it must carry what a snapshot carries: not only RAM but the CPU
state — PC, SP, AF/BC/DE/HL and their shadows, IX, IY, I, R, the interrupt mode and
IFF, the border, and on a 128K the `$7FFD` latch.

That creates one genuinely awkward problem: **you cannot restore registers without
using registers.** It needs a small stub that sets SP, pushes the saved values, pops
them into place and ends with `RET` — which is precisely how `.sna` itself works, with
PC left on the stack for that final `RET` to jump to. So the assembly can mirror the
format it came from.

But the stub has to *live* somewhere, and the dump has already claimed every byte of
RAM. That is the one place the output cannot be byte-faithful. Usual homes: the printer
buffer at `$5B00` (256 bytes, almost nothing uses it) or screen memory, if the program
redraws it on entry anyway.

**So emit two artefacts, not one** — otherwise the correctness invariant gets littered
with "except these twelve bytes":

  * a **faithful dump** — pure `db`/code, no stub, byte-identical to the original. This
    is what the round-trip test checks, and it stays exact.
  * a **runnable project** — the same data plus the restore stub and a `SAVESNA`. This
    is what you build and step through, and it gets its *own* exact test: build it,
    load the resulting `.sna`, and compare the emulator's full state — registers
    included — against the original snapshot's.

Two tests, each precise about its own thing, instead of one test with excuses.

Note the symmetry with Phase E: that places assets *into* memory, this pulls them
*out*. Both need the same "what lives where" model, so they should share it.

### 2. Tape & snapshot formats
- **TAP loading** (ROM-trap fast load + edge replay) -- closes Milestone 3.
- **TZX** -- the richer tape format (turbo loaders, custom timing).
- **More snapshots** -- `.z80`, `.szx` (load *and* save, so machine state can be saved).
- **Tape-deck UI** -- play / stop / rewind, block list, "insert tape."

### 3. Visual memory management (Phase E -- the "Unity" centerpiece)
Superseded by the detailed **Milestone 4: Asset workflow (Phase E)** section below --
this backlog line is kept only as an index pointer.

### 4. Sound & hardware completeness
- AY **stereo** (ACB/ABC), and an **AY register/scope panel** to watch the chip live. ★
- **128K RAM disk**.
- **PT3 / beeper-SFX playback** for imported audio assets.
- *(Skipping +2/+3 machine variants -- little used today.)*

### 5. Editor & project
- **Build-error jump** -- click an sjasmplus error -> jump to the source line.
- **Symbol navigation** in the editor (go-to-definition for labels).
- **★ Lua syntax support** -- sjasmplus embeds a Lua interpreter (`LUA ... ENDLUA` blocks,
  the `sj.` emit/label API) for compile-time metaprogramming (lookup tables, codegen).
  Highlight Lua inside those blocks and in standalone `.lua` files; add `.lua` to the
  editable-text suffixes.
- **Multiple build targets / configs**; **.szx or .tap as a build output**.
- **Richer project templates** (a game skeleton, an AY music demo).

### 6. Polish / fixes
- **Runtime swap-pause bug** -- opening a 128K project *while running* pauses the controller
  without resuming (startup swap is fine; only a live swap is affected).
- Per-scanline **border effects** and tighter **contention** (a cycle-accuracy pass).
- Optional **zexall under PyPy** as a conformance gate.

### Recommended sequence
**TAP** (finish M3) -> then the **RE / debugging toolkit** (disassembly panel + labels +
annotated ROM source) as the strongest *educational* bet, reusing the existing debugger ->
then **Milestone 4 / Phase E** (the flashier "product" feature). The RE toolkit is where
the *teaching* happens; Phase E is where zxide feels most like "Unity for the Spectrum."

---

## Milestone 4: Asset workflow (Phase E)

Today there is **zero asset tooling**: no importers, no placement UI, no build-time asset
codegen. The memory map is a read-only debug view (PC/SP markers only); the project
manifest has no `assets` concept. This milestone builds the whole pipeline end to end --
import, place, build, preview -- in six steps, each independently testable before the next
begins.

**1. Core, Qt-free asset modules** (`zxemu_core/assets/`, mirrors the `debug/`/`sound/`
package split):
- `manifest.py` -- `AssetKind` enum (`bitmap`, `sprite_sheet`, `sprite_sequence`, `font`,
  `tilemap`, `binary`, `pt3`, `beeper_sfx`) and `AssetEntry` (`id`, `source` -- a path, or
  a list of paths for `sprite_sequence` -- `kind`, `symbol`, `placement`: `"auto"` or
  `{bank, offset}`, plus kind metadata below), with `to_dict`/`from_dict`. `sprite_sheet`,
  `sprite_sequence`, and `font` all produce the same shape -- a `FrameSequence` (ordered
  frames, common `frame_width`/`frame_height`/`frame_stride`, optional mask) -- so
  anything downstream (Inspector preview, Milestone 5's `draw_sprite`) treats them
  identically regardless of import path. There is **no separate "tileset" kind** -- a
  tileset/palette is just a `sprite_sheet`/`sprite_sequence` asset used in a different
  role (see `tilemap`).
- `bmp_convert.py` -- BMP -> Spectrum format:
  - **`bitmap`** (full-screen 256x192) -> 6144-byte bitmap + 768-byte attributes
    (nearest-color match per 8x8 cell against the 8-color normal/bright palette --
    `emulator_view.py`'s RGB tables are the reference, duplicated here since core can't
    import `zxemu_ui`); attribute-clash warnings (>2 colors/cell) returned to the caller.
  - **`sprite_sheet`** -- a BMP holding a grid or strip of equal-sized frames. Explicit
    params (no auto-detection, ambiguous for irregular sheets): `frame_width` (multiple
    of 8), `frame_height` (any), `layout` (`{"grid": {cols, rows}}` or `{"strip": {axis,
    count}}`). Frames pack 1bpp row-major MSB-first, no screen interleaving, all the same
    byte stride so code addresses any frame as `label + frame_index * frame_stride`; a
    frame-count constant is emitted alongside the label.
  - **`sprite_sequence`** (the animation-flip case) -- an ordered list of individual
    same-sized image files, each file *is* one whole frame. Dimensions read off the first
    file and validated identical across the rest; frame order is the list order (natural
    filename sort by default, reorderable). Converts to the identical `FrameSequence`
    shape as `sprite_sheet`, through the same mask path, so both feed one packing routine.
  - **Mask generation is a per-asset toggle** (`generate_mask`, off by default, both
    `sprite_sheet` and `sprite_sequence`): converts a chosen `mask_color` (sampled from
    the source image's own palette) into a paired AND-mask plane per frame, adjacent to
    its pixel data; off emits only the raw bitmap. Toggling later just re-runs the
    converter.
  - **`font`** -- a `FrameSequence` of glyphs, reusing the grid slicer wholesale, with
    `frame_width`/`frame_height` defaulted to 8x8 and no mask (glyphs are OR/XOR-plotted,
    not overlay-masked). The one new bit of metadata is `first_char_code` (default `32`),
    emitted as an `equ` so code indexes a glyph as
    `label + (char_code - first_char_code) * frame_stride`. Two source paths land on the
    same converter: a BMP grid, or a pre-packed raw binary charset (skips slicing, just
    `binary_convert` passthrough plus the same metadata attached).
- `binary_convert.py` -- passthrough with optional length check.
- `tilemap_convert.py` -- **`tilemap`**, the level-layout asset: instead of a full pixel
  bitmap per screen, a grid of small tile-index bytes referencing a tileset (any
  `sprite_sheet`/`sprite_sequence` asset, at whatever tile size it was imported at --
  8x8, 16x16, custom). The actual space win: a 32x24 grid of 8x8 tiles is 768 index bytes
  vs. 6144+768 for a raw bitmap; a 16x16 tileset over the same area is 192 bytes.
  - Metadata: `tileset_symbol` (the "palette" asset's symbol), `map_width`/`map_height`
    (in tiles). A tileset can be shared across levels or dedicated to one -- structurally
    identical either way, just which `AssetEntry` the symbol points at.
  - Source format (v1, hand-authored -- no in-app level editor yet): a plain JSON grid,
    e.g. `{"tileset": "tileset_forest", "width": 32, "height": 24, "tiles": [[0,0,1,2,...],
    ...]}`, indices validated against the tileset's real frame count at convert time. This
    is the one converter needing the full asset registry, not just its own source file.
  - Packing: one byte/tile by default (up to 256 tiles); an optional `pack_nibble` toggle
    (mirrors `generate_mask`) halves this to 4 bits/tile when the tileset has <=16 frames.
  - **Deferred**: importing an existing level-editor format (Tiled's `.tmx`/`.json`). The
    representation above is chosen so that's a straightforward later converter, not a
    restructure.
- `pt3_convert.py` -- passthrough + `PT3` magic-header check (playback stays a separate
  backlog item).
- `beeper_sfx.py` -- v1 text format (`period_tstates,duration_frames` pairs) compiled to a
  sentinel-terminated binary table.
- `registry.py` -- suffix -> converter dispatch, used by both the import UI and the
  build-time regenerator.
- `preview.py` -- `render_frame_rgb(frame_bytes, width, height, attr_byte)`, a
  non-screen-scrambled renderer for standalone frame previews (kept separate from
  `emulator_view.render_screen_rgb`, which assumes live hardware screen layout).
  `render_sheet_rgb(sequence)` tiles every frame into one grid image (fonts, and sprites
  too). `render_tilemap_rgb(tilemap, tileset_sequence)` composites a whole level preview
  by stamping tileset frames into the grid the tilemap specifies.

**2. Free-space / placement model** (`zxemu_core/memlayout.py`, a top-level sibling of
`memory.py` -- not nested under `assets/`, since the future memory-dumper (see "1b" above)
needs the same "what lives where" model):
- `bank_ids_for_model(model)` -- `["rom","ram1","ram2","ram3"]` (48K) vs.
  `["rom0","rom1","ram0".."ram7"]` (128K).
- Reserved-range table per bank (ROM fully reserved; the screen bank reserves its first
  `SCREEN_BYTES` -- reuse the constants already in `memory_map_view.py`).
- `FreeSpaceIndex`: `place(bank, offset, length)`, `free_ranges(bank)`,
  `auto_locate(length, prefer_banks=...)` (first-fit bin packing, RAM before screen-bank
  leftover space, never ROM).
- **Known v1 limitation, stated explicitly**: "free" only excludes hardware-reserved
  ranges and other placed assets -- it does not yet know where the user's own hand-written
  `ORG`'d code lives (the same undecidable-without-execution problem as "1b" above). The
  UI must warn accordingly; a real fix extends `sld.py` to capture the currently-ignored
  `page` column.

**3. Manifest additions** (`zxemu_ui/workspace/project.py`): `"assets": [...]` in
`default_manifest()`; `Project.assets()`, `add_asset(source, kind, symbol=None)`
(auto-derives a sjasmplus-safe label), `set_asset_placement(id, bank, offset)`,
`set_asset_auto(id)`, `remove_asset(id)` -- thin read/write, matching `set_model()`.

**4. Memory Map Design mode** (`zxemu_ui/panels/memory_map_view.py`): one class, a
Design <-> Debug toggle (Debug unchanged; Design draws placed-asset rectangles from
`project.assets()`) plus an Auto-locate button. Drag-drop reuses the project tree's
existing `QFileSystemModel` `text/uri-list` drag data (`setDragEnabled(True)`) --
`MemoryMapView` adds `setAcceptDrops(True)` + drag/drop handlers and a `_hit_test(pos) ->
(bank, offset)` (inverse of `_draw_marker`). Dropping a single `.bmp` prompts a small
dialog to choose `bitmap` vs `sprite_sheet` vs `font`. `sprite_sequence` gets its own
"Import Animation Sequence..." multi-select command on the tree's context menu, since it
doesn't fit a single-file drop.

**5. Build integration** (`zxemu_ui/workspace/asset_build.py` + `builder.py`):
`regenerate_assets_asm(project)` runs each asset's converter (cached under
`.zxide/generated/<symbol>.bin`, keyed by source mtime/hash), resolves `"auto"`
placements via `memlayout`, and emits `assets_generated.asm` (generated/do-not-edit
header; one `ORG`/label/`incbin` per asset -- 48K banks map to fixed addresses, 128K uses
sjasmplus's native `SLOT`/`PAGE` directives). Every `FrameSequence` asset also gets
`equ` constants beside its label (`_FRAME_COUNT`, `_FRAME_STRIDE`, `font`s also
`_FIRST_CHAR`); `tilemap` gets `_WIDTH`/`_HEIGHT` plus a comment naming its
`tileset_symbol`, with tileset assets regenerated before the tilemaps referencing them.
`builder.build()` calls this first; a converter failure (including a bad
`tileset_symbol`) is a normal build-log error, never a crash. New templates bake in
`include "assets_generated.asm"`; existing projects get a one-time idempotent append the
first time an asset is imported.

**6. Inspector integration** (`zxemu_ui/panels/inspector_view.py`): a `set_selection(...)`
entry point wired from the project tree's selection and a new `asset_selected` signal on
`MemoryMapView`. `bitmap` reuses `emulator_view.render_screen_rgb` via a small
`Memory`-shaped adapter; `sprite_sheet`/`sprite_sequence` use `render_frame_rgb` with a
frame-index scrubber; `font` uses `render_sheet_rgb` to show the whole charset at once;
`tilemap` uses `render_tilemap_rgb` plus a field naming (and jumping to) its
`tileset_symbol`. Everything else (`binary`/`pt3`/`beeper_sfx`) gets symbol/size/placement
fields and a per-asset auto-locate action.

**Verification**: unit tests per converter asserting exact byte output for small
fixtures (including `sprite_sheet` grid/strip/mask variants, `sprite_sequence` ordering
and mismatched-size rejection, `font`'s two source paths, and `tilemap`'s packing/
nibble-packing/out-of-range/bad-reference cases); `FreeSpaceIndex` and `Project` manifest
unit tests; one integration test building a project with imported assets through the
real sjasmplus pipeline and diffing the resulting `.sna`; a manual pass in the running
app (drag a bmp onto the Design-mode map, auto-locate, Build & Run, confirm render and
Inspector preview).

**Since delivered, on top of the above -- drawing sprites in zxide, not just importing them:**
- `FrameSequence` gained an optional attribute plane (`has_attrs`): one real Spectrum
  attribute byte (ink/paper/bright) per 8x8 cell, alongside the pixel plane, instead of
  a sprite being plotted in one colour chosen at draw time. `bmp_convert.py`'s
  `generate_attrs` toggle reuses the exact same colour-clash quantization `bitmap`
  already does for the full screen, scoped to each frame.
- A native `.zxspr.json` format (`zxemu_core/assets/native_sprite.py`) for sprites
  *drawn* in zxide rather than imported -- plain pixels+attributes as human-readable
  JSON, no BMP round-trip for data that never had a source image.
  `zxemu_ui/panels/sprite_editor_view.py` is the pixel editor: ink/paper palette rows
  (real ZX colours, normal + bright), a canvas with 8x8 attribute-cell gridlines, and
  the key invariant that makes the "2 colours per cell" hardware limit a consequence of
  the tool rather than a rule you could break -- **every paint action reclaims its
  whole cell's attribute** for whatever ink/paper/bright is currently selected, so
  there is no way to accidentally leave a third colour in a cell. Autosaves on every
  edit, matching the rest of the asset system's "writes straight through" convention.
  "New Sprite Asset…" (project tree context menu) creates a blank one at a chosen
  size (8x8/16x16/custom) and frame count and opens it directly; opening an existing
  `.zxspr.json` from the tree does the same rather than treating it as generic text.
  `asset_build.py` emits an extra `_ATTR_OFFSET` equ for attributed frames (where the
  attribute plane starts within each frame's stride), and Inspector/tilemap/sheet
  previews all render true per-cell colour automatically when `has_attrs` is set.

**Also since delivered -- two follow-ups the live smoke tests surfaced or suggested:**
- **Auto-locate now avoids known hand-written code, best-effort.** The exact collision
  hit twice in testing -- a fresh asset auto-locating to `ram2` offset 0, exactly where
  a template's own `org $8000` begins -- is fixed for the common case. `sld.py` now
  parses the SLD's `page` column, which turns out (checked empirically against real
  sjasmplus output) to be the **slot** index, not a physical 128K bank. Slots 1/2 are
  hardware-fixed on both 48K and 128K (always RAM5/RAM2, never repaged), so tracing
  code there reliably means "this bank, always" -- `asset_build.reserved_code_ranges`
  reads the *previous* build's SLD (if any) and reserves those addresses before
  auto-locating. This converges over builds rather than fixing everything at once
  (there's no way to know where code lands before a first build ever runs -- the same
  undecidable-without-execution problem the memory-dumper backlog item already names),
  and **128K's slot 3 is deliberately left alone**: it can hold any of 8 banks
  depending on runtime paging the SLD has no way to see, so guessing there would be
  false confidence, not a fix. The real, complete fix stays the originally-planned one
  (treating a build's *entire* emitted image as occupied, not just traced instruction
  addresses) -- this is a meaningfully-scoped step toward it, not a replacement.
- **`beeper_sfx` playback preview.** `zxemu_core/sound/beeper_preview.py` renders a
  `beeper_sfx` asset's tone/duration list to PCM via a standalone `Beeper` (no live
  machine needed -- same "one frame at a time" contract the real machine drives it
  with), and the Inspector's new "▶ Play" button pushes the result through a freshly
  sized `AudioOutput`. (Real PT3 preview remains out of scope -- that needs an actual
  tracker player driving the AY chip live, a separate and much larger feature.)
- **A Beeper SFX editor**, since a raw T-state period is not a format anyone can
  hand-author without documentation. Unlike sprites, the existing `.zxsfx` text format
  (renamed from a plain `.sfx` to avoid colliding with other tools' generic SFX files)
  needed no new native format -- `period,duration` pairs were already a fine storage
  shape, just not a friendly *display* one. `zxemu_core/assets/beeper_sfx.py` gained
  `period_to_hz`/`hz_to_period` (period is T-states between speaker flips; frequency is
  `3500000 / (2 * period)`, the Z80 clock) and `format_beeper_sfx` (the inverse of
  `parse_beeper_sfx`). `zxemu_ui/panels/beeper_sfx_editor_view.py` is the editor: rows
  of Hz + frames + a remove button, "+ Tone"/"+ Rest"/"▶ Play", autosaving every edit
  straight to the `.zxsfx` file (same convention as the sprite editor and the rest of
  the asset system). "New Beeper SFX Asset…" (project tree) creates a blank one and
  opens it directly; opening an existing `.zxsfx` does the same.
- **Save Screenshot**, a button on the emulator control strip (next to Run/Pause/Step/
  Reset), saving the current picture two ways at once into a `screenshots/` folder
  (in the open project, or next to the app itself -- the same anchor `layout.json`
  uses -- if none is open): a real `.scr`, the classic Spectrum screen-dump format,
  exactly the 6912 bytes of display memory (`machine.display_memory()`, which already
  picks the right bank on 48K/128K, shadow screen included, so it has no concept of a
  border and never carries one) -- openable by any Spectrum-aware tool; and a `.bmp`,
  a normal viewable image. The `.bmp` is *not* a grab of the emulator widget -- that
  would only capture whatever size the dock happens to be scaling the picture to right
  now -- but `EmulatorView`'s own native 320x256 `QImage` (a new `current_image()`
  accessor), so it's always crisp at the Spectrum's real resolution, border included,
  regardless of window size.

## Milestone 5: Visual Logic (design, not yet started)

*Sequenced after Milestone 4 -- actions like `draw_sprite` need assets to already exist.
This section records the design direction; nothing here is implemented yet.*

**Scope decision**: v1 is GameMaker-style linear/branching **action lists per event**,
not a full Unreal-style typed-pin data-flow graph -- much cheaper to build and codegen on
Z80-constrained hardware, and still expressive enough for real small games.

**Runtime model**: a fixed-size **array-of-structs** entity table (AoS suits the Z80's
`LD A,(IX+d)` addressing; no hardware multiply rules out SoA's stride math), driven by
the existing 50Hz frame loop with **zero changes** to `zxemu_core/machine.py`/`cpu/` --
this milestone only changes what assembly text gets generated and run inside the
already-working frame.

**IR**: one JSON file per Object (`logic/*.zxobj.json`) with events (Create / Step / Draw
/ Key Down / Collision), each holding a linear/branching action list. v1 action
vocabulary (8 ops): `set_var`, `if`, `move_by`, `set_border`, `play_tone` (blocking),
`draw_sprite` (references a Phase-E asset **symbol** -- the clean dependency edge between
the two milestones), `wait_frames` (single-pending-wait-per-object, not a real stall),
`call_event`.

**Codegen**: generate **plain sjasmplus text per action, not `LUA...ENDLUA`**. Decisive
reason: the SLD attributes one label per emitted action, so the existing
breakpoint/disassembly/step machinery works on generated logic code with **zero debugger
changes**; routing through Lua would collapse everything to one source line and break
per-action stepping.

**Editor**: a new `logic_view.py` dockable panel -- a reorderable action-list widget (not
a `QGraphicsView` node canvas; nothing in the codebase uses one today, and linear action
lists don't need it), following the same dock/tree-open patterns as the editor.

**Phased build-out** ends in a demoable vertical slice: a Phase-E-imported sprite moved
by arrow keys via `key_down`, colliding with a second object to change the border.

---

## Settled during layout review

- **Docking:** stock Qt docks; editor central, Project locked-left, everything else floatable
  (see Window & docking model). *(was open Q: docks vs splitter)*
- **Memory map form:** **bank-segmented columns** (one bar per slot, coloured by region, with
  PC/SP markers) — validated as genuinely useful in the mockup. Paired with a **hex memory
  cells** view for detail. *(was open Q: strip vs grid vs columns)*
- **Memory map placement:** its **own dock** on the right, under registers; the hex cells dock
  sits directly under the emulator. *(was open Q: tab vs dock)*
- **Editor:** in-app, central, multi-view/split — supersedes "external editor only".
- **Interface:** dark theme, High-DPI, Segoe UI + monospace console, adjustable UI scale.

## Open questions (to settle as we go)

1. Confirm **`(bank, offset)`** as the universal addressing convention everywhere.
2. Debugger v1 scope: ship "inspect + step" first and add breakpoints/disassembly later, or
   build the full debugger as one milestone?
3. How exactly the debug workflow is *used* day-to-day (still being explored).
4. Default proportions & which panels start visible vs. hidden in the Design/Debug presets.

---

## Appendix: original vision

> since this application is going to be "Unity" for ZX Spectrum. We need to think about UI
> and zxide project setup. I see that that in the middle will be our created previous
> zxemu_widget. on the left will project structure: source assets (imported asset?),
> sourcecode
>
> Beside this we have to have direct access to memory (since we have emulator intergrated it
> should be not so hard), memory management before compil. Literally locate assets in memory
> visaully. with drag and drop (but should have auto locate button).
>
> Imported assets could be bmp, binary, pt3 (for audio?), some asset for beeper sfx?
>
> We are going to use sjasmplus. and path to it could be taken from PATH environment.
> Default editor is VS (also should be findable via system)
>
> But can be changed to any other.
