"""The Settings dialog -- global (per-machine) and per-project build configuration.

Two groups, matching where the settings actually live:

  * Global -- the sjasmplus location. One install per machine, shared by every
    project; saved to the app Settings.
  * Project -- the build arguments and snapshot output for the *open* project.
    Saved to that project's ``zxide.json`` manifest, so each project can differ.

Both already have working defaults (sjasmplus auto-detected; the manifest seeded
when the project was created), so this dialog is only for overriding.
"""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from zxemu_ui.workspace.project import DEFAULT_BUILD_ARGS
from zxemu_ui.workspace.settings import detect_assembler


class SettingsDialog(QDialog):
    """Edit the global assembler path and the open project's build config."""

    def __init__(self, settings, project, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.project = project
        self.setWindowTitle("Settings")
        self.setMinimumWidth(720)
        self.resize(820, 300)

        layout = QVBoxLayout(self)
        layout.addWidget(self._build_global_group())
        layout.addWidget(self._build_project_group())

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # --- global (per-machine) --------------------------------------------------

    def _build_global_group(self) -> QGroupBox:
        group = QGroupBox("Global (this machine)")
        form = QFormLayout(group)

        self._assembler_edit = QLineEdit(self.settings.get("assembler_path", ""))
        detect_button = QPushButton("Detect")
        detect_button.setToolTip("Search PATH for sjasmplus")
        detect_button.clicked.connect(self._detect)
        browse_button = QPushButton("Browse…")
        browse_button.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self._assembler_edit, 1)
        row.addWidget(detect_button)
        row.addWidget(browse_button)
        form.addRow("Assembler (sjasmplus)", row)
        return group

    # --- per-project -----------------------------------------------------------

    def _build_project_group(self) -> QGroupBox:
        group = QGroupBox("Project")
        form = QFormLayout(group)

        if self.project is None:
            form.addRow(QLabel("Open a project to edit its build settings."))
            self._args_edit = None
            self._output_edit = None
            return group

        build = self.project.load_manifest().get("build", {})
        self._args_edit = QLineEdit(" ".join(build.get("args", DEFAULT_BUILD_ARGS)))
        self._output_edit = QLineEdit(build.get("output", "main.sna"))
        form.addRow("Build arguments", self._args_edit)
        form.addRow("Snapshot output", self._output_edit)
        hint = QLabel(
            "{main} = main source · {output} = snapshot path. sjasmplus writes the .sna "
            "via a SAVESNA directive in the source (there is no --sna flag)."
        )
        hint.setWordWrap(True)
        form.addRow("", hint)
        return group

    # --- actions ---------------------------------------------------------------

    def _detect(self) -> None:
        found = detect_assembler()
        self._assembler_edit.setText(found)
        if not found:
            self._assembler_edit.setPlaceholderText("sjasmplus not found on PATH")

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Locate the assembler")
        if path:
            self._assembler_edit.setText(path)

    def _accept(self) -> None:
        self.settings.set("assembler_path", self._assembler_edit.text().strip())
        if self.project is not None and self._args_edit is not None:
            manifest = self.project.load_manifest()
            build = manifest.setdefault("build", {})
            build["args"] = self._args_edit.text().split()
            build["output"] = self._output_edit.text().strip() or "main.sna"
            self.project.save_manifest(manifest)
        self.accept()
