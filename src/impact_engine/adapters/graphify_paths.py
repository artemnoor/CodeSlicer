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


def graphify_interpreter_from_executable(executable: str | Path) -> Path | None:
    """Locate the interpreter paired with a Graphify console entry point."""
    path = Path(executable).expanduser().resolve()
    candidates = [path.parent / "python.exe", path.parent / "python", path.parent.parent / "python.exe", path.parent.parent / "bin" / "python"]
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def record_graphify_interpreter(graph_path: str | Path, executable: str | Path) -> Path | None:
    interpreter = graphify_interpreter_from_executable(executable)
    if not interpreter:
        return None
    target = Path(graph_path).resolve().parent / ".graphify_python"
    target.write_text(str(interpreter) + "\n", encoding="utf-8")
    return target
