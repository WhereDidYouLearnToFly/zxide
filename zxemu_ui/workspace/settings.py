"""App-wide (per-machine) settings, auto-created with sensible defaults on first run.

Stored as a plain ``settings.json`` next to the app (no registry), so it's easy to
read and delete. The point is zero-config: the first time zxide runs it writes the
file and tries to locate the sjasmplus assembler on PATH, so the build pipeline
works out of the box.

Scope note: only things that are the *same for every project* live here -- where
sjasmplus is installed, UI preferences, the last-opened project. Per-project build
config (arguments, output) lives in each project's ``zxide.json`` manifest instead.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path


def detect_assembler() -> str:
    """Best effort: find sjasmplus on PATH (honours .exe on Windows). '' if absent."""
    return shutil.which("sjasmplus") or ""


#: Where to look for a tracker player binary near the open project, before falling back to
#: the ones zxide ships (``zxemu_core/players``). Project first, deliberately: a project
#: that carries its own player wants *that* one, which may be a version its music needs.
PLAYER_SEARCH_DIRS = (".", "music", "players", "tools", "lib")


def bundled_player_dir():
    """The players shipped with zxide, so raw .pt2/.pt3 modules play with no setup at all.

    Third-party binaries under their own terms, exactly like the ROM images beside them --
    see ``zxemu_core/players/LICENSE-players.txt``. Kept last in the search order so a
    player sitting next to the project always wins.
    """
    from pathlib import Path as _Path

    import zxemu_core

    return _Path(zxemu_core.__file__).resolve().parent / "players"


def detect_tracker_players(project_dir, extra_dir="") -> list:
    """Player binaries for raw tracker data, identified by *shape* rather than by name.

    A candidate is accepted only if it is laid out as a player and its own header agrees
    with its length (see ``zxemu_core.sound.tracker_player.identify_player``) -- which is a
    strong enough check to scan folders of arbitrary ``.bin`` files safely. Name matching
    would be both looser and more brittle: these things are called ``pt3_c000.bin``,
    ``PT3.BIN``, ``player.bin`` and worse.

    Search order is chosen-folder, then project, then bundled: the more specific the
    location, the more likely it is the one somebody meant.
    """
    from zxemu_core.sound.tracker_player import identify_player

    found = []
    seen = set()
    for directory in _player_dirs(project_dir, extra_dir):
        if not directory.is_dir():
            continue
        for candidate in sorted(directory.glob("*.bin")):
            resolved = str(candidate.resolve())
            if resolved in seen:
                continue
            seen.add(resolved)
            try:
                data = candidate.read_bytes()
            except OSError:
                continue  # unreadable is simply "not a player we can use"
            player = identify_player(data, path=resolved)
            if player is not None:
                found.append(player)
    return found


def _player_dirs(project_dir, extra_dir):
    if extra_dir:
        yield Path(extra_dir)
    if project_dir:
        base = Path(project_dir)
        for name in PLAYER_SEARCH_DIRS:
            yield base / name
    yield bundled_player_dir()  # last: whatever the project has takes precedence


RECENT_LIMIT = 10  # how many entries the Open Recent / Load Recent menus remember


def default_settings() -> dict:
    return {
        "assembler_path": detect_assembler(),
        "last_project": "",
        "show_special": False,  # editor: render whitespace markers
        # Kempston Mouse interface: off by default, same reasoning as the tape/disk
        # write-protect default -- software that probes for a mouse and finds one
        # unexpectedly present can behave differently than it would on real bare
        # hardware, so this stays an opt-in rather than something every project
        # silently gets. Fitting one also has a cost beyond the probe: the interface
        # decodes only four address lines, so it answers every port with A0 set and
        # A5 clear (see zxemu_core/mouse.py) -- a real expansion-bus device sitting
        # on its neighbours, and not something to hand out by default.
        "kempston_mouse_enabled": False,
        # The Kempston Joystick, off for the same reasons and additionally exclusive with
        # the mouse above -- both interfaces answer port 0x1F, so only one can be fitted.
        "kempston_joystick_enabled": False,
        # The Next's MD 3-button mode: bits 7:6 (A and START) reach the port instead of
        # being masked off. Off by default because software written for a one-button stick
        # can read those bits as something else entirely.
        "kempston_joystick_extended": False,
        # Where to find a PT2/PT3 player binary for raw tracker modules, when the ones near
        # the project aren't the ones you meant. Empty = search the project only. zxide
        # bundles no player: see detect_tracker_players above for why.
        "tracker_player_dir": "",
        # Editor: hover an instruction for what it does, its cost and the flags it
        # disturbs. On by default -- it costs nothing until you point at something --
        # but it is the kind of help you stop needing, so it can be switched off.
        "instruction_help": True,
        "recent_projects": [],  # project folders, most-recent first (Open Recent menu)
        "recent_files": [],     # loaded .sna/.tap files, most-recent first (Load Recent menu)
        # Where the last tape/disk/snapshot came from. Media lives in a collection folder,
        # not in your project, so every Load dialog should reopen where you were rather
        # than sending you back to the project each time -- and one shared folder rather
        # than one per format, because a .tzx and a .trd usually sit side by side.
        "last_media_dir": "",
    }


class Settings:
    """Load ``settings.json`` (creating it with detected defaults if missing)."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data = self._load_or_create()

    def _load_or_create(self) -> dict:
        if self.path.exists():
            try:
                # Merge over defaults so new keys appear for old files.
                data = {**default_settings(), **json.loads(self.path.read_text(encoding="utf-8"))}
                return self._migrate(data)
            except (ValueError, OSError):
                pass
        data = default_settings()
        self._write(data)
        return data

    def _migrate(self, data: dict) -> dict:
        """Heal settings written by older versions."""
        # Build config moved to the per-project manifest; drop the old global copy
        # (which in early builds also held a bogus "--sna=" arg that sjasmplus rejects).
        if "build_args" in data:
            del data["build_args"]
            self._write(data)
        return data

    def _write(self, data: dict) -> None:
        try:
            self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass  # non-fatal: settings just won't persist

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def set(self, key: str, value) -> None:
        self.data[key] = value
        self._write(self.data)

    def push_recent(self, key: str, value: str, limit: int = RECENT_LIMIT) -> None:
        """Prepend ``value`` to a recent-list setting, de-duplicated and capped.

        Moving a re-used entry back to the front (rather than appending a duplicate)
        keeps the most recently touched item at the top of the menu.
        """
        items = [item for item in self.get(key, []) if item != value]
        items.insert(0, value)
        del items[limit:]
        self.set(key, items)

    def remove_recent(self, key: str, value: str) -> None:
        """Drop ``value`` from a recent-list setting (e.g. when the path is gone)."""
        items = [item for item in self.get(key, []) if item != value]
        self.set(key, items)
