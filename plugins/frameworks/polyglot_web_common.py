"""Evidence-gated route helpers shared by optional polyglot framework packs.

Literal route declarations are useful boundary facts in their own right.  A
``ROUTE_HANDLES`` edge is added only when the target is an exact local method;
an inline callback therefore creates a confirmed route without pretending that
CodeSlicer resolved a named handler symbol.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from impact_engine.models import Edge, Evidence, Node
from impact_engine.plugin_architecture.contracts import PluginResult


def source_files(root: Path, suffixes: tuple[str, ...]) -> Iterable[tuple[str, str]]:
    ignored = {".git", ".impact_engine", ".codeslicer", "node_modules", "bin", "obj", "vendor", "generated"}
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in suffixes:
            continue
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue
        if ignored.intersection(rel.parts):
            continue
        try:
            yield rel.as_posix(), path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue


def join_path(prefix: str, path: str) -> str:
    parts = [part.strip("/") for part in (prefix, path) if part and part.strip("/")]
    return "/" + "/".join(parts) if parts else "/"


def method_for(graph, *, language: str, name: str, file: str, owner: str | None = None):
    # Tree-sitter fragments preserve language at graph level in several
    # extractors rather than copying it to every method node.  Restrict by the
    # exact source file below; requiring a per-node language property would
    # silently discard otherwise exact local symbols.
    candidates = [node for node in graph.nodes if node.kind in {"METHOD", "FUNCTION"} and node.name == name]
    in_file = [node for node in candidates if str(node.properties.get("file") or "") == file]
    if in_file:
        candidates = in_file
    if owner:
        owned = [node for node in candidates if str(node.properties.get("scope") or node.id).startswith(f"{owner}.")]
        if owned:
            candidates = owned
    return candidates[0] if len(candidates) == 1 else None


def add_literal_route(
    graph,
    *,
    framework: str,
    language: str,
    method: str,
    path: str,
    file: str,
    line: int,
):
    """Add a source-backed literal route, without inferring its handler."""
    route_id = f"HTTP {method.upper()} {path}"
    route = graph.get_node(route_id)
    if route is None:
        route = Node(route_id, "ROUTE", route_id, {
            "file": file, "line": line, "language": language,
            "http_method": method.upper(), "path": path,
            "framework": framework, "boundary_category": "api",
            "confidence_status": "confirmed",
            "handler_resolution": "not_requested",
        })
        graph.add_node(route)
    return route


def add_route(
    graph,
    *,
    framework: str,
    language: str,
    method: str,
    path: str,
    handler: str,
    file: str,
    line: int,
    owner: str | None = None,
    edge_kind: str = "ROUTE_HANDLES",
    direction: str = "route_to_handler",
    confidence: float = 0.86,
) -> bool:
    """Add a route/client relation only when its local method symbol is exact."""
    # Go router examples commonly pass a typed receiver method (`rs.List`).
    # The receiver binding is already validated by the language graph; route
    # attachment needs the local method declaration's terminal symbol.
    handler = handler.rsplit(".", 1)[-1]
    target = method_for(graph, language=language, name=handler, file=file, owner=owner)
    if target is None:
        return False
    route_id = add_literal_route(
        graph, framework=framework, language=language, method=method,
        path=path, file=file, line=line,
    ).id
    from_node, to_node = (route_id, target.id) if direction == "route_to_handler" else (target.id, route_id)
    edge_id = f"plugin_{framework.replace('.', '_').replace('-', '_')}__{edge_kind.lower()}__{from_node}__{to_node}"
    if any(edge.id == edge_id for edge in graph.edges):
        return False
    graph.add_edge(Edge(
        id=edge_id, kind=edge_kind, from_node=from_node, to_node=to_node,
        source="SUPPORT_PACK", confidence=confidence,
        evidence=[Evidence(file=file, line=line, description=f"{framework}: literal {method.upper()} {path} -> {handler}", source="local-framework-pack")],
        properties={
            "framework": framework, "http_method": method.upper(), "path": path,
            "resolution_status": "resolved_exact", "confidence_status": "confirmed",
            "support_pack_library": framework, "support_pack_id": framework,
            "support_pack_rule_id": f"{framework}-literal-route", "resolver_hook_name": f"{framework}_resolver",
            "provenance": {"plugin_id": f"framework.{language}.{framework}", "rule_id": f"{framework}-literal-route"},
        },
    ))
    return True


def add_framework_candidate(
    graph,
    *,
    framework: str,
    language: str,
    registration: str,
    handler: str,
    file: str,
    line: int,
) -> bool:
    """Record a framework registration as a likely, never-confirmed edge.

    The callsite proves that a registration occurred, but structural parsers
    alone cannot prove receiver type, factory identity, or runtime ordering.
    This representation is intentionally consumed by the adaptive candidate
    layer rather than promoted into the canonical confirmed path.
    """
    target = method_for(graph, language=language, name=handler.rsplit(".", 1)[-1], file=file)
    if target is None:
        return False
    node_id = f"FRAMEWORK {framework} {registration} {file}:{line}"
    if graph.get_node(node_id) is None:
        graph.add_node(Node(node_id, "ROUTE", registration, {
            "file": file, "line": line, "language": language,
            "framework": framework, "boundary_category": "middleware",
            "candidate_only": True,
        }))
    edge_id = f"plugin_{framework.replace('.', '_').replace('-', '_')}__candidate__{node_id}__{target.id}"
    if any(edge.id == edge_id for edge in graph.edges):
        return False
    graph.add_edge(Edge(
        id=edge_id, kind="MAY_CALL", from_node=node_id, to_node=target.id,
        source="SUPPORT_PACK", confidence=0.72,
        evidence=[Evidence(file=file, line=line, description=f"{framework}: {registration} registers {handler}; receiver/runtime ordering not type-validated", source="local-framework-pack")],
        properties={
            "status": "likely", "resolution_status": "framework_candidate",
            "validation_status": "not_validated", "framework": framework,
            "support_pack_library": framework, "support_pack_id": framework,
            "support_pack_rule_id": f"{framework}-middleware-registration",
            "resolver_hook_name": f"{framework}_resolver",
            "reason_not_confirmed": "framework registration has no full receiver/type validation",
        },
    ))
    return True


def result(graph, pack_id: str, framework: str, routes: int) -> PluginResult:
    graph.metadata.setdefault("polyglot_framework_features", {})[framework] = {
        "status": "supported" if routes else "limited",
        "literal_routes": routes,
        "review_usable": bool(routes),
        "review_usable_features": ["literal_route", "literal_route_to_local_handler"],
        "note": "Literal declarations are confirmed; route-to-handler edges require an exact extracted local handler.",
    }
    return PluginResult(graph=graph, provenance={"pack_id": pack_id, "framework": framework, "literal_routes": routes})
