"""Evidence-backed route extraction for Next.js filesystem conventions."""
from __future__ import annotations

import re
from pathlib import Path

from impact_engine.models import Edge, Evidence, GraphDocument, Node
from impact_engine.scope import iter_project_files


_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx"}
_HTTP_METHOD_RE = re.compile(r"\bexport\s+(?:async\s+)?function\s+(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\b")
_PAGE_HANDLER_RE = re.compile(r"\bexport\s+default\s+(?:async\s+)?function\s*([A-Za-z_$][\w$]*)?")


def apply_nextjs_routes(graph: GraphDocument, project_path: str | Path) -> GraphDocument:
    """Add routes only when an on-disk Next.js convention proves them.

    This deliberately does not infer client navigation or dynamic data flows.
    It maps the stable App Router and Pages Router file-system contracts to
    concrete source handlers and leaves absent handlers unresolved.
    """
    root = Path(project_path)
    if not root.is_dir():
        return graph
    candidates = [path for path in iter_project_files(root) if path.suffix.lower() in _EXTENSIONS]
    route_count = 0
    for path in candidates:
        rel = path.relative_to(root).as_posix()
        parts = Path(rel).parts
        route_path: str | None = None
        methods: list[str] = []
        handler_names: list[str] = []
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        if "app" in parts and path.stem == "route":
            app_index = parts.index("app")
            segments = [part for part in parts[app_index + 1:-1] if not (part.startswith("(") and part.endswith(")"))]
            route_path = "/" + "/".join(_normalise_app_segment(segment) for segment in segments)
            route_path = route_path.rstrip("/") or "/"
            methods = _HTTP_METHOD_RE.findall(source)
            handler_names = methods
        elif "app" in parts and path.stem == "page":
            app_index = parts.index("app")
            segments = [part for part in parts[app_index + 1:-1] if not (part.startswith("(") and part.endswith(")"))]
            route_path = "/" + "/".join(_normalise_app_segment(segment) for segment in segments)
            route_path = route_path.rstrip("/") or "/"
            methods = ["GET"]
            match = _PAGE_HANDLER_RE.search(source)
            handler_names = [match.group(1)] if match and match.group(1) else []
        elif len(parts) >= 3 and parts[0] == "pages" and parts[1] == "api":
            route_path = "/api/" + "/".join(parts[2:-1] + (path.stem,))
            route_path = route_path.replace("/index", "") or "/api"
            methods = ["*"]
            match = _PAGE_HANDLER_RE.search(source)
            handler_names = [match.group(1)] if match and match.group(1) else []

        if route_path is None or not methods:
            continue
        file_methods = [node for node in graph.nodes if str(node.properties.get("file") or node.properties.get("path") or "").replace("\\", "/") == rel and node.kind == "METHOD"]
        for method in methods:
            route_id = f"HTTP {method} {route_path}"
            if not any(node.id == route_id for node in graph.nodes):
                graph.add_node(Node(
                    id=route_id, kind="ROUTE", name=route_id,
                    properties={"file": rel, "line": 1, "framework": "nextjs", "route_path": route_path, "http_method": method},
                ))
            targets = [node for node in file_methods if node.name in handler_names]
            if method != "*":
                targets = [node for node in targets if node.name == method] or targets
            for handler in targets:
                edge_id = f"nextjs_route__{route_id}__{handler.id}"
                if not any(edge.id == edge_id for edge in graph.edges):
                    graph.add_edge(Edge(
                        id=edge_id, kind="ROUTE_HANDLES", from_node=route_id, to_node=handler.id,
                        source="INFERRED", confidence=0.86,
                        evidence=[Evidence(file=rel, line=handler.properties.get("line", 1), description="Next.js filesystem route convention")],
                        properties={"framework": "nextjs", "resolver": "filesystem_route"},
                    ))
            route_count += 1
    if route_count:
        graph.metadata["nextjs_routes"] = {"status": "applied", "routes": route_count, "evidence": "filesystem_conventions"}
    return graph


def _normalise_app_segment(segment: str) -> str:
    if segment.startswith("[[...") and segment.endswith("]]" ):
        return "*"
    if segment.startswith("[...") and segment.endswith("]"):
        return "*"
    if segment.startswith("[") and segment.endswith("]"):
        return "{" + segment[1:-1] + "}"
    return segment
