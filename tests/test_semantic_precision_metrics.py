import json

from impact_engine.models import Edge, FactDocument, GraphDocument, Node
from impact_engine.resolution_coverage import build_resolution_coverage
from impact_engine.unknown_regions import build_pr_scoped_research_requests, select_research_regions


def test_coverage_contains_rates_and_actionable_breakdown():
    graph = GraphDocument()
    graph.add_node(Node("call:1", "CALL_EXPR", "repo.save", {"file": "orders.py", "call_name": "repo.save", "receiver": "repo"}))
    graph.add_node(Node("call:2", "CALL_EXPR", "json.dumps", {"file": "orders.py", "call_name": "json.dumps"}))
    graph.add_edge(Edge("e", "CALLS", "call:1", "OrderRepository.save", source="INFERRED", confidence=0.85))
    report = build_resolution_coverage(graph)
    assert report["totals"]["callsites_total"] == 2
    assert "resolution_rate" in report["by_language"]["python"]
    assert report["totals"]["external_terminal"] == 1


def test_pr_queue_is_smaller_than_project_queue():
    report = {"regions": [
        {"region_id": "a", "kind": "unresolved_call", "evidence": [{"file": "changed.py", "line": 1}], "details": {"receiver": "self.repo", "fingerprint": "p1"}},
        {"region_id": "b", "kind": "unresolved_call", "evidence": [{"file": "other.py", "line": 2}], "details": {"receiver": "self.repo", "fingerprint": "p2"}},
    ]}
    requests = build_pr_scoped_research_requests(report, changed_files=["changed.py"], max_requests=50)
    assert len(requests) == 1
    assert requests[0]["scope"] == "pr"


def test_fact_document_serialization_is_order_independent():
    first = FactDocument(callsites=[{"id": "b"}, {"id": "a"}]).to_json()
    second = FactDocument(callsites=[{"id": "a"}, {"id": "b"}]).to_json()
    assert first == second
