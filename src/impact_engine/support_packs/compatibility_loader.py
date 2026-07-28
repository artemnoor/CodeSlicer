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
    # In a source checkout plugins live beside ``src``; in a wheel they live
    # beside ``impact_engine`` in site-packages.  Never assume one layout.
    here = Path(__file__).resolve()
    for root in (here.parents[2], here.parents[3]):
        candidate = root / "plugins" / "compatibility"
        if candidate.is_dir():
            return _load_first(candidate, "legacy_resolution.py", "codeslicer_legacy_resolution")
    raise ImportError("compatibility implementation 'legacy_resolution.py' was not discovered")


def load_endpoint_bridge() -> ModuleType:
    here = Path(__file__).resolve()
    for root in (here.parents[2], here.parents[3]):
        candidate = root / "plugins" / "frameworks"
        if candidate.is_dir():
            return _load_first(candidate, "endpoint_bridge.py", "codeslicer_endpoint_bridge")
    raise ImportError("compatibility implementation 'endpoint_bridge.py' was not discovered")
