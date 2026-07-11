import pytest
import json
from pathlib import Path
from impact_engine.analysis.contracts import AnalysisOptions
from impact_engine.analysis.pipeline import AnalysisPipeline, analyze_project_core

PROJECT_PATH = Path(__file__).parent.parent / "examples" / "golden_cases" / "python_di_basic"
POLYGLOT_PATH = Path(__file__).parent / "fixtures" / "polyglot_basic_project"


def test_analyze_project_core_success(tmp_path):
    out_file = tmp_path / "graph_output.json"
    res = analyze_project_core(str(PROJECT_PATH), out_path=str(out_file))
    
    assert res["status"] == "ok"
    assert res["path"] == str(PROJECT_PATH.resolve())
    assert res["project_path"] == str(PROJECT_PATH.resolve())
    assert res["graph_path"] == str(out_file.resolve())
    assert res["nodes"] > 0
    assert res["edges"] > 0
    assert out_file.exists()
    
    # Assert extra keys are present
    assert "inventory" in res
    assert "languages" in res
    assert "extractors_used" in res
    assert "diagnostics" in res
    assert "items" in res["diagnostics"]
    assert "support_pack_load_errors" in res
    assert "graph" in res
    
    # Assert JSON serializable
    serialized = json.dumps(res)
    assert serialized is not None
    
    # Assert MVP edge exists in the output graph
    graph_dict = res["graph"]
    edges = graph_dict.get("edges", [])
    mvp_edge = next(
        (e for e in edges if e.get("kind") == "CALLS" and e.get("from") == "services.OrderService.create_order" and e.get("to") == "repositories.OrderRepository.save"),
        None
    )
    assert mvp_edge is not None
    assert mvp_edge["source"] == "INFERRED"
    assert mvp_edge["confidence"] >= 0.80
    assert len(mvp_edge.get("evidence", [])) >= 1

    hygiene = graph_dict["metadata"].get("project_hygiene")
    assert hygiene is not None
    assert graph_dict["metadata"].get("project_hygiene_status") == "applied"
    assert graph_dict["metadata"].get("pre_project_hygiene_status") == "applied"
    assert graph_dict["metadata"].get("post_project_hygiene_status") == "applied"
    assert graph_dict["metadata"]["pre_project_hygiene"]["stage"] == "pre"
    assert graph_dict["metadata"]["post_project_hygiene"]["stage"] == "post"
    assert graph_dict["metadata"]["support_pack_rule_engine"]["status"] == "active"
    assert hygiene["summary"]["files.total"] > 0
    assert hygiene["node_annotations"]


def test_analysis_pipeline_contract_matches_legacy_entrypoint(tmp_path):
    out_file = tmp_path / "graph_output.json"
    result = AnalysisPipeline(AnalysisOptions(project_path=str(PROJECT_PATH), out_path=str(out_file))).run()
    data = result.to_dict()

    assert data["status"] == "ok"
    assert data["path"] == str(PROJECT_PATH.resolve())
    assert data["graph_path"] == str(out_file.resolve())
    assert data["nodes"] > 0
    assert data["edges"] > 0
    assert isinstance(data["diagnostics"]["items"], list)
    assert data["diagnostics"]["normal_analyze_requires_internet"] is False


def test_analyze_polyglot_project_tree_sitter():
    res = analyze_project_core(str(POLYGLOT_PATH))
    assert res["status"] == "ok"
    assert "typescript" in res["languages"]
    
    graph_dict = res["graph"]
    edges = graph_dict.get("edges", [])
    
    # Verify tree-sitter edges are present with confidence 0.60
    ts_edges = [e for e in edges if e.get("properties", {}).get("extractor_id") == "tree_sitter" and e.get("kind") == "CALLS"]
    assert len(ts_edges) >= 2
    
    for e in ts_edges:
        assert e["confidence"] == 0.60
        assert e["source"] == "EXTRACTED"
        
    targets = {e["to"] for e in ts_edges}
    assert "helper" in targets
    assert "this.save" in targets


def test_pipeline_merges_optional_graphify_input(tmp_path):
    graphify_path = tmp_path / "graphify.json"
    graphify_path.write_text(json.dumps({
        "nodes": [
            {"id": "external:a", "kind": "FILE", "name": "external.py"},
            {"id": "external:b", "kind": "FUNCTION", "name": "external_fn"},
        ],
        "links": [{"source": "external:a", "target": "external:b", "relation": "contains", "confidence": "EXTRACTED"}],
    }), encoding="utf-8")
    result = analyze_project_core(str(PROJECT_PATH), graphify_path=str(graphify_path))
    assert result["status"] == "ok"
    assert "graphify_adapter" in result["extractors_used"]
    assert any(node["id"] == "external:a" for node in result["graph"]["nodes"])
    assert result["graph"]["metadata"].get("sources")
