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
    longest_module = ""
    for node in graph.nodes:
        if node.kind == "MODULE":
            mod_name = node.id
            if mod_name.startswith("module:"):
                mod_name = mod_name[7:]
            if scope == mod_name or scope.startswith(mod_name + "."):
                if len(mod_name) > len(longest_module):
                    longest_module = mod_name
    if longest_module:
        return longest_module
    return scope.split(".")[0]
