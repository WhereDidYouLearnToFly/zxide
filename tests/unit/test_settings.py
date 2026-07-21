"""Tests for the recent-list helpers on Settings (Open Recent / Load Recent)."""

from __future__ import annotations

from zxemu_ui.settings import Settings


def _settings(tmp_path) -> Settings:
    return Settings(tmp_path / "settings.json")


def test_push_recent_prepends_most_recent_first(tmp_path):
    s = _settings(tmp_path)
    s.push_recent("recent_projects", "/a")
    s.push_recent("recent_projects", "/b")
    assert s.get("recent_projects") == ["/b", "/a"]


def test_push_recent_deduplicates_and_moves_to_front(tmp_path):
    s = _settings(tmp_path)
    for path in ("/a", "/b", "/c"):
        s.push_recent("recent_projects", path)
    s.push_recent("recent_projects", "/a")  # re-used -> jumps to the top, no duplicate
    assert s.get("recent_projects") == ["/a", "/c", "/b"]


def test_push_recent_caps_the_list(tmp_path):
    s = _settings(tmp_path)
    for i in range(15):
        s.push_recent("recent_files", f"/f{i}", limit=10)
    recent = s.get("recent_files")
    assert len(recent) == 10
    assert recent[0] == "/f14"   # newest kept
    assert "/f4" not in recent   # oldest dropped


def test_remove_recent_drops_a_single_entry(tmp_path):
    s = _settings(tmp_path)
    for path in ("/a", "/b", "/c"):
        s.push_recent("recent_projects", path)
    s.remove_recent("recent_projects", "/b")
    assert s.get("recent_projects") == ["/c", "/a"]


def test_recent_lists_persist_across_reload(tmp_path):
    s = _settings(tmp_path)
    s.push_recent("recent_projects", "/keep")
    reloaded = Settings(tmp_path / "settings.json")
    assert reloaded.get("recent_projects") == ["/keep"]
