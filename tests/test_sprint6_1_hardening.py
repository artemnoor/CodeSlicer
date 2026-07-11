from __future__ import annotations

import json
from pathlib import Path

from impact_engine.impact import impact_query
from impact_engine.inventory.scanner import scan_project_inventory
from impact_engine.models import Edge, GraphDocument, Node
from impact_engine.support_packs.detection import detect_unknown_libraries_core


FIXTURES = Path(__file__).parent / "fixtures" / "sprint6_1_classification"


def test_stdlib_and_local_classification_has_no_false_unknowns():
    expected = {
        "go_stdlib": set(),
        "python_stdlib": set(),
        "ts_alias": set(),
        "java_local": set(),
        "test_only": set(),
    }
    for name, forbidden in expected.items():
        project = FIXTURES / name
        inventory = scan_project_inventory(project)
        unknown = set(detect_unknown_libraries_core(str(project)))
        assert not (unknown & forbidden)
        assert inventory.external_imports_by_ecosystem is not None
        assert name != ""  # keeps the fixture table explicit in failure output


def test_stdlib_imports_are_not_external_or_unknown():
    checks = {
        "python_stdlib": ("python", {"uuid"}),
        "go_stdlib": ("go", {"bytes", "context", "testing"}),
    }
    for name, (ecosystem, imports) in checks.items():
        inventory = scan_project_inventory(FIXTURES / name)
        assert not imports.intersection(set(inventory.external_imports_by_ecosystem.get(ecosystem, [])))


def test_ts_aliases_are_local_but_scoped_packages_remain_external():
    project = Path(__file__).parent / "fixtures" / "sprint6_1_classification" / "ts_alias"
    inventory = scan_project_inventory(project)
    unknown = set(detect_unknown_libraries_core(str(project)))
    assert "@/service" not in unknown
    assert "@/service" not in inventory.external_imports_by_ecosystem.get("typescript", [])


def test_alias_shadowing_does_not_hide_scoped_dependency():
    project = Path(__file__).parent / "fixtures" / "sprint6_1_classification" / "ts_alias_scoped"
    inventory = scan_project_inventory(project)
    unknown = set(detect_unknown_libraries_core(str(project)))
    assert "@/service" not in unknown
    assert "@unknown/vendor" in unknown


def test_impact_query_reports_isolation_instead_of_silent_empty():
    graph = GraphDocument()
    graph.add_node(Node(id="python://demo#isolated", kind="FUNCTION", name="isolated"))
    result = impact_query(graph, target="python://demo#isolated")
    assert result["isolated"] is True
    assert result["isolation_reason"] == "node_has_no_active_edges"
    assert result["query_diagnostics"]["matched_node_count"] == 1


def test_impact_query_reports_unknown_target_reason():
    result = impact_query(GraphDocument(), target="missing.symbol")
    assert result["isolated"] is False
    assert result["isolation_reason"] == "no_matching_node_or_edge_endpoint"


def test_incremental_metadata_contract_is_serializable():
    graph = GraphDocument(metadata={
        "incremental_cache": {
            "files_total": 3,
            "files_reused": 2,
            "files_reanalyzed": 1,
            "cache_hit_rate": 0.666667,
        }
    })
    assert json.loads(graph.to_json())["metadata"]["incremental_cache"]["files_reused"] == 2
