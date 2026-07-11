"""Impact query and explain edge v2 implementation. Stage 16."""
import json
from typing import Optional, Dict, Any, List
from impact_engine.models import GraphDocument, Edge, Node
from impact_engine.edge_quality import bucket_edge_dicts, classify_edge_quality, edge_is_active_for_impact
from impact_engine.scoring import (
    ImpactScoringConfig,
    chain_confidence,
    chain_status,
    rank_impact_paths,
    scoring_explanation,
    token_saving_report,
)
from project_semantics_hygiene import GraphNodeAnnotation, group_nodes_by_semantic_role


def _path_status(edges: list[Edge]) -> str:
    statuses = []
    for edge in edges:
        status = str(edge.properties.get("validation_status") or edge.properties.get("evidence_class") or {
            "EXTRACTED": "static_proven",
            "RUNTIME_CONFIRMED": "runtime_observed",
        }.get(edge.source, "static_inferred"))
        if status in {"runtime_observed", "static_proven"}:
            statuses.append("confirmed")
        elif status in {"ai_proposed", "not_validated"}:
            statuses.append("likely")
        else:
            statuses.append("likely")
    if "likely" in statuses:
        return "likely"
    return "confirmed"


def node_to_dict(node) -> dict:
    return {
        "id": node.id,
        "name": getattr(node, "name", ""),
        "kind": node.kind,
        "properties": getattr(node, "properties", {}),
        "metadata": getattr(node, "metadata", {})
    }


def edge_to_dict(edge) -> dict:
    ev_list = []
    for ev in getattr(edge, "evidence", []):
        ev_list.append({
            "description": getattr(ev, "description", ""),
            "file": getattr(ev, "file", ""),
            "line": getattr(ev, "line", None),
            "source": getattr(ev, "source", "")
        })
    quality = classify_edge_quality(edge)
    support_pack_provenance = getattr(edge, "properties", {}).get("support_pack")
    return {
        "id": edge.id,
        "kind": edge.kind,
        "from": edge.from_node,
        "to": edge.to_node,
        "source": edge.source,
        "confidence": edge.confidence,
        "properties": getattr(edge, "properties", {}),
        "metadata": getattr(edge, "metadata", {}),
        "evidence": ev_list,
        "evidence_chain": ev_list,
        "quality": quality.to_dict(),
        "support_pack": support_pack_provenance,
    }


def impact_query(
    graph: Any,
    target: str = "",
    symbol: str | None = None,
    file_path: str | None = None,
    direction: str = "both",
    max_depth: int | None = None,
    min_confidence: float = 0.0,
    include_evidence: bool = True,
    scoring_config: dict | None = None,
    full_context_tokens: int | None = None,
    selected_context_tokens: int | None = None,
) -> dict:
    # 1. Parse GraphDocument if it is a dictionary
    if isinstance(graph, dict):
        graph = GraphDocument.from_json(json.dumps(graph))

    # 2. Determine target query string
    q_str = target
    if symbol:
        q_str = symbol
    elif file_path:
        q_str = file_path

    # 3. Match initial nodes
    matched_nodes = []
    for node in graph.nodes:
        if file_path:
            f = node.properties.get("file") or node.properties.get("path") or ""
            if (f and (file_path in f or f in file_path)) or (file_path in node.id):
                matched_nodes.append(node)
        elif symbol:
            if symbol in node.id or (node.name and symbol in node.name):
                matched_nodes.append(node)
        elif target:
            if node.id == target:
                matched_nodes.append(node)

    # Fallback to substring matching if only target was specified and no exact match found
    if not matched_nodes and target and not symbol and not file_path:
        for node in graph.nodes:
            if target in node.id or (node.name and target in node.name):
                matched_nodes.append(node)

    # 4. BFS Traversal setup
    queue = []
    visited_nodes = set()
    affected_nodes = []
    affected_edges = []
    explanation_chain = []
    impact_paths = []
    warnings = []

    # Seed queue with matched node IDs
    for n in matched_nodes:
        queue.append((n.id, 0, n.id, []))
        visited_nodes.add(n.id)

    # Always seed the queue with the query string itself to allow traversal on non-node symbols
    if q_str and q_str not in visited_nodes:
        queue.append((q_str, 0, q_str, []))
        visited_nodes.add(q_str)

    # Build adjacency lists
    out_adj = {}
    in_adj = {}
    for edge in graph.edges:
        if edge.confidence < min_confidence:
            continue
        if not edge_is_active_for_impact(edge):
            continue
        out_adj.setdefault(edge.from_node, []).append(edge)
        in_adj.setdefault(edge.to_node, []).append(edge)

    # BFS Traversal
    while queue:
        curr_id, depth, path_str, path_edges = queue.pop(0)

        if max_depth is not None and depth >= max_depth:
            continue

        next_edges = []
        if direction in ("downstream", "both"):
            next_edges.extend((e.to_node, e, "downstream") for e in out_adj.get(curr_id, []))
        if direction in ("upstream", "both"):
            next_edges.extend((e.from_node, e, "upstream") for e in in_adj.get(curr_id, []))

        for next_id, edge, dir_type in next_edges:
            if edge in affected_edges:
                continue

            affected_edges.append(edge)

            arrow = "->" if dir_type == "downstream" else "<-"
            new_path_str = f"{path_str} {arrow} ({edge.kind}, c={edge.confidence}) {arrow} {next_id}"

            if next_id not in visited_nodes:
                visited_nodes.add(next_id)
                queue.append((next_id, depth + 1, new_path_str, path_edges + [edge]))
                node_obj = graph._node_index.get(next_id) if isinstance(graph, GraphDocument) else next((node for node in graph.nodes if node.id == next_id), None)
                if not node_obj:
                    # Create placeholder symbol node
                    node_obj = Node(id=next_id, name=next_id, kind="FUNCTION")
                affected_nodes.append(node_obj)
                explanation_chain.append(new_path_str)
                full_path = path_edges + [edge]
                impact_paths.append({
                    "target": next_id,
                    "depth": depth + 1,
                    "status": _path_status(full_path),
                    "confidence": min((item.confidence for item in full_path), default=1.0),
                    "edges": [item.id for item in full_path],
                })

    # Group by kind
    grouped = {
        "files": [],
        "classes": [],
        "functions": [],
        "routes": [],
        "tests": [],
        "external_libraries": []
    }
    for node in affected_nodes:
        kind = node.kind.upper()
        node_id = node.id
        if kind == "FILE":
            grouped["files"].append(node_id)
        elif kind == "CLASS":
            grouped["classes"].append(node_id)
        elif kind in ("FUNCTION", "METHOD", "SYMBOL"):
            grouped["functions"].append(node_id)
        elif kind in ("ROUTE", "HTTP_ROUTE"):
            grouped["routes"].append(node_id)
        elif kind == "TEST":
            grouped["tests"].append(node_id)
        elif kind in ("EXTERNAL_LIBRARY", "SUPPORT_PACK", "LIBRARY"):
            grouped["external_libraries"].append(node_id)
        else:
            grouped.setdefault(kind.lower() + "s", []).append(node_id)

    affected_node_dicts = [node_to_dict(n) for n in affected_nodes]
    semantic_grouped = _semantic_groups_from_hygiene(graph, affected_node_dicts)
    for role, ids in semantic_grouped.items():
        grouped.setdefault(role, [])
        if role in {"routes", "tests", "external_libraries"}:
            for node_id in ids:
                if node_id not in grouped[role]:
                    grouped[role].append(node_id)

    # For backward-compatible return payload of old tests/CLI
    # we return upstream/downstream lists
    upstream_direct = sorted(list(set(e.from_node for e in affected_edges if e.to_node == q_str)))
    downstream_direct = sorted(list(set(e.to_node for e in affected_edges if e.from_node == q_str)))

    # Make empty results diagnosable. Imported/external graphs may represent a
    # query only as an edge endpoint rather than as a materialized node.
    matched_edge_endpoints = [
        edge for edge in graph.edges
        if q_str and q_str in {edge.from_node, edge.to_node}
    ]
    if matched_edge_endpoints and not affected_edges:
        warnings.append("query matched an edge endpoint but no active traversal edge")
    if matched_nodes and not affected_edges:
        isolated = True
        isolation_reason = "node_has_no_active_edges"
    elif not matched_nodes and not matched_edge_endpoints:
        isolated = False
        isolation_reason = "no_matching_node_or_edge_endpoint"
    else:
        isolated = False
        isolation_reason = None

    affected_edge_dicts = [edge_to_dict(e) for e in affected_edges]
    quality_buckets = bucket_edge_dicts(affected_edge_dicts)
    confirmed_impact_edges = quality_buckets["confirmed"]
    likely_impact_edges = quality_buckets["likely"]
    weak_impact_edges = quality_buckets["weak"]
    score_config = ImpactScoringConfig.from_dict(scoring_config)
    impact_ranking = rank_impact_paths(graph, impact_paths, score_config)
    scoring = scoring_explanation(score_config)
    context_efficiency = token_saving_report(full_context_tokens, selected_context_tokens)
    ranked_by_path = {
        (item["node_id"], item["distance"]): item for item in impact_ranking
    }
    for path in impact_paths:
        # Keep the existing weakest-edge confidence for compatibility, while
        # exposing the geometric-mean chain confidence separately.
        ranked = ranked_by_path.get((path.get("target"), int(path.get("depth", 0))))
        if ranked is None:
            continue
        path["chain_confidence"] = ranked["path_confidence"]
        path["chain_status"] = ranked["confidence_status"]

    return {
        "target": q_str,
        "matched_nodes": [node_to_dict(n) for n in matched_nodes],
        "affected_nodes": affected_node_dicts,
        "affected_edges": affected_edge_dicts,
        "grouped_by_kind": grouped,
        "grouped_by_semantic_role": semantic_grouped,
        "confirmed": confirmed_impact_edges,
        "likely": likely_impact_edges,
        "weak": weak_impact_edges,
        "suspicious": quality_buckets["suspicious"],
        "rejected": quality_buckets["rejected"],
        "not_resolved": quality_buckets["not_resolved"],
        "impact_sections": {
            "confirmed": confirmed_impact_edges,
            "likely": likely_impact_edges,
            "weak": weak_impact_edges,
            "suspicious": quality_buckets["suspicious"],
            "rejected": quality_buckets["rejected"],
            "not_resolved": quality_buckets["not_resolved"],
        },
        "explanation_chain": explanation_chain,
        "impact_paths": impact_paths,
        "impact_ranking": impact_ranking,
        "scoring": scoring,
        "context_efficiency": context_efficiency,
        "warnings": warnings,
        "isolated": isolated,
        "isolation_reason": isolation_reason,
        "query_diagnostics": {
            "matched_node_count": len(matched_nodes),
            "matched_edge_endpoint_count": len(matched_edge_endpoints),
            "active_edge_count": len(affected_edges),
            "isolated": isolated,
            "reason": isolation_reason,
        },
        # Backward compatibility fields:
        "upstream": upstream_direct,
        "downstream": downstream_direct,
        "edges": affected_edge_dicts
    }


def _semantic_groups_from_hygiene(graph: GraphDocument, nodes: list[dict]) -> dict[str, list[str]]:
    hygiene = graph.metadata.get("project_hygiene") if isinstance(graph.metadata, dict) else None
    if not isinstance(hygiene, dict):
        return {}
    annotations = []
    for item in hygiene.get("node_annotations", []) or []:
        try:
            annotations.append(GraphNodeAnnotation.from_dict(item))
        except Exception:
            continue
    if not annotations:
        return {}
    grouped = group_nodes_by_semantic_role(nodes, annotations)
    return {role: [str(node.get("id", "")) for node in grouped_nodes] for role, grouped_nodes in grouped.items()}


def explain_edge(graph: Any, from_symbol: str, to_symbol: str, kind: Optional[str] = None) -> dict:
    if isinstance(graph, dict):
        graph = GraphDocument.from_json(json.dumps(graph))

    matching_edge = None
    for edge in graph.edges:
        if edge.from_node == from_symbol and edge.to_node == to_symbol:
            if kind is None or edge.kind == kind:
                matching_edge = edge
                break

    if matching_edge:
        ev_list = []
        for ev in getattr(matching_edge, "evidence", []):
            ev_list.append({
                "description": getattr(ev, "description", ""),
                "file": getattr(ev, "file", ""),
                "line": getattr(ev, "line", None),
                "source": getattr(ev, "source", "")
            })

        rule_attribution = matching_edge.properties.get("support_pack")
        rule_id = matching_edge.properties.get("support_pack_rule_id")
        rules_used = [rule_id] if rule_id else []

        reasoning = []
        if matching_edge.source == "INFERRED":
            reasoning.append("Edge was inferred via precision resolver resolution logic.")
            if rule_id:
                reasoning.append(f"Applied support pack rule: {rule_id}")
        elif rule_attribution:
            reasoning.append(f"Edge was produced by support pack rule: {rule_id or rule_attribution.get('rule_id', '')}.")
        else:
            reasoning.append(f"Edge was directly extracted from AST (extractor: {matching_edge.properties.get('extractor_id', 'unknown')}).")

        warnings = []
        quality = classify_edge_quality(matching_edge)
        if matching_edge.confidence < 0.70:
            warnings.append("Low confidence edge (confidence < 0.70). Use with caution.")
        warnings.extend(quality.warnings)

        edge_dict = edge_to_dict(matching_edge)

        return {
            "found": True,
            "edge": edge_dict,
            "confidence": matching_edge.confidence,
            "source": matching_edge.source,
            "quality": quality.to_dict(),
            "status": quality.status,
            "evidence_chain": ev_list,
            "evidence": ev_list,  # Backward compatible alias
            "reasoning_steps": reasoning,
            "support_pack_rules_used": rules_used,
            "rule_attribution": rule_attribution,
            "warnings": warnings
        }

    return {
        "found": False,
        "from": from_symbol,
        "to": to_symbol,
        "kind": kind,
        "edge": None,
        "confidence": 0.0,
        "source": "UNKNOWN",
        "evidence_chain": [],
        "evidence": [],
        "reasoning_steps": [f"No edge found from {from_symbol} to {to_symbol}."],
        "support_pack_rules_used": [],
        "rule_attribution": None,
        "warnings": [f"No edge connects {from_symbol} and {to_symbol}."]
    }


def impact_path(graph: Any, from_symbol: str, to_symbol: str, max_depth: int = 20) -> dict:
    """Return the highest-confidence directed path between two graph nodes."""
    if isinstance(graph, dict):
        graph = GraphDocument.from_json(json.dumps(graph))
    adjacency: dict[str, list[Edge]] = {}
    for edge in graph.edges:
        if edge_is_active_for_impact(edge):
            adjacency.setdefault(edge.from_node, []).append(edge)
    queue: list[tuple[str, list[Edge]]] = [(from_symbol, [])]
    visited = {from_symbol}
    while queue:
        current, path = queue.pop(0)
        if current == to_symbol:
            return {
                "found": True,
                "from": from_symbol,
                "to": to_symbol,
                "nodes": [from_symbol] + [edge.to_node for edge in path],
                "edges": [edge_to_dict(edge) for edge in path],
                "confidence": min((edge.confidence for edge in path), default=1.0),
                "chain_confidence": chain_confidence(edge.confidence for edge in path),
                "chain_status": chain_status(chain_confidence(edge.confidence for edge in path)),
                "path_status": _path_status(path),
                "evidence_chain": [ev for edge in path for ev in edge_to_dict(edge)["evidence_chain"]],
            }
        if len(path) >= max_depth:
            continue
        for edge in sorted(adjacency.get(current, []), key=lambda item: (-item.confidence, item.to_node)):
            if edge.to_node not in visited:
                visited.add(edge.to_node)
                queue.append((edge.to_node, path + [edge]))
    return {"found": False, "from": from_symbol, "to": to_symbol, "nodes": [], "edges": [], "confidence": 0.0, "evidence_chain": []}
