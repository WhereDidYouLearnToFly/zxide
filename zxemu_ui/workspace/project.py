"""A folder-based project and its ``zxide.json`` manifest.

A zxide project is just a folder on disk (VSCode-style) with a small manifest at
its root recording the project name, the main source file, the per-project build
settings, and its imported assets. Opening a project points the file tree at the
folder; creating one scaffolds the folder, the manifest, and a starter ``main.asm``
for you to fill in.

The manifest is intentionally tiny and human-editable -- machine-wide settings
(like where sjasmplus lives) live in the app Settings, while what's here is what
belongs *to the project*.

The ``assets`` list records every imported asset as a plain dict (see
``zxemu_core.assets.manifest.AssetEntry`` for the shape) -- where its source file
lives, what kind of thing it is, what label the build should give it, and where in
memory it belongs, or ``"auto"`` to let the build's free-space search decide. This
class only ever reads/writes that list as data; the actual conversion (BMP -> Spectrum
bitmap, and so on) and memory placement live in ``zxemu_core.assets``/
``zxemu_core.memlayout``, kept separate so the manifest format doesn't need to change
just because a converter's internals do.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from zxemu_core.assets.manifest import AssetEntry, AssetKind

MANIFEST_NAME = "zxide.json"

# Text files we open in the editor; anything else (bmp/bin/pt3...) is an asset.
TEXT_SUFFIXES = {".asm", ".s", ".z80", ".z80asm", ".inc", ".i", ".txt", ".md", ".json", ".cfg", ".def"}

# The starter templates scaffolded into a new project, one per machine model (each a
# buildable visible demo). The model is chosen at New-Project time and recorded in the
# manifest, so opening a project later knows which machine to boot.
# Templates and addons are package *data*, so they live at the zxemu_ui root rather
# than beside this module -- hence parent.parent, not parent.
_TEMPLATE_ROOT = Path(__file__).resolve().parent.parent / "templates"
TEMPLATE_DIRS = {"48k": _TEMPLATE_ROOT / "project48", "128k": _TEMPLATE_ROOT / "project128"}
DEFAULT_MODEL = "48k"

# Optional addons: extra source files a project can opt into *after* creation, unlike
# the templates above which are scaffolded once at New-Project time. Keeping them out
# of the templates is the point -- a project only carries what it actually uses, which
# matters when every byte of a 48K is spoken for.
_ADDON_ROOT = Path(__file__).resolve().parent.parent / "addons"
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
        "assets": [],  # imported AssetEntry records -- see zxemu_core.assets.manifest
    }


def _sanitize_symbol(name: str) -> str:
    """A filename turned into a valid sjasmplus label: letters/digits/underscore, not digit-first."""
    sanitized = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not sanitized or not (sanitized[0].isalpha() or sanitized[0] == "_"):
        sanitized = f"asset_{sanitized}"
    return sanitized


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

    def assets(self) -> list[AssetEntry]:
        """Every imported asset recorded in the manifest, as :class:`AssetEntry` objects."""
        return [AssetEntry.from_dict(data) for data in self.load_manifest().get("assets", [])]

    def add_asset(
        self,
        source: str | list[str],
        kind: AssetKind,
        symbol: str | None = None,
        params: dict | None = None,
    ) -> AssetEntry:
        """Record a newly-imported asset, placement left as ``"auto"`` until placed.

        ``symbol`` is auto-derived from the source filename when omitted -- except for
        a list ``source`` (a ``sprite_sequence``'s multiple frame files), where there is
        no single filename to derive one from, so an explicit symbol is required.
        ``params`` carries whatever the kind needs beyond source/symbol/placement --
        frame size/layout/mask for sprites, ``first_char_code`` for fonts, and so on.
        """
        if symbol is None:
            if isinstance(source, list):
                raise ValueError("a sprite_sequence asset needs an explicit symbol (no single source filename)")
            symbol = _sanitize_symbol(Path(source).stem)
        asset_id = self._unique_asset_id(symbol)
        entry = AssetEntry(id=asset_id, source=source, kind=kind, symbol=symbol, params=dict(params or {}))
        manifest = self.load_manifest()
        manifest.setdefault("assets", []).append(entry.to_dict())
        self.save_manifest(manifest)
        return entry

    def _unique_asset_id(self, base: str) -> str:
        existing = {data["id"] for data in self.load_manifest().get("assets", [])}
        if base not in existing:
            return base
        suffix = 2
        while f"{base}_{suffix}" in existing:
            suffix += 1
        return f"{base}_{suffix}"

    def _update_asset(self, asset_id: str, update) -> None:
        manifest = self.load_manifest()
        assets = manifest.get("assets", [])
        for data in assets:
            if data["id"] == asset_id:
                update(data)
                break
        else:
            raise ValueError(f"no asset with id {asset_id!r}")
        manifest["assets"] = assets
        self.save_manifest(manifest)

    def set_asset_placement(self, asset_id: str, bank: str, offset: int) -> None:
        self._update_asset(asset_id, lambda data: data.__setitem__("placement", {"bank": bank, "offset": offset}))

    def set_asset_auto(self, asset_id: str) -> None:
        self._update_asset(asset_id, lambda data: data.__setitem__("placement", "auto"))

    def remove_asset(self, asset_id: str) -> None:
        manifest = self.load_manifest()
        assets = manifest.get("assets", [])
        filtered = [data for data in assets if data["id"] != asset_id]
        if len(filtered) == len(assets):
            raise ValueError(f"no asset with id {asset_id!r}")
        manifest["assets"] = filtered
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
