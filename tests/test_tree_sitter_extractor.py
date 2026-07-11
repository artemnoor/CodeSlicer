import pytest
import json
from pathlib import Path
from impact_engine.extractors.tree_sitter.adapter import (
    is_tree_sitter_available,
    get_supported_tree_sitter_languages,
    extract_tree_sitter_project
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_tree_sitter_availability():
    assert is_tree_sitter_available() is True
    langs = get_supported_tree_sitter_languages()
    assert "javascript" in langs
    assert "typescript" in langs
    assert "go" in langs
    assert "java" in langs


def test_extract_ts_project():
    ts_project = FIXTURES_DIR / "ts_basic_project"
    graph = extract_tree_sitter_project(ts_project, languages=["typescript"])
    
    # 1. Assert nodes
    nodes = {n.id: n for n in graph.nodes}
    assert "file:src/index.ts" in nodes
    assert "module:src/index" in nodes
    assert "OrderService" in nodes
    assert "OrderService.createOrder" in nodes
    assert "OrderService.saveOrder" in nodes
    
    # 2. Assert IMPORTS edge
    imports_edge = next((e for e in graph.edges if e.kind == "IMPORTS"), None)
    assert imports_edge is not None
    assert imports_edge.from_node == "module:src/index"
    assert imports_edge.to_node == "module:external_lib"
    
    # 3. Assert CALLS edge
    calls_edges = [e for e in graph.edges if e.kind == "CALLS"]
    assert len(calls_edges) > 0
    # Should have order_service.createOrder calling helper and self.saveOrder
    create_order_calls = [e for e in calls_edges if e.from_node == "OrderService.createOrder"]
    assert len(create_order_calls) >= 2
    
    targets = {e.to_node for e in create_order_calls}
    assert "this.saveOrder" in targets
    assert not any(".." in t for t in targets)
    
    # Assert evidence
    sample_edge = create_order_calls[0]
    assert sample_edge.confidence == 0.60
    assert len(sample_edge.evidence) > 0
    assert sample_edge.evidence[0].file == "src/index.ts"
    assert sample_edge.evidence[0].line is not None
    assert sample_edge.properties.get("extractor_id") == "tree_sitter"
    
    # Assert serialization with tree_sitter_errors metadata does not fail
    graph.metadata["tree_sitter_errors"] = ["Mock diagnostic error"]
    assert json.loads(graph.to_json()) is not None


def test_extract_go_project():
    go_project = FIXTURES_DIR / "go_basic_project"
    graph = extract_tree_sitter_project(go_project, languages=["go"])
    
    nodes = {n.id: n for n in graph.nodes}
    assert "module:main" in nodes
    assert "main.Service.Process" in nodes
    assert "main.Service.Save" in nodes
    
    # Assert IMPORTS
    imports_edge = next((e for e in graph.edges if e.kind == "IMPORTS"), None)
    assert imports_edge is not None
    assert imports_edge.from_node == "module:main"
    assert "github.com/some/lib" in imports_edge.to_node
    
    # Assert CALLS
    calls_edges = [e for e in graph.edges if e.kind == "CALLS" and e.from_node == "main.Service.Process"]
    assert len(calls_edges) > 0
    targets = {e.to_node for e in calls_edges}
    assert "lib.Call" in targets
    assert "s.Save" in targets
    assert not any(".." in t for t in targets)


def test_extract_java_project():
    java_project = FIXTURES_DIR / "java_basic_project"
    graph = extract_tree_sitter_project(java_project, languages=["java"])
    
    nodes = {n.id: n for n in graph.nodes}
    assert "com.example.OrderService" in nodes
    assert "com.example.OrderService.createOrder" in nodes
    
    # Assert IMPORTS
    imports_edge = next((e for e in graph.edges if e.kind == "IMPORTS"), None)
    assert imports_edge is not None
    assert imports_edge.from_node == "module:App"
    assert "com.other.Helper" in imports_edge.to_node
    
    # Assert CALLS
    calls_edges = [e for e in graph.edges if e.kind == "CALLS"]
    assert len(calls_edges) > 0


def test_tree_sitter_repos_are_cloned():
    base_path = Path(__file__).parent.parent / "external_tools" / "tree-sitter"
    repos = [
        "tree-sitter-javascript",
        "tree-sitter-typescript",
        "tree-sitter-go",
        "tree-sitter-java"
    ]
    for r in repos:
        repo_path = base_path / r
        assert repo_path.exists(), f"Path {repo_path} does not exist"
        assert (repo_path / ".git").exists() or (repo_path / "SOURCE_REPOSITORY.txt").exists(), (
            f"Source provenance marker in {repo_path} does not exist"
        )
        assert any(repo_path.glob("README*")) or any(repo_path.glob("readme*")), f"README in {repo_path} not found"
        # package metadata / grammar metadata check
        assert (repo_path / "package.json").exists() or (repo_path / "grammar.js").exists() or any(repo_path.rglob("package.json")) or any(repo_path.rglob("grammar.js")), f"Metadata in {repo_path} not found"


def test_tree_sitter_runtime_availability_is_reported_truthfully():
    # If HAS_TREE_SITTER is False, is_tree_sitter_available() must be False.
    # If it is True, it must return True because we checked that the packages are importable and functional.
    from impact_engine.extractors.tree_sitter.adapter import HAS_TREE_SITTER
    if not HAS_TREE_SITTER:
        assert is_tree_sitter_available() is False
    else:
        # Since it is True, let's verify it actually behaves correctly
        assert is_tree_sitter_available() is True


def test_native_or_fallback_status_is_explicit(monkeypatch):
    polyglot_project = FIXTURES_DIR / "polyglot_real"
    
    # 1. Test with tree-sitter enabled/available (real path)
    if is_tree_sitter_available():
        graph = extract_tree_sitter_project(polyglot_project)
        assert graph.metadata.get("tree_sitter_status") == "native"
        diagnostics = graph.metadata.get("tree_sitter_diagnostics", [])
        assert len(diagnostics) > 0
        for d in diagnostics:
            assert d["status"] == "native"
            assert d["parser_runtime"] == "tree-sitter-language-pack"
            assert d["extractor_id"] == "tree_sitter"
    
    # 2. Test with tree-sitter forced to fallback (unavailable path)
    import impact_engine.extractors.tree_sitter.adapter as adapter
    monkeypatch.setattr(adapter, "is_tree_sitter_available", lambda: False)
    
    graph_fallback = extract_tree_sitter_project(polyglot_project)
    assert graph_fallback.metadata.get("tree_sitter_status") == "partial_local_fallback"
    diagnostics_fallback = graph_fallback.metadata.get("tree_sitter_diagnostics", [])
    assert len(diagnostics_fallback) > 0
    for d in diagnostics_fallback:
        assert d["status"] == "fallback"
        assert d["parser_runtime"] == "fallback_regex"
        assert d["extractor_id"] == "tree_sitter_fallback"


def test_polyglot_graph_contains_files_modules_methods_calls():
    polyglot_project = FIXTURES_DIR / "polyglot_real"
    graph = extract_tree_sitter_project(polyglot_project)
    
    nodes = {n.id: n for n in graph.nodes}
    
    # JS checks
    assert "file:js_module.js" in nodes
    assert "Calculator" in nodes
    assert "Calculator.add" in nodes or "js_module.Calculator.add" in nodes
    
    # TS checks
    assert "file:ts_module.ts" in nodes
    assert "OrderProcessor" in nodes
    assert "OrderProcessor.processOrder" in nodes or "ts_module.OrderProcessor.processOrder" in nodes
    
    # Go checks
    assert "file:go_module.go" in nodes
    
    # Java checks
    assert "file:java_class.java" in nodes
    assert "com.example.processor.JavaProcessor" in nodes or "JavaProcessor" in nodes


def test_fallback_edges_are_low_confidence_and_marked(monkeypatch):
    polyglot_project = FIXTURES_DIR / "polyglot_real"
    import impact_engine.extractors.tree_sitter.adapter as adapter
    monkeypatch.setattr(adapter, "is_tree_sitter_available", lambda: False)
    
    graph = extract_tree_sitter_project(polyglot_project)
    assert len(graph.edges) > 0
    for edge in graph.edges:
        assert edge.properties.get("extractor_id") == "tree_sitter_fallback"
        assert edge.confidence <= 0.60


def test_no_docs_claim_production_polyglot_when_status_is_fallback():
    # Read the markdown files and assert they don't claim production-level polyglot support when status is fallback
    readme_path = Path(__file__).parent.parent / "README.md"
    readme_content = readme_path.read_text(encoding="utf-8")
    assert "experimental" in readme_content.lower() or "partial" in readme_content.lower() or "fallback" in readme_content.lower()
    
    acceptance_path = Path(__file__).parent.parent / "docs" / "ACCEPTANCE_REPORT.md"
    acceptance_content = acceptance_path.read_text(encoding="utf-8")
    assert "partial" in acceptance_content.lower() or "fallback" in acceptance_content.lower()


def test_language_pack_creates_parsers_and_native_path_invoked():
    # Proof that tree-sitter-language-pack actually creates language parsers for all 4 languages
    import tree_sitter
    import tree_sitter_language_pack
    
    for lang_name in ["javascript", "typescript", "go", "java"]:
        lang = tree_sitter_language_pack.get_language(lang_name)
        assert lang is not None
        parser = tree_sitter.Parser(lang)
        assert parser is not None
        
    # Check that native path is actually invoked for at least one file of each language if runtime is available
    if is_tree_sitter_available():
        polyglot_project = FIXTURES_DIR / "polyglot_real"
        graph = extract_tree_sitter_project(polyglot_project)
        diagnostics = graph.metadata.get("tree_sitter_diagnostics", [])
        
        langs_seen = {d["language"] for d in diagnostics if d["status"] == "native"}
        assert "javascript" in langs_seen
        assert "typescript" in langs_seen
        assert "go" in langs_seen
        assert "java" in langs_seen
