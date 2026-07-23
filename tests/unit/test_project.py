"""Tests for the folder-based project model and its manifest (zxemu_ui.workspace.project)."""

from __future__ import annotations

from zxemu_ui.workspace.project import DEFAULT_MODEL, Project, default_manifest


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


def test_model_defaults_to_48k_for_manifests_without_the_field(tmp_path):
    project = Project.create(tmp_path / "old", "Old", "48k")
    # Simulate a pre-model manifest by stripping the field back out.
    manifest = project.load_manifest()
    del manifest["model"]
    project.save_manifest(manifest)
    assert project.model == DEFAULT_MODEL == "48k"
