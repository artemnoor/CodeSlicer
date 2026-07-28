"""Build a compact projection from a full :class:`GraphDocument`."""
from __future__ import annotations

import hashlib
import heapq
from dataclasses import replace
from typing import Any

from impact_engine.edge_quality import classify_edge_quality, edge_is_active_for_impact
from impact_engine.ranking_policy import DEFAULT_RANKING_POLICY, RankingPolicy, TEST_SELECTION_POLICY_VERSION, REVIEW_SCHEMA_VERSION
from .contracts import ReviewCandidate, ReviewChain, ReviewEvidence, ReviewProjection, ReviewRank
from .diversification import diversify_candidates
from .explanations import build_chain, explanation
from .filters import is_actionable, is_boundary_node, is_test_node, node_file, semantic_cluster, suppression_reason
from .ranking import is_changed_downstream_edge, score_path, traversal_directions
from .test_selection import select_targeted_tests


def _node_label(node: Any) -> str:
    return str(getattr(node, "name", "") or getattr(node, "id", ""))


def _edge_evidence(edge: Any, evidence: dict[str, ReviewEvidence]) -> list[ReviewEvidence]:
    result: list[ReviewEvidence] = []
    raw = list(getattr(edge, "evidence", []) or [])
    if not raw:
        ev = ReviewEvidence(id=f"edge:{edge.id}:missing", kind=getattr(edge, "kind", "UNKNOWN"), description="edge has no recorded evidence", source=getattr(edge, "source", None), confidence=getattr(edge, "confidence", None))
        evidence.setdefault(ev.id, ev)
        return [ev]
    for index, item in enumerate(raw):
        ev = ReviewEvidence(
            id=f"edge:{edge.id}:{index}", file=getattr(item, "file", None), line=getattr(item, "line", None),
            kind=getattr(edge, "kind", "UNKNOWN"), description=getattr(item, "description", ""),
            source=getattr(item, "source", None) or getattr(edge, "source", None), confidence=getattr(edge, "confidence", None),
        )
        evidence.setdefault(ev.id, ev)
        result.append(ev)
    return result


def _path_confidence(edges: list[Any]) -> str:
    qualities = [classify_edge_quality(edge) for edge in edges]
    properties = [getattr(edge, "properties", {}) or {} for edge in edges]
    if any(item.status == "suspicious" or str(props.get("resolution_status", "")).lower() in {"ambiguous", "unresolved"} for item, props in zip(qualities, properties)):
        return "unresolved"
    if any(item.status == "rejected" or item.confidence < 0.55 for item in qualities):
        return "speculative"
    if all(item.status == "confirmed" and getattr(edge, "evidence", None) for item, edge in zip(qualities, edges)):
        return "confirmed"
    return "likely"


def _impact_class(target: Any, edges: list[Any], depth: int, features: list[str], confidence: str) -> str:
    if confidence == "speculative":
        return "speculative"
    if is_boundary_node(target) or is_test_node(target) or any(item in features for item in {"route_handler_boundary", "frontend_backend_boundary", "schema_database_boundary", "queue_boundary", "public_api_boundary"}):
        return "boundary"
    return "direct" if depth <= 1 else "transitive"


def collect_candidates(
    graph: Any,
    changed_symbols: list[dict[str, Any]],
    *,
    policy: RankingPolicy = DEFAULT_RANKING_POLICY,
    deep: bool = False,
    max_depth: int = 5,
    max_nodes: int = 200,
    max_edges: int = 400,
    max_path_states: int = 1000,
    max_branching: int = 8,
    min_path_score: float = -80.0,
) -> tuple[dict[str, ReviewCandidate], dict[str, ReviewEvidence], list[ReviewChain], set[str], list[str], dict[str, ReviewCandidate]]:
    """Traverse causal evidence paths while preserving the full graph.

    Budgets apply only to this projection traversal.  They are deliberately
    explicit so a large or cyclic graph cannot turn a concise review into an
    unbounded closure.  The full ``GraphDocument`` is never pruned.
    """
    nodes = {node.id: node for node in graph.nodes}
    csharp_projection = any(
        str((getattr(node, "properties", {}) or {}).get("language") or "").lower() == "csharp"
        for node in graph.nodes
    )
    edges_by_id = {edge.id: edge for edge in graph.edges}
    outgoing: dict[str, list[Any]] = {}
    incoming: dict[str, list[Any]] = {}
    warnings: list[str] = []
    suppressed: dict[str, ReviewCandidate] = {}
    discovered_nodes: set[str] = set()
    expanded_edges = 0
    expanded_states = 0

    def warn_once(message: str) -> None:
        if message not in warnings:
            warnings.append(message)

    for edge in graph.edges:
        if edge.from_node not in nodes or edge.to_node not in nodes:
            continue
        if not deep and not edge_is_active_for_impact(edge):
            continue
        if deep and classify_edge_quality(edge).status == "rejected":
            continue
        outgoing.setdefault(edge.from_node, []).append(edge)
        incoming.setdefault(edge.to_node, []).append(edge)
    for values in (*outgoing.values(), *incoming.values()):
        values.sort(key=lambda item: (-float(getattr(item, "confidence", 0.0)), str(getattr(item, "kind", "")), str(getattr(item, "id", ""))))

    def actionable_endpoint_ids(node_id: str) -> list[str]:
        """Map canonical unresolved endpoints back to materialized symbols."""
        endpoint = nodes.get(node_id)
        if endpoint is None or suppression_reason(endpoint, allow_boundary=False) is None:
            return [node_id]
        properties = getattr(endpoint, "properties", {}) or {}
        canonical = properties.get("canonical_identity") or {}
        qualified_name = str(canonical.get("qualname") or "")
        endpoint_name = _node_label(endpoint)
        if not qualified_name and not endpoint_name:
            return [node_id]
        matches: list[str] = []
        for candidate in graph.nodes:
            if candidate.id == node_id or not is_actionable(candidate):
                continue
            candidate_properties = getattr(candidate, "properties", {}) or {}
            candidate_canonical = candidate_properties.get("canonical_identity") or {}
            candidate_qualified_name = str(candidate_canonical.get("qualname") or "")
            if (qualified_name and candidate_qualified_name == qualified_name) or (endpoint_name and _node_label(candidate) == endpoint_name):
                matches.append(candidate.id)
        return matches or [node_id]

    evidence: dict[str, ReviewEvidence] = {}
    candidates: dict[str, ReviewCandidate] = {}
    path_signatures: dict[str, set[tuple[str, ...]]] = {}
    chains: list[ReviewChain] = []
    chain_seen: set[tuple[str, ...]] = set()
    for changed in changed_symbols:
        target_id = str(changed.get("id", ""))
        discovered_nodes.add(target_id)
        node = nodes.get(target_id)
        label = _node_label(node) if node else target_id
        diff_ev = ReviewEvidence(id=f"diff:{target_id}", file=changed.get("file"), line=changed.get("line"), kind="DIFF", description="changed symbol is present in the diff", source="DIFF", confidence=1.0)
        evidence[diff_ev.id] = diff_ev
        if node is not None and is_actionable(node):
            changed_breakdown = {"changed_symbol": policy.weights()["changed_symbol"]}
            changed_factors = ["changed_symbol"]
            if str(getattr(node, "kind", "")).upper() in {"METHOD", "FUNCTION", "CLASS"}:
                changed_breakdown["changed_callable"] = policy.weights()["changed_callable"]
                changed_factors.append("changed_callable")
            rank = ReviewRank(round(sum(changed_breakdown.values()), 6), tuple(changed_factors), changed_breakdown, policy.version)
            candidates[target_id] = ReviewCandidate(target_id, node.kind, node_file(node), label, "direct", "confirmed", rank, (diff_ev.id,), {}, (), None, semantic_cluster(node))
        elif node is None:
            # A file-only or unsupported-language diff is still an actionable
            # review anchor.  It is not evidence of downstream impact.
            rank = ReviewRank(policy.weights()["changed_symbol"], ("changed_symbol",), {"changed_symbol": policy.weights()["changed_symbol"]}, policy.version)
            candidates[target_id] = ReviewCandidate(target_id, str(changed.get("kind") or "FILE"), changed.get("file"), target_id, "direct", "confirmed", rank, (diff_ev.id,), {}, (), None, str(changed.get("file") or "file"))
        if target_id not in nodes:
            warnings.append(f"changed entity {target_id} is not materialized in full graph")
            continue
        # Some extractors retain a precise METHOD node while resolved CALLS
        # edges are attached to a same-scope canonical/unresolved endpoint.
        # Traverse those equivalent start IDs, but keep the precise changed
        # declaration as the visible review anchor.
        start_ids = [target_id]
        target_scope = str((getattr(node, "properties", {}) or {}).get("scope") or "")
        target_file = node_file(node)
        target_name = _node_label(node)
        target_canonical = (getattr(node, "properties", {}) or {}).get("canonical_identity") or {}
        target_qualified_name = str(target_canonical.get("qualname") or target_name)
        for alias in graph.nodes:
            if alias.id == target_id or alias.id in start_ids:
                continue
            alias_properties = getattr(alias, "properties", {}) or {}
            same_scope = target_scope and str(alias_properties.get("scope") or "") == target_scope
            same_name = _node_label(alias) == target_name and str(getattr(alias, "kind", "")).upper() in {"METHOD", "FUNCTION", "CLASS", "EXTERNAL_LIBRARY", "LIBRARY"}
            same_file = target_file and node_file(alias) and node_file(alias) == target_file
            alias_canonical = alias_properties.get("canonical_identity") or {}
            same_canonical = str(alias_canonical.get("qualname") or "") == target_qualified_name
            if same_scope or same_canonical or (same_name and (same_file or str(getattr(alias, "kind", "")).upper() in {"EXTERNAL_LIBRARY", "LIBRARY"})):
                start_ids.append(alias.id)
        queue: list[tuple[float, int, str, tuple[str, ...], tuple[str, ...]]] = [(0.0, 0, start_id, (), (start_id,)) for start_id in start_ids]
        seen_paths: set[tuple[str, ...]] = set()
        while queue:
            if expanded_states >= max_path_states:
                warn_once("projection_budget_exhausted:path_states")
                break
            neg_score, depth, current, edge_ids, path_nodes = heapq.heappop(queue)
            expanded_states += 1
            if depth >= max_depth:
                continue
            # Tests are a terminal review concern. They are selected by the
            # dedicated test layer; allowing concise impact traversal to pass
            # through a test and back into another HTTP boundary creates
            # unrelated route-to-route chains.
            if csharp_projection and is_test_node(nodes.get(current)):
                continue
            adjacent: list[tuple[Any, str, bool]] = []
            for edge in outgoing.get(current, []):
                changed_downstream = current in start_ids and is_changed_downstream_edge(edge, changed)
                target_ids = actionable_endpoint_ids(edge.to_node)
                for next_id in target_ids:
                    terminal_technical = suppression_reason(nodes.get(next_id), allow_boundary=True) is not None
                    boundary_terminal = is_boundary_node(nodes.get(next_id))
                    if "outgoing" in traversal_directions(edge) or changed_downstream or ((terminal_technical or boundary_terminal) and str(getattr(edge, "kind", "")).upper() in {"ASSIGNS", "CALLS", "IMPORTS"}):
                        adjacent.append((edge, next_id, terminal_technical))
            for edge in incoming.get(current, []):
                if "incoming" in traversal_directions(edge):
                    adjacent.append((edge, edge.from_node, False))
            adjacent.sort(key=lambda item: (-float(getattr(item[0], "confidence", 0.0)), str(getattr(item[0], "kind", "")), str(getattr(item[0], "id", "")), item[1]))
            for edge, next_id, terminal_technical in adjacent[:max_branching]:
                expanded_edges += 1
                if expanded_edges > max_edges:
                    warn_once("projection_budget_exhausted:edges")
                    break
                if next_id in path_nodes or next_id not in nodes:
                    continue
                next_edges = edge_ids + (edge.id,)
                if next_edges in seen_paths:
                    continue
                seen_paths.add(next_edges)
                if next_id not in discovered_nodes:
                    if len(discovered_nodes) >= max_nodes:
                        warn_once("projection_budget_exhausted:nodes")
                        continue
                    discovered_nodes.add(next_id)
                next_node = nodes[next_id]
                edge_objects = [edges_by_id.get(edge_id) for edge_id in next_edges]
                edge_objects = [item for item in edge_objects if item is not None]
                node_objects = [nodes[node_id] for node_id in path_nodes + (next_id,)]
                score, features, breakdown = score_path(edge_objects, node_objects, depth + 1, policy)
                if path_nodes[0] in start_ids and edge_objects and is_changed_downstream_edge(edge_objects[0], changed):
                    downstream_weight = policy.weights().get("changed_downstream", 0.0)
                    if downstream_weight:
                        breakdown = dict(breakdown)
                        breakdown["changed_downstream"] = downstream_weight
                        features = tuple(list(features) + ["changed_downstream"])
                        score = round(score + downstream_weight, 6)
                confidence = _path_confidence(edge_objects)
                impact_class = _impact_class(next_node, edge_objects, depth + 1, list(features), confidence)
                technical = suppression_reason(next_node, allow_boundary=True) or is_test_node(next_node)
                if score < min_path_score and not technical and not is_boundary_node(next_node):
                    warn_once("projection_pruned:low_score")
                    continue
                # Test files belong in the dedicated targeted-test layer.  A
                # generic import/call into a test module is not proof that the
                # test covers the changed symbol.
                test_without_coverage = is_test_node(next_node) and "test_direct" not in features
                if suppression_reason(next_node, allow_boundary=True) or test_without_coverage:
                    # Technical nodes remain available to the chain, but never
                    # become top entities in concise mode.
                    reason = suppression_reason(next_node, allow_boundary=True) or "test coverage not proven"
                    suppressed[next_id] = ReviewCandidate(
                        next_id, next_node.kind, node_file(next_node), _node_label(next_node), impact_class,
                        confidence, ReviewRank(score, tuple(features), breakdown, policy.version), (), {}, (), reason,
                        semantic_cluster(next_node),
                    )
                    if not terminal_technical and expanded_states + len(queue) < max_path_states:
                        heapq.heappush(queue, (-score, depth + 1, next_id, next_edges, path_nodes + (next_id,)))
                    elif not terminal_technical:
                        warn_once("projection_budget_exhausted:path_states")
                    continue
                evidence_items: list[ReviewEvidence] = []
                for path_edge in edge_objects:
                    evidence_items.extend(_edge_evidence(path_edge, evidence))
                evidence_items = list({item.id: item for item in evidence_items}.values())
                chain_key = path_nodes + (next_id,)
                chain_digest = hashlib.sha256("\0".join(chain_key).encode("utf-8")).hexdigest()[:16]
                chain_id = "chain:" + chain_digest
                if chain_key not in chain_seen and evidence_items and len(path_nodes) >= 1:
                    chain = build_chain(chain_id, [_node_label(nodes[item]) for item in chain_key], evidence_items, confidence, "confirmed" if confidence == "confirmed" else confidence, impact_class)
                    chains.append(chain)
                    chain_seen.add(chain_key)
                old = candidates.get(next_id)
                rank = ReviewRank(score, tuple(features), breakdown, policy.version)
                signature = tuple(next_edges)
                known_paths = path_signatures.setdefault(next_id, set())
                if signature not in known_paths and known_paths and "independent_evidence_path" not in rank.factors:
                    boosted_breakdown = dict(rank.breakdown)
                    boosted_breakdown["independent_evidence_path"] = policy.weights()["independent_evidence_path"]
                    rank = ReviewRank(
                        round(rank.score + policy.weights()["independent_evidence_path"], 6),
                        tuple(list(rank.factors) + ["independent_evidence_path"]),
                        dict(sorted(boosted_breakdown.items())),
                        policy.version,
                    )
                known_paths.add(signature)
                # A boundary call expression is displayed as a boundary
                # action, never as raw CALL_EXPR noise.  The original node
                # and edge kind remain intact in the full graph/evidence.
                display_kind = "BOUNDARY_CALL" if str(getattr(next_node, "kind", "")).upper() == "CALL_EXPR" and is_boundary_node(next_node) else next_node.kind
                candidate = ReviewCandidate(next_id, display_kind, node_file(next_node), _node_label(next_node), impact_class, confidence, rank, tuple(item.id for item in evidence_items), {}, (chain_id,) if evidence_items else (), None, semantic_cluster(next_node))
                if old is None or (candidate.rank.score, candidate.entity_id) > (old.rank.score, old.entity_id):
                    candidates[next_id] = candidate
                elif old is not None and candidate.rank.score == old.rank.score:
                    candidates[next_id] = replace(old, evidence_ids=tuple(sorted(set(old.evidence_ids + candidate.evidence_ids))), chain_ids=tuple(sorted(set(old.chain_ids + candidate.chain_ids))))
                if expanded_states + len(queue) < max_path_states:
                    heapq.heappush(queue, (-score, depth + 1, next_id, next_edges, path_nodes + (next_id,)))
                else:
                    warn_once("projection_budget_exhausted:path_states")
            if expanded_edges >= max_edges:
                break
    return candidates, evidence, chains, {item.get("id", "") for item in changed_symbols}, warnings, suppressed


def _risk(graph: Any, changed_ids: set[str], candidates: list[ReviewCandidate], tests: list[Any], coverage: list[dict[str, Any]]) -> dict[str, Any]:
    changed_nodes = [node for node in graph.nodes if node.id in changed_ids]
    all_nodes = changed_nodes + [node for node in graph.nodes if node.id in {item.entity_id for item in candidates}]
    reasons: list[str] = []
    score = 0
    boundary = any(is_boundary_node(node) for node in all_nodes)
    critical = any(bool((getattr(node, "properties", {}) or {}).get(key)) for node in all_nodes for key in ("critical", "critical_path", "security", "auth", "payment"))
    routes = any(str(getattr(node, "kind", "")).upper() in {"ROUTE", "HTTP_ROUTE"} for node in all_nodes)
    schema = any(str((getattr(node, "properties", {}) or {}).get("boundary_category", "")).lower() in {"schema", "database", "db"} for node in all_nodes)
    unresolved_boundary = any(item.impact_class == "unresolved" and item.entity_id in {node.id for node in all_nodes} for item in candidates)
    independent_paths = sum(1 for item in candidates if "independent_evidence_path" in item.rank.factors)
    if boundary:
        score += 3; reasons.append("public or application boundary affected")
    if routes:
        score += 3; reasons.append("route/API boundary affected")
    if schema:
        score += 3; reasons.append("schema/database boundary affected")
    if critical:
        score += 3; reasons.append("critical/auth/payment path affected")
    if independent_paths >= 2:
        score += 2; reasons.append("multiple independent impact paths")
    if tests:
        reasons.append("targeted test evidence exists")
    incomplete = any(
        item.get("status") in {"unsupported", "limited"}
        and not item.get("review_usable", False)
        and not str(item.get("path", "")).lower().startswith(("test", "tests/"))
        for item in coverage
    )
    if incomplete or unresolved_boundary:
        reasons.append("incomplete or unresolved high-value coverage")
        return {"level": "UNKNOWN", "score": score, "confidence": "low", "reason": "incomplete language coverage" if incomplete else "unresolved high-value boundary", "reasons": reasons}
    level = "CRITICAL" if score >= 9 else "HIGH" if score >= 6 else "MEDIUM" if score >= 3 else "LOW"
    confidence = "high" if all(item.confidence in {"confirmed", "likely"} for item in candidates[:5]) else "medium"
    return {"level": level, "score": score, "confidence": confidence, "reasons": reasons}


def build_review_projection(
    graph: Any,
    changed_symbols: list[dict[str, Any]],
    changed_files: set[str] | None = None,
    *,
    max_results: int = 10,
    policy: RankingPolicy = DEFAULT_RANKING_POLICY,
    deep: bool = False,
    coverage: list[dict[str, Any]] | None = None,
    max_depth: int = 5,
    max_nodes: int = 200,
    max_edges: int = 400,
    max_path_states: int = 1000,
    max_branching: int = 8,
    min_path_score: float = -80.0,
) -> ReviewProjection:
    candidates_by_id, evidence, chains, changed_ids, warnings, suppressed = collect_candidates(
        graph,
        changed_symbols,
        policy=policy,
        deep=deep,
        max_depth=max_depth,
        max_nodes=max_nodes,
        max_edges=max_edges,
        max_path_states=max_path_states,
        max_branching=max_branching,
        min_path_score=min_path_score,
    )
    coverage = coverage or []
    candidates_by_id = _dedupe_alias_candidates(candidates_by_id)
    selected = diversify_candidates(candidates_by_id.values(), min(max_results, policy.max_results), policy)
    chains_by_id = {item.id: item for item in chains}
    enriched: list[ReviewCandidate] = []
    displayed_chain_ids: list[str] = []
    for candidate in selected:
        for chain_id in candidate.chain_ids:
            if chain_id in chains_by_id and chain_id not in displayed_chain_ids:
                displayed_chain_ids.append(chain_id)
                if len(displayed_chain_ids) == 3:
                    break
        if len(displayed_chain_ids) == 3:
            break
    displayed_chains = [chains_by_id[item] for item in displayed_chain_ids]
    for candidate in selected:
        selected_evidence = [evidence[item] for item in candidate.evidence_ids if item in evidence]
        visible_chain_ids = tuple(item for item in candidate.chain_ids if item in displayed_chain_ids)
        chain = next((chains_by_id[item] for item in visible_chain_ids if item in chains_by_id), None)
        why = explanation(candidate, chain, selected_evidence)
        enriched.append(replace(candidate, chain_ids=visible_chain_ids, why_affected=why))
    # Test selection is scoped to the actionable top-K projection.  Traversing
    # every candidate would recommend unrelated tests from a noisy full graph;
    # route/contract paths are still found inside this bounded target set.
    impacted_ids = {item.entity_id for item in selected}
    tests = select_targeted_tests(graph, changed_ids, impacted_ids, evidence, changed_files or set(), max_results=max_results)
    risk = _risk(graph, changed_ids, enriched, tests, coverage)
    if not displayed_chains:
        warnings.append("no_cross_file_impact_proven")
    return ReviewProjection(
        changed_entities=tuple(sorted(changed_ids)), candidates=tuple(enriched), suppressed_candidates=tuple(sorted(suppressed.values(), key=lambda item: item.entity_id)[:100]), evidence=tuple(sorted(evidence.values(), key=lambda item: item.id)),
        chains=tuple(displayed_chains), tests=tuple(tests), risk=risk, coverage=tuple(coverage), warnings=tuple(sorted(set(warnings))),
        policy_version=policy.version, test_selection_policy_version=TEST_SELECTION_POLICY_VERSION, schema_version=REVIEW_SCHEMA_VERSION,
        mode="deep" if deep else "concise",
    )


def _dedupe_alias_candidates(candidates: dict[str, ReviewCandidate]) -> dict[str, ReviewCandidate]:
    """Hide extractor compatibility aliases while retaining the full graph."""
    groups: dict[tuple[str | None, str], list[ReviewCandidate]] = {}
    for item in candidates.values():
        groups.setdefault((item.file, item.symbol), []).append(item)
    hidden: set[str] = set()
    prefixes = ("method:", "function:", "class:")
    for group in groups.values():
        canonical = [item for item in group if not item.entity_id.lower().startswith(prefixes)]
        if canonical:
            hidden.update(item.entity_id for item in group if item.entity_id.lower().startswith(prefixes))
    return {key: value for key, value in candidates.items() if key not in hidden}
