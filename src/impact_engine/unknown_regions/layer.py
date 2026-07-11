"""Universal uncertainty boundary for unresolved semantic regions.

This module deliberately does not infer edges from names or from an AI answer.
It reports gaps, creates bounded machine-readable requests for an external
researcher, and promotes a proposal only when an independent runtime/test
trace proves the exact endpoints and edge kind.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable

from impact_engine.models import EDGE_KINDS, Edge, Evidence, GraphDocument


_DECLARATION_KINDS = {"PROJECT", "FILE", "MODULE", "CLASS", "PARAMETER", "ATTRIBUTE"}
_CALL_EDGE_KINDS = {"CALLS", "RESOLVES_TO", "HTTP_CALLS", "MATCHES_ENDPOINT", "ROUTE_HANDLES"}


@dataclass(frozen=True)
class UnknownRegion:
    """A bounded piece of code for which the current graph has no proof."""

    region_id: str
    target_id: str
    kind: str
    status: str
    reasons: tuple[str, ...] = field(default_factory=tuple)
    evidence: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "region_id": self.region_id,
            "target_id": self.target_id,
            "kind": self.kind,
            "status": self.status,
            "reasons": list(self.reasons),
            "evidence": list(self.evidence),
            "details": dict(self.details),
        }


def analyze_unknown_regions(graph: GraphDocument) -> dict[str, Any]:
    """Find unresolved and suspicious regions without inventing relationships.

    An isolated function is not claimed to be dead. It is merely a candidate
    for review. Extracted call expressions with no semantic outgoing edge are
    higher-value candidates because they represent a missing resolution step.
    """

    outgoing: dict[str, list[Edge]] = {}
    incoming: dict[str, list[Edge]] = {}
    for edge in graph.edges:
        outgoing.setdefault(edge.from_node, []).append(edge)
        incoming.setdefault(edge.to_node, []).append(edge)

    regions: list[UnknownRegion] = []
    support_observations: dict[tuple[str, int], list[Edge]] = {}
    support_scopes: dict[str, list[Edge]] = {}
    for edge in graph.edges:
        if edge.source != "SUPPORT_PACK":
            continue
        support_scopes.setdefault(str(edge.to_node), []).append(edge)
        for evidence in edge.evidence or []:
            if evidence.file and evidence.line:
                support_observations.setdefault((str(evidence.file).replace("\\", "/"), int(evidence.line)), []).append(edge)
    resolved_by_support_pack: list[dict[str, Any]] = []
    for node in graph.nodes:
        props = node.properties or {}
        location = _location_evidence(node)
        if node.kind == "CALL_EXPR":
            location_key = (str(props.get("file", "")).replace("\\", "/"), int(props.get("line", 0) or 0))
            matched_support = list(support_observations.get(location_key, []))
            scope = str(props.get("scope") or "")
            for support_edge in support_scopes.get(scope, []):
                if support_edge not in matched_support:
                    matched_support.append(support_edge)
            if matched_support:
                for support_edge in matched_support:
                    provenance = (support_edge.properties or {}).get("support_pack") or {}
                    resolved_by_support_pack.append({
                        "region_target_id": node.id,
                        "status": "resolved_by_support_pack",
                        "support_pack": provenance.get("support_pack") or (support_edge.properties or {}).get("support_pack_id"),
                        "rule_id": provenance.get("rule_id") or (support_edge.properties or {}).get("support_pack_rule_id"),
                        "evidence": [item.to_dict() for item in support_edge.evidence or []],
                    })
                continue
            semantic_outgoing = [edge for edge in outgoing.get(node.id, []) if edge.kind in _CALL_EDGE_KINDS]
            if not semantic_outgoing:
                regions.append(_region(
                    graph,
                    node.id,
                    "unresolved_call",
                    ("no semantic outgoing edge", "receiver or target was not resolved"),
                    location,
                    details={
                        "call_name": props.get("call_name") or node.name,
                        "receiver": props.get("receiver"),
                        "method": props.get("method_name") or props.get("method"),
                        "scope": props.get("scope"),
                        "taxonomy": _unresolved_kind(props),
                    },
                ))
        elif node.kind in {"FUNCTION", "METHOD"} and not outgoing.get(node.id) and not incoming.get(node.id):
            regions.append(_region(
                graph,
                node.id,
                "isolated_symbol",
                ("no graph edges", "absence of evidence is not proof of dead code"),
                location,
            ))
        if str(props.get("resolution_status", "")).lower() in {"unresolved", "ambiguous"}:
            regions.append(_region(
                graph,
                node.id,
                "explicit_resolution_gap",
                (f"extractor status is {props['resolution_status']}",),
                location,
            ))

    for edge in graph.edges:
        status = str((edge.properties or {}).get("status", "")).lower()
        warnings = edge.properties.get("warnings", []) if edge.properties else []
        if status in {"suspicious", "rejected"} or warnings:
            regions.append(_region(
                graph,
                edge.id,
                "suspicious_edge",
                tuple([f"edge status is {status}"] if status else []) + tuple(str(item) for item in warnings),
                [_evidence_dict(ev) for ev in edge.evidence],
            ))

    regions = _dedupe_regions(regions)
    counts = {status: sum(1 for item in regions if item.status == status) for status in ("unresolved", "suspicious")}
    return {
        "status": "gaps_found" if regions else "no_gaps_detected",
        "policy": "no_ai_edges_without_independent_evidence",
        "regions": [item.to_dict() for item in regions],
        "counts": counts,
        "resolved_by_support_pack": resolved_by_support_pack,
        "resolved_by_support_pack_count": len(resolved_by_support_pack),
    }


def build_research_requests(report: dict[str, Any], *, project_path: str | None = None) -> list[dict[str, Any]]:
    """Create bounded requests an external AI researcher can process.

    Requests contain facts and questions, never an instruction to fabricate an
    edge. The caller may attach source code snippets and test constraints.
    """

    requests: list[dict[str, Any]] = []
    selected, selection = select_research_regions(report.get("regions", []))
    report["research_selection"] = selection
    for region in selected:
        request_id = "ur-" + sha256(str(region.get("region_id")).encode("utf-8")).hexdigest()[:16]
        requests.append({
            "request_id": request_id,
            "type": "unknown_region_research",
            "status": "unresolved",
            "project_path": project_path,
            "region": region,
            "questions": [
                "Which explicit language/library semantics could resolve this region?",
                "What deterministic evidence would distinguish the candidate targets?",
                "Which bounded test or runtime trace can validate the proposed edge?",
            ],
            "constraints": {
                "no_name_similarity_edges": True,
                "no_confirmed_edge_without_runtime_or_explicit_static_evidence": True,
                "proposal_must_include_from_to_kind": True,
            },
        })
    return requests


def build_pr_scoped_research_requests(
    report: dict[str, Any],
    *,
    project_path: str | None = None,
    changed_files: Iterable[str],
    max_requests: int = 50,
) -> list[dict[str, Any]]:
    """Build a bounded queue for the current PR/change set only."""
    changed = {str(item).replace("\\", "/") for item in changed_files}
    scoped = [
        region for region in report.get("regions", [])
        if any(str(item.get("file", "")).replace("\\", "/") in changed for item in (region.get("evidence", []) or []))
    ]
    selected, selection = select_research_regions(scoped, max_requests=max_requests)
    selection["scope"] = "changed_files"
    selection["changed_files"] = sorted(changed)
    report["pr_research_selection"] = selection
    requests = build_research_requests({"regions": selected}, project_path=project_path)
    for request in requests:
        request["scope"] = "pr"
    return requests


def select_research_regions(
    regions: Iterable[dict[str, Any]],
    *,
    max_requests: int = 2000,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Select bounded, evidence-bearing regions for an external AI agent.

    The complete report remains lossless. This queue is intentionally
    conservative: unlocated calls and isolated symbols are diagnostics, not
    actionable AI work. Identical call signatures are represented once.
    """
    candidates: list[tuple[int, dict[str, Any]]] = []
    excluded = {"no_evidence": 0, "isolated_symbol": 0, "duplicate": 0, "limit": 0}
    seen: set[tuple[Any, ...]] = set()
    for raw in regions:
        region = dict(raw)
        kind = str(region.get("kind", ""))
        details = dict(region.get("details", {}) or {})
        taxonomy = str(details.get("taxonomy") or kind)
        evidence = list(region.get("evidence", []) or [])
        if kind == "isolated_symbol":
            excluded["isolated_symbol"] += 1
            continue
        if kind.startswith("unresolved_") and not evidence and not details.get("receiver"):
            excluded["no_evidence"] += 1
            continue
        if taxonomy not in {"unresolved_call_target", "unresolved_receiver", "unresolved_route_prefix", "unresolved_call", "suspicious_edge"}:
            excluded["no_evidence"] += 1
            continue
        first_evidence = evidence[0] if evidence else {}
        key = (
            kind,
            first_evidence.get("file"),
            first_evidence.get("line"),
            details.get("call_name"),
            details.get("receiver"),
            details.get("method"),
            region.get("target_id") if not evidence else None,
        )
        if key in seen:
            excluded["duplicate"] += 1
            continue
        seen.add(key)
        score = 100 if kind == "suspicious_edge" else 60
        if details.get("receiver"):
            score += 20
        if str(details.get("receiver", "")).startswith("self."):
            score += 15
        if evidence:
            score += 10
        region["priority"] = min(score, 100)
        region["pattern_fingerprint"] = details.get("fingerprint") or region.get("target_id")
        candidates.append((score, region))

    candidates.sort(key=lambda item: (-item[0], str(item[1].get("region_id", ""))))
    if len(candidates) > max_requests:
        excluded["limit"] = len(candidates) - max_requests
    selected = [item for _, item in candidates[:max_requests]]
    return selected, {
        "policy": "evidence_and_priority_gated",
        "max_requests": max_requests,
        "selected": len(selected),
        "candidate_count": len(candidates),
        "excluded": excluded,
        "unique_patterns": len({item.get("pattern_fingerprint") for item in selected}),
    }


def write_research_requests(requests: list[dict[str, Any]], path: str | Path) -> str:
    """Persist the AI handoff contract as UTF-8 JSON."""
    destination = Path(path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps({
        "protocol": "impact-engine.unknown-region-research",
        "version": "1.0",
        "policy": "proposals require independent runtime/test evidence",
        "requests": requests,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(destination)


def apply_validated_hypotheses(
    graph: GraphDocument,
    hypotheses: Iterable[dict[str, Any]],
    runtime_trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Promote only hypotheses matched by an independent runtime trace.

    A trace match may identify endpoints using ``from``, ``to``, ``kind`` or
    an existing edge id. Unmatched and malformed proposals are returned for
    inspection and do not mutate the graph.
    """

    trace = runtime_trace or {}
    matched = list(trace.get("matched_edges", []) or [])
    node_ids = {node.id for node in graph.nodes}
    promoted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for raw in hypotheses:
        item = dict(raw or {})
        from_node, to_node, kind = item.get("from") or item.get("from_node"), item.get("to") or item.get("to_node"), item.get("kind")
        if not from_node or not to_node or kind not in EDGE_KINDS or str(kind) == "AFFECTS":
            rejected.append({"hypothesis": item, "reason": "invalid edge contract"})
            continue
        if str(from_node) not in node_ids or str(to_node) not in node_ids:
            rejected.append({"hypothesis": item, "reason": "hypothesis endpoint is not present in graph"})
            continue
        if not _trace_matches(item, matched):
            rejected.append({"hypothesis": item, "reason": "no independent runtime evidence"})
            continue
        evidence = [Evidence(description="AI hypothesis independently confirmed by runtime/test trace", source="RUNTIME_CONFIRMED")]
        evidence.extend(_evidence_from_dicts(item.get("evidence", [])))
        edge = Edge(
            id=str(item.get("id") or f"runtime:{from_node}:{kind}:{to_node}"),
            kind=str(kind),
            from_node=str(from_node),
            to_node=str(to_node),
            source="RUNTIME_CONFIRMED",
            confidence=min(0.98, max(0.80, float(item.get("confidence", 0.80)))),
            evidence=evidence,
            properties={
                "status": "confirmed",
                "validated_hypothesis": True,
                "validation": "independent_runtime_trace",
                "ai_proposal_id": item.get("proposal_id"),
            },
        )
        graph.add_edge(edge)
        promoted.append(edge.to_dict())
    return {
        "status": "applied" if promoted else "no_hypotheses_promoted",
        "promoted": promoted,
        "rejected": rejected,
        "policy": "only_exact_runtime_matches_are_promoted",
    }


def _trace_matches(hypothesis: dict[str, Any], matched_edges: list[dict[str, Any]]) -> bool:
    for item in matched_edges:
        if item.get("edge_id") and item.get("edge_id") == hypothesis.get("id"):
            return True
        if (
            (item.get("from") or item.get("from_node")) == (hypothesis.get("from") or hypothesis.get("from_node"))
            and (item.get("to") or item.get("to_node")) == (hypothesis.get("to") or hypothesis.get("to_node"))
            and item.get("kind", hypothesis.get("kind")) == hypothesis.get("kind")
        ):
            return True
    return False


def _region(
    graph: GraphDocument,
    target_id: str,
    kind: str,
    reasons: tuple[str, ...],
    evidence: list[dict[str, Any]],
    details: dict[str, Any] | None = None,
) -> UnknownRegion:
    status = "suspicious" if kind == "suspicious_edge" else "unresolved"
    clean_details = {key: value for key, value in (details or {}).items() if value is not None}
    location = evidence[0] if evidence else {}
    fingerprint_input = "|".join(str(item) for item in (
        kind, location.get("file"), clean_details.get("scope"),
        clean_details.get("call_name"), clean_details.get("receiver"), clean_details.get("method"),
    ))
    fingerprint = sha256(fingerprint_input.encode("utf-8")).hexdigest()[:20]
    clean_details["fingerprint"] = fingerprint
    return UnknownRegion(
        region_id=f"unknown:{kind}:{target_id}",
        target_id=target_id,
        kind=kind,
        status=status,
        reasons=tuple(reasons),
        evidence=tuple(evidence),
        details=clean_details,
    )


def _unresolved_kind(properties: dict[str, Any]) -> str:
    receiver = properties.get("receiver")
    call_name = str(properties.get("call_name") or "")
    if receiver:
        return "unresolved_call_target"
    if call_name.startswith("HTTP ") or "route" in call_name.lower():
        return "unresolved_route_prefix"
    return "unresolved_receiver"


def _location_evidence(node: Any) -> list[dict[str, Any]]:
    props = getattr(node, "properties", {}) or {}
    file_name = props.get("file") or props.get("path")
    line = props.get("line")
    if not file_name and line is None:
        return []
    return [{"file": file_name, "line": line, "description": "unresolved graph target location"}]


def _evidence_dict(ev: Evidence) -> dict[str, Any]:
    return ev.to_dict()


def _evidence_from_dicts(items: Any) -> list[Evidence]:
    result: list[Evidence] = []
    for item in items or []:
        if isinstance(item, dict):
            result.append(Evidence(
                description=str(item.get("description", "hypothesis evidence")),
                file=item.get("file"),
                line=item.get("line"),
                source=str(item.get("source", "AI_PROPOSED")),
            ))
    return result


def _dedupe_regions(regions: list[UnknownRegion]) -> list[UnknownRegion]:
    result: list[UnknownRegion] = []
    seen: set[str] = set()
    for region in regions:
        if region.region_id not in seen:
            result.append(region)
            seen.add(region.region_id)
    return result
