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


def default_settings() -> dict:
    return {
        "assembler_path": detect_assembler(),
        "last_project": "",
        "show_special": False,  # editor: render whitespace markers
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
