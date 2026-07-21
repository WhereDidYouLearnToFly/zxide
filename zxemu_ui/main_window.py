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
debug panels, update the status bar). File/View menus, a monospace console, an
adjustable interface scale, and layout reset round it out. The Project tree and
Output console are still stubs, filled in by the project system and build pipeline.
"""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QAction,
    QActionGroup,
    QApplication,
    QDockWidget,
    QFileDialog,
    QFileSystemModel,
    QInputDialog,
    QMainWindow,
    QMenu,
    QPlainTextEdit,
    QTreeView,
    QWidget,
)

from zxemu_core import snapshot
from zxemu_core.machine import Machine
from zxemu_ui import builder, sld
from zxemu_ui.controller import EmulatorController
from zxemu_ui.editor import EditorArea
from zxemu_ui.emulator_panel import EmulatorPanel
from zxemu_ui.emulator_view import EmulatorView
from zxemu_ui import layout_store
from zxemu_ui.inspector_view import InspectorView
from zxemu_ui.machine_factory import build_machine, machine_model
from zxemu_ui.memory_cells_view import MemoryCellsView
from zxemu_ui.memory_map_view import MemoryMapView
from zxemu_ui.project import Project, is_text_file
from zxemu_ui.registers_view import RegistersView
from zxemu_ui.settings import Settings
from zxemu_ui.settings_dialog import SettingsDialog
from zxemu_ui.theme import apply_ui_scale, monospace_font

# Interface-scale choices offered in the View menu, as multiples of the base font size.
INTERFACE_SCALE_CHOICES = (
    ("100%", 1.0), ("125%", 1.25), ("150%", 1.5), ("175%", 1.75), ("200%", 2.0),
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
        self._source_map = None  # line<->address map from the last build (for breakpoints)
        self._debugging = False  # True after Build & Debug (breakpoints active)

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
        self.registers = RegistersView(machine)
        self.memory_map = MemoryMapView(machine)
        self.inspector = InspectorView()
        self.output_console = self._make_console()

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
        self.controller.frame_ready.connect(self.memory_map.refresh)
        self.controller.status_changed.connect(self.statusBar().showMessage)
        self.controller.breakpoint_hit.connect(self._on_breakpoint_hit)
        self.editor.breakpoints_changed.connect(self._sync_breakpoints)
        # The execution-line marker: cleared while running, shown (and moved) whenever
        # paused -- on a breakpoint, a manual pause, or after each Step.
        self.controller.running_changed.connect(self._on_running_marker)
        self.controller.frame_ready.connect(self._on_frame_marker)

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

    def _finish_layout(self) -> None:
        if self._saved_layout is not None:
            docks_by_name = {d.objectName(): d for d in self._all_docks}
            layout_store.apply(self, docks_by_name, self._saved_layout)
        else:
            self._apply_default_sizes()

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

    def _make_console(self) -> QPlainTextEdit:
        console = QPlainTextEdit()
        console.setReadOnly(True)
        console.setPlaceholderText("Build output will appear here.")
        console.setFont(monospace_font())  # column-aligned, like a code editor
        return console

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
        self.project_tree = tree
        return tree

    # --- project ---------------------------------------------------------------

    def _open_project(self, folder) -> None:
        """Point the tree at a project folder and remember it as the last opened."""
        folder = Path(folder)
        self.project = Project(folder)
        self._fs_model.setRootPath(str(folder))
        self.project_tree.setRootIndex(self._fs_model.index(str(folder)))
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
        self.registers.machine = machine
        self.memory_map.machine = machine
        self.controller.set_machine(machine)
        self.view.refresh()
        self.registers.refresh()
        self.memory_cells.refresh(force=True)
        self.memory_map.refresh()

    def _new_project(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder for the new project")
        if not folder:
            return
        name, ok = QInputDialog.getText(self, "New Project", "Project name:", text=Path(folder).name)
        if not ok or not name.strip():
            return
        model_label, ok = QInputDialog.getItem(
            self, "Target machine", "Machine model:", ["48K", "128K"], 0, False
        )
        if not ok:
            return
        model = "128k" if model_label == "128K" else "48k"
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
        """Double-click a file: open text files in the editor."""
        path = self._fs_model.filePath(index)
        if path and Path(path).is_file() and is_text_file(path):
            self.editor.open_file(path)

    def _show_tree_menu(self, pos) -> None:
        if self.project is None:
            return
        menu = QMenu(self)
        menu.addAction("New File…", self._new_file)
        menu.addAction("New Folder…", self._new_folder)
        menu.exec_(self.project_tree.viewport().mapToGlobal(pos))

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
        result = builder.build(self.project, self.settings)
        self._log("$ " + " ".join(result.command))
        if result.output.strip():
            self._log(result.output.rstrip())
        if result.returncode != 0:
            self._log(f"Build failed (exit code {result.returncode}).")
            return
        if result.snapshot is None:
            self._log("Build succeeded, but no snapshot was produced.")
            return
        self._debugging = debug
        self._load_source_map(result.sld)  # source lines <-> addresses
        self._sync_breakpoints()            # applied only when debugging
        if self._load_snapshot(result.snapshot):
            self.controller.set_running(True)

    def _load_source_map(self, sld_path) -> None:
        """Parse the build's SLD file into a line<->address map."""
        self._source_map = None
        if sld_path is not None and self.project is not None:
            try:
                self._source_map = sld.parse(
                    Path(sld_path).read_text(encoding="utf-8"), base_dir=self.project.folder
                )
            except OSError:
                pass

    def _sync_breakpoints(self) -> None:
        """Translate editor breakpoint lines into PC addresses -- only when debugging."""
        addresses = set()
        if self._debugging and self._source_map is not None:
            for path, lines in self.editor.all_breakpoints().items():
                addresses |= self._source_map.breakpoint_addresses(path, lines)
        self.controller.set_breakpoints(addresses)

    def _on_breakpoint_hit(self, address: int) -> None:
        """Execution paused on a breakpoint: log it and refresh the debug panels.

        The editor's execution-line highlight follows from the pause itself
        (see _on_running_marker), so it lands on the right line automatically.
        """
        self._log(f"Breakpoint hit at ${address:04X}")
        self.view.refresh()
        self.registers.refresh()
        self.memory_cells.refresh(force=True)
        self.memory_map.refresh()

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
        if self._source_map is None:
            return
        location = self._source_map.line_for(self.machine.cpu.regs.pc)
        if location is not None:
            self.editor.set_execution_line(*location)
        else:
            self.editor.clear_execution_line()  # PC is in code we have no source for

    def _load_snapshot_dialog(self) -> None:
        start_dir = str(self.project.folder) if self.project else ""
        path, _ = QFileDialog.getOpenFileName(self, "Load Snapshot", start_dir, "Snapshots (*.sna)")
        if path:
            self._load_media(path)

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
        suffix = path.suffix.lower()
        if suffix == ".sna":
            ok = self._load_snapshot(path)
        elif suffix == ".tap":
            self._log("Tape (.tap) loading isn't supported yet.")
            ok = False
        else:
            self._log(f"Don't know how to load {path.name}.")
            ok = False
        if ok:
            self.settings.push_recent("recent_files", str(path))
        return ok

    def _load_snapshot(self, path) -> bool:
        """Load a .sna into the machine and refresh the views. Returns success."""
        path = Path(path)
        try:
            snapshot.load_sna(self.machine, path.read_bytes())
        except (ValueError, NotImplementedError, OSError) as error:
            self._log(f"Could not load {path.name}: {error}")
            return False
        # Repaint the screen and the live debug panels from the new state.
        self.view.refresh()
        self.registers.refresh()
        self.memory_cells.refresh(force=True)
        self.memory_map.refresh()
        self.view.setFocus()  # you just loaded something to run -- send the keyboard here
        self._log(f"Loaded {path.name} — running.")
        return True

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

        # Full-width build/output console along the bottom.
        self._output_dock = self._make_dock("Output", self.output_console, "outputDock")
        self.addDockWidget(Qt.BottomDockWidgetArea, self._output_dock)

        self._all_docks = [
            self._project_dock, self._inspector_dock, self._emulator_dock,
            self._memory_dock, self._registers_dock, self._memmap_dock, self._output_dock,
        ]

    # --- menu -----------------------------------------------------------------

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        new_project = QAction("New Project…", self)
        new_project.triggered.connect(self._new_project)
        file_menu.addAction(new_project)
        open_folder = QAction("Open Folder…", self)
        open_folder.triggered.connect(self._open_folder)
        file_menu.addAction(open_folder)
        # Open Recent: recently opened project folders, rebuilt each time it's shown.
        self._open_recent_menu = file_menu.addMenu("Open &Recent")
        self._open_recent_menu.aboutToShow.connect(self._populate_open_recent)
        self._populate_open_recent()
        file_menu.addSeparator()
        save = QAction("&Save", self)
        save.setShortcut("Ctrl+S")
        save.triggered.connect(self.editor.save_current)
        file_menu.addAction(save)
        save_all = QAction("Save A&ll", self)
        save_all.setShortcut("Ctrl+Shift+S")
        save_all.triggered.connect(self.editor.save_all)
        file_menu.addAction(save_all)
        file_menu.addSeparator()
        quit_action = QAction("E&xit", self)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        build_menu = self.menuBar().addMenu("&Build")
        debug_action = QAction("Build && Debug", self)
        debug_action.setShortcut("F5")
        debug_action.setToolTip("Build and run with breakpoints active")
        debug_action.triggered.connect(self._build_and_debug)
        build_menu.addAction(debug_action)
        run_action = QAction("Build && Run", self)
        run_action.setShortcut("Ctrl+F5")
        run_action.setToolTip("Build and run without debugging (ignore breakpoints)")
        run_action.triggered.connect(self._build_and_run)
        build_menu.addAction(run_action)
        build_menu.addSeparator()
        load_snapshot = QAction("Load Snapshot…", self)
        load_snapshot.triggered.connect(self._load_snapshot_dialog)
        build_menu.addAction(load_snapshot)
        # Load Recent: recently loaded snapshots/tapes, rebuilt each time it's shown.
        self._load_recent_menu = build_menu.addMenu("Load &Recent")
        self._load_recent_menu.aboutToShow.connect(self._populate_load_recent)
        self._populate_load_recent()

        view_menu = self.menuBar().addMenu("&View")
        self._build_interface_scale_menu(view_menu)
        special_chars = QAction("Show special characters", self, checkable=True)
        special_chars.setChecked(bool(self.settings.get("show_special", False)))
        self.editor.set_show_special(special_chars.isChecked())  # apply the saved preference
        special_chars.toggled.connect(self._set_show_special)
        view_menu.addAction(special_chars)
        view_menu.addSeparator()
        for dock in self._all_docks:
            view_menu.addAction(dock.toggleViewAction())  # show/hide each panel
        view_menu.addSeparator()
        save_action = QAction("Save layout", self)
        save_action.triggered.connect(self._save_layout)
        view_menu.addAction(save_action)
        reset_action = QAction("Reset layout", self)
        reset_action.triggered.connect(self._reset_layout)
        view_menu.addAction(reset_action)

        # Top-level "Settings" in the menu bar, alongside File and View (opens directly).
        settings_action = self.menuBar().addAction("Settings")
        settings_action.triggered.connect(self._open_settings)

    def _build_interface_scale_menu(self, view_menu) -> None:
        """A checkable group scaling all UI text, for readability on large displays."""
        scale_menu = view_menu.addMenu("Interface scale")
        group = QActionGroup(self)
        group.setExclusive(True)
        for label, scale in INTERFACE_SCALE_CHOICES:
            action = QAction(label, self, checkable=True)
            action.setChecked(scale == 1.0)
            action.triggered.connect(lambda _checked, s=scale: self._set_interface_scale(s))
            group.addAction(action)
            scale_menu.addAction(action)

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
        self.registers.set_mono_scale(scale)
        self.output_console.setFont(monospace_font(scale))

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
        self.output_console.appendPlainText(message)
