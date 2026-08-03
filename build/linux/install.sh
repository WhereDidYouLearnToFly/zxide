#!/usr/bin/env bash
# Install a built zxide into the current user's desktop environment: app menu entry,
# icon, and a `zxide` command on PATH.
#
# This is the step build.sh does not do. A PyInstaller bundle is just a folder --
# nothing about it registers with the desktop, so without this you are launching the
# binary by path forever. Run it after build/build.sh, or after unpacking a release
# tarball (point it at the unpacked folder with --from).
#
# Deliberately a *user* install, into ~/.local, needing no root:
#
#   ~/.local/lib/zxide/                             the bundle
#   ~/.local/bin/zxide                              symlink onto PATH
#   ~/.local/share/applications/zxide.desktop       app menu entry
#   ~/.local/share/icons/hicolor/256x256/apps/      icon
#
# A system-wide install under /opt would need root, and -- more importantly -- would
# put the bundle somewhere the user cannot write. zxide keeps settings.json and
# layout.json inside its own folder (see build/README.md), so a root-owned install
# would silently fail to remember anything. Fix that first if you want /opt.
#
# REQUIREMENTS: a built or unpacked zxide folder, and a freedesktop.org-compliant
# desktop (GNOME, KDE, XFCE, ...). desktop-file-install is not needed; the caches are
# refreshed only if the usual tools happen to be present.
#
# Usage:
#   build/linux/install.sh                  install from release/zxide
#   build/linux/install.sh --from /path     install from an unpacked release
#   build/linux/install.sh --prefix ~/apps  install somewhere other than ~/.local
#   build/linux/uninstall.sh                undo it

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$(dirname "$HERE")")"

SOURCE="$ROOT/release/zxide"
PREFIX="$HOME/.local"

while [ $# -gt 0 ]; do
    case "$1" in
        --from) SOURCE="$2"; shift 2 ;;
        --prefix) PREFIX="$2"; shift 2 ;;
        -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

[ -x "$SOURCE/zxide" ] || { echo "No zxide build at $SOURCE -- run build/build.sh, or pass --from" >&2; exit 1; }

LIB_DIR="$PREFIX/lib/zxide"
BIN_DIR="$PREFIX/bin"
APP_DIR="$PREFIX/share/applications"
ICON_DIR="$PREFIX/share/icons/hicolor/256x256/apps"

echo "installing zxide"
echo "  from : $SOURCE"
echo "  to   : $LIB_DIR"

mkdir -p "$BIN_DIR" "$APP_DIR" "$ICON_DIR" "$(dirname "$LIB_DIR")"

# Replace wholesale rather than copying over the top: a stale file left behind from an
# older build is the kind of thing that produces an impossible-looking bug report.
rm -rf "$LIB_DIR"
cp -r "$SOURCE" "$LIB_DIR"

ln -sf "$LIB_DIR/zxide" "$BIN_DIR/zxide"
cp "$HERE/../icon/zxide.png" "$ICON_DIR/zxide.png"

# Point Exec at the real binary, not the symlink: the symlink is for typing `zxide` in
# a terminal, while the menu entry should keep working even if ~/.local/bin is not on
# the desktop session's PATH -- which it often is not.
sed "s|^Exec=.*|Exec=$LIB_DIR/zxide|" "$HERE/zxide.desktop" > "$APP_DIR/zxide.desktop"
chmod 644 "$APP_DIR/zxide.desktop"

# Best-effort cache refresh. Both tools are optional; every desktop picks the entry up
# on its own eventually, this just means "now" instead of "after the next login".
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APP_DIR" || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t "$PREFIX/share/icons/hicolor" || true

echo
echo "done. Launch it from the app menu, or run: $BIN_DIR/zxide"
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) echo "note: $BIN_DIR is not on your PATH, so the plain 'zxide' command will not resolve until you add it." ;;
esac
echo "sjasmplus is not bundled -- install it and point Settings at it before using Build."
