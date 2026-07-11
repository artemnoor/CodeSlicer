import pytest
from pathlib import Path
from impact_engine.extractors.python_ast import extract_project
from impact_engine.resolution.precision import resolve_precision
from impact_engine.impact import explain_edge

PROJECT_PATH = Path(__file__).parent.parent / "examples" / "golden_cases" / "python_di_basic"


@pytest.fixture
def resolved_graph():
    graph = extract_project(PROJECT_PATH)
    return resolve_precision(graph)


def test_explain_edge_reasoning_and_warnings(resolved_graph):
    res = explain_edge(
        resolved_graph,
        from_symbol="services.OrderService.create_order",
        to_symbol="repositories.OrderRepository.save",
        kind="CALLS"
    )
    assert res["found"] is True
    assert len(res["reasoning_steps"]) >= 1
    assert "evidence_chain" in res
    assert res["evidence"] == res["evidence_chain"]
    assert isinstance(res["support_pack_rules_used"], list)
    assert isinstance(res["warnings"], list)


def test_explain_edge_not_found(resolved_graph):
    res = explain_edge(
        resolved_graph,
        from_symbol="nonexistent_src",
        to_symbol="nonexistent_dst"
    )
    assert res["found"] is False
    assert len(res["reasoning_steps"]) >= 1
    assert res["edge"] is None
