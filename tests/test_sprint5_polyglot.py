from pathlib import Path

from impact_engine.analysis.pipeline import analyze_project_core


FIXTURES = Path(__file__).parent / "fixtures"


def test_go_limited_provider_resolves_typed_receiver_only():
    result = analyze_project_core(str(FIXTURES / "go_basic_project"))
    edges = result["graph"]["edges"]
    assert any(
        edge["from"] == "main.Service.Process"
        and edge["to"] == "main.Service.Save"
        and edge["properties"].get("provider") == "polyglot_limited_semantics"
        and edge["properties"].get("resolution_status") == "resolved_inferred"
        for edge in edges
    )
    assert not any(edge["to"] == "lib.Call" and edge["source"] == "INFERRED" for edge in edges)


def test_java_limited_provider_resolves_this_call_without_name_only_matching():
    result = analyze_project_core(str(FIXTURES / "java_basic_project"))
    edges = result["graph"]["edges"]
    assert any(
        edge["from"] == "com.example.OrderService.createOrder"
        and edge["to"] == "com.example.OrderService.save"
        and edge["properties"].get("provider") == "polyglot_limited_semantics"
        for edge in edges
    )
    assert result["graph"]["metadata"]["polyglot_semantic_resolution"]["capabilities"]["java"]
