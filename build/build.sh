#!/usr/bin/env bash
# Build a standalone zxide into the repo's release/ folder (Linux/macOS).
#
# The Windows twin of this script is build/build.ps1; both drive the same
# build/zxide.spec, so the two platforms bundle identical contents. The result is
# release/zxide/zxide -- a one-folder build, because zxide writes settings.json and
# layout.json next to itself and a --onefile bundle would lose them on every exit.
#
# Usage:
#   build/build.sh            normal build
#   build/build.sh --clean    discard cached PyInstaller state first
#   build/build.sh --console  keep stdout attached (debugging startup crashes)
#
# Set PYTHON=... to build with an interpreter other than python3.
#
# REQUIREMENTS (all checked below before anything is built):
#   * Python 3.10+ 64-bit. The interpreter this script runs is the one frozen into
#     the bundle, so pick it deliberately if you keep several.
#   * The runtime dependencies -- PyQt5, numpy, pygame, Pillow. PyInstaller bundles
#     the installed copies, so they must be importable here:  pip install -e .
#   * PyInstaller 6.x:  pip install -e ".[build]"
#   * A machine of the target platform. PyInstaller freezes the interpreter it runs
#     under and cannot cross-compile, so a Windows .exe has to be built on Windows.
#
# NOT required, and deliberately not bundled: sjasmplus. zxide runs the assembler as
# an external process chosen in Settings, so whoever runs the release needs their own
# copy before the Build menu does anything. Everything else -- emulator, editor,
# debugger, asset tools -- works without it.
#
# See build/README.md for what ends up in the bundle and where the app writes its
# settings once frozen.

set -euo pipefail

BUILD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$BUILD_DIR")"
DIST="$ROOT/release"
WORK="$BUILD_DIR/work"
SPEC="$BUILD_DIR/zxide.spec"

CLEAN=0
export ZXIDE_CONSOLE=0
for arg in "$@"; do
    case "$arg" in
        --clean) CLEAN=1 ;;
        --console) export ZXIDE_CONSOLE=1 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

PYTHON="${PYTHON:-python3}"

echo "zxide build"
echo "  repo    : $ROOT"
echo "  output  : $DIST/zxide"
echo "  python  : $("$PYTHON" -c 'import sys; print(sys.version.split()[0])')"

"$PYTHON" -c "import PyQt5, numpy, pygame, PIL" >/dev/null || { echo "Missing runtime dependencies. Run: $PYTHON -m pip install -e ." >&2; exit 1; }
"$PYTHON" -m PyInstaller --version >/dev/null 2>&1 || { echo "PyInstaller not installed. Run: $PYTHON -m pip install pyinstaller" >&2; exit 1; }

if [ "$CLEAN" = "1" ]; then
    echo "cleaning previous build..."
    rm -rf "$WORK" "$DIST/zxide"
fi

echo "drawing icon..."
"$PYTHON" "$BUILD_DIR/make_icon.py"

echo "running PyInstaller..."
"$PYTHON" -m PyInstaller --noconfirm --distpath "$DIST" --workpath "$WORK" "$SPEC"

echo
echo "done: $DIST/zxide/zxide"
echo "sjasmplus is NOT bundled -- point Settings at your own copy on first run."
