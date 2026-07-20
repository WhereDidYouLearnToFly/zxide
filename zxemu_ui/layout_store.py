"""Saving and restoring the dock layout to a local JSON file (no registry).

The file, ``layout.json``, holds two things:

  * ``"state"`` -- Qt's own dock-layout blob (``QMainWindow.saveState``), base64
    encoded. This is what faithfully captures *everything*: panels moved to new
    positions, tabbed together, floated, hidden, and their sizes. Restoring by hand
    can't rebuild Qt's nested splitter tree, so we let Qt do it.
  * ``"docks"`` -- a plain, human-readable summary of each dock (area, size,
    visibility, floating), so you can open the file and see what was saved.

Restore uses the ``"state"`` blob; the summary is for your eyes. Older files that
predate the blob (just the flat dock summary) still load via a manual fallback.
"""

from __future__ import annotations

import json
from pathlib import Path

from PyQt5.QtCore import QByteArray, QRect, Qt

_AREA_TO_NAME = {
    Qt.LeftDockWidgetArea: "left",
    Qt.RightDockWidgetArea: "right",
    Qt.TopDockWidgetArea: "top",
    Qt.BottomDockWidgetArea: "bottom",
    Qt.NoDockWidgetArea: "none",
}
_NAME_TO_AREA = {v: k for k, v in _AREA_TO_NAME.items()}


def capture(window, docks) -> dict:
    """A readable summary of each dock's location, size, visibility and floating state."""
    summary = {}
    for dock in docks:
        geometry = dock.geometry()
        summary[dock.objectName()] = {
            "visible": dock.isVisible(),
            "floating": dock.isFloating(),
            "area": _AREA_TO_NAME.get(window.dockWidgetArea(dock), "right"),
            "width": geometry.width(),
            "height": geometry.height(),
            "x": dock.x(),
            "y": dock.y(),
        }
    return summary


def save(path: str | Path, window, docks) -> Path:
    """Write Qt's full dock state (for exact restore) plus a readable summary."""
    path = Path(path)
    data = {
        "state": bytes(window.saveState().toBase64()).decode("ascii"),
        "docks": capture(window, docks),
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def load(path: str | Path) -> dict | None:
    """Read the layout file back, or None if it's missing/unreadable."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def apply(window, docks_by_name: dict, data: dict) -> None:
    """Restore the layout.

    Qt's state blob nails the *arrangement* -- panels moved to new areas, tabbed,
    floated, hidden -- but its restored *sizes* can be off after the window
    maximises. So we let restoreState set the arrangement, then reinforce the panel
    sizes explicitly with resizeDocks (which places absolute sizes reliably). Older
    files without the blob fall back to the summary-only path.
    """
    summary = data.get("docks", data) if isinstance(data, dict) else {}
    state = data.get("state") if isinstance(data, dict) else None
    if state:
        window.restoreState(QByteArray.fromBase64(state.encode("ascii")))
    else:
        _apply_summary_arrangement(window, docks_by_name, summary)
    _reinforce_sizes(window, docks_by_name, summary)


def _apply_summary_arrangement(window, docks_by_name: dict, summary: dict) -> None:
    """Floating/visibility from the summary (fallback when there's no state blob)."""
    for name, info in summary.items():
        dock = docks_by_name.get(name)
        if dock is None:
            continue
        if info["floating"]:
            dock.setFloating(True)
            dock.setGeometry(QRect(info["x"], info["y"], info["width"], info["height"]))
        elif dock.isFloating():
            window.addDockWidget(_NAME_TO_AREA.get(info["area"], Qt.RightDockWidgetArea), dock)
            dock.setFloating(False)
        dock.setVisible(info["visible"])


def _reinforce_sizes(window, docks_by_name: dict, summary: dict) -> None:
    """Re-apply saved sizes to docked, visible panels: widths, then heights."""
    docked = [
        (docks_by_name[name], info)
        for name, info in summary.items()
        if docks_by_name.get(name) is not None and not info["floating"] and info["visible"]
    ]
    if docked:
        group = [dock for dock, _ in docked]
        window.resizeDocks(group, [info["width"] for _, info in docked], Qt.Horizontal)
        window.resizeDocks(group, [info["height"] for _, info in docked], Qt.Vertical)
