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
    _materialize_unresolved_endpoints(graph)
    return graph


def normalize_graph_document(graph: GraphDocument) -> GraphDocument:
    if graph.metadata is None:
        graph.metadata = {}
    graph.metadata["normalized"] = True
    graph.metadata["normalizer"] = "impact_engine.normalization.graph"
    _canonicalize_scope_endpoints(graph)
    _materialize_unresolved_endpoints(graph)
    return graph


def _materialize_unresolved_endpoints(graph: GraphDocument) -> None:
    """Make unresolved CALLS/DEPENDS_ON endpoints explicit graph nodes.

    Extractors may know a display name but not a canonical declaration ID.
    Keeping the edge without an endpoint makes the GraphDocument internally
    inconsistent; an explicit suppressed external node preserves provenance
    while allowing every edge to satisfy the graph schema.
    """
    graph._ensure_indexes()
    node_ids = {node.id for node in graph.nodes}
    created = 0
    for edge in graph.edges:
        if edge.kind not in {"CALLS", "DEPENDS_ON"}:
            continue
        for endpoint in (edge.from_node, edge.to_node):
            if endpoint in node_ids:
                continue
            graph.add_node(Node(
                id=endpoint,
                kind="EXTERNAL_LIBRARY",
                name=endpoint,
                properties={
                    "unresolved_endpoint": True,
                    "resolution_status": "unresolved",
                    "original_endpoint": endpoint,
                    "normalizer": "impact_engine.normalization.graph",
                },
            ))
            node_ids.add(endpoint)
            created += 1
    graph.metadata["materialized_unresolved_endpoint_nodes"] = created


def _canonicalize_scope_endpoints(graph: GraphDocument) -> None:
    """Map resolver display scopes to canonical node IDs before integrity checks."""
    node_ids = {node.id for node in graph.nodes}
    node_by_id = {node.id: node for node in graph.nodes}
    aliases: dict[str, str] = {}
    for node in graph.nodes:
        if node.kind not in {"ASSIGNMENT", "CALL_EXPR", "EXTERNAL_LIBRARY", "CANONICAL_ALIAS", "SUPPORT_PACK"}:
            for key in ("scope", "qualified_name", "canonical_name"):
                value = node.properties.get(key)
                if value and str(value) not in aliases:
                    aliases[str(value)] = node.id
        # An unresolved external placeholder may happen to have the same
        # display name as a later workspace declaration.  It must never win
        # the alias index over that declaration.
        if node.kind != "EXTERNAL_LIBRARY" and node.name and node.name not in aliases:
            aliases[node.name] = node.id
    changed = 0
    for edge in graph.edges:
        for endpoint_name, side in ((edge.from_node, "from"), (edge.to_node, "to")):
            if endpoint_name not in node_ids and endpoint_name in aliases:
                target_id = aliases[endpoint_name]
                # Legacy extractors/resolvers historically exposed scope names.
                # Preserve that serialized endpoint through an explicit alias,
                # while modern plugin extractors can emit canonical IDs. This
                # keeps old API consumers working without dangling nodes and
                # records the compatibility boundary in provenance.
                if edge.source == "SUPPORT_PACK":
                    original = node_by_id.get(target_id)
                    if original is not None:
                        graph.add_node(Node(
                            id=endpoint_name,
                            kind=original.kind,
                            name=original.name,
                            properties={**original.properties, "compatibility_alias_for": target_id},
                        ))
                        node_ids.add(endpoint_name)
                        node_by_id[endpoint_name] = graph.get_node(endpoint_name)
                        changed += 1
                else:
                    original = node_by_id.get(target_id)
                    if original is not None:
                        graph.add_node(Node(
                            id=endpoint_name,
                            kind=original.kind,
                            name=original.name,
                            properties={**original.properties, "compatibility_alias_for": target_id},
                        ))
                        node_ids.add(endpoint_name)
                        node_by_id[endpoint_name] = graph.get_node(endpoint_name)
                        changed += 1
    # Earlier normalization passes may already have materialized a scope name
    # as EXTERNAL_LIBRARY.  If that name is now proven to be one local
    # declaration, retain it as a compatibility endpoint but do not mislabel a
    # workspace symbol as an external dependency.
    aliases_reclassified = 0
    for node in graph.nodes:
        if node.kind != "EXTERNAL_LIBRARY" or not (node.properties.get("unresolved_endpoint") or node.properties.get("unresolved")):
            continue
        target_id = aliases.get(node.id)
        target = node_by_id.get(target_id) if target_id else None
        if target is None or target.id == node.id:
            continue
        node.kind = "CANONICAL_ALIAS"
        node.properties["canonical_alias_of"] = target.id
        node.properties["scope"] = node.properties.get("scope") or str(target.properties.get("scope") or node.id)
        aliases_reclassified += 1
    graph._rebuild_edge_indexes()
    graph.metadata["canonicalized_endpoint_rewrites"] = changed
    graph.metadata["canonicalized_workspace_aliases"] = aliases_reclassified


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
            # Manifest-owned language providers may carry raw, evidence-backed
            # relation facts into framework hooks. Preserve namespaced
            # metadata instead of silently dropping it during multi-language
            # merge (for example C# generic MediatR base relations).
            for key, value in graph.metadata.items():
                if not str(key).startswith("csharp_"):
                    continue
                if isinstance(value, list):
                    merged.metadata.setdefault(key, [])
                    for item in value:
                        if item not in merged.metadata[key]:
                            merged.metadata[key].append(item)
                elif isinstance(value, dict):
                    merged.metadata.setdefault(key, {})
                    if isinstance(merged.metadata[key], dict):
                        merged.metadata[key].update(value)
                else:
                    merged.metadata[key] = value
                
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
