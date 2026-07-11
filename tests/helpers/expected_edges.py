import json
from pathlib import Path
from impact_engine.models import GraphDocument


def load_expected_edges(path: str | Path) -> dict:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Expected edges file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def edge_key(edge_or_dict) -> tuple:
    if hasattr(edge_or_dict, "from_node"):
        f = edge_or_dict.from_node
        t = edge_or_dict.to_node
        k = edge_or_dict.kind
    elif isinstance(edge_or_dict, dict):
        f = edge_or_dict.get("from") or edge_or_dict.get("from_node")
        t = edge_or_dict.get("to") or edge_or_dict.get("to_node")
        k = edge_or_dict.get("kind")
    else:
        raise TypeError("Must be Edge object or dict")
    return (str(f), str(t), str(k))


def graph_edge_set(graph: GraphDocument) -> set:
    return {edge_key(e) for e in graph.edges}


def compare_expected_edges(graph: GraphDocument, expected: dict) -> dict:
    graph_edges = graph_edge_set(graph)
    
    must_find = expected.get("must_find", [])
    should_find = expected.get("should_find", [])
    must_not_find = expected.get("must_not_find", [])
    
    must_find_found = []
    must_find_missing = []
    for e in must_find:
        if edge_key(e) in graph_edges:
            must_find_found.append(e)
        else:
            must_find_missing.append(e)
            
    should_find_found = []
    should_find_missing = []
    for e in should_find:
        if edge_key(e) in graph_edges:
            should_find_found.append(e)
        else:
            should_find_missing.append(e)
            
    must_not_find_absent = []
    must_not_find_present = []
    for e in must_not_find:
        if edge_key(e) in graph_edges:
            must_not_find_present.append(e)
        else:
            must_not_find_absent.append(e)
            
    return {
        "must_find_found": must_find_found,
        "must_find_missing": must_find_missing,
        "should_find_found": should_find_found,
        "should_find_missing": should_find_missing,
        "must_not_find_absent": must_not_find_absent,
        "must_not_find_present": must_not_find_present
    }
