"""Internal helpers for resolver precision and scope resolution. Stage 15."""
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
    # Resolution calls this for every callsite and assignment.  Cache the
    # result per scope and pre-sort module names once; the prior full graph
    # scan here turned ordinary Python projects into O(calls * nodes) work.
    cache = getattr(graph, "_module_scope_cache", None)
    if cache is None:
        module_names = []
        for node in graph.nodes:
            if node.kind != "MODULE":
                continue
            module_id = node.id
            module_names.append(module_id[7:] if module_id.startswith("module:") else module_id)
        module_names.sort(key=len, reverse=True)
        cache = {"modules": module_names, "scopes": {}}
        setattr(graph, "_module_scope_cache", cache)
    scopes = cache["scopes"]
    if scope in scopes:
        return scopes[scope]
    longest_module = next(
        (module for module in cache["modules"] if scope == module or scope.startswith(module + ".")),
        "",
    )
    if longest_module:
        scopes[scope] = longest_module
    else:
        scopes[scope] = scope.split(".")[0]
    return scopes[scope]
