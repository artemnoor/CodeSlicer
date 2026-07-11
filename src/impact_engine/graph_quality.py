"""Deterministic graph quality checks and fingerprints.

These checks are annotations only: they never invent semantic edges.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from impact_engine.models import GraphDocument, Node


def annotate_edge_contracts(graph: GraphDocument) -> GraphDocument:
    """Add provenance dimensions at the resolved-graph boundary."""
    classes = {
        "EXTRACTED": "static_proven", "INFERRED": "static_inferred",
        "SUPPORT_PACK": "support_pack_rule", "EXTERNAL_TOOL": "external_observation",
        "RUNTIME_CONFIRMED": "static_inferred", "AI_PROPOSED": "ai_proposed", "MANUAL": "manual",
    }
    stable_by_legacy = {node.id: node.properties.get("stable_id") for node in graph.nodes}
    for edge in graph.edges:
        edge.properties.setdefault("resolution_status", "proposal" if edge.source == "AI_PROPOSED" else "resolved")
        edge.properties.setdefault("evidence_class", classes.get(edge.source, "unknown"))
        edge.properties.setdefault("validation_status", "runtime_observed" if edge.source == "RUNTIME_CONFIRMED" else "not_validated")
        observations = edge.properties.setdefault("observations", [])
        observation = {"source": edge.source, "confidence": edge.confidence}
        if observation not in observations:
            observations.append(observation)
        if stable_by_legacy.get(edge.from_node):
            edge.properties.setdefault("canonical_from", stable_by_legacy[edge.from_node])
        if stable_by_legacy.get(edge.to_node):
            edge.properties.setdefault("canonical_to", stable_by_legacy[edge.to_node])
    return graph


def validate_edge_contract(edge: Any) -> list[str]:
    """Validate orthogonal resolution/evidence/validation dimensions."""
    props = edge.properties or {}
    errors: list[str] = []
    resolution = str(props.get("resolution_status", ""))
    evidence = str(props.get("evidence_class", ""))
    validation = str(props.get("validation_status", ""))
    if resolution == "unresolved" and validation == "runtime_observed":
        errors.append("unresolved edge cannot be runtime_observed")
    if evidence == "static_proven" and resolution == "ambiguous":
        errors.append("static_proven edge cannot be ambiguous")
    if edge.source == "AI_PROPOSED" and validation == "runtime_observed" and not props.get("validated_hypothesis"):
        errors.append("AI proposal lacks validation gate provenance")
    if validation == "runtime_observed" and not (props.get("runtime_observation") or edge.source == "RUNTIME_CONFIRMED"):
        errors.append("runtime_observed edge lacks runtime observation")
    if resolution == "unresolved" and float(edge.confidence) >= 1.0:
        errors.append("unresolved edge cannot have confidence 1.0")
    return errors


def graph_fingerprint(graph: GraphDocument) -> str:
    """Return a stable content hash independent of list ordering."""
    payload = graph.to_dict()
    payload["metadata"] = {}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def graph_quality_report(graph: GraphDocument) -> dict[str, Any]:
    node_ids = {node.id for node in graph.nodes}
    aliases = _node_aliases(graph)
    dangling = []
    duplicate_ids = []
    seen_ids: set[str] = set()
    for node in graph.nodes:
        if node.id in seen_ids:
            duplicate_ids.append(node.id)
        seen_ids.add(node.id)
    for edge in graph.edges:
        missing = [node_id for node_id in (edge.from_node, edge.to_node) if node_id not in node_ids and node_id not in aliases]
        if missing:
            dangling.append({"edge_id": edge.id, "missing_nodes": missing})
    orphan_nodes = sorted(node_id for node_id in node_ids if not any(
        edge.from_node == node_id or edge.to_node == node_id for edge in graph.edges
    ))
    return {
        "status": "warning" if dangling or duplicate_ids else "ok",
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "orphan_node_count": len(orphan_nodes),
        "orphan_nodes": orphan_nodes[:100],
        "dangling_edge_count": len(dangling),
        "dangling_edges": dangling[:100],
        "duplicate_node_id_count": len(duplicate_ids),
        "duplicate_node_ids": sorted(set(duplicate_ids))[:100],
        "fingerprint": graph_fingerprint(graph),
    }


def annotate_graph_quality(graph: GraphDocument) -> GraphDocument:
    graph.metadata["graph_quality"] = graph_quality_report(graph)
    graph.metadata["graph_fingerprint"] = graph.metadata["graph_quality"]["fingerprint"]
    return graph


def run_quality_gate(graph: GraphDocument, stage: str) -> dict[str, Any]:
    """Run stage-specific, non-mutating quality checks."""
    node_ids = {node.id for node in graph.nodes}
    dangling = sum(1 for edge in graph.edges if edge.from_node not in node_ids or edge.to_node not in node_ids)
    missing_evidence = sum(1 for edge in graph.edges if edge.source in {"INFERRED", "SUPPORT_PACK", "AI_PROPOSED"} and not edge.evidence)
    invalid_confidence = sum(1 for edge in graph.edges if not 0.0 <= edge.confidence <= 1.0)
    invalid_status = sum(1 for edge in graph.edges if validate_edge_contract(edge))
    result = {
        "stage": stage,
        "status": "ok" if not dangling and not missing_evidence and not invalid_confidence and not invalid_status else "warning",
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "dangling_edges": dangling,
        "missing_evidence": missing_evidence,
        "invalid_confidence": invalid_confidence,
        "invalid_status_combinations": invalid_status,
    }
    graph.metadata.setdefault("quality_gates", []).append(result)
    return result


def apply_quality_guard(graph: GraphDocument) -> GraphDocument:
    """Quarantine edges that reference no graph node.

    The edge is retained for diagnostics/provenance, but marked suspicious so
    impact traversal cannot present it as confirmed or likely impact.
    """
    node_ids = {node.id for node in graph.nodes}
    aliases = _node_aliases(graph)
    quarantined = 0
    for edge in graph.edges:
        missing = [node_id for node_id in (edge.from_node, edge.to_node) if node_id not in node_ids and node_id not in aliases]
        if missing:
            for node_id in missing:
                placeholder = Node(
                    id=node_id,
                    kind=_placeholder_kind(node_id),
                    name=node_id,
                    properties={
                        "placeholder": True,
                        "resolution_status": "unresolved_endpoint",
                        "quality_warning": "created by graph quality guard; no extracted declaration",
                    },
                )
                graph.add_node(placeholder)
                node_ids.add(node_id)
            warnings = list(edge.properties.get("warnings", []) or [])
            warning = f"dangling edge: missing endpoint(s) {', '.join(missing)}"
            if warning not in warnings:
                warnings.append(warning)
            edge.properties["warnings"] = warnings
            edge.properties["status"] = "suspicious"
            edge.properties["quality_guard"] = "quarantined_dangling_endpoint"
            quarantined += 1
    graph.metadata["graph_quality_guard"] = {
        "status": "applied",
        "quarantined_edges": quarantined,
        "impact_policy": "dangling edges excluded from active impact traversal",
    }
    return graph


def _node_aliases(graph: GraphDocument) -> set[str]:
    """Return canonical symbol aliases represented by extractor-qualified IDs."""
    aliases: set[str] = set()
    prefixes = ("method:", "class:", "function:", "module:", "file:")
    for node in graph.nodes:
        aliases.add(node.id)
        if node.name:
            aliases.add(str(node.name))
        for prefix in prefixes:
            if node.id.startswith(prefix):
                remainder = node.id[len(prefix):]
                if ":" in remainder:
                    aliases.add(remainder.split(":", 1)[0])
                aliases.add(remainder)
    return aliases


def _placeholder_kind(node_id: str) -> str:
    value = str(node_id)
    if value.startswith("module:"):
        return "MODULE"
    if value.startswith("class:"):
        return "CLASS"
    if value.startswith("method:"):
        return "METHOD"
    if value.startswith("HTTP "):
        return "ROUTE"
    if value.startswith("file:"):
        return "FILE"
    if value.startswith("react") or value in {"fastapi", "fetch", "JSON.stringify"}:
        return "EXTERNAL_LIBRARY"
    return "FUNCTION"
