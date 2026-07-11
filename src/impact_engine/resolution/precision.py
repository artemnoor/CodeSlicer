"""Precision resolver backward compatibility wrapper. Stage 5 API wrapper."""
from impact_engine.models import GraphDocument


def resolve_precision(graph: GraphDocument, support_packs: list | None = None) -> GraphDocument:
    from impact_engine.resolution.engine import resolve_graph
    return resolve_graph(graph, support_packs=support_packs)
