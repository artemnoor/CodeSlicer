"""Local HTTP API and static frontend host for the Impact Engine UI.

The browser never runs analysis logic and never receives a mock graph.  This
module is a thin same-origin boundary around the existing analysis and impact
query APIs.  It intentionally uses only the Python standard library so the
local distribution stays lightweight.
"""
from __future__ import annotations

import argparse
from importlib.resources import files as package_files
import json
import html
import os
import subprocess
import sys
import threading
import time
from dataclasses import asdict
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from impact_engine.analysis.pipeline import analyze_project_core
from impact_engine.inventory.scanner import scan_project_inventory
from impact_engine.impact import explain_edge, impact_query
from impact_engine.models import GraphDocument
from impact_engine.review import build_review_report
from impact_engine.modes import build_ci_report, build_inspect_report, build_investigate_report, to_sarif
from impact_engine.contracts import build_mode_response
from impact_engine.project_storage import ensure_project_storage
from impact_engine.persistence import AnalysisCancelled, CancellationToken, classify_path, daemon_status
from impact_engine.adapters.registry import AdapterRegistry
from impact_engine.adapters.lsp import configure_lsp, disable_lsp, lsp_privacy, map_lsp_overlay, probe_lsp, query_lsp
from impact_engine.adapters.otel import map_otel_overlay
from impact_engine.adapters.scip import map_scip_overlay
from impact_engine.adapters.boundary import map_boundary_overlay
from impact_engine.adapters.security import map_security_overlay
from impact_engine.adapters.joern import bounded_joern_context
from impact_engine.adapters.native import native_profile, run_native_operation
from impact_engine.graph_workspaces import build_workspace
from impact_engine.tool_runtime import ToolRuntime
from impact_engine.adapters.graphify_paths import find_graphify_graph


_OVERVIEW_LANGUAGE_SUFFIXES = {
    ".py": "python", ".js": "javascript", ".jsx": "javascript", ".ts": "typescript", ".tsx": "typescript",
    ".go": "go", ".java": "java", ".cs": "csharp",
}
_PROJECTION_HIGH_LEVEL_KINDS = {"SERVICE", "MODULE", "FILE", "ROUTE", "DATABASE", "QUEUE", "COMPONENT", "CLASS", "PACKAGE"}
# The browser uses this explicit capability rather than guessing endpoint
# availability.  That prevents a newly built frontend from repeatedly calling
# /api/tools on an older local-api process and presenting a misleading
# "tool not found" state.
LOCAL_API_CONTRACT_VERSION = "CodeSlicerLocalAPI/v2"


def _projection_values(value: Any) -> set[str]:
    if isinstance(value, str):
        return {item.strip().lower() for item in value.split(",") if item.strip()}
    if isinstance(value, (list, tuple, set)):
        return {str(item).strip().lower() for item in value if str(item).strip()}
    return set()


def _projection_relation_scope(edge: Any) -> str:
    properties = edge.properties if isinstance(getattr(edge, "properties", None), dict) else {}
    explicit = properties.get("relation_scope") or properties.get("directness")
    if isinstance(explicit, str) and explicit.lower() in {"direct", "transitive"}:
        return explicit.lower()
    if properties.get("transitive") is True:
        return "transitive"
    # A canonical graph edge is an explicitly stored relationship. Without a
    # transitive marker, do not infer a longer path that the graph did not store.
    return "direct"


def _adapter_evidence_sources(project_path: str) -> list[dict[str, Any]]:
    """Return a uniform, metadata-only catalog for mode/API consumers."""
    if not project_path:
        return []
    sources: list[dict[str, Any]] = [{
        "id": "codeslicer", "display_name": "CodeSlicer canonical graph", "source": "CodeSlicer",
        "role": "canonical", "enabled": True, "status": "ready", "freshness": {"status": "unknown", "verified": False},
        "entity_count": 0, "relationship_count": 0, "diagnostics": [],
        "privacy": {"mode": "local-only", "network_used": False}, "affects_review_ranking": True,
        "ranking_impact": "owner",
    }]
    for item in AdapterRegistry(project_path).list():
        artifact = item.get("artifact") or {}
        sources.append({
            "id": item.get("id"), "display_name": (item.get("manifest") or {}).get("display_name", item.get("id")),
            "source": item.get("id"), "role": "supplemental", "enabled": bool(item.get("enabled")),
            "status": item.get("status", "unknown"), "freshness": item.get("freshness", {"status": "unknown", "verified": False}),
            "entity_count": artifact.get("nodes", item.get("components", 0)),
            "relationship_count": artifact.get("edges", 0), "diagnostics": list(item.get("diagnostics") or [])[:8],
            "privacy": {"mode": "local-only", "network_used": False}, "affects_review_ranking": False,
            "ranking_impact": "none", "provenance": {
                "source_path": artifact.get("source_path"), "fingerprint": artifact.get("source_fingerprint"),
            },
        })
    return sources


def _adapter_mapping_summary_unchecked(project_path: str, adapter_id: str) -> dict[str, Any]:
    """Report whether an imported supplemental artifact maps to this graph."""
    graph, _ = _project_graph(project_path)
    if graph is None:
        return {"status": "unresolved", "matched_nodes": 0, "matched_relationships": 0, "unresolved_nodes": 0, "unresolved_relationships": 0}
    overlay = AdapterRegistry(project_path).overlay(adapter_id)
    if not overlay:
        return {"status": "not_evaluated", "matched_nodes": 0, "matched_relationships": 0, "unresolved_nodes": 0, "unresolved_relationships": 0}
    mapped = None
    if adapter_id == "lsp":
        mapped = map_lsp_overlay(overlay, graph)
    elif adapter_id == "scip":
        mapped = map_scip_overlay(overlay, graph)
    elif adapter_id in {"openapi", "asyncapi"}:
        mapped = map_boundary_overlay(overlay, graph)
    elif adapter_id == "otel":
        mapped = map_otel_overlay(overlay, graph)
    elif adapter_id in {"cyclonedx", "spdx", "sarif"}:
        mapped = map_security_overlay(overlay, graph)
    if mapped is not None and mapped.get("mapping_summary") is not None:
        raw = mapped["mapping_summary"]
        matched_nodes = int(raw.get("confirmed", raw.get("exact", 0)) or 0) + int(raw.get("likely", 0) or 0)
        unresolved_nodes = int(raw.get("unresolved", 0) or 0) + int(raw.get("ambiguous", 0) or 0)
        mapped_edges = mapped.get("edges") or []
        matched_relationships = sum(1 for edge in mapped_edges if edge.get("resolution") in {"confirmed", "likely"} or edge.get("confirmed") is True)
        unresolved_relationships = max(0, len(mapped_edges) - matched_relationships)
    else:
        canonical = list(graph.nodes)
        canonical_ids = {node.id for node in canonical}
        canonical_pairs = {
            (str(node.name).lower(), str(node.properties.get("file") or node.properties.get("path") or "").replace("\\", "/").lstrip("./").lower())
            for node in canonical if node.name
        }
        overlay_nodes = list(overlay.get("nodes") or [])
        matched_nodes = 0
        for node in overlay_nodes:
            props = node.get("properties") or {}
            name = str(node.get("name") or node.get("label") or "").lower()
            file_name = str(node.get("file") or node.get("source_file") or props.get("file") or props.get("path") or "").replace("\\", "/").lstrip("./").lower()
            if str(node.get("id") or "") in canonical_ids or (name, file_name) in canonical_pairs:
                matched_nodes += 1
        unresolved_nodes = max(0, len(overlay_nodes) - matched_nodes)
        overlay_edges = list(overlay.get("edges") or [])
        matched_relationships = sum(1 for edge in overlay_edges if edge.get("from") in canonical_ids and edge.get("to") in canonical_ids)
        unresolved_relationships = max(0, len(overlay_edges) - matched_relationships)
    total = matched_nodes + matched_relationships
    return {
        "status": "linked" if total else "unlinked",
        "matched_nodes": matched_nodes, "matched_relationships": matched_relationships,
        "unresolved_nodes": unresolved_nodes, "unresolved_relationships": unresolved_relationships,
    }


def _adapter_mapping_summary(project_path: str, adapter_id: str) -> dict[str, Any]:
    """Keep optional-adapter diagnostics from breaking the architecture view."""
    try:
        return _adapter_mapping_summary_unchecked(project_path, adapter_id)
    except Exception as exc:  # optional adapter failures must remain diagnostics, not API failures
        return {
            "status": "unresolved", "matched_nodes": 0, "matched_relationships": 0,
            "unresolved_nodes": 0, "unresolved_relationships": 0,
            "diagnostics": [f"mapping could not be evaluated: {exc}"],
        }


def _project_graph(project_path: str, graph_path: str | Path | None = None) -> tuple[GraphDocument | None, Path | None]:
    root = Path(project_path).expanduser().resolve()
    candidates = [Path(str(graph_path)).expanduser().resolve()] if graph_path else [root / ".impact_engine" / "graph.json", root / "graph.json"]
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            return GraphDocument.from_json(candidate.read_text(encoding="utf-8")), candidate
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return None, None


def _project_overview(project_path: str, state: "LocalApiState | None" = None) -> dict[str, Any]:
    root = Path(project_path).expanduser().resolve()
    analysis = {}
    graph: GraphDocument | None = None
    graph_path: Path | None = None
    if state is not None:
        snapshot = state.snapshot(include_graph=True)
        analysis = snapshot.get("analysis") or {}
        if snapshot.get("graph") and Path(str(snapshot.get("project_path") or "")).resolve() == root:
            try:
                graph = GraphDocument.from_dict(snapshot["graph"])
                graph_path = Path(str(analysis.get("graph_path"))).expanduser().resolve() if analysis.get("graph_path") else root / ".impact_engine" / "graph.json"
            except (ValueError, TypeError, OSError):
                graph = None
    if graph is None:
        graph, graph_path = _project_graph(str(root))
    inventory = analysis.get("inventory") or {}
    if not inventory:
        try:
            inventory = asdict(scan_project_inventory(str(root)))
        except (OSError, ValueError):
            inventory = {}
    files = list(inventory.get("files") or [])
    excluded: list[dict[str, str]] = []
    supported_counts: dict[str, int] = {}
    unsupported_files: list[str] = []
    for relative in files:
        classification = classify_path(str(relative))
        if classification != "source":
            excluded.append({"path": str(relative).replace("\\", "/"), "reason": classification})
            continue
        suffix = Path(str(relative)).suffix.lower()
        language = _OVERVIEW_LANGUAGE_SUFFIXES.get(suffix)
        if language:
            supported_counts[language] = supported_counts.get(language, 0) + 1
        elif suffix and suffix not in {".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".xml"}:
            unsupported_files.append(str(relative).replace("\\", "/"))
    languages = [{"language": language, "status": "supported", "files": count} for language, count in sorted(supported_counts.items())]
    if unsupported_files:
        languages.append({"language": "unknown", "status": "unsupported", "files": len(unsupported_files), "reason": "No active language plugin matched these source extensions"})
    graph_freshness: dict[str, Any]
    if not graph or not graph_path or not graph_path.is_file():
        graph_freshness = {"status": "missing", "verified": False, "graph_path": str(graph_path) if graph_path else None}
    else:
        try:
            graph_mtime = graph_path.stat().st_mtime
            latest_source = max((Path(root / str(relative)).stat().st_mtime for relative in files if Path(root / str(relative)).is_file()), default=graph_mtime)
            stale = latest_source > graph_mtime + 1.0
            graph_freshness = {"status": "stale" if stale else "fresh", "verified": not stale, "graph_path": str(graph_path), "reason": "source file is newer than graph" if stale else None}
        except OSError:
            graph_freshness = {"status": "unknown", "verified": False, "graph_path": str(graph_path)}
    metadata = graph.metadata if graph else {}
    incomplete = bool(metadata.get("incomplete")) or bool(metadata.get("diagnostics"))
    unsupported = bool(unsupported_files)
    if graph_freshness["status"] == "missing":
        health_status = "incomplete"
    elif graph_freshness["status"] == "stale":
        health_status = "stale"
    elif unsupported:
        health_status = "unsupported"
    elif incomplete:
        health_status = "incomplete"
    else:
        health_status = "ready"
    daemon = daemon_status(root)
    return {
        "status": health_status, "project": {"path": str(root), "name": root.name},
        "freshness": graph_freshness,
        "coverage": {"status": "unsupported" if unsupported else "complete" if languages else "unknown", "languages": languages, "unsupported_files": unsupported_files[:100], "supported_files": sum(supported_counts.values())},
        "cache": {"status": "ready" if (root / ".impact_engine").is_dir() else "missing", "path": str(root / ".impact_engine")},
        "daemon": {"status": daemon.get("status", "stopped"), "pid": daemon.get("pid"), "port": daemon.get("port")},
        "excluded": {"count": len(excluded), "files": excluded[:100], "reasons": sorted({item["reason"] for item in excluded})},
        "graph": {"available": bool(graph), "nodes": len(graph.nodes) if graph else 0, "edges": len(graph.edges) if graph else 0},
        "diagnostics": list(metadata.get("diagnostics") or [])[:12] if isinstance(metadata.get("diagnostics"), list) else [],
        "evidence_sources": _adapter_evidence_sources(str(root)),
        "privacy": {"mode": "local-only", "network_used": False, "telemetry": False},
        "actions": {"review": True, "inspect": bool(graph), "investigate": bool(graph), "architecture": True},
    }


def _graph_projection(project_path: str, payload: dict[str, Any]) -> dict[str, Any]:
    graph, graph_path = _project_graph(project_path, payload.get("graph_path"))
    if graph is None:
        return {"status": "missing", "freshness": {"status": "missing", "verified": False}, "level": payload.get("level", "overview"), "nodes": [], "edges": [], "total_nodes": 0, "total_edges": 0, "truncated": False, "diagnostics": ["canonical graph is missing"], "privacy": {"mode": "local-only", "network_used": False}, "evidence_sources": _adapter_evidence_sources(project_path)}
    level = str(payload.get("level") or "overview").lower()
    if level not in {"overview", "detail"}:
        raise ValueError("level must be overview or detail")
    query = str(payload.get("query") or "").strip().lower()
    filters = payload.get("filters") if isinstance(payload.get("filters"), dict) else {}
    node_kinds = {str(value).upper() for value in (filters.get("node_kinds") or [])}
    edge_kinds = {str(value).upper() for value in (filters.get("edge_kinds") or [])}
    evidence_classes = _projection_values(filters.get("evidence_classes") or filters.get("evidence_class"))
    evidence_sources = _projection_values(filters.get("evidence_sources") or filters.get("evidence_source"))
    relation_scopes = _projection_values(filters.get("relation_scopes") or filters.get("relation_scope"))
    confidence = filters.get("min_confidence")
    try:
        min_confidence = float(confidence) if confidence is not None else 0.0
    except (TypeError, ValueError):
        min_confidence = 0.0
    candidate_nodes = list(graph.nodes)
    if level == "overview":
        high_level = [node for node in candidate_nodes if node.kind in _PROJECTION_HIGH_LEVEL_KINDS]
        if high_level:
            candidate_nodes = high_level
    if query:
        candidate_nodes = [node for node in candidate_nodes if query in node.id.lower() or query in node.name.lower() or query in str(node.properties.get("file") or node.properties.get("path") or "").lower()]
    if node_kinds:
        candidate_nodes = [node for node in candidate_nodes if node.kind.upper() in node_kinds]
    if evidence_classes:
        candidate_nodes = [node for node in candidate_nodes if "static_extracted" in evidence_classes]
    if evidence_sources:
        candidate_nodes = [node for node in candidate_nodes if "codeslicer" in evidence_sources]
    max_nodes = min(max(int(payload.get("max_nodes", 120)), 1), 300)
    max_edges = min(max(int(payload.get("max_edges", 200)), 1), 600)
    selected_nodes = candidate_nodes[:max_nodes]
    selected_ids = {node.id for node in selected_nodes}
    candidate_edges = [edge for edge in graph.edges if edge.from_node in selected_ids and edge.to_node in selected_ids and float(edge.confidence) >= min_confidence]
    if edge_kinds:
        candidate_edges = [edge for edge in candidate_edges if edge.kind.upper() in edge_kinds]
    if evidence_classes:
        candidate_edges = [edge for edge in candidate_edges if "static_extracted" in evidence_classes]
    if evidence_sources:
        candidate_edges = [edge for edge in candidate_edges if "codeslicer" in evidence_sources or str(edge.source).lower() in evidence_sources]
    if relation_scopes:
        candidate_edges = [edge for edge in candidate_edges if _projection_relation_scope(edge) in relation_scopes]
    nodes = [{**node.to_dict(), "canonical": True, "source": "CodeSlicer", "evidence_source": "CodeSlicer", "evidence_class": "STATIC_EXTRACTED", "overlay": False} for node in selected_nodes]
    edges = [{**edge.to_dict(), "canonical": True, "source": edge.source, "evidence_source": "CodeSlicer", "evidence_class": "STATIC_EXTRACTED", "relation_scope": _projection_relation_scope(edge), "overlay": False} for edge in candidate_edges[:max_edges]]
    overview = _project_overview(project_path)
    freshness = dict(overview.get("freshness") or {"status": "unknown", "verified": False})
    health_status = overview.get("status") or "unknown"
    # Projection availability is distinct from whole-project coverage.  A
    # valid local graph can still render while one optional language/plugin is
    # unsupported; do not return contradictory "unsupported" plus nodes/edges.
    projection_status = health_status if health_status in {"stale", "missing", "unknown"} else "ready"
    projection_diagnostics = ["progressive overview shows structural node kinds first"] if level == "overview" else []
    if health_status not in {"ready", "fresh"}:
        projection_diagnostics.append(f"project health is {health_status}; projection availability does not imply complete language coverage")
    if freshness.get("status") not in {"fresh", "unknown"}:
        projection_diagnostics.append(f"canonical graph freshness is {freshness.get('status')}; refresh analysis before relying on this view")
    return {
        "status": projection_status, "health_status": health_status, "freshness": freshness,
        "level": level, "canonical_only": True, "nodes": nodes, "edges": edges,
        "total_nodes": len(candidate_nodes), "total_edges": len(candidate_edges),
        "truncated": len(candidate_nodes) > max_nodes or len(candidate_edges) > max_edges,
        "filters": {"query": query, "node_kinds": sorted(node_kinds), "edge_kinds": sorted(edge_kinds), "evidence_classes": sorted(evidence_classes), "evidence_sources": sorted(evidence_sources), "relation_scopes": sorted(relation_scopes), "min_confidence": min_confidence},
        "diagnostics": projection_diagnostics,
        "privacy": {"mode": "local-only", "network_used": False}, "evidence_sources": _adapter_evidence_sources(project_path),
    }


def _graph_workspace(project_path: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Expose one task-specific graph without merging it into CodeSlicer.

    This endpoint is intentionally separate from ``/api/graph/projection``:
    the latter is the canonical graph used by Review, while this one renders a
    selected tool graph or a conservative bridge-only view.
    """
    canonical, _ = _project_graph(project_path, payload.get("graph_path"))
    return build_workspace(
        project_path,
        canonical,
        workspace_id=str(payload.get("workspace") or "impact").lower(),
        source_id=str(payload.get("source_id") or "").lower() or None,
        max_nodes=int(payload.get("max_nodes", 120)),
        max_edges=int(payload.get("max_edges", 200)),
    )


def _mode_api_report(mode: str, report: dict[str, Any]) -> dict[str, Any]:
    """Serialize one legacy mode report through the localhost v2 envelope."""

    project_path = report.get("project") or report.get("project_path") or ""
    project = {
        "path": str(project_path),
        "name": Path(str(project_path)).name if project_path else None,
        "graph_path": (report.get("graph_freshness") or {}).get("graph_path"),
    }
    adapter_statuses = AdapterRegistry(str(project_path)).list() if project_path else []
    compact_adapter_warnings = []
    for adapter in adapter_statuses:
        if adapter.get("id") == "scip" and adapter.get("status") in {"stale", "unverified"}:
            compact_adapter_warnings.append("SCIP semantic index is stale or unverified; it does not increase Review confidence.")
        if adapter.get("id") == "lsp" and adapter.get("status") == "stale":
            compact_adapter_warnings.append("LSP semantic context is stale; it is context only and does not increase Review risk or ranking.")
        if adapter.get("id") in {"openapi", "asyncapi"} and adapter.get("status") in {"stale", "unverified"}:
            compact_adapter_warnings.append(f"{adapter.get('id')} specification is stale or unverified; boundary context does not increase Review risk or ranking.")
        if adapter.get("id") == "otel" and adapter.get("status") in {"stale", "unverified"}:
            compact_adapter_warnings.append("OpenTelemetry trace is stale or unverified; runtime context does not increase Review risk or ranking.")
        if adapter.get("id") in {"cyclonedx", "spdx", "sarif"} and adapter.get("status") in {"stale", "unverified"}:
            compact_adapter_warnings.append(f"{adapter.get('id')} security report is stale or unverified; it does not increase Review risk, ranking, or test recommendations.")
        if adapter.get("id") in {"graphify", "codegraph"} and adapter.get("status") in {"stale", "unverified", "incomplete", "unsupported"}:
            compact_adapter_warnings.append(f"{adapter.get('id')} external graph is {adapter.get('status')}; it is overlay context only and does not change Review ranking.")
    envelope = build_mode_response(
        mode,
        project=project,
        freshness=report.get("graph_freshness"),
        coverage=report.get("coverage"),
        warnings=list(report.get("warnings", [])) + compact_adapter_warnings,
        adapters=adapter_statuses or report.get("adapters", []),
        result=report,
    )
    # Explicit migration handle for clients that still consume the flat mode
    # builders directly (CLI/MCP remain backward compatible).
    envelope["legacy_schema_version"] = report.get("schema_version")
    envelope["contract_version"] = report.get("contract_version", "CodeSlicerModeContract/v1")
    envelope["graph_freshness"] = report.get("graph_freshness", envelope["freshness"])
    envelope["legacy_report"] = report
    envelope["evidence_sources"] = _adapter_evidence_sources(str(project_path)) if project_path else []
    envelope["result"]["evidence_sources"] = envelope["evidence_sources"]
    return envelope


def _mode_api_response(mode: str, report: dict[str, Any]) -> dict[str, Any]:
    envelope = _mode_api_report(mode, report)
    # The envelope is both the endpoint response and the ``report`` field.
    # Keeping the latter preserves the existing local API shape for clients.
    return {"status": "ok", **envelope, "report": envelope}


def _bounded_overlay(overlay: dict[str, Any] | None, *, max_nodes: int = 120, max_edges: int = 160) -> dict[str, Any] | None:
    if not overlay:
        return None
    bounded = dict(overlay)
    all_nodes = list(overlay.get("nodes") or [])
    all_edges = list(overlay.get("edges") or [])
    bounded["nodes"] = all_nodes[:max_nodes]
    bounded["edges"] = all_edges[:max_edges]
    bounded["bounded"] = True
    bounded["total_nodes"] = len(all_nodes)
    bounded["total_edges"] = len(all_edges)
    if len(all_nodes) > max_nodes or len(all_edges) > max_edges:
        bounded["diagnostics"] = list(bounded.get("diagnostics") or []) + [{
            "code": "bounded_overlay", "severity": "info",
            "message": f"Overlay display bounded to {max_nodes} nodes and {max_edges} edges",
        }]
    return bounded


def _semantic_graph(project_path: str, report: dict[str, Any], graph_path: str | Path | None = None) -> GraphDocument | None:
    freshness = report.get("graph_freshness") or {}
    candidate = graph_path or freshness.get("graph_path") or (Path(project_path).resolve() / ".impact_engine" / "graph.json")
    path = Path(str(candidate)).expanduser()
    if not path.is_file():
        return None
    try:
        return GraphDocument.from_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _semantic_evidence(project_path: str, report: dict[str, Any], graph_path: str | Path | None = None) -> dict[str, Any]:
    registry = AdapterRegistry(project_path)
    status = registry.status("scip")
    base = {
        "adapter_id": "scip", "status": status.get("status"), "enabled": bool(status.get("enabled")),
        "freshness": status.get("freshness", {"status": "unknown", "verified": False}),
        "network_used": False, "symbol_id": None, "definitions": [],
        "reference_ranges": [], "references_count": 0, "implementations": [],
        "mapping": {"status": "unresolved"}, "diagnostics": list(status.get("diagnostics") or [])[:5],
    }
    overlay = registry.overlay("scip")
    graph = _semantic_graph(project_path, report, graph_path)
    if not overlay or not graph:
        return base
    mapped = map_scip_overlay(overlay, graph)
    resolved_id = str((report.get("resolved_entity") or {}).get("id") or "")
    semantic = next((node for node in mapped.get("nodes", []) if node.get("mapping", {}).get("canonical_node_id") == resolved_id), None)
    if semantic is None:
        return {**base, "status": status.get("status"), "diagnostics": list(mapped.get("diagnostics") or [])[-5:]}
    implementations = [edge for edge in mapped.get("edges", []) if edge.get("from") == semantic.get("id") and edge.get("kind") == "IMPLEMENTS" and edge.get("resolution") in {"confirmed", "likely", "stale"}]
    references = [edge for edge in mapped.get("edges", []) if edge.get("to") == semantic.get("id") and edge.get("kind") == "REFERENCES" and edge.get("resolution") in {"confirmed", "likely", "stale"}]
    return {
        **base, "status": status.get("status"), "symbol_id": semantic.get("semantic_id"),
        "definitions": semantic.get("definitions") or [], "reference_ranges": semantic.get("reference_ranges") or [],
        "references_count": len(references), "implementations": implementations[:20],
        "mapping": semantic.get("mapping") or {"status": "unresolved"},
        "diagnostics": list(mapped.get("diagnostics") or [])[-5:],
    }


def _lsp_evidence(project_path: str, report: dict[str, Any], graph_path: str | Path | None = None) -> dict[str, Any]:
    registry = AdapterRegistry(project_path)
    status = registry.status("lsp")
    base = {
        "adapter_id": "lsp", "evidence_class": "LSP_RUNTIME", "status": status.get("status"),
        "enabled": bool(status.get("enabled")), "freshness": status.get("freshness", {"status": "unknown", "verified": False}),
        "source_server": status.get("executable"), "capabilities": status.get("capabilities", {}),
        "network_used": False, "privacy": lsp_privacy(), "nodes": [], "edges": [], "mapping_summary": {"confirmed": 0, "ambiguous": 0, "unresolved": 0},
        "diagnostics": list(status.get("diagnostics") or [])[:5],
    }
    overlay = registry.overlay("lsp")
    graph = _semantic_graph(project_path, report, graph_path)
    if not overlay or not graph:
        return base
    mapped = map_lsp_overlay(overlay, graph)
    resolved_id = str((report.get("resolved_entity") or {}).get("id") or "")
    selected_nodes = [node for node in mapped.get("nodes", []) if node.get("mapping", {}).get("canonical_node_id") == resolved_id]
    selected_edges = [edge for edge in mapped.get("edges", []) if edge.get("from") == resolved_id or edge.get("to") == resolved_id]
    return {
        **base, "status": status.get("status"), "nodes": selected_nodes[:40], "edges": selected_edges[:40],
        "mapping_summary": mapped.get("mapping_summary", base["mapping_summary"]),
        "diagnostics": list(mapped.get("diagnostics") or status.get("diagnostics") or [])[-5:],
        "capability": overlay.get("capability"), "timestamp": overlay.get("timestamp"),
    }


def _bounded_semantic_context(project_path: str, report: dict[str, Any], graph_path: str | Path | None = None, *, max_items: int = 40) -> dict[str, Any]:
    evidence = _semantic_evidence(project_path, report, graph_path)
    return {
        "status": evidence.get("status"), "freshness": evidence.get("freshness"), "network_used": False,
        "symbol_id": evidence.get("symbol_id"), "definitions": (evidence.get("definitions") or [])[:max_items],
        "reference_ranges": (evidence.get("reference_ranges") or [])[:max_items],
        "implementations": (evidence.get("implementations") or [])[:max_items],
        "mapping": evidence.get("mapping"), "diagnostics": (evidence.get("diagnostics") or [])[:5],
        "bounded": True, "max_items": max_items,
    }


def _bounded_lsp_context(project_path: str, report: dict[str, Any], graph_path: str | Path | None = None, *, max_items: int = 40) -> dict[str, Any]:
    evidence = _lsp_evidence(project_path, report, graph_path)
    return {
        "status": evidence.get("status"), "freshness": evidence.get("freshness"), "capability": evidence.get("capability"),
        "source_server": evidence.get("source_server"), "nodes": (evidence.get("nodes") or [])[:max_items],
        "edges": (evidence.get("edges") or [])[:max_items], "mapping_summary": evidence.get("mapping_summary"),
        "diagnostics": (evidence.get("diagnostics") or [])[:5], "bounded": True, "max_items": max_items,
        "network_used": False, "privacy": evidence.get("privacy", lsp_privacy()),
    }


def _boundary_evidence(project_path: str, report: dict[str, Any], graph_path: str | Path | None = None) -> list[dict[str, Any]]:
    registry = AdapterRegistry(project_path)
    graph = _semantic_graph(project_path, report, graph_path)
    resolved_id = str((report.get("resolved_entity") or {}).get("id") or "")
    result: list[dict[str, Any]] = []
    for adapter_id in ("openapi", "asyncapi"):
        status = registry.status(adapter_id)
        item: dict[str, Any] = {
            "adapter_id": adapter_id, "evidence_class": "CONTRACT_CONFIRMED",
            "status": status.get("status"), "enabled": bool(status.get("enabled")),
            "freshness": status.get("freshness", {"status": "unknown", "verified": False}),
            "nodes": [], "edges": [], "mapping_summary": {"confirmed": 0, "likely": 0, "unresolved": 0, "ambiguous": 0},
            "diagnostics": list(status.get("diagnostics") or [])[:8],
            "network_used": False, "privacy": {"mode": "local-only", "network_used": False},
        }
        overlay = registry.overlay(adapter_id)
        if overlay and graph:
            mapped = map_boundary_overlay(overlay, graph)
            selected = [node for node in mapped.get("nodes", []) if node.get("mapping", {}).get("canonical_node_id") == resolved_id]
            selected_ids = {node.get("id") for node in selected}
            selected_edges = [edge for edge in [*(mapped.get("edges", []) or []), *(mapped.get("canonical_links", []) or [])] if edge.get("from") in selected_ids or edge.get("to") in selected_ids or edge.get("canonical_from") == resolved_id or edge.get("canonical_to") == resolved_id]
            item.update({
                "spec_format": mapped.get("spec_format"), "spec_version": mapped.get("spec_version"),
                "nodes": selected[:40], "edges": selected_edges[:80],
                "mapping_summary": mapped.get("mapping_summary", item["mapping_summary"]),
                "canonical_links": mapped.get("canonical_links", [])[:80],
                "diagnostics": list(mapped.get("diagnostics") or [])[-8:],
                "source_spec": mapped.get("source_spec"),
            })
        result.append(item)
    return result


def _bounded_boundary_context(project_path: str, report: dict[str, Any], graph_path: str | Path | None = None, *, max_items: int = 40) -> list[dict[str, Any]]:
    result = _boundary_evidence(project_path, report, graph_path)
    for item in result:
        item["nodes"] = (item.get("nodes") or [])[:max_items]
        item["edges"] = (item.get("edges") or [])[:max_items]
        item["bounded"] = True
        item["max_items"] = max_items
    return result


def _render_graphify_native_html(project_path: str | Path) -> str:
    proj = Path(project_path).expanduser().resolve()
    # This endpoint must never render the CodeSlicer canonical graph as if it
    # were produced by Graphify.  The two graphs have different provenance and
    # serve different questions.  A missing Graphify artifact is an honest
    # empty state, not a reason to fall back to .impact_engine/graph.json.
    graph_file = find_graphify_graph(proj)
    if not graph_file.is_file():
        return "<!DOCTYPE html><html><body style='background:#0f0f1a;color:#e0e0e0;font-family:sans-serif;padding:40px;'><h2>Graphify Native Viewer</h2><p>Нативный граф Graphify для этого проекта ещё не построен.</p><p>Настройте executable Graphify и явно выполните <strong>«Построить architecture graph»</strong>. Канонический граф CodeSlicer здесь намеренно не показывается.</p></body></html>"

    runtime_status = ToolRuntime(proj).status("graphify")
    repo_path = runtime_status.get("repository", {}).get("path")
    repo = Path(str(repo_path or "")).expanduser()
    if not repo.is_dir():
        return "<!DOCTYPE html><html><body style='background:#0f0f1a;color:#e0e0e0;font-family:sans-serif;padding:40px;'><h2>Graphify Native Viewer</h2><p>Для оригинального renderer подключите локальный Graphify repository. CodeSlicer не импортирует upstream-код в процесс Local API.</p></body></html>"

    # Keep upstream imports out of the Local API process. A Graphify run may
    # live in another venv, so use the interpreter it recorded beside its
    # artifact instead of silently importing it with CodeSlicer's Python.
    interpreter_record = graph_file.parent / ".graphify_python"
    if not interpreter_record.is_file():
        return "<!DOCTYPE html><html><body style='background:#0f0f1a;color:#e0e0e0;font-family:sans-serif;padding:40px;'><h2>Graphify Native Viewer</h2><p>Не найден interpreter Graphify (<code>.graphify_python</code>) рядом с его graph. Перестройте Graphify graph его исходной командой или настройте его managed environment.</p></body></html>"
    try:
        interpreter = Path(interpreter_record.read_text(encoding="utf-8").strip()).expanduser().resolve()
    except OSError:
        interpreter = Path()
    if not interpreter.is_file():
        return "<!DOCTYPE html><html><body style='background:#0f0f1a;color:#e0e0e0;font-family:sans-serif;padding:40px;'><h2>Graphify Native Viewer</h2><p>Сохранённый interpreter Graphify больше недоступен. Перестройте его graph в актуальном Graphify environment.</p></body></html>"

    # The renderer receives only the already-created local graph and returns
    # bounded HTML over stdout.
    renderer = """
import json, sys, tempfile
from pathlib import Path
repo, graph_file = map(Path, sys.argv[1:3])
sys.path.insert(0, str(repo))
import networkx as nx
from graphify.exporters.html import to_html
data = json.loads(graph_file.read_text(encoding='utf-8'))
links = [{'source': e.get('from', e.get('source')), 'target': e.get('to', e.get('target')), 'kind': e.get('kind', 'CALLS'), 'confidence': e.get('confidence', 1.0)} for e in (data.get('edges') or data.get('links') or [])]
nodes = [{'id': str(n['id']), 'label': str(n.get('name', n['id'])), 'kind': str(n.get('kind', 'FUNCTION'))} for n in data.get('nodes', [])]
graph = nx.node_link_graph({'directed': True, 'nodes': nodes, 'links': links}, edges='links')
with tempfile.NamedTemporaryFile(suffix='.html', delete=False) as handle:
    output = Path(handle.name)
try:
    to_html(graph, {0: [node['id'] for node in nodes]}, output)
    sys.stdout.write(output.read_text(encoding='utf-8'))
finally:
    output.unlink(missing_ok=True)
"""
    safe_env = {"PATH": os.environ.get("PATH", ""), "PYTHONNOUSERSITE": "1"}
    if os.name == "nt":
        safe_env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", "")
    try:
        completed = subprocess.run(
            [str(interpreter), "-I", "-c", renderer, str(repo.resolve()), str(graph_file)],
            cwd=repo, env=safe_env, capture_output=True, text=True, timeout=30, check=False,
        )
        if completed.returncode == 0 and completed.stdout:
            return completed.stdout[:4 * 1024 * 1024]
        detail = (completed.stderr or completed.stdout or "Graphify renderer did not produce HTML").strip()[:1200]
        return f"<!DOCTYPE html><html><body style='background:#0f0f1a;color:#e0e0e0;font-family:sans-serif;padding:40px;'><h2>Graphify Native Viewer</h2><pre>Renderer failed in its isolated subprocess: {html.escape(detail)}</pre></body></html>"
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"<!DOCTYPE html><html><body style='background:#0f0f1a;color:#e0e0e0;font-family:sans-serif;padding:40px;'><h2>Graphify Native Viewer</h2><pre>Renderer unavailable: {html.escape(str(exc))}</pre></body></html>"


def _otel_evidence(project_path: str, report: dict[str, Any], graph_path: str | Path | None = None) -> dict[str, Any]:
    registry = AdapterRegistry(project_path)
    status = registry.status("otel")
    base = {
        "adapter_id": "otel", "evidence_class": "RUNTIME_OBSERVED", "status": status.get("status"),
        "enabled": bool(status.get("enabled")), "freshness": status.get("freshness", {"status": "unknown", "verified": False}),
        "format": status.get("artifact", {}).get("format"), "observed": False, "observation": "not observed",
        "nodes": [], "edges": [], "mapping_summary": {"confirmed": 0, "likely": 0, "unresolved": 0, "ambiguous": 0, "stale": 0},
        "diagnostics": list(status.get("diagnostics") or [])[:8], "network_used": False,
        "privacy": {"mode": "local-only", "network_used": False, "raw_attributes_stored": False, "redaction": "allowlist"},
    }
    overlay = registry.overlay("otel")
    graph = _semantic_graph(project_path, report, graph_path)
    if not overlay:
        return base
    if not graph:
        observed = bool(overlay.get("nodes"))
        return {**base, "observed": observed, "observation": "observed" if observed else "not observed", "nodes": (overlay.get("nodes") or [])[:40], "edges": (overlay.get("edges") or [])[:80], "diagnostics": list(overlay.get("diagnostics") or [])[-8:]}
    mapped = map_otel_overlay(overlay, graph)
    resolved_id = str((report.get("resolved_entity") or {}).get("id") or "")
    selected = [node for node in mapped.get("nodes", []) if node.get("mapping", {}).get("canonical_node_id") == resolved_id]
    selected_ids = {node.get("id") for node in selected}
    selected_edges = [edge for edge in mapped.get("edges", []) if edge.get("from") in selected_ids or edge.get("to") in selected_ids]
    observed = bool(selected or selected_edges)
    timestamps = [node.get("properties", {}).get("start_time_ns") for node in selected if node.get("properties", {}).get("start_time_ns") is not None]
    return {
        **base, "format": mapped.get("format"), "observed": observed,
        "observation": "observed" if observed else "not observed",
        "nodes": selected[:40], "edges": selected_edges[:80], "mapping_summary": mapped.get("mapping_summary", base["mapping_summary"]),
        "diagnostics": list(mapped.get("diagnostics") or [])[-8:], "timestamp": min(timestamps) if timestamps else None,
        "source_artifact_path": mapped.get("source_artifact_path"),
    }


def _bounded_otel_context(project_path: str, report: dict[str, Any], graph_path: str | Path | None = None, *, max_items: int = 40) -> dict[str, Any]:
    evidence = _otel_evidence(project_path, report, graph_path)
    return {
        **evidence, "nodes": (evidence.get("nodes") or [])[:max_items], "edges": (evidence.get("edges") or [])[:max_items],
        "bounded": True, "max_items": max_items,
    }


def _security_evidence(project_path: str, report: dict[str, Any], graph_path: str | Path | None = None) -> list[dict[str, Any]]:
    registry = AdapterRegistry(project_path)
    graph = _semantic_graph(project_path, report, graph_path)
    resolved_id = str((report.get("resolved_entity") or {}).get("id") or "")
    result: list[dict[str, Any]] = []
    for adapter_id in ("cyclonedx", "spdx", "sarif"):
        status = registry.status(adapter_id)
        summary = status.get("artifact", {}).get("summary") or {}
        item: dict[str, Any] = {
            "adapter_id": adapter_id, "evidence_class": "SECURITY_FINDING", "status": status.get("status"),
            "enabled": bool(status.get("enabled")), "freshness": status.get("freshness", {"status": "unknown", "verified": False}),
            "format": status.get("artifact", {}).get("format"), "source_report_path": status.get("artifact", {}).get("source_path"),
            "tool": status.get("artifact", {}).get("tool", {}), "components": summary.get("components", 0),
            "findings": summary.get("findings", 0), "licenses": summary.get("licenses", 0), "severity": summary.get("severity", {}),
            "nodes": [], "edges": [], "mapping_summary": {"confirmed": 0, "likely": 0, "unresolved": 0, "stale": 0},
            "diagnostics": list(status.get("diagnostics") or [])[:8], "network_used": False,
            "privacy": {"mode": "local-only", "network_used": False, "raw_messages_stored": False, "secrets_stored": False},
        }
        overlay = registry.overlay(adapter_id)
        if overlay and graph:
            mapped = map_security_overlay(overlay, graph)
            selected = [node for node in mapped.get("nodes", []) if node.get("mapping", {}).get("canonical_node_id") == resolved_id]
            selected_ids = {node.get("id") for node in selected}
            selected_edges = [edge for edge in mapped.get("edges", []) if edge.get("from") in selected_ids or edge.get("to") in selected_ids]
            item.update({"nodes": selected[:40], "edges": selected_edges[:80], "mapping_summary": mapped.get("mapping_summary", item["mapping_summary"]), "diagnostics": list(mapped.get("diagnostics") or [])[-8:], "source_report_path": mapped.get("source_report_path") or item["source_report_path"], "tool": mapped.get("tool") or item["tool"]})
        elif overlay:
            item.update({"nodes": (overlay.get("nodes") or [])[:40], "edges": (overlay.get("edges") or [])[:80], "diagnostics": list(overlay.get("diagnostics") or [])[-8:]})
        result.append(item)
    return result


def _bounded_security_context(project_path: str, report: dict[str, Any], graph_path: str | Path | None = None, *, max_items: int = 40) -> list[dict[str, Any]]:
    result = _security_evidence(project_path, report, graph_path)
    for item in result:
        item["nodes"] = (item.get("nodes") or [])[:max_items]
        item["edges"] = (item.get("edges") or [])[:max_items]
        item["bounded"] = True
        item["max_items"] = max_items
    return result


def _bounded_joern_context(project_path: str, report: dict[str, Any], *, max_nodes: int = 80, max_edges: int = 160, max_paths: int = 40) -> dict[str, Any]:
    entity_id = str((report.get("resolved_entity") or {}).get("id") or "")
    overlay = AdapterRegistry(project_path).overlay("joern")
    return bounded_joern_context(overlay, entity=entity_id or None, max_nodes=max_nodes, max_edges=max_edges, max_paths=max_paths)


def _external_graph_evidence(project_path: str, report: dict[str, Any], *, max_items: int = 40) -> list[dict[str, Any]]:
    """Return bounded, explicitly labelled external graph context only."""
    registry = AdapterRegistry(project_path)
    entity_id = str((report.get("resolved_entity") or {}).get("id") or "")
    result: list[dict[str, Any]] = []
    for adapter_id in ("graphify", "codegraph"):
        status = registry.status(adapter_id)
        item: dict[str, Any] = {
            "adapter_id": adapter_id, "source": adapter_id, "evidence_class": "DOC_INFERRED",
            "status": status.get("status"), "enabled": bool(status.get("enabled")),
            "freshness": status.get("freshness", {"status": "unknown", "verified": False}),
            "network_used": False, "privacy": {"mode": "local-only", "network_used": False},
            "nodes": [], "edges": [], "diagnostics": list(status.get("diagnostics") or [])[:8],
            "why": "External graph is supplemental overlay evidence; it never changes canonical graph or Review ranking.",
        }
        overlay = registry.overlay(adapter_id)
        if overlay:
            nodes = list(overlay.get("nodes") or [])
            edges = list(overlay.get("edges") or [])
            if entity_id:
                selected_nodes = [node for node in nodes if str(node.get("id")) == entity_id or str(node.get("name")) == entity_id]
                selected_ids = {str(node.get("id")) for node in selected_nodes}
                selected_edges = [edge for edge in edges if str(edge.get("from")) in selected_ids or str(edge.get("to")) in selected_ids]
                nodes, edges = selected_nodes, selected_edges
            item.update({
                "nodes": nodes[:max_items], "edges": edges[:max_items],
                "total_nodes": len(overlay.get("nodes") or []), "total_edges": len(overlay.get("edges") or []),
                "diagnostics": list(overlay.get("diagnostics") or [])[-8:],
            })
        result.append(item)
    return result


def _test_command_for_file(project: Path, file_name: str) -> list[str] | None:
    """Return a conservative, shell-free command for one explicit test action."""
    suffix = Path(file_name).suffix.lower()
    if suffix == ".py":
        return [sys.executable, "-m", "pytest", file_name, "-q"]
    if suffix in {".js", ".jsx", ".ts", ".tsx"} and (project / "package.json").is_file():
        if (project / "pnpm-lock.yaml").is_file():
            return ["pnpm", "test", "--", file_name]
        if (project / "yarn.lock").is_file():
            return ["yarn", "test", file_name]
        return ["npm", "test", "--", file_name]
    if suffix == ".go" and (project / "go.mod").is_file():
        return ["go", "test", "./..."]
    if suffix == ".cs" and any(project.glob("*.sln")):
        return ["dotnet", "test"]
    if suffix == ".java":
        if (project / "pom.xml").is_file():
            return ["mvn", "test"]
        if (project / "gradlew").is_file():
            return ["gradlew", "test"]
        if (project / "gradlew.bat").is_file():
            return ["gradlew.bat", "test"]
    return None


class LocalApiState:
    def __init__(self, default_project: str | None, support_pack_root: str) -> None:
        self.default_project = default_project
        self.support_pack_root = support_pack_root
        self.project_path: str | None = default_project
        self.analysis: dict[str, Any] | None = None
        self.last_error: str | None = None
        self.analyzed_at: float | None = None
        self.progress: dict[str, Any] = {"status": "idle"}
        self.lock = threading.RLock()
        self.cancellation: CancellationToken | None = None
        self.analysis_running = False
        if default_project:
            try:
                ensure_project_storage(default_project)
            except (FileNotFoundError, OSError):
                pass
        self._load_existing_graph()

    def _load_existing_graph(self, graph_path: str | None = None) -> bool:
        """Hydrate API state from a graph produced by the CLI.

        CLI and the local UI are separate processes.  Without this handoff a
        successful CLI analysis leaves the UI in the misleading ``idle`` state
        until the analysis is run a second time through the browser.
        """
        if not self.project_path:
            return False
        project = Path(self.project_path).expanduser().resolve()
        candidates = [Path(graph_path).expanduser().resolve()] if graph_path else [
            project / ".impact_engine" / "graph.json",
            project / "graph.json",
        ]
        for candidate in candidates:
            if not candidate.is_file():
                continue
            try:
                graph = GraphDocument.from_json(candidate.read_text(encoding="utf-8"))
                metadata = graph.metadata or {}
                recorded_project = metadata.get("project_path")
                if recorded_project and Path(str(recorded_project)).expanduser().resolve() != project:
                    continue
                inventory = asdict(scan_project_inventory(str(project)))
                progress = metadata.get("analysis_progress") or {
                    "status": "loaded",
                    "current": {"stage": "loaded", "message": "Граф загружен из cache"},
                }
                self.analysis = {
                    "status": "ok",
                    "path": str(project),
                    "project_path": str(project),
                    "graph_path": str(candidate),
                    "inventory": inventory,
                    "languages": inventory.get("languages", []),
                    "extractors_used": metadata.get("extractors", []),
                    "diagnostics": metadata.get("diagnostics", {}),
                    "nodes": len(graph.nodes),
                    "edges": len(graph.edges),
                    "graph": graph.to_dict(),
                    "progress": progress,
                    "loaded_from_existing_graph": True,
                }
                self.project_path = str(project)
                self.analyzed_at = candidate.stat().st_mtime
                self.progress = progress
                self.last_error = None
                return True
            except (OSError, ValueError, TypeError):
                continue
        return False

    def snapshot(self, include_graph: bool = True) -> dict[str, Any]:
        with self.lock:
            analysis = self.analysis or {}
            project_exists = False
            if self.project_path:
                try:
                    project_exists = Path(self.project_path).expanduser().is_dir()
                except OSError:
                    project_exists = False
            result = {
                "status": "error" if self.last_error else ("ready" if self.analysis else "idle"),
                "has_analysis": bool(self.analysis),
                "project_path": self.project_path,
                "project_exists": project_exists,
                "analyzed_at": self.analyzed_at,
                "error": self.last_error,
                "progress": self.progress,
                "analysis": {key: value for key, value in analysis.items() if key != "graph"},
            }
            if include_graph:
                result["graph"] = analysis.get("graph")
            return result

    def analyze(self, project_path: str) -> dict[str, Any]:
        path = Path(project_path).expanduser().resolve()
        if not path.exists() or not path.is_dir():
            raise FileNotFoundError(f"Project directory does not exist: {project_path}")
        out_path = path / ".impact_engine" / "graph.json"
        with self.lock:
            if self.analysis_running:
                raise RuntimeError("analysis already running")
            token = CancellationToken()
            self.cancellation = token
            self.analysis_running = True
            self.last_error = None
            self.progress = {
                "status": "running",
                "current": {
                    "stage": "starting", "message": "Подготовка локального анализа",
                    "processed": 0, "total": 0, "overall_percent": 0.0,
                    "elapsed_seconds": 0.0, "eta_seconds": None, "cancellable": True,
                },
            }
        def report_progress(event: dict[str, Any]) -> None:
            with self.lock:
                self.progress = {"status": "running", "current": event}
        try:
            result = analyze_project_core(
                str(path),
                out_path=str(out_path),
                support_pack_root=self.support_pack_root,
                enable_remote_registry=False,
                create_research_requests=True,
                progress_callback=report_progress,
                cancellation=token,
            )
        except AnalysisCancelled:
            with self.lock:
                current = dict((self.progress or {}).get("current") or {})
                current.update({"cancellable": False, "eta_seconds": None})
                self.progress = {"status": "cancelled", "current": current}
            raise
        except Exception as exc:
            with self.lock:
                self.last_error = str(exc)
                self.progress = {"status": "failed", "error": str(exc), "current": self.progress.get("current", {})}
            raise
        finally:
            with self.lock:
                self.analysis_running = False
                self.cancellation = None
        with self.lock:
            self.project_path = str(path)
            self.analysis = result
            self.last_error = None
            self.analyzed_at = time.time()
            self.progress = result.get("progress", {"status": "completed"})
        return self.snapshot()

    def cancel_analysis(self) -> dict[str, Any]:
        with self.lock:
            if not self.analysis_running or self.cancellation is None:
                return {"status": "idle", "message": "No analysis is running", "progress": self.progress}
            self.cancellation.cancel()
            return {"status": "cancelling", "message": "Cancellation requested", "progress": self.progress}


class LocalApiHandler(SimpleHTTPRequestHandler):
    server_version = "ImpactEngineLocalAPI/0.5"

    @property
    def state(self) -> LocalApiState:
        return self.server.impact_state  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:
        # Keep stdout clean for callers that launch the server from a terminal.
        return

    def _send_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 2_000_000:
            raise ValueError("Request body exceeds 2 MB")
        value = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(value, dict):
            raise ValueError("Request body must be a JSON object")
        return value

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send_json(204, {})

    def do_GET(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/api/health":
                return self._send_json(200, {
                    "status": "ok",
                    "service": "impact-engine-local-api",
                    "api_contract_version": LOCAL_API_CONTRACT_VERSION,
                    "capabilities": {
                        "managed_tools": True,
                        "tools_endpoint": "/api/tools",
                    },
                })
            if parsed.path == "/api/state":
                return self._send_json(200, self.state.snapshot(include_graph=False))
            if parsed.path == "/api/progress":
                return self._send_json(200, {"status": "ok", "progress": self.state.progress})
            if parsed.path == "/api/overview":
                project_path = self.state.project_path or self.state.default_project
                if not project_path:
                    return self._send_json(200, {"status": "incomplete", "project": None, "freshness": {"status": "missing", "verified": False}, "coverage": {"status": "unknown", "languages": []}, "evidence_sources": [], "privacy": {"mode": "local-only", "network_used": False}})
                project = Path(str(project_path)).expanduser().resolve()
                if not project.is_dir():
                    return self._send_json(404, {
                        "status": "error", "error": "project_not_found",
                        "message": f"Project directory does not exist: {project}",
                        "project_path": str(project),
                    })
                return self._send_json(200, _project_overview(str(project_path), self.state))
            if parsed.path == "/api/graph":
                snapshot = self.state.snapshot()
                if not snapshot.get("graph"):
                    return self._send_json(404, {"error": "no_analysis", "message": "Analyze a project first"})
                return self._send_json(200, {"status": "ok", "project_path": snapshot["project_path"], "graph": snapshot["graph"]})
            if parsed.path == "/api/libraries":
                return self._send_json(200, {"status": "ok", "items": self._libraries()})
            if parsed.path == "/api/inventory":
                analysis = self.state.snapshot(include_graph=False).get("analysis") or {}
                return self._send_json(200, {"status": "ok", "inventory": analysis.get("inventory", {})})
            if parsed.path == "/api/adapters":
                project_path = self.state.project_path or self.state.default_project
                if not project_path:
                    return self._send_json(200, {"status": "ok", "project_path": None, "adapters": []})
                return self._send_json(200, {"status": "ok", "project_path": str(Path(project_path).resolve()), "adapters": AdapterRegistry(project_path).list(), "privacy": {"mode": "local-only", "network_used": False}})
            if parsed.path == "/api/tools":
                project_path = self.state.project_path or self.state.default_project
                if not project_path:
                    return self._send_json(200, {"status": "ok", "api_contract_version": LOCAL_API_CONTRACT_VERSION, "project_path": None, "tools": []})
                return self._send_json(200, {"status": "ok", "api_contract_version": LOCAL_API_CONTRACT_VERSION, "project_path": str(Path(project_path).resolve()), "tools": ToolRuntime(project_path).catalog(), "privacy": {"mode": "local-only", "network_used": False}})
            if parsed.path == "/api/adapters/graphify/viewer/status":
                project_path = self.state.project_path or self.state.default_project
                graph_file = find_graphify_graph(project_path) if project_path else None
                available = bool(graph_file and graph_file.is_file())
                return self._send_json(200, {
                    "status": "ready" if available else "missing",
                    "available": available,
                    "artifact": str(graph_file) if graph_file else None,
                    "artifact_bytes": graph_file.stat().st_size if available else 0,
                    "renderer": "graphify-upstream-html",
                    "privacy": {"mode": "local-only", "network_used": False},
                })
            if parsed.path == "/api/adapters/graphify/viewer":
                project_path = self.state.project_path or self.state.default_project
                if not project_path:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"No active project")
                    return
                html = _render_graphify_native_html(project_path)
                encoded = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
                return
            if parsed.path == "/api/adapters/lsp/status":
                project_path = self.state.project_path or self.state.default_project
                if not project_path:
                    return self._send_json(200, {"status": "disabled", "adapter_id": "lsp", "network_used": False, "privacy": lsp_privacy()})
                return self._send_json(200, {"status": "ok", "adapter": AdapterRegistry(project_path).status("lsp"), "privacy": lsp_privacy()})
            return super().do_GET()
        except Exception as exc:
            self._send_json(500, {"status": "error", "error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            body = self._read_json()
            # A deliberately narrow live OpenTelemetry receiver. It accepts
            # OTLP/HTTP *JSON* only, on a loopback-bound local API, and only
            # after the project owner opted in via /api/adapters/otel/live.
            # The raw request is never persisted; AdapterRegistry writes the
            # sanitized evidence overlay instead.
            if parsed.path == "/v1/traces":
                if self.client_address[0] not in {"127.0.0.1", "::1"}:
                    return self._send_json(403, {"status": "error", "error": "OTLP receiver accepts loopback clients only"})
                project_path = str(self.state.project_path or self.state.default_project or "").strip()
                if not project_path:
                    return self._send_json(409, {"status": "error", "error": "Select and analyze a local project before enabling OTLP capture"})
                registry = AdapterRegistry(project_path)
                receiver = registry.otel_live_receiver()
                if not receiver.get("enabled"):
                    return self._send_json(403, {"status": "disabled", "error": "OTLP live receiver is disabled; enable it explicitly in Sources"})
                endpoint = str(receiver.get("endpoint") or "otlp-http-json-loopback")
                imported = registry.import_otel_document(body, source_label=endpoint)
                summary = (imported.get("overlay") or {}).get("summary") or {}
                return self._send_json(200, {"status": "accepted", "spans": summary.get("spans", 0), "traces": summary.get("traces", 0), "raw_payload_stored": False, "adapter": imported.get("adapter")})
            if parsed.path == "/api/analyze":
                project_path = str(body.get("project_path") or self.state.default_project or "").strip()
                if not project_path:
                    return self._send_json(400, {"status": "error", "error": "project_path is required"})
                try:
                    return self._send_json(200, self.state.analyze(project_path))
                except AnalysisCancelled:
                    return self._send_json(409, {"status": "cancelled", "progress": self.state.progress})
                except Exception as exc:
                    with self.state.lock:
                        self.state.last_error = str(exc)
                    return self._send_json(422, {"status": "error", "error": str(exc)})
            if parsed.path == "/api/analyze/cancel":
                return self._send_json(200, self.state.cancel_analysis())
            if parsed.path == "/api/graph/projection":
                project_path = str(body.get("project_path") or self.state.project_path or self.state.default_project or "").strip()
                if not project_path:
                    return self._send_json(400, {"status": "error", "error": "project_path is required"})
                try:
                    return self._send_json(200, _graph_projection(project_path, body))
                except (ValueError, OSError, TypeError) as exc:
                    return self._send_json(422, {"status": "error", "error": str(exc)})
            if parsed.path == "/api/graph-workspace":
                project_path = str(body.get("project_path") or self.state.project_path or self.state.default_project or "").strip()
                if not project_path:
                    return self._send_json(400, {"status": "error", "error": "project_path is required"})
                try:
                    return self._send_json(200, _graph_workspace(project_path, body))
                except (ValueError, OSError, TypeError) as exc:
                    return self._send_json(422, {"status": "error", "error": str(exc)})
            tool_parts = parsed.path.strip("/").split("/")
            if len(tool_parts) >= 2 and tool_parts[:2] == ["api", "tools"]:
                project_path = str(body.get("project_path") or self.state.project_path or self.state.default_project or "").strip()
                if not project_path:
                    return self._send_json(400, {"status": "error", "error": "project_path is required"})
                runtime = ToolRuntime(project_path)
                if len(tool_parts) == 2:
                    return self._send_json(200, {"status": "ok", "tools": runtime.catalog(), "privacy": {"mode": "local-only", "network_used": False}})
                if len(tool_parts) != 4:
                    return self._send_json(404, {"status": "error", "error": "unknown tool runtime endpoint"})
                tool_id, action = tool_parts[2], tool_parts[3]
                try:
                    if action == "connect":
                        tool = runtime.connect(tool_id, confirmed=bool(body.get("confirmed", False)), ref=body.get("ref"))
                        return self._send_json(200, {"status": "ok", "tool": tool, "privacy": {"mode": "local-only", "network_used": True, "network_action": "explicit-git-clone"}})
                    if action == "executable":
                        tool = runtime.configure_executable(tool_id, body.get("executable") or "")
                        return self._send_json(200, {"status": "ok", "tool": tool, "privacy": {"mode": "local-only", "network_used": False}})
                    if action == "docs":
                        return self._send_json(200, {"status": "ok", **runtime.docs(tool_id, query=str(body.get("query") or ""), limit=int(body.get("limit", 40)))})
                    if action == "document":
                        return self._send_json(200, {"status": "ok", **runtime.read_document(
                            tool_id,
                            str(body.get("path") or ""),
                            offset=int(body.get("offset") or 0),
                            limit_bytes=int(body.get("limit_bytes") or 128 * 1024),
                        )})
                    if action == "help":
                        return self._send_json(200, {"status": "ok", **runtime.help(tool_id)})
                    if action == "run":
                        return self._send_json(200, runtime.run(tool_id, argv=body.get("argv") or [], confirmed=bool(body.get("confirmed", False)), workspace=str(body.get("workspace") or "project"), timeout_seconds=int(body.get("timeout_seconds", 60))))
                    return self._send_json(404, {"status": "error", "error": "unknown tool runtime action"})
                except (FileNotFoundError, ValueError, OSError, RuntimeError) as exc:
                    return self._send_json(422, {"status": "error", "error": str(exc)})
            adapter_parts = parsed.path.strip("/").split("/")
            if len(adapter_parts) == 4 and adapter_parts[:3] == ["api", "adapters", "otel"] and adapter_parts[3] in {"live-enable", "live-disable", "live-status"}:
                project_path = str(body.get("project_path") or self.state.project_path or self.state.default_project or "").strip()
                if not project_path:
                    return self._send_json(400, {"status": "error", "error": "project_path is required"})
                registry = AdapterRegistry(project_path)
                endpoint = f"http://127.0.0.1:{self.server.server_address[1]}/v1/traces"
                action = adapter_parts[3]
                if action == "live-enable":
                    adapter = registry.set_otel_live_receiver(True, endpoint=endpoint)
                    return self._send_json(200, {"status": "ok", "adapter": adapter, "receiver": registry.otel_live_receiver(), "privacy": {"mode": "loopback-otlp-json", "network_used": False, "raw_payload_stored": False}})
                if action == "live-disable":
                    adapter = registry.set_otel_live_receiver(False, endpoint=endpoint)
                    return self._send_json(200, {"status": "ok", "adapter": adapter, "receiver": registry.otel_live_receiver(), "privacy": {"mode": "loopback-otlp-json", "network_used": False, "raw_payload_stored": False}})
                return self._send_json(200, {"status": "ok", "adapter": registry.status("otel"), "receiver": registry.otel_live_receiver(), "privacy": {"mode": "loopback-otlp-json", "network_used": False, "raw_payload_stored": False}})
            if len(adapter_parts) == 4 and adapter_parts[:2] == ["api", "adapters"] and adapter_parts[3] in {"native-profile", "native-run", "native-config"}:
                adapter_id = adapter_parts[2]
                project_path = str(body.get("project_path") or self.state.project_path or self.state.default_project or "").strip()
                if not project_path:
                    return self._send_json(400, {"status": "error", "error": "project_path is required"})
                try:
                    registry = AdapterRegistry(project_path)
                    if adapter_parts[3] == "native-profile":
                        return self._send_json(200, {"status": "ok", "adapter_id": adapter_id, "native": registry.status(adapter_id).get("native", native_profile(adapter_id)), "privacy": {"mode": "local-only", "network_used": False}})
                    if adapter_parts[3] == "native-config":
                        adapter = registry.configure_native_executable(adapter_id, body.get("executable"))
                        return self._send_json(200, {"status": "ok", "adapter": adapter, "privacy": {"mode": "local-only", "network_used": False}})
                    result = run_native_operation(
                        project_path, adapter_id, str(body.get("operation") or ""),
                        confirmed=bool(body.get("confirmed", False)), query=str(body.get("query") or ""),
                        configured_executable=registry._state(adapter_id).get("native_executable"),
                        timeout_seconds=int(body.get("timeout_seconds", 60)),
                    )
                    generated = result.get("generated_artifact")
                    if result.get("status") == "completed" and generated and adapter_id in {"openapi", "scip", "cyclonedx", "spdx", "sarif"}:
                        try:
                            # A native generator is an explicit user action;
                            # importing its local output is safe and leaves it
                            # disabled until the user chooses to enable it.
                            result["imported_artifact"] = registry.import_artifact(adapter_id, generated)
                        except (ValueError, OSError) as exc:
                            result["import_error"] = str(exc)
                    return self._send_json(200, result)
                except (FileNotFoundError, ValueError, OSError) as exc:
                    return self._send_json(422, {"status": "error", "error": str(exc)})
            adapter_action = None
            adapter_id = None
            if len(adapter_parts) == 4 and adapter_parts[:3] == ["api", "adapters", "lsp"] and adapter_parts[3] in {"configure", "probe", "disable", "query"}:
                project_path = str(body.get("project_path") or self.state.project_path or self.state.default_project or "").strip()
                if not project_path:
                    return self._send_json(400, {"status": "error", "error": "project_path is required"})
                try:
                    action = adapter_parts[3]
                    if action == "configure":
                        adapter = configure_lsp(project_path, body.get("executable") or "", body.get("workspace_roots") or [], arguments=body.get("arguments") or [], timeout_ms=int(body.get("timeout_ms", 5000)))
                        return self._send_json(200, {"status": "ok", "adapter": adapter, "privacy": lsp_privacy()})
                    if action == "probe":
                        return self._send_json(200, {"status": "ok", "adapter": probe_lsp(project_path), "privacy": lsp_privacy()})
                    if action == "disable":
                        return self._send_json(200, {"status": "ok", "adapter": disable_lsp(project_path), "privacy": lsp_privacy()})
                    result = query_lsp(project_path, method=str(body.get("method") or ""), file=body.get("file"), line=int(body.get("line", 0)), character=int(body.get("character", 0)), query=str(body.get("query") or ""), entity_id=body.get("entity_id"), timeout_ms=body.get("timeout_ms"))
                    graph = _semantic_graph(project_path, {}, body.get("graph_path"))
                    if result.get("nodes") and graph:
                        result = {**result, "mapped_overlay": map_lsp_overlay(result, graph)}
                    return self._send_json(200, {"status": result.get("status", "ok"), "result": result, "privacy": lsp_privacy()})
                except (FileNotFoundError, ValueError, OSError) as exc:
                    return self._send_json(422, {"status": "error", "error": str(exc)})
            if len(adapter_parts) == 4 and adapter_parts[:2] == ["api", "adapters"] and adapter_parts[3] in {"enable", "disable"}:
                adapter_id, adapter_action = adapter_parts[2], adapter_parts[3]
            if adapter_action:
                project_path = str(body.get("project_path") or self.state.project_path or self.state.default_project or "").strip()
                if not project_path:
                    return self._send_json(400, {"status": "error", "error": "project_path is required"})
                try:
                    enabled = adapter_action == "enable"
                    adapter = AdapterRegistry(project_path).set_enabled(adapter_id, enabled)
                    return self._send_json(200, {"status": "ok", "adapter": adapter, "privacy": {"mode": "local-only", "network_used": False}})
                except (FileNotFoundError, ValueError, OSError) as exc:
                    return self._send_json(422, {"status": "error", "error": str(exc)})
            if len(adapter_parts) == 4 and adapter_parts[:2] == ["api", "adapters"] and adapter_parts[3] == "import":
                adapter_id = adapter_parts[2]
                project_path = str(body.get("project_path") or self.state.project_path or self.state.default_project or "").strip()
                artifact_path = str(body.get("artifact_path") or body.get("path") or "").strip()
                if not project_path or not artifact_path:
                    return self._send_json(400, {"status": "error", "error": "project_path and artifact_path are required"})
                try:
                    result = AdapterRegistry(project_path).import_artifact(adapter_id, artifact_path)
                    return self._send_json(200, {"status": "ok", "import_status": result.get("status"), **{key: value for key, value in result.items() if key != "status"}, "privacy": {"mode": "local-only", "network_used": False}})
                except (FileNotFoundError, ValueError, OSError) as exc:
                    return self._send_json(422, {"status": "error", "error": str(exc)})
            if parsed.path == "/api/architecture":
                project_path = str(body.get("project_path") or self.state.project_path or self.state.default_project or "").strip()
                if not project_path:
                    return self._send_json(400, {"status": "error", "error": "project_path is required"})
                overlay_mode = str(body.get("overlay") or "codeslicer").lower()
                if overlay_mode not in {"codeslicer", "graphify", "combined"}:
                    return self._send_json(400, {"status": "error", "error": "overlay must be codeslicer, graphify, or combined"})
                registry = AdapterRegistry(project_path)
                overlay = _bounded_overlay(registry.overlay("graphify")) if overlay_mode in {"graphify", "combined"} else None
                status = registry.status("graphify")
                scip_status = registry.status("scip")
                openapi_status = registry.status("openapi")
                asyncapi_status = registry.status("asyncapi")
                otel_status = registry.status("otel")
                joern_status = registry.status("joern")
                security_statuses = {adapter_id: registry.status(adapter_id) for adapter_id in ("cyclonedx", "spdx", "sarif")}
                external_graph_statuses = {adapter_id: registry.status(adapter_id) for adapter_id in ("graphify", "codegraph")}
                overview = _project_overview(project_path, self.state)
                result = {
                    "mode": "architecture", "overlay_mode": overlay_mode,
                    "status": "ok", "code_slicer": {"enabled": True},
                    "health_status": overview.get("status", "unknown"),
                    "freshness": overview.get("freshness", {"status": "unknown", "verified": False}),
                    "coverage": overview.get("coverage", {"status": "unknown"}),
                    "diagnostics": overview.get("diagnostics", []),
                    "evidence_sources": _adapter_evidence_sources(project_path),
                    "graphify": overlay or {"status": status["status"], "message": "Import and enable a local Graphify graph.json to inspect the architecture overlay."},
                    "external_graphs": {
                        adapter_id: {
                            "status": external_status.get("status"), "enabled": external_status.get("enabled", False),
                            "freshness": external_status.get("freshness"), "entities": external_status.get("artifact", {}).get("nodes", 0),
                            "relationships": external_status.get("artifact", {}).get("edges", 0),
                            "diagnostics": external_status.get("diagnostics", [])[:8], "network_used": False,
                            "instruction": "Import an existing local external graph. CodeSlicer never downloads, runs, or uploads graph tools.",
                        } for adapter_id, external_status in external_graph_statuses.items()
                    },
                    "scip": {
                        "status": scip_status.get("status"), "enabled": scip_status.get("enabled", False),
                        "freshness": scip_status.get("freshness"), "network_used": False,
                        "symbols": scip_status.get("artifact", {}).get("nodes", 0),
                        "references_and_implementations": scip_status.get("artifact", {}).get("edges", 0),
                        "instruction": "Import an existing local .scip index. CodeSlicer does not generate or upload it automatically.",
                    },
                    "lsp": {
                        "status": registry.status("lsp").get("status"), "enabled": registry.status("lsp").get("enabled", False),
                        "freshness": registry.status("lsp").get("freshness"), "network_used": False, "privacy": lsp_privacy(),
                        "capabilities": registry.status("lsp").get("capabilities", {}),
                        "instruction": "Configure an existing local LSP executable and probe it explicitly. CodeSlicer never installs or starts one automatically.",
                    },
                    "openapi": {
                        "status": openapi_status.get("status"), "enabled": openapi_status.get("enabled", False),
                        "freshness": openapi_status.get("freshness"), "network_used": False,
                        "boundaries": openapi_status.get("artifact", {}).get("nodes", 0),
                        "diagnostics": openapi_status.get("diagnostics", [])[:8],
                        "instruction": "Import an existing local OpenAPI/Swagger document. CodeSlicer never downloads or generates one.",
                    },
                    "asyncapi": {
                        "status": asyncapi_status.get("status"), "enabled": asyncapi_status.get("enabled", False),
                        "freshness": asyncapi_status.get("freshness"), "network_used": False,
                        "boundaries": asyncapi_status.get("artifact", {}).get("nodes", 0),
                        "diagnostics": asyncapi_status.get("diagnostics", [])[:8],
                        "instruction": "Import an existing local AsyncAPI document. Broker URLs are metadata only; CodeSlicer never connects.",
                    },
                    "otel": {
                        "status": otel_status.get("status"), "enabled": otel_status.get("enabled", False),
                        "freshness": otel_status.get("freshness"), "network_used": False,
                        "privacy": {"mode": "local-only", "network_used": False, "raw_attributes_stored": False, "redaction": "allowlist"},
                        "format": otel_status.get("artifact", {}).get("format"),
                        "traces": otel_status.get("artifact", {}).get("traces", 0),
                        "spans": otel_status.get("artifact", {}).get("spans", 0),
                        "services": otel_status.get("artifact", {}).get("services", 0),
                        "diagnostics": otel_status.get("diagnostics", [])[:8],
                        "instruction": "Import an existing local OTLP JSON or Jaeger JSON trace. CodeSlicer never connects to a collector or endpoint.",
                    },
                    "joern": {
                        "status": joern_status.get("status"), "enabled": joern_status.get("enabled", False),
                        "freshness": joern_status.get("freshness"), "network_used": False, "overlay_only": True,
                        "participates_in_ranking": False, "nodes": joern_status.get("artifact", {}).get("nodes", 0),
                        "edges": joern_status.get("artifact", {}).get("edges", 0), "paths": joern_status.get("paths", 0),
                        "findings": joern_status.get("findings", 0), "diagnostics": joern_status.get("diagnostics", [])[:8],
                        "instruction": "Import an existing local Joern JSON interchange artifact. CodeSlicer never installs or starts Joern automatically.",
                    },
                    "security": {
                        adapter_id: {
                            "status": status.get("status"), "enabled": status.get("enabled", False),
                            "freshness": status.get("freshness"), "network_used": False,
                            "components": status.get("components", 0), "findings": status.get("findings", 0),
                            "licenses": status.get("licenses", 0), "severity": status.get("severity", {}),
                            "tool": status.get("artifact", {}).get("tool", {}),
                            "diagnostics": status.get("diagnostics", [])[:8],
                            "instruction": "Import an existing local security report. CodeSlicer does not scan, resolve advisories, or upload it.",
                        } for adapter_id, status in security_statuses.items()
                    },
                    "adapters": registry.list(), "privacy": {"mode": "local-only", "network_used": False},
                    "visualize_compare": {
                        "available": bool((Path(project_path).resolve() / ".impact_engine" / "graph.json").is_file() and status.get("artifact", {}).get("artifact_path")),
                        "command": f"impact-engine visualize-compare {Path(project_path).resolve() / '.impact_engine' / 'graph.json'} {status.get('artifact', {}).get('artifact_path') or '<local-graphify.json>'}",
                    },
                }
                mapping_summaries = {item.get("id"): _adapter_mapping_summary(project_path, str(item.get("id"))) for item in result.get("adapters", []) if item.get("id")}
                for adapter_id, summary in mapping_summaries.items():
                    if adapter_id in result and isinstance(result[adapter_id], dict):
                        result[adapter_id]["mapping_summary"] = summary
                    if adapter_id in result.get("security", {}) and isinstance(result["security"].get(adapter_id), dict):
                        result["security"][adapter_id]["mapping_summary"] = summary
                result["adapters"] = [{**item, "mapping_summary": mapping_summaries.get(item.get("id"), item.get("mapping_summary"))} for item in result.get("adapters", [])]
                return self._send_json(200, result)
            if parsed.path == "/api/load-graph":
                project_path = str(body.get("project_path") or self.state.default_project or "").strip()
                graph_path = str(body.get("graph_path") or "").strip()
                if not project_path or not graph_path:
                    return self._send_json(400, {"status": "error", "error": "project_path and graph_path are required"})
                project = Path(project_path).expanduser().resolve()
                candidate = Path(graph_path).expanduser().resolve()
                if not project.is_dir() or not candidate.is_file():
                    return self._send_json(422, {"status": "error", "error": "project_path or graph_path does not exist"})
                with self.state.lock:
                    self.state.project_path = str(project)
                    self.state.analysis = None
                if not self.state._load_existing_graph(str(candidate)):
                    return self._send_json(422, {"status": "error", "error": "graph does not belong to project or is invalid"})
                return self._send_json(200, self.state.snapshot())
            if parsed.path == "/api/impact":
                graph = self._graph_document()
                result = impact_query(
                    graph,
                    target=str(body.get("target") or ""),
                    symbol=body.get("symbol"),
                    direction=str(body.get("direction") or "both"),
                    max_depth=int(body.get("max_depth", 20)),
                    min_confidence=float(body.get("min_confidence", 0.0)),
                )
                return self._send_json(200, {"status": "ok", "result": result})
            if parsed.path == "/api/review":
                project_path = str(body.get("project_path") or self.state.project_path or self.state.default_project or "").strip()
                if not project_path:
                    return self._send_json(400, {"status": "error", "error": "project_path is required"})
                project = Path(project_path).expanduser().resolve()
                if not project.is_dir():
                    return self._send_json(422, {"status": "error", "error": "project_path must be an existing directory"})
                ensure_project_storage(project)
                analysis = self.state.snapshot(include_graph=False).get("analysis") or {}
                requested_graph_path = str(body.get("graph_path") or analysis.get("graph_path") or "").strip()
                graph = None
                current = self.state.snapshot().get("graph")
                loaded_graph_path = str(analysis.get("graph_path") or "").strip()
                if current and Path(str(self.state.project_path)).resolve() == project and (
                    not requested_graph_path or Path(loaded_graph_path).expanduser().resolve() == Path(requested_graph_path).expanduser().resolve()
                ):
                    graph = GraphDocument.from_dict(current)
                local_graph_paths = {(project / ".impact_engine" / "graph.json").resolve(), (project / "graph.json").resolve()}
                review_graph_path = None if requested_graph_path and Path(requested_graph_path).expanduser().resolve() in local_graph_paths and graph is not None else (requested_graph_path or None)
                report = build_review_report(
                    str(project), graph=graph, diff_text=body.get("diff_text"),
                    graph_path=review_graph_path,
                    base=body.get("base"), refresh=str(body.get("refresh") or "auto"),
                    max_results=int(body.get("max_results", 10)),
                    run_tests=str(body.get("run_tests") or "suggested"),
                    deep=bool(body.get("deep", False)),
                    entity=str(body.get("entity")) if body.get("entity") else None,
                )
                # Metadata only: external graph overlays are never fed back
                # into review scoring, impact ranking, or test selection.
                review_registry = AdapterRegistry(str(project))
                report["external_graph_sources"] = []
                for adapter_id in ("graphify", "codegraph"):
                    external_status = review_registry.status(adapter_id)
                    external_artifact = external_status.get("artifact") or {}
                    report["external_graph_sources"].append({
                        "adapter_id": adapter_id, "source": adapter_id, "evidence_class": "DOC_INFERRED",
                        "status": external_status.get("status"), "freshness": external_status.get("freshness"),
                        "entities": external_artifact.get("nodes", 0), "relationships": external_artifact.get("edges", 0),
                        "source_path": external_artifact.get("source_path"), "fingerprint": external_artifact.get("source_fingerprint"),
                        "confidence": "confirmed_or_likely", "network_used": False,
                    })
                from impact_engine.review_history import record_review
                report["review_id"] = record_review(str(project), report)
                return self._send_json(200, _mode_api_response("review", report))
            if parsed.path == "/api/inspect":
                project_path = str(body.get("project_path") or self.state.project_path or self.state.default_project or "").strip()
                entity = str(body.get("entity") or "").strip()
                if not project_path or not entity:
                    return self._send_json(400, {"status": "error", "error": "project_path and entity are required"})
                ensure_project_storage(project_path)
                report = build_inspect_report(
                    project_path,
                    entity=entity,
                    graph_path=body.get("graph_path"),
                    refresh=str(body.get("refresh") or "never"),
                    max_context=int(body.get("max_context", 12)),
                )
                report["semantic_evidence"] = _semantic_evidence(project_path, report, body.get("graph_path"))
                report["lsp_evidence"] = _lsp_evidence(project_path, report, body.get("graph_path"))
                report["boundary_evidence"] = _boundary_evidence(project_path, report, body.get("graph_path"))
                report["otel_evidence"] = _otel_evidence(project_path, report, body.get("graph_path"))
                report["security_evidence"] = _security_evidence(project_path, report, body.get("graph_path"))
                report["external_graph_evidence"] = _external_graph_evidence(project_path, report)
                return self._send_json(200, _mode_api_response("inspect", report))
            if parsed.path == "/api/investigate":
                project_path = str(body.get("project_path") or self.state.project_path or self.state.default_project or "").strip()
                entity = str(body.get("entity") or "").strip()
                if not project_path or not entity:
                    return self._send_json(400, {"status": "error", "error": "project_path and entity are required"})
                ensure_project_storage(project_path)
                report = build_investigate_report(
                    project_path,
                    entity=entity,
                    graph_path=body.get("graph_path"),
                    direction=str(body.get("direction") or "both"),
                    depth=int(body.get("depth", 8)),
                    runtime_validate=bool(body.get("runtime_validate", False)),
                    max_nodes=int(body.get("max_nodes", 500)),
                    max_edges=int(body.get("max_edges", 1000)),
                    refresh=str(body.get("refresh") or "never"),
                )
                overlay_mode = str(body.get("overlay") or "codeslicer").lower()
                if overlay_mode in {"graphify", "combined"}:
                    overlay = _bounded_overlay(AdapterRegistry(project_path).overlay("graphify"))
                    report["architecture_overlay"] = overlay or {"status": "unavailable", "message": "Graphify overlay is not enabled with a fresh local artifact."}
                if bool(body.get("semantic_context", False)):
                    report["semantic_context"] = _bounded_semantic_context(project_path, report, body.get("graph_path"), max_items=min(max(int(body.get("semantic_max_items", 40)), 1), 100))
                if bool(body.get("lsp_context", False)):
                    report["lsp_context"] = _bounded_lsp_context(project_path, report, body.get("graph_path"), max_items=min(max(int(body.get("lsp_max_items", 40)), 1), 100))
                if bool(body.get("boundary_context", False)):
                    report["boundary_context"] = _bounded_boundary_context(project_path, report, body.get("graph_path"), max_items=min(max(int(body.get("boundary_max_items", 40)), 1), 100))
                if bool(body.get("otel_context", False)):
                    report["otel_context"] = _bounded_otel_context(project_path, report, body.get("graph_path"), max_items=min(max(int(body.get("otel_max_items", 40)), 1), 100))
                if bool(body.get("security_context", False)):
                    report["security_context"] = _bounded_security_context(project_path, report, body.get("graph_path"), max_items=min(max(int(body.get("security_max_items", 40)), 1), 100))
                if bool(body.get("joern_context", False)):
                    report["joern_context"] = _bounded_joern_context(
                        project_path, report,
                        max_nodes=min(max(int(body.get("joern_max_nodes", 80)), 1), 200),
                        max_edges=min(max(int(body.get("joern_max_edges", 160)), 1), 400),
                        max_paths=min(max(int(body.get("joern_max_paths", 40)), 1), 100),
                    )
                if bool(body.get("external_graph_context", False)):
                    report["external_graph_context"] = _external_graph_evidence(project_path, report, max_items=min(max(int(body.get("external_graph_max_items", 40)), 1), 100))
                return self._send_json(200, _mode_api_response("investigate", report))
            if parsed.path == "/api/ci":
                project_path = str(body.get("project_path") or self.state.project_path or self.state.default_project or "").strip()
                if not project_path:
                    return self._send_json(400, {"status": "error", "error": "project_path is required"})
                ensure_project_storage(project_path)
                diff_text = body.get("diff_text")
                if body.get("diff_file") and diff_text is None:
                    diff_text = Path(str(body["diff_file"])).expanduser().resolve().read_text(encoding="utf-8")
                report = build_ci_report(
                    project_path,
                    base=body.get("base"),
                    policy_path=body.get("policy_path") or body.get("policy"),
                    graph_path=body.get("graph_path"),
                    diff_text=diff_text,
                    refresh=str(body.get("refresh") or "auto"),
                    run_tests=bool(body.get("run_tests", False)),
                    test_command=body.get("test_command"),
                )
                response: dict[str, Any] = _mode_api_response("ci", report)
                if str(body.get("format") or "json") == "sarif":
                    response["sarif"] = to_sarif(report)
                return self._send_json(200, response)
            if parsed.path == "/api/review/run-test":
                project_path = str(body.get("project_path") or self.state.project_path or "").strip()
                file_name = str(body.get("file") or "").strip().replace("\\", "/")
                if not project_path or not file_name:
                    return self._send_json(400, {"status": "error", "error": "project_path and file are required"})
                project = Path(project_path).expanduser().resolve()
                candidate = (project / file_name).resolve()
                if not project.is_dir() or not candidate.is_file() or project not in candidate.parents:
                    return self._send_json(422, {"status": "error", "error": "file must be an existing file inside project_path"})
                command = _test_command_for_file(project, file_name)
                if not command:
                    return self._send_json(422, {"status": "unsupported", "error": "No safe test runner is configured for this file"})
                try:
                    completed = subprocess.run(
                        command, cwd=project, capture_output=True, text=True,
                        timeout=min(max(int(body.get("timeout", 120)), 1), 600), shell=False,
                    )
                except subprocess.TimeoutExpired as exc:
                    return self._send_json(504, {"status": "timeout", "command": command, "stdout": exc.stdout or "", "stderr": exc.stderr or ""})
                return self._send_json(200, {
                    "status": "ok", "command": command, "exit_code": completed.returncode,
                    "passed": completed.returncode == 0,
                    "stdout": completed.stdout[-12000:], "stderr": completed.stderr[-12000:],
                })
            if parsed.path == "/api/review/feedback":
                project_path = str(body.get("project_path") or self.state.project_path or "").strip()
                from impact_engine.review_history import add_feedback
                add_feedback(project_path, str(body.get("review_id") or ""), str(body.get("value") or ""), body.get("reason"))
                return self._send_json(200, {"status": "ok"})
            if parsed.path == "/api/review/history":
                project_path = str(body.get("project_path") or self.state.project_path or "").strip()
                from impact_engine.review_history import list_history
                return self._send_json(200, {"status": "ok", "items": list_history(project_path, int(body.get("limit", 20)))})
            if parsed.path == "/api/query":
                return self._send_json(200, {"status": "ok", "result": self._run_typed_query(body)})
            if parsed.path == "/api/incremental":
                return self._send_json(501, {"status": "unsupported", "message": "Use impact-engine analyze-incremental for a real changed-file comparison."})
            return self._send_json(404, {"status": "error", "error": "not_found"})
        except Exception as exc:
            self._send_json(500, {"status": "error", "error": str(exc)})

    def _graph_document(self) -> GraphDocument:
        graph = self.state.snapshot().get("graph")
        if not graph:
            raise RuntimeError("No analyzed graph. Run /api/analyze first.")
        return GraphDocument.from_dict(graph)

    def _run_typed_query(self, body: dict[str, Any]) -> dict[str, Any]:
        graph = self._graph_document()
        query_type = str(body.get("type") or "impact")
        if query_type.startswith("diagnostics"):
            metadata = graph.metadata
            return {
                "request": body,
                "response": {
                    "unknown_regions": metadata.get("unknown_regions", {}),
                    "diagnostics": metadata.get("diagnostics", {}),
                },
            }
        if query_type.startswith("explain") and body.get("from") and body.get("to"):
            return {"request": body, "response": explain_edge(graph, str(body["from"]), str(body["to"]), body.get("kind"))}
        result = impact_query(
            graph,
            target=str(body.get("target") or ""),
            direction="downstream" if "database" in query_type else "upstream",
            max_depth=int(body.get("max_depth", 8)),
            min_confidence=float(body.get("min_confidence", 0.0)),
        )
        return {"request": body, "response": result}

    def _libraries(self) -> list[dict[str, Any]]:
        analysis = self.state.snapshot(include_graph=False).get("analysis") or {}
        inventory = analysis.get("inventory") or {}
        graph = self.state.snapshot().get("graph") or {}
        contexts = {
            str(item.get("library")): item
            for item in (graph.get("metadata", {}).get("support_pack_context", []) or [])
            if isinstance(item, dict)
        }
        names: list[tuple[str, str, str]] = []
        for ecosystem, values in (inventory.get("declared_dependencies_by_ecosystem", {}) or {}).items():
            for value in values or []:
                names.append((str(value), str(ecosystem), "declared"))
        for ecosystem, values in (inventory.get("external_imports_by_ecosystem", {}) or {}).items():
            for value in values or []:
                names.append((str(value), str(ecosystem), "external_import"))
        result = []
        seen = set()
        for name, ecosystem, source in sorted(names):
            key = (name, ecosystem)
            if key in seen:
                continue
            seen.add(key)
            context = contexts.get(name, {})
            result.append({
                "name": name,
                "ecosystem": ecosystem,
                "version": None,
                "status": source,
                "trust_level": context.get("trust_level"),
                "confidence_cap": None,
                "coverage": "unknown",
                "last_checked": None,
                "source": source,
            })
        return result


def create_server(host: str, port: int, frontend_dir: str, state: LocalApiState) -> ThreadingHTTPServer:
    directory = str(Path(frontend_dir).resolve())

    class Handler(LocalApiHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=directory, **kwargs)

    server = ThreadingHTTPServer((host, port), Handler)
    server.impact_state = state  # type: ignore[attr-defined]
    return server


def default_frontend_dir() -> str:
    """Locate the UI in a checkout first and in an installed wheel second."""
    source_frontend = Path(__file__).resolve().parents[2] / "frontend"
    if source_frontend.is_dir():
        return str(source_frontend)
    packaged_frontend = package_files("impact_engine").joinpath("frontend")
    if packaged_frontend.is_dir():
        return str(packaged_frontend)
    # Keep the old path as a useful diagnostic if a broken third-party build
    # omits static files; the release E2E test guards this case.
    return str(source_frontend)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="impact-engine-local-api")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--frontend-dir", default=default_frontend_dir())
    parser.add_argument("--default-project", default=None)
    args = parser.parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    state = LocalApiState(args.default_project, str(repo_root / "support_packs"))
    server = create_server(args.host, args.port, args.frontend_dir, state)
    print(f"Impact Engine local API: http://{args.host}:{args.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
