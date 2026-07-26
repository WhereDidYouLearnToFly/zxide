"""Run the assembler on a project and report the result.

Pure and UI-free: it shells out to sjasmplus (per the app Settings and the project
manifest) in the project folder and returns what happened -- the command, exit
code, combined output, and the snapshot path if one was produced. The window turns
that into log lines and, on success, loads the snapshot.

Before invoking sjasmplus, it regenerates ``assets_generated.asm`` from the project's
imported assets (``zxemu_ui.workspace.asset_build``) -- a converter failure there is
reported the same way an assembler error would be, never a crash.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from zxemu_ui.workspace.asset_build import AssetBuildError, regenerate_assets_asm
from zxemu_ui.workspace.project import DEFAULT_BUILD_ARGS, snapshot_from_source


@dataclass
class BuildResult:
    command: list[str]
    returncode: int
    output: str
    snapshot: Path | None  # the produced .sna, or None if the build failed / it's missing
    sld: Path | None  # the Source Level Debug map (for breakpoints), if produced

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and self.snapshot is not None


def build(project, settings, main: str | None = None) -> BuildResult:
    """Assemble ``main`` (a project-relative source path), or the manifest's main source.

    The caller normally passes the file you have open in the editor: on a folder zxide
    did not scaffold, the entry point is whatever that codebase calls it, and no manifest
    default can know that. The manifest's ``main`` stays as the fallback for when nothing
    source-like is focused.

    Build config (arguments, output) comes from the project's manifest so each
    project can differ; only the assembler *location* comes from the global
    settings (it's a per-machine install, the same for every project).
    """
    try:
        regenerate_assets_asm(project)
    except AssetBuildError as exc:
        return BuildResult([], 1, "Asset build failed: {}\n".format(exc), None, None)

    manifest = project.load_manifest()
    main = main or manifest.get("main", "main.asm")
    main_path = project.folder / main
    if not main_path.is_file():
        return BuildResult(
            [], 1,
            "No source to build: {} does not exist in {}.\n"
            "Open the file you want to assemble in the editor, or set \"main\" in zxide.json.\n".format(main, project.folder),
            None, None,
        )

    build_config = manifest.get("build", {})
    # The source's own savesna wins over the manifest: assembling fallout.asm writes
    # fallout.sna whatever zxide.json says, so believing the manifest here would mean
    # hunting for a file the assembler never wrote.
    output_name = snapshot_from_source(main_path) or build_config.get("output", "main.sna")
    output = project.folder / output_name
    sld_path = output.with_suffix(".sld")  # Source Level Debug map, for breakpoints
    arg_templates = build_config.get("args") or DEFAULT_BUILD_ARGS
    assembler = settings.get("assembler_path") or "sjasmplus"
    args = [arg.format(main=main, output=str(output)) for arg in arg_templates]
    command = [assembler, *args, "--sld={}".format(sld_path)]

    output.parent.mkdir(parents=True, exist_ok=True)  # in case output is in a subfolder
    try:
        proc = subprocess.run(
            command, cwd=str(project.folder), capture_output=True, text=True
        )
    except FileNotFoundError:
        return BuildResult(command, 127, "Assembler not found: {}\n"
                           "Set its path in Settings.".format(assembler), None, None)

    combined = (proc.stdout or "") + (proc.stderr or "")
    ok = proc.returncode == 0
    if ok and not output.exists():
        combined += (
            "\nAssembled cleanly, but no snapshot at {}. "
            "Add a `savesna \"{}\", entry` directive to {} "
            "(or point the manifest's build.output at the one it writes).\n".format(output_name, output_name, main)
        )
    snapshot = output if ok and output.exists() else None
    sld = sld_path if ok and sld_path.exists() else None
    return BuildResult(command, proc.returncode, combined, snapshot, sld)
