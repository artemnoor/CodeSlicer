"""Deterministic optional graph annotations for communities and hubs."""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from impact_engine.models import GraphDocument


def annotate_communities(graph: GraphDocument) -> GraphDocument:
    """Annotate weakly connected components and node degree.

    This is intentionally metadata-only. Community membership never changes
    resolver output or creates an edge.
    """
    adjacency: dict[str, set[str]] = defaultdict(set)
    degree: dict[str, int] = {node.id: 0 for node in graph.nodes}
    for edge in graph.edges:
        adjacency[edge.from_node].add(edge.to_node)
        adjacency[edge.to_node].add(edge.from_node)
        degree[edge.from_node] = degree.get(edge.from_node, 0) + 1
        degree[edge.to_node] = degree.get(edge.to_node, 0) + 1
    unseen = set(degree)
    components: list[list[str]] = []
    while unseen:
        seed = min(unseen)
        unseen.remove(seed)
        component = []
        queue = deque([seed])
        while queue:
            current = queue.popleft()
            component.append(current)
            for neighbor in sorted(adjacency.get(current, set())):
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    queue.append(neighbor)
        components.append(sorted(component))
    component_ids = {}
    for index, component in enumerate(sorted(components, key=lambda value: value[0] if value else ""), start=1):
        label = f"community-{index:04d}"
        for node_id in component:
            component_ids[node_id] = label
    hubs = sorted(degree, key=lambda node_id: (-degree[node_id], node_id))
    top_degree = degree[hubs[0]] if hubs else 0
    for node in graph.nodes:
        node.properties["community_id"] = component_ids.get(node.id)
        node.properties["graph_degree"] = degree.get(node.id, 0)
        node.properties["is_hub"] = bool(degree.get(node.id, 0) > 0 and degree[node.id] >= max(3, top_degree * 0.5))
    graph.metadata["communities"] = {
        "algorithm": "deterministic_weak_components",
        "count": len(components),
        "hub_nodes": hubs[:20],
        "status": "annotated",
    }
    return graph
