import pytest
from pathlib import Path
from impact_engine.extractors.python_ast import extract_project
from impact_engine.resolution.engine import resolve_graph
from tests.helpers.expected_edges import load_expected_edges, compare_expected_edges

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "realistic_impact_project"


def test_realistic_impact_project_regression():
    graph = extract_project(FIXTURE_PATH)
    resolved = resolve_graph(graph)
    
    expected = load_expected_edges(FIXTURE_PATH / "expected_edges.json")
    
    res = compare_expected_edges(resolved, expected)
    
    # Assertions
    assert len(res["must_find_missing"]) == 0, f"Missing must_find edges: {res['must_find_missing']}"
    assert len(res["must_not_find_present"]) == 0, f"Forbidden must_not_find edges present: {res['must_not_find_present']}"
    
    print("\n--- Realistic Project Regression Report ---")
    print(f"Must Find: {len(res['must_find_found'])} / {len(expected['must_find'])} found")
    print(f"Should Find: {len(res['should_find_found'])} / {len(expected['should_find'])} found")
    print(f"Must Not Find: {len(res['must_not_find_absent'])} / {len(expected['must_not_find'])} absent")
    
    if res["should_find_missing"]:
        print(f"Gaps identified (Should Find missing): {res['should_find_missing']}")
