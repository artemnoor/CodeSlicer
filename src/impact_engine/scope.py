"""Deterministic project scope planning and pruned filesystem traversal."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterator


DEFAULT_EXCLUDED_DIRS = {
    ".git", ".impact_engine", "__pycache__", "venv", ".venv", "env",
    "node_modules", "dist", "build", "target", ".next", "coverage",
}
PLAN_NAME = "scan_plan.json"


def _plan_path(root: Path) -> Path:
    return root / ".impact_engine" / PLAN_NAME


def _load_extra_exclusions(root: Path) -> set[str]:
    path = _plan_path(root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {str(item).replace("\\", "/").strip("/") for item in data.get("excluded_directories", [])}
    except (OSError, ValueError, TypeError):
        return set()


def iter_project_files(root: str | Path, suffixes: set[str] | None = None) -> Iterator[Path]:
    """Yield project files while pruning known/generated dependency trees."""
    base = Path(root).resolve()
    extra = _load_extra_exclusions(base)
    for current, directories, files in os.walk(base, topdown=True):
        current_path = Path(current)
        relative = current_path.relative_to(base).as_posix() if current_path != base else ""
        kept: list[str] = []
        for directory in directories:
            rel = f"{relative}/{directory}".strip("/")
            nested_repository = directory != ".git" and (current_path / directory / ".git").exists()
            if directory in DEFAULT_EXCLUDED_DIRS or rel in extra or nested_repository:
                continue
            kept.append(directory)
        directories[:] = kept
        for filename in files:
            path = current_path / filename
            if suffixes and path.suffix.lower() not in suffixes:
                continue
            yield path


def build_scan_plan(root: str | Path) -> dict:
    base = Path(root).resolve()
    excluded = set()
    files = []
    for path in iter_project_files(base):
        files.append(path.relative_to(base).as_posix())
    for current, directories, _ in os.walk(base, topdown=True):
        current_path = Path(current)
        relative = current_path.relative_to(base).as_posix() if current_path != base else ""
        kept: list[str] = []
        for directory in list(directories):
            rel = f"{relative}/{directory}".strip("/")
            if directory in DEFAULT_EXCLUDED_DIRS or (current_path / directory / ".git").exists():
                excluded.add(rel)
            else:
                kept.append(directory)
        directories[:] = kept
    return {
        "schema_version": "impact_engine.scan_plan.v1",
        "project_path": str(base),
        "excluded_directories": sorted(excluded),
        "included_files": len(files),
        "excluded_rules": sorted(DEFAULT_EXCLUDED_DIRS),
    }


def write_scan_plan(root: str | Path, plan: dict | None = None) -> Path:
    base = Path(root).resolve()
    output = _plan_path(base)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(plan or build_scan_plan(base), indent=2, ensure_ascii=False), encoding="utf-8")
    return output
