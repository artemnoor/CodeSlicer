"""Unified implementations for inspect, investigate and CI.

The mode layer is deliberately an orchestration layer.  Graph construction,
ranking, test selection, edge quality and runtime tracing remain in their
existing modules and are called from here rather than copied.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from impact_engine.contracts import (
    CI_POLICY_SCHEMA_VERSION,
    MODE_SCHEMA_VERSION,
    action,
    attach_mode_contract,
    mode_status,
)
from impact_engine.edge_quality import classify_edge_quality, edge_is_active_for_impact
from impact_engine.graph_quality import graph_quality_report
from impact_engine.impact import impact_query
from impact_engine.models import GraphDocument, Node
from impact_engine.review import (
    SCHEMA_VERSION as LEGACY_REVIEW_SCHEMA_VERSION,
    _coverage,
    _coverage_warnings,
    _resolve_graph,
)
from impact_engine.unknown_regions import analyze_unknown_regions


SUPPRESSED_KINDS = {"ASSIGNMENT", "CALL_EXPR", "EXTERNAL_LIBRARY", "SUPPORT_PACK"}
GENERATED_MARKERS = ("/generated/", "\\generated\\", ".generated.", "/vendor/", "\\vendor\\", "/bin/", "\\bin/", "/obj/", "\\obj\\")
BOUNDARY_KINDS = {"ROUTE"}
BOUNDARY_CATEGORIES = {"api", "public_api", "database", "schema", "frontend_backend", "queue", "public"}


def build_inspect_report(
    project_path: str,
    *,
    entity: str,
    graph: GraphDocument | None = None,
    graph_path: str | Path | None = None,
    refresh: str = "never",
    max_context: int = 12,
) -> dict[str, Any]:
    started = time.perf_counter()
    root = _project_root(project_path)
    warnings: list[str] = []
    graph, freshness = _resolve_graph(root, graph, refresh, warnings, graph_path=graph_path)
    resolved, candidates = _resolve_entity(graph, entity)
    if resolved is None:
        status = "needs_selection" if candidates else "not_found"
        payload = {
            "schema_version": MODE_SCHEMA_VERSION,
            "status": status,
            "project": str(root),
            "query": entity,
            "resolved_entity": None,
            "candidates": [_node_dict(node) for node in candidates],
            "entity_metadata": {},
            "direct_upstream": [],
            "direct_downstream": [],
            "why_affected": [],
            "why_not_confirmed": ["symbol is ambiguous; select a candidate ID" if candidates else "no graph entity matched the query"],
            "confidence": {"level": "unknown", "value": 0.0, "provenance": []},
            "linked_tests": [],
            "linked_routes": [],
            "coverage": [],
            "graph_freshness": freshness,
            "warnings": sorted(set(warnings)),
            "truncated": False,
            "context_budget": {"max_items": max_context, "used_items": 0},
        }
        items = [action("refresh-graph", "refresh_graph", "Refresh graph", payload={"project_path": str(root)})]
        if candidates:
            items.append(action("inspect-candidate", "inspect_entity", "Select an entity candidate", payload={"candidates": [node.id for node in candidates]}))
        return attach_mode_contract(payload, "inspect", actions=items)

    entity_dict = _node_dict(resolved)
    entity_file = _node_file(resolved)
    coverage = _coverage(graph, {entity_file} if entity_file else set())
    adjacent = _inspect_adjacent_edges(graph, resolved)
    upstream = [item for item in adjacent if item["direction"] == "upstream"]
    downstream = [item for item in adjacent if item["direction"] == "downstream"]
    compact_upstream = upstream[:max_context]
    compact_downstream = downstream[:max_context]
    truncated = len(compact_upstream) < len(upstream) or len(compact_downstream) < len(downstream)
    all_edges = compact_upstream + compact_downstream
    provenance = [entry["edge"]["source"] for entry in all_edges]
    confidence_values = [float(entry["edge"].get("confidence", 0.0)) for entry in all_edges]
    why_affected = [
        {"direction": item["direction"], "edge": item["edge"], "claim": _edge_claim(item["edge"], item["direction"])}
        for item in all_edges
        if item["quality"]["status"] in {"confirmed", "likely", "weak"}
    ]
    why_not_confirmed = [
        {"edge_id": item["edge"]["id"], "reason": "; ".join(item["quality"]["warnings"] or item["quality"]["reasons"])}
        for item in all_edges
        if item["quality"]["status"] not in {"confirmed", "likely"}
    ]
    linked_tests, linked_routes = _linked_boundary_nodes(graph, resolved.id)
    incomplete = any(item["status"] == "unsupported" for item in coverage) or bool(graph.metadata.get("incomplete"))
    if truncated:
        warnings.append("inspect context truncated to the compact context budget")
    warnings.extend(_coverage_warnings(coverage))
    payload = {
        "schema_version": MODE_SCHEMA_VERSION,
        "status": mode_status(stale=bool(freshness.get("stale")), incomplete=incomplete),
        "project": str(root),
        "query": entity,
        "resolved_entity": entity_dict,
        "entity_metadata": dict(resolved.properties),
        "direct_upstream": [item["edge"] for item in compact_upstream],
        "direct_downstream": [item["edge"] for item in compact_downstream],
        "why_affected": why_affected,
        "why_not_confirmed": why_not_confirmed or (["no direct evidence-bearing edge was found"] if not all_edges else []),
        "confidence": {
            "level": _confidence_level(min(confidence_values, default=0.0)),
            "value": round(min(confidence_values, default=0.0), 4),
            "provenance": sorted(set(provenance)),
        },
        "linked_tests": linked_tests,
        "linked_routes": linked_routes,
        "coverage": coverage,
        "graph_freshness": freshness,
        "warnings": sorted(set(warnings)),
        "truncated": truncated,
        "context_budget": {"max_items": max_context, "used_items": len(all_edges), "total_items": len(upstream) + len(downstream)},
        "cache": {"status": "not_cached", "cache_key": _mode_cache_key("inspect", graph, entity, {"max_context": max_context})},
        "analysis_seconds": round(time.perf_counter() - started, 6),
    }
    items = [
        action("investigate-entity", "investigate_entity", "Investigate this entity", payload={"project_path": str(root), "entity": resolved.id}),
        action("refresh-graph", "refresh_graph", "Refresh graph", payload={"project_path": str(root)}),
        action("view-coverage", "view_coverage", "View coverage", payload={"coverage": coverage}),
    ]
    for item in all_edges[:5]:
        items.append(action(
            f"explain-{item['edge']['id']}", "explain_edge", "Explain edge",
            payload={"from": item["edge"]["from"], "to": item["edge"]["to"], "kind": item["edge"]["kind"]},
        ))
    if entity_file:
        items.append(action("open-entity-file", "open_file", "Open entity file", payload={"file": entity_file, "line": resolved.properties.get("line")}))
    return attach_mode_contract(payload, "inspect", actions=items)


def build_investigate_report(
    project_path: str,
    *,
    entity: str,
    direction: str = "both",
    depth: int = 8,
    graph: GraphDocument | None = None,
    graph_path: str | Path | None = None,
    refresh: str = "never",
    runtime_validate: bool = False,
    max_nodes: int = 500,
    max_edges: int = 1000,
) -> dict[str, Any]:
    root = _project_root(project_path)
    if direction not in {"upstream", "downstream", "both"}:
        raise ValueError("direction must be upstream, downstream or both")
    if depth < 0 or depth > 100:
        raise ValueError("depth must be between 0 and 100")
    warnings: list[str] = []
    graph, freshness = _resolve_graph(root, graph, refresh, warnings, graph_path=graph_path)
    resolved, candidates = _resolve_entity(graph, entity)
    if resolved is None:
        status = "needs_selection" if candidates else "not_found"
        payload = {"schema_version": MODE_SCHEMA_VERSION, "status": status, "project": str(root), "query": entity, "resolved_entity": None, "candidates": [_node_dict(node) for node in candidates], "graph_freshness": freshness, "coverage": [], "warnings": warnings, "truncated": False, "max_depth": depth, "visited_nodes": 0, "visited_edges": 0, "full_bounded_impact_paths": [], "edges": [], "graph_integrity": graph_quality_report(graph), "unresolved_regions": [], "support_packs": [], "runtime_validation": {"status": "not_requested", "requires_explicit_flag": True}}
        return attach_mode_contract(payload, "investigate", actions=[action("refresh-graph", "refresh_graph", "Refresh graph", payload={"project_path": str(root)})])

    result = impact_query(
        graph,
        target=resolved.id,
        direction=direction,
        max_depth=depth,
        min_confidence=0.0,
        max_nodes=max_nodes,
        max_edges=max_edges,
    )
    entity_file = _node_file(resolved)
    coverage = _coverage(graph, {entity_file} if entity_file else set())
    unknown = analyze_unknown_regions(graph)
    related_unknown = [region for region in unknown.get("regions", []) if _region_related(region, resolved, result)]
    runtime_result: dict[str, Any]
    if runtime_validate:
        try:
            from impact_engine.runtime_trace import run_runtime_trace_boost
            runtime_result = run_runtime_trace_boost(str(root), graph=graph)
        except Exception as exc:
            runtime_result = {"status": "failed", "error": str(exc), "explicit": True}
            warnings.append(f"runtime validation failed: {exc}")
    else:
        runtime_result = {"status": "not_requested", "requires_explicit_flag": True, "explicit": False}
    warnings.extend(_coverage_warnings(coverage))
    warnings.extend(result.get("warnings", []))
    traversal = result.get("traversal", {})
    payload = {
        "schema_version": MODE_SCHEMA_VERSION,
        "status": mode_status(stale=bool(freshness.get("stale")), incomplete=bool(coverage and coverage[0]["status"] == "unsupported")),
        "project": str(root),
        "query": entity,
        "resolved_entity": _node_dict(resolved),
        "direction": direction,
        "max_depth": depth,
        "full_bounded_impact_paths": result.get("impact_paths", []),
        "edges": result.get("affected_edges", []),
        "nodes": result.get("affected_nodes", []),
        "graph_integrity": graph_quality_report(graph),
        "unresolved_regions": related_unknown[:max_nodes],
        "unknown_region_summary": {"total": len(related_unknown), "policy": unknown.get("policy")},
        "support_packs": _support_pack_activation(graph),
        "runtime_validation": runtime_result,
        "truncated": bool(traversal.get("truncated")),
        "truncation": traversal,
        "visited_nodes": int(traversal.get("visited_nodes", len(result.get("affected_nodes", [])) + 1)),
        "visited_edges": int(traversal.get("visited_edges", len(result.get("affected_edges", [])))),
        "coverage": coverage,
        "graph_freshness": freshness,
        "warnings": sorted(set(warnings)),
        "cache": {"status": "not_cached", "cache_key": _mode_cache_key("investigate", graph, entity, {"direction": direction, "depth": depth, "runtime_validate": runtime_validate, "max_nodes": max_nodes, "max_edges": max_edges})},
    }
    items = [
        action("inspect-entity", "inspect_entity", "Inspect resolved entity", payload={"project_path": str(root), "entity": resolved.id}),
        action("refresh-graph", "refresh_graph", "Refresh graph", payload={"project_path": str(root)}),
        action("view-coverage", "view_coverage", "View coverage", payload={"coverage": coverage}),
    ]
    for edge in payload["edges"][:10]:
        items.append(action(f"explain-{edge['id']}", "explain_edge", "Explain edge", payload={"from": edge["from"], "to": edge["to"], "kind": edge["kind"]}))
    if not runtime_validate:
        items.append(action("runtime-validate", "investigate_entity", "Run runtime validation", payload={"project_path": str(root), "entity": resolved.id, "runtime_validate": True}))
    return attach_mode_contract(payload, "investigate", actions=items)


def build_ci_report(
    project_path: str,
    *,
    base: str | None = None,
    policy_path: str | Path | None = None,
    graph_path: str | Path | None = None,
    diff_text: str | None = None,
    refresh: str = "auto",
    run_tests: bool = False,
    test_command: list[str] | None = None,
) -> dict[str, Any]:
    root = _project_root(project_path)
    policy = load_ci_policy(policy_path)
    started = time.perf_counter()
    review = build_review_for_ci(root, base=base, graph_path=graph_path, diff_text=diff_text, refresh=refresh, run_tests=run_tests)
    graph = _load_graph_for_ci(root, graph_path, review)
    test_execution: dict[str, Any] = {"status": "not_requested", "explicit": False}
    warnings = list(review.get("warnings", []))
    if run_tests:
        try:
            from impact_engine.runtime_trace import run_runtime_trace_boost
            test_execution = run_runtime_trace_boost(str(root), graph=graph, test_command=test_command)
            test_execution["explicit"] = True
        except Exception as exc:
            test_execution = {"status": "failed", "error": str(exc), "explicit": True, "exit_code": 1}
            warnings.append(f"required targeted test execution failed: {exc}")
    findings = _ci_findings(review, graph, test_execution)
    evaluation = evaluate_ci_policy(review, findings, policy, test_execution, elapsed_seconds=time.perf_counter() - started)
    payload = {
        "schema_version": MODE_SCHEMA_VERSION,
        "status": "failed" if evaluation["violations"] else ("advisory" if findings else "passed"),
        "project": str(root),
        "base": base,
        "review": review,
        "findings": findings,
        "policy": policy,
        "policy_evaluation": evaluation,
        "test_execution": test_execution,
        "format": "json",
        "exit_code": 1 if evaluation["violations"] else 0,
        "warnings": sorted(set(warnings)),
        "graph_freshness": review.get("graph_freshness", {}),
        "coverage": review.get("coverage", []),
        "cache": {"status": "derived_from_review", "cache_key": _mode_cache_key("ci", graph, base or "working-tree", {"policy": policy, "run_tests": run_tests})},
    }
    items = [
        action("inspect-ci-impact", "inspect_entity", "Inspect top impact", payload={"project_path": str(root), "entity": (review.get("top_impacts") or [{}])[0].get("entity_id")} , enabled=bool(review.get("top_impacts")), reason_disabled="no top impact was produced" if not review.get("top_impacts") else None),
        action("refresh-graph", "refresh_graph", "Refresh graph", payload={"project_path": str(root)}),
        action("view-coverage", "view_coverage", "View coverage", payload={"coverage": review.get("coverage", [])}),
    ]
    payload = attach_mode_contract(payload, "ci", actions=items)
    payload["analysis_seconds"] = round(time.perf_counter() - started, 6)
    return payload


def build_review_for_ci(root: Path, **kwargs: Any) -> dict[str, Any]:
    from impact_engine.review import build_review_report

    return build_review_report(
        str(root),
        base=kwargs.get("base"),
        graph_path=kwargs.get("graph_path"),
        diff_text=kwargs.get("diff_text"),
        refresh=kwargs.get("refresh", "auto"),
        run_tests="suggested",
    )


def load_ci_policy(path: str | Path | None) -> dict[str, Any]:
    defaults = {
        "schema_version": CI_POLICY_SCHEMA_VERSION,
        "fail_on_risk": None,
        "fail_on_incomplete_coverage": False,
        "fail_on_stale_graph": False,
        "require_evidence_for_top_impacts": False,
        "max_noise_ratio": 1.0,
        "max_review_seconds": None,
        "required_test_status": "advisory",
    }
    if not path:
        return defaults
    policy_file = Path(path).expanduser().resolve()
    if not policy_file.is_file():
        raise ValueError(f"policy file does not exist: {policy_file}")
    try:
        raw = json.loads(policy_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raw = _parse_simple_policy(policy_file.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("policy must be a JSON/YAML object")
    supplied_version = raw.get("schema_version") or raw.get("version")
    if supplied_version and supplied_version != CI_POLICY_SCHEMA_VERSION:
        raise ValueError(f"unsupported CI policy schema: {supplied_version}")
    defaults.update(raw)
    defaults["schema_version"] = CI_POLICY_SCHEMA_VERSION
    return defaults


def evaluate_ci_policy(review: dict[str, Any], findings: list[dict[str, Any]], policy: dict[str, Any], test_execution: dict[str, Any], *, elapsed_seconds: float) -> dict[str, Any]:
    violations: list[dict[str, Any]] = []
    risk = str((review.get("risk") or {}).get("level") or "UNKNOWN").upper()
    threshold = str(policy.get("fail_on_risk") or "").upper()
    levels = {"UNKNOWN": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
    if threshold in levels and levels.get(risk, 0) >= levels[threshold]:
        violations.append({"rule": "fail_on_risk", "reason": f"risk {risk} meets or exceeds {threshold}"})
    incomplete = any(item.get("status") == "unsupported" or (item.get("status") == "limited" and not item.get("review_usable")) for item in review.get("coverage", []))
    if policy.get("fail_on_incomplete_coverage") and incomplete:
        violations.append({"rule": "fail_on_incomplete_coverage", "reason": "changed coverage is incomplete or unsupported"})
    if policy.get("fail_on_stale_graph") and (review.get("graph_freshness") or {}).get("stale"):
        violations.append({"rule": "fail_on_stale_graph", "reason": "graph freshness is stale or unverified"})
    if policy.get("require_evidence_for_top_impacts"):
        missing = [item.get("entity_id") for item in review.get("top_impacts", []) if not (item.get("why") or {}).get("evidence_ids")]
        if missing:
            violations.append({"rule": "require_evidence_for_top_impacts", "reason": "top impacts lack evidence", "entities": missing})
    max_noise = policy.get("max_noise_ratio")
    if max_noise is not None:
        projection = review.get("review_projection") or {}
        suppressed = len(projection.get("suppressed_candidates", []) or [])
        produced = len(review.get("top_impacts", []) or []) + suppressed
        ratio = suppressed / produced if produced else 0.0
        if ratio > float(max_noise):
            violations.append({"rule": "max_noise_ratio", "reason": f"noise ratio {ratio:.4f} exceeds {float(max_noise):.4f}", "value": ratio})
    max_seconds = policy.get("max_review_seconds")
    if max_seconds is not None and elapsed_seconds > float(max_seconds):
        violations.append({"rule": "max_review_seconds", "reason": f"review took {elapsed_seconds:.3f}s", "value": elapsed_seconds})
    required = str(policy.get("required_test_status") or "advisory").lower()
    test_status = str(test_execution.get("status") or "not_requested").lower()
    if required not in {"", "advisory", "not_required"} and test_status != required:
        violations.append({"rule": "required_test_status", "reason": f"required status {required}, observed {test_status}"})
    return {"status": "failed" if violations else "passed", "violations": violations, "elapsed_seconds": round(elapsed_seconds, 6), "evaluated_rules": sorted(str(key) for key in policy if key != "schema_version")}


def to_sarif(report: dict[str, Any]) -> dict[str, Any]:
    results = []
    for finding in report.get("findings", []):
        level = finding.get("level", "warning").lower()
        result = {
            "ruleId": finding.get("rule_id", "codeslicer.finding"),
            "level": "error" if level in {"critical", "high"} else ("warning" if level == "warning" else "note"),
            "message": {"text": finding.get("message", "CodeSlicer finding")},
            "properties": {"mode": "ci", "confidence": finding.get("confidence"), "localOnly": True},
        }
        file_name = finding.get("file")
        line = finding.get("line")
        if file_name:
            result["locations"] = [{"physicalLocation": {"artifactLocation": {"uri": str(file_name).replace("\\", "/")}, **({"region": {"startLine": int(line)}} if line else {})}}]
        results.append(result)
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{"tool": {"driver": {"name": "CodeSlicer", "version": MODE_SCHEMA_VERSION, "informationUri": "https://github.com/artemnoor/CodeSlicer"}}, "results": results}],
    }


def _ci_findings(review: dict[str, Any], graph: GraphDocument, test_execution: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    risk = review.get("risk") or {}
    if str(risk.get("level", "")).upper() in {"HIGH", "CRITICAL"}:
        findings.append({"rule_id": "codeslicer.risk", "level": str(risk.get("level")).lower(), "message": f"Review risk is {risk.get('level')}", "confidence": risk.get("confidence")})
    for item in review.get("coverage", []):
        if item.get("status") in {"unsupported", "limited"}:
            findings.append({"rule_id": "codeslicer.coverage", "level": "warning", "message": f"Coverage for {item.get('path')} is {item.get('status')}", "file": item.get("path"), "confidence": "low"})
    if (review.get("graph_freshness") or {}).get("stale"):
        findings.append({"rule_id": "codeslicer.stale-graph", "level": "warning", "message": "Graph is stale or externally unverified", "confidence": "low"})
    for item in _unresolved_boundary_findings(graph):
        findings.append(item)
    if test_execution.get("explicit") and str(test_execution.get("status")) not in {"ok", "passed"}:
        findings.append({"rule_id": "codeslicer.required-test", "level": "error", "message": "Explicit targeted test execution failed", "confidence": "observed"})
    return findings


def _unresolved_boundary_findings(graph: GraphDocument) -> list[dict[str, Any]]:
    node_by_id = {node.id: node for node in graph.nodes}
    results = []
    for edge in graph.edges:
        props = edge.properties or {}
        warning_text = " ".join(str(item) for item in props.get("warnings", []) or []).lower()
        unresolved = str(props.get("resolution_status", "")).lower() in {"unresolved", "ambiguous"} or "unresolved" in warning_text or "missing endpoint" in warning_text
        if not unresolved:
            continue
        endpoints = (node_by_id.get(edge.from_node), node_by_id.get(edge.to_node))
        boundary = next((node for node in endpoints if node and (node.kind in BOUNDARY_KINDS or str(node.properties.get("boundary_category", "")).lower() in BOUNDARY_CATEGORIES)), None)
        if boundary:
            results.append({"rule_id": "codeslicer.unresolved-boundary", "level": "warning", "message": f"Unresolved public/API/database boundary near {boundary.name}", "file": _node_file(boundary), "line": boundary.properties.get("line"), "confidence": "low"})
    return results


def _load_graph_for_ci(root: Path, graph_path: str | Path | None, review: dict[str, Any]) -> GraphDocument:
    path = Path(graph_path).expanduser().resolve() if graph_path else Path(str((review.get("graph_freshness") or {}).get("graph_path") or root / ".impact_engine" / "graph.json"))
    if path.is_file():
        return GraphDocument.from_json(path.read_text(encoding="utf-8"))
    return GraphDocument()


def _canonical_aliases(node: Node) -> set[str]:
    properties = node.properties or {}
    identity = properties.get("canonical_identity") or {}
    aliases = {str(node.id), str(node.name)}
    for key in ("qualname", "scope", "canonical_id", "symbol"):
        value = identity.get(key) if isinstance(identity, dict) else None
        if value:
            aliases.add(str(value))
        value = properties.get(key)
        if value:
            aliases.add(str(value))
    for prefix in ("method:", "function:", "class:", "module:"):
        if node.id.startswith(prefix):
            aliases.add(node.id[len(prefix):])
    return {item.strip() for item in aliases if item and item.strip()}


def _entity_priority(node: Node) -> tuple[int, int, str]:
    """Prefer canonical declarations over technical alias nodes."""
    technical = 1 if node.kind in SUPPRESSED_KINDS else 0
    canonical_prefix = 0 if node.id.startswith(("method:", "function:", "class:", "module:")) else 1
    return technical, canonical_prefix, node.id


def _prefer_canonical_entities(nodes: list[Node]) -> list[Node]:
    if not nodes:
        return nodes
    visible = [node for node in nodes if node.kind not in SUPPRESSED_KINDS]
    return sorted(visible or nodes, key=_entity_priority)


def _resolve_entity(graph: GraphDocument, query: str) -> tuple[Node | None, list[Node]]:
    value = str(query or "").strip()
    if not value:
        return None, []
    # Search/UI aliases may contain the qualname without the canonical
    # ``method:`` prefix. Resolve that alias before accepting an external
    # library node with the same text as its ID.
    alias_matches = [node for node in graph.nodes if value in _canonical_aliases(node) and node.kind not in SUPPRESSED_KINDS]
    if len(alias_matches) == 1:
        return alias_matches[0], alias_matches
    exact_id = [node for node in graph.nodes if node.id == value]
    if len(exact_id) == 1:
        return exact_id[0], exact_id
    exact_name = _prefer_canonical_entities([node for node in graph.nodes if node.name == value])
    if len(exact_name) == 1:
        return exact_name[0], exact_name
    if len(exact_name) > 1:
        return None, exact_name
    lowered = value.lower()
    candidates = _prefer_canonical_entities([node for node in graph.nodes if lowered and (lowered in node.id.lower() or lowered in node.name.lower())])
    return (candidates[0], candidates) if len(candidates) == 1 else (None, candidates)


def _adjacent_edges(graph: GraphDocument, node_id: str) -> list[dict[str, Any]]:
    result = []
    node_by_id = {node.id: node for node in graph.nodes}
    for edge in graph.edges:
        if node_id not in {edge.from_node, edge.to_node}:
            continue
        other_id = edge.to_node if edge.from_node == node_id else edge.from_node
        if not _context_visible(node_by_id.get(other_id)):
            continue
        quality = classify_edge_quality(edge).to_dict()
        direction = "upstream" if edge.to_node == node_id else "downstream"
        result.append({"direction": direction, "edge": edge.to_dict(), "quality": quality})
    return sorted(result, key=lambda item: (item["direction"], item["edge"]["id"]))


def _inspect_adjacent_edges(graph: GraphDocument, resolved: Node) -> list[dict[str, Any]]:
    """Return visible direct edges, materializing hidden call endpoints.

    Python extraction can preserve a precise METHOD node while attaching the
    inferred CALLS edge to canonical EXTERNAL_LIBRARY endpoints.  Inspect must
    expose the same direct call evidence as Investigate/Review, without
    leaking the technical endpoint nodes into the UI contract.
    """
    node_by_id = {node.id: node for node in graph.nodes}
    source_ids = [resolved.id]
    resolved_qualname = _canonical_qualname(resolved)
    for node in graph.nodes:
        if node.id != resolved.id and resolved_qualname and _canonical_qualname(node) == resolved_qualname and not _context_visible(node):
            source_ids.append(node.id)

    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def visible_targets(node_id: str) -> list[str]:
        target = node_by_id.get(node_id)
        if target is None:
            return []
        if _context_visible(target):
            return [target.id]
        qualname = _canonical_qualname(target)
        return [candidate.id for candidate in graph.nodes if _context_visible(candidate) and qualname and _canonical_qualname(candidate) == qualname]

    def add_edge(edge: Any, from_id: str, to_id: str, *, derived_from: list[str] | None = None) -> None:
        if from_id == to_id or to_id not in node_by_id or not _context_visible(node_by_id[to_id]):
            return
        relation_kind = "CALLS" if derived_from else str(getattr(edge, "kind", "RELATED"))
        key = (from_id, to_id, relation_kind)
        if key in seen:
            return
        payload = edge.to_dict()
        payload["from"] = from_id
        payload["to"] = to_id
        if derived_from:
            payload["id"] = f"inspect:{from_id}:{to_id}:{edge.id}"
            payload["kind"] = "CALLS"
            payload["properties"] = {
                **(payload.get("properties") or {}),
                "derived_from": derived_from,
                "relation_scope": "direct",
                "projection": "inspect_visible_call",
            }
        seen.add(key)
        direction = "downstream" if from_id == resolved.id else "upstream"
        result.append({"direction": direction, "edge": payload, "quality": classify_edge_quality(edge).to_dict()})

    # Direct materialized relationships and canonical CALLS aliases.
    for edge in graph.edges:
        if edge.from_node in source_ids:
            for target_id in visible_targets(edge.to_node):
                add_edge(edge, resolved.id, target_id, derived_from=[edge.id] if edge.from_node != resolved.id or target_id != edge.to_node else None)
        if edge.to_node in source_ids:
            for source_id in visible_targets(edge.from_node):
                add_edge(edge, source_id, resolved.id, derived_from=[edge.id] if edge.to_node != resolved.id or source_id != edge.from_node else None)

    # A precise method often reaches its call expression through CONTAINS;
    # follow the local RESOLVES_TO/CALLS edge to expose the called method.
    for contains in graph.edges:
        if contains.from_node not in source_ids or str(contains.kind).upper() != "CONTAINS":
            continue
        call_id = contains.to_node
        for relation in graph.edges:
            if relation.from_node != call_id or str(relation.kind).upper() not in {"RESOLVES_TO", "CALLS"}:
                continue
            for target_id in visible_targets(relation.to_node):
                add_edge(relation, resolved.id, target_id, derived_from=[contains.id, relation.id])

    return sorted(result, key=lambda item: (item["direction"], item["edge"]["id"]))


def _canonical_qualname(node: Node) -> str:
    identity = node.properties.get("canonical_identity") or {}
    return str(identity.get("qualname") or node.name or "")


def _context_visible(node: Node | None) -> bool:
    if node is None:
        return False
    if node.kind in SUPPRESSED_KINDS:
        return False
    file_name = (_node_file(node) or "").lower()
    return not any(marker in file_name for marker in GENERATED_MARKERS)


def _linked_boundary_nodes(graph: GraphDocument, node_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    node_by_id = {node.id: node for node in graph.nodes}
    tests, routes = [], []
    for edge in graph.edges:
        if node_id not in {edge.from_node, edge.to_node}:
            continue
        other_id = edge.to_node if edge.from_node == node_id else edge.from_node
        other = node_by_id.get(other_id)
        if not other:
            continue
        item = {"node": _node_dict(other), "edge": edge.to_dict()}
        if other.kind == "TEST":
            tests.append(item)
        if other.kind in BOUNDARY_KINDS or str(other.properties.get("boundary_category", "")).lower() in BOUNDARY_CATEGORIES:
            routes.append(item)
    return tests, routes


def _support_pack_activation(graph: GraphDocument) -> dict[str, Any]:
    metadata = graph.metadata or {}
    for key in ("plugin_selection_plan", "support_pack_versions", "support_pack_fingerprint"):
        if key in metadata:
            return {"source": key, "activation": metadata[key]}
    return {"source": "graph_metadata", "activation": [], "status": "not_recorded"}


def _region_related(region: dict[str, Any], node: Node, result: dict[str, Any]) -> bool:
    target_ids = {str(item.get("id")) for item in result.get("affected_nodes", []) if isinstance(item, dict)} | {node.id}
    evidence = region.get("evidence", []) or []
    return str(region.get("target_id")) in target_ids or any(str(item.get("node_id")) in target_ids for item in evidence if isinstance(item, dict))


def _edge_claim(edge: dict[str, Any], direction: str) -> str:
    return f"{direction} relationship {edge.get('kind')} is supported by {edge.get('source')} evidence at confidence {edge.get('confidence')}"


def _confidence_level(value: float) -> str:
    if value >= 0.84:
        return "high"
    if value >= 0.70:
        return "medium"
    if value > 0:
        return "low"
    return "unknown"


def _node_dict(node: Node) -> dict[str, Any]:
    return {"id": node.id, "kind": node.kind, "name": node.name, "properties": dict(node.properties)}


def _node_file(node: Node) -> str | None:
    value = node.properties.get("file") or node.properties.get("path")
    return str(value).replace("\\", "/") if value else None


def _project_root(project_path: str) -> Path:
    root = Path(project_path).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Project directory does not exist: {project_path}")
    return root


def _mode_cache_key(mode: str, graph: GraphDocument, subject: str, flags: dict[str, Any]) -> str:
    from impact_engine.ranking_policy import DEFAULT_RANKING_POLICY, TEST_SELECTION_POLICY_VERSION

    payload = {
        "mode": mode,
        "schema_version": MODE_SCHEMA_VERSION,
        "graph_fingerprint": graph.metadata.get("graph_fingerprint"),
        "ranking_policy_version": DEFAULT_RANKING_POLICY.version,
        "test_selection_policy_version": TEST_SELECTION_POLICY_VERSION,
        "subject": subject,
        "flags": flags,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def _parse_simple_policy(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = [item.strip() for item in line.split(":", 1)]
        if value.lower() in {"true", "false"}:
            parsed: Any = value.lower() == "true"
        elif value.lower() in {"null", "none"}:
            parsed = None
        else:
            try:
                parsed = float(value) if "." in value else int(value)
            except ValueError:
                parsed = value.strip("'\"")
        result[key] = parsed
    return result
