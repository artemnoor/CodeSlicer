"""One authoritative location for project-local Graphify artifacts."""
from __future__ import annotations

from pathlib import Path


def graphify_artifact_root(project_path: str | Path) -> Path:
    return Path(project_path).expanduser().resolve() / ".codeslicer" / "artifacts" / "graphify"


def graphify_graph_path(project_path: str | Path) -> Path:
    return graphify_artifact_root(project_path) / "graphify-out" / "graph.json"


def legacy_graphify_graph_path(project_path: str | Path) -> Path:
    return Path(project_path).expanduser().resolve() / "graphify-out" / "graph.json"


def find_graphify_graph(project_path: str | Path) -> Path:
    """Prefer the current artifact contract, retaining read-only legacy support."""
    canonical = graphify_graph_path(project_path)
    return canonical if canonical.is_file() else legacy_graphify_graph_path(project_path)
