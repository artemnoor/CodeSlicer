"""High-signal real acceptance checks for the stabilized package."""
from __future__ import annotations

import importlib
import json
import os
from pathlib import Path

import pytest

from impact_engine.analysis.pipeline import analyze_project_core
from impact_engine.impact import impact_query, explain_edge
from impact_engine.models import GraphDocument, Node
from impact_engine.support_packs.resolution import apply_support_pack_rules

ROOT = Path(__file__).resolve().parents[1]
PROJECT_PATH = ROOT / "examples" / "golden_cases" / "python_di_basic"
FASTAPI_PACK = ROOT / "support_packs" / "python" / "fastapi" / "support_pack.json"


def _mvp_edge(graph: GraphDocument):
    return next(
        (
            e for e in graph.edges
            if e.kind == "CALLS"
            and e.from_node == "services.OrderService.create_order"
            and e.to_node == "repositories.OrderRepository.save"
        ),
        None,
    )


def test_real_acceptance_core_graph_impact_and_explain(tmp_path):
    assert importlib.import_module("impact_engine") is not None
    out_path = tmp_path / "graph.json"

    result = analyze_project_core(str(PROJECT_PATH), out_path=str(out_path))
    assert result["status"] == "ok"
    assert out_path.exists()

    graph = GraphDocument.from_json(out_path.read_text(encoding="utf-8"))
    edge = _mvp_edge(graph)
    assert edge is not None
    assert edge.source == "INFERRED"
    assert edge.confidence >= 0.80
    assert len(edge.evidence) >= 1

    impact = impact_query(
        graph,
        symbol="repositories.OrderRepository.save",
        direction="upstream",
        max_depth=3,
        min_confidence=0.8,
    )
    affected_ids = {n["id"] for n in impact["affected_nodes"]}
    assert "services.OrderService.create_order" in affected_ids

    explanation = explain_edge(
        graph,
        "services.OrderService.create_order",
        "repositories.OrderRepository.save",
    )
    assert explanation["found"] is True
    assert explanation["source"] == "INFERRED"
    assert len(explanation["evidence_chain"]) >= 1


def test_real_acceptance_support_pack_source_graphify_network_and_research(tmp_path, monkeypatch):
    import requests

    def fail_network(*args, **kwargs):  # pragma: no cover - failure path only
        raise AssertionError("normal analyze must not access the network")

    monkeypatch.setattr(requests, "get", fail_network)
    result = analyze_project_core(str(PROJECT_PATH), out_path=str(tmp_path / "no_net_graph.json"))
    assert result["status"] == "ok"
    assert result["diagnostics"]["normal_analyze_requires_internet"] is False

    graph = GraphDocument()
    graph.add_node(Node(
        id="call:component:1",
        kind="CALL_EXPR",
        name="render",
        properties={"scope": "components.App", "call_name": "React.useEffect"},
    ))
    pack = {
        "library": "react",
        "version_range": ">=18",
        "language": "javascript",
        "edge_rules": [{
            "id": "react-use-effect",
            "match": {"node_kind": "CALL_EXPR", "call_name": "React.useEffect"},
            "emit": {"kind": "DEPENDS_ON", "to": "external:react.useEffect", "source": "INFERRED", "confidence": 0.65},
        }],
    }
    resolved = apply_support_pack_rules(graph, [pack])
    support_edge = next(e for e in resolved.edges if e.properties.get("support_pack_rule_id") == "react-use-effect")
    assert support_edge.source == "SUPPORT_PACK"

    from impact_engine.adapters.graphify import is_graphify_available
    assert isinstance(is_graphify_available(), bool)

    from impact_engine.research.workflow import init_workflow
    old_cwd = Path.cwd()
    try:
        os.chdir(tmp_path)
        wf_id = init_workflow(str(PROJECT_PATH), "fastapi", "python")
        assert (tmp_path / ".impact_engine" / "research_workflows" / wf_id / "research_request.json").exists()
    finally:
        os.chdir(old_cwd)


def test_real_acceptance_mcp_tools_json_serializable(tmp_path, monkeypatch):
    import impact_engine.mcp.server as server
    from impact_engine.research.fetcher import FetchResult, WebFetcher

    def fake_fetch(self: WebFetcher, url: str) -> FetchResult:
        return FetchResult(url=url, status_code=200, content_type="text/html", text_excerpt="fastapi docs excerpt")

    monkeypatch.setattr(WebFetcher, "fetch", fake_fetch)

    old_cwd = Path.cwd()
    try:
        os.chdir(tmp_path)
        graph_path = tmp_path / "mcp_graph.json"
        candidate = {
            "library": "fastapi",
            "version_range": ">=0.60.0",
            "language": "python",
            "status": "experimental",
            "sources": [{"type": "documentation", "url": "https://pypi.org/project/fastapi/"}],
            "patterns": [],
            "edge_rules": [{
                "id": "fastapi-doc-rule",
                "type": "standard",
                "match": {"node_kind": "CALL_EXPR", "call_name": "fastapi.Depends"},
                "emit": {"kind": "DEPENDS_ON", "to": "external:fastapi.Depends", "confidence": 0.70, "evidence_ref": "https://pypi.org/project/fastapi/"},
                "evidence_ref": "https://pypi.org/project/fastapi/",
            }],
            "confidence_rules": [],
            "playground_cases": [],
        }

        workflow = server.create_library_research_workflow(str(PROJECT_PATH), "fastapi", "python")
        assert workflow["status"] == "ok"
        wf_id = workflow["workflow_id"]

        tool_calls = [
            server.analyze_project(str(PROJECT_PATH), out_path=str(graph_path)),
            server.impact_query(str(graph_path), symbol="repositories.OrderRepository.save", direction="upstream", max_depth=3, min_confidence=0.8),
            server.explain_edge(str(graph_path), "services.OrderService.create_order", "repositories.OrderRepository.save"),
            server.detect_languages(str(PROJECT_PATH)),
            server.project_inventory(str(PROJECT_PATH)),
            server.detect_unknown_libraries(str(PROJECT_PATH)),
            server.list_support_packs(str(ROOT / "support_packs")),
            server.validate_support_pack(str(FASTAPI_PACK)),
            server.install_support_pack(str(FASTAPI_PACK), registry_root=str(tmp_path / "installed_packs")),
            server.create_library_research_request("fastapi", version="unknown", package_manager="pip"),
            workflow,
            server.prepare_library_research_input(wf_id, allow_network=True),
            server.validate_library_research_candidate(wf_id, candidate),
            server.install_library_support_pack(wf_id, candidate),
        ]

        for payload in tool_calls:
            encoded = json.dumps(payload)
            decoded = json.loads(encoded)
            assert isinstance(decoded, dict)
            assert decoded.get("status") in {"ok", "imported", "already_exists", "installed", "error"}

        assert tool_calls[0]["status"] == "ok"
        assert tool_calls[1]["status"] == "ok"
        assert tool_calls[2]["status"] == "ok"
        assert tool_calls[7]["valid"] is True
        assert tool_calls[8]["status"] in {"imported", "already_exists"}
        assert tool_calls[11]["status"] == "ok"
        assert tool_calls[12]["valid"] is True
        assert tool_calls[13]["status"] == "installed"
    finally:
        os.chdir(old_cwd)
