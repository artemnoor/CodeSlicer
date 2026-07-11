import pytest
import json
from pathlib import Path
from impact_engine.adapters.graphify import from_graphify_json, from_graphify_file
from impact_engine.models import GraphDocument


def test_graphify_adapter_imports_structural_nodes_and_edges():
    data = {
        "nodes": [
            {"id": "module:example", "kind": "MODULE", "name": "example", "properties": {"path": "example.py", "custom": "abc"}}
        ],
        "edges": [
            {"id": "edge-1", "kind": "CONTAINS", "from": "module:example", "to": "module:example", "properties": {"extra": 123}}
        ]
    }
    
    doc = from_graphify_json(data)
    assert isinstance(doc, GraphDocument)
    assert len(doc.nodes) == 1
    assert len(doc.edges) == 1
    
    node = doc.nodes[0]
    assert node.id == "module:example"
    assert node.kind == "MODULE"
    assert node.properties["custom"] == "abc"
    
    edge = doc.edges[0]
    assert edge.id == "edge-1"
    assert edge.kind == "CONTAINS"
    assert edge.source == "EXTERNAL_TOOL"
    assert edge.confidence == 1.0
    assert edge.properties["extra"] == 123


def test_graphify_adapter_adds_evidence():
    data = {
        "nodes": [
            {"id": "module:example", "kind": "MODULE", "name": "example", "properties": {}}
        ],
        "edges": [
            {"id": "edge-1", "kind": "CONTAINS", "from": "module:example", "to": "module:example"}
        ]
    }
    
    doc = from_graphify_json(data)
    edge = doc.edges[0]
    assert len(edge.evidence) == 1
    assert "Normalized from external graph input" in edge.evidence[0].description


def test_graphify_adapter_skips_invalid_kinds():
    data = {
        "nodes": [
            {"id": "node-1", "kind": "INVALID_KIND", "name": "name"}
        ],
        "edges": [
            {"id": "edge-1", "kind": "INVALID_KIND", "from": "node-1", "to": "node-2"}
        ]
    }
    
    doc = from_graphify_json(data)
    assert len(doc.nodes) == 0
    assert len(doc.edges) == 0
    assert doc.metadata["skipped_nodes"] == 1
    assert doc.metadata["skipped_edges"] == 1


def test_graphify_file_loader(tmp_path):
    data = {
        "nodes": [
            {"id": "module:example", "kind": "MODULE", "name": "example"}
        ],
        "edges": []
    }
    
    temp_file = tmp_path / "graphify_export.json"
    temp_file.write_text(json.dumps(data), encoding="utf-8")
    
    doc = from_graphify_file(temp_file)
    assert isinstance(doc, GraphDocument)
    assert len(doc.nodes) == 1
    assert doc.nodes[0].id == "module:example"


def test_graphify_adapter_does_not_create_inferred_edges():
    data = {
        "nodes": [
            {"id": "a", "kind": "MODULE", "name": "a"},
            {"id": "b", "kind": "MODULE", "name": "b"}
        ],
        "edges": [
            {"id": "edge-1", "kind": "CONTAINS", "from": "a", "to": "b"}
        ]
    }
    
    doc = from_graphify_json(data)
    for edge in doc.edges:
        assert edge.source != "INFERRED"
        assert edge.source == "EXTERNAL_TOOL"


def test_is_graphify_available():
    from impact_engine.adapters.graphify import is_graphify_available
    res = is_graphify_available()
    assert isinstance(res, bool)


def test_normalize_graphify_json():
    from impact_engine.adapters.graphify import normalize_graphify_json
    data = {
        "nodes": [
            {"key": "a", "type": "module", "label": "a_label"}
        ],
        "edges": [
            {"source": "a", "target": "a", "label": "calls"}
        ]
    }
    doc = normalize_graphify_json(data)
    assert len(doc.nodes) == 1
    assert doc.nodes[0].id == "a"
    assert doc.nodes[0].kind == "MODULE"
    assert doc.nodes[0].name == "a_label"
    assert len(doc.edges) == 1
    assert doc.edges[0].from_node == "a"
    assert doc.edges[0].to_node == "a"
    assert doc.edges[0].kind == "CALLS"


def test_graphify_links_are_supported_with_bounded_external_confidence():
    from impact_engine.adapters.graphify import normalize_graphify_json

    doc = normalize_graphify_json({
        "nodes": [
            {"id": "a", "label": "a", "file_type": "code"},
            {"id": "b", "label": "b", "file_type": "code"},
        ],
        "links": [{
            "source": "a", "target": "b", "relation": "calls",
            "confidence": "INFERRED", "source_file": "main.py", "source_location": "L3",
        }],
    })
    assert len(doc.edges) == 1
    assert doc.edges[0].source == "EXTERNAL_TOOL"
    assert doc.edges[0].confidence == 0.55
    assert doc.edges[0].properties["external_tool"] == "graphify"


def test_graphify_file_loader_accepts_native_links_shape(tmp_path):
    from impact_engine.adapters.graphify import from_graphify_file
    path = tmp_path / "graph.json"
    path.write_text(json.dumps({
        "nodes": [{"id": "a", "label": "a"}, {"id": "b", "label": "b"}],
        "links": [{"source": "a", "target": "b", "relation": "imports_from", "confidence": "EXTRACTED"}],
    }), encoding="utf-8")
    doc = from_graphify_file(path)
    assert len(doc.edges) == 1
    assert doc.edges[0].source == "EXTERNAL_TOOL"
    assert doc.edges[0].confidence == 0.6
