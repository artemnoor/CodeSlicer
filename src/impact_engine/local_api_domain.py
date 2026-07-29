"""Local HTTP API and static frontend host for the Impact Engine UI.

The browser never runs analysis logic and never receives a mock graph.  This
module is a thin same-origin boundary around the existing analysis and impact
query APIs.  It intentionally uses only the Python standard library so the
local distribution stays lightweight.
"""
from __future__ import annotations

import argparse
import hashlib
from importlib.resources import files as package_files
import ipaddress
import json
import html
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from dataclasses import asdict
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse, urlsplit

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
from impact_engine.adapters.lsp import configure_lsp, disable_lsp, lsp_privacy, map_lsp_overlay, preflight_lsp, probe_lsp, query_lsp
from impact_engine.adapters.otel import map_otel_overlay
from impact_engine.adapters.scip import map_scip_overlay
from impact_engine.adapters.boundary import map_boundary_overlay
from impact_engine.adapters.security import map_security_overlay
from impact_engine.adapters.joern import bounded_joern_context
from impact_engine.adapters.native import native_profile, run_native_operation
from impact_engine.graph_workspaces import build_workspace
from impact_engine.tool_runtime import ToolRuntime
from impact_engine.adapters.graphify_paths import find_graphify_graph, graphify_viewer_cache_path, graphify_viewer_ready
from impact_engine.approvals import ApprovalStore


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


def _project_identity(project: Path, project_id: str | None = None) -> str:
    """Stable Docker identity: explicit namespace plus repository origin.

    Lockfiles are intentionally excluded: dependency updates must not make a
    valid state look like it belongs to another project.
    """
    digest = hashlib.sha256()
    digest.update(b"codeslicer-docker-state/v2\0")
    digest.update((project_id or "host-local").encode("utf-8"))
    git_config = project / ".git" / "config"
    if git_config.is_file():
        for line in git_config.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().startswith("url ="):
                digest.update(line.strip().encode("utf-8"))
    for relative in ("pyproject.toml", "package.json", "go.mod", "*.sln"):
        candidates = list(project.glob(relative)) if "*" in relative else [project / relative]
        for candidate in sorted(candidates):
            if candidate.is_file():
                digest.update(candidate.name.encode("utf-8"))
                digest.update(candidate.read_bytes()[:64_000])
    return digest.hexdigest()


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
    candidate_ids = {node.id for node in candidate_nodes}
    # An overview deliberately starts from high-level entities such as routes
    # and modules. Their confirmed handler/method is often not high-level,
    # though, so requiring both endpoints to be in that initial set silently
    # erased every meaningful relationship from real projects (for example
    # Spring PetClinic's ROUTE_HANDLES edges).  Keep one-hop canonical edges
    # available and add their endpoint while constructing the bounded view.
    include_one_hop_neighbors = level == "overview" or bool(query)
    candidate_edges = [
        edge for edge in graph.edges
        if float(edge.confidence) >= min_confidence
        and (
            edge.from_node in candidate_ids or edge.to_node in candidate_ids
            if include_one_hop_neighbors
            else edge.from_node in candidate_ids and edge.to_node in candidate_ids
        )
    ]
    if edge_kinds:
        candidate_edges = [edge for edge in candidate_edges if edge.kind.upper() in edge_kinds]
    if evidence_classes:
        candidate_edges = [edge for edge in candidate_edges if "static_extracted" in evidence_classes]
    if evidence_sources:
        candidate_edges = [edge for edge in candidate_edges if "codeslicer" in evidence_sources or str(edge.source).lower() in evidence_sources]
    if relation_scopes:
        candidate_edges = [edge for edge in candidate_edges if _projection_relation_scope(edge) in relation_scopes]
    graph_nodes = {node.id: node for node in graph.nodes}
    edges_by_node: dict[str, list[Any]] = {}
    for edge in candidate_edges:
        edges_by_node.setdefault(edge.from_node, []).append(edge)
        edges_by_node.setdefault(edge.to_node, []).append(edge)
    selected_nodes = []
    selected_ids: set[str] = set()

    def include(node_id: str) -> bool:
        node = graph_nodes.get(node_id)
        if node is None or node_id in selected_ids or len(selected_nodes) >= max_nodes:
            return False
        selected_nodes.append(node)
        selected_ids.add(node_id)
        return True

    for node in candidate_nodes:
        if len(selected_nodes) >= max_nodes:
            break
        include(node.id)
        # Kind-filtered views are intentionally exact.  Default/detail/query
        # views may include a direct endpoint so every displayed edge remains
        # inspectable instead of becoming an invisible dangling relation.
        if node_kinds:
            continue
        for edge in edges_by_node.get(node.id, []):
            other = edge.to_node if edge.from_node == node.id else edge.from_node
            include(other)
            if len(selected_nodes) >= max_nodes:
                break
    selected_edges = [
        edge for edge in candidate_edges
        if edge.from_node in selected_ids and edge.to_node in selected_ids
    ][:max_edges]
    nodes = [{**node.to_dict(), "canonical": True, "source": "CodeSlicer", "evidence_source": "CodeSlicer", "evidence_class": "STATIC_EXTRACTED", "overlay": False} for node in selected_nodes]
    edges = [{**edge.to_dict(), "canonical": True, "source": edge.source, "evidence_source": "CodeSlicer", "evidence_class": "STATIC_EXTRACTED", "relation_scope": _projection_relation_scope(edge), "overlay": False} for edge in selected_edges]
    # Resolve this through the stable facade at call time.  Existing extension
    # points patch ``impact_engine.local_api._project_overview``.
    from impact_engine import local_api as local_api_facade

    overview = local_api_facade._project_overview(project_path)
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
        "truncated": len(candidate_nodes) > len(selected_nodes) or len(candidate_edges) > len(selected_edges),
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


def _graphify_viewer_cache_path(project_path: str | Path) -> Path:
    return graphify_viewer_cache_path(project_path)


def _render_graphify_native_html(project_path: str | Path) -> str:
    """Compatibility reader for tests and callers; it never spawns a process."""
    cache = _graphify_viewer_cache_path(project_path)
    if cache.is_file():
        return cache.read_text(encoding="utf-8")[:4 * 1024 * 1024]
    return "<!DOCTYPE html><html><body><h2>Graphify Native Viewer</h2><p>Нативный граф Graphify для этого проекта ещё не построен.</p><p>Канонический граф CodeSlicer здесь намеренно не показывается.</p></body></html>"


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




__all__ = [name for name in globals() if not name.startswith("__")]
