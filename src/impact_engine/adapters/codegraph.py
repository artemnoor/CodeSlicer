"""Safe compatibility normalizer for local CodeGraph-like JSON artifacts."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .contracts import normalize_overlay
from .graphify import _recursive_allowlist, _safe_pointer, _safe_range, _safe_relative_path, _safe_text


SUPPORTED_EDGE_KINDS = {
    "IMPORT": "IMPORTS",
    "IMPORTS": "IMPORTS",
    "CALL": "CALLS",
    "CALLS": "CALLS",
    "CONTAINS": "CONTAINS",
}


def _diagnostic(code: str, message: str, severity: str = "warning") -> dict[str, str]:
    return {"code": code, "severity": severity, "message": message}


def parse_codegraph_json(data: Any) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Validate only the small interoperable CodeGraph subset.

    Unknown shapes are returned as diagnostics instead of being coerced into
    nodes or edges. This function intentionally does not mutate a canonical
    GraphDocument.
    """
    diagnostics: list[dict[str, str]] = []
    if not isinstance(data, dict):
        return {"nodes": [], "edges": []}, [_diagnostic("unsupported_schema", "CodeGraph artifact must be a JSON object", "error")]
    nodes = data.get("nodes")
    edges = data.get("edges", data.get("links"))
    if not isinstance(nodes, list):
        return {"nodes": [], "edges": []}, [_diagnostic("unsupported_schema", "CodeGraph artifact requires a nodes array", "error")]
    if edges is None:
        diagnostics.append(_diagnostic("incomplete_schema", "CodeGraph artifact has no edges/links array"))
        edges = []
    elif not isinstance(edges, list):
        diagnostics.append(_diagnostic("incomplete_schema", "CodeGraph edges/links must be an array", "error"))
        edges = []
    if not any(isinstance(node, dict) and (node.get("id") or node.get("key") or node.get("file") or node.get("path")) for node in nodes):
        diagnostics.append(_diagnostic("unsupported_schema", "No supported CodeGraph node identity was found", "error"))
    return {"nodes": [node for node in nodes if isinstance(node, dict)], "edges": [edge for edge in edges if isinstance(edge, dict)]}, diagnostics


def _node_id(node: dict[str, Any], index: int) -> str:
    return _safe_text(node.get("id") or node.get("key") or node.get("symbol") or node.get("file") or node.get("path"), max_length=512) or f"node_{index}"


def _source(node_or_edge: dict[str, Any], artifact_path: str) -> dict[str, Any]:
    result = {
        "adapter_id": "codegraph",
        "source": "codegraph",
        "source_artifact_path": str(Path(artifact_path).resolve()),
    }
    if node_or_edge.get("pointer"):
        result["source_pointer"] = node_or_edge["pointer"]
    if node_or_edge.get("source_file") or node_or_edge.get("file"):
        result["source_file"] = node_or_edge.get("source_file") or node_or_edge.get("file")
    if node_or_edge.get("source_location") or node_or_edge.get("range"):
        result["source_location"] = node_or_edge.get("source_location") or node_or_edge.get("range")
    return result


def _resolution(item: dict[str, Any], *, is_edge: bool) -> tuple[str, str]:
    raw_value = item.get("resolution") or item.get("confidence") or ""
    raw = (_safe_text(raw_value, max_length=80) or "").lower() if isinstance(raw_value, str) else ""
    has_location = bool(item.get("source_file")) and bool(item.get("source_location"))
    if raw in {"confirmed", "extracted", "exact"} and (has_location or not is_edge):
        return "confirmed", "confirmed"
    if raw in {"unresolved", "ambiguous", "unknown"}:
        return "unresolved", "unresolved"
    if raw or has_location:
        return "likely", "likely"
    return "unresolved", "unresolved"


def _sanitize_codegraph_input(data: Any, project_root: str | Path) -> tuple[dict[str, Any], list[dict[str, str]]]:
    normalized, diagnostics = parse_codegraph_json(data)
    safe_nodes: list[dict[str, Any]] = []
    for index, raw in enumerate(normalized["nodes"]):
        raw_properties = raw.get("properties") if isinstance(raw.get("properties"), dict) else {}
        safe_properties = _recursive_allowlist(raw_properties, {
            "path": None,
            "file": None,
            "range": {
                "start": {"line": None, "character": None, "column": None, "start_line": None, "start_column": None},
                "end": {"line": None, "character": None, "column": None, "end_line": None, "end_column": None},
                "line": None, "character": None, "column": None,
                "start_line": None, "start_column": None, "end_line": None, "end_column": None,
            },
        })
        path = _safe_relative_path(raw.get("file") or raw.get("path") or safe_properties.get("file") or safe_properties.get("path"), project_root)
        location = _safe_range(raw.get("range") or raw.get("location") or raw.get("source_location") or safe_properties.get("range"))
        node = {
            "id": _node_id(raw, index),
            "kind": _safe_text(raw.get("kind") or raw.get("type"), max_length=80) or ("FILE" if path else "SYMBOL"),
            "name": _safe_text(raw.get("name") or raw.get("symbol"), max_length=512) or _node_id(raw, index),
        }
        if path:
            node["file"] = path
        if location:
            node["range"] = location
        pointer = _safe_pointer(raw.get("pointer") or raw.get("json_pointer"))
        if pointer:
            node["pointer"] = pointer
        safe_nodes.append(node)
    safe_edges: list[dict[str, Any]] = []
    for index, raw in enumerate(normalized["edges"]):
        source_id = _safe_text(raw.get("from") or raw.get("source") or raw.get("source_id"), max_length=512)
        target_id = _safe_text(raw.get("to") or raw.get("target") or raw.get("target_id"), max_length=512)
        kind = _safe_text(raw.get("kind") or raw.get("type") or raw.get("relation"), max_length=80)
        if not source_id or not target_id:
            diagnostics.append(_diagnostic("unresolved_edge", f"Skipped CodeGraph edge {index} without safe endpoints"))
            continue
        edge: dict[str, Any] = {
            "id": _safe_text(raw.get("id"), max_length=512) or f"edge_{index}_{source_id}_{target_id}",
            "from": source_id, "to": target_id, "kind": kind or "",
        }
        source_file = _safe_relative_path(raw.get("file") or raw.get("path") or raw.get("source_file"), project_root)
        source_location = _safe_range(raw.get("range") or raw.get("location") or raw.get("source_location"))
        if source_file:
            edge["source_file"] = source_file
        if source_location:
            edge["source_location"] = source_location
        pointer = _safe_pointer(raw.get("pointer") or raw.get("json_pointer"))
        if pointer:
            edge["pointer"] = pointer
        for key in ("confidence", "resolution"):
            value = _safe_text(raw.get(key), max_length=80)
            if value:
                edge[key] = value
        safe_edges.append(edge)
    return {"nodes": safe_nodes, "edges": safe_edges}, diagnostics


def build_codegraph_overlay(
    data: Any,
    *,
    artifact_path: str,
    project_root: str | Path,
    freshness: dict[str, Any] | None = None,
    enabled: bool = False,
) -> dict[str, Any]:
    normalized, diagnostics = _sanitize_codegraph_input(data, project_root)
    raw_nodes = normalized["nodes"]
    raw_edges = normalized["edges"]
    nodes: list[dict[str, Any]] = []
    node_ids: set[str] = set()
    for index, raw in enumerate(raw_nodes):
        node_id = _node_id(raw, index)
        node_ids.add(node_id)
        kind = str(raw.get("kind") or raw.get("type") or ("FILE" if raw.get("file") or raw.get("path") else "SYMBOL")).upper()
        node_resolution, _ = _resolution(raw, is_edge=False)
        nodes.append({
            "id": node_id, "kind": kind, "name": str(raw.get("name") or raw.get("label") or raw.get("symbol") or node_id),
            "resolution": node_resolution, "confidence": node_resolution,
            "source": "codegraph", "evidence_class": "DOC_INFERRED", "confirmed": node_resolution == "confirmed",
            "participates_in_ranking": False, "provenance": _source(raw, artifact_path),
            "properties": {"overlay_only": True, "external_tool": "codegraph", "file": raw.get("file") or raw.get("path"), "range": raw.get("range") or raw.get("location")},
        })
    edges: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_edges):
        source_id = str(raw.get("from") or raw.get("source") or raw.get("source_id") or "")
        target_id = str(raw.get("to") or raw.get("target") or raw.get("target_id") or "")
        kind_raw = str(raw.get("kind") or raw.get("type") or raw.get("relation") or "").upper()
        kind = SUPPORTED_EDGE_KINDS.get(kind_raw)
        if not kind:
            diagnostics.append(_diagnostic("unsupported_edge_kind", f"Skipped unsupported CodeGraph edge kind: {kind_raw or 'missing'}"))
            continue
        if not source_id or not target_id or source_id not in node_ids or target_id not in node_ids:
            diagnostics.append(_diagnostic("unresolved_edge", f"Skipped dangling CodeGraph edge {source_id}->{target_id}"))
            continue
        resolution, confidence = _resolution(raw, is_edge=True)
        edges.append({
            "id": str(raw.get("id") or f"edge_{index}_{source_id}_{target_id}"), "kind": kind, "from": source_id, "to": target_id,
            "resolution": resolution, "confidence": confidence, "source": "codegraph", "evidence_class": "DOC_INFERRED",
            "confirmed": resolution == "confirmed", "participates_in_ranking": False,
            "provenance": _source(raw, artifact_path), "properties": {"overlay_only": True, "external_tool": "codegraph", "relation": kind_raw},
        })
    if not edges and raw_edges:
        diagnostics.append(_diagnostic("incomplete_graph", "No supported, non-dangling CodeGraph edges were imported"))
    has_error = any(item.get("severity") == "error" for item in diagnostics)
    availability = "unsupported" if any(item.get("code") == "unsupported_schema" for item in diagnostics) else ("incomplete" if diagnostics else "ready")
    return normalize_overlay(
        adapter_id="codegraph", adapter_version="1.0", source_kind="CODEGRAPH_OVERLAY",
        evidence_class="DOC_INFERRED", confidence="confirmed_or_likely",
        freshness=freshness or {"status": "unverified", "verified": False},
        local_artifact_reference={"path": str(Path(artifact_path).resolve())}, nodes=nodes, edges=edges,
        diagnostics=diagnostics, enabled=enabled, availability="unsupported" if has_error and availability == "ready" else availability,
    )
