"""Nested Object Graph Resolver.

Public API:
    resolve_nested_object_graph(input_data: dict) -> dict
"""

from .resolver import resolve_nested_object_graph

__all__ = ["resolve_nested_object_graph"]
__version__ = "0.1.0"
