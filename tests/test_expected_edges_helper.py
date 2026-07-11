import pytest
import json
from pathlib import Path
from impact_engine.models import GraphDocument, Edge
from tests.helpers.expected_edges import compare_expected_edges, load_expected_edges


def test_expected_edges_comparison():
    graph = GraphDocument()
    # Add a found edge
    graph.add_edge(Edge(
        id="edge-1",
        kind="CALLS",
        from_node="a",
        to_node="b",
        source="EXTRACTED",
        confidence=1.0,
        evidence=[]
    ))
    # Add a forbidden edge that is present
    graph.add_edge(Edge(
        id="edge-2",
        kind="DEPENDS_ON",
        from_node="x",
        to_node="y",
        source="EXTRACTED",
        confidence=1.0,
        evidence=[]
    ))
    
    expected = {
        "must_find": [
            {"from": "a", "to": "b", "kind": "CALLS"},  # should be found
            {"from": "c", "to": "d", "kind": "CALLS"}   # should be missing
        ],
        "should_find": [
            {"from": "a", "to": "b", "kind": "CALLS"},  # should be found
            {"from": "e", "to": "f", "kind": "CALLS"}   # should be missing
        ],
        "must_not_find": [
            {"from": "x", "to": "y", "kind": "DEPENDS_ON"},  # should be present (failed assertion)
            {"from": "w", "to": "z", "kind": "DEPENDS_ON"}   # should be absent (passed assertion)
        ]
    }
    
    res = compare_expected_edges(graph, expected)
    
    assert res["must_find_found"] == [{"from": "a", "to": "b", "kind": "CALLS"}]
    assert res["must_find_missing"] == [{"from": "c", "to": "d", "kind": "CALLS"}]
    assert res["should_find_found"] == [{"from": "a", "to": "b", "kind": "CALLS"}]
    assert res["should_find_missing"] == [{"from": "e", "to": "f", "kind": "CALLS"}]
    assert res["must_not_find_present"] == [{"from": "x", "to": "y", "kind": "DEPENDS_ON"}]
    assert res["must_not_find_absent"] == [{"from": "w", "to": "z", "kind": "DEPENDS_ON"}]


def test_load_expected_edges_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        load_expected_edges(Path("nonexistent_file_path.json"))


def test_load_expected_edges_success(tmp_path):
    data = {
        "must_find": [{"from": "x", "to": "y", "kind": "CALLS"}],
        "should_find": [],
        "must_not_find": []
    }
    temp_file = tmp_path / "expected_edges.json"
    temp_file.write_text(json.dumps(data), encoding="utf-8")
    
    loaded = load_expected_edges(temp_file)
    assert loaded == data
