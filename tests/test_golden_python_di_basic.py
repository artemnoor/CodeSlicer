import json
import pytest
from pathlib import Path
from impact_engine.models import Edge, Evidence, GraphDocument
from impact_engine.extractors.python_ast import extract_project
from impact_engine.resolution.precision import resolve_precision

# Path to the expected edges file and project path relative to this test file
EXPECTED_EDGES_PATH = Path(__file__).parent.parent / "examples" / "golden_cases" / "python_di_basic" / "expected_edges.json"
PROJECT_PATH = Path(__file__).parent.parent / "examples" / "golden_cases" / "python_di_basic"


def assert_expected_edge_matches(actual_edge: Edge, expected_edge: dict):
    assert actual_edge.kind == expected_edge["kind"], f"Expected kind {expected_edge['kind']}, got {actual_edge.kind}"
    assert actual_edge.from_node == expected_edge["from"], f"Expected from_node {expected_edge['from']}, got {actual_edge.from_node}"
    assert actual_edge.to_node == expected_edge["to"], f"Expected to_node {expected_edge['to']}, got {actual_edge.to_node}"
    assert actual_edge.source == expected_edge["source"], f"Expected source {expected_edge['source']}, got {actual_edge.source}"
    assert actual_edge.confidence >= expected_edge["min_confidence"], f"Expected confidence >= {expected_edge['min_confidence']}, got {actual_edge.confidence}"
    if expected_edge.get("requires_evidence"):
        assert len(actual_edge.evidence) > 0, "Expected evidence to be present, but evidence list is empty"


def test_expected_edges_json_structure():
    # 1. Тест должен читать examples/golden_cases/python_di_basic/expected_edges.json
    assert EXPECTED_EDGES_PATH.exists(), f"File {EXPECTED_EDGES_PATH} does not exist"
    with open(EXPECTED_EDGES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 2. Тест должен проверять структуру файла
    assert "expected_edges" in data, "Missing 'expected_edges' key in JSON"
    expected_list = data["expected_edges"]
    assert isinstance(expected_list, list), "'expected_edges' must be a list"
    assert len(expected_list) > 0, "'expected_edges' list cannot be empty"

    for edge in expected_list:
        assert "from" in edge, "Missing 'from' key in expected edge"
        assert "to" in edge, "Missing 'to' key in expected edge"
        assert "kind" in edge, "Missing 'kind' key in expected edge"
        assert "source" in edge, "Missing 'source' key in expected edge"
        assert "min_confidence" in edge, "Missing 'min_confidence' key in expected edge"
        assert "requires_evidence" in edge, "Missing 'requires_evidence' key in expected edge"

    # 3. Тест должен явно проверить, что в expected file есть главный edge
    main_edge_found = False
    for edge in expected_list:
        if (
            edge["from"] == "services.OrderService.create_order"
            and edge["to"] == "repositories.OrderRepository.save"
            and edge["kind"] == "CALLS"
            and edge["source"] == "INFERRED"
            and edge["min_confidence"] >= 0.8
            and edge["requires_evidence"] is True
        ):
            main_edge_found = True
            break
    assert main_edge_found, "Main edge services.OrderService.create_order -> repositories.OrderRepository.save not found in expected_edges.json with correct properties"


def test_helper_assertions():
    # 5. Добавь unit test helper-а на искусственном Edge, созданном через impact_engine.models.Edge.
    # Success case
    actual_edge = Edge(
        id="edge-1",
        kind="CALLS",
        from_node="services.OrderService.create_order",
        to_node="repositories.OrderRepository.save",
        source="INFERRED",
        confidence=0.85,
        evidence=[Evidence(description="receiver resolved", file="services.py", line=5)]
    )
    
    expected_edge = {
        "from": "services.OrderService.create_order",
        "to": "repositories.OrderRepository.save",
        "kind": "CALLS",
        "source": "INFERRED",
        "min_confidence": 0.8,
        "requires_evidence": True
    }
    
    # This should pass without raising AssertionError
    assert_expected_edge_matches(actual_edge, expected_edge)

    # Failure case: different kind
    bad_kind_edge = Edge(
        id="edge-1",
        kind="CONTAINS",
        from_node="services.OrderService.create_order",
        to_node="repositories.OrderRepository.save",
        source="INFERRED",
        confidence=0.85,
        evidence=[Evidence(description="receiver resolved", file="services.py", line=5)]
    )
    with pytest.raises(AssertionError):
        assert_expected_edge_matches(bad_kind_edge, expected_edge)

    # Failure case: different endpoints
    bad_from_edge = Edge(
        id="edge-1",
        kind="CALLS",
        from_node="services.OrderService.other_method",
        to_node="repositories.OrderRepository.save",
        source="INFERRED",
        confidence=0.85,
        evidence=[Evidence(description="receiver resolved", file="services.py", line=5)]
    )
    with pytest.raises(AssertionError):
        assert_expected_edge_matches(bad_from_edge, expected_edge)

    # Failure case: lower confidence
    low_confidence_edge = Edge(
        id="edge-1",
        kind="CALLS",
        from_node="services.OrderService.create_order",
        to_node="repositories.OrderRepository.save",
        source="INFERRED",
        confidence=0.7,
        evidence=[Evidence(description="receiver resolved", file="services.py", line=5)]
    )
    with pytest.raises(AssertionError):
        assert_expected_edge_matches(low_confidence_edge, expected_edge)

    # Failure case: missing evidence
    no_evidence_edge = Edge(
        id="edge-1",
        kind="CALLS",
        from_node="services.OrderService.create_order",
        to_node="repositories.OrderRepository.save",
        source="INFERRED",
        confidence=0.9,
        evidence=[]
    )
    with pytest.raises(AssertionError):
        assert_expected_edge_matches(no_evidence_edge, expected_edge)


def test_python_di_basic_pipeline_produces_expected_edges():
    # 6. Pipeline test for extractor + resolver.
    
    # 1. Run skeleton extractor
    extracted_doc = extract_project(PROJECT_PATH)
    
    # 2. Run skeleton resolver
    resolved_doc = resolve_precision(extracted_doc)
    
    # 3. Read expected edges
    with open(EXPECTED_EDGES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    expected_list = data["expected_edges"]
    
    # 4. Try to match each expected edge to one of the resolved edges
    # (This will fail currently because resolved_doc will have no edges or only skeleton metadata)
    for expected in expected_list:
        matched = False
        for actual in resolved_doc.edges:
            try:
                assert_expected_edge_matches(actual, expected)
                matched = True
                break
            except AssertionError:
                continue
        assert matched, f"Could not find a matching resolved edge for expected: {expected}"
