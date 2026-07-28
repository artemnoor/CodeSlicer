"""Safe, metadata-only CodeSlicer project-local storage preparation."""
from __future__ import annotations

import json
from pathlib import Path


STORAGE_DIRECTORIES = ("cache", "artifacts", "adapters", "history", "logs")
INTERNAL_ARTIFACT_PREFIXES = (".impact_engine/", ".codeslicer/")
CONFIG = {
    "schema_version": "CodeSlicerProjectConfig/v1",
    "privacy": {"mode": "local-only", "network_used": False},
    "retention": {"history_days": 30, "logs_days": 7},
}


def ensure_project_storage(project_path: str | Path) -> Path:
    """Create only the empty metadata directories that do not already exist.

    Existing ``.impact_engine`` state is deliberately untouched.  The new
    structure is currently reserved for UI metadata and future adapter
    artifacts; it never receives source files or the canonical graph.
    """

    root = Path(project_path).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Project directory does not exist: {project_path}")
    storage = root / ".codeslicer"
    storage.mkdir(exist_ok=True)
    for name in STORAGE_DIRECTORIES:
        (storage / name).mkdir(exist_ok=True)
    config_path = storage / "config.json"
    if not config_path.exists():
        config_path.write_text(json.dumps(CONFIG, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return storage


def is_codeslicer_artifact_path(path: str) -> bool:
    """Return whether a repository-relative path is generated CodeSlicer state.

    These folders are product-owned metadata, never project source. They must
    not make a review stale or unsupported if a repository accidentally tracks
    them before adding the paths to ``.gitignore``.
    """
    normalized = str(path).replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized in {".impact_engine", ".codeslicer"} or normalized.startswith(INTERNAL_ARTIFACT_PREFIXES)
