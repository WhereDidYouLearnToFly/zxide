# build/ — packaging zxide as a standalone app

Everything needed to turn the source tree into a folder you can hand to someone who
has no Python, no PyQt5 and no idea what a virtualenv is. The result lands in
`release/` at the repo root and is not tracked by git.

Nothing in here is needed to *run* zxide from source (`python main.py`) — this is
only for producing a distributable build.

| file | what it is |
| --- | --- |
| `build.ps1` | Windows build script — run this |
| `build.sh` | the same build for Linux/macOS |
| `zxide.spec` | PyInstaller recipe: what goes in the bundle and how it is packed |
| `make_icon.py` | draws the application icon (`icon/zxide.ico`, `icon/zxide.png`) |
| `package.sh` | packs a finished Linux build into a release tarball |
| `linux/` | desktop integration: `install.sh`, `uninstall.sh`, `zxide.desktop` |
| `icon/` | the generated icon, regenerated on every build |
| `work/` | PyInstaller's scratch state — git-ignored, safe to delete |

## Requirements

1. **Python 3.10 or newer**, 64-bit. Built and tested on 3.11.9 (Windows 11).
   Whichever interpreter is first on `PATH` is the one that gets frozen into the
   bundle, so if you keep several, make sure the right one is in front.

2. **The runtime dependencies**, because PyInstaller bundles the copies it finds
   installed — PyQt5, numpy, pygame and Pillow:

   ```
   pip install -e .
   ```

3. **PyInstaller 6.x**:

   ```
   pip install -e ".[build]"
   ```

   (or plain `pip install pyinstaller`; the extra just pins the supported major.)

4. **A machine of the platform you are building for.** PyInstaller freezes the
   running interpreter, so it cannot cross-compile: a Windows `.exe` must be built
   on Windows, a Linux binary on Linux. The two scripts exist for exactly that
   reason, and both drive the same `zxide.spec` so the contents stay identical.

5. **Nothing else at build time.** Note what is *not* required, and therefore not
   bundled: **sjasmplus**. The assembler is invoked as an external process the user
   chooses in Settings (see `zxemu_ui/workspace/builder.py`), so a machine that runs
   the release still needs its own sjasmplus before the Build menu will do anything.
   The emulator, editor, debugger and asset tools all work without it.

## Building

Windows:

```
powershell -ExecutionPolicy Bypass -File build\build.ps1
```

Linux/macOS:

```
build/build.sh
```

Both accept two switches:

- `-Clean` / `--clean` — delete `build/work/` and the previous `release/zxide/`
  first. Use it after changing dependencies or `zxide.spec`; PyInstaller otherwise
  reuses a cached module graph and can carry a stale one forward.
- `-Console` / `--console` — build with a console window attached, so a crash
  before the Qt window appears prints a traceback instead of vanishing. Debug aid;
  do not ship a build made with it.

A full build takes a couple of minutes and prints the output path and total size
when it finishes.

## What you get

```
release/zxide/
    zxide.exe          (or `zxide` on Linux/macOS)
    _internal/         Python runtime, Qt, numpy, and the app's own data
```

Roughly 165 MB on Windows, most of it Qt5 and numpy. Copy or zip the whole
`release/zxide/` folder — the exe alone will not run.

### One folder, not one file

`--onefile` is deliberately not used. A one-file exe unpacks itself into a fresh
temporary directory on every launch, and zxide writes `settings.json` (your
sjasmplus path, last project, preferences) and `layout.json` (your panel
arrangement) *next to the package* — see `MainWindow.__init__`. Under `--onefile`
both would be written into a temp dir that is deleted on exit, so the app would
forget everything every time it closed. One-folder keeps them.

### Where the app's own data lives

Bundled read-only, copied into the same relative paths they occupy in the repo so
that `importlib.resources` and the `Path(__file__).parent` lookups in the app code
resolve identically frozen or not — no frozen-app special-casing anywhere in
`zxemu_core`/`zxemu_ui`:

- `_internal/zxemu_core/roms/` — the 48K/128K/Pentagon/TR-DOS ROM images
- `_internal/zxemu_core/players/` — the PT2/PT3 tracker players
- `_internal/zxemu_ui/templates/` — the 48K and 128K new-project templates
- `_internal/zxemu_ui/addons/` — the optional ZX0 decompressor

Written at runtime, into that same `_internal/` folder:

- `settings.json`, `layout.json` — per-user state
- `screenshots/`, `recordings/` — only when no project is open; with a project
  open they go into the project folder

That works where the folder is writable, which covers unzip-and-run. It does *not*
survive an install under `C:\Program Files` or `/usr/local`, where the app
directory is read-only for a normal user. If zxide is ever packaged as a real
installer, that is the thing to change first: make those paths fall back to
`%APPDATA%` / `~/.config` when `sys.frozen` is set.

## Linux

`build.sh` produces the same one-folder bundle as on Windows, but a folder is all it
is — nothing about it registers with the desktop. The extras in `linux/` finish the
job:

```
build/build.sh                        build release/zxide/
build/linux/install.sh                install it for the current user
build/linux/uninstall.sh              undo that
build/package.sh                      pack it into release/zxide-linux-<arch>-<version>.tar.gz
```

`install.sh` is a **user** install into `~/.local` — bundle in `~/.local/lib/zxide`,
symlink in `~/.local/bin`, a `.desktop` entry in `~/.local/share/applications` and the
icon in the hicolor theme. No root, and `--from` lets it install from an unpacked
release tarball instead of a fresh build. A system-wide `/opt` install is deliberately
not offered: the bundle would be root-owned, and zxide writes `settings.json` and
`layout.json` inside its own folder, so it would silently fail to remember anything.
That is the same limitation described above, and the same fix unblocks both.

`package.sh` writes a `.tar.gz` rather than a zip because tar records the executable
bit — unpack a zip and `zxide` comes out non-executable, which is a baffling first
experience. `.gitignore` exempts archives in `release/` from the ignore rule, so a
packed release can be committed without `git add -f`.

Two Linux-specific things that have no Windows equivalent:

- **glibc pins the build.** A PyInstaller binary runs only on a glibc at least as new
  as the one it was built against, so build on the oldest distro you intend to
  support and it will work on everything newer, not the other way round.
- **Qt's xcb platform plugin needs system X libraries** that the PyQt5 wheel does not
  carry — typically `libxcb-xinerama0` and `libxkbcommon-x11-0`, and on newer distros
  `libxcb-cursor0`. Most desktop installs already have them; a minimal container will
  not, and the symptom is the "could not load the Qt platform plugin xcb" error.

One thing to watch when committing from Windows: git stores the executable bit, and
files added from a Windows checkout arrive as `100644`. If the shell scripts land
without `+x`, Linux users have to invoke them as `bash build/build.sh`. Fix it in the
index with:

```
git update-index --chmod=+x build/build.sh build/package.sh build/linux/install.sh build/linux/uninstall.sh
```

## The icon

`make_icon.py` draws it rather than storing hand-made art, so it can be re-rendered
at any size from plain Pillow geometry — a dark IDE-style tile, a fat `>` prompt
with a caret (the "this is a developer tool" cue), and the four slanted Sinclair
rainbow stripes (the "for this machine" cue). Everything is drawn at 1024×1024 and
downsampled with LANCZOS into each icon size, because drawing small directly gives
ragged diagonals. The build scripts run it every time, so editing the shapes and
rebuilding is enough — there is no separate icon step to remember.

It is only used for the executable's own icon. The running window's icon is
whatever `main_window.py` sets, which is a separate matter.

## Troubleshooting

**`ModuleNotFoundError` at startup, but running from source works.** PyInstaller
found no static `import` for it. Add it to `HIDDEN` in `zxide.spec` — that is what
`pygame` and `PIL.Image` are already there for: both are imported inside functions
so a missing package costs one feature instead of the whole IDE, which also hides
them from the analysis.

**A file the app opens at runtime is missing.** Add it to `DATAS` in `zxide.spec`
as `(absolute source path, destination inside the bundle)`. Keep the destination
equal to the repo-relative path or the app's own lookups will not find it.

**Qt fails to start ("could not find or load the Qt platform plugin").** Usually a
half-cached build: rerun with `-Clean`. PyInstaller's PyQt5 hook collects the
platform plugins itself, so this is rarely a spec problem.

**Antivirus flags the exe.** A known false positive on PyInstaller's bootloader,
not specific to this project. Unsigned executables that unpack their own archive
look like packers. Code signing is the real fix.

**The build is large.** `EXCLUDES` in the spec already keeps out tkinter,
matplotlib, scipy, pandas and the unused Qt modules. The remainder is Qt5 plus
numpy and there is not much to shave without dropping features. UPX compression is
deliberately off: it saves some tens of MB but raises the antivirus false-positive
rate sharply.
