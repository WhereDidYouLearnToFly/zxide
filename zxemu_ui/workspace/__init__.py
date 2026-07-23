"""Workspace: the project you are working on, and how it becomes a running program.

Everything here is about *your* code rather than the emulated machine. It is the
half of an IDE that has nothing to do with emulation at all -- a folder on disk, the
tools that build it, and the settings that say where those tools live.

    project.py          A project is just a folder with a small ``zxide.json``
                        manifest (name, target machine model, main file, build args).
                        Creating one scaffolds a starter template; optional addons
                        (like ZX0) can be copied in later.
    settings.py         App-wide settings, auto-created on first run with sjasmplus
                        auto-detected on PATH. Also holds the recent-file lists.
    settings_dialog.py  The dialog for overriding all of that.
    builder.py          Shells out to sjasmplus and reports what happened: exit code,
                        combined output, the snapshot produced, the SLD emitted.
    sld.py              Parses that SLD (Source Level Debug) file into the map the
                        debugger needs -- source line <-> address, and your labels.

The split that matters here is between *machine-wide* settings (where sjasmplus
lives -- ``settings.py``) and *per-project* settings (which machine to target, what
build arguments to use -- the manifest). Getting that wrong means a project that
only builds on the machine it was written on.

``sld.py`` is the quiet keystone: breakpoints, the execution-line marker, Run to
Cursor and Go to Label all exist because the assembler tells us where each source
line ended up, and this is the only thing that reads it.
"""
