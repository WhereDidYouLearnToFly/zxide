"""The project tree's model: the folder on disk, with manifest assets badged by kind.

A project folder is a plain directory listing, and a stock ``QFileSystemModel`` shows it
as one -- every file with the same generic icon. But half the files in a zxide project are
not just files: they are *assets*, recorded in ``zxide.json``, converted at build time and
placed somewhere in the machine's memory. Which of them are is invisible in a plain
listing, and the distinction matters constantly:

    hero.zx8x8     ← an asset: converted, placed, addressable from code as `hero`
    stray.zx8x8    ← the same kind of file, sitting in the folder, in no build

Nothing about the two names tells them apart, and finding out otherwise means opening the
manifest or clicking through the Inspector. So this model overlays what the manifest
knows onto the listing: the asset's kind colour and glyph as its icon (the same
``asset_icons`` table the Inspector badge and the Design-mode memory map use, so one
asset looks like itself everywhere), and a tooltip naming its symbol and kind.

The overlay is deliberately a *decoration*, not a filter. Non-asset files stay visible and
keep their normal icons -- a project is a folder you can put anything in, and a tree that
hid what it didn't recognise would be lying about what is on disk.

The asset map is rebuilt on demand rather than watched, because every path that changes it
already runs through ``MainWindow`` (opening a project, creating an asset, importing one,
deleting a file) and can say so. Re-reading the manifest on every repaint would be the
alternative, and the tree repaints a lot.
"""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFileSystemModel

from zxemu_core.assets.manifest import AssetEntry, AssetKind
from zxemu_ui.asset_icons import icon_for_kind
from zxemu_ui.workspace.project_files import normalise

ICON_SIZE = 16


class ProjectFilesModel(QFileSystemModel):
    """A file listing that knows which of its files the open project calls assets."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project = None
        self._assets: dict[str, AssetEntry] = {}  # normalised absolute path -> its entry
        self._icons: dict[AssetKind, object] = {}

    # --- what the manifest says --------------------------------------------------

    def set_project(self, project) -> None:
        self._project = project
        self.refresh_assets()

    def refresh_assets(self) -> None:
        """Re-read the manifest and repaint. Called whenever assets are added or removed."""
        self._assets = {}
        if self._project is not None:
            for entry in self._project.assets():
                sources = entry.source if isinstance(entry.source, list) else [entry.source]
                for source in sources:
                    self._assets[normalise(self._project.folder / source)] = entry
        # Every row's decoration may have changed; the model has no cheaper way to say so.
        self.layoutChanged.emit()

    def asset_for(self, path: str | Path) -> AssetEntry | None:
        """The manifest entry backing ``path``, or None if that file isn't an asset.

        Also the answer to "would double-clicking this open an editor" -- which is why it
        is public rather than folded into :meth:`data`.
        """
        return self._assets.get(normalise(path))

    def _icon(self, kind: AssetKind):
        # Icons are drawn with QPainter, so they are cached per kind rather than redrawn
        # for every row on every repaint.
        if kind not in self._icons:
            self._icons[kind] = icon_for_kind(kind, ICON_SIZE)
        return self._icons[kind]

    # --- the overlay ---------------------------------------------------------------

    def data(self, index, role=Qt.DisplayRole):  # noqa: N802
        if index.isValid() and index.column() == 0 and role in (Qt.DecorationRole, Qt.ToolTipRole):
            entry = self._assets.get(normalise(self.filePath(index)))
            if entry is not None:
                if role == Qt.DecorationRole:
                    return self._icon(entry.kind)
                return "{} — {} asset".format(entry.symbol, entry.kind.value)
        return super().data(index, role)
