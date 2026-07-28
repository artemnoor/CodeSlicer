"""Neutral loader for isolated compatibility implementations."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def _load_first(root: Path, filename: str, module_name: str) -> ModuleType:
    matches = sorted(root.rglob(filename))
    if not matches:
        raise ImportError(f"compatibility implementation {filename!r} was not discovered")
    path = matches[0]
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load compatibility implementation {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_legacy_resolution() -> ModuleType:
    repo_root = Path(__file__).resolve().parents[3]
    return _load_first(repo_root / "plugins" / "compatibility", "legacy_resolution.py", "codeslicer_legacy_resolution")


def load_endpoint_bridge() -> ModuleType:
    repo_root = Path(__file__).resolve().parents[3]
    return _load_first(repo_root / "plugins" / "frameworks", "endpoint_bridge.py", "codeslicer_endpoint_bridge")
