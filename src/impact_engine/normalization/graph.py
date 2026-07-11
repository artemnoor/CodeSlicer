"""Unified normalizer for external and internal graph documents. Stage 11."""
from typing import Any, Dict, Optional
from impact_engine.models import GraphDocument, Node, Edge, Evidence


def normalize_node_dict(data: dict) -> Optional[Node]:
    if not isinstance(data, dict):
        return None
    node_id = data.get("id")
    kind = data.get("kind")
    name = data.get("name")
    properties = data.get("properties", {})
    if not node_id or not kind or not name:
        return None
    try:
        return Node(
            id=str(node_id),
            kind=str(kind),
            name=str(name),
            properties=dict(properties)
        )
    except Exception:
        return None


def normalize_edge_dict(data: dict, default_source: str = "EXTERNAL_TOOL") -> Optional[Edge]:
    if not isinstance(data, dict):
        return None
    edge_id = data.get("id")
    kind = data.get("kind")
    from_node = data.get("from")
    to_node = data.get("to")
    source = data.get("source") or default_source
    if source == "INFERRED":
        source = "EXTERNAL_TOOL"
    confidence = data.get("confidence", 1.0)
    properties = data.get("properties", {})
    
    if not edge_id or not kind or not from_node or not to_node:
        return None
        
    try:
        evidence_obj = Evidence(
            file=None,
            line=None,
            description="Normalized from external graph input"
        )
        return Edge(
            id=str(edge_id),
            kind=str(kind),
            from_node=str(from_node),
            to_node=str(to_node),
            source=str(source),
            confidence=float(confidence),
            evidence=[evidence_obj],
            properties=dict(properties)
        )
    except Exception:
        return None


def normalize_external_graph(data: dict, source_name: str = "external") -> GraphDocument:
    skipped_nodes = 0
    skipped_edges = 0
    
    graph = GraphDocument(
        metadata={
            "source": source_name,
            "normalizer": "impact_engine.normalization.graph",
            "status": "normalized",
            "skipped_nodes": 0,
            "skipped_edges": 0
        }
    )
    
    if not isinstance(data, dict):
        graph.metadata["skipped_nodes"] = skipped_nodes
        graph.metadata["skipped_edges"] = skipped_edges
        return graph
        
    nodes_list = data.get("nodes", [])
    if isinstance(nodes_list, list):
        for node_data in nodes_list:
            node = normalize_node_dict(node_data)
            if node is not None:
                graph.add_node(node)
            else:
                skipped_nodes += 1
    else:
        skipped_nodes += 1
        
    edges_list = data.get("edges", [])
    if isinstance(edges_list, list):
        for edge_data in edges_list:
            edge = normalize_edge_dict(edge_data)
            if edge is not None:
                graph.add_edge(edge)
            else:
                skipped_edges += 1
    else:
        skipped_edges += 1
        
    graph.metadata["skipped_nodes"] = skipped_nodes
    graph.metadata["skipped_edges"] = skipped_edges
    return graph


def normalize_graph_document(graph: GraphDocument) -> GraphDocument:
    if graph.metadata is None:
        graph.metadata = {}
    graph.metadata["normalized"] = True
    graph.metadata["normalizer"] = "impact_engine.normalization.graph"
    return graph


def merge_graph_documents(graphs: list[GraphDocument], source_labels: list[str] | None = None) -> GraphDocument:
    merged = GraphDocument()
    edge_evidence_index: dict[tuple[str, str, str, str, int], Edge] = {}

    def evidence_signature(edge: Edge) -> int:
        values = tuple(sorted(hash((ev.file, ev.line, ev.description)) for ev in edge.evidence))
        return hash(values)

    sources = set()
    extractors = set()
    if source_labels:
        sources.update(source_labels)
        
    for graph in graphs:
        if graph.metadata:
            if "source" in graph.metadata:
                sources.add(graph.metadata["source"])
            if "sources" in graph.metadata and isinstance(graph.metadata["sources"], list):
                sources.update(graph.metadata["sources"])
            if "extractor" in graph.metadata:
                extractors.add(graph.metadata["extractor"])
            if "extractors" in graph.metadata and isinstance(graph.metadata["extractors"], list):
                extractors.update(graph.metadata["extractors"])
            for key in ("tree_sitter_status", "tree_sitter_diagnostics", "tree_sitter_errors"):
                if key in graph.metadata:
                    if isinstance(graph.metadata[key], list):
                        merged.metadata.setdefault(key, [])
                        merged.metadata[key].extend(graph.metadata[key])
                    else:
                        merged.metadata[key] = graph.metadata[key]
                
        for node in graph.nodes:
            existing = merged._node_index.get(node.id)
            if existing is None:
                merged.add_node(Node(
                    id=node.id,
                    kind=node.kind,
                    name=node.name,
                    properties=dict(node.properties)
                ))
            else:
                existing.properties.update(node.properties)
                
        for edge in graph.edges:
            key = (edge.from_node, edge.to_node, edge.kind, edge.source, evidence_signature(edge))
            existing = edge_evidence_index.get(key)
            if existing:
                existing.properties.update(edge.properties)
            else:
                incoming = Edge(
                    id=edge.id,
                    kind=edge.kind,
                    from_node=edge.from_node,
                    to_node=edge.to_node,
                    source=edge.source,
                    confidence=edge.confidence,
                    evidence=list(edge.evidence),
                    properties=dict(edge.properties)
                )
                merged.add_edge(incoming)
                stored = merged._edge_index.get(incoming.semantic_key(True)) or merged._edge_base_index.get(incoming.semantic_key(False)) or merged._edge_id_index.get(incoming.id)
                if stored is not None:
                    edge_evidence_index[key] = stored
                
    merged.metadata["sources"] = sorted(list(sources))
    merged.metadata["extractors"] = sorted(list(extractors))
    merged.metadata["normalizer"] = "impact_engine.normalization.graph"
    merged.metadata["normalized"] = True
    return merged
