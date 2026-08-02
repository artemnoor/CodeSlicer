import pytest
from pathlib import Path
from impact_engine.extractors.python_ast import extract_project
from impact_engine.resolution.engine import resolve_exact_import_calls, resolve_graph
from impact_engine.resolution.precision import resolve_precision

PROJECT_PATH = Path(__file__).parent.parent / "examples" / "golden_cases" / "python_di_basic"


def test_resolve_graph_creates_mvp_edge():
    graph = extract_project(PROJECT_PATH)
    resolved = resolve_graph(graph)
    
    mvp_edge = next(
        (e for e in resolved.edges if e.from_node == "services.OrderService.create_order"
         and e.to_node == "repositories.OrderRepository.save"
         and e.kind == "CALLS"),
        None
    )
    assert mvp_edge is not None
    assert mvp_edge.source == "INFERRED"
    assert mvp_edge.confidence >= 0.80


def test_resolve_precision_and_resolve_graph_are_equivalent():
    graph1 = extract_project(PROJECT_PATH)
    graph2 = extract_project(PROJECT_PATH)
    
    res1 = resolve_precision(graph1)
    res2 = resolve_graph(graph2)
    
    # Assert MVP edge is in both
    mvp1 = next((e for e in res1.edges if e.from_node == "services.OrderService.create_order" and e.to_node == "repositories.OrderRepository.save"), None)
    mvp2 = next((e for e in res2.edges if e.from_node == "services.OrderService.create_order" and e.to_node == "repositories.OrderRepository.save"), None)
    
    assert mvp1 is not None
    assert mvp2 is not None
    assert mvp1.id == mvp2.id
    assert mvp1.source == mvp2.source
    assert mvp1.confidence == mvp2.confidence


def test_resolve_graph_support_packs_param_does_not_break():
    graph = extract_project(PROJECT_PATH)
    # Pass empty list of support packs
    resolved = resolve_graph(graph, support_packs=[])
    
    mvp_edge = next((e for e in resolved.edges if e.from_node == "services.OrderService.create_order" and e.to_node == "repositories.OrderRepository.save"), None)
    assert mvp_edge is not None


def test_exact_import_call_pass_resolves_only_unambiguous_project_symbols(tmp_path: Path):
    (tmp_path / "providers.py").write_text(
        "def target(value: int) -> int:\n    return value\n",
        encoding="utf-8",
    )
    (tmp_path / "consumer.py").write_text(
        "from providers import target\n\ndef caller() -> int:\n    return target(1)\n",
        encoding="utf-8",
    )

    graph = extract_project(tmp_path)
    summary = resolve_exact_import_calls(graph)

    assert summary["status"] == "completed"
    assert summary["exact_calls_added"] == 1
    edge = next(
        edge for edge in graph.edges
        if edge.kind == "CALLS"
        and edge.from_node == "method:consumer.caller"
        and edge.to_node == "method:providers.target"
    )
    assert edge.confidence == 1.0
    assert edge.properties["resolution_status"] == "resolved_exact"
