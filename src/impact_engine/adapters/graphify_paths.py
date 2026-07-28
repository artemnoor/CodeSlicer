"""One authoritative location for project-local Graphify artifacts."""
from __future__ import annotations

import html
import os
from pathlib import Path
import subprocess


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


def graphify_viewer_cache_path(project_path: str | Path) -> Path:
    return find_graphify_graph(project_path).parent / ".codeslicer_graphify_viewer.html"


def cache_graphify_viewer(project_path: str | Path) -> Path | None:
    """Create a bounded upstream Graphify HTML artifact after index/refresh.

    This shared runtime hook is deliberately usable from both the CLI and the
    Local API. Viewer GET requests therefore only read a local file.
    """
    graph = find_graphify_graph(project_path)
    interpreter_file = graph.parent / ".graphify_python"
    if not graph.is_file() or not interpreter_file.is_file():
        return None
    interpreter = Path(interpreter_file.read_text(encoding="utf-8").strip())
    if not interpreter.is_file():
        return None
    script = """
import json, sys, tempfile
from pathlib import Path
import networkx as nx
from graphify.exporters.html import to_html
graph_file = Path(sys.argv[1]); data = json.loads(graph_file.read_text(encoding='utf-8'))
nodes = [{'id': str(n['id']), 'label': str(n.get('name', n['id'])), 'kind': str(n.get('kind', 'FUNCTION'))} for n in data.get('nodes', [])]
links = [{'source': e.get('from', e.get('source')), 'target': e.get('to', e.get('target')), 'kind': e.get('kind', 'CALLS')} for e in (data.get('edges') or data.get('links') or [])]
g = nx.node_link_graph({'directed': True, 'nodes': nodes, 'links': links}, edges='links')
with tempfile.NamedTemporaryFile(suffix='.html', delete=False) as h: output = Path(h.name)
try: to_html(g, {0: [n['id'] for n in nodes]}, output); sys.stdout.write(output.read_text(encoding='utf-8'))
finally: output.unlink(missing_ok=True)
"""
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONNOUSERSITE": "1"}
    if os.name == "nt":
        env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", "")
    try:
        completed = subprocess.run([str(interpreter), "-I", "-c", script, str(graph)], cwd=str(graph.parent), env=env, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0 or not completed.stdout:
        return None
    cache = graphify_viewer_cache_path(project_path)
    cache.write_text(completed.stdout[:4 * 1024 * 1024], encoding="utf-8")
    return cache
