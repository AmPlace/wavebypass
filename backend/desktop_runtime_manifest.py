"""Pure-stdlib helpers shared by Desktop runtime build and startup checks."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Iterator


DESKTOP_RUNTIME_METADATA = "runtime.json"
DESKTOP_RUNTIME_BYTECODE_DIRECTORY = "__pycache__"
DESKTOP_RUNTIME_BYTECODE_SUFFIXES = (".pyc", ".pyo")


def _is_runtime_bytecode(relative: str) -> bool:
    parts = Path(relative).parts
    return (
        DESKTOP_RUNTIME_BYTECODE_DIRECTORY in parts
        or Path(relative).suffix in DESKTOP_RUNTIME_BYTECODE_SUFFIXES
    )


def runtime_entries(root: str | Path) -> Iterator[tuple[str, str, str | None, Path | None]]:
    """Yield deterministic runtime entries without following directory links."""
    root = Path(root).resolve()
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        directories.sort()
        files.sort()
        for name in tuple(directories):
            path = current_path / name
            if path.is_symlink():
                directories.remove(name)
                yield path.relative_to(root).as_posix(), "symlink", os.readlink(path), None
        for name in files:
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            if relative == DESKTOP_RUNTIME_METADATA:
                continue
            # CPython may create bytecode while importing the bundled stdlib.
            # It is a runtime cache, not part of the immutable release payload;
            # including it would make a read-only app fail its own integrity
            # check after the first sidecar startup.
            if _is_runtime_bytecode(relative):
                continue
            if path.is_symlink():
                yield relative, "symlink", os.readlink(path), None
            elif path.is_file():
                yield relative, "file", None, path


def runtime_tree_digest(root: str | Path) -> tuple[str, int]:
    """Return a path-independent digest for the installed runtime payload."""
    digest = hashlib.sha256()
    count = 0
    for relative, kind, target, path in runtime_entries(root):
        count += 1
        digest.update(kind.encode("utf-8"))
        digest.update(b"\0")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        if kind == "symlink":
            digest.update(str(target).encode("utf-8"))
        else:
            assert path is not None
            size = path.stat().st_size
            digest.update(str(size).encode("ascii"))
            digest.update(b"\0")
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
    return digest.hexdigest(), count
