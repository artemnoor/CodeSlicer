from __future__ import annotations

from typing import Any, Dict, List, Optional

from .models import Evidence, ResolutionResult, ResolvedEdge, stable_id


_GRAPH_EDGE_KINDS = {
    "CALLS",
    "ROUTE_HANDLES",
    "HTTP_CALLS",
    "MATCHES_ENDPOINT",
    "DEPENDS_ON",
    "RESOLVES_TO",
}


def _route_node(method: Optional[str], path: Optional[str], fallback: str) -> str:
    if method and path:
        return f"HTTP {method.upper()} {path}"
    if path:
        return path
    return fallback


def _evidence_to_graph(evidence: Evidence) -> Dict[str, Any]:
    description = evidence.message or evidence.kind or "semantic binding evidence"
    item: Dict[str, Any] = {"description": description}
    if evidence.file is not None:
        item["file"] = evidence.file
    if evidence.line is not None:
        item["line"] = evidence.line
    return item


def _convert_edge(edge: ResolvedEdge) -> Optional[Dict[str, Any]]:
    if not edge.source or not edge.target or not edge.evidence:
        return None

    semantic_kind = edge.kind
    kind = semantic_kind
    source = edge.source
    target = edge.target
    method = edge.method.upper() if isinstance(edge.method, str) and edge.method else None
    path = edge.path or (edge.target if isinstance(edge.target, str) and edge.target.startswith("/") else None)

    if semantic_kind in {"ROUTE", "ROUTE_HANDLES"}:
        kind = "ROUTE_HANDLES"
        source = _route_node(method, path or edge.target, edge.target)
        target = edge.source
    elif semantic_kind == "HTTP_CALLS":
        target = _route_node(method, path or edge.target, edge.target) if (method or path) else edge.target
    elif semantic_kind == "MATCHES_ENDPOINT":
        kind = "MATCHES_ENDPOINT"
    elif semantic_kind not in _GRAPH_EDGE_KINDS:
        # Keep common semantic graph shape conservative. Unknown semantic edges become DEPENDS_ON.
        kind = "DEPENDS_ON"

    if not source or not target:
        return None

    graph_evidence = [_evidence_to_graph(ev) for ev in edge.evidence]
    if not graph_evidence:
        return None

    graph_id = stable_id("graph_edge", kind, source, target, method, path, semantic_kind)
    return {
        "id": graph_id,
        "kind": kind,
        "from_node": source,
        "to_node": target,
        "source": "INFERRED",
        "confidence": edge.confidence,
        "evidence": graph_evidence,
        "properties": {
            "resolver": "semantic_binding_layer",
            "semantic_edge_kind": semantic_kind,
            "method": method,
            "path": path,
        },
    }


def semantic_result_to_graph_edges(result: ResolutionResult) -> List[Dict[str, Any]]:
    """Convert semantic resolution output into Impact Engine-style graph edges.

    This adapter intentionally does not import or depend on Impact Engine. It emits plain
    dictionaries with stable deterministic IDs and the GraphDocument-compatible fields
    used by Impact Engine edge records.
    """
    edges: Dict[str, Dict[str, Any]] = {}
    for edge in result.resolved_edges:
        converted = _convert_edge(edge)
        if converted is None:
            continue
        edges[converted["id"]] = converted
    return [edges[key] for key in sorted(edges)]
