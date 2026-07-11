import pytest
from pathlib import Path
from impact_engine.mcp.server import (
    analyze_project,
    impact_query,
    explain_edge,
    detect_unknown_libraries,
    detect_languages,
    project_inventory,
    list_support_packs,
    validate_support_pack,
    create_library_research_request
)

PROJECT_PATH = Path(__file__).parent.parent / "examples" / "golden_cases" / "python_di_basic"
EXAMPLE_PACK_PATH = Path(__file__).parent.parent / "support_packs" / "example_library" / "support_pack.json"


@pytest.fixture
def temp_graph_path(tmp_path):
    return tmp_path / "graph.json"


def test_mcp_analyze_project_wraps_core(temp_graph_path):
    res = analyze_project(str(PROJECT_PATH), out_path=str(temp_graph_path))
    assert res["status"] == "ok"
    assert res["tool"] == "analyze_project"
    assert res["graph_path"] == str(temp_graph_path)
    assert res["nodes"] > 0
    assert res["edges"] > 0
    assert temp_graph_path.exists()


def test_mcp_impact_query_wraps_core(temp_graph_path):
    # First analyze
    analyze_project(str(PROJECT_PATH), out_path=str(temp_graph_path))
    
    # Now query impact
    res = impact_query(str(temp_graph_path), "services.OrderService.create_order")
    assert res["status"] == "ok"
    assert res["tool"] == "impact_query"
    
    result = res["result"]
    assert result["target"] == "services.OrderService.create_order"
    assert "repositories.OrderRepository.save" in result["downstream"]


def test_mcp_explain_edge_wraps_core(temp_graph_path):
    # First analyze
    analyze_project(str(PROJECT_PATH), out_path=str(temp_graph_path))
    
    # Now explain edge
    res = explain_edge(
        str(temp_graph_path),
        from_symbol="services.OrderService.create_order",
        to_symbol="repositories.OrderRepository.save",
        kind="CALLS"
    )
    assert res["status"] == "ok"
    assert res["tool"] == "explain_edge"
    
    result = res["result"]
    assert result["found"] is True
    assert result["edge"]["source"] == "INFERRED"
    assert result["edge"]["confidence"] >= 0.80
    assert len(result["evidence"]) >= 4


def test_mcp_validate_support_pack():
    res = validate_support_pack(str(EXAMPLE_PACK_PATH))
    assert res["status"] == "ok"
    assert res["tool"] == "validate_support_pack"
    assert res["valid"] is True
    assert len(res["errors"]) == 0


def test_mcp_list_support_packs():
    # Registry root is parent of support_packs folder
    support_packs_root = Path(__file__).parent.parent / "support_packs"
    res = list_support_packs(root=str(support_packs_root))
    assert res["status"] == "ok"
    assert res["tool"] == "list_support_packs"
    
    # The example support pack path should be in the returned list
    packs = res["packs"]
    assert len(packs) > 0
    assert any("example_library/support_pack.json" in p for p in packs)


def test_mcp_create_library_research_request_no_network():
    res = create_library_research_request("requests", version="1.0", package_manager="pip")
    assert res["status"] == "ok"
    assert res["tool"] == "create_library_research_request"
    assert res["library_name"] == "requests"
    assert res["version"] == "1.0"
    assert res["package_manager"] == "pip"
    
    prompt = res["prompt"]
    assert "official documentation" in prompt or "official GitHub" in prompt
    assert "machine-readable support_pack.json" in prompt


def test_mcp_detect_unknown_libraries_golden_case():
    res = detect_unknown_libraries(str(PROJECT_PATH))
    assert res["status"] == "ok"
    assert res["tool"] == "detect_unknown_libraries"
    assert isinstance(res["unknown_libraries"], list)
    # The golden case dependencies (repositories, services) are local modules, so they should be ignored
    assert res["unknown_libraries"] == []


def test_mcp_detect_languages():
    res = detect_languages(str(PROJECT_PATH))
    assert res["status"] == "ok"
    assert res["tool"] == "detect_languages"
    assert "python" in res["languages"]


def test_mcp_project_inventory():
    res = project_inventory(str(PROJECT_PATH))
    assert res["status"] == "ok"
    assert res["tool"] == "project_inventory"
    inv = res["inventory"]
    assert "python" in inv["languages"]
    assert any("container.py" in f for f in inv["files"])


def test_mcp_detect_unknown_libraries_invalid_path():
    res = detect_unknown_libraries("non_existent_directory_xyz")
    assert res["status"] == "error"
    assert res["tool"] == "detect_unknown_libraries"
    assert "error" in res


def test_mcp_analyze_project_exposes_new_keys(temp_graph_path):
    res = analyze_project(str(PROJECT_PATH), out_path=str(temp_graph_path))
    assert res["status"] == "ok"
    assert "languages" in res
    assert "extractors_used" in res
    assert "diagnostics" in res
    assert "support_pack_load_errors" in res
    assert "graph" in res

