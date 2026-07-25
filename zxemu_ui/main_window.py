"""MainWindow -- the zxide IDE shell.

The window is a Visual-Studio-style dock layout (see DEV_PLAN.md's "Window &
docking model"):

  * the **editor** is the central widget -- the fixed anchor everything docks
    around,
  * the **Project** tree is a locked dock on the left (can't be floated away),
  * and every other panel -- emulator, memory cells, registers, memory map,
    inspector, output -- is a floatable ``QDockWidget`` the user can drag, tab
    together, float, or hide.

The window owns no timing: an ``EmulatorController`` drives the machine and the
window merely wires its signals to the views (repaint the screen, refresh the live
debug panels, update the status bar).

The menu bar is split by *what you are doing*, not by which code implements it:

  * **File** -- projects and source files (new/open/save, recent projects),
  * **Build** -- turning *your* project into a running program (sjasmplus, then
    load the snapshot it produced), with or without breakpoints,
  * **Load** -- running *somebody else's* program, one item per format (.tap/.tzx tapes,
    .sna/.z80 snapshots),
  * **Disassembly** -- the disassembly panel and where it points,
  * **Breaks** -- conditions on breakpoints, and run-to-cursor/address,
  * **Reversing** -- understanding someone else's program: search, cross-references,
    coverage, execution trace,
  * **Watch** -- pause when a value or a port is *touched* (as against a breakpoint,
    which pauses when execution *reaches* somewhere),
  * **Compression** -- optional addons (ZX0) copied into the open project on request,
  * **Model** -- which machine is emulated (48K/128K). A project declares a target
    model and opening one switches to it, but the machine isn't owned by a project,
  * **View** -- panel visibility, interface scale, and the saved dock layout.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QDockWidget,
    QFileDialog,
    QFileSystemModel,
    QInputDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QTreeView,
    QWidget,
)

from zxemu_core.machine import Machine
from zxemu_core.memlayout import PAGED_MODELS
from zxemu_core.debug import debug_expr
from zxemu_core.assets.manifest import AssetKind
from zxemu_core.assets.native_sprite import NATIVE_SUFFIX, blank_sprite_data
from zxemu_core.assets.beeper_sfx import SUFFIX as BEEPER_SFX_SUFFIX
from zxemu_ui.workspace import builder
from zxemu_ui.controller import EmulatorController
from zxemu_ui.editor import EditorArea
from zxemu_ui.panels.emulator_panel import EmulatorPanel
from zxemu_ui.panels.emulator_view import EmulatorView
from zxemu_ui import layout_store, media, menu_builder
from zxemu_ui.debug_session import DebugSession
from zxemu_ui.panels.inspector_view import InspectorView
from zxemu_ui.panels.sprite_editor_view import SpriteEditorView
from zxemu_ui.panels.beeper_sfx_editor_view import BeeperSfxEditorView
from zxemu_ui.machine_factory import build_machine, machine_model
from zxemu_ui.panels.analysis_view import AnalysisView
from zxemu_ui.panels.call_stack_view import CallStackView
from zxemu_ui.panels.disassembly_view import DisassemblyView
from zxemu_ui.panels.disk_view import DiskView
from zxemu_ui.panels.memory_cells_view import MemoryCellsView
from zxemu_ui.panels.memory_map_view import MemoryMapView
from zxemu_ui.panels.output_console import OutputConsole
from zxemu_ui.workspace.dump_project import dump_to_project
from zxemu_ui.workspace.project import SOURCE_SUFFIXES, Project, is_text_file
from zxemu_ui.panels.registers_view import RegistersView
from zxemu_ui.workspace.search import search_project
from zxemu_ui.workspace.settings import Settings
from zxemu_ui.workspace.settings_dialog import SettingsDialog
from zxemu_ui.system_open import FILE_MANAGER_NAME, reveal
from zxemu_ui.theme import apply_ui_scale

# Interface-scale choices offered in the View menu, as multiples of the base font size.
INTERFACE_SCALE_CHOICES = (
    ("100%", 1.0), ("125%", 1.25), ("150%", 1.5), ("175%", 1.75), ("200%", 2.0),
)

# How long an inserted tape may go unread before the Output explains why (in emulated
# frames, so 50 = one second). Long enough that booting the ROM and typing LOAD "" at a
# human pace doesn't trip it.
TAPE_STALL_FRAMES = 400

# Machine models, as (menu label, model string). One list drives both the Model menu
# and the New Project prompt, so the two can't drift apart. The model strings are the
# ones stored in zxide.json and understood by machine_factory.build_machine.
MACHINE_MODEL_CHOICES = (
    ("ZX Spectrum 48K", "48k"),
    ("ZX Spectrum 128K", "128k"),
    ("Pentagon 128 (TR-DOS)", "pentagon"),
)


class MainWindow(QMainWindow):
    """The IDE window: central editor, locked Project dock, floatable everything else."""

    def __init__(self, machine: Machine, controller: EmulatorController):
        super().__init__()
        self.setWindowTitle("zxide")
        self.machine = machine
        self.controller = controller
        self.setDockNestingEnabled(True)
        self._laid_out = False  # guard so the layout is applied once, on first show
        # Saved layout lives in a plain JSON file next to the app (repo root) -- no
        # registry, so you can open/inspect/delete it.
        self._layout_path = Path(__file__).resolve().parent.parent / "layout.json"
        # App settings (auto-created with sjasmplus auto-detected on first run) and the
        # currently open project (None until one is opened/created).
        self.settings = Settings(Path(__file__).resolve().parent.parent / "settings.json")
        self.project: Project | None = None
        # Everything about why execution would pause and where we are when it does --
        # source map, breakpoints, conditions, watchpoints -- lives in one object.
        self.debug = DebugSession(controller, machine)
        self._last_search = ""   # pre-filled into Find in Project, so Ctrl+F repeats cheaply
        # Tape-stall watch (see _check_tape_progress): frames since a block was last read.
        self._tape_idle_frames = 0
        self._tape_watch_index = 0
        self._tape_stall_reported = True  # nothing inserted yet, so nothing to report
        # Deck preferences live on the window, not the machine, because switching model
        # builds a *new* machine: kept here, your choice survives the swap (see set_machine).
        self._fast_load = True
        self._tape_audible = True
        # Disks mount **write-protected by default**, and the tab on a real 3.5" disk is
        # the right analogy: you slide it open deliberately, for the one disk you meant to
        # write to. The asymmetry is what decides it -- a game refusing to save its high
        # scores is a nuisance you notice immediately, while a loader quietly scribbling
        # over a disk in an irreplaceable collection is silent and permanent. We have
        # already had one bug erase a catalogue; a default that limits the blast radius of
        # the next one is worth the occasional trip to the menu.
        self._pending_write_protect = True
        # Model-menu radio items, keyed by model string. Populated by _build_menu and
        # kept in sync by set_machine, so the tick always follows the *live* machine --
        # whether it changed from the menu or from opening a project.
        self._model_actions: dict[str, QAction] = {}

        # Give the left/right dock areas the corners, so the side columns (Project +
        # Inspector, and the emulator/registers/memory-map stack) run the full height
        # of the window. The bottom area is then confined to the centre -- the Output
        # console sits directly under the editor rather than spanning the whole width.
        for corner in (Qt.TopLeftCorner, Qt.BottomLeftCorner):
            self.setCorner(corner, Qt.LeftDockWidgetArea)
        for corner in (Qt.TopRightCorner, Qt.BottomRightCorner):
            self.setCorner(corner, Qt.RightDockWidgetArea)

        # Central anchor: the code/text editor.
        self.editor = EditorArea()
        self.setCentralWidget(self.editor)

        # Panels (each becomes a dock below).
        self.view = EmulatorView(machine)
        self.emulator_panel = EmulatorPanel(self.view, controller)
        self.memory_cells = MemoryCellsView(machine)
        self.disassembly = DisassemblyView(machine)
        self.call_stack = CallStackView(machine)
        self.analysis = AnalysisView(machine)
        self.disk = DiskView(machine)
        # The panel asks; the window acts. It owns no dialogs and knows nothing about
        # projects or where images live, so it stays a view rather than a second
        # implementation of the Disk Drive menu.
        self.disk.mount_requested.connect(self._mount_disk_dialog)
        self.disk.eject_requested.connect(self._eject_disk)
        self.disk.save_requested.connect(self._save_disk_as)
        self.disk.write_protect_changed.connect(
            lambda drive, protected: self._set_disk_write_protect(protected, drive))
        self.registers = RegistersView(machine)
        self.memory_map = MemoryMapView(machine)
        self.inspector = InspectorView()
        self.sprite_editor = SpriteEditorView()
        self.beeper_sfx_editor = BeeperSfxEditorView()
        self.output_console = OutputConsole()
        self.output_console.link_activated.connect(self._open_search_hit)

        self._build_docks()

        # Remember the built-in default arrangement (for "Reset layout"), and load any
        # saved layout from disk. It is applied later -- once the window is shown and
        # maximised (see showEvent) -- so the saved per-dock sizes land in a window of
        # the same size they were captured in.
        self._default_state = self.saveState()
        self._saved_layout = layout_store.load(self._layout_path)

        self._build_menu()
        self.statusBar().showMessage("ready")

        # Controller signals -> views. frame_ready carries the emulated-frame count,
        # which the screen uses for real-time FLASH timing and the debug panels use
        # as a cheap "something changed, refresh if visible" tick.
        self.controller.frame_ready.connect(self.view.refresh)
        self.controller.frame_ready.connect(self.registers.refresh)
        self.controller.frame_ready.connect(self.memory_cells.refresh)
        self.controller.frame_ready.connect(self.disassembly.refresh)
        self.controller.frame_ready.connect(self.call_stack.refresh)
        self.controller.frame_ready.connect(self.memory_map.refresh)
        self.controller.status_changed.connect(self.statusBar().showMessage)
        self.controller.breakpoint_hit.connect(self._on_breakpoint_hit)
        self.controller.watchpoint_hit.connect(self._on_watchpoint_hit)
        # Double-clicking an analysis result should take you to the code it names.
        self.analysis.address_activated.connect(self._disasm_goto)
        # Clicking a placed asset in the Design-mode memory map shows it in the Inspector.
        self.memory_map.asset_selected.connect(self._on_asset_selected)
        self.emulator_panel.screenshot_requested.connect(self._save_screenshot)
        self.editor.breakpoints_changed.connect(self._sync_breakpoints)
        # The execution-line marker: cleared while running, shown (and moved) whenever
        # paused -- on a breakpoint, a manual pause, or after each Step.
        self.controller.running_changed.connect(self._on_running_marker)
        self.controller.frame_ready.connect(self._on_frame_marker)
        self.controller.frame_ready.connect(self._check_tape_progress)

        self._reopen_last_project()  # reopen whatever project was last used

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override name)
        """Apply the layout once, a tick after the first show.

        Deferring lets the window reach its real (maximised) size first, so per-dock
        sizes -- whether the saved ones or the default proportions -- are placed
        correctly. splitDockWidget otherwise splits evenly, letting the compact
        Registers panel claim as much height as the emulator.
        """
        super().showEvent(event)
        if self._laid_out:
            return
        self._laid_out = True
        QTimer.singleShot(0, self._finish_layout)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override name)
        """Leave fullscreen before the IDE goes away.

        The fullscreen emulator is a top-level window of its own, so closing the IDE
        while it is up would leave it on screen -- and, since Qt quits when the *last*
        window closes, leave the application running with nothing but a Spectrum
        screen and no way back to it.
        """
        self.emulator_panel.exit_fullscreen()
        super().closeEvent(event)

    def _finish_layout(self) -> None:
        if self._saved_layout is not None:
            docks_by_name = {d.objectName(): d for d in self._all_docks}
            layout_store.apply(self, docks_by_name, self._saved_layout)
        else:
            self._apply_default_sizes()

    # --- small shared gestures -------------------------------------------------

    def _refresh_all_panels(self) -> None:
        """Repaint every live view from the machine's current state.

        For the moments when everything changed at once and no signal covers it: a
        snapshot was loaded, the machine was swapped, a watchpoint fired. ``force=True``
        on the heavier panels bypasses their "has anything moved?" caching, which is what
        makes them cheap during normal running but stale after a wholesale state change.
        """
        self.view.refresh()
        self.registers.refresh()
        self.memory_cells.refresh(force=True)
        self.disassembly.refresh(force=True)
        self.call_stack.refresh(force=True)
        self.memory_map.refresh()
        self.disk.refresh()

    @staticmethod
    def _reveal_dock(dock) -> None:
        """Bring a dock to the front: show it, and raise it above whatever it's tabbed with.

        ``show()`` alone is not enough for a tabbed dock -- it would stay behind its
        sibling, so the panel you just asked for appears to do nothing.
        """
        dock.show()
        dock.raise_()

    def _apply_default_sizes(self) -> None:
        h = self.height()
        # Right column: give the emulator the lion's share; keep registers compact,
        # sitting just above the memory map.
        self.resizeDocks(
            [self._emulator_dock, self._registers_dock, self._memmap_dock],
            [int(h * 0.55), int(h * 0.15), int(h * 0.30)],
            Qt.Vertical,
        )
        # Left column: project tree gets more room than the inspector.
        self.resizeDocks(
            [self._project_dock, self._inspector_dock],
            [int(h * 0.62), int(h * 0.38)],
            Qt.Vertical,
        )

    # --- construction helpers -------------------------------------------------

    def _make_project_tree(self) -> QTreeView:
        """A live view of the open project's folder on disk (empty until one opens)."""
        self._fs_model = QFileSystemModel()
        tree = QTreeView()
        tree.setModel(self._fs_model)
        tree.setHeaderHidden(True)
        for column in (1, 2, 3):  # hide size / type / date -- just show names
            tree.hideColumn(column)
        tree.setRootIndex(self._fs_model.index(""))  # nothing shown until a project opens
        tree.doubleClicked.connect(self._open_tree_index)
        tree.setContextMenuPolicy(Qt.CustomContextMenu)
        tree.customContextMenuRequested.connect(self._show_tree_menu)
        # Lets a file be dragged onto the Design-mode memory map to import it as an asset.
        tree.setDragEnabled(True)
        tree.selectionModel().currentChanged.connect(self._on_tree_selection_changed)
        self.project_tree = tree
        return tree

    def _on_tree_selection_changed(self, current, _previous) -> None:
        """Selecting a file that matches an asset's source shows it in the Inspector."""
        if self.project is None:
            return
        path = self._fs_model.filePath(current)
        if not path:
            return
        self.inspector.show_path(self.project, self.project.relative(path) or path)

    def _on_asset_selected(self, asset_id: str) -> None:
        """A placed asset was clicked in the Design-mode memory map."""
        if self.project is not None:
            self.inspector.show_asset_id(self.project, asset_id)

    # --- project ---------------------------------------------------------------

    def _open_project(self, folder) -> None:
        """Point the tree at a project folder and remember it as the last opened."""
        folder = Path(folder)
        self.project = Project(folder)
        self._fs_model.setRootPath(str(folder))
        self.project_tree.setRootIndex(self._fs_model.index(str(folder)))
        self.memory_map.set_project(self.project)
        self.setWindowTitle(f"zxide — {self.project.name}")
        self.settings.set("last_project", str(folder))
        self.settings.push_recent("recent_projects", str(folder))
        self._log(f"Opened project: {folder}")
        # Boot the machine the project targets; swap only if it differs from the current one.
        model = self.project.model
        if model != machine_model(self.machine):
            self.set_machine(build_machine(model))
            self._log(f"Switched to the {model.upper()} machine for this project.")

    def set_machine(self, machine) -> None:
        """Swap the emulated machine (48K <-> 128K) and re-point every view at it.

        The frame_ready -> refresh signal bindings target the view objects, not the
        machine, so they survive untouched; we only rebind each view's ``.machine``
        and hand the new machine to the controller, then repaint from its state.
        """
        self.machine = machine
        self.view.machine = machine
        self.memory_cells.machine = machine
        self.disassembly.machine = machine
        self.call_stack.machine = machine
        self.analysis.machine = machine
        self.registers.machine = machine
        self.memory_map.machine = machine
        self.disk.set_machine(machine)
        self.debug.machine = machine  # conditions are validated against the live machine
        # A fresh machine comes with the defaults, not with your deck settings; re-apply
        # them, or turning Fast Load off and then switching model silently turns it back on.
        machine.fast_load_enabled = self._fast_load
        machine.tape_audible = self._tape_audible
        self.controller.set_machine(machine)
        # Keep the Model menu's tick on the machine that's actually running, however the
        # switch was triggered (menu, or opening a project that targets the other model).
        action = self._model_actions.get(machine_model(machine))
        if action is not None:
            action.setChecked(True)
        # Boot it. A freshly built machine has never run an instruction, so if the
        # emulator was paused -- at a breakpoint, or by the Pause button -- switching
        # model would hand you a black screen and a dead keyboard that looks like the new
        # model is broken. Swapping the machine is a power-cycle by any reasonable
        # reading, so it behaves like one.
        self.controller.reset()
        self.controller.set_running(True)
        self._refresh_all_panels()

    def _new_project(self) -> None:
        # Model first: it decides which starter template is scaffolded into the folder,
        # so asking for it up front means the folder picker is the last thing standing
        # between you and a created project -- and cancelling costs you nothing.
        labels = [label for label, _model in MACHINE_MODEL_CHOICES]
        model_label, ok = QInputDialog.getItem(
            self, "New Project", "Target machine:", labels, 0, False
        )
        if not ok:
            return
        model = dict((label, m) for label, m in MACHINE_MODEL_CHOICES)[model_label]
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder for the new project")
        if not folder:
            return
        name, ok = QInputDialog.getText(self, "New Project", "Project name:", text=Path(folder).name)
        if not ok or not name.strip():
            return
        project = Project.create(folder, name.strip(), model)
        self._open_project(folder)
        main = project.folder / project.load_manifest().get("main", "main.asm")
        if main.exists():
            self.editor.open_file(str(main))

    def _open_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Open Folder")
        if folder:
            self._open_project(folder)

    def _open_tree_index(self, index) -> None:
        """Double-click a file: sprites/SFX open in their own editor; other text files in the code editor."""
        path = self._fs_model.filePath(index)
        if not path or not Path(path).is_file():
            return
        if path.lower().endswith(NATIVE_SUFFIX) and self._open_sprite_editor_for_path(path):
            return
        if path.lower().endswith(BEEPER_SFX_SUFFIX) and self._open_beeper_sfx_editor_for_path(path):
            return
        if is_text_file(path):
            self.editor.open_file(path)

    def _open_sprite_editor_for_path(self, path: str) -> bool:
        """Show ``path`` in the Sprite Editor if it's a registered asset. False if not (caller falls back)."""
        if self.project is None:
            return False
        source = self.project.relative(path)
        entry = next((e for e in self.project.assets() if e.source == source), None)
        if entry is None:
            return False
        self.sprite_editor.show_asset(self.project, entry)
        self._reveal_dock(self._sprite_editor_dock)
        return True

    def _open_beeper_sfx_editor_for_path(self, path: str) -> bool:
        """Show ``path`` in the Beeper SFX Editor if it's a registered asset. False if not (caller falls back)."""
        if self.project is None:
            return False
        source = self.project.relative(path)
        entry = next((e for e in self.project.assets() if e.source == source), None)
        if entry is None:
            return False
        self.beeper_sfx_editor.show_asset(self.project, entry)
        self._reveal_dock(self._beeper_sfx_editor_dock)
        return True

    def _show_tree_menu(self, pos) -> None:
        if self.project is None:
            return
        menu = QMenu(self)
        menu.addAction("New File…", self._new_file)
        menu.addAction("New Folder…", self._new_folder)
        menu.addAction("New Sprite Asset…", self._new_sprite_asset)
        menu.addAction("New Beeper SFX Asset…", self._new_beeper_sfx_asset)
        menu.addSeparator()
        menu.addAction("Import Animation Sequence…", self._import_animation_sequence)
        menu.addSeparator()
        menu.addAction(f"Show in {FILE_MANAGER_NAME}", self._reveal_in_file_manager)
        menu.exec_(self.project_tree.viewport().mapToGlobal(pos))

    def _new_sprite_asset(self) -> None:
        """A blank sprite drawn in zxide's own editor, not imported from a file."""
        if self.project is None:
            return
        size_label, ok = QInputDialog.getItem(
            self, "New Sprite Asset", "Size:", ["8x8", "16x16", "Custom"], 0, False
        )
        if not ok:
            return
        if size_label == "Custom":
            width, ok = QInputDialog.getInt(self, "New Sprite Asset", "Width (multiple of 8):", 8, 8, 256, 8)
            if not ok:
                return
            height, ok = QInputDialog.getInt(self, "New Sprite Asset", "Height (multiple of 8):", 8, 8, 256, 8)
            if not ok:
                return
        else:
            width, height = (8, 8) if size_label == "8x8" else (16, 16)
        frame_count, ok = QInputDialog.getInt(self, "New Sprite Asset", "Frame count:", 1, 1, 64, 1)
        if not ok:
            return
        name, ok = QInputDialog.getText(self, "New Sprite Asset", "Name:", text="sprite")
        if not ok or not name.strip():
            return

        symbol = name.strip()
        path = self._target_dir() / f"{symbol}{NATIVE_SUFFIX}"
        path.write_text(json.dumps(blank_sprite_data(width, height, frame_count), indent=2), encoding="utf-8")
        entry = self.project.add_asset(self.project.relative(path), AssetKind.SPRITE_SHEET, symbol=symbol)

        self.sprite_editor.show_asset(self.project, entry)
        self._reveal_dock(self._sprite_editor_dock)
        self.memory_map.refresh()

    def _new_beeper_sfx_asset(self) -> None:
        """A blank beeper sound effect built in zxide's own editor, not hand-typed."""
        if self.project is None:
            return
        name, ok = QInputDialog.getText(self, "New Beeper SFX Asset", "Name:", text="sfx")
        if not ok or not name.strip():
            return

        symbol = name.strip()
        path = self._target_dir() / f"{symbol}{BEEPER_SFX_SUFFIX}"
        path.write_text("", encoding="utf-8")  # empty -- add tones/rests in the editor
        entry = self.project.add_asset(self.project.relative(path), AssetKind.BEEPER_SFX, symbol=symbol)

        self.beeper_sfx_editor.show_asset(self.project, entry)
        self._reveal_dock(self._beeper_sfx_editor_dock)
        self.memory_map.refresh()

    def _import_animation_sequence(self) -> None:
        """A sprite_sequence asset: several individually-drawn frame images, one file each.

        Unlike a single dropped file (handled by the memory map's own drag-drop), this
        has no single filename to derive a symbol from, so it asks for one up front.
        """
        paths, _filter = QFileDialog.getOpenFileNames(
            self, "Import Animation Sequence", str(self._target_dir()), "Bitmap images (*.bmp)"
        )
        if not paths:
            return
        symbol, ok = QInputDialog.getText(self, "Import Animation Sequence", "Symbol name:")
        if not ok or not symbol.strip():
            return
        sources = [self.project.relative(path) or path for path in paths]
        self.project.add_asset(sources, AssetKind.SPRITE_SEQUENCE, symbol=symbol.strip())
        self.memory_map.refresh()

    def _target_dir(self) -> Path:
        """Where a new file/folder goes: the selected folder (or a file's parent)."""
        index = self.project_tree.currentIndex()
        if index.isValid():
            path = Path(self._fs_model.filePath(index))
            return path if path.is_dir() else path.parent
        return self.project.folder

    def _new_file(self) -> None:
        name, ok = QInputDialog.getText(self, "New File", "File name:", text="new.asm")
        if not ok or not name.strip():
            return
        path = self._target_dir() / name.strip()
        if not path.exists():
            path.write_text("", encoding="utf-8")
        if is_text_file(path):
            self.editor.open_file(str(path))

    def _new_folder(self) -> None:
        name, ok = QInputDialog.getText(self, "New Folder", "Folder name:")
        if not ok or not name.strip():
            return
        (self._target_dir() / name.strip()).mkdir(exist_ok=True)

    # --- build & run -----------------------------------------------------------

    def _build_and_debug(self) -> None:
        self._build_and_launch(debug=True)

    def _build_and_run(self) -> None:
        self._build_and_launch(debug=False)

    def _build_and_launch(self, debug: bool) -> None:
        """Assemble the project, load the snapshot, and run it.

        With debug=True (F5) breakpoints are active; with debug=False (Ctrl+F5) it
        runs straight through, ignoring them.
        """
        if self.project is None:
            self._log("No project open — use File ▸ New Project or Open Folder first.")
            return
        self._log(f"── {'Build & Debug' if debug else 'Build & Run'} ──")
        self.editor.save_all()  # you can't assemble a tab, only a file on disk
        main = self._compile_target()
        if main is not None:
            self._log(f"Assembling {main}")
        result = builder.build(self.project, self.settings, main)
        self._log("$ " + " ".join(result.command))
        if result.output.strip():
            self._log(result.output.rstrip())
        if result.returncode != 0:
            self._log(f"Build failed (exit code {result.returncode}).")
            return
        if result.snapshot is None:
            self._log("Build succeeded, but no snapshot was produced.")
            return
        self.debug.debugging = debug
        self._load_source_map(result.sld)  # source lines <-> addresses
        self._sync_breakpoints()            # applied only when debugging
        if self._load_snapshot(result.snapshot):
            self.controller.set_running(True)

    def _compile_target(self) -> str | None:
        """Which source F5 assembles: the one you have open, as a project-relative path.

        The build entry point follows the editor rather than a manifest field, because
        the manifest can only ever guess -- a folder zxide didn't scaffold calls its
        entry point whatever it calls it (``fallout.asm``), and a project can hold
        several buildable sources with no single "main" among them.

        Returns None -- letting the builder fall back to the manifest -- when the focused
        tab is not something assembleable: the welcome tab, a non-source text file like
        ``zxide.json``, an ``.inc`` meant to be included by something else, or a file
        outside the project folder.
        """
        path = self.editor.current_path()
        if path is None:
            return None
        path = Path(path)
        if path.suffix.lower() not in SOURCE_SUFFIXES:
            return None
        try:
            return self.project.relative(path)
        except ValueError:
            return None

    def _load_source_map(self, sld_path) -> None:
        """Hand the build's SLD to the debug session, and its labels to the disassembly."""
        if self.project is None:
            return
        self.debug.load_source_map(sld_path, self.project.folder)
        # The panel shows your own label names for addresses, so it needs the map too.
        self.disassembly.source_map = self.debug.source_map

    def _sync_breakpoints(self) -> None:
        """Push the editor's gutter breakpoints through to the running machine."""
        self.debug.sync_breakpoints(self.editor.all_breakpoints())

    def _on_breakpoint_hit(self, address: int) -> None:
        """Execution paused on a breakpoint: log it and refresh the debug panels.

        The editor's execution-line highlight follows from the pause itself
        (see _on_running_marker), so it lands on the right line automatically.
        """
        self._log(f"Breakpoint hit at ${address:04X}")

    def _on_watchpoint_hit(self, description: str) -> None:
        """Execution paused on a watchpoint: report what was touched, and by roughly what.

        "Roughly": PC has already moved past the instruction that did it by the time we
        look, so the reported address is where execution *is*, not the exact opcode.
        Open the disassembly to see the instruction just above it.
        """
        self._log(f"Watchpoint: {description}")
        self._refresh_all_panels()

    def _on_running_marker(self, running: bool) -> None:
        if running:
            self.editor.clear_execution_line()  # no marker while free-running
        else:
            self._refresh_execution_marker()

    def _on_frame_marker(self, _frames: int) -> None:
        if not self.controller.running:  # after a Step (or Frame) while paused
            self._refresh_execution_marker()

    def _refresh_execution_marker(self) -> None:
        """Point the editor's execution highlight at the current PC's source line."""
        location = self.debug.location_of(self.machine.cpu.regs.pc)
        if location is not None:
            self.editor.set_execution_line(*location)
        else:
            self.editor.clear_execution_line()  # PC is in code we have no source for

    def _load_format_dialog(self, fmt) -> None:
        """Pick a file of one specific format (see ``media.FORMATS``) and load it.

        One menu item per format, so the item names what it opens and the dialog lists
        one format's files rather than a mixed bag -- ``.tap`` and ``.tzx`` are both
        tapes but behave differently enough to be worth choosing between deliberately.
        """
        path, _ = QFileDialog.getOpenFileName(
            self, f"Load {fmt.label}", self._media_dir(), fmt.file_filter
        )
        if path:
            self._load_media(path)

    def _media_dir(self) -> str:
        """Where a Load dialog should open: wherever you last loaded something from.

        Shared by every format deliberately. Tapes, disks and snapshots live together in
        a collection folder and almost never inside the project you have open, so
        starting at the project -- the old behaviour -- meant navigating the same long
        path again for each one. One folder rather than one per format, because a .tzx
        and a .trd from the same collection sit side by side.

        Falls back to the project, then to the dialog's own default, and forgets a folder
        that has since been deleted rather than opening somewhere arbitrary.
        """
        remembered = self.settings.get("last_media_dir", "")
        if remembered and Path(remembered).is_dir():
            return remembered
        return str(self.project.folder) if self.project else ""

    def _remember_media_dir(self, path) -> None:
        """Record the folder a media file came from, for the next Load dialog."""
        folder = Path(path).parent
        if folder.is_dir():
            self.settings.set("last_media_dir", str(folder))

    def _load_media(self, path) -> bool:
        """Load a user-chosen media file (snapshot/tape) and record it in Load Recent.

        Dispatches on the file extension so tape support slots in later without
        touching the menu wiring. A file that has since been deleted is dropped from
        the recent list rather than left to fail again.
        """
        path = Path(path)
        if not path.exists():
            self._log(f"File no longer exists: {path}")
            self.settings.remove_recent("recent_files", str(path))
            return False
        kind = media.kind_of(path)
        if kind == media.SNAPSHOT:
            ok = self._load_snapshot(path)
        elif kind == media.TAPE:
            ok = self._load_tape(path)
        elif kind == media.DISK:
            ok = self._load_disk(path)
        else:
            self._log(f"Don't know how to load {path.name}.")
            ok = False
        if ok:
            self.settings.push_recent("recent_files", str(path))
            # Recorded here rather than in the dialog, so it also follows Load Recent and
            # anything else that loads by path -- the useful folder is the one you last
            # actually loaded from, however you got there.
            self._remember_media_dir(path)
        return ok

    def _load_snapshot(self, path) -> bool:
        """Load a .sna or .z80 into the machine, resume it, and refresh the views."""
        path = Path(path)
        try:
            media.load_snapshot(self.machine, path)
        except (ValueError, NotImplementedError, OSError) as error:
            self._log(f"Could not load {path.name}: {error}")
            return False
        # Resume. A snapshot *is* a running machine, so loading one into a paused
        # emulator -- paused by the Pause button, or by a breakpoint from an earlier
        # Build & Debug -- and leaving it paused looks exactly like a broken load: the
        # screen shows the game (the panels repainted) but nothing moves and the
        # keyboard does nothing. The tape path has always resumed; this one only said
        # it did.
        self.controller.set_running(True)
        self._refresh_all_panels()
        self._focus_emulator()
        self._log(f"Loaded {path.name} — running.")
        return True

    def _focus_emulator(self) -> None:
        """Send the keyboard to the emulator, once the file dialog has finished closing.

        Deferred rather than immediate: the modal file dialog restores focus to whatever
        held it before, and on Windows that happens as its native window is destroyed --
        potentially *after* this handler returns, undoing a plain ``setFocus()`` and
        leaving your keystrokes going to the editor instead of the Spectrum.
        """
        QTimer.singleShot(0, self.view.setFocus)

    def _load_tape(self, path) -> bool:
        """Insert a .tap or .tzx into the deck and reset, ready for the ROM to LOAD it.

        Unlike a snapshot (which *is* a running state), a tape has to be loaded by the
        machine itself. We reset to a clean ROM prompt, insert the tape, and -- with
        fast load on -- the LD-BYTES trap delivers each block instantly the moment the
        ROM asks for it. The dev just kicks it off with the usual LOAD command.
        """
        path = Path(path)
        try:
            blocks, notes = media.read_tape(path)
        except (ValueError, OSError) as error:
            self._log(f"Could not load {path.name}: {error}")
            return False

        self.controller.reset()             # clean power-on state before inserting
        self.machine.insert_tape(media.make_deck(blocks))
        self.controller.set_running(True)
        self.view.refresh()
        self._focus_emulator()
        for line in media.tape_summary(path.name, blocks, notes, machine_model(self.machine)):
            self._log(line)
        # Start watching for a tape that never gets read -- see _check_tape_progress.
        self._tape_idle_frames = 0
        self._tape_watch_index = 0
        self._tape_stall_reported = False
        return True

    def _dump_to_project(self) -> None:
        """Turn the running program's RAM into a project you can build and step through.

        The two caveats are put in front of you *before* the dump rather than in a README
        afterwards, because both change what you would do next: a region with no coverage
        is emitted as data even if it is really code you simply have not run yet, and only
        what is *resident* is captured — a game that streams levels from disk has just the
        part that was loaded at this instant.
        """
        coverage = self.controller.coverage
        executed = coverage.count() if coverage.enabled else 0
        if not executed:
            # The dependency between recording and dumping is the one thing about this
            # feature people get wrong, and the cost is silent: you get a correct dump in
            # which nothing is disassembled. So it is asked here rather than left to be
            # discovered from the result.
            reply = QMessageBox.question(
                self, "Dump to Project",
                "Nothing has been recorded yet, so everything would be dumped as data "
                "rather than disassembled.\n\n"
                "Start recording now? Then exercise the program — play the menu, run the "
                "level you care about — and dump again.\n\n"
                "Yes: start recording.   No: dump anyway, all data.",
            )
            if reply == QMessageBox.Yes:
                self._set_coverage(True)
                for action in self.menuBar().findChildren(QAction):
                    if action.text() == "1. Record What Runs":
                        action.setChecked(True)
                return
        folder = QFileDialog.getExistingDirectory(self, "Dump to a new project folder",
                                                  self._media_dir())
        if not folder:
            return
        if any(Path(folder).iterdir()):
            reply = QMessageBox.question(
                self, "Dump to Project",
                f"{folder} is not empty. Files with the same names will be overwritten.\n\n"
                "Continue?",
            )
            if reply != QMessageBox.Yes:
                return

        model = machine_model(self.machine)
        try:
            project = dump_to_project(
                self.machine, folder, model=model,
                coverage_executed=coverage.executed if coverage.enabled else None,
                coverage=coverage if coverage.enabled else None,
                start_address=self.machine.cpu.regs.pc,
            )
        except (OSError, ValueError) as error:
            self._log(f"Could not dump: {error}")
            return

        self._log(f"Dumped {model.upper()} RAM to {folder}.")
        if executed:
            self._log(f"  {executed} address(es) executed — those became disassembly; "
                      "everything else is data.")
        else:
            self._log("  No coverage was recorded, so everything is data. Turn on "
                      "Reversing ▸ Record Coverage, exercise the program, and dump again "
                      "to get disassembly.")
        self._log("  Only what was resident is here: a program that loads more from disk "
                  "or tape later has just the part that was in memory.")
        if model in PAGED_MODELS:
            self._log("  All eight RAM banks were captured, including any paged out. A bank "
                      "is disassembled where the CPU was seen to run with it mapped in, and "
                      "kept as data otherwise.")
        reply = QMessageBox.question(self, "Dump to Project",
                                     "Open the dumped project now?")
        if reply == QMessageBox.Yes:
            self._open_project(str(project.folder))

    # --- the disk drives --------------------------------------------------------

    def _load_disk(self, path, drive: int = 0) -> bool:
        """Mount a .trd/.scl in a drive, switching to a machine that has drives at all.

        A disk image is meaningless on a 48K or a Sinclair 128: neither has a disk
        interface, so there is nowhere to put it. Rather than refuse, we switch to the
        Pentagon -- clicking "Load TRD" is an unambiguous statement of intent, and the
        alternative is an error message telling you to go and do the obvious thing
        yourself. It is logged, because a silent machine swap would be worse.
        """
        path = Path(path)
        try:
            image = media.read_disk(path)
        except (ValueError, OSError) as error:
            self._log(f"Could not load {path.name}: {error}")
            return False

        if getattr(self.machine, "beta", None) is None:
            self._log("This machine has no disk interface — switching to Pentagon 128.")
            self._switch_model("pentagon")

        image.write_protected = self._pending_write_protect
        self.machine.beta_drives[drive] = image
        self.controller.set_running(True)
        self.disk.refresh()
        self._reveal_dock(self._disk_dock)   # you just mounted a disk; show what is on it
        self.view.refresh()
        self._focus_emulator()
        for line in media.disk_summary(path.name, image, "AB"[drive] if drive < 2 else str(drive)):
            self._log(line)
        return True

    def _disk_image(self, drive: int = 0):
        """The image in a drive, or None (with an explanatory log line)."""
        drives = getattr(self.machine, "beta_drives", None)
        if not drives or drives[drive] is None:
            self._log("No disk in the drive.")
            return None
        return drives[drive]

    def _eject_disk(self, drive: int = 0) -> None:
        image = self._disk_image(drive)
        if image is None:
            return
        if image.dirty:
            # Ejecting a written-to disk is how you lose a game's save file, so it asks.
            reply = QMessageBox.question(
                self, "Eject disk",
                f"{image.name or 'This disk'} has unsaved changes. Eject anyway?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            )
            if reply == QMessageBox.Cancel:
                return
            if reply == QMessageBox.Save and not self._save_disk_as(drive):
                return
        self.machine.beta_drives[drive] = None
        self._log("Disk ejected.")

    def _mount_disk_dialog(self, drive: int) -> None:
        """Pick a disk image for a specific drive (drive A is Load TRD/SCL's own target)."""
        path, _ = QFileDialog.getOpenFileName(
            self, f"Mount in drive {'AB'[drive]}", self._media_dir(),
            "TR-DOS disk image (*.trd *.scl)",
        )
        if path:
            self._load_disk(path, drive)

    def _set_disk_write_protect(self, protected: bool, drive: int = 0) -> None:
        """Checkable menu item, so the handler takes the new state rather than toggling.

        Toggling would drift out of step with the tick the moment anything else changed
        the flag -- and the tick is the only thing telling you which way round it is.
        """
        drives = getattr(self.machine, "beta_drives", None)
        if not drives or drives[drive] is None:
            if protected:
                self._log("No disk in the drive — write protection will apply once one is in.")
            self._pending_write_protect = protected
            return
        drives[drive].write_protected = protected
        self._log("Disk is now write-protected." if protected else "Disk is now writable.")

    def _save_disk_as(self, drive: int = 0) -> bool:
        """Write the mounted image back out as a .trd.

        Always .trd, never .scl, even if that is what was loaded: an SCL cannot express
        free space or a disk label, both of which exist by the time the machine has
        written anything, so saving back to one would quietly throw work away.
        """
        image = self._disk_image(drive)
        if image is None:
            return False
        start = self._media_dir()
        suggested = Path(image.name or "disk").with_suffix(".trd").name
        path, _ = QFileDialog.getSaveFileName(
            self, "Save disk image", str(Path(start) / suggested) if start else suggested,
            "TR-DOS disk image (*.trd)",
        )
        if not path:
            return False
        try:
            Path(path).write_bytes(image.to_bytes(pad=True))
        except OSError as error:
            self._log(f"Could not save {path}: {error}")
            return False
        image.dirty = False
        image.name = Path(path).name
        self._remember_media_dir(path)   # saving somewhere is just as good a hint as loading
        self._log(f"Saved disk to {path}.")
        return True

    # --- the tape deck ----------------------------------------------------------

    def _set_fast_load(self, enabled: bool) -> None:
        """Choose between the two loaders (see zxemu_core/storage/tape.py and pulse.py).

        On, the ROM's loader is intercepted and each block appears instantly. Off, the
        machine loads the way it did in 1985: by listening to pulses on port 0xFE, in
        real time, with the loading stripes and the noise. Either way a game's *own*
        turbo loader is served by the pulses, because it never calls the ROM at all.
        """
        self._fast_load = enabled
        self.machine.fast_load_enabled = enabled
        self._log("Fast tape load on — blocks load instantly." if enabled else
                  "Fast tape load off — tapes now load at real speed, from real pulses.")

    def _set_tape_audible(self, enabled: bool) -> None:
        self._tape_audible = enabled
        self.machine.tape_audible = enabled

    def _tape_player(self):
        """The edge player for the inserted tape, or None (with a note) if there isn't one."""
        player = self.machine.tape_player
        if player is None:
            self._log("No tape in the deck.")
        return player

    def _tape_play(self) -> None:
        """Start the motor now, rather than waiting to be read.

        Normally the player works its own motor: it starts when it can see the machine
        sampling the tape and stops at the pause after each block. Play just brings that
        forward, and re-arms the automatic behaviour if Stop had disarmed it.
        """
        player = self._tape_player()
        if player is not None:
            player.auto = True
            player.start()
            self._log("Tape playing.")

    def _tape_stop(self) -> None:
        """Stop the motor and leave it stopped.

        This also turns the automatic motor off, which it has to: the machine may still
        be polling port 0xFE, and the player would read that as "they're listening" and
        start the tape again within the frame. Play arms it again.
        """
        player = self._tape_player()
        if player is not None:
            player.auto = False
            player.stop()
            self._log("Tape stopped.")

    def _tape_rewind(self) -> None:
        player = self._tape_player()
        if player is not None:
            player.rewind()
            player.auto = True
            self._tape_watch_index = 0
            self._tape_idle_frames = 0
            self._log("Tape rewound to the first block.")

    def _eject_tape(self) -> None:
        if self.machine.tape is None:
            self._log("No tape in the deck.")
            return
        self.machine.eject_tape()
        self._tape_stall_reported = True  # nothing inserted: nothing to report on
        self._log("Tape ejected.")

    def _check_tape_progress(self, _frames: int) -> None:
        """Say something when an inserted tape stops being read.

        A stalled tape looks identical whichever way it happened -- the border sits there,
        often flashing red, and nothing loads -- but the causes need opposite actions from
        you, so guessing is worse than asking. Either the machine is waiting for you to
        start the load, or the game has its own turbo loader, which no ROM trap can feed
        and which therefore wants Fast Load turned *off* so it gets real pulses instead
        (see zxemu_core/storage/pulse.py). Reported once per tape, not per frame.
        """
        deck = self.machine.tape
        if deck is None or deck.at_end or self._tape_stall_reported:
            return
        if deck.index != self._tape_watch_index:
            self._tape_watch_index = deck.index   # progress: reset the clock
            self._tape_idle_frames = 0
            return
        self._tape_idle_frames += 1
        if self._tape_idle_frames < TAPE_STALL_FRAMES:
            return
        self._tape_stall_reported = True
        blocks_read = deck.index
        self._log(f"No tape block has been read for {TAPE_STALL_FRAMES // 50}s "
                  f"({blocks_read} of {len(deck.blocks)} loaded).")
        if blocks_read == 0:
            self._log('  The machine is waiting for you to start it — type LOAD "" ⏎ '
                      "(or pick Tape Loader from the 128K menu).")
        elif self.machine.fast_load_enabled:
            self._log("  If the loading screen is showing and the border is flashing, this "
                      "game has its own turbo loader: it reads the tape without the ROM, so "
                      "fast load can't feed it. Turn off Load ▸ Tape Deck ▸ Fast Load and "
                      "reload the tape — it will then load from real pulses, at real speed.")
        else:
            self._log("  Loading from real pulses can take a minute or two per block — if "
                      "the border is striped, it is working. If it is not, the tape may "
                      "need rewinding (Load ▸ Tape Deck ▸ Rewind).")

    # --- recent projects / files -----------------------------------------------

    def _populate_open_recent(self) -> None:
        self._fill_recent_menu(
            self._open_recent_menu, "recent_projects", self._open_recent_project, "No recent projects"
        )

    def _populate_load_recent(self) -> None:
        self._fill_recent_menu(
            self._load_recent_menu, "recent_files", self._load_media, "No recent files"
        )

    def _fill_recent_menu(self, menu, key: str, handler, empty_label: str) -> None:
        """Rebuild a recent submenu from settings: numbered entries + a Clear action."""
        menu.clear()
        paths = self.settings.get(key, [])
        if not paths:
            disabled = menu.addAction(f"({empty_label})")
            disabled.setEnabled(False)
            return
        for index, path in enumerate(paths, start=1):
            prefix = f"&{index}  " if index <= 9 else ""
            action = menu.addAction(prefix + self._recent_label(path))
            action.setToolTip(path)
            action.triggered.connect(lambda _checked=False, p=path: handler(p))
        menu.addSeparator()
        clear = menu.addAction("Clear")
        clear.triggered.connect(lambda _checked=False, k=key: self.settings.set(k, []))

    @staticmethod
    def _recent_label(path: str) -> str:
        """A compact menu label: the item's name plus its parent folder for context."""
        p = Path(path)
        parent = p.parent.name
        return f"{p.name}  ({parent})" if parent else p.name

    def _open_recent_project(self, folder) -> None:
        """Open a project from the recent list, pruning it if the folder is gone."""
        if Path(folder).is_dir():
            self._open_project(folder)
        else:
            self._log(f"Project folder no longer exists: {folder}")
            self.settings.remove_recent("recent_projects", str(folder))

    def _open_settings(self) -> None:
        SettingsDialog(self.settings, self.project, self).exec_()

    def _reopen_last_project(self) -> None:
        last = self.settings.get("last_project", "")
        if last and Path(last).is_dir():
            self._open_project(last)

    def _make_dock(self, title: str, widget: QWidget, object_name: str, *, locked: bool = False) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(object_name)  # required for saveState/restoreState
        dock.setWidget(widget)
        if locked:
            # Movable within its area and hideable, but not floatable -- stays put.
            dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetClosable)
        return dock

    def _build_docks(self) -> None:
        # Left column: Project (locked) with the Inspector beneath it.
        self._project_dock = self._make_dock("Project", self._make_project_tree(), "projectDock", locked=True)
        self.addDockWidget(Qt.LeftDockWidgetArea, self._project_dock)
        self._inspector_dock = self._make_dock("Inspector", self.inspector, "inspectorDock")
        self.splitDockWidget(self._project_dock, self._inspector_dock, Qt.Vertical)

        # Right column, top-to-bottom: emulator, registers, memory map.
        self._emulator_dock = self._make_dock("Emulator", self.emulator_panel, "emulatorDock")
        self.addDockWidget(Qt.RightDockWidgetArea, self._emulator_dock)
        self._registers_dock = self._make_dock("Registers", self.registers, "registersDock")
        self.splitDockWidget(self._emulator_dock, self._registers_dock, Qt.Vertical)
        self._memmap_dock = self._make_dock("Memory map", self.memory_map, "memmapDock")
        self.splitDockWidget(self._registers_dock, self._memmap_dock, Qt.Vertical)

        # The Memory (hex) panel is tall and would squeeze the emulator, so it starts
        # detached (a floating window) and hidden -- give the machine column its room.
        # Toggle it on from the View menu when you want to pore over bytes.
        self._memory_dock = self._make_dock("Memory", self.memory_cells, "memoryDock")
        self.addDockWidget(Qt.RightDockWidgetArea, self._memory_dock)
        self._memory_dock.setFloating(True)
        self._memory_dock.resize(560, 380)
        self._memory_dock.hide()

        # Disassembly starts floating and hidden for the same reason as Memory: it wants
        # height the machine column can't spare. Open it from the Disassembly menu.
        self._disasm_dock = self._make_dock("Disassembly", self.disassembly, "disasmDock")
        self.addDockWidget(Qt.RightDockWidgetArea, self._disasm_dock)
        self._disasm_dock.setFloating(True)
        self._disasm_dock.resize(520, 460)
        self._disasm_dock.hide()

        self._callstack_dock = self._make_dock("Call stack", self.call_stack, "callStackDock")
        self.addDockWidget(Qt.RightDockWidgetArea, self._callstack_dock)
        self._callstack_dock.setFloating(True)
        self._callstack_dock.resize(420, 260)
        self._callstack_dock.hide()

        self._analysis_dock = self._make_dock("Analysis", self.analysis, "analysisDock")
        self.addDockWidget(Qt.RightDockWidgetArea, self._analysis_dock)
        self._analysis_dock.setFloating(True)
        self._analysis_dock.resize(520, 400)
        self._analysis_dock.hide()

        # Sprite Editor: opened on demand (New Sprite Asset, or opening a .zxspr.json),
        # so it starts floating and hidden like the other on-demand tools above.
        self._sprite_editor_dock = self._make_dock("Sprite Editor", self.sprite_editor, "spriteEditorDock")
        self.addDockWidget(Qt.RightDockWidgetArea, self._sprite_editor_dock)
        self._sprite_editor_dock.setFloating(True)
        self._sprite_editor_dock.resize(420, 520)
        self._sprite_editor_dock.hide()

        # Beeper SFX Editor: same on-demand pattern as the Sprite Editor above.
        self._beeper_sfx_editor_dock = self._make_dock(
            "Beeper SFX Editor", self.beeper_sfx_editor, "beeperSfxEditorDock"
        )
        self.addDockWidget(Qt.RightDockWidgetArea, self._beeper_sfx_editor_dock)
        self._beeper_sfx_editor_dock.setFloating(True)
        self._beeper_sfx_editor_dock.resize(420, 360)
        self._beeper_sfx_editor_dock.hide()

        # Disk drives: on-demand like the other tools, since only a Pentagon has any.
        self._disk_dock = self._make_dock("Disk Drives", self.disk, "diskDock")
        self.addDockWidget(Qt.RightDockWidgetArea, self._disk_dock)
        self._disk_dock.setFloating(True)
        self._disk_dock.resize(520, 380)
        self._disk_dock.hide()

        # Full-width build/output console along the bottom.
        self._output_dock = self._make_dock("Output", self.output_console, "outputDock")
        self.addDockWidget(Qt.BottomDockWidgetArea, self._output_dock)

        self._all_docks = [
            self._project_dock, self._inspector_dock, self._emulator_dock,
            self._memory_dock, self._registers_dock, self._memmap_dock,
            self._disasm_dock, self._callstack_dock, self._analysis_dock,
            self._sprite_editor_dock, self._beeper_sfx_editor_dock, self._disk_dock,
            self._output_dock,
        ]

    # --- menu -----------------------------------------------------------------

    def _build_menu(self) -> None:
        """Build the menu bar (see ``menu_builder``) and keep the few parts we reuse."""
        menus = menu_builder.build(
            self, model_choices=MACHINE_MODEL_CHOICES, scale_choices=INTERFACE_SCALE_CHOICES
        )
        self._open_recent_menu = menus.open_recent
        self._load_recent_menu = menus.load_recent
        self._model_actions = menus.model_actions
        self._populate_open_recent()
        self._populate_load_recent()

    def _switch_model(self, model: str) -> None:
        """Boot the other machine model, and retarget the open project to match.

        The switch sticks: without writing it to the manifest, reopening the project would
        silently switch back, and its build template would no longer match the machine you
        chose. The same field can also be set directly in Settings ▸ Project ▸ Target
        machine, for changing what a project builds for without rebooting the emulator.
        """
        if model == machine_model(self.machine):
            return  # already there -- re-ticking the current item shouldn't reset the machine
        self.set_machine(build_machine(model))
        self._log(f"Switched to the {model.upper()} machine.")
        if self.project is not None:
            self.project.set_model(model)
            self._log(f'Project "{self.project.name}" now targets {model.upper()}.')

    # --- analysis (thin: the work is in analysis_view / zxemu_core.debug.analysis) --------

    def _show_analysis(self) -> None:
        self._reveal_dock(self._analysis_dock)

    def _find_in_memory(self, as_text: bool) -> None:
        title = "Find Text" if as_text else "Find Bytes"
        prompt = "Text:" if as_text else "Hex bytes (e.g. 21 00 40):"
        text, ok = QInputDialog.getText(self, title, prompt)
        if not ok or not text.strip():
            return
        self._show_analysis()
        if as_text:
            self.analysis.find_text(text)
            return
        try:
            pattern = bytes(int(part, 16) for part in text.split())
        except ValueError:
            self._log(f"Not a hex byte sequence: {text.strip()}")
            return
        self.analysis.find_bytes(pattern, " ".join(f"{b:02X}" for b in pattern))

    def _cross_references(self) -> None:
        address = self._ask_hex("Cross-references", "Address (hex):")
        if address is None:
            return
        self._show_analysis()
        self.analysis.cross_references(address)

    def _set_coverage(self, on: bool) -> None:
        self.controller.set_coverage_enabled(on)
        self._log("Coverage recording " + ("on (runs the slower debug loop)." if on else "off."))

    def _show_coverage(self) -> None:
        self._show_analysis()
        self.analysis.show_coverage(self.controller.coverage)

    def _set_trace(self, on: bool) -> None:
        self.controller.set_trace_enabled(on)
        self._log("Trace recording " + ("on (runs the slower debug loop)." if on else "off."))

    def _show_trace(self) -> None:
        self._show_analysis()
        self.analysis.show_trace(self.controller.trace_entries())

    # --- breakpoint conditions ---------------------------------------------------

    def _set_breakpoint_condition(self) -> None:
        address = self._ask_hex("Breakpoint Condition", "Breakpoint address (hex):")
        if address is None:
            return
        expression, ok = QInputDialog.getText(
            self,
            "Breakpoint Condition",
            f"Stop at ${address & 0xFFFF:04X} only when:",
            text=self.debug.condition_for(address) or "A == $FF",
        )
        if not ok:
            return
        expression = expression.strip()
        if not expression:  # cleared
            self.debug.remove_condition(address)
            self._log(f"Condition on ${address & 0xFFFF:04X} removed.")
            return
        try:
            self.debug.set_condition(address, expression)
        except debug_expr.ExpressionError as error:
            self._log(f"Bad condition: {error}")
            return
        self._log(f"Breakpoint ${address & 0xFFFF:04X} stops only when: {expression}")

    def _run_to_cursor(self) -> None:
        """Run until execution reaches the line the caret is on."""
        if self.debug.source_map is None:
            self._log("Run to Cursor needs a build first (no source map yet).")
            return
        path, line = self.editor.current_location()
        if path is None:
            self._log("Run to Cursor: no file open.")
            return
        address = self.debug.address_for(path, line)
        if address is None:
            self._log(f"Line {line} produced no code — nothing to run to.")
            return
        self._log(f"Running to ${address:04X} (line {line})")
        self.controller.run_to(address)

    def _run_to_address(self) -> None:
        address = self._ask_hex("Run to Address", "Address (hex):")
        if address is None:
            return
        self._log(f"Running to ${address & 0xFFFF:04X}")
        self.controller.run_to(address)

    def _list_breakpoint_conditions(self) -> None:
        if not self.debug.conditions:
            self._log("No breakpoint conditions set.")
            return
        for address, expression in sorted(self.debug.conditions.items()):
            self._log(f"  ${address:04X}  when  {expression}")

    def _clear_breakpoint_conditions(self) -> None:
        self.debug.clear_conditions()
        self._log("Cleared all breakpoint conditions.")

    # --- watchpoints ------------------------------------------------------------

    def _ask_hex(self, title: str, prompt: str) -> int | None:
        """Prompt for a hex value, accepting $8000 / 0x8000 / 8000. None if cancelled."""
        text, ok = QInputDialog.getText(self, title, prompt)
        if not ok or not text.strip():
            return None
        try:
            return int(text.strip().lstrip("$#").removeprefix("0x"), 16)
        except ValueError:
            self._log(f"Not a hex value: {text.strip()}")
            return None

    def _watch_memory(self, write: bool) -> None:
        label = "Write" if write else "Read"
        address = self._ask_hex(f"Watch Memory {label}", "Address (hex):")
        if address is None:
            return
        self.debug.watch_memory(address, write=write)
        self._log(f"Watching ${address & 0xFFFF:04X} for {label.lower()}s")

    def _watch_port(self, write: bool) -> None:
        label = "OUT" if write else "IN"
        port = self._ask_hex(f"Watch Port ({label})", "Port (hex, e.g. FE or 7FFD):")
        if port is None:
            return
        self.debug.watch_port(port, write=write)
        self._log(f"Watching {label} on port ${port:04X}")

    def _clear_watchpoints(self) -> None:
        self.debug.clear_watchpoints()
        self._log("Cleared all watchpoints.")

    def _show_disassembly(self) -> None:
        """Reveal the disassembly dock -- navigating to it should also open it."""
        self._reveal_dock(self._disasm_dock)

    def _disasm_goto_pc(self) -> None:
        self._show_disassembly()
        self.disassembly.goto_pc()

    def _disasm_goto(self, address: int) -> None:
        """Open the disassembly at an address (used by analysis results)."""
        self._show_disassembly()
        self.disassembly.goto(address)

    def _disasm_goto_label(self) -> None:
        if not self.debug.has_labels:
            self._log("No labels yet — build the project first (labels come from its SLD).")
            return
        name, ok = QInputDialog.getText(self, "Go to Label", "Label name:")
        if not ok or not name.strip():
            return
        address = self.debug.address_for_label(name)
        if address is None:
            self._log(f"No unique label matching {name.strip()!r}.")
            return
        self._log(f"{name.strip()} = ${address:04X}")
        self._show_disassembly()
        self.disassembly.goto(address)

    def _disasm_goto_address(self) -> None:
        text, ok = QInputDialog.getText(self, "Go to Address", "Address (hex):")
        if not ok or not text.strip():
            return
        try:
            address = int(text.strip().lstrip("$#").removeprefix("0x"), 16)
        except ValueError:
            self._log(f"Not a hex address: {text.strip()}")
            return
        self._show_disassembly()
        self.disassembly.goto(address)

    def _add_addon(self, addon: str, label: str) -> None:
        """Copy an optional addon's files into the open project and report what changed."""
        if self.project is None:
            self._log("No project open — use File ▸ New Project or Open Folder first.")
            return
        try:
            added, skipped = self.project.add_addon(addon)
        except OSError as error:
            self._log(f"Could not add {label}: {error}")
            return
        if added:
            self._log(f"Added {label}: {', '.join(added)}")
        for name in skipped:
            self._log(f"{label}: {name} already exists — left untouched.")
        if not added and not skipped:
            self._log(f"{label} addon is empty — nothing to add.")

    def _set_show_special(self, on: bool) -> None:
        """Toggle whitespace markers and remember the choice (auto-saved)."""
        self.editor.set_show_special(on)
        self.settings.set("show_special", on)

    def _set_interface_scale(self, scale: float) -> None:
        """Scale all UI text, then restore the (now scaled) monospace code surfaces.

        apply_ui_scale pushes the UI font onto every widget, which would overwrite
        the fixed-pitch fonts of the editor, hex view, registers, and console; we
        re-apply those at the new size so they stay monospace and aligned.
        """
        apply_ui_scale(QApplication.instance(), scale)
        self.editor.set_mono_scale(scale)
        self.memory_cells.set_mono_scale(scale)
        self.disassembly.set_mono_scale(scale)
        self.call_stack.set_mono_scale(scale)
        self.analysis.set_mono_scale(scale)
        self.registers.set_mono_scale(scale)
        self.output_console.set_mono_scale(scale)

    def _save_layout(self) -> None:
        """Write each dock's location/size/visibility to the JSON file, and log it."""
        path = layout_store.save(self._layout_path, self, self._all_docks)
        self._saved_layout = layout_store.load(path)
        self._log(f"Layout saved to {path}")
        self.statusBar().showMessage("Layout saved", 3000)

    def _reset_layout(self) -> None:
        """Restore the built-in default arrangement and delete the saved layout file."""
        self.restoreState(self._default_state)  # default panel positions
        self._apply_default_sizes()             # default proportions
        self._saved_layout = None
        if self._layout_path.exists():
            self._layout_path.unlink()
        self._log("Layout reset to default (saved layout cleared)")
        self.statusBar().showMessage("Layout reset to default", 3000)

    def _log(self, message: str) -> None:
        """Append a line to the Output console."""
        self.output_console.append_line(message)

    # --- find / go to line -----------------------------------------------------

    def _find_in_project(self) -> None:
        """Ctrl+F: search every text file in the project, results into Output.

        Project-wide rather than within-file on purpose: a Z80 project is a dozen small
        included files, so "where is this label used" is nearly always a question about
        the project, and the answer is only useful if it takes you to the line -- hence
        clickable results rather than a printed list.
        """
        if self.project is None:
            self._log("No project open — Find in Project needs a project folder.")
            return
        query, ok = QInputDialog.getText(self, "Find in Project", "Find:", text=self._last_search)
        if not ok or not query:
            return
        self._last_search = query

        hits, truncated = search_project(self.project.folder, query)
        self._reveal_dock(self._output_dock)
        self._log(f'── Find "{query}" ──')
        if not hits:
            self._log("No matches.")
            return
        for hit in hits:
            self.output_console.append_link(
                f"{hit.relative}:{hit.line}: {hit.text}", hit.path, hit.line
            )
        files = len({hit.relative for hit in hits})
        summary = f'{len(hits)} match(es) in {files} file(s) — click a line to open it'
        if truncated:
            summary += f" (stopped at {len(hits)}; narrow the search to see the rest)"
        self._log(summary)

    def _open_search_hit(self, path: str, line: int) -> None:
        """A clicked search result: open the file and put the caret on the line."""
        if not Path(path).exists():
            self._log(f"{path} no longer exists.")
            return
        self.editor.goto_line(path, line)
        self.editor.setFocus()

    def _goto_line_dialog(self) -> None:
        """Ctrl+G: jump to a line in the file you're editing."""
        path, current = self.editor.current_location()
        if path is None:
            self._log("Go to Line needs an open file.")
            return
        maximum = max(1, self.editor.line_count())
        line, ok = QInputDialog.getInt(
            self, "Go to Line", f"Line (1–{maximum}):", current or 1, 1, maximum, 1
        )
        if ok:
            self.editor.goto_line(path, line)
            self.editor.setFocus()

    def _reveal_in_file_manager(self) -> None:
        """Show the selected file (or the project folder) in the system file manager."""
        index = self.project_tree.currentIndex()
        target = Path(self._fs_model.filePath(index)) if index.isValid() else None
        if target is None or not str(target):
            target = self.project.folder if self.project is not None else None
        if target is None:
            self._log("Nothing to show — open a project or select a file first.")
            return
        error = reveal(target)
        if error:
            self._log(f"Could not show {target}: {error}")

    def _save_screenshot(self) -> None:
        """Save the current screen as both a real .scr and a viewable .bmp.

        The two capture the picture two different ways on purpose: .scr is the
        classic Spectrum screen-dump format -- exactly the 6912 bytes of display
        memory (``machine.display_memory()``, which already picks the right bank on
        both 48K and 128K, shadow screen included), openable by any Spectrum-aware
        tool -- and it has no concept of a border, so it never carries one. .bmp is
        a normal image anyone can view anywhere, taken from the view's own native
        320x256 image (border included) rather than a grab of the widget itself,
        which would only capture whatever size the dock happens to be scaling the
        picture to right now.
        """
        # Falls back to the app's own folder (the same anchor layout.json uses) when no
        # project is open -- e.g. after loading a .sna directly rather than a project.
        folder = self.project.folder if self.project is not None else Path(__file__).resolve().parent.parent
        screenshots_dir = folder / "screenshots"
        screenshots_dir.mkdir(exist_ok=True)
        base = screenshots_dir / f"screenshot_{datetime.now():%Y%m%d_%H%M%S}"

        scr_path = base.with_suffix(".scr")
        scr_path.write_bytes(bytes(self.machine.display_memory()[:6912]))

        bmp_path = base.with_suffix(".bmp")
        self.view.current_image().save(str(bmp_path), "BMP")

        self._log(f"Saved screenshot: {scr_path.name}, {bmp_path.name}")
