"""Internal helpers for resolver precision and scope resolution. Stage 15."""
from collections.abc import Callable
from typing import Optional, Tuple
from impact_engine.models import GraphDocument
from impact_engine.resolution.symbol_index import SymbolIndex


def resolve_class_name(class_name: str, current_module: str, index: SymbolIndex) -> Optional[str]:
    return index.resolve_class_name(class_name, current_module)


def get_node_location(node_id: str, doc: GraphDocument) -> Tuple[Optional[str], Optional[int]]:
    doc._ensure_indexes()
    for edge in doc._incoming_index.get(node_id, []):
        if edge.to_node == node_id and edge.evidence:
            return edge.evidence[0].file, edge.evidence[0].line
    return None, None


def module_for_scope(scope: str, graph: GraphDocument) -> str:
    cache = getattr(graph, "_module_scope_cache", None)
    if not isinstance(cache, dict):
        cache = {"scopes": {}, "modules": sorted({
            node.id[7:] if node.id.startswith("module:") else node.id
            for node in graph.nodes if node.kind == "MODULE"
        }, key=len, reverse=True)}
        setattr(graph, "_module_scope_cache", cache)
    scopes = cache["scopes"]
    if scope not in scopes:
        scopes[scope] = next((name for name in cache["modules"] if scope == name or scope.startswith(name + ".")), scope.split(".")[0])
    return scopes[scope]


def build_module_scope_resolver(graph: GraphDocument) -> Callable[[str], str]:
    """Build a memoized module lookup for one precision-resolution run.

    Precision inference asks for the owning module at several points in each
    fixpoint pass.  Scanning all graph nodes for every lookup made resolution
    quadratic on large projects.  Module nodes are immutable for this stage,
    so one sorted index plus a scope cache preserves the exact longest-prefix
    rule without repeated graph walks.
    """
    module_names = sorted(
        {
            node.id[7:] if node.id.startswith("module:") else node.id
            for node in graph.nodes
            if node.kind == "MODULE"
        },
        key=len,
        reverse=True,
    )
    cache: dict[str, str] = {}

    def resolve(scope: str) -> str:
        cached = cache.get(scope)
        if cached is not None:
            return cached
        result = next(
            (
                module_name
                for module_name in module_names
                if scope == module_name or scope.startswith(module_name + ".")
            ),
            scope.split(".")[0],
        )
        cache[scope] = result
        return result

    return resolve
