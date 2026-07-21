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
  highlighted in the editor, and **Step Into (F11) / Step Over (F10)** — step-over runs CALLs,
  RSTs and repeating block ops (LDIR/...) to completion, honouring breakpoints hit inside.
  *Later:* disassembly panel, watchpoints.
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
  the **audio output pipeline**, built in two layers: `zxemu_core/audio.py` (`Beeper`, a
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

### 2. Tape & snapshot formats
- **TAP loading** (ROM-trap fast load + edge replay) -- closes Milestone 3.
- **TZX** -- the richer tape format (turbo loaders, custom timing).
- **More snapshots** -- `.z80`, `.szx` (load *and* save, so machine state can be saved).
- **Tape-deck UI** -- play / stop / rewind, block list, "insert tape."

### 3. Visual memory management (Phase E -- the "Unity" centerpiece)
- Bank-oriented map with **drag-drop asset placement** + an **auto-locate** button.
- **Asset import** (bmp / binary / pt3 / beeper sfx) -> generates `ORG` / `incbin`.
- Live "where do my bytes live" before *and* after the build.

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
then **Phase E** (the flashier "product" feature). The RE toolkit is where the *teaching*
happens; Phase E is where zxide feels most like "Unity for the Spectrum."

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
