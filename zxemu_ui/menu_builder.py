"""The menu bar, described as data rather than assembled by hand.

Every menu item was four near-identical statements -- make a ``QAction``, set a shortcut,
set a tooltip, connect it, add it -- repeated about sixty times, which put two hundred
lines of ceremony in ``MainWindow`` and buried the one thing a reader actually wants from
this code: *what is on the menus, and what does each item do?* Here the answer is a list
you can read top to bottom.

``Item`` holds real callables, not method names as strings: a handler stays greppable,
renameable and checkable by tooling, which a string would quietly break.

The grouping is the point, and it is by **what you are doing** rather than by which class
implements it -- see the module docstring in ``main_window.py``. Nothing here knows how any
of the actions work; it knows only where they live.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from PyQt5.QtWidgets import QAction, QActionGroup, QMenu

from zxemu_ui import media


@dataclass(frozen=True)
class Item:
    """One menu entry. An empty label (:data:`SEPARATOR`) is a divider."""

    label: str = ""
    handler: Callable[[], None] | None = None
    shortcut: str = ""
    tip: str = ""
    checkable: bool = False
    checked: bool = False  # only meaningful with checkable; set before the handler is
                           # connected, so declaring a default can't fire it on startup
    # An action that already exists -- a dock's own toggleViewAction, say -- to be added
    # as-is rather than built here. ``label`` then renames it for the menu.
    action: QAction | None = None


SEPARATOR = Item()


@dataclass
class Menus:
    """The few menu objects the window keeps a handle on, and why it needs each.

    Everything else is owned by the menu bar and never touched again; these three are
    referred to later, so they are handed back explicitly rather than reached for.
    """

    open_recent: QMenu  # repopulated from settings each time it is shown
    load_recent: QMenu  # likewise
    model_actions: dict[str, QAction] = field(default_factory=dict)  # ticked to follow the live machine


def add_items(window, menu: QMenu, items) -> None:
    """Append ``items`` to ``menu``, creating a QAction for each (or reusing one)."""
    for item in items:
        if not item.label and item.action is None:
            menu.addSeparator()
            continue
        if item.action is not None:
            action = item.action
            if item.label:
                action.setText(item.label)
        else:
            action = QAction(item.label, window, checkable=item.checkable)
            if item.checkable and item.checked:
                action.setChecked(True)  # before connecting: a default is not a user action
            if item.shortcut:
                action.setShortcut(item.shortcut)
            if item.handler is not None:
                if item.checkable:
                    # A checkable item's handler wants the new state; toggled carries it.
                    action.toggled.connect(item.handler)
                else:
                    # ``triggered`` carries a `checked` bool, and PyQt passes it to any
                    # slot that will accept one -- which silently poisons a handler like
                    # ``lambda f=fmt: ...``: it looks zero-argument but takes one, so
                    # `f` arrives as False and the handler crashes the whole process
                    # (an exception inside a Qt slot aborts, it doesn't just log). The
                    # wrapper swallows the flag so no item author has to know this.
                    action.triggered.connect(lambda _checked=False, h=item.handler: h())
        if item.tip:
            action.setToolTip(item.tip)
        menu.addAction(action)


def build(window, *, model_choices, scale_choices) -> Menus:
    """Build the whole menu bar for ``window`` and return the parts it keeps.

    ``model_choices`` and ``scale_choices`` are passed in rather than imported so this
    module doesn't depend on the window's module -- which depends on this one.
    """
    bar = window.menuBar()

    file_menu = bar.addMenu("&File")
    add_items(window, file_menu, [
        Item("New Project…", window._new_project),
        Item("Open Folder…", window._open_folder),
    ])
    # Recent submenus are rebuilt on every show, so they can't be declared as items.
    open_recent = file_menu.addMenu("Open &Recent")
    open_recent.aboutToShow.connect(window._populate_open_recent)
    add_items(window, file_menu, [
        SEPARATOR,
        Item("&Save", window.editor.save_current, shortcut="Ctrl+S"),
        Item("Save A&ll", window.editor.save_all, shortcut="Ctrl+Shift+S"),
        SEPARATOR,
        Item("E&xit", window.close),
    ])

    # Edit: navigating your own text. Separate from File (which is about the files
    # themselves) and from Reversing (which is about someone else's *program*).
    add_items(window, bar.addMenu("&Edit"), [
        Item("&Find in Project…", window._find_in_project, shortcut="Ctrl+F",
             tip="Search every text file in the project; results go to Output"),
        Item("&Go to Line…", window._goto_line_dialog, shortcut="Ctrl+G"),
    ])

    add_items(window, bar.addMenu("&Build"), [
        Item("Build && Debug", window._build_and_debug, shortcut="F5",
             tip="Build and run with breakpoints active"),
        Item("Build && Run", window._build_and_run, shortcut="Ctrl+F5",
             tip="Build and run without debugging (ignore breakpoints)"),
    ])

    # Loading someone else's snapshot/tape has nothing to do with building your own
    # project, so it gets its own menu rather than sharing Build's. One item per format,
    # generated from media.FORMATS -- see there for why, and for how to add one.
    load_menu = bar.addMenu("&Load")
    tips = {
        media.TAPE: 'Insert the tape, then LOAD "" from BASIC',
        media.DISK: "Mount a TR-DOS disk — implies a Pentagon, and switches to one",
        media.SNAPSHOT: "Restore a machine mid-run — it resumes immediately",
    }
    previous_kind = None
    for fmt in media.FORMATS:
        if previous_kind is not None and fmt.kind != previous_kind:
            load_menu.addSeparator()  # tapes and snapshots are different things
        previous_kind = fmt.kind
        add_items(window, load_menu, [
            Item(fmt.menu_label, lambda f=fmt: window._load_format_dialog(f), tip=tips[fmt.kind]),
        ])
    load_menu.addSeparator()
    load_recent = load_menu.addMenu("Load &Recent")
    load_recent.aboutToShow.connect(window._populate_load_recent)

    # The deck itself, under the menu that puts tapes into it. These are only useful
    # once a tape is inserted, and they matter most when Fast Load is off: without the
    # trap the machine loads by listening to real pulses, which is slow, audible, and
    # the only thing a game's own turbo loader will accept.
    load_menu.addSeparator()
    add_items(window, load_menu.addMenu("&Tape Deck"), [
        Item("&Fast Load", window._set_fast_load, checkable=True, checked=True,
             tip="Intercept the ROM loader and deliver each block instantly. "
                 "Turn off to load at real tape speed, with stripes and sound"),
        Item("Tape &Sound", window._set_tape_audible, checkable=True, checked=True,
             tip="Let the tape signal reach the speaker, as it does on real hardware"),
        SEPARATOR,
        Item("&Play", window._tape_play, tip="Start the motor now, without waiting to be read"),
        Item("S&top", window._tape_stop),
        Item("&Rewind", window._tape_rewind, tip="Back to the first block"),
        SEPARATOR,
        Item("&Eject", window._eject_tape),
    ])

    # The disk drives, beside the deck for the same reason: these operate the medium you
    # already mounted rather than choosing a new one. Only a Pentagon has them, and
    # mounting a disk on anything else switches to one (see MainWindow._load_disk).
    add_items(window, load_menu.addMenu("&Disk Drive"), [
        Item("Mount in Drive &B…", lambda: window._mount_disk_dialog(1),
             tip="Drive A is where Load TRD/SCL puts a disk; this is the second drive"),
        SEPARATOR,
        Item("&Write Protect", window._set_disk_write_protect, checkable=True, checked=True,
             tip="On by default — untick it for the one disk you mean to write to"),
        Item("&Save Disk As…", window._save_disk_as,
             tip="Write the mounted image back out as a .trd, including anything the "
                 "machine has saved onto it"),
        SEPARATOR,
        Item("E&ject Disk", window._eject_disk),
    ])

    model_actions = _build_model_menu(window, model_choices)

    # Disassembly: the panel and where it points. Its own menu rather than a line in
    # View, because "show the panel" and "navigate it" belong together.
    add_items(window, bar.addMenu("D&isassembly"), [
        Item("Show Disassembly", action=window._disasm_dock.toggleViewAction()),
        SEPARATOR,
        Item("Go to PC", window._disasm_goto_pc,
             tip="Re-centre on the program counter and keep following it"),
        Item("Go to Address…", window._disasm_goto_address),
        Item("Go to Label…", window._disasm_goto_label,
             tip="Jump to one of your own labels from the last build"),
        SEPARATOR,
        Item("Show Call Stack", action=window._callstack_dock.toggleViewAction()),
    ])

    # Breaks: conditions attached to the gutter breakpoints, so a routine called ten
    # thousand times a frame can stop on the one call that misbehaves.
    add_items(window, bar.addMenu("&Breaks"), [
        Item("Set Breakpoint Condition…", window._set_breakpoint_condition,
             tip="Stop at an address only when an expression is true"),
        Item("Run to Cursor", window._run_to_cursor, shortcut="Ctrl+F10",
             tip="Resume, stopping at the line the caret is on (Ctrl+F10)"),
        Item("Run to Address…", window._run_to_address),
        Item("List Conditions", window._list_breakpoint_conditions),
        SEPARATOR,
        Item("Clear All Conditions", window._clear_breakpoint_conditions),
    ])

    # Watch: pause when a value or a port is touched, as opposed to a breakpoint, which
    # pauses when execution *reaches* somewhere.
    add_items(window, bar.addMenu("&Watch"), [
        Item("Watch Memory Write…", lambda: window._watch_memory(write=True),
             tip="Pause when the program writes to an address"),
        Item("Watch Memory Read…", lambda: window._watch_memory(write=False),
             tip="Pause when the program reads an address"),
        Item("Watch Port (OUT)…", lambda: window._watch_port(write=True),
             tip="Pause when the program writes to a port"),
        Item("Watch Port (IN)…", lambda: window._watch_port(write=False),
             tip="Pause when the program reads a port"),
        SEPARATOR,
        Item("Clear All Watchpoints", window._clear_watchpoints),
    ])

    # Reversing: understanding somebody else's program -- questions about the whole of it
    # rather than about the machine's current state, which is what Breaks and Watch are for.
    # The memory->sources dumper lives here because it *consumes* these results: coverage
    # decides what it disassembles, and the same honesty applies to its output.
    add_items(window, bar.addMenu("&Reversing"), [
        Item("Find Bytes…", lambda: window._find_in_memory(as_text=False),
             tip="Search memory for a hex byte sequence"),
        Item("Find Text…", lambda: window._find_in_memory(as_text=True)),
        Item("Cross-references…", window._cross_references,
             tip="What calls, jumps to, reads or writes an address?"),
        SEPARATOR,
        # The two halves of recovering a program, adjacent and in order, because the
        # dependency between them is otherwise invisible: the dump is only as good as
        # what was recorded, and nothing about a "Dump" item three groups below a
        # "Record Coverage" checkbox says so. Trace has nothing to do with dumping and
        # sits apart from them for that reason.
        Item("1. Record What Runs", window._set_coverage, checkable=True,
             tip="Mark every address the CPU executes. Turn this on, exercise the "
                 "program, then dump — what ran becomes disassembly, the rest stays data"),
        Item("2. Dump to Project…", window._dump_to_project,
             tip="Turn the running program's RAM into a buildable, debuggable project"),
        Item("Show What Ran", window._show_coverage,
             tip="The recorded addresses, collapsed into ranges"),
        SEPARATOR,
        Item("Record Trace", window._set_trace, checkable=True,
             tip="A rolling log of the last few thousand instructions — for 'how did I "
                 "get here?' at a breakpoint. Not used by the dumper"),
        Item("Show Trace", window._show_trace),
    ])

    # Compression: optional addons a project can opt into. Nothing is added to a project
    # until you ask, so a project that compresses nothing carries nothing.
    add_items(window, bar.addMenu("&Compression"), [
        Item("Add ZX0", lambda: window._add_addon("zx0", "ZX0"),
             tip="Copy the ZX0 decompressor into the open project"),
    ])

    _build_view_menu(window, bar, scale_choices)

    # Top-level "Settings" in the menu bar, alongside File and View (opens directly).
    bar.addAction("Settings").triggered.connect(window._open_settings)

    return Menus(open_recent=open_recent, load_recent=load_recent, model_actions=model_actions)


def _build_model_menu(window, model_choices) -> dict[str, QAction]:
    """Top-level Model menu: switch the emulated machine at any time.

    A project still declares its target model (and opening one switches to it), but the
    machine is not *owned* by the project -- you often want to try a tape or a snapshot on
    the other model without creating a project at all. These are radio items reflecting
    the live machine, which is why the window keeps them: see ``MainWindow.set_machine``.
    """
    from zxemu_ui.machine_factory import machine_model

    menu = window.menuBar().addMenu("&Model")
    group = QActionGroup(window)
    group.setExclusive(True)
    actions: dict[str, QAction] = {}
    for label, model in model_choices:
        action = QAction(label, window, checkable=True)
        action.setChecked(model == machine_model(window.machine))
        action.triggered.connect(lambda _checked, m=model: window._switch_model(m))
        group.addAction(action)
        menu.addAction(action)
        actions[model] = action
    return actions


def _build_view_menu(window, bar, scale_choices) -> None:
    """View: how the IDE itself looks -- text size, which panels show, dock layout."""
    view_menu = bar.addMenu("&View")

    scale_menu = view_menu.addMenu("Interface scale")
    scale_group = QActionGroup(window)
    scale_group.setExclusive(True)
    for label, scale in scale_choices:
        action = QAction(label, window, checkable=True)
        action.setChecked(scale == 1.0)
        action.triggered.connect(lambda _checked, s=scale: window._set_interface_scale(s))
        scale_group.addAction(action)
        scale_menu.addAction(action)

    special = QAction("Show special characters", window, checkable=True)
    special.setChecked(bool(window.settings.get("show_special", False)))
    window.editor.set_show_special(special.isChecked())  # apply the saved preference
    special.toggled.connect(window._set_show_special)
    view_menu.addAction(special)

    view_menu.addSeparator()
    for dock in window._all_docks:
        view_menu.addAction(dock.toggleViewAction())  # show/hide each panel
    add_items(window, view_menu, [
        SEPARATOR,
        Item("Save layout", window._save_layout),
        Item("Reset layout", window._reset_layout),
    ])
