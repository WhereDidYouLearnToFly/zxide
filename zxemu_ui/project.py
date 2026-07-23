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

# The starter templates scaffolded into a new project, one per machine model (each a
# buildable visible demo). The model is chosen at New-Project time and recorded in the
# manifest, so opening a project later knows which machine to boot.
_TEMPLATE_ROOT = Path(__file__).resolve().parent / "templates"
TEMPLATE_DIRS = {"48k": _TEMPLATE_ROOT / "project48", "128k": _TEMPLATE_ROOT / "project128"}
DEFAULT_MODEL = "48k"

# Optional addons: extra source files a project can opt into *after* creation, unlike
# the templates above which are scaffolded once at New-Project time. Keeping them out
# of the templates is the point -- a project only carries what it actually uses, which
# matters when every byte of a 48K is spoken for.
_ADDON_ROOT = Path(__file__).resolve().parent / "addons"
ADDON_DIRS = {"zx0": _ADDON_ROOT / "zx0addon"}

# Default sjasmplus invocation for a new project. {main}/{output} are filled in per
# build. sjasmplus writes the snapshot itself via a SAVESNA directive in the source
# (there is no --sna flag); --fullpath makes error messages carry the full path.
# This is a PER-PROJECT default stored in the manifest, so each project can differ.
DEFAULT_BUILD_ARGS = ["--fullpath", "{main}"]


def default_manifest(name: str, model: str = DEFAULT_MODEL) -> dict:
    return {
        "name": name,
        "model": model,  # "48k" or "128k" -- which machine the emulator boots
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

    @property
    def model(self) -> str:
        """The machine model ("48k"/"128k"). Defaults to 48K for older manifests."""
        return self.load_manifest().get("model", DEFAULT_MODEL)

    def set_model(self, model: str) -> None:
        """Record a new machine model in the manifest, leaving everything else intact.

        Switching model from the Model menu writes through to here, so the choice
        survives closing and reopening the project rather than silently reverting to
        whatever the manifest still said.
        """
        manifest = self.load_manifest()
        manifest["model"] = model
        self.save_manifest(manifest)

    def add_addon(self, name: str) -> tuple[list[str], list[str]]:
        """Copy an addon's files into the project root. Returns (added, skipped) names.

        Existing files are never overwritten, so re-adding an addon is harmless and
        can't clobber a copy you have since edited -- the same no-clobber rule
        ``create`` uses when scaffolding a template.
        """
        added: list[str] = []
        skipped: list[str] = []
        for source in sorted(ADDON_DIRS[name].iterdir()):
            if not source.is_file():
                continue
            destination = self.folder / source.name
            if destination.exists():
                skipped.append(source.name)
            else:
                shutil.copy(source, destination)
                added.append(source.name)
        return added, skipped

    def load_manifest(self) -> dict:
        try:
            return json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return default_manifest(self.folder.name)

    def save_manifest(self, manifest: dict) -> None:
        self.manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    @classmethod
    def create(cls, folder: str | Path, name: str | None = None, model: str = DEFAULT_MODEL) -> "Project":
        """Scaffold a new project from the model's template, plus its manifest.

        Copies the chosen template's source files (a buildable visible demo) into the
        folder without clobbering anything already there, then writes zxide.json with
        the selected machine model.
        """
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        name = name or folder.name
        template_dir = TEMPLATE_DIRS.get(model, TEMPLATE_DIRS[DEFAULT_MODEL])
        for source in template_dir.iterdir():
            if source.is_file():
                destination = folder / source.name
                if not destination.exists():
                    shutil.copy(source, destination)
        project = cls(folder)
        project.save_manifest(default_manifest(name, model))
        return project


def is_text_file(path: str | Path) -> bool:
    return Path(path).suffix.lower() in TEXT_SUFFIXES
