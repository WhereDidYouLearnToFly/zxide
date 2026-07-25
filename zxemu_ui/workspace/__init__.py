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
                        combined output, the snapshot produced, the SLD emitted. The
                        entry point it assembles is passed in -- normally the file open
                        in the editor, since only a project zxide scaffolded is likely
                        to call its main source ``main.asm``.
    asset_build.py      Runs every imported asset through its converter, places the
                        results, and writes ``assets_generated.asm`` for the build to
                        include -- the bridge between the asset workflow and sjasmplus.
    sld.py              Parses that SLD (Source Level Debug) file into the map the
                        debugger needs -- source line <-> address, and your labels.
    search.py           Find-in-project: every editable text file searched for a
                        string, skipping assets, build output and generated files.
    dump_project.py     The reverse of everything above: takes a machine's RAM and
                        writes it out as a *project* -- manifest, ``main.asm``, one
                        source per region -- so somebody else's running program becomes
                        somewhere you can work. The reasoning about what is code lives
                        in ``zxemu_core.debug.dumper``; this half only writes files.

The split that matters here is between *machine-wide* settings (where sjasmplus
lives -- ``settings.py``) and *per-project* settings (which machine to target, what
build arguments to use -- the manifest). Getting that wrong means a project that
only builds on the machine it was written on.

``sld.py`` is the quiet keystone: breakpoints, the execution-line marker, Run to
Cursor and Go to Label all exist because the assembler tells us where each source
line ended up, and this is the only thing that reads it.
"""
