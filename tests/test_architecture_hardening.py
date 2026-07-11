from impact_engine.graph_quality import annotate_edge_contracts, run_quality_gate
from impact_engine.impact import impact_path
from impact_engine.models import Edge, FactDocument, GraphDocument, Node
from impact_engine.runtime_trace import apply_runtime_trace_boost
from impact_engine.graph_identity import annotate_stable_identities


def _graph():
    graph = GraphDocument()
    for node_id in ("a", "b", "c"):
        graph.add_node(Node(node_id, "FUNCTION", node_id))
    graph.add_edge(Edge("ab", "CALLS", "a", "b", source="EXTRACTED", confidence=1.0))
    graph.add_edge(Edge("bc", "CALLS", "b", "c", source="INFERRED", confidence=0.85))
    return graph


def test_edge_contracts_are_independent_and_observations_are_retained():
    graph = _graph()
    annotate_edge_contracts(graph)
    inferred = next(edge for edge in graph.edges if edge.id == "bc")
    assert inferred.properties["resolution_status"] == "resolved"
    assert inferred.properties["evidence_class"] == "static_inferred"
    assert inferred.properties["validation_status"] == "not_validated"
    assert inferred.properties["observations"]


def test_impact_path_uses_weakest_link_status():
    result = impact_path(_graph(), "a", "c")
    assert result["found"] is True
    assert result["confidence"] == 0.85
    assert result["path_status"] == "likely"


def test_unmatched_runtime_calls_are_quarantined_not_discarded():
    graph = _graph()
    patched = apply_runtime_trace_boost(graph, {
        "status": "ok",
        "matched_edges": [],
        "unmatched_calls": [{"caller": "a", "callee": "missing", "test_id": "test_one"}],
        "tests": [{"id": "test_one", "file": "tests/test_one.py"}],
    })
    assert patched.metadata["runtime_only_observations"][0]["status"] == "quarantined"
    assert len(patched.edges) == 2


def test_stable_identity_contains_structured_polyglot_fields():
    graph = GraphDocument()
    graph.add_node(Node("method:OrderService.save", "METHOD", "save", {
        "file": "orders/service.py", "scope": "orders.OrderService.save", "line": 4,
    }))
    annotate_stable_identities(graph, "/workspace/orders")
    identity = graph.nodes[0].properties["canonical_identity"]
    assert identity["language"] == "python"
    assert identity["workspace"] == "orders"
    assert identity["qualname"] == "orders.OrderService.save"


def test_quality_gate_reports_missing_inferred_evidence():
    graph = GraphDocument()
    graph.add_node(Node("a", "FUNCTION", "a"))
    graph.add_node(Node("b", "FUNCTION", "b"))
    graph.add_edge(Edge("ab", "CALLS", "a", "b", source="INFERRED", confidence=0.8))
    result = run_quality_gate(graph, "resolver")
    assert result["status"] == "warning"
    assert result["missing_evidence"] == 1


def test_fact_document_is_full_serializable_model():
    fact = FactDocument(callsites=[{"caller": "a", "receiver": "self.repo", "member": "save"}])
    restored = FactDocument.from_dict(__import__("json").loads(fact.to_json()))
    assert restored.callsites[0]["receiver"] == "self.repo"
    assert restored.to_dict()["schema"] == "impact-engine.fact-document.v1"
