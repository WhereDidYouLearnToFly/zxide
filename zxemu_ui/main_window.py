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

from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import QEvent, Qt, QTimer
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from zxemu_core.machine import Machine
from zxemu_core.memlayout import PAGED_MODELS
from zxemu_core.debug import asm_meter, debug_expr
from zxemu_core.assets.manifest import AssetKind
from zxemu_core.assets.native_sprite import blank_sprite, sprite_format, sprite_suffix, suffix_for
from zxemu_core.assets.beeper_sfx import SUFFIX as BEEPER_SFX_SUFFIX
from zxemu_core.sound import music_file
from zxemu_ui.workspace import builder, project_files
from zxemu_ui.workspace.settings import detect_tracker_players
from zxemu_ui.controller import EmulatorController
from zxemu_ui.editor import EditorArea
from zxemu_ui.gamepad import GamepadSource
from zxemu_ui.panels.emulator_panel import EmulatorPanel
from zxemu_ui.panels.ay_player_view import AyPlayerView
from zxemu_ui.panels.emulator_view import EmulatorView
from zxemu_ui import layout_store, media, menu_builder
from zxemu_ui.debug_session import DebugSession
from zxemu_ui.project_tree_model import ProjectFilesModel
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
from zxemu_ui.workspace.project import ASM_SUFFIXES, SOURCE_SUFFIXES, Project, is_text_file
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


def _music_audio_sink():
    """An audio sink for the music player, or None where there is no sound device.

    Its own, not the emulator's: the two are independent streams, and a preview that fell
    silent because the machine was paused -- or fought it for the device -- would be worse
    than no preview. None is a normal outcome (headless test runs, a machine with no audio),
    and the player simply renders without playing.
    """
    try:
        from zxemu_ui.audio_output import AudioOutput

        return AudioOutput()
    except Exception:
        return None


class MainWindow(QMainWindow):
    """The IDE window: central editor, locked Project dock, floatable everything else."""

    def __init__(self, machine: Machine, controller: EmulatorController):
        super().__init__()
        self.setWindowTitle("zxide")
        self.machine = machine
        self.controller = controller
        # Constructed unconditionally, opened only when a joystick is fitted: the object
        # is inert (and pygame is not even imported) until something asks it for a pad.
        self.gamepad = GamepadSource()
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
        # The Kempston peripherals, unlike the deck prefs above, are persisted settings
        # (see settings.py) -- so they survive a relaunch, not just a model swap -- and
        # they must be applied to *this* first machine too, not only to future ones (see
        # set_machine), since nothing else will if the user fitted one last session.
        machine.mouse.enabled = bool(self.settings.get("kempston_mouse_enabled", False))
        machine.joystick.enabled = bool(self.settings.get("kempston_joystick_enabled", False))
        machine.joystick.extended = bool(self.settings.get("kempston_joystick_extended", False))
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

        # Central anchor: the code/text editor, with the assembly meter as its footer.
        self.editor = EditorArea()
        central = QWidget()
        column = QVBoxLayout(central)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self.editor, 1)
        column.addWidget(self._build_asm_meter())
        self.setCentralWidget(central)

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
        # The music player gets its own audio sink rather than sharing the emulator's: the
        # two are independent streams, and previewing a tune must not fight the machine you
        # are debugging for the sound device -- or fall silent whenever it is paused.
        self._tracker_players = []  # found per project, see _refresh_tracker_players
        self.music_player = AyPlayerView(_music_audio_sink())
        self.music_player.on_locate_player = self._adopt_tracker_player
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
        self._apply_editor_preferences()
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
        # A file dropped onto the Design-mode map becomes an asset -- the tree badges it.
        self.memory_map.assets_changed.connect(self._assets_changed)
        self.emulator_panel.screenshot_requested.connect(self._save_screenshot)
        self.editor.breakpoints_changed.connect(self._sync_breakpoints)
        # The execution-line marker: cleared while running, shown (and moved) whenever
        # paused -- on a breakpoint, a manual pause, or after each Step.
        self.controller.running_changed.connect(self._on_running_marker)
        self.controller.frame_ready.connect(self._on_frame_marker)
        self.controller.frame_ready.connect(self._check_tape_progress)

        # A pad fitted in a previous session has to be picked up now, since the menu item
        # is already ticked and nothing will toggle it to trigger the search.
        if machine.joystick.enabled:
            self._start_gamepad()

        # A player folder chosen in a previous session should work before any project is
        # opened -- otherwise picking one, restarting, and playing a .pt3 asks again.
        self._refresh_tracker_players()

        self._reopen_last_project()  # reopen whatever project was last used

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override name)
        """Arm the layout pass for once the window reaches its real (maximised) size.

        ``showMaximized()`` resizes synchronously on Windows, so this first show already
        has the final geometry. On X11/Wayland the maximise is negotiated with the window
        manager (or compositor) asynchronously -- on GNOME/Wayland in particular it can take
        well over a tick to land -- so laying out here would still see the pre-maximise
        size, throwing off the saved dock sizes (most visibly the Registers panel). Instead
        wait for the state-change event below, with this as a capped fallback for a window
        manager that never reports maximised at all (e.g. no WM, or one that ignores the
        request).
        """
        super().showEvent(event)
        if self._laid_out:
            return
        QTimer.singleShot(3000, self._finish_layout_once)

    def changeEvent(self, event) -> None:  # noqa: N802 (Qt override name)
        """Catch the window manager actually reporting "maximised" and lay out then.

        Event-driven rather than polling isMaximized() on a timer: a fixed poll interval
        either fires too early (Wayland's maximise can lag past a short poll window,
        landing the saved sizes on the pre-maximise geometry) or wastes ticks once it has
        landed. The WindowStateChange event fires exactly when Qt's idea of the window
        state changes, so there is nothing to tune here.
        """
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange and self.isMaximized():
            self._finish_layout_once()

    def _finish_layout_once(self) -> None:
        if self._laid_out:
            return
        self._laid_out = True
        # One more deferred tick: the state-change event can fire a moment before the
        # window's geometry itself has settled to the final maximised size, and dock
        # sizing below reads that geometry.
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
        self._fs_model = ProjectFilesModel()
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
        # Delete works from the keyboard too, but only while the tree has focus -- the
        # shortcut is scoped to the widget so it can never fire while you're typing code.
        delete_action = QAction("Delete", tree)
        delete_action.setShortcut(QKeySequence.Delete)
        delete_action.setShortcutContext(Qt.WidgetShortcut)
        delete_action.triggered.connect(self._delete_selected)
        tree.addAction(delete_action)
        # F2 is the rename key everywhere in Windows and in every IDE, and like Delete it
        # is scoped to the tree -- so it can never fire while you are typing in the editor.
        rename_action = QAction("Rename", tree)
        rename_action.setShortcut(QKeySequence("F2"))
        rename_action.setShortcutContext(Qt.WidgetShortcut)
        rename_action.triggered.connect(self._rename_selected)
        tree.addAction(rename_action)
        self.project_tree = tree
        return tree

    def _on_tree_selection_changed(self, current, _previous) -> None:
        """Selecting a file that matches an asset's source shows it in the Inspector."""
        if self.project is None:
            return
        path = self._fs_model.filePath(current)
        if not path:
            return
        # Music is described from the file on disk, so it needs the absolute path and the
        # detected players (whether a raw module is playable is not a property of the file).
        if self.inspector.show_music(path, self._tracker_players):
            return
        self.inspector.show_path(self.project, self.project.relative(path) or path)

    def _on_asset_selected(self, asset_id: str) -> None:
        """A placed asset was clicked in the Design-mode memory map."""
        if self.project is not None:
            self.inspector.show_asset_id(self.project, asset_id)

    def _assets_changed(self) -> None:
        """The manifest's asset list changed -- re-badge the tree and redraw the map.

        One method rather than two calls at each of the five sites that can change it
        (new sprite, new SFX, imported sequence, dropped file, deleted file), so a sixth
        can't forget half of the update.
        """
        self._fs_model.refresh_assets()
        self.memory_map.refresh()

    # --- the Z80 assembly meter -------------------------------------------------

    def _build_asm_meter(self) -> QWidget:
        """A live byte/T-state readout, as a strip along the bottom of the editor.

        It sits with the editor rather than in the status bar because it is a fact *about
        the text above it* -- it measures whatever the caret has selected -- and the far
        bottom-right corner of the window is both a long way from the code being measured
        and the most crowded spot on the screen: the corner belongs to the size grip, and
        a maximized window (which has no grip) let the readout run flush to the screen
        edge with its last glyph clipped. As a footer under the tabs it has the full width
        of the editor to itself and cannot be squeezed by anything.

        The status bar was the first home for a different reason, still worth stating: the
        controller pushes transient messages ("running", "paused at $8000") through
        ``showMessage``, so an ordinary status-bar widget would be hidden by them exactly
        when you're stepping through the code you just measured. Moving out of the status
        bar removes that hazard rather than working around it.

        Recomputation is debounced -- measuring the whole file on every keystroke is
        wasted work when the next keystroke is 40ms away, and the numbers are still live
        to the eye at this interval.
        """
        self._meter_label = QLabel("")
        self._meter_label.setToolTip(
            "Z80 Assembly Meter — T-states and size of the selected code; size alone for "
            "the whole file, since summing a file's instructions counts a loop body once "
            "and answers nothing.\nT-states are the published uncontended figures; a "
            "range means a conditional branch costs different amounts taken and not taken."
        )

        self._meter_bar = QWidget()
        self._meter_bar.setObjectName("asmMeterBar")
        # A hairline above it, so the strip reads as the editor's footer rather than as a
        # line of text floating under the last row of code.
        self._meter_bar.setStyleSheet(
            "#asmMeterBar { border-top: 1px solid #3a3a3a; background: #2b2b2b; }"
            # A soft green rather than the UI grey: the numbers are a measurement of the
            # code above, not another piece of chrome, and a desaturated tint separates
            # them from the editor without shouting at the corner of your eye.
            "#asmMeterBar QLabel { color: #9ecf9e; }"
        )
        row = QHBoxLayout(self._meter_bar)
        row.setContentsMargins(10, 3, 10, 3)
        row.addWidget(self._meter_label)
        row.addStretch(1)

        self._meter_timer = QTimer(self)
        self._meter_timer.setSingleShot(True)
        self._meter_timer.setInterval(150)
        self._meter_timer.timeout.connect(self._update_asm_meter)
        self.editor.cursor_or_text_changed.connect(self._meter_timer.start)
        self.editor.currentChanged.connect(lambda _index: self._meter_timer.start())
        return self._meter_bar

    def _update_asm_meter(self) -> None:
        path = self.editor.current_path()
        if path is None or Path(path).suffix.lower() not in ASM_SUFFIXES:
            # Not assembly -- a byte count would be nonsense, and an empty strip under a
            # text file is a row of height spent saying nothing, so the bar goes with it.
            self._set_meter_text("")
            return
        text, is_selection = self.editor.selected_or_all_text()
        # Timing only for a selection. A whole file's T-state total sums every instruction
        # once, which is not what any file costs to run -- a loop body counts one pass, a
        # subroutine called all over counts once. Its byte total is real, so that stays.
        summary = asm_meter.format_result(asm_meter.measure(text), timing=is_selection)
        # Spelled out rather than abbreviated: which of the two it is decides how to read
        # every number after it, and "sel:" was quiet enough that the readout looked like
        # it never followed the selection at all.
        scope = "selection" if is_selection else "file"
        self._set_meter_text("{}: {}".format(scope, summary) if summary else "")

    def _set_meter_text(self, text: str) -> None:
        """Show the readout, or hide the whole strip when there is nothing to say."""
        self._meter_label.setText(text)
        self._meter_bar.setVisible(bool(text))

    # --- project ---------------------------------------------------------------

    def _open_project(self, folder) -> None:
        """Point the tree at a project folder and remember it as the last opened."""
        folder = Path(folder)
        self.project = Project(folder)
        self._fs_model.setRootPath(str(folder))
        self._fs_model.set_project(self.project)  # badge this project's assets in the tree
        self.project_tree.setRootIndex(self._fs_model.index(str(folder)))
        self.memory_map.set_project(self.project)
        self.setWindowTitle("zxide — {}".format(self.project.name))
        self.settings.set("last_project", str(folder))
        self.settings.push_recent("recent_projects", str(folder))
        self._log("Opened project: {}".format(folder))
        # Boot the machine the project targets; swap only if it differs from the current one.
        self._refresh_tracker_players()  # they live beside the project, so they change with it
        model = self.project.model
        if model != machine_model(self.machine):
            self.set_machine(build_machine(model))
            self._log("Switched to the {} machine for this project.".format(model.upper()))

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
        machine.mouse.enabled = bool(self.settings.get("kempston_mouse_enabled", False))
        machine.joystick.enabled = bool(self.settings.get("kempston_joystick_enabled", False))
        machine.joystick.extended = bool(self.settings.get("kempston_joystick_extended", False))
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
        if self._open_asset_editor_for_path(path):
            return
        if self._open_music_for_path(path):
            return
        if is_text_file(path):
            self.editor.open_file(path)

    def _open_music_for_path(self, path: str) -> bool:
        """Open a music file in the player. False if this file isn't music.

        Content decides, not the extension, and that matters for exactly one suffix: a
        compiled module is conventionally ``.c``, which is also C source. Sniffing the bytes
        means a real ``.c`` file still opens in the editor, as it must.
        """
        if Path(path).suffix.lower() not in music_file.MUSIC_SUFFIXES:
            return False
        try:
            data = Path(path).read_bytes()
        except OSError as problem:
            self._log("Could not read {}: {}".format(path, problem))
            return False
        info = music_file.describe(path, data, self._tracker_players)
        if info["kind"] in ("unknown", "C source"):
            return False  # a genuine .c source file, or something else entirely
        self.music_player.load(path, data)
        self._reveal_dock(self._music_dock)
        return True

    def _adopt_tracker_player(self, chosen: str) -> list:
        """Take a player binary the user picked, remember its folder, and re-scan.

        The *folder* is remembered rather than the file: player binaries come in pairs (one
        per format) and live together, so recording where they are answers the PT2 question
        as well as the PT3 one -- asked once, not once per format.
        """
        folder = str(Path(chosen).parent)
        self.settings.set("tracker_player_dir", folder)
        self._refresh_tracker_players()
        return self._tracker_players

    def _refresh_tracker_players(self) -> None:
        """Re-hunt for player binaries, which live with the project rather than with zxide."""
        folder = str(self.project.folder) if self.project is not None else ""
        self._tracker_players = detect_tracker_players(folder, self.settings.get("tracker_player_dir", ""))
        self.music_player.set_player_binaries(self._tracker_players)
        if self._tracker_players:
            names = ", ".join(sorted({Path(p.path).name for p in self._tracker_players}))
            self._log("Tracker player(s) found for raw .pt2/.pt3 modules: {}".format(names))

    def _asset_editor_for(self, path: str):
        """``(panel, dock, kind)`` for the editor that handles this file type, or None.

        The file's *extension* decides, not the manifest -- so a sprite file that hasn't
        been added to the project yet still routes to the sprite editor rather than
        falling through to "unknown file, do nothing".
        """
        if sprite_suffix(path) is not None:
            return self.sprite_editor, self._sprite_editor_dock, AssetKind.SPRITE_SHEET
        if path.lower().endswith(BEEPER_SFX_SUFFIX):
            return self.beeper_sfx_editor, self._beeper_sfx_editor_dock, AssetKind.BEEPER_SFX
        return None

    def _open_asset_editor_for_path(self, path: str) -> bool:
        """Open ``path`` in its asset editor. False if nothing here edits that file type."""
        target = self._asset_editor_for(path)
        if target is None or self.project is None:
            return False
        panel, dock, kind = target
        entry = self._fs_model.asset_for(path) or self._offer_to_register(path, kind)
        if entry is None:
            return False  # not an asset, and the user declined to make it one
        panel.show_asset(self.project, entry)
        self._reveal_dock(dock)
        return True

    def _offer_to_register(self, path: str, kind: AssetKind):
        """Adopt a sprite/SFX file that is in the folder but not in the manifest.

        Double-clicking one of these used to do nothing at all -- no editor, no message --
        which is indistinguishable from the IDE being broken. The file is obviously
        editable (its extension says exactly what it is); the only thing missing is the
        manifest entry, so ask for that instead of silently refusing.
        """
        source = self.project.relative(path)
        name = Path(path).name
        if source is None:
            QMessageBox.information(
                self, "Add to project",
                "“{}” is outside the project folder. Copy it in first — an asset's "
                "source is recorded relative to the project so the folder can be moved.".format(name),
            )
            return None
        answer = QMessageBox.question(
            self, "Add to project",
            "“{}” isn't one of this project's assets yet, so it isn't converted, "
            "placed in memory, or addressable from your code.\n\nAdd it as a "
            "{} asset?".format(name, kind.value),
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Yes,
        )
        if answer != QMessageBox.Yes:
            return None
        entry = self.project.add_asset(source, kind)
        self._assets_changed()
        self._log("Added asset '{}' ({}) from {}".format(entry.symbol, kind.value, source))
        return entry

    def _show_tree_menu(self, pos) -> None:
        if self.project is None:
            return
        # Right-clicking does not move the selection in a QTreeView, so the menu asks the
        # view what is under the cursor rather than trusting whatever was selected before.
        clicked = self._fs_model.filePath(self.project_tree.indexAt(pos))
        menu = QMenu(self)
        menu.addAction("New File…", self._new_file)
        menu.addAction("New Folder…", self._new_folder)
        menu.addAction("New Sprite Asset…", self._new_sprite_asset)
        menu.addAction("New Beeper SFX Asset…", self._new_beeper_sfx_asset)
        menu.addSeparator()
        menu.addAction("Import Animation Sequence…", self._import_animation_sequence)
        if clicked:
            menu.addSeparator()
            menu.addAction("Rename…\tF2", lambda: self.rename_path(clicked))
            label = "Delete Folder…" if Path(clicked).is_dir() else "Delete…"
            menu.addAction(label, lambda: self.delete_path(clicked))
        menu.addSeparator()
        menu.addAction("Show in {}".format(FILE_MANAGER_NAME), self._reveal_in_file_manager)
        menu.exec_(self.project_tree.viewport().mapToGlobal(pos))

    def _delete_selected(self) -> None:
        """What the Delete key does: remove whatever the tree has selected."""
        index = self.project_tree.currentIndex()
        if index.isValid():
            self.delete_path(self._fs_model.filePath(index))

    def _rename_selected(self) -> None:
        """What F2 does: rename whatever the tree has selected."""
        index = self.project_tree.currentIndex()
        if index.isValid():
            self.rename_path(self._fs_model.filePath(index))

    def rename_path(self, path: str) -> bool:
        """Rename a file or folder in the project. Returns whether it happened.

        Same split as ``delete_path``: what needs a window stays here -- asking for the
        name, reopening the editor tab, logging -- and the part with consequences
        (``workspace.project_files.rename``, which also repoints the manifest) is Qt-free
        and tested without one.
        """
        if self.project is None or not path:
            return False
        target = Path(path)
        if not target.exists():
            return False
        if target.resolve() == self.project.folder.resolve():
            QMessageBox.information(self, "Rename", "That's the project folder itself — rename it from outside zxide.")
            return False

        new_name, ok = QInputDialog.getText(self, "Rename", "New name:", text=target.name)
        if not ok:
            return False

        # Warned about rather than refused: a native sprite's extension *is* its format
        # (see native_sprite), so changing it changes how the bytes are read back -- which
        # is occasionally exactly what somebody means to do.
        if not self._confirm_suffix_change(target, new_name.strip()):
            return False

        # Which tabs were open on this, so they can be reopened at the new name. Saved
        # first: the file is about to move out from under them, and an unsaved buffer over
        # a path that no longer exists would recreate the old file on the next Save All.
        reopen = self.editor.close_files_under(str(target))
        try:
            affected = project_files.rename(self.project, target, new_name)
        except project_files.RenameProblem as problem:
            QMessageBox.information(self, "Rename", str(problem))
            self._reopen(reopen)
            return False
        except OSError as exc:
            QMessageBox.critical(self, "Rename", "Could not rename {}:\n{}".format(target.name, exc))
            self._reopen(reopen)
            return False

        destination = target.with_name(new_name.strip())
        self._log(
            "Renamed {} to {}".format(target.name, destination.name)
            + (" ({} asset(s) repointed)".format(len(affected)) if affected else "")
        )
        self._reopen_moved(reopen, target, destination)
        self._assets_changed()
        return True

    def _confirm_suffix_change(self, target: Path, new_name: str) -> bool:
        """If a rename changes an asset file's extension, say what that means first."""
        if target.is_dir() or Path(new_name).suffix.lower() == target.suffix.lower():
            return True
        if not project_files.assets_under(self.project, target):
            return True
        answer = QMessageBox.warning(
            self,
            "Rename",
            "“{}” is an asset and you are changing its extension.\n\nFor sprites the extension *is* "
            "the format — its size and whether it has colour — so the same bytes will be read back "
            "differently.\n\nRename anyway?".format(target.name),
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        return answer == QMessageBox.Yes

    def _reopen(self, paths) -> None:
        """Put back tabs closed for a rename that then did not happen.

        A refused or failed rename must not cost somebody the tabs they had open -- they
        were closed in preparation, and the preparation turned out to be unnecessary.
        """
        for path in paths or ():
            self.editor.open_file(path)

    def _reopen_moved(self, paths, target: Path, destination: Path) -> None:
        """Put back tabs at where their files are *now*, after a rename succeeded."""
        for path in paths or ():
            was = Path(path)
            self.editor.open_file(str(destination if was == target else destination / was.relative_to(target)))

    def delete_path(self, path: str) -> bool:
        """Delete a file or folder from the project, after confirming. Returns whether it went.

        Only the parts that need a window are here -- asking whether you meant it, closing
        the editor tab, logging. What actually has to happen to the project (its assets,
        their cached bytes, then the file) is ``workspace.project_files.delete``, which
        needs no Qt and is tested without it.
        """
        if self.project is None or not path:
            return False
        target = Path(path)
        if not target.exists():
            return False
        if target.resolve() == self.project.folder.resolve():
            QMessageBox.information(
                self, "Delete", "That's the project folder itself — close the project and delete it from disk."
            )
            return False

        if not self._confirm_delete(target):
            return False

        # The tab goes first: it is the one thing that can't be undone by re-reading disk,
        # and a tab over a deleted file would recreate it on the next Save All.
        self.editor.close_files_under(str(target))
        try:
            removed = project_files.delete(self.project, target)
        except OSError as exc:
            QMessageBox.critical(self, "Delete", "Could not delete {}:\n{}".format(target.name, exc))
            return False

        self._log("Deleted {}".format(target) + (" (and {} asset(s))".format(len(removed)) if removed else ""))
        self._assets_changed()
        self.inspector.clear()
        return True

    def _confirm_delete(self, target: Path) -> bool:
        """Ask, saying up front everything that goes along with the file itself."""
        consequences = []
        if target.is_dir():
            contents = project_files.count_contents(target)
            consequences.append("{} item{} inside it".format(contents, 's' if contents != 1 else ''))
        assets = project_files.assets_under(self.project, target)
        if assets:
            names = ", ".join(sorted(entry.symbol for entry in assets))
            consequences.append("{} asset{} in the manifest ({})".format(len(assets), 's' if len(assets) != 1 else '', names))

        detail = "\n\nThis also removes {}.".format(' and '.join(consequences)) if consequences else ""
        answer = QMessageBox.warning(
            self,
            "Delete",
            "Delete {} “{}”?{}\n\nThis cannot be undone.".format('folder' if target.is_dir() else 'file', target.name, detail),
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        return answer == QMessageBox.Yes

    def _new_sprite_asset(self) -> None:
        """A blank sprite drawn in zxide's own editor, not imported from a file.

        Size and colour-ness pick the file's *extension* rather than being recorded
        anywhere: a native sprite file is exactly the bytes the Z80 gets, so its name is
        the only place left to say how to read it back (see ``native_sprite``).
        """
        if self.project is None:
            return
        size_label, ok = QInputDialog.getItem(
            self, "New Sprite Asset", "Size:", ["8x8", "16x16", "Custom"], 0, False
        )
        if not ok:
            return
        if size_label == "Custom":
            width, ok = QInputDialog.getInt(self, "New Sprite Asset", "Width (multiple of 8):", 8, 8, 248, 8)
            if not ok:
                return
            height, ok = QInputDialog.getInt(self, "New Sprite Asset", "Height (multiple of 8):", 8, 8, 248, 8)
            if not ok:
                return
        else:
            width, height = (8, 8) if size_label == "8x8" else (16, 16)
        colour_label, ok = QInputDialog.getItem(
            self, "New Sprite Asset", "Data:", ["Pixels + attributes", "Pixels only"], 0, False
        )
        if not ok:
            return
        has_attrs = colour_label == "Pixels + attributes"
        frame_count, ok = QInputDialog.getInt(self, "New Sprite Asset", "Frame count:", 1, 1, 64, 1)
        if not ok:
            return
        name, ok = QInputDialog.getText(self, "New Sprite Asset", "Name:", text="sprite")
        if not ok or not name.strip():
            return

        symbol = name.strip()
        suffix = suffix_for(width, height, has_attrs)
        path = self._target_dir() / "{}{}".format(symbol, suffix)
        document = blank_sprite(width, height, frame_count, has_attrs=has_attrs)
        path.write_bytes(document.encode(with_header=sprite_format(suffix).has_header))
        entry = self.project.add_asset(self.project.relative(path), AssetKind.SPRITE_SHEET, symbol=symbol)

        self.sprite_editor.show_asset(self.project, entry)
        self._reveal_dock(self._sprite_editor_dock)
        self._assets_changed()

    def _new_beeper_sfx_asset(self) -> None:
        """A blank beeper sound effect built in zxide's own editor, not hand-typed."""
        if self.project is None:
            return
        name, ok = QInputDialog.getText(self, "New Beeper SFX Asset", "Name:", text="sfx")
        if not ok or not name.strip():
            return

        symbol = name.strip()
        path = self._target_dir() / "{}{}".format(symbol, BEEPER_SFX_SUFFIX)
        path.write_text("", encoding="utf-8")  # empty -- add tones/rests in the editor
        entry = self.project.add_asset(self.project.relative(path), AssetKind.BEEPER_SFX, symbol=symbol)

        self.beeper_sfx_editor.show_asset(self.project, entry)
        self._reveal_dock(self._beeper_sfx_editor_dock)
        self._assets_changed()

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
        self._assets_changed()

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
        self._log("── {} ──".format('Build & Debug' if debug else 'Build & Run'))
        self.editor.save_all()  # you can't assemble a tab, only a file on disk
        main = self._compile_target()
        if main is not None:
            self._log("Assembling {}".format(main))
        result = builder.build(self.project, self.settings, main)
        self._log("$ " + " ".join(result.command))
        if result.output.strip():
            self._log(result.output.rstrip())
        if result.returncode != 0:
            self._log("Build failed (exit code {}).".format(result.returncode))
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
        self._log("Breakpoint hit at ${:04X}".format(address))

    def _on_watchpoint_hit(self, description: str) -> None:
        """Execution paused on a watchpoint: report what was touched, and by roughly what.

        "Roughly": PC has already moved past the instruction that did it by the time we
        look, so the reported address is where execution *is*, not the exact opcode.
        Open the disassembly to see the instruction just above it.
        """
        self._log("Watchpoint: {}".format(description))
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
            self, "Load {}".format(fmt.label), self._media_dir(), fmt.file_filter
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
            self._log("File no longer exists: {}".format(path))
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
            self._log("Don't know how to load {}.".format(path.name))
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
            self._log("Could not load {}: {}".format(path.name, error))
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
        self._log("Loaded {} — running.".format(path.name))
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
            self._log("Could not load {}: {}".format(path.name, error))
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
                "{} is not empty. Files with the same names will be overwritten.\n\n"
                "Continue?".format(folder),
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
            self._log("Could not dump: {}".format(error))
            return

        self._log("Dumped {} RAM to {}.".format(model.upper(), folder))
        if executed:
            self._log("  {} address(es) executed — those became disassembly; "
                      "everything else is data.".format(executed))
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
            self._log("Could not load {}: {}".format(path.name, error))
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
                "{} has unsaved changes. Eject anyway?".format(image.name or 'This disk'),
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
            self, "Mount in drive {}".format('AB'[drive]), self._media_dir(),
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
            self._log("Could not save {}: {}".format(path, error))
            return False
        image.dirty = False
        image.name = Path(path).name
        self._remember_media_dir(path)   # saving somewhere is just as good a hint as loading
        self._log("Saved disk to {}.".format(path))
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
        self._log("No tape block has been read for {}s "
                  "({} of {} loaded).".format(TAPE_STALL_FRAMES // 50, blocks_read, len(deck.blocks)))
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
            disabled = menu.addAction("({})".format(empty_label))
            disabled.setEnabled(False)
            return
        for index, path in enumerate(paths, start=1):
            prefix = "&{}  ".format(index) if index <= 9 else ""
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
        return "{}  ({})".format(p.name, parent) if parent else p.name

    def _open_recent_project(self, folder) -> None:
        """Open a project from the recent list, pruning it if the folder is gone."""
        if Path(folder).is_dir():
            self._open_project(folder)
        else:
            self._log("Project folder no longer exists: {}".format(folder))
            self.settings.remove_recent("recent_projects", str(folder))

    def _open_settings(self) -> None:
        SettingsDialog(self.settings, self.project, self).exec_()
        self._apply_editor_preferences()  # a preference you just changed should be live

    def _apply_editor_preferences(self) -> None:
        """Push the saved editor preferences onto the editor. Called at startup too."""
        self.editor.set_instruction_help(bool(self.settings.get("instruction_help", True)))

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

        # Sprite Editor: opened on demand (New Sprite Asset, or opening a sprite file),
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

        # Music player: on-demand like the editors above, and floating from the start --
        # it is something you pop out beside the IDE while a tune plays, not a panel you
        # dock permanently into a layout you use for code.
        self._music_dock = self._make_dock("Music Player", self.music_player, "musicPlayerDock")
        # Belt and braces on "closing the popup stops the music". The panel stops itself on
        # hide, which covers the dock closing -- but this is the dock saying so directly,
        # and it costs one connection to not depend on how Qt propagates hides to children.
        self._music_dock.visibilityChanged.connect(lambda visible: None if visible else self.music_player.stop())
        self.addDockWidget(Qt.RightDockWidgetArea, self._music_dock)
        self._music_dock.setFloating(True)
        self._music_dock.resize(420, 260)
        self._music_dock.hide()

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
            self._sprite_editor_dock, self._beeper_sfx_editor_dock, self._music_dock,
            self._disk_dock, self._output_dock,
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
        self._log("Switched to the {} machine.".format(model.upper()))
        if self.project is not None:
            self.project.set_model(model)
            self._log('Project "{}" now targets {}.'.format(self.project.name, model.upper()))

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
            self._log("Not a hex byte sequence: {}".format(text.strip()))
            return
        self.analysis.find_bytes(pattern, " ".join("{:02X}".format(b) for b in pattern))

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
            "Stop at ${:04X} only when:".format(address & 65535),
            text=self.debug.condition_for(address) or "A == $FF",
        )
        if not ok:
            return
        expression = expression.strip()
        if not expression:  # cleared
            self.debug.remove_condition(address)
            self._log("Condition on ${:04X} removed.".format(address & 65535))
            return
        try:
            self.debug.set_condition(address, expression)
        except debug_expr.ExpressionError as error:
            self._log("Bad condition: {}".format(error))
            return
        self._log("Breakpoint ${:04X} stops only when: {}".format(address & 65535, expression))

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
            self._log("Line {} produced no code — nothing to run to.".format(line))
            return
        self._log("Running to ${:04X} (line {})".format(address, line))
        self.controller.run_to(address)

    def _run_to_address(self) -> None:
        address = self._ask_hex("Run to Address", "Address (hex):")
        if address is None:
            return
        self._log("Running to ${:04X}".format(address & 65535))
        self.controller.run_to(address)

    def _list_breakpoint_conditions(self) -> None:
        if not self.debug.conditions:
            self._log("No breakpoint conditions set.")
            return
        for address, expression in sorted(self.debug.conditions.items()):
            self._log("  ${:04X}  when  {}".format(address, expression))

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
            self._log("Not a hex value: {}".format(text.strip()))
            return None

    def _watch_memory(self, write: bool) -> None:
        label = "Write" if write else "Read"
        address = self._ask_hex("Watch Memory {}".format(label), "Address (hex):")
        if address is None:
            return
        self.debug.watch_memory(address, write=write)
        self._log("Watching ${:04X} for {}s".format(address & 65535, label.lower()))

    def _watch_port(self, write: bool) -> None:
        label = "OUT" if write else "IN"
        port = self._ask_hex("Watch Port ({})".format(label), "Port (hex, e.g. FE or 7FFD):")
        if port is None:
            return
        self.debug.watch_port(port, write=write)
        self._log("Watching {} on port ${:04X}".format(label, port))

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
            self._log("No unique label matching {!r}.".format(name.strip()))
            return
        self._log("{} = ${:04X}".format(name.strip(), address))
        self._show_disassembly()
        self.disassembly.goto(address)

    def _disasm_goto_address(self) -> None:
        text, ok = QInputDialog.getText(self, "Go to Address", "Address (hex):")
        if not ok or not text.strip():
            return
        try:
            address = int(text.strip().lstrip("$#").removeprefix("0x"), 16)
        except ValueError:
            self._log("Not a hex address: {}".format(text.strip()))
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
            self._log("Could not add {}: {}".format(label, error))
            return
        if added:
            self._log("Added {}: {}".format(label, ', '.join(added)))
        for name in skipped:
            self._log("{}: {} already exists — left untouched.".format(label, name))
        if not added and not skipped:
            self._log("{} addon is empty — nothing to add.".format(label))

    def _set_show_special(self, on: bool) -> None:
        """Toggle whitespace markers and remember the choice (auto-saved)."""
        self.editor.set_show_special(on)
        self.settings.set("show_special", on)

    def _set_kempston_mouse(self, on: bool) -> None:
        """Fit or remove the Kempston Mouse, and remember the choice (auto-saved)."""
        self.machine.mouse.enabled = on
        self.settings.set("kempston_mouse_enabled", on)
        if on:
            self._kempston_actions["joystick"].setChecked(False)  # they share port 0x1F
            self._log_kempston_needs_a_restart("Kempston Mouse")
        else:
            # Switching it off mid-capture would otherwise strand the pointer hidden
            # and grabbed with no interface left listening to it.
            self.view.release_mouse_capture()

    def _set_kempston_joystick(self, on: bool) -> None:
        """Fit or remove the Kempston Joystick, and remember the choice (auto-saved)."""
        self.machine.joystick.enabled = on
        self.settings.set("kempston_joystick_enabled", on)
        self._kempston_actions["extended"].setEnabled(on)  # a mode of this, not a third device
        if on:
            self._kempston_actions["mouse"].setChecked(False)  # they share port 0x1F
            self._log_kempston_needs_a_restart("Kempston Joystick")
            self._start_gamepad()
        else:
            self.gamepad.close()
            self.controller.input_poll = None
            # Anything held when the interface goes away never gets its key-up, and the
            # switches would stay closed -- a game left running into a wall for good.
            self.machine.joystick.release_all()

    def _set_kempston_joystick_extended(self, on: bool) -> None:
        """Switch the joystick between the Next's Kempston and MD 3-button masks.

        Not a separate interface and not a separate port -- the same 0x1F, with bits 7:6
        either passed or forced to 0. See ``zxemu_core/joystick.py`` for why that masking
        is the whole of the difference.
        """
        self.machine.joystick.extended = on
        self.settings.set("kempston_joystick_extended", on)

    def _start_gamepad(self) -> None:
        """Look for a USB pad and, if one is there, poll it into the fitted joystick.

        Deliberately silent when there is nothing to find: a pad is a bonus, the arrow keys
        are the baseline, and a user who has never owned a gamepad should not be told about
        one. When a pad *is* found its name is logged, because the opposite failure -- a
        connected pad doing nothing -- is otherwise impossible to distinguish from a bug.
        """
        name = self.gamepad.open()
        if name is None:
            self.controller.input_poll = None
            return
        self._log("Gamepad detected: {} — steers the Kempston Joystick, any button fires.".format(name))
        self.controller.input_poll = self._poll_gamepad

    def _poll_gamepad(self) -> None:
        """Hand one poll of the pad to the joystick (see ``KempstonJoystick.set_pad_switches``)."""
        self.machine.joystick.set_pad_switches(self.gamepad.poll())

    def _log_kempston_needs_a_restart(self, label: str) -> None:
        """Say out loud that fitting an interface mid-game is usually too late.

        Software reads these ports once, on startup, to decide what is attached and which
        control scheme to offer. Plugging something in underneath a running game therefore
        appears to do nothing at all, and the user is left toggling a menu item that (as
        far as they can see) is broken. The port is live immediately -- it is the *game*
        that has stopped asking.
        """
        self._log("{} fitted. Software checks for it at startup, so reset or reload for a running program to notice.".format(label))

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
        self._log("Layout saved to {}".format(path))
        self.statusBar().showMessage("Layout saved", 3000)

    def _reset_layout(self) -> None:
        """Restore the built-in default arrangement and delete the saved layout file.

        The sizes wait a tick behind the arrangement for the same reason ``layout_store.apply``
        defers its own: ``restoreState`` queues the splitter rebuild for the next event loop
        pass, so ``resizeDocks`` called in this tick would size the *old* tree and silently
        do nothing -- leaving Registers oversized on the very menu item meant to fix it.
        """
        self.restoreState(self._default_state)          # default panel positions
        QTimer.singleShot(0, self._apply_default_sizes)  # default proportions, once it lands
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
        self._log('── Find "{}" ──'.format(query))
        if not hits:
            self._log("No matches.")
            return
        for hit in hits:
            self.output_console.append_link(
                "{}:{}: {}".format(hit.relative, hit.line, hit.text), hit.path, hit.line
            )
        files = len({hit.relative for hit in hits})
        summary = '{} match(es) in {} file(s) — click a line to open it'.format(len(hits), files)
        if truncated:
            summary += " (stopped at {}; narrow the search to see the rest)".format(len(hits))
        self._log(summary)

    def _open_search_hit(self, path: str, line: int) -> None:
        """A clicked search result: open the file and put the caret on the line."""
        if not Path(path).exists():
            self._log("{} no longer exists.".format(path))
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
            self, "Go to Line", "Line (1–{}):".format(maximum), current or 1, 1, maximum, 1
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
            self._log("Could not show {}: {}".format(target, error))

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
        base = screenshots_dir / "screenshot_{:%Y%m%d_%H%M%S}".format(datetime.now())

        scr_path = base.with_suffix(".scr")
        scr_path.write_bytes(bytes(self.machine.display_memory()[:6912]))

        bmp_path = base.with_suffix(".bmp")
        self.view.current_image().save(str(bmp_path), "BMP")

        self._log("Saved screenshot: {}, {}".format(scr_path.name, bmp_path.name))
