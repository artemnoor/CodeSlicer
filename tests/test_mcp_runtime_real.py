from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT_PATH = ROOT / "examples" / "golden_cases" / "python_di_basic"
FASTAPI_PACK = ROOT / "support_packs" / "python" / "fastapi" / "support_pack.json"


def test_all_mcp_tools_return_json_serializable_dicts_without_unexpected_network(tmp_path, monkeypatch):
    import requests
    import impact_engine.mcp.server as server
    from impact_engine.research.fetcher import FetchResult, WebFetcher

    def forbid_requests_get(*args, **kwargs):  # pragma: no cover - failure-only guard
        raise AssertionError("MCP non-research tools must not call requests.get")

    monkeypatch.setattr(requests, "get", forbid_requests_get)

    def fake_fetch(self: WebFetcher, url: str) -> FetchResult:
        return FetchResult(url=url, status_code=200, content_type="text/html", text_excerpt="fastapi docs excerpt")

    monkeypatch.setattr(WebFetcher, "fetch", fake_fetch)

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

    old_cwd = Path.cwd()
    try:
        os.chdir(tmp_path)
        graph_path = tmp_path / "graph.json"
        workflow = server.create_library_research_workflow(str(PROJECT_PATH), "fastapi", "python")
        wf_id = workflow["workflow_id"]

        calls = {
            "analyze_project": server.analyze_project(str(PROJECT_PATH), out_path=str(graph_path)),
            "impact_query": server.impact_query(str(graph_path), symbol="repositories.OrderRepository.save", direction="upstream", max_depth=3, min_confidence=0.8),
            "explain_edge": server.explain_edge(str(graph_path), "services.OrderService.create_order", "repositories.OrderRepository.save"),
            "detect_languages": server.detect_languages(str(PROJECT_PATH)),
            "project_inventory": server.project_inventory(str(PROJECT_PATH)),
            "detect_unknown_libraries": server.detect_unknown_libraries(str(PROJECT_PATH)),
            "list_support_packs": server.list_support_packs(str(ROOT / "support_packs")),
            "validate_support_pack": server.validate_support_pack(str(FASTAPI_PACK)),
            "install_support_pack": server.install_support_pack(str(FASTAPI_PACK), registry_root=str(tmp_path / "registry")),
            "create_library_research_request": server.create_library_research_request("fastapi", "unknown", "pip"),
            "create_library_research_workflow": workflow,
            "prepare_library_research_input": server.prepare_library_research_input(wf_id, allow_network=True),
            "validate_library_research_candidate": server.validate_library_research_candidate(wf_id, candidate),
            "install_library_support_pack": server.install_library_support_pack(wf_id, candidate),
        }
    finally:
        os.chdir(old_cwd)

    for name, payload in calls.items():
        assert isinstance(payload, dict), name
        json.dumps(payload)
        assert payload.get("tool") or name == "create_library_research_workflow"
        assert "status" in payload

    assert calls["analyze_project"]["status"] == "ok"
    assert calls["impact_query"]["status"] == "ok"
    assert calls["explain_edge"]["status"] == "ok"
    assert calls["validate_support_pack"]["valid"] is True
    assert calls["prepare_library_research_input"]["status"] == "ok"
    assert calls["validate_library_research_candidate"]["valid"] is True
    assert calls["install_library_support_pack"]["status"] == "installed"


def test_mcp_reports_errors_as_json_serializable_dicts(tmp_path):
    import impact_engine.mcp.server as server

    missing_graph = tmp_path / "missing.json"
    result = server.impact_query(str(missing_graph), symbol="x")
    assert result["status"] == "error"
    assert result["result"] is None
    json.dumps(result)
