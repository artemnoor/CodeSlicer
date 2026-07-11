from impact_engine.models import Edge, Evidence, GraphDocument, Node
from impact_engine.unknown_regions import (
    analyze_unknown_regions,
    apply_validated_hypotheses,
    build_research_requests,
    write_research_requests,
    select_research_regions,
)


def test_unresolved_calls_are_reported_without_inventing_edges():
    graph = GraphDocument(metadata={"path": "fixture"})
    graph.add_node(Node("call:one", "CALL_EXPR", "client.run", {"file": "a.py", "line": 4}))

    report = analyze_unknown_regions(graph)

    assert report["status"] == "gaps_found"
    assert report["regions"][0]["kind"] == "unresolved_call"
    assert graph.edges == []
    requests = build_research_requests(report, project_path="fixture")
    assert requests[0]["constraints"]["no_name_similarity_edges"] is True


def test_isolated_symbol_is_review_candidate_not_dead_code_claim():
    graph = GraphDocument()
    graph.add_node(Node("function:unused", "FUNCTION", "unused", {"file": "a.py", "line": 1}))

    report = analyze_unknown_regions(graph)

    region = report["regions"][0]
    assert region["kind"] == "isolated_symbol"
    assert "not proof of dead code" in " ".join(region["reasons"])


def test_ai_hypothesis_without_runtime_is_not_added():
    graph = GraphDocument()
    graph.add_node(Node("a", "FUNCTION", "a"))
    graph.add_node(Node("b", "FUNCTION", "b"))
    result = apply_validated_hypotheses(
        graph,
        [{"id": "proposal-1", "from": "a", "to": "b", "kind": "CALLS", "confidence": 0.99}],
    )

    assert result["promoted"] == []
    assert result["rejected"][0]["reason"] == "no independent runtime evidence"
    assert graph.edges == []


def test_exact_runtime_match_promotes_hypothesis_with_provenance():
    graph = GraphDocument()
    graph.add_node(Node("a", "FUNCTION", "a"))
    graph.add_node(Node("b", "FUNCTION", "b"))
    result = apply_validated_hypotheses(
        graph,
        [{"id": "proposal-1", "from": "a", "to": "b", "kind": "CALLS", "confidence": 0.91}],
        {"matched_edges": [{"edge_id": "proposal-1"}]},
    )

    assert len(result["promoted"]) == 1
    assert graph.edges[0].source == "RUNTIME_CONFIRMED"
    assert graph.edges[0].properties["validated_hypothesis"] is True
    assert graph.edges[0].properties["status"] == "confirmed"


def test_runtime_match_cannot_create_missing_graph_endpoints():
    graph = GraphDocument()
    graph.add_node(Node("a", "FUNCTION", "a"))
    result = apply_validated_hypotheses(
        graph,
        [{"id": "proposal-1", "from": "a", "to": "missing", "kind": "CALLS"}],
        {"matched_edges": [{"edge_id": "proposal-1"}]},
    )

    assert result["promoted"] == []
    assert result["rejected"][0]["reason"] == "hypothesis endpoint is not present in graph"
    assert graph.edges == []


def test_suspicious_edges_are_separate_from_unresolved_regions():
    graph = GraphDocument()
    graph.add_node(Node("a", "FUNCTION", "a"))
    graph.add_node(Node("b", "FUNCTION", "b"))
    graph.add_edge(Edge(
        "e", "CALLS", "a", "b", source="AI_PROPOSED", confidence=0.5,
        evidence=[Evidence("name similarity")], properties={"status": "suspicious", "warnings": ["name similarity"]},
    ))
    report = analyze_unknown_regions(graph)
    assert report["counts"]["suspicious"] == 1


def test_research_tasks_are_machine_readable(tmp_path):
    path = write_research_requests([{"request_id": "ur-1", "status": "unresolved"}], tmp_path / "tasks.json")
    payload = __import__("json").loads((tmp_path / "tasks.json").read_text(encoding="utf-8"))
    assert path.endswith("tasks.json")
    assert payload["protocol"] == "impact-engine.unknown-region-research"
    assert payload["requests"][0]["request_id"] == "ur-1"


def test_vendor_and_generated_directories_are_excluded_from_python_extraction(tmp_path):
    from impact_engine.extractors.python_ast import extract_project

    (tmp_path / "app.py").write_text("def app():\n    return 1\n", encoding="utf-8")
    (tmp_path / "external_tools").mkdir()
    (tmp_path / "external_tools" / "vendor.py").write_text("def vendor():\n    return 2\n", encoding="utf-8")
    (tmp_path / ".impact_engine").mkdir()
    (tmp_path / ".impact_engine" / "generated.py").write_text("def generated():\n    return 3\n", encoding="utf-8")

    graph = extract_project(tmp_path)
    files = {node.properties.get("path") for node in graph.nodes if node.kind == "FILE"}
    assert files == {"app.py"}


def test_research_queue_excludes_unlocated_noise_and_deduplicates():
    regions = [
        {"region_id": "noise", "kind": "unresolved_call", "status": "unresolved", "evidence": [], "details": {"call_name": "print"}},
        {"region_id": "one", "kind": "unresolved_call", "status": "unresolved", "evidence": [{"file": "a.py", "line": 4}], "details": {"call_name": "self.repo.save", "receiver": "self.repo"}},
        {"region_id": "duplicate", "kind": "unresolved_call", "status": "unresolved", "evidence": [{"file": "a.py", "line": 4}], "details": {"call_name": "self.repo.save", "receiver": "self.repo"}},
        {"region_id": "suspicious", "kind": "suspicious_edge", "status": "suspicious", "evidence": [{"file": "b.py", "line": 2}], "details": {}},
    ]
    selected, meta = select_research_regions(regions)
    assert {item["kind"] for item in selected} == {"unresolved_call", "suspicious_edge"}
    assert len(selected) == 2
    assert meta["excluded"]["no_evidence"] == 1
    assert meta["excluded"]["duplicate"] == 1
