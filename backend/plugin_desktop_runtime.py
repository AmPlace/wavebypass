"""Resolve the controlled Python runtime used by frozen Desktop builds."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from plugin_runtime import PluginError


DESKTOP_RUNTIME_DIRECTORY = "python-runtime"
DESKTOP_RUNTIME_METADATA = "runtime.json"


def _runtime_candidate(backend_executable: str | Path) -> Path:
    executable = Path(backend_executable).resolve()
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    return executable.parent / DESKTOP_RUNTIME_DIRECTORY / "bin" / f"python{version}"


def resolve_plugin_python_executable() -> Path:
    """Return the interpreter allowed to create/run Python Plugin envs.

    A frozen backend must never fall back to its PyInstaller interpreter or to
    a user/system Python.  The only accepted frozen-build path is the sibling
    runtime staged by the Desktop release builder.  Normal backend/test runs
    retain the existing interpreter behavior.
    """

    if not getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise PluginError(
                "PYTHON_RUNTIME_UNSUPPORTED",
                "The controlled Python runtime is unavailable",
                category="runtime",
            )
        return executable

    runtime_root = (Path(sys.executable).resolve().parent / DESKTOP_RUNTIME_DIRECTORY).resolve()
    candidate = _runtime_candidate(sys.executable).resolve()
    try:
        candidate.relative_to(runtime_root)
    except ValueError as exc:
        raise PluginError(
            "PYTHON_RUNTIME_UNSUPPORTED",
            "The Desktop Python runtime path is invalid",
            category="runtime",
        ) from exc
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        raise PluginError(
            "PYTHON_RUNTIME_UNSUPPORTED",
            "The Desktop Python runtime is not bundled",
            category="runtime",
        )
    try:
        metadata = json.loads((runtime_root / DESKTOP_RUNTIME_METADATA).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PluginError(
            "PYTHON_RUNTIME_UNSUPPORTED",
            "The Desktop Python runtime metadata is invalid",
            category="runtime",
        ) from exc
    expected_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    if metadata != {
        "schema_version": 1,
        "python_version": expected_version,
        "os": "macos",
        "arch": "arm64",
    }:
        raise PluginError(
            "PYTHON_RUNTIME_UNSUPPORTED",
            "The Desktop Python runtime metadata is incompatible",
            category="runtime",
        )
    return candidate
