import pytest
from impact_engine.normalization import (
    normalize_external_graph,
    normalize_graph_document,
    normalize_node_dict,
    normalize_edge_dict
)
from impact_engine.adapters.graphify import from_graphify_json
from impact_engine.models import GraphDocument, Node, Edge, Evidence


def test_normalize_external_graph_imports_valid_nodes_edges():
    data = {
        "nodes": [
            {"id": "module:example", "kind": "MODULE", "name": "example", "properties": {"path": "example.py"}}
        ],
        "edges": [
            {"id": "edge-1", "kind": "CONTAINS", "from": "module:example", "to": "module:example", "properties": {"extra": 123}}
        ]
    }
    
    doc = normalize_external_graph(data, source_name="test_source")
    assert isinstance(doc, GraphDocument)
    assert len(doc.nodes) == 1
    assert len(doc.edges) == 1
    
    node = doc.nodes[0]
    assert node.id == "module:example"
    assert node.kind == "MODULE"
    
    edge = doc.edges[0]
    assert edge.id == "edge-1"
    assert edge.kind == "CONTAINS"
    assert edge.source == "EXTERNAL_TOOL"
    assert edge.confidence == 1.0
    assert len(edge.evidence) == 1
    assert edge.evidence[0].description == "Normalized from external graph input"


def test_normalize_external_graph_skips_invalid_kinds():
    data = {
        "nodes": [
            {"id": "node-1", "kind": "INVALID_KIND", "name": "name"}
        ],
        "edges": [
            {"id": "edge-1", "kind": "INVALID_KIND", "from": "node-1", "to": "node-2"}
        ]
    }
    
    doc = normalize_external_graph(data)
    assert len(doc.nodes) == 0
    assert len(doc.edges) == 0
    assert doc.metadata["skipped_nodes"] == 1
    assert doc.metadata["skipped_edges"] == 1


def test_normalizer_never_creates_inferred_edges():
    # Pass edge with source set to INFERRED, check if normalizer enforces default
    data = {
        "nodes": [
            {"id": "a", "kind": "MODULE", "name": "a"},
            {"id": "b", "kind": "MODULE", "name": "b"}
        ],
        "edges": [
            {"id": "edge-1", "kind": "CONTAINS", "from": "a", "to": "b", "source": "INFERRED"}
        ]
    }
    
    doc = normalize_external_graph(data)
    assert len(doc.edges) == 1
    assert doc.edges[0].source != "INFERRED"
    assert doc.edges[0].source == "EXTERNAL_TOOL"


def test_normalize_graph_document_is_idempotent():
    doc = GraphDocument(metadata={"source": "test"})
    doc.add_node(Node(id="module:x", kind="MODULE", name="x"))
    doc.add_edge(Edge(
        id="edge-1",
        kind="CONTAINS",
        from_node="module:x",
        to_node="module:x",
        source="EXTRACTED",
        confidence=1.0,
        evidence=[]
    ))
    
    normalized = normalize_graph_document(doc)
    assert len(normalized.nodes) == 1
    assert len(normalized.edges) == 1
    assert normalized.nodes[0].id == "module:x"
    assert normalized.edges[0].source == "EXTRACTED"  # remains unchanged
    assert normalized.metadata["normalized"] is True
    assert normalized.metadata["normalizer"] == "impact_engine.normalization.graph"


def test_graphify_adapter_uses_normalizer_contract():
    data = {
        "nodes": [
            {"id": "module:example", "kind": "MODULE", "name": "example"}
        ],
        "edges": []
    }
    
    doc = from_graphify_json(data)
    assert doc.metadata["source"] == "graphify"
    assert doc.metadata["adapter"] == "graphify"
    assert doc.metadata["normalizer"] == "impact_engine.normalization.graph"
