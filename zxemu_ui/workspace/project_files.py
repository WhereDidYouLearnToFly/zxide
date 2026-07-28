"""Removing a file from a project, and the path arithmetic that goes with it.

Deleting a file out of a project folder is not one operation, it is three: the file
itself, the manifest assets sourced from it, and the converted bytes those assets left in
the build cache. Doing only the first leaves a build that fails on a source it can no
longer read, and a Design-mode map still drawing a rectangle for something that is gone.

None of that reasoning is about windows, so none of it lives in one. ``MainWindow`` keeps
what genuinely is UI -- asking whether you meant it, closing the editor tab, writing to
the log -- and calls in here for the rest, which is then testable with a ``tmp_path`` and
no ``QApplication`` at all. That is the same split the rest of the workspace package
follows (``builder`` shells out and reports; the window turns the report into log lines).

The path helpers are here rather than beside their callers because *comparing project
paths correctly* is a single problem with a single answer, and it had started to grow two:
the manifest stores a relative ``levels\\hero.zx8x8`` while Qt hands back an absolute
``C:/project/levels/hero.zx8x8``, and on Windows either may differ in case. Everything
that has to decide "is this the same file" -- the tree's asset badges, and deletion's
"which assets go with this folder" -- now asks the same function.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from zxemu_core.assets.manifest import AssetEntry
from zxemu_ui.workspace import asset_build


def normalise(path: str | Path) -> str:
    """A path in the one form comparisons can use.

    ``normcase`` + ``normpath`` collapses separator and case differences without touching
    the filesystem -- unlike ``resolve()``, which stats, and which the project tree would
    be calling on every row of every repaint.
    """
    return os.path.normcase(os.path.normpath(str(path)))


def is_within(target: Path, path: Path) -> bool:
    """Whether ``path`` *is* ``target`` or lives inside it (``target`` being a folder)."""
    target_key, path_key = normalise(target), normalise(path)
    return path_key == target_key or path_key.startswith(target_key + os.sep)


def assets_under(project, target: Path) -> list[AssetEntry]:
    """Every manifest asset whose source file is ``target`` or lives inside it.

    A ``sprite_sequence`` names several files; losing any one of them leaves an asset that
    can no longer be converted, so the whole entry matches rather than a silently broken
    one staying behind.
    """
    matched = []
    for entry in project.assets():
        sources = entry.source if isinstance(entry.source, list) else [entry.source]
        if any(is_within(target, project.folder / source) for source in sources):
            matched.append(entry)
    return matched


def count_contents(folder: Path) -> int:
    """How many files and folders are inside ``folder``, at any depth.

    Only ever used to tell you what you are about to lose before you lose it.
    """
    return sum(1 for _ in folder.rglob("*"))


class RenameProblem(ValueError):
    """Why a rename cannot go ahead, in a sentence for the user.

    Ordinary refusals, not bugs: a name with a slash in it, a name already taken, an empty
    one. The caller shows the text and the user tries again.
    """


def check_rename(target: Path, new_name: str) -> Path:
    """Validate a new name and return the path it would become. Raises ``RenameProblem``.

    Separate from ``rename`` so a dialog can check before committing, and so every refusal
    reads the same whether it came from typing or from a script. A *name* is wanted here,
    not a path: renaming is not moving, and accepting ``../elsewhere/x`` would quietly turn
    one into the other.
    """
    cleaned = (new_name or "").strip()
    if not cleaned:
        raise RenameProblem("A name is required.")
    if cleaned in (".", ".."):
        raise RenameProblem("That is not a name.")
    if os.sep in cleaned or (os.altsep and os.altsep in cleaned):
        raise RenameProblem("A name cannot contain a path separator -- renaming does not move a file.")
    if cleaned == target.name:
        raise RenameProblem("That is already its name.")

    destination = target.with_name(cleaned)
    # Case-only renames are a legitimate thing to want and look like a collision on
    # Windows, where the filesystem says the destination exists because it *is* the source.
    if destination.exists() and normalise(destination) != normalise(target):
        raise RenameProblem("“{}” already exists here.".format(cleaned))
    return destination


def rename(project, target: Path, new_name: str) -> list[AssetEntry]:
    """Rename a file or folder and repoint any manifest assets at it. Returns those assets.

    The manifest stores each asset's *source path*, so renaming the file underneath one and
    stopping there leaves a project whose next build fails on a file it can no longer find.
    Folders carry their whole subtree with them, so every asset sourced from inside one has
    to move too.

    Two things deliberately do not change. The asset's **symbol** is what the assembler
    sees, so renaming a file is not allowed to silently rename a label somebody's source
    already refers to. The **build cache** is keyed by that symbol, so it stays valid --
    the bytes did not change, only where they came from.

    The disk rename happens first: if it fails there is nothing to undo, whereas a manifest
    updated ahead of a failed rename would point at a file that was never created.
    """
    destination = check_rename(target, new_name)
    affected = assets_under(project, target)

    target.rename(destination)

    for entry in affected:
        was_list = isinstance(entry.source, list)
        sources = entry.source if was_list else [entry.source]
        moved = [_moved_source(project, source, target, destination) for source in sources]
        project.set_asset_source(entry.id, moved if was_list else moved[0])
    return affected


def _moved_source(project, source: str, target: Path, destination: Path) -> str:
    """Where one manifest source ends up after ``target`` became ``destination``.

    Handles both cases in one place because a folder rename moves things *inside* it: the
    renamed thing itself becomes the destination, while anything beneath keeps its position
    within the subtree. A sprite sequence naming five frames in a renamed folder needs all
    five repointed, not the folder mentioned once.
    """
    absolute = Path(project.folder) / source
    if normalise(absolute) == normalise(target):
        return _project_relative(project, destination)
    return _project_relative(project, destination / absolute.relative_to(target))


def _project_relative(project, path: Path) -> str:
    """A path as the manifest stores it: relative to the project folder where possible."""
    try:
        return str(path.relative_to(Path(project.folder)))
    except ValueError:
        return str(path)


def delete(project, target: Path) -> list[AssetEntry]:
    """Remove ``target`` from the project entirely. Returns the assets that went with it.

    Order matters: the manifest is updated *before* the bytes disappear, so an interrupted
    delete leaves a project that is merely missing an asset rather than one pointing at a
    file that no longer exists. Folders go recursively -- deleting one from a file tree
    plainly means the things in it too.

    Raises ``OSError`` if the file or folder cannot be removed; the caller reports it.
    """
    removed = assets_under(project, target)
    for entry in removed:
        project.remove_asset(entry.id)
        # Otherwise the stale converted bytes outlive the asset that produced them, and
        # the next auto-locate reserves space for something that no longer exists.
        asset_build.cache_path(project, entry.symbol).unlink(missing_ok=True)

    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    return removed
