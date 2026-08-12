#!/usr/bin/env bash
set -euo pipefail

# The release pipeline supplies a versioned, relocatable CPython runtime root.
# This script only stages that already-controlled input; it never downloads or
# builds Python and never accepts the host interpreter implicitly.
SOURCE_DIR="${1:?usage: stage-desktop-python-runtime.sh SOURCE_DIR DEST_DIR}"
DEST_DIR="${2:?usage: stage-desktop-python-runtime.sh SOURCE_DIR DEST_DIR}"

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  echo "Desktop Python runtime staging currently supports macOS arm64 only" >&2
  exit 1
fi

SOURCE_DIR="$(cd -- "$SOURCE_DIR" && pwd -P)"
SOURCE_PYTHON="$SOURCE_DIR/bin/python3.14"
if [[ ! -f "$SOURCE_PYTHON" || -L "$SOURCE_PYTHON" || ! -x "$SOURCE_PYTHON" ]]; then
  echo "Controlled runtime must contain a regular executable bin/python3.14" >&2
  exit 1
fi

rm -rf -- "$DEST_DIR"
mkdir -p -- "$DEST_DIR"
cp -a "$SOURCE_DIR/." "$DEST_DIR/"

DEST_PYTHON="$DEST_DIR/bin/python3.14"
if [[ ! -f "$DEST_PYTHON" || ! -x "$DEST_PYTHON" ]]; then
  echo "Staged Desktop Python runtime is incomplete" >&2
  exit 1
fi

# -I -S proves the staged interpreter can run without environment variables or
# site-packages. The source bundle is expected to carry its own stdlib and
# native runtime; no host Python executable is consulted by this check.
"$DEST_PYTHON" -I -S -c 'import sys; assert sys.version_info[:2] == (3, 14)' \
  || { echo "Staged runtime is not CPython 3.14" >&2; exit 1; }

"$DEST_PYTHON" -I -S -c 'import json, platform, sys; print(json.dumps({
    "schema_version": 1, "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
    "os": "macos" if sys.platform == "darwin" else sys.platform,
    "arch": platform.machine(),
}, sort_keys=True))' > "$DEST_DIR/runtime.json"

echo "Staged controlled Python runtime: $DEST_PYTHON"
