"""One authoritative location for project-local Graphify artifacts."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile


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
    target.parent.mkdir(parents=True, exist_ok=True)
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
    try:
        raw = json.loads(graph.read_text(encoding="utf-8"))
        max_nodes, max_edges = 750, 2_000
        nodes = list(raw.get("nodes") or [])[:max_nodes]
        node_ids = {str(item.get("id")) for item in nodes if item.get("id") is not None}
        edges = [edge for edge in (raw.get("edges") or raw.get("links") or []) if str(edge.get("from", edge.get("source"))) in node_ids and str(edge.get("to", edge.get("target"))) in node_ids][:max_edges]
        limited = {**raw, "nodes": nodes, "edges": edges, "links": edges, "codeslicer_viewer": {"truncated": len(nodes) < len(raw.get("nodes") or []) or len(edges) < len(raw.get("edges") or raw.get("links") or []), "max_nodes": max_nodes, "max_edges": max_edges}}
    except (OSError, ValueError, TypeError):
        return None
    script = """
import json, sys, tempfile
from pathlib import Path
import networkx as nx
from graphify.exporters.html import to_html
graph_file, output = map(Path, sys.argv[1:3]); data = json.loads(graph_file.read_text(encoding='utf-8'))
nodes = [{'id': str(n['id']), 'label': str(n.get('name', n['id'])), 'kind': str(n.get('kind', 'FUNCTION'))} for n in data.get('nodes', [])]
links = [{'source': e.get('from', e.get('source')), 'target': e.get('to', e.get('target')), 'kind': e.get('kind', 'CALLS')} for e in (data.get('edges') or data.get('links') or [])]
g = nx.node_link_graph({'directed': True, 'nodes': nodes, 'links': links}, edges='links')
to_html(g, {0: [n['id'] for n in nodes]}, output)
"""
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONNOUSERSITE": "1"}
    if os.name == "nt":
        env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", "")
    try:
        with tempfile.TemporaryDirectory(dir=str(graph.parent)) as temporary:
            source = Path(temporary) / "bounded-graph.json"
            produced = Path(temporary) / "viewer.html"
            source.write_text(json.dumps(limited, ensure_ascii=False), encoding="utf-8")
            completed = subprocess.run([str(interpreter), "-I", "-c", script, str(source), str(produced)], cwd=str(graph.parent), env=env, capture_output=True, text=True, timeout=30, check=False)
            if completed.returncode != 0 or not produced.is_file() or produced.stat().st_size > 4 * 1024 * 1024:
                return None
            html_output = produced.read_text(encoding="utf-8")
            # Never publish a partial renderer response. The viewer is an
            # iframe document, so a syntactically complete local artifact is
            # preferable to a truncated best-effort preview.
            lowered = html_output.lower()
            if "<html" not in lowered or "</html>" not in lowered:
                return None
    except (OSError, subprocess.TimeoutExpired):
        return None
    cache = graphify_viewer_cache_path(project_path)
    temporary_cache = cache.with_suffix(cache.suffix + ".tmp")
    temporary_cache.write_text(html_output, encoding="utf-8")
    os.replace(temporary_cache, cache)
    return cache
