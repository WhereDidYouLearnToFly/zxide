"""Search every text file in a project for a string.

Deliberately Qt-free, like the rest of ``workspace/``: what "search a project" means --
which files count, what a hit is -- is project knowledge, not UI, and keeping it here
makes it testable without a running window.

The awkward part of a project-wide search is not the matching, it is deciding what
*not* to read. A zxide project folder holds sources, but also imported assets (.bmp,
.pt3, .bin), build output (.sna, .sld, .bmp screenshots), and whatever else the
developer keeps next to them. Reading a 131 KB snapshot as text to look for "player"
wastes time and produces line numbers that mean nothing, so only the suffixes the
editor itself can open are searched (``project.TEXT_SUFFIXES``), and generated files
are skipped by name.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from zxemu_ui.workspace.project import TEXT_SUFFIXES

# Files that exist only because a build wrote them: searching them turns up your own
# generated code as if you had written it, which is noise in every case we could think of.
GENERATED_NAMES = {"assets_generated.asm"}

# Same reasoning, by name pattern rather than exact name. A dumped SLD is a *listing* of
# where every label ended up, so every symbol you search for appears in it two or three
# more times, with absolute paths and no useful line to jump to. (`.sld` itself is already
# skipped for not being an editable suffix; it is the `.sld.txt` dumps that leak through.)
GENERATED_ENDINGS = (".sld.txt",)

# Folders never worth walking into.
SKIPPED_DIRS = {".git", "__pycache__", ".vscode", "screenshots"}

DEFAULT_RESULT_LIMIT = 500


@dataclass(frozen=True)
class SearchHit:
    """One matching line: where it is, and enough context to show it in a list."""

    path: Path          # absolute, so the editor can open it directly
    relative: str       # project-relative, for display
    line: int           # 1-based, matching what the editor and the SLD use
    text: str           # the whole matching line, stripped
    column: int         # 0-based offset of the match within the raw line


def search_project(
    folder: str | Path,
    query: str,
    *,
    case_sensitive: bool = False,
    limit: int = DEFAULT_RESULT_LIMIT,
) -> tuple[list[SearchHit], bool]:
    """Find ``query`` in every searchable file under ``folder``.

    Returns ``(hits, truncated)`` -- ``truncated`` is True when the limit cut the list
    short, so the caller can say so rather than quietly showing a partial answer.
    Unreadable files are skipped: a search shouldn't fail because one file is locked or
    holds bytes that aren't text.
    """
    folder = Path(folder)
    if not query:
        return [], False
    needle = query if case_sensitive else query.lower()

    hits: list[SearchHit] = []
    for path in _searchable_files(folder):
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for number, line in enumerate(content.splitlines(), start=1):
            column = (line if case_sensitive else line.lower()).find(needle)
            if column < 0:
                continue
            if len(hits) >= limit:
                return hits, True
            hits.append(SearchHit(
                path=path,
                relative=str(path.relative_to(folder)),
                line=number,
                text=line.strip(),
                column=column,
            ))
    return hits, False


def _searchable_files(folder: Path):
    """Every file worth reading as text, in a stable (sorted) order."""
    for path in sorted(folder.rglob("*")):
        if not path.is_file():
            continue
        name = path.name.lower()
        if name in GENERATED_NAMES or name.endswith(GENERATED_ENDINGS):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if any(part in SKIPPED_DIRS for part in path.relative_to(folder).parts[:-1]):
            continue
        yield path
