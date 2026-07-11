from pathlib import Path
from impact_engine.analysis.pipeline import analyze_project_core
from impact_engine.extractors.tree_sitter.adapter import is_tree_sitter_available


def test_tree_sitter_polyglot_status_is_honest_and_network_free(monkeypatch):
    project = Path(__file__).parent / "fixtures" / "polyglot_basic_project"
    
    # Check honest status when tree-sitter is available
    if is_tree_sitter_available():
        res = analyze_project_core(str(project))
        assert res["status"] == "ok"
        assert "typescript" in res["languages"]
        assert "tree_sitter" in res["extractors_used"]
        assert res["graph"]["metadata"].get("tree_sitter_status") == "native"
        assert res["diagnostics"].get("tree_sitter_status") == "native"
        assert res["diagnostics"].get("normal_analyze_requires_internet") is False
        
    # Check fallback behavior when tree-sitter is mocked as unavailable
    import impact_engine.extractors.tree_sitter.adapter as adapter
    monkeypatch.setattr(adapter, "is_tree_sitter_available", lambda: False)
    
    res_fallback = analyze_project_core(str(project))
    assert res_fallback["status"] == "ok"
    assert "typescript" in res_fallback["languages"]
    assert "tree_sitter" in res_fallback["extractors_used"]
    assert res_fallback["graph"]["metadata"].get("tree_sitter_status") == "partial_local_fallback"
    assert res_fallback["diagnostics"].get("tree_sitter_status") == "partial_local_fallback"
    assert res_fallback["diagnostics"].get("normal_analyze_requires_internet") is False
