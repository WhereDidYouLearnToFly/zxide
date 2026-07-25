"""Tests for the folder-based project model and its manifest (zxemu_ui.workspace.project)."""

from __future__ import annotations

from zxemu_ui.workspace.project import (
    DEFAULT_MODEL,
    Project,
    default_manifest,
    snapshot_from_source,
)


def test_default_manifest_records_the_model():
    manifest = default_manifest("demo", "128k")
    assert manifest["name"] == "demo"
    assert manifest["model"] == "128k"
    assert manifest["main"] == "main.asm"
    assert manifest["build"]["output"] == "main.sna"


def test_create_48k_project_scaffolds_the_48k_template(tmp_path):
    project = Project.create(tmp_path / "p48", "P48", "48k")
    assert project.model == "48k"
    main = (project.folder / "main.asm").read_text(encoding="utf-8")
    assert "device zxspectrum48" in main


def test_create_128k_project_scaffolds_the_128k_template(tmp_path):
    project = Project.create(tmp_path / "p128", "P128", "128k")
    assert project.model == "128k"
    main = (project.folder / "main.asm").read_text(encoding="utf-8")
    assert "device zxspectrum128" in main
    # The 128K demo exercises paging, so it writes the paging port.
    assert "$7ffd" in main.lower()


def test_snapshot_from_source_reads_the_savesna_directive(tmp_path):
    """The source, not the manifest, decides where the snapshot lands (sjasmplus has no --sna)."""
    path = tmp_path / "fallout.asm"
    path.write_text('    org $8000\nstart:\n    savesna "out/fallout.sna", start\n', encoding="utf-8")
    assert snapshot_from_source(path) == "out/fallout.sna"


def test_snapshot_from_source_is_case_insensitive_and_tolerant_of_indentation(tmp_path):
    path = tmp_path / "g.asm"
    path.write_text('\t\tSAVESNA  "game.sna", entry\n', encoding="utf-8")
    assert snapshot_from_source(path) == "game.sna"


def test_snapshot_from_source_returns_none_when_there_is_no_directive(tmp_path):
    path = tmp_path / "fragment.asm"
    path.write_text("    nop\n", encoding="utf-8")
    assert snapshot_from_source(path) is None
    assert snapshot_from_source(tmp_path / "missing.asm") is None


def test_scaffolded_templates_savesna_matches_the_manifest_output(tmp_path):
    """The default main.sna isn't a guess -- both templates really write it."""
    for model in ("48k", "128k"):
        project = Project.create(tmp_path / model, model.upper(), model)
        manifest = project.load_manifest()
        assert snapshot_from_source(project.folder / manifest["main"]) == manifest["build"]["output"]


def test_model_defaults_to_48k_for_manifests_without_the_field(tmp_path):
    project = Project.create(tmp_path / "old", "Old", "48k")
    # Simulate a pre-model manifest by stripping the field back out.
    manifest = project.load_manifest()
    del manifest["model"]
    project.save_manifest(manifest)
    assert project.model == DEFAULT_MODEL == "48k"
