import pytest
from pathlib import Path
import json
from impact_engine.analysis.pipeline import analyze_project_core
from impact_engine.models import GraphDocument

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_analyze_polyglot_project_success(tmp_path):
    polyglot_project = FIXTURES_DIR / "polyglot_basic_project"
    out_file = tmp_path / "polyglot_graph.json"
    
    res = analyze_project_core(str(polyglot_project), out_path=str(out_file))
    
    assert res["status"] == "ok"
    assert res["nodes"] > 0
    assert res["edges"] > 0
    assert out_file.exists()
    
    # Assert JSON serializable and valid
    content = out_file.read_text(encoding="utf-8")
    graph_data = json.loads(content)
    
    # Confirm Python module run and TS module index exist
    nodes = {n["id"] for n in graph_data.get("nodes", [])}
    assert any("main" in n for n in nodes)
    assert any("index" in n for n in nodes)
    
    # Assert MVP edge test doesn't fail
    mvp_project = Path(__file__).parent.parent / "examples" / "golden_cases" / "python_di_basic"
    mvp_out = tmp_path / "mvp_graph.json"
    mvp_res = analyze_project_core(str(mvp_project), out_path=str(mvp_out))
    
    assert mvp_res["status"] == "ok"
    mvp_content = mvp_out.read_text(encoding="utf-8")
    mvp_data = json.loads(mvp_content)
    
    # Check that services.OrderService.create_order -> repositories.OrderRepository.save is still there
    edges = mvp_data.get("edges", [])
    mvp_edge = next(
        (e for e in edges if e.get("kind") == "CALLS" and e.get("from") == "services.OrderService.create_order" and e.get("to") == "repositories.OrderRepository.save"),
        None
    )
    assert mvp_edge is not None
    assert mvp_edge["source"] == "INFERRED"
    assert mvp_edge["confidence"] >= 0.80
