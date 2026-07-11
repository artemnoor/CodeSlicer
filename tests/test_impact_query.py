import pytest
from pathlib import Path
from impact_engine.extractors.python_ast import extract_project
from impact_engine.resolution.precision import resolve_precision
from impact_engine.impact import impact_query
from impact_engine.models import GraphDocument

PROJECT_PATH = Path(__file__).parent.parent / "examples" / "golden_cases" / "python_di_basic"


@pytest.fixture
def resolved_graph():
    graph = extract_project(PROJECT_PATH)
    return resolve_precision(graph)


def test_impact_query_symbol_substring(resolved_graph):
    res = impact_query(
        resolved_graph,
        symbol="OrderRepository"
    )
    assert len(res["matched_nodes"]) >= 1
    # Check it matched class:repositories.OrderRepository
    matched_ids = [n["id"] for n in res["matched_nodes"]]
    assert any("repositories.OrderRepository" in mid for mid in matched_ids)


def test_impact_query_file_path(resolved_graph):
    res = impact_query(
        resolved_graph,
        file_path="repositories.py"
    )
    assert len(res["matched_nodes"]) >= 1


def test_impact_query_max_depth(resolved_graph):
    # Traverse from container class with depth limit 1
    res = impact_query(
        resolved_graph,
        target="class:container.Container",
        max_depth=1,
        direction="downstream"
    )
    # Check that depth is restricted and doesn't reach deep nodes
    for path in res["explanation_chain"]:
        assert path.count("->") <= 2  # one edge has at most 2 arrows (curr -> edge -> next)


def test_impact_query_min_confidence(resolved_graph):
    res_high = impact_query(
        resolved_graph,
        target="services.OrderService.create_order",
        min_confidence=0.90
    )
    # The CALLS edge is 0.85, so with 0.90 threshold it should NOT be traversed
    assert "repositories.OrderRepository.save" not in [n["id"] for n in res_high["affected_nodes"]]

    res_low = impact_query(
        resolved_graph,
        target="services.OrderService.create_order",
        min_confidence=0.80
    )
    # With 0.80 threshold, it should be traversed successfully
    assert any("repositories.OrderRepository.save" in n["id"] for n in res_low["affected_nodes"])


def test_impact_query_grouping(resolved_graph):
    res = impact_query(
        resolved_graph,
        target="services.OrderService.create_order"
    )
    grouped = res["grouped_by_kind"]
    assert "functions" in grouped
    assert "classes" in grouped


def test_impact_query_fastapi_upstream():
    import json
    from impact_engine.analysis.pipeline import analyze_project_core
    res = analyze_project_core(str(Path(__file__).parent / "fixtures" / "fastapi_realistic_project"))
    graph = GraphDocument.from_json(json.dumps(res["graph"]))
    
    impact_res = impact_query(
        graph,
        target="app.repositories.OrderRepository.save",
        direction="upstream"
    )
    affected_ids = [n["id"] for n in impact_res["affected_nodes"]]
    assert "app.services.OrderService.create_order" in affected_ids
    assert "app.main.create_order_endpoint" in affected_ids
    assert "HTTP POST /orders" in affected_ids

    semantic_groups = impact_res["grouped_by_semantic_role"]
    assert "routes" in semantic_groups
    assert "HTTP POST /orders" in semantic_groups["routes"]
