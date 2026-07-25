"""Hand a path to the desktop's own file manager.

"Show in Explorer" is one line of code per platform and three different ideas of what
the argument means, so the command is built by a pure function (:func:`reveal_command`)
and run by a thin wrapper. That split is what makes it testable -- checking that Windows
gets ``explorer /select,`` and a file's own path, while Linux gets the *containing
folder*, needs no file manager to actually open.

Windows and macOS can both select the file within its folder; Linux has no portable way
to do that, so ``xdg-open`` is given the directory instead. Selecting the file is a nicety;
landing in the right folder is the part that matters.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def file_manager_name(platform: str | None = None) -> str:
    """What to call the file manager in a menu item, per platform."""
    platform = platform or sys.platform
    if platform.startswith("win"):
        return "Explorer"
    return "Finder" if platform == "darwin" else "File Manager"


FILE_MANAGER_NAME = file_manager_name()


def reveal_command(path: str | Path, platform: str | None = None) -> list[str]:
    """The argv that shows ``path`` in the platform's file manager.

    ``platform`` defaults to ``sys.platform`` and exists so tests can ask for another
    one. A directory is opened; a file is revealed *and selected* where the platform
    supports it.
    """
    path = Path(path)
    platform = platform or sys.platform
    if platform.startswith("win"):
        if path.is_dir():
            return ["explorer", str(path)]
        # The comma is not a typo and there is no space after it: explorer's /select
        # takes the file path glued on like this, and anything else opens My Documents.
        return ["explorer", f"/select,{path}"]
    if platform == "darwin":
        return ["open", "-R", str(path)] if path.is_file() else ["open", str(path)]
    folder = path if path.is_dir() else path.parent
    return ["xdg-open", str(folder)]


def reveal(path: str | Path) -> str | None:
    """Show ``path`` in the file manager. Returns None on success, else a message.

    Never raises: failing to open a file manager is a cosmetic disappointment, not
    something that should take the IDE down with it. Explorer is also cheerfully
    inconsistent about its exit code, which is why success isn't inferred from one.
    """
    path = Path(path)
    if not path.exists():
        return f"{path} no longer exists"
    try:
        subprocess.Popen(reveal_command(path))
    except (OSError, ValueError) as error:
        return f"could not open a file manager: {error}"
    return None
