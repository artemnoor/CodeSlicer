"""Task-oriented, local-only graph workspaces.

The canonical CodeSlicer graph is deliberately *not* a container for every
external graph.  Optional tools own separate graph workspaces and may expose
only explicit, provenance-bearing bridges to the canonical graph.  This keeps
impact ranking deterministic while still making architecture, semantic,
runtime and security views useful in the same local UI.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from impact_engine.adapters.registry import AdapterRegistry
from impact_engine.models import GraphDocument


@dataclass(frozen=True)
class WorkspaceDefinition:
    id: str
    title: str
    purpose: str
    source_ids: tuple[str, ...]
    canonical: bool = False


WORKSPACES: tuple[WorkspaceDefinition, ...] = (
    WorkspaceDefinition("impact", "Влияние изменений", "Риск, затронутый код и тесты; только канонический граф CodeSlicer.", ("codeslicer",), True),
    WorkspaceDefinition("architecture", "Архитектура", "Модули, сообщества и архитектурные связи из внешних графов.", ("graphify", "codegraph")),
    WorkspaceDefinition("gortex", "Gortex", "Отдельный knowledge graph Gortex: файлы, символы, вызовы и multi-repo связи.", ("gortex",)),
    WorkspaceDefinition("symbols", "Символы", "Определения, references и implementations из локальных semantic sources.", ("lsp", "scip")),
    WorkspaceDefinition("contracts", "Контракты", "HTTP API и асинхронные события как отдельный contract graph.", ("openapi", "asyncapi")),
    WorkspaceDefinition("runtime", "Runtime", "Наблюдавшиеся локально пути выполнения из OpenTelemetry.", ("otel",)),
    WorkspaceDefinition("security", "Security", "Data-flow, findings и зависимости; не участвуют в review ranking.", ("joern", "cyclonedx", "spdx", "sarif")),
    WorkspaceDefinition("bridges", "Связи графов", "Только подтверждённые мосты между независимыми графами.", ()),
)

_WORKSPACE_BY_ID = {item.id: item for item in WORKSPACES}


def workspace_catalog(project_path: str | Path) -> list[dict[str, Any]]:
    """Return task-oriented workspaces without loading any graph content."""
    registry = AdapterRegistry(project_path)
    statuses = {item["id"]: item for item in registry.list()}
    result: list[dict[str, Any]] = []
    for item in WORKSPACES:
        if item.canonical:
            available = True
            ready_sources = ["codeslicer"]
        elif item.id == "bridges":
            ready_sources = [adapter_id for adapter_id, status in statuses.items() if status.get("status") == "ready" and status.get("enabled")]
            available = bool(ready_sources)
        else:
            ready_sources = [adapter_id for adapter_id in item.source_ids if statuses.get(adapter_id, {}).get("status") == "ready" and statuses.get(adapter_id, {}).get("enabled")]
            available = bool(ready_sources)
        result.append({
            "id": item.id, "title": item.title, "purpose": item.purpose,
            "source_ids": list(item.source_ids), "ready_sources": ready_sources,
            "available": available, "ranking_owner": item.canonical,
            "privacy": {"mode": "local-only", "network_used": False},
        })
    return result


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _node_path(node: dict[str, Any]) -> str:
    props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
    provenance = node.get("provenance") if isinstance(node.get("provenance"), dict) else {}
    value = (
        node.get("file") or node.get("path") or node.get("source_file")
        or props.get("file") or props.get("path") or props.get("external_source_file")
        or provenance.get("source_file")
    )
    return _safe_text(value).replace("\\", "/").lstrip("./").lower()


def _canonical_node_payload(node: Any) -> dict[str, Any]:
    return {
        **node.to_dict(), "canonical": True, "overlay": False,
        "source": "codeslicer", "evidence_source": "CodeSlicer",
        "evidence_class": "STATIC_EXTRACTED", "participates_in_ranking": True,
    }


def _canonical_edge_payload(edge: Any) -> dict[str, Any]:
    return {
        **edge.to_dict(), "canonical": True, "overlay": False,
        "source": "codeslicer", "evidence_source": "CodeSlicer",
        "evidence_class": "STATIC_EXTRACTED", "participates_in_ranking": True,
    }


def _canonical_graph(canonical: GraphDocument, max_nodes: int, max_edges: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = [_canonical_node_payload(node) for node in canonical.nodes[:max_nodes]]
    ids = {node["id"] for node in nodes}
    edges = [_canonical_edge_payload(edge) for edge in canonical.edges if edge.from_node in ids and edge.to_node in ids][:max_edges]
    return nodes, edges


def _external_graph(adapter_id: str, overlay: dict[str, Any], max_nodes: int, max_edges: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Namespace external ids so separate tool graphs never collide."""
    raw_nodes = list(overlay.get("nodes") or [])[:max_nodes]
    id_map = {str(node.get("id")): f"{adapter_id}::{node.get('id')}" for node in raw_nodes if node.get("id")}
    nodes: list[dict[str, Any]] = []
    for raw in raw_nodes:
        external_id = _safe_text(raw.get("id"))
        if not external_id:
            continue
        node = dict(raw)
        node["id"] = id_map[external_id]
        node["external_id"] = external_id
        node["canonical"] = False
        node["overlay"] = True
        node["source"] = adapter_id
        node["evidence_source"] = adapter_id
        node["participates_in_ranking"] = False
        nodes.append(node)
    edges: list[dict[str, Any]] = []
    for raw in list(overlay.get("edges") or []):
        source = id_map.get(_safe_text(raw.get("from")))
        target = id_map.get(_safe_text(raw.get("to")))
        if not source or not target:
            continue
        edge = dict(raw)
        raw_edge_id = _safe_text(raw.get("id")) or f"{raw.get('from')}->{raw.get('to')}"
        edge["id"] = f"{adapter_id}::{raw_edge_id}"
        edge["from"] = source
        edge["to"] = target
        edge["canonical"] = False
        edge["overlay"] = True
        edge["source"] = adapter_id
        edge["evidence_source"] = adapter_id
        edge["participates_in_ranking"] = False
        edges.append(edge)
        if len(edges) >= max_edges:
            break
    return nodes, edges


def _bridge_candidates(canonical: GraphDocument, adapter_id: str, external_nodes: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Create only conservative bridges: exact id or name+file equality.

    Name-only matches are intentionally not bridges: they make large codebases
    look connected when the evidence is ambiguous.
    """
    canonical_by_id = {node.id: node for node in canonical.nodes}
    canonical_by_name_path = {
        (_safe_text(node.name).lower(), _node_path(node.to_dict())): node
        for node in canonical.nodes if _safe_text(node.name) and _node_path(node.to_dict())
    }
    bridges: list[dict[str, Any]] = []
    for external in external_nodes:
        external_id = _safe_text(external.get("external_id"))
        canonical_node = canonical_by_id.get(external_id)
        match_kind = "exact_id" if canonical_node else ""
        if canonical_node is None:
            name = _safe_text(external.get("name")).lower()
            path = _node_path(external)
            if name and path:
                canonical_node = canonical_by_name_path.get((name, path))
                match_kind = "name_and_file" if canonical_node else ""
        if canonical_node is None:
            continue
        bridges.append({
            "id": f"bridge::{adapter_id}::{external_id}::{canonical_node.id}",
            "kind": "BRIDGES_TO", "from": external["id"], "to": canonical_node.id,
            "source": adapter_id, "evidence_source": adapter_id,
            "evidence_class": "CROSS_GRAPH_BRIDGE", "canonical": False, "overlay": True,
            "confirmed": True, "resolution": "confirmed", "confidence": 1.0,
            "participates_in_ranking": False,
            "provenance": {"adapter_id": adapter_id, "match": match_kind, "local_only": True},
        })
    return bridges


def build_workspace(
    project_path: str | Path,
    canonical: GraphDocument | None,
    *,
    workspace_id: str = "impact",
    source_id: str | None = None,
    max_nodes: int = 120,
    max_edges: int = 200,
) -> dict[str, Any]:
    """Build one graph at a time and expose bridges as a distinct view."""
    if workspace_id not in _WORKSPACE_BY_ID:
        raise ValueError(f"workspace must be one of: {', '.join(_WORKSPACE_BY_ID)}")
    max_nodes = min(max(int(max_nodes), 1), 300)
    max_edges = min(max(int(max_edges), 1), 600)
    definition = _WORKSPACE_BY_ID[workspace_id]
    registry = AdapterRegistry(project_path)
    catalog = workspace_catalog(project_path)
    status_by_id = {item["id"]: item for item in registry.list()}

    if workspace_id == "impact":
        if canonical is None:
            nodes: list[dict[str, Any]] = []
            edges: list[dict[str, Any]] = []
            status = "missing"
            diagnostics = ["canonical CodeSlicer graph is missing"]
        else:
            nodes, edges = _canonical_graph(canonical, max_nodes, max_edges)
            status = "ready"
            diagnostics = []
        return _workspace_result(definition, workspace_id, "codeslicer", nodes, edges, [], status, diagnostics, catalog)

    selected_sources = list(definition.source_ids)
    if workspace_id == "bridges":
        selected_sources = [adapter_id for adapter_id, status in status_by_id.items() if status.get("status") == "ready" and status.get("enabled")]
    if source_id:
        allowed_sources = selected_sources if workspace_id == "bridges" else list(definition.source_ids)
        if source_id not in allowed_sources:
            raise ValueError(f"source_id {source_id} is not available for workspace {workspace_id}")
        selected_sources = [source_id]
    elif workspace_id != "bridges":
        # A workspace is a graph, not a silent union of tool outputs.  Choose
        # the first ready source deterministically; the caller can select a
        # different source explicitly through ``source_id``.
        ready_sources = [adapter_id for adapter_id in selected_sources if status_by_id.get(adapter_id, {}).get("status") == "ready" and status_by_id.get(adapter_id, {}).get("enabled")]
        selected_sources = (ready_sources or selected_sources)[:1]

    graph_entries: list[dict[str, Any]] = []
    all_external_nodes: list[dict[str, Any]] = []
    all_external_edges: list[dict[str, Any]] = []
    diagnostics: list[str] = []
    for adapter_id in selected_sources:
        adapter_status = status_by_id.get(adapter_id, {})
        if adapter_status.get("status") != "ready" or not adapter_status.get("enabled"):
            diagnostics.append(f"{adapter_id}: source is not ready")
            continue
        overlay = registry.overlay(adapter_id)
        if not overlay:
            diagnostics.append(f"{adapter_id}: no local graph artifact is available")
            continue
        nodes, edges = _external_graph(adapter_id, overlay, max_nodes, max_edges)
        graph_entries.append({"id": adapter_id, "nodes": nodes, "edges": edges})
        all_external_nodes.extend(nodes)
        all_external_edges.extend(edges)

    bridges: list[dict[str, Any]] = []
    if canonical is not None:
        for entry in graph_entries:
            bridges.extend(_bridge_candidates(canonical, entry["id"], entry["nodes"]))

    if workspace_id == "bridges":
        bridge_ids = {edge["from"] for edge in bridges} | {edge["to"] for edge in bridges}
        external_by_id = {node["id"]: node for node in all_external_nodes}
        canonical_by_id = {node.id: _canonical_node_payload(node) for node in (canonical.nodes if canonical else [])}
        nodes = [external_by_id[node_id] for node_id in bridge_ids if node_id in external_by_id]
        nodes += [canonical_by_id[node_id] for node_id in bridge_ids if node_id in canonical_by_id]
        edges = bridges[:max_edges]
        status = "ready" if bridges else "empty"
        if not bridges:
            diagnostics.append("No confirmed bridges exist between the enabled local graphs.")
        selected_source = "bridges"
    else:
        nodes = all_external_nodes[:max_nodes]
        selected_ids = {node["id"] for node in nodes}
        edges = [edge for edge in all_external_edges if edge.get("from") in selected_ids and edge.get("to") in selected_ids][:max_edges]
        status = "ready" if graph_entries else "unavailable"
        selected_source = source_id or (graph_entries[0]["id"] if len(graph_entries) == 1 else "multiple")
    return _workspace_result(definition, workspace_id, selected_source, nodes, edges, bridges[:max_edges], status, diagnostics, catalog, graph_entries)


def _workspace_result(
    definition: WorkspaceDefinition,
    workspace_id: str,
    selected_source: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    bridges: list[dict[str, Any]],
    status: str,
    diagnostics: list[str],
    catalog: list[dict[str, Any]],
    graphs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "workspace": {"id": workspace_id, "title": definition.title, "purpose": definition.purpose, "ranking_owner": definition.canonical},
        "selected_source": selected_source,
        "nodes": nodes,
        "edges": edges,
        "bridges": bridges,
        "graphs": graphs or ([{"id": "codeslicer", "nodes": nodes, "edges": edges}] if definition.canonical else []),
        "total_nodes": len(nodes), "total_edges": len(edges), "total_bridges": len(bridges),
        "diagnostics": diagnostics,
        "workspaces": catalog,
        "privacy": {"mode": "local-only", "network_used": False},
        "ranking": {"owner": "codeslicer", "external_graphs_affect_ranking": False},
    }
