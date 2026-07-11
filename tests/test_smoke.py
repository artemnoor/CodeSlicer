from pathlib import Path


def test_smoke_imports():
    import impact_engine
    from impact_engine.models import GraphDocument
    assert GraphDocument() is not None


def test_core_boundaries_and_mcp_real_behavior(tmp_path):
    from impact_engine.extractors.python_ast import extract_project
    from impact_engine.resolution.precision import resolve_precision
    from impact_engine.models import GraphDocument
    from impact_engine.mcp.server import analyze_project, impact_query

    project = Path(__file__).parent.parent / "examples" / "golden_cases" / "python_di_basic"
    graph_path = tmp_path / "smoke_graph.json"

    doc = extract_project(str(project))
    assert isinstance(doc, GraphDocument)
    assert doc.metadata.get("extractor") == "python_ast"

    doc_resolved = resolve_precision(doc)
    assert isinstance(doc_resolved, GraphDocument)
    assert doc_resolved.metadata.get("precision_resolver") in ("skeleton", "active")

    res = analyze_project(str(project), out_path=str(graph_path))
    assert res["status"] == "ok"
    assert graph_path.exists()

    res_query = impact_query(
        str(graph_path),
        target="services.OrderService.create_order",
        direction="downstream",
        max_depth=2,
        min_confidence=0.8,
    )
    assert res_query["status"] == "ok"
    affected = {n["id"] for n in res_query["result"].get("affected_nodes", [])}
    assert "repositories.OrderRepository.save" in affected


def test_mcp_impact_query_missing_graph_is_json_error():
    from impact_engine.mcp.server import impact_query

    res = impact_query("missing_graph.json", target="target")
    assert res["tool"] == "impact_query"
    assert res["status"] == "error"
    assert "missing_graph.json" in res["graph_path"]
    assert res["result"] is None
    assert "error" in res
