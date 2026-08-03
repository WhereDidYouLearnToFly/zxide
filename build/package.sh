#!/usr/bin/env bash
# Archive a finished Linux build into release/zxide-linux-<arch>-<version>.tar.gz.
#
# Run build/build.sh first; this only packs what it produced. There is no Windows
# counterpart -- 7-Zip's GUI does that job there just as well.
#
# Why tar.gz rather than .7z or .zip here: tar records the executable bit, and the
# bundle is useless without it -- unpack a zip and `zxide` comes out non-executable,
# which is a confusing first experience. p7zip can store unix permissions too, but
# tar.gz is what every Linux user already has.
#
# The archive root is the `zxide` directory itself, so extracting anywhere yields a
# self-contained zxide/ folder rather than 300-odd loose files.
#
# .gitignore lets archives in release/ through (the folder itself stays ignored), so
# what this writes can be committed without -f.
#
# REQUIREMENTS: a completed build in release/zxide/, plus tar and gzip. Nothing else.
#
# Usage:
#   build/package.sh

set -euo pipefail

BUILD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$BUILD_DIR")"
PAYLOAD="$ROOT/release/zxide"

[ -x "$PAYLOAD/zxide" ] || { echo "No build found at $PAYLOAD -- run build/build.sh first" >&2; exit 1; }

# Single-sourced from pyproject.toml so the archive name cannot drift from the project's
# own idea of its version.
VERSION="$(sed -n 's/^version *= *"\([^"]*\)".*/\1/p' "$ROOT/pyproject.toml" | head -n 1)"
[ -n "$VERSION" ] || { echo "Could not read version from pyproject.toml" >&2; exit 1; }

ARCH="$(uname -m)"
OUT="$ROOT/release/zxide-linux-$ARCH-$VERSION.tar.gz"

rm -f "$OUT"
# -C release so the paths inside the archive start at `zxide/`, not `release/zxide/`.
tar -czf "$OUT" -C "$ROOT/release" zxide

echo
echo "wrote $OUT ($(du -h "$OUT" | cut -f1))"
