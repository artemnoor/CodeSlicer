"""Optional Graphify adapter implementation. Stage 11."""
import json
from pathlib import Path
from typing import Any, Dict
from impact_engine.models import GraphDocument
from impact_engine.normalization import normalize_external_graph
from impact_engine.graph_identity import stable_symbol_id


def from_graphify_json(data: Dict[str, Any]) -> GraphDocument:
    if "links" in data or any(
        "source" in edge and "target" in edge
        for edge in data.get("edges", []) or []
    ):
        return normalize_graphify_json(data)
    graph = normalize_external_graph(data, source_name="graphify")
    if graph.metadata is None:
        graph.metadata = {}
    graph.metadata["adapter"] = "graphify"
    return graph


def from_graphify_file(path: str | Path) -> GraphDocument:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    return from_graphify_json(data)


def is_graphify_available() -> bool:
    try:
        import graphify
        return True
    except ImportError:
        return False


def normalize_graphify_json(graphify_json: dict, project_root: str = ".") -> GraphDocument:
    from impact_engine.models import NODE_KINDS, EDGE_KINDS
    
    nodes = []
    for gn in graphify_json.get("nodes", []):
        nid = gn.get("id") or gn.get("key")
        if not nid:
            nid = stable_symbol_id(
                project_root,
                str(gn.get("source_file") or gn.get("file") or "external"),
                str(gn.get("name") or gn.get("label") or "anonymous"),
                str(gn.get("kind") or gn.get("type") or "FUNCTION").upper(),
            )
        if not nid:
            continue
        gkind = gn.get("kind") or gn.get("type") or gn.get("label") or "FUNCTION"
        gkind = str(gkind).upper()
        if gkind not in NODE_KINDS:
            gkind = "FUNCTION"
        name = gn.get("name") or gn.get("label") or nid
        nodes.append({
            "id": nid,
            "kind": gkind,
            "name": name,
            "properties": {
                **dict(gn.get("properties", {}) or {}),
                "external_source_file": gn.get("source_file") or gn.get("file"),
                "external_source_location": gn.get("source_location"),
                "external_tool": "graphify",
            }
        })
        
    edges = []
    raw_edges = graphify_json.get("edges") or graphify_json.get("links") or []
    node_ids = {item["id"] for item in nodes}
    for ge in raw_edges:
        gfrom = ge.get("from") or ge.get("source")
        gto = ge.get("to") or ge.get("target")
        if not gfrom or not gto:
            continue
        gkind = ge.get("kind") or ge.get("type") or ge.get("label") or "CALLS"
        gkind = str(gkind).upper()
        if gkind not in EDGE_KINDS:
            gkind = "CALLS"
        edge_id = ge.get("id") or f"edge_{gfrom}_{gto}_{gkind}"
        raw_confidence = ge.get("confidence", 0.5)
        confidence = {
            "EXTRACTED": 0.60,
            "INFERRED": 0.55,
            "AMBIGUOUS": 0.35,
        }.get(str(raw_confidence).upper(), raw_confidence)
        try:
            confidence = min(0.70, max(0.0, float(confidence)))
        except (TypeError, ValueError):
            confidence = 0.50
        properties = dict(ge.get("properties", {}) or {})
        properties.update({
            "external_tool": "graphify",
            "external_relation": ge.get("relation") or ge.get("kind") or ge.get("type"),
            "external_source_file": ge.get("source_file"),
            "external_source_location": ge.get("source_location"),
        })
        if gfrom not in node_ids or gto not in node_ids:
            properties["quality_warning"] = "dangling_external_reference"
        edges.append({
            "id": edge_id,
            "kind": gkind,
            "from": gfrom,
            "to": gto,
            "source": "EXTERNAL_TOOL",
            "confidence": confidence,
            "properties": properties
        })
        
    normalized_data = {
        "nodes": nodes,
        "edges": edges
    }
    return from_graphify_json(normalized_data)
