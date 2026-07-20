"""A folder-based project and its ``zxide.json`` manifest.

A zxide project is just a folder on disk (VSCode-style) with a small manifest at
its root recording the project name, the main source file, and the per-project
build settings. Opening a project points the file tree at the folder; creating one
scaffolds the folder, the manifest, and a starter ``main.asm`` for you to fill in.

The manifest is intentionally tiny and human-editable -- machine-wide settings
(like where sjasmplus lives) live in the app Settings, while what's here is what
belongs *to the project*.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

MANIFEST_NAME = "zxide.json"

# Text files we open in the editor; anything else (bmp/bin/pt3...) is an asset.
TEXT_SUFFIXES = {".asm", ".s", ".z80", ".z80asm", ".inc", ".i", ".txt", ".md", ".json", ".cfg", ".def"}

# The starter template scaffolded into a new project (a buildable 48K demo).
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates" / "project48"

# Default sjasmplus invocation for a new project. {main}/{output} are filled in per
# build. sjasmplus writes the snapshot itself via a SAVESNA directive in the source
# (there is no --sna flag); --fullpath makes error messages carry the full path.
# This is a PER-PROJECT default stored in the manifest, so each project can differ.
DEFAULT_BUILD_ARGS = ["--fullpath", "{main}"]


def default_manifest(name: str) -> dict:
    return {
        "name": name,
        "main": "main.asm",
        "build": {
            "args": list(DEFAULT_BUILD_ARGS),
            "output": "main.sna",  # matches the SAVESNA path in the template
        },
    }


class Project:
    """A project rooted at a folder, backed by a ``zxide.json`` manifest."""

    def __init__(self, folder: str | Path):
        self.folder = Path(folder)

    @property
    def manifest_path(self) -> Path:
        return self.folder / MANIFEST_NAME

    @property
    def name(self) -> str:
        return self.load_manifest().get("name", self.folder.name)

    def load_manifest(self) -> dict:
        try:
            return json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return default_manifest(self.folder.name)

    def save_manifest(self, manifest: dict) -> None:
        self.manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    @classmethod
    def create(cls, folder: str | Path, name: str | None = None) -> "Project":
        """Scaffold a new project from the 48K template, plus its manifest.

        Copies the template's source files (a buildable visible demo) into the
        folder without clobbering anything already there, then writes zxide.json.
        """
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        name = name or folder.name
        for source in TEMPLATE_DIR.iterdir():
            if source.is_file():
                destination = folder / source.name
                if not destination.exists():
                    shutil.copy(source, destination)
        project = cls(folder)
        project.save_manifest(default_manifest(name))
        return project


def is_text_file(path: str | Path) -> bool:
    return Path(path).suffix.lower() in TEXT_SUFFIXES
