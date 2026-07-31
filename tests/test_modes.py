from __future__ import annotations

import json
import threading
from pathlib import Path
from urllib.request import Request, urlopen

import pytest

from impact_engine.contracts import CI_POLICY_SCHEMA_VERSION, MODE_CONTRACT_VERSION, MODE_SCHEMA_VERSION
from impact_engine.analysis.pipeline import analyze_project_core
from impact_engine.models import Edge, Evidence, GraphDocument, Node
from impact_engine.modes import (
    build_ci_report,
    build_inspect_report,
    build_investigate_report,
    to_sarif,
)


def _graph() -> GraphDocument:
    graph = GraphDocument(metadata={"graph_fingerprint": "fixture-mode-fp"})
    graph.add_node(Node("repo", "METHOD", "save", {"file": "src/repo.py", "line": 4}))
    graph.add_node(Node("service", "METHOD", "create", {"file": "src/service.py", "line": 8}))
    graph.add_node(Node("route", "ROUTE", "POST /orders", {"file": "src/routes.py", "line": 12, "boundary_category": "api"}))
    graph.add_node(Node("test", "TEST", "test_create", {"file": "tests/test_orders.py", "line": 3, "test_command": "pytest tests/test_orders.py"}))
    graph.add_node(Node("assignment", "ASSIGNMENT", "tmp", {"file": "src/service.py", "line": 9}))
    graph.add_node(Node("generated", "FUNCTION", "generated", {"file": "src/generated/client.py", "line": 2}))
    evidence = Evidence("static relation", "src/service.py", 8, "EXTRACTED")
    graph.add_edge(Edge("call", "CALLS", "service", "repo", confidence=.95, evidence=[evidence]))
    graph.add_edge(Edge("route", "ROUTE_HANDLES", "route", "service", confidence=.96, evidence=[Evidence("route delegates", "src/routes.py", 12, "SUPPORT_PACK")]))
    graph.add_edge(Edge("test", "TESTS", "test", "service", confidence=.95, evidence=[Evidence("test covers", "tests/test_orders.py", 3, "EXTRACTED")]))
    graph.add_edge(Edge("noise", "ASSIGNS", "service", "assignment", confidence=1.0))
    graph.add_edge(Edge("generated", "CALLS", "service", "generated", confidence=.9, evidence=[Evidence("generated", "src/generated/client.py", 2, "EXTRACTED")]))
    return graph


def _graph_path(tmp_path: Path) -> Path:
    path = tmp_path / "graph.json"
    path.write_text(_graph().to_json(), encoding="utf-8")
    return path


def _assert_contract(payload: dict, mode: str) -> None:
    assert payload["schema_version"] == ("ReviewReport/v1" if mode == "review" else MODE_SCHEMA_VERSION)
    assert payload["mode"] == mode
    assert payload["contract_version"] == MODE_CONTRACT_VERSION
    assert payload["local_only"] is True
    assert "graph_freshness" in payload
    assert "coverage" in payload
    assert "warnings" in payload
    assert isinstance(payload["actions"]["items"], list)
    for item in payload["actions"]["items"]:
        assert {"id", "kind", "title", "enabled", "requires_explicit_user_action", "payload"} <= set(item)


def test_inspect_exact_entity_and_compact_context(tmp_path: Path):
    report = build_inspect_report(str(tmp_path), entity="save", graph_path=_graph_path(tmp_path))
    _assert_contract(report, "inspect")
    assert report["resolved_entity"]["id"] == "repo"
    assert report["why_affected"]
    assert report["linked_routes"] == []
    assert all(item["edge"]["to"] != "assignment" for item in report["why_affected"])


def test_inspect_alias_resolves_to_canonical_method(tmp_path: Path):
    graph = GraphDocument()
    graph.add_node(Node("method:core.merge.merge_profile", "METHOD", "merge_profile", {"file": "core/merge.py", "line": 12, "scope": "core.merge.merge_profile"}))
    graph.add_node(Node("core.merge.merge_profile", "EXTERNAL_LIBRARY", "merge_profile", {"external_tool": "legacy-alias"}))
    graph.add_node(Node("method:tests.test_merge.test_merge_profile", "METHOD", "test_merge_profile", {"file": "tests/test_merge.py", "line": 4}))
    graph.add_edge(Edge("test-merge-profile", "TESTS", "method:tests.test_merge.test_merge_profile", "method:core.merge.merge_profile", confidence=.95))
    path = tmp_path / "graph.json"
    path.write_text(graph.to_json(), encoding="utf-8")

    report = build_inspect_report(str(tmp_path), entity="core.merge.merge_profile", graph_path=path)

    assert report["resolved_entity"]["id"] == "method:core.merge.merge_profile"
    assert report["resolved_entity"]["kind"] == "METHOD"
    assert report["resolved_entity"]["properties"]["file"] == "core/merge.py"


def test_inspect_links_test_methods_by_confirmed_call_and_canonical_alias(tmp_path: Path):
    graph = GraphDocument()
    target = Node("method:app.service.save", "METHOD", "save", {"file": "app/service.py", "scope": "app.service.save"})
    target_alias = Node("app.service.save", "EXTERNAL_LIBRARY", "save", {"canonical_identity": {"qualname": "app.service.save"}})
    test = Node("method:tests.test_service.test_save", "METHOD", "test_save", {"file": "tests/test_service.py", "scope": "tests.test_service.test_save"})
    test_alias = Node("tests.test_service.test_save", "EXTERNAL_LIBRARY", "test_save", {"canonical_identity": {"qualname": "tests.test_service.test_save"}})
    for node in (target, target_alias, test, test_alias):
        graph.add_node(node)
    graph.add_edge(Edge("verified-test-call", "CALLS", test_alias.id, target_alias.id, source="EXTRACTED", confidence=.95, evidence=[Evidence("exact call", "tests/test_service.py", 5, "EXTRACTED")]))
    path = tmp_path / "graph.json"
    path.write_text(graph.to_json(), encoding="utf-8")

    report = build_inspect_report(str(tmp_path), entity=target.id, graph_path=path)

    assert [item["node"]["id"] for item in report["linked_tests"]] == [test.id]


def test_inspect_materializes_canonical_downstream_calls(tmp_path: Path):
    project = Path(__file__).parent / "fixtures" / "realistic_impact_project"
    graph_path = tmp_path / "graph.json"
    analyze_project_core(str(project), out_path=str(graph_path))

    report = build_inspect_report(
        str(project),
        entity="method:services.order_service.OrderService.place_order",
        graph_path=graph_path,
        refresh="never",
    )

    downstream = {edge["to"] for edge in report["direct_downstream"]}
    assert "method:repositories.order_repository.OrderRepository.save" in downstream
    assert "method:adapters.email_adapter.EmailAdapter.send_email" in downstream
    assert all("EXTERNAL_LIBRARY" not in edge["to"] for edge in report["direct_downstream"])


def test_inspect_ambiguous_symbol_requires_selection(tmp_path: Path):
    graph = _graph()
    graph.add_node(Node("other", "METHOD", "save", {"file": "src/other.py", "line": 2}))
    path = tmp_path / "graph.json"
    path.write_text(graph.to_json(), encoding="utf-8")
    report = build_inspect_report(str(tmp_path), entity="save", graph_path=path)
    assert report["status"] == "needs_selection"
    assert {item["id"] for item in report["candidates"]} == {"repo", "other"}


def test_investigate_is_bounded_and_exposes_truncation(tmp_path: Path):
    report = build_investigate_report(str(tmp_path), entity="repo", graph_path=_graph_path(tmp_path), depth=8, max_nodes=2, max_edges=1)
    _assert_contract(report, "investigate")
    assert report["max_depth"] == 8
    assert report["truncated"] is True
    assert report["visited_nodes"] <= 2
    assert report["visited_edges"] <= 1
    assert report["graph_integrity"]["fingerprint"]


def test_runtime_validation_is_explicit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    called = []

    def fake_runtime(*args, **kwargs):
        called.append(True)
        return {"status": "ok", "matched_edges": []}

    monkeypatch.setattr("impact_engine.runtime_trace.run_runtime_trace_boost", fake_runtime)
    path = _graph_path(tmp_path)
    without_flag = build_investigate_report(str(tmp_path), entity="repo", graph_path=path)
    assert called == []
    assert without_flag["runtime_validation"]["status"] == "not_requested"
    with_flag = build_investigate_report(str(tmp_path), entity="repo", graph_path=path, runtime_validate=True)
    assert called == [True]
    assert with_flag["runtime_validation"]["status"] == "ok"


def test_ci_json_sarif_policy_and_exit_semantics(tmp_path: Path):
    graph_path = _graph_path(tmp_path)
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps({"schema_version": CI_POLICY_SCHEMA_VERSION, "fail_on_stale_graph": True}), encoding="utf-8")
    report = build_ci_report(str(tmp_path), graph_path=graph_path, policy_path=policy_path, refresh="never")
    _assert_contract(report, "ci")
    assert report["status"] == "failed"
    assert report["exit_code"] == 1
    assert any(item["rule"] == "fail_on_stale_graph" for item in report["policy_evaluation"]["violations"])
    sarif = to_sarif(report)
    assert sarif["version"] == "2.1.0"
    assert sarif["runs"][0]["tool"]["driver"]["name"] == "CodeSlicer"


def test_ci_default_is_advisory_and_does_not_run_tests(tmp_path: Path):
    report = build_ci_report(str(tmp_path), graph_path=_graph_path(tmp_path), refresh="never")
    assert report["exit_code"] == 0
    assert report["test_execution"]["status"] == "not_requested"
    assert report["review"]["local_only"] is True


def test_mcp_and_local_api_use_the_same_mode_builders(tmp_path: Path):
    graph_path = _graph_path(tmp_path)
    from impact_engine.mcp.server import TOOLS, inspect as mcp_inspect
    from impact_engine.local_api import LocalApiState, create_server

    assert {"inspect", "investigate", "ci"} <= {item["name"] for item in TOOLS}
    mcp_result = mcp_inspect(str(tmp_path), "repo", graph_path=str(graph_path))
    assert mcp_result["status"] == "ok"
    assert mcp_result["result"]["mode"] == "inspect"

    state = LocalApiState(str(tmp_path), "support_packs")
    server = create_server("127.0.0.1", 0, str(tmp_path), state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/inspect",
            data=json.dumps({"project_path": str(tmp_path), "entity": "repo", "graph_path": str(graph_path)}).encode(),
            method="POST",
            headers={"Content-Type": "application/json", "X-CodeSlicer-Session": server.session_token},
        )
        with urlopen(request, timeout=5) as response:
            payload = json.loads(response.read())
        assert payload["status"] == "ok"
        assert payload["report"]["mode"] == mcp_result["result"]["mode"]
        assert payload["report"]["contract_version"] == mcp_result["result"]["contract_version"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_ci_cli_invalid_and_analysis_exit_codes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from impact_engine.cli import main

    with pytest.raises(SystemExit) as invalid:
        main(["ci", str(tmp_path), "--policy", str(tmp_path / "missing.json"), "--json"])
    assert invalid.value.code == 2

    def broken(*args, **kwargs):
        raise RuntimeError("fixture analysis failure")

    monkeypatch.setattr("impact_engine.modes.build_ci_report", broken)
    with pytest.raises(SystemExit) as failed:
        main(["ci", str(tmp_path), "--json"])
    assert failed.value.code == 3
