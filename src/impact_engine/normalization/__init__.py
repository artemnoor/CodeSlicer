"""Normalization module for unified graph representation."""
from impact_engine.normalization.graph import (
    normalize_node_dict,
    normalize_edge_dict,
    normalize_external_graph,
    normalize_graph_document
)

__all__ = [
    "normalize_node_dict",
    "normalize_edge_dict",
    "normalize_external_graph",
    "normalize_graph_document"
]
