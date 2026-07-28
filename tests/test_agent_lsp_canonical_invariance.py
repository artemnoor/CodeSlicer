"""Agent-LSP evidence is context only unless a future merge policy opts in."""
from __future__ import annotations

import json
import os
from pathlib import Path

from impact_engine.models import Edge, GraphDocument, Node
from impact_engine.project_storage import ensure_project_storage
from impact_engine.review import build_review_report


def _graph(project: Path) -> GraphDocument:
    graph = GraphDocument(metadata={"project_path": str(project)})
    graph.add_node(Node(id="route", kind="ROUTE", name="POST /orders", properties={"file": "api.py"}))
    graph.add_node(Node(id="service", kind="FUNCTION", name="create_order", properties={"file": "service.py"}))
    graph.add_edge(Edge(id="route-service", from_node="route", to_node="service", kind="CALLS", confidence=0.9))
    return graph


def _canonical(graph: GraphDocument, report: dict) -> dict:
    """The canonical projection must not observe optional runtime evidence."""
    return {
        "nodes": sorted((node.id, node.kind, node.name) for node in graph.nodes),
        "edges": sorted((edge.id, edge.from_node, edge.to_node, edge.kind) for edge in graph.edges),
        "impact_paths": report["chains"],
        "risk": report["risk"],
        "ranking": report["top_impacts"],
        "recommended_tests": report["test_recommendations"],
    }


def _write_report(payload: dict) -> None:
    value = os.environ.get("IMPACT_AGENT_LSP_CANONICAL_REPORT")
    if value:
        target = Path(value); target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_agent_lsp_overlay_states_do_not_change_canonical_review(tmp_path: Path):
    project = tmp_path / "project"; project.mkdir()
    graph = _graph(project)
    baseline = build_review_report(str(project), graph=graph, diff_text="", refresh="never")
    storage = ensure_project_storage(project)
    overlay = storage / "artifacts" / "agent-lsp" / "overlay.json"; overlay.parent.mkdir(parents=True)
    overlay.write_text(json.dumps({"schema_version": "CodeSlicerLspEvidenceOverlay/v1", "nodes": [{"id": "lsp-node"}], "edges": []}), encoding="utf-8")
    state = storage / "adapters" / "agent_lsp.json"
    states = [
        {"enabled": False},
        {"enabled": True, "backend": "agent_lsp", "overlay_path": str(overlay), "project_head": None},
        {"enabled": True, "backend": "agent_lsp", "overlay_path": str(overlay), "project_head": "stale"},
        {"enabled": True, "backend": "agent_lsp", "overlay_path": str(overlay), "runtime_status": "degraded", "diagnostics": ["forced crash"]},
    ]
    baseline_canonical = _canonical(graph, baseline)
    snapshots = []
    for index, value in enumerate(states):
        overlay.write_text(json.dumps({"schema_version": "CodeSlicerLspEvidenceOverlay/v1", "state": index, "nodes": [{"id": f"lsp-node-{index}"}], "edges": []}), encoding="utf-8")
        state.write_text(json.dumps(value), encoding="utf-8")
        report = build_review_report(str(project), graph=graph, diff_text="", refresh="never")
        snapshots.append({"state": ("disabled", "ready", "stale", "degraded")[index], "canonical": _canonical(graph, report), "semantic_overlay": json.loads(overlay.read_text(encoding="utf-8"))})
    assert all(snapshot["canonical"] == baseline_canonical for snapshot in snapshots)
    assert len({snapshot["semantic_overlay"]["nodes"][0]["id"] for snapshot in snapshots}) == 4
    _write_report({"baseline": baseline_canonical, "states": snapshots, "canonical_diff": []})
