"""Evidence-oriented resolution coverage and unknown-region metrics."""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import Any

from impact_engine.models import GraphDocument


_NON_ACTIONABLE_TERMINALS = {
    "print", "len", "str", "int", "float", "bool", "list", "dict", "set",
    "tuple", "isinstance", "getattr", "hasattr", "sorted", "enumerate", "range",
    "json.dumps", "json.loads", "path.exists", "path.is_file", "path.is_dir",
    "logger.info", "logger.debug", "logger.warning", "logger.error",
}


def build_resolution_coverage(graph: GraphDocument) -> dict[str, Any]:
    """Build a reproducible coverage report from the resolved graph."""
    call_nodes = [node for node in graph.nodes if node.kind == "CALL_EXPR"]
    outgoing = {}
    for edge in graph.edges:
        outgoing.setdefault(edge.from_node, []).append(edge)
    by_language: dict[str, dict[str, int]] = {}
    unresolved_reasons = Counter()
    pattern_counts = Counter()
    support_resolved_ids = {
        str(item.get("region_target_id"))
        for item in graph.metadata.get("unknown_regions", {}).get("resolved_by_support_pack", [])
    }

    for node in call_nodes:
        language = _node_language(node)
        bucket = by_language.setdefault(language, Counter())
        bucket["callsites_total"] += 1
        call_name = str(node.properties.get("call_name") or node.name or "")
        terminal = _is_terminal(call_name)
        if terminal:
            bucket["external_terminal"] += 1
            # Terminal calls are a disjoint non-actionable category.
            pattern_counts[_pattern(node)] += 1
            continue
        edges = outgoing.get(node.id, [])
        semantic = [edge for edge in edges if edge.kind in {"CALLS", "RESOLVES_TO", "HTTP_CALLS", "MATCHES_ENDPOINT"}]
        if node.id in support_resolved_ids:
            bucket["resolved_inferred"] += 1
            bucket["support_pack_resolved"] += 1
            bucket["eligible_for_resolution"] += 1
            continue
        if semantic:
            if any(edge.source == "EXTRACTED" or edge.properties.get("resolution_status") == "resolved_exact" for edge in semantic):
                bucket["resolved_exact"] += 1
            else:
                bucket["resolved_inferred"] += 1
        else:
            bucket["actionable_unresolved"] += 1
            taxonomy = "unresolved_receiver" if not node.properties.get("receiver") else "unresolved_call_target"
            unresolved_reasons[taxonomy] += 1
            pattern_counts[_pattern(node)] += 1
        bucket["eligible_for_resolution"] += 1

    for bucket in by_language.values():
        bucket.setdefault("resolved_exact", 0)
        bucket.setdefault("resolved_inferred", 0)
        bucket.setdefault("ambiguous", 0)
        bucket.setdefault("external_terminal", 0)
        bucket.setdefault("unsupported_dynamic", 0)
        bucket.setdefault("actionable_unresolved", 0)
        bucket.setdefault("support_pack_resolved", 0)
        bucket = dict(bucket)

    regions = graph.metadata.get("unknown_regions", {}).get("regions", [])
    suspicious = sum(1 for region in regions if region.get("kind") == "suspicious_edge")
    return {
        "status": "ok",
        "by_language": {language: _with_rates(dict(values)) for language, values in sorted(by_language.items())},
        "totals": {
            "callsites_total": len(call_nodes),
            "actionable_unresolved": sum(item.get("actionable_unresolved", 0) for item in by_language.values()),
            "external_terminal": sum(item.get("external_terminal", 0) for item in by_language.values()),
            "suspicious_edges": suspicious,
            "eligible_callsites": sum(item.get("eligible_for_resolution", 0) for item in by_language.values()),
            "resolved_exact": sum(item.get("resolved_exact", 0) for item in by_language.values()),
            "resolved_inferred": sum(item.get("resolved_inferred", 0) for item in by_language.values()),
            "support_pack_resolved": sum(item.get("support_pack_resolved", 0) for item in by_language.values()),
        },
        "unresolved_breakdown": dict(unresolved_reasons),
        "accounting": _accounting(by_language, len(call_nodes)),
        "top_patterns": [
            {"fingerprint": key, "count": count}
            for key, count in pattern_counts.most_common(20)
        ],
    }


def _accounting(by_language: dict[str, Counter], total: int) -> dict[str, Any]:
    parts = {key: sum(item.get(key, 0) for item in by_language.values()) for key in (
        "resolved_exact", "resolved_inferred", "external_terminal", "ambiguous",
        "actionable_unresolved", "non_actionable_unresolved", "unsupported_dynamic",
    )}
    accounted = sum(parts.values())
    return {"total_callsites": total, "accounted_callsites": accounted, "difference": total - accounted, "valid": accounted == total, "parts": parts}


def _with_rates(values: dict[str, int]) -> dict[str, Any]:
    eligible = values.get("eligible_for_resolution", 0)
    values["resolution_rate"] = round((values.get("resolved_exact", 0) + values.get("resolved_inferred", 0)) / eligible, 4) if eligible else 0.0
    values["actionable_unresolved_rate"] = round(values.get("actionable_unresolved", 0) / eligible, 4) if eligible else 0.0
    return values


def _node_language(node: Any) -> str:
    file_name = str((node.properties or {}).get("file") or "")
    suffix = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else "unknown"
    return {"py": "python", "js": "javascript", "jsx": "javascript", "ts": "typescript", "tsx": "typescript", "go": "go", "java": "java"}.get(suffix, "unknown")


def _is_terminal(call_name: str) -> bool:
    normalized = call_name.strip().lower()
    return normalized in _NON_ACTIONABLE_TERMINALS or normalized.split(".")[-1] in {"info", "debug", "warning", "error"}


def _pattern(node: Any) -> str:
    props = node.properties or {}
    raw = "|".join(str(props.get(key) or "") for key in ("call_name", "receiver", "method", "scope"))
    raw = re.sub(r"\d+", "#", raw)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
