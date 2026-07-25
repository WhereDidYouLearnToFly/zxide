"""Shared test setup.

The one thing here is settings isolation. ``MainWindow`` builds its ``Settings`` from a
fixed path beside the package (``settings.json`` next to the app -- deliberately, so the
app is zero-config and has no registry keys or per-user directory to hunt for), and
``_open_project`` writes ``last_project``/``recent_projects`` through to it. Any test that
constructs a MainWindow therefore rewrites the *developer's own* settings: ``last_project``
ends up pointing at a ``tmp_path`` folder pytest deletes, so the next real launch opens no
project, and Open Recent fills with dead temp paths.

Redirecting the class MainWindow reaches for keeps that damage inside the test run, and as
a bonus makes tests deterministic: a fresh settings file has no ``last_project``, so
``_reopen_last_project`` no longer drags whatever project you had open into the test.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_app_settings(tmp_path, monkeypatch):
    from zxemu_ui import main_window

    real_settings = main_window.Settings
    monkeypatch.setattr(
        main_window, "Settings",
        lambda _path: real_settings(tmp_path / "app-settings.json"),
    )
