#!/usr/bin/env bash
# Undo build/linux/install.sh: remove the bundle, the launcher symlink, the app menu
# entry and the icon.
#
# What it does NOT remove is anything zxide wrote while you used it -- your projects
# live wherever you put them, and settings.json/layout.json live inside the bundle
# folder, so reinstalling starts fresh. That is a deliberate asymmetry: an uninstall
# script that deletes user data is a bug, not a feature.
#
# Usage:
#   build/linux/uninstall.sh                 undo an install into ~/.local
#   build/linux/uninstall.sh --prefix ~/apps undo an install made with the same --prefix

set -euo pipefail

PREFIX="$HOME/.local"

while [ $# -gt 0 ]; do
    case "$1" in
        --prefix) PREFIX="$2"; shift 2 ;;
        -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

LIB_DIR="$PREFIX/lib/zxide"
REMOVED=0

for target in "$LIB_DIR" "$PREFIX/bin/zxide" "$PREFIX/share/applications/zxide.desktop" "$PREFIX/share/icons/hicolor/256x256/apps/zxide.png"; do
    if [ -e "$target" ] || [ -L "$target" ]; then
        rm -rf "$target"
        echo "removed $target"
        REMOVED=1
    fi
done

if [ "$REMOVED" = "0" ]; then
    echo "nothing to remove under $PREFIX"
    exit 0
fi

command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$PREFIX/share/applications" || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t "$PREFIX/share/icons/hicolor" || true

echo
echo "done. Your projects and any settings.json inside the removed folder are gone with it; nothing outside was touched."
