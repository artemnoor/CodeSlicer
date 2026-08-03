"""Compact, local-first daily review projection.

This module deliberately projects the existing graph instead of changing the
legacy PR review or impact-query contracts.  The full graph remains available
through ``deep_action`` and the existing viewers.
"""
from __future__ import annotations

import subprocess
import time
import hashlib
import json
from dataclasses import dataclass
import heapq
import shlex
from pathlib import Path
from typing import Any

from impact_engine.graph_quality import graph_fingerprint
from impact_engine.impact import impact_query
from impact_engine.edge_quality import classify_edge_quality, edge_is_active_for_impact
from impact_engine.models import GraphDocument
from impact_engine.persistence import write_json_atomic
from impact_engine.profiling import AnalysisProfiler
from impact_engine.pr_review import (
    _changed_symbols,
    parse_git_diff,
    recommend_tests,
    score_pr_risk,
)
from impact_engine.ranking_policy import DEFAULT_RANKING_POLICY, REVIEW_PROJECTION_POLICY_VERSION, REVIEW_SCHEMA_VERSION, TEST_SELECTION_POLICY_VERSION
from impact_engine.review_projection import build_review_projection
from impact_engine.contracts import MODE_CONTRACT_VERSION, action, attach_mode_contract
from impact_engine.project_storage import is_codeslicer_artifact_path
from impact_engine.review_source import review_source


SCHEMA_VERSION = "ReviewReport/v2"
SUPPRESSED_KINDS = {"ASSIGNMENT", "CALL_EXPR", "EXTERNAL_LIBRARY", "CANONICAL_ALIAS", "SUPPORT_PACK"}
SUPPORTED_SUFFIXES = {".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts", ".go", ".java", ".cs", ".c", ".h", ".cc", ".cpp", ".cxx", ".hh", ".hpp", ".hxx", ".rs", ".kt", ".kts", ".php", ".rb", ".html", ".htm", ".xhtml", ".css", ".scss", ".sass", ".less", ".vue", ".svelte", ".astro"}


def _raw_graph_cache_path(root: Path, scope: str | None = None) -> Path:
    """Return the scope-isolated raw graph cache used by incremental review.

    The regular ``analyze-incremental`` command already uses this convention.
    Reusing it from Review prevents a UI-triggered refresh from silently
    falling back to a complete extraction of an otherwise cached workspace.
    """
    scope_key = hashlib.sha256((scope or ".").encode("utf-8")).hexdigest()[:12]
    return root / ".impact_engine" / f"raw_graph.{scope_key}.json"


@dataclass(frozen=True)
class ReviewReport:
    """Typed wrapper for the stable ReviewReport/v1 dictionary contract."""

    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return dict(self.payload)


def build_review_report(
    project_path: str,
    *,
    graph: GraphDocument | None = None,
    graph_path: str | Path | None = None,
    diff_text: str | None = None,
    diff_source: str | None = None,
    base: str | None = None,
    refresh: str = "auto",
    max_results: int = 10,
    run_tests: str = "suggested",
    deep: bool = False,
    entity: str | None = None,
    scope: str | None = None,
    review_source_kind: str = "current-changes",
    include_potential: bool = False,
) -> dict[str, Any]:
    """Build a deterministic, bounded daily review report.

    ``graph`` is injectable for fixtures and callers that already loaded the
    local graph.  No network or upload is performed here.
    """
    root = Path(project_path).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Project directory does not exist: {project_path}")
    warnings: list[str] = []
    profiler = AnalysisProfiler()
    profile_started = time.perf_counter()
    graph, freshness = _resolve_graph(root, graph, refresh, warnings, base=base, graph_path=graph_path, scope=scope)
    graph = _exclude_graphify_from_default_review(graph, warnings)
    graph_integrity = _review_graph_integrity(graph)
    if graph_integrity["dangling_endpoint_edges"]:
        warnings.append(
            f"{graph_integrity['dangling_endpoint_edges']} dangling edges excluded from concise review"
        )
    if review_source_kind == "github-pr" and diff_text is None:
        raise ValueError("--source github-pr requires a local diff file prepared by an explicit OAuth action; no network request was made")
    if review_source_kind == "diff-file" and diff_text is None:
        raise ValueError("--source diff-file requires --diff-file; no file or network source was inferred")
    source_contract = review_source(root, base=base, diff_file="provided" if diff_text is not None else None)
    if review_source_kind == "staged" and not diff_text:
        source_contract["kind"] = "staged"
        source_contract["label"] = "Staged changes"
    elif review_source_kind == "compare" and not diff_text:
        source_contract["kind"] = "compare"
        source_contract["label"] = "Compare refs"
    elif review_source_kind == "github-pr":
        source_contract["kind"] = "github_pull_request"
        source_contract["label"] = "GitHub pull request (local diff)"
    selected_base = base or source_contract["base"].get("base_ref")
    diff, source = _resolve_diff(root, diff_text, "staged" if review_source_kind == "staged" else diff_source, selected_base)
    if source == "project-not-a-git-repository":
        # A nested project must never inherit the parent repository's diff.
        # Keep the review honest and let the UI explain why no changed files
        # were inferred until the caller supplies an explicit diff.
        warnings.append("project is nested in another Git repository; parent diff was not used")
    changed_files = parse_git_diff(diff)
    if not changed_files:
        warnings.append("no local changes were found; make a change or choose an explicit comparison source")
    generated_changes = [item.path for item in changed_files if is_codeslicer_artifact_path(item.path)]
    changed_files = [item for item in changed_files if not is_codeslicer_artifact_path(item.path)]
    if generated_changes:
        warnings.append(f"{len(generated_changes)} generated CodeSlicer artifact changes excluded from review")
    semantic_diff = {
        "files": [
            {
                "path": item.path,
                "status": item.semantic_status,
                "reasons": list(item.semantic_reasons),
            }
            for item in changed_files
        ],
        "has_runtime_change": any(item.semantic_status != "no_runtime_change" for item in changed_files),
        "has_behavioral_default_change": any(item.semantic_status == "behavioral_default_change" for item in changed_files),
    }
    if changed_files and not semantic_diff["has_runtime_change"]:
        warnings.append("no runtime change detected: the diff contains only comments or docstrings")
    scope_prefix = (scope or "").replace("\\", "/").strip("/")
    # CLI callers use ``--scope .`` for the repository root.  Treat it as no
    # path filter; otherwise it would only retain paths beginning with ``./``
    # while Git diffs correctly use repository-relative paths such as
    # ``src/service.py``.  That silently emptied every root-scoped review.
    if scope_prefix == ".":
        scope_prefix = ""
    if scope_prefix:
        changed_files = [
            item for item in changed_files
            if item.path == scope_prefix or item.path.startswith(scope_prefix + "/")
        ]
    # The final pipeline already persists a content fingerprint. Recomputing
    # a sorted JSON serialization of a large graph on every repeated review
    # request dominated the review-cache hit path on Cruxa.
    graph_key = graph.metadata.get("graph_fingerprint") or graph_fingerprint(graph)
    plugin_fingerprint = graph.metadata.get("plugin_packs_fingerprint") or graph.metadata.get("support_pack_fingerprint") or graph.metadata.get("support_pack_versions", {})
    review_cache_key = hashlib.sha256(json.dumps({
        "mode": "review",
        "mode_contract_version": MODE_CONTRACT_VERSION,
        "graph_fingerprint": graph_key,
        # Freshness changes the safety verdict itself (a stale graph is
        # UNKNOWN, not LOW/HIGH).  Reusing a projection computed under a
        # different freshness state and replacing only the envelope produced
        # self-contradictory reports: ``fresh`` metadata with stale warnings
        # and UNKNOWN risk, or the reverse.  Keep the fast cache, but make
        # freshness part of its semantic identity.
        "freshness_state": {
            "status": freshness.get("status"),
            "stale": bool(freshness.get("stale")),
            "verified": freshness.get("verified"),
        },
        "diff_fingerprint": hashlib.sha256(diff.encode("utf-8")).hexdigest(),
        "scope": scope or ".",
        "ranking_policy_version": DEFAULT_RANKING_POLICY.version,
        "review_projection_policy_version": REVIEW_PROJECTION_POLICY_VERSION,
        "test_selection_policy_version": TEST_SELECTION_POLICY_VERSION,
        "max_results": max_results,
        "deep_or_concise": "deep" if deep else "concise",
        "plugin_packs_fingerprint": plugin_fingerprint,
        "review_schema_version": REVIEW_SCHEMA_VERSION,
        "report_schema_version": SCHEMA_VERSION,
        "review_source_kind": review_source_kind,
        "selected_base": selected_base,
        "run_tests": run_tests,
        "include_potential": include_potential,
    }, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    review_cache_path = root / ".impact_engine" / "review.json"
    if refresh != "force" and not deep and not entity and review_cache_path.is_file():
        try:
            cached_review = json.loads(review_cache_path.read_text(encoding="utf-8"))
            if cached_review.get("cache_key") == review_cache_key and cached_review.get("payload", {}).get("schema_version") == SCHEMA_VERSION:
                cached_payload = dict(cached_review.get("payload") or {})
                # The projection is reusable across equivalent graph payloads,
                # but its provenance envelope is request-local. In particular,
                # an externally supplied graph may live at a different path
                # while retaining the same fingerprint.
                cached_payload["graph_freshness"] = freshness
                cached_payload["project"] = str(root)
                cached_payload.setdefault("cache", {})["review_projection"] = "hit"
                profiler.timings["review_projection"] = time.perf_counter() - profile_started
                profiler.add_work(files_reused=1)
                cached_payload["profiling"] = profiler.snapshot()
                _attach_review_contract(cached_payload)
                return cached_payload
        except (OSError, ValueError, TypeError):
            warnings.append("review projection cache invalidated")
    changed_symbols = _changed_symbols(graph, changed_files)
    if entity and not changed_symbols:
        query = str(entity).strip().lower()
        entity_matches = [
            node for node in graph.nodes
            if query and (str(node.id).lower() == query or str(node.name).lower() == query)
        ]
        if not entity_matches:
            entity_matches = [
                node for node in graph.nodes
                if query and (query in str(node.id).lower() or query in str(node.name).lower())
            ]
        if len(entity_matches) == 1:
            selected = entity_matches[0]
            selected_file = selected.properties.get("file") or selected.properties.get("path")
            changed_symbols = [{
                "id": selected.id, "kind": selected.kind, "file": selected_file,
                "line": selected.properties.get("line"), "changed_lines": [],
                "entity_scope": True,
            }]
            warnings.append("entity-scoped review: no diff supplied; impact is anchored to the selected entity")

    changed_paths = {item.path for item in changed_files}
    changed_paths.update(str(item.get("file")) for item in changed_symbols if item.get("file"))
    coverage = _coverage(graph, changed_paths)
    projection = build_review_projection(
        graph, changed_symbols, changed_paths, max_results=max_results,
        deep=deep, coverage=coverage,
    )
    all_nodes = {
        node.id: {"id": node.id, "name": node.name, "kind": node.kind, "properties": node.properties}
        for node in graph.nodes
        if node.id in {item.entity_id for item in projection.candidates} or node.id in set(projection.changed_entities)
    }
    all_edges = {edge.id: edge.to_dict() for edge in graph.edges if edge.from_node in all_nodes or edge.to_node in all_nodes}
    suppressed = sum(1 for node in graph.nodes if _suppressed(node, allow_boundary=True))
    local_graph_path = Path(str(freshness.get("graph_path"))) if freshness.get("graph_path") else root / ".impact_engine" / "graph.json"
    if not local_graph_path.is_file():
        local_graph_path = root / "graph.json"
    def review_item(candidate: Any, *, tier: str) -> dict[str, Any]:
        item = candidate.to_dict()
        item["entity_id"] = _review_entity_id(candidate.entity_id)
        item["label"] = candidate.symbol
        item["class"] = candidate.impact_class
        item["impact_tier"] = tier
        item["line"] = next((ev.line for ev in projection.evidence if ev.id in candidate.evidence_ids and ev.line is not None), None)
        item["why_affected"] = candidate.why_affected
        item["why"] = {
            "evidence_ids": list(candidate.evidence_ids),
            "evidence_locations": [ev.to_dict() for ev in projection.evidence if ev.id in candidate.evidence_ids and (ev.file or ev.line)],
        }
        if not item["why"]["evidence_locations"]:
            item["why"]["heuristic"] = "changed symbol or file-level fallback"
            item["heuristic"] = True
        else:
            item["heuristic"] = False
        item["deep_action"] = f"impact-engine review {root} --deep --entity {candidate.entity_id} --graph {local_graph_path}"
        if tier == "possible":
            # The underlying resolver state remains available for diagnostics,
            # but a broad-discovery card intentionally never reads as proof.
            item["evidence_status"] = candidate.confidence
            item["confidence"] = "low"
            item["reason"] = candidate.discovery_reason or "low-confidence inferred relationship"
            item["why"]["reason"] = item["reason"]
            item["why"]["summary"] = "possible impact: evidence is not sufficient for the primary review"
        elif freshness.get("stale"):
            item["confidence"] = "low"
        return item

    visible = [
        review_item(candidate, tier="confirmed" if candidate.confidence == "confirmed" else "likely")
        for candidate in projection.candidates
    ]
    all_potential_impacts = [review_item(candidate, tier="possible") for candidate in projection.possible_candidates]
    # Broad discovery is intentionally a separate opt-in.  It is useful when
    # investigating a PR, but must never make the concise review look more
    # certain or noisier than the evidence supports.
    potential_impacts = all_potential_impacts if include_potential else []

    chains = []
    for chain in projection.chains:
        chain_dict = chain.to_dict()
        # The stable projection explanation contains human labels.  The
        # legacy ReviewReport chain field keeps IDs for existing consumers,
        # while technical hops remain hidden in concise mode.
        chain_node_ids = []
        for label in chain.nodes:
            node = next((item for item in graph.nodes if item.name == label), None)
            if node is not None and _chain_visible(node) and node.id not in chain_node_ids:
                chain_node_ids.append(node.id)
        chain_dict["node_ids"] = chain_node_ids
        chain_dict["evidence_locations"] = [ev.to_dict() for ev in projection.evidence if ev.id in chain.evidence_ids]
        chain_dict["edge_ids"] = [ev.id.split(":", 2)[1] for ev in projection.evidence if ev.id in chain.evidence_ids and ev.id.startswith("edge:")]
        chains.append(chain_dict)
    if not chains:
        warnings.append("no cross-file impact proven: no concise chain available")
    changed_dicts = [item.to_dict() for item in changed_files]
    changed_paths = {item.path for item in changed_files}
    affected_nodes = list(all_nodes.values())
    risk = dict(projection.risk)
    risk["confidence"] = "low" if freshness.get("stale") else risk.get("confidence", "medium")
    if freshness.get("stale"):
        risk["reasons"].append("graph is stale; high-confidence claims are suppressed")
        # A graph that is known not to represent the reviewed source cannot
        # support a safety verdict.  Lowering a numeric score still left a
        # prominent LOW headline, which reads as an approval in a PR flow.
        # Preserve evidence for investigation, but require a refresh before a
        # risk level can be asserted.
        risk.update({"level": "UNKNOWN", "confidence": "low", "reason": "graph freshness is not verified"})
    warnings.extend(_coverage_warnings(coverage))
    incomplete_coverage = any(
        item["status"] in {"unsupported", "limited"}
        and not item.get("review_usable", False)
        and not _is_test_path(item["path"])
        for item in coverage
    )
    usable_limited_coverage = any(item.get("status") == "limited" and item.get("review_usable") for item in coverage)
    if incomplete_coverage and chains:
        # Limited language coverage cannot support a *confirmed* cross-file
        # claim.  It can still support a source-backed `likely` relation (for
        # example an explicit framework factory call).  Keep those visibly
        # labelled likely chains instead of throwing useful evidence away.
        confirmed_count = sum(item.get("confidence") == "confirmed" for item in chains)
        if confirmed_count:
            chains = [item for item in chains if item.get("confidence") != "confirmed"]
            warnings.append("confirmed cross-file chains withheld because changed language coverage is incomplete")
    if incomplete_coverage:
        risk.update({"level": "UNKNOWN", "confidence": "low", "reason": "incomplete language coverage"})
        risk.setdefault("reasons", []).append("incomplete language coverage")
    elif usable_limited_coverage:
        risk.setdefault("reasons", []).append("limited compiler coverage; confirmed structural features used")
    if freshness.get("status") == "externally_supplied_unverified":
        risk["confidence"] = "low"
        risk.setdefault("reasons", []).append("external graph is not verified against the current branch")
    if semantic_diff["has_behavioral_default_change"] and any(
        item.get("kind") in {"CLASS", "FUNCTION", "METHOD"} for item in changed_symbols
    ):
        # A public default is executable API surface.  Missing downstream
        # edges must not make the review look safer; the graph may still be
        # incomplete, but the source diff proves a behavioural contract edit.
        if not freshness.get("stale") and not incomplete_coverage:
            risk["level"] = "HIGH" if risk.get("level") in {"LOW", "MEDIUM"} else risk.get("level")
            risk["score"] = max(int(risk.get("score", 0)), 5)
            risk.setdefault("reasons", []).append("typed default value changed on a callable or class API")
    test_recommendations = [] if run_tests == "none" else [item.to_dict() for item in projection.tests]
    if incomplete_coverage:
        # Do not turn limited-language evidence into a normal recommendation.
        # A source-confirmed test remains useful as an explicit *advisory*: it
        # gives the developer a concrete verification path while the report
        # still keeps its UNKNOWN risk and withholds cross-file conclusions.
        test_recommendations = [
            {
                **item,
                "advisory": True,
                "safety": "advisory_limited_coverage",
                "reason": f"{item.get('reason', 'source-confirmed targeted test')} (advisory: changed language coverage is limited)",
            }
            for item in test_recommendations
            # A nearby-test fallback remains useful under limited language
            # coverage when it carries a concrete source location.  It is
            # explicitly advisory (never promoted to a confirmed TESTS edge),
            # which keeps a comment-only TypeScript edit from claiming runtime
            # impact while still giving the developer a practical check.
            if item.get("evidence_ids")
        ]
    if not test_recommendations and semantic_diff["has_behavioral_default_change"]:
        fallback = _semantic_default_test_fallback(root, changed_symbols)
        if fallback:
            test_recommendations.append(fallback)
    test_plan = _test_plan(test_recommendations, root, changed_symbols, visible)
    if incomplete_coverage and projection.tests:
        if test_recommendations:
            warnings.append("targeted tests are advisory because changed language coverage is incomplete")
        else:
            warnings.append("no source-confirmed targeted test is available because changed language coverage is incomplete")
    if suppressed:
        warnings.append(f"{suppressed} low-value entities suppressed (assignments, built-ins, libraries, or generated files)")
    warnings.extend(projection.warnings)
    limitations = _limitations(freshness, coverage, warnings)
    all_rejected_relations = _rejected_relations(graph, changed_symbols)
    rejected_relations = all_rejected_relations if include_potential else []

    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "ok",
        "project": str(root),
        "diff_source": source,
        "source": {**source_contract, "resolved_diff": source, "selected_base": selected_base},
        "graph_freshness": freshness,
        "graph_integrity": graph_integrity,
        "changed": {"files": changed_dicts, "hunks": _hunks(changed_files), "symbols": changed_symbols, "symbol_confidence": "ast_or_graph_span" if changed_symbols and changed_symbols[0].get("line") is not None else "file_fallback"},
        "semantic_diff": semantic_diff,
        "risk": risk,
        "coverage": coverage,
        "top_impacts": visible,
        "potential_impacts": potential_impacts,
        "potential_impact": {
            "status": "included_on_explicit_request" if include_potential else "available_on_explicit_request",
            "count": len(all_potential_impacts),
            "rejected_count": len(all_rejected_relations),
            "limitation_count": len(limitations),
            "hint": "Pass include_potential=true (or --show-potential) to include possible impacts, rejected relations, and limitations.",
            "limitations": limitations if include_potential else [],
        },
        "rejected_relations": rejected_relations,
        "impact_summary": {
            "confirmed": sum(item.get("impact_tier") == "confirmed" for item in visible),
            "likely": sum(item.get("impact_tier") == "likely" for item in visible),
            "possible": len(all_potential_impacts),
            "rejected": len(all_rejected_relations),
        },
        "test_recommendations": test_recommendations,
        "test_plan": test_plan,
        "review_projection": projection.to_dict(),
        "ranking_policy": DEFAULT_RANKING_POLICY.to_dict(),
        "test_selection_policy_version": TEST_SELECTION_POLICY_VERSION,
        "chains": chains,
        "chain_summary": {
            "status": "cross_file_proven" if chains else "no_cross_file_impact_proven",
            "count": len(chains),
        },
        "warnings": sorted(set(warnings)),
        "limitations": limitations,
        "summary": _summary(risk, changed_dicts, visible, test_plan),
        "impact_groups": _impact_groups(visible),
        "areas": _areas(changed_dicts, visible),
        "actions": {"deep": deep, "suppressed_count": suppressed, "local_only": True},
        "scope": scope or ".",
        "cache": graph.metadata.get("cache", {"status": "unknown", "reason": "graph_metadata_missing"}),
        "progress": graph.metadata.get("analysis_progress", {"phase": "unknown", "completed": 0, "total": 0, "elapsed_seconds": 0.0, "eta_seconds": None, "cancellable": True}),
        "incomplete": bool(incomplete_coverage or graph.metadata.get("incomplete")),
        "contract_compatibility": {"previous_schema_version": "ReviewReport/v1", "legacy_fields_preserved": True},
    }
    profiler.timings["review_projection"] = time.perf_counter() - profile_started
    profiler.add_work(
        files_seen=len(changed_files),
        facts_reused=len(graph.nodes),
        edges_reused=len(graph.edges),
    )
    payload["profiling"] = profiler.snapshot()
    if deep:
        selected_entity = entity or (visible[0]["entity_id"] if visible else None)
        if selected_entity:
            payload["deep_result"] = impact_query(graph, target=selected_entity, direction="both", max_depth=20, min_confidence=0.0)
            payload["actions"]["selected_entity"] = selected_entity
    _attach_review_contract(payload)
    try:
        write_json_atomic(review_cache_path, {"schema_version": SCHEMA_VERSION, "cache_key": review_cache_key, "payload": payload})
    except OSError:
        payload.setdefault("warnings", []).append("review projection cache write failed")
    return payload


def _safe_argv(command: Any) -> list[str] | None:
    """Expose executable test argv without ever interpreting a shell string."""
    if isinstance(command, list) and all(isinstance(item, str) and item for item in command):
        argv = list(command)
    elif isinstance(command, str) and command.strip():
        if any(token in command for token in ("\n", "\r", "|", "&&", ";", "`", "$(`")):
            return None
        try:
            argv = shlex.split(command, posix=False)
        except ValueError:
            return None
    else:
        return None
    if not argv or any("\x00" in item or "\n" in item or "\r" in item for item in argv):
        return None
    return argv


def _semantic_default_test_fallback(root: Path, changed_symbols: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Offer a clearly advisory suite when a public default changed.

    This is not a claimed TESTS edge.  It is a conservative operational
    fallback for a source-proven API change when graph coverage has not yet
    reached an exact test.  The command still goes through the usual separate
    confirmation flow.
    """
    test_dir = next((candidate for candidate in (root / "tests", root / "test") if candidate.is_dir()), None)
    if test_dir is None or not any(path.suffix == ".py" for path in test_dir.rglob("*.py")):
        return None
    return {
        "file": test_dir.relative_to(root).as_posix(),
        "symbol": changed_symbols[0].get("id") if changed_symbols else None,
        "category": "semantic_default_fallback_suite",
        "confidence": "likely",
        "evidence_ids": [],
        "reason": "typed default value changed; run the local Python test suite as an advisory fallback",
        "command": ["pytest", test_dir.relative_to(root).as_posix()],
        "fallback_status": "semantic_advisory",
        "advisory": True,
    }


def _test_plan(recommendations: list[dict[str, Any]], root: Path, changed_symbols: list[dict[str, Any]], impacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    covered = sorted({str(item.get("symbol")) for item in recommendations if item.get("symbol")})
    affected = {str(item.get("entity_id")) for item in impacts if item.get("entity_id")}
    changed = {str(item.get("id")) for item in changed_symbols if item.get("id")}
    uncovered = sorted((changed | affected) - set(covered))
    plan = []
    for recommendation in recommendations:
        argv = _safe_argv(recommendation.get("command"))
        advisory = bool(recommendation.get("advisory")) or recommendation.get("fallback_status") != "primary"
        plan.append({
            "argv": argv,
            "cwd": str(root),
            "runner": Path(argv[0]).name if argv else None,
            "reason": recommendation.get("reason") or "Suggested from local evidence",
            "confidence": recommendation.get("confidence", "unknown"),
            "safety": (
                "advisory_confirmation_required" if advisory and argv
                else "advisory_not_runnable_without_manual_command" if advisory
                else "confirmation_required" if argv
                else "not_runnable_without_manual_command"
            ),
            "advisory": advisory,
            "covered_entities": [recommendation.get("symbol")] if recommendation.get("symbol") else [],
            "uncovered_entities": uncovered,
            "file": recommendation.get("file"),
            "category": recommendation.get("category"),
        })
    return plan


def _rejected_relations(graph: GraphDocument, changed_symbols: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return explicitly rejected relations near the changed source.

    Rejected candidates are diagnostics, never impact.  Keeping them in an
    opt-in category makes a framework heuristic auditable without accidentally
    promoting a rejected route or call into filtering, ranking, or test
    selection.
    """
    changed_ids = {str(item.get("id") or "") for item in changed_symbols}
    changed_files = {str(item.get("file") or "").replace("\\", "/") for item in changed_symbols if item.get("file")}
    if not changed_ids and not changed_files:
        return []
    relations: list[dict[str, Any]] = []
    for edge in graph.edges:
        quality = classify_edge_quality(edge)
        evidence_files = {
            str(item.file or "").replace("\\", "/")
            for item in edge.evidence
            if item.file
        }
        touches_changed_source = bool({edge.from_node, edge.to_node} & changed_ids) or bool(evidence_files & changed_files)
        if quality.status != "rejected" or not touches_changed_source:
            continue
        relations.append({
            "edge_id": edge.id,
            "from": edge.from_node,
            "to": edge.to_node,
            "kind": edge.kind,
            "confidence": "none",
            "reason": "; ".join(quality.reasons) or "explicitly rejected relationship",
            "evidence_locations": [item.to_dict() for item in edge.evidence[:4]],
        })
    return sorted(relations, key=lambda item: (str(item["from"]), str(item["to"]), str(item["edge_id"])))[:50]


def _limitations(freshness: dict[str, Any], coverage: list[dict[str, Any]], warnings: list[str]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    if freshness.get("stale"):
        items.append({"kind": "stale_graph", "message": "The analysis graph may not match the current project.", "action": "Refresh the graph, then run the review again."})
    for item in coverage:
        if item.get("status") in {"limited", "unsupported"}:
            items.append({"kind": str(item["status"]), "message": f"{item.get('path')} has {item.get('status')} coverage.", "action": "Review the changed area manually and run its focused tests."})
        elif item.get("may_be_incomplete"):
            items.append({"kind": "bounded_semantic_coverage", "message": f"{item.get('path')} has exact import-call coverage, but full type/data-flow resolution was bounded for scale.", "action": "Treat shown chains as proven; use Potential impact and focused tests for unresolved dynamic consumers."})
    if not items and warnings:
        items.append({"kind": "review_warning", "message": "Some evidence could not be shown in the concise review.", "action": "Open Architecture or inspect the affected item for detail."})
    return items


def _impact_groups(impacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for impact in impacts:
        grouped.setdefault(str(impact.get("class") or "affected"), []).append(impact)
    return [{"kind": kind, "label": kind.replace("_", " "), "count": len(items), "entities": [item.get("entity_id") for item in items]} for kind, items in sorted(grouped.items())]


def _areas(changed: list[dict[str, Any]], impacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    paths = {str(item.get("path")) for item in changed if item.get("path")}
    paths.update(str(item.get("file")) for item in impacts if item.get("file"))
    return [{"path": path, "kind": "changed" if any(item.get("path") == path for item in changed) else "affected"} for path in sorted(paths)]


def _summary(risk: dict[str, Any], changed: list[dict[str, Any]], impacts: list[dict[str, Any]], test_plan: list[dict[str, Any]]) -> dict[str, Any]:
    return {"headline": f"{risk.get('level', 'UNKNOWN')} risk across {len(changed)} changed file(s)", "risk_level": risk.get("level", "UNKNOWN"), "changed_file_count": len(changed), "affected_count": len(impacts), "runnable_test_count": sum(1 for item in test_plan if item.get("argv"))}


def _attach_review_contract(payload: dict[str, Any]) -> dict[str, Any]:
    """Add the common mode envelope while preserving legacy review actions."""

    legacy = dict(payload.get("actions") or {})
    legacy.pop("items", None)
    items = [
        action("refresh-graph", "refresh_graph", "Refresh graph", payload={"project_path": payload.get("project")}),
        action("view-coverage", "view_coverage", "View coverage", payload={"coverage": payload.get("coverage", [])}),
    ]
    for item in (payload.get("top_impacts") or [])[:10]:
        entity_id = item.get("entity_id")
        if entity_id:
            items.append(action(
                f"inspect-{entity_id}", "inspect_entity", "Inspect impact",
                payload={"project_path": payload.get("project"), "entity": entity_id},
            ))
            items.append(action(
                f"investigate-{entity_id}", "investigate_entity", "Investigate impact",
                payload={"project_path": payload.get("project"), "entity": entity_id},
            ))
        file_name = item.get("file") or item.get("path")
        if file_name:
            items.append(action(f"open-{entity_id or file_name}", "open_file", "Open impact file", payload={"file": file_name, "line": item.get("line")}))
    for test in (payload.get("test_recommendations") or [])[:10]:
        if test.get("file"):
            items.append(action(
                f"test-{test.get('file')}", "run_recommended_test", "Run recommended test",
                payload={"project_path": payload.get("project"), "file": test.get("file"), "command": test.get("command")},
            ))
    for warning in (payload.get("warnings") or [])[:10]:
        items.append(action(
            f"ack-{hashlib.sha256(str(warning).encode('utf-8')).hexdigest()[:12]}", "acknowledge_warning", "Acknowledge warning",
            payload={"warning": warning},
        ))
    attach_mode_contract(payload, "review", schema_version=SCHEMA_VERSION, actions=items, legacy_actions=legacy)
    return payload


def _resolve_graph(root: Path, graph: GraphDocument | None, refresh: str, warnings: list[str], base: str | None = None, graph_path: str | Path | None = None, scope: str | None = None) -> tuple[GraphDocument, dict[str, Any]]:
    explicit_path = Path(graph_path).expanduser().resolve() if graph_path else None
    if explicit_path is not None:
        if not explicit_path.is_file():
            raise FileNotFoundError(f"Graph path does not exist: {explicit_path}")
        if graph is None:
            graph = GraphDocument.from_json(explicit_path.read_text(encoding="utf-8"))
        path = explicit_path
        age = max(0.0, time.time() - path.stat().st_mtime)
        graph_fp = graph.metadata.get("graph_fingerprint") or graph_fingerprint(graph)
        freshness = {
            "fingerprint": graph_fp, "graph_path": str(path), "external_graph": True,
            "branch": _git(root, ["branch", "--show-current"]), "head": _git(root, ["rev-parse", "HEAD"]),
            "base": base, "age_seconds": round(age, 3), "refresh_mode": refresh,
            "stale": True, "status": "externally_supplied_unverified", "verified": False,
            "freshness_assertion": "external graph timestamp/fingerprint only",
            "scan_plan_hash": None, "extractor_versions": graph.metadata.get("extractor_versions", {}),
            "support_pack_versions": graph.metadata.get("support_pack_versions", {}),
        }
        warnings.append("external graph supplied; project graph freshness is not asserted")
        return graph, freshness
    path = next((p for p in (root / ".impact_engine" / "graph.json", root / "graph.json") if p.is_file()), None)
    stale = False
    loaded_from_project_cache = graph is None and path is not None
    if graph is None and path:
        graph = GraphDocument.from_json(path.read_text(encoding="utf-8"))
    # ``snapshot.json`` is the current persistent-cache artifact.  Retain the
    # old filename for repositories created by earlier CodeSlicer versions.
    # A disk graph without either snapshot cannot prove source freshness.
    snapshot_path = next(
        (candidate for candidate in (
            root / ".impact_engine" / "project.snapshot.json",
            root / ".impact_engine" / "snapshot.json",
        ) if candidate.is_file()),
        None,
    )
    # A first review has no persisted snapshot yet, but a successful full
    # refresh must still create one.  Keep the existing-path sentinel above
    # for freshness and incremental decisions; use this canonical destination
    # only when persisting a newly generated snapshot.
    snapshot_write_path = snapshot_path or root / ".impact_engine" / "project.snapshot.json"
    snapshot_changed = False
    snapshot_unverified = loaded_from_project_cache and snapshot_path is None
    refresh_status = "reused" if graph is not None else "full_refresh"
    fallback_reason = None
    if snapshot_path is not None and refresh in {"auto", "never"}:
        try:
            from impact_engine.incremental import project_snapshot
            previous = json.loads(snapshot_path.read_text(encoding="utf-8"))
            snapshot_changed = previous != project_snapshot(root)
        except Exception:
            snapshot_changed = True
    if graph is None and refresh == "never":
        graph = GraphDocument(metadata={"project_path": str(root)})
        warnings.append("graph is missing; refresh was disabled")
        return graph, {
            "status": "missing", "stale": True, "verified": False,
            "graph_path": None, "refresh_mode": refresh,
            "fallback_reason": "graph_missing_refresh_disabled",
        }
    if graph is None or refresh == "force" or (refresh == "auto" and path is not None):
        from impact_engine.analysis.pipeline import analyze_project_core
        try:
            if refresh == "auto" and path and path.exists() and snapshot_path is not None:
                from impact_engine.incremental import incremental_update, load_snapshot, save_snapshot
                result = incremental_update(
                    str(root),
                    lambda changed: analyze_project_core(
                        str(root), out_path=None, changed_files=changed,
                        raw_graph_cache_path=str(_raw_graph_cache_path(root, scope)), scope=scope,
                    ),
                    load_snapshot(snapshot_path), str(root / ".impact_engine" / "graph.json"), str(path),
                    scope=scope, previous_graph=graph,
                )
                if result.get("incremental", {}).get("requires_full_refresh"):
                    warnings.append("incremental candidate was incomplete; ran a full refresh to preserve graph coverage")
                    result = analyze_project_core(
                        str(root), out_path=str(root / ".impact_engine" / "graph.json"),
                        raw_graph_cache_path=str(_raw_graph_cache_path(root, scope)), scope=scope,
                    )
                    from impact_engine.incremental import project_snapshot, save_snapshot
                    save_snapshot(project_snapshot(root), snapshot_path)
                    refresh_status = "full_refresh_after_partial_candidate"
                    fallback_reason = "incremental_candidate_not_proven_whole_project_graph"
                else:
                    save_snapshot(result["incremental"]["snapshot"], snapshot_path)
                    refresh_status = "compatibility_full_refresh" if result.get("selective_execution", {}).get("execution_mode") == "full_pipeline_compatibility" else str(result.get("incremental", {}).get("status", "updated"))
                    fallback_reason = result.get("selective_execution", {}).get("reason")
            else:
                result = analyze_project_core(
                    str(root), out_path=str(root / ".impact_engine" / "graph.json"),
                    raw_graph_cache_path=str(_raw_graph_cache_path(root, scope)), scope=scope,
                )
                if refresh == "auto":
                    from impact_engine.incremental import project_snapshot, save_snapshot
                    save_snapshot(project_snapshot(root), snapshot_write_path)
                refresh_status = "full_refresh"
                fallback_reason = "snapshot_missing_or_graph_missing"
            graph = GraphDocument.from_dict(result["graph"])
            path = Path(result.get("graph_path") or root / ".impact_engine" / "graph.json")
        except Exception as exc:
            stale = True
            warnings.append(f"graph refresh failed; using last local graph: {exc}")
            if graph is None:
                graph = GraphDocument(metadata={"project_path": str(root)})
                path = None
                freshness = {
                    "status": "missing", "stale": True, "verified": False,
                    "graph_path": None, "refresh_mode": refresh,
                    "fallback_reason": "graph_missing_and_refresh_failed",
                }
                warnings.append("graph is missing; run a local analysis before relying on impact results")
                return graph, freshness
    elif refresh == "never":
        # A supplied graph does not override a concrete stale snapshot.  The
        # caller may choose the graph artifact, but it is still a claim about
        # this workspace and must not look fresh when its recorded source set
        # differs.  Only the absence of a snapshot is specific to a graph
        # loaded from the project cache.
        if snapshot_changed:
            stale = True
            warnings.append("graph snapshot differs from working tree")
        elif loaded_from_project_cache and snapshot_unverified:
            stale = True
            warnings.append("graph source snapshot is unavailable; freshness cannot be verified")
    assert graph is not None
    age = max(0.0, time.time() - path.stat().st_mtime) if path and path.exists() else 0.0
    graph_fp = graph.metadata.get("graph_fingerprint") or graph_fingerprint(graph)
    scan_plan = root / ".impact_engine" / "scan_plan.json"
    scan_plan_hash = hashlib.sha256(scan_plan.read_bytes()).hexdigest() if scan_plan.is_file() else None
    freshness = {
        "fingerprint": graph_fp,
        "graph_path": str(path) if path else None,
        "branch": _git(root, ["branch", "--show-current"]),
        "head": _git(root, ["rev-parse", "HEAD"]),
        "base": base,
        "age_seconds": round(age, 3),
        "refresh_mode": refresh,
        "stale": stale,
        "scan_plan_hash": scan_plan_hash,
        "extractor_versions": graph.metadata.get("extractor_versions", {}),
        "support_pack_versions": graph.metadata.get("support_pack_versions", {}),
        "refresh_status": refresh_status,
        "fallback_reason": fallback_reason,
    }
    freshness["status"] = "stale" if stale else "fresh"
    if not graph.metadata.get("graph_fingerprint"):
        warnings.append("graph fingerprint was not recorded; computed locally")
    return graph, freshness


def _exclude_graphify_from_default_review(graph: GraphDocument, warnings: list[str]) -> GraphDocument:
    """Keep legacy Graphify imports readable without letting them rank Review."""
    graphify_document = graph.metadata.get("adapter") == "graphify" or graph.metadata.get("source") == "graphify"
    graphify_nodes = {node.id for node in graph.nodes if graphify_document or node.properties.get("external_tool") == "graphify"}
    graphify_edges = [edge for edge in graph.edges if edge.properties.get("external_tool") == "graphify"]
    if not graphify_nodes and not graphify_edges:
        return graph
    filtered = GraphDocument(metadata={**graph.metadata, "graphify_overlay_excluded_from_review": True})
    for node in graph.nodes:
        if node.id not in graphify_nodes:
            filtered.add_node(node)
    for edge in graph.edges:
        if graphify_document or edge.properties.get("external_tool") == "graphify" or edge.from_node in graphify_nodes or edge.to_node in graphify_nodes:
            continue
        filtered.add_edge(edge)
    warnings.append("Graphify overlay is available only for explicit Architecture/Investigate views; default Review ranking is CodeSlicer-only")
    return filtered


def _resolve_diff(root: Path, diff_text: str | None, source: str | None, base: str | None) -> tuple[str, str]:
    if diff_text is not None:
        return diff_text, source or "provided"
    if source == "staged":
        return _git(root, ["diff", "--cached", "--unified=0"]) or "", "staged"
    if base:
        value = _git(root, ["diff", "--unified=0", f"{base}...HEAD"])
        if value is not None:
            working = _working_tree_diff(root)
            if working:
                return "\n".join(part for part in (value, working) if part), f"base:{base}...HEAD+working-tree"
            return value, f"base:{base}...HEAD"
    git_root = _git(root, ["rev-parse", "--show-toplevel"])
    if git_root:
        try:
            if Path(git_root.strip()).expanduser().resolve() != root.resolve():
                return "", "project-not-a-git-repository"
        except OSError:
            return "", "project-not-a-git-repository"
    return _working_tree_diff(root), "working-tree:staged+unstaged-fallback"


def _git(root: Path, args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=20,
        )
        if result.returncode == 0:
            return result.stdout
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def _working_tree_diff(root: Path) -> str:
    unstaged = _git(root, ["diff", "--unified=0"]) or ""
    staged = _git(root, ["diff", "--cached", "--unified=0"]) or ""
    return "\n".join(part for part in (unstaged, staged) if part)


def _bounded_projection(
    graph: GraphDocument,
    target: str,
    *,
    direction: str,
    max_depth: int,
    min_confidence: float,
    max_nodes: int = 40,
    max_edges: int = 80,
    max_branching: int = 6,
) -> dict[str, Any]:
    """Priority traversal used by default review.

    It stops expanding once the bounded evidence budget is exhausted; the
    legacy ``impact_query`` remains reserved for explicit deep investigation.
    """
    graph._ensure_indexes()
    node_by_id = {node.id: node for node in graph.nodes}
    out_adj: dict[str, list[Any]] = {}
    in_adj: dict[str, list[Any]] = {}
    for edge in graph.edges:
        if edge.from_node not in node_by_id or edge.to_node not in node_by_id:
            continue
        if edge.confidence < min_confidence or not edge_is_active_for_impact(edge):
            continue
        out_adj.setdefault(edge.from_node, []).append(edge)
        in_adj.setdefault(edge.to_node, []).append(edge)
    for values in (*out_adj.values(), *in_adj.values()):
        values.sort(key=lambda edge: (-edge.confidence, edge.kind, edge.id))

    matched = node_by_id.get(target)
    queue: list[tuple[float, int, str, tuple[str, ...], tuple[str, ...]]] = [(0.0, 0, target, (), (target,))]
    visited = {target}
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    paths: list[dict[str, Any]] = []
    while queue and len(nodes) < max_nodes and len(edges) < max_edges:
        neg_score, depth, current, path_edges, path_nodes = heapq.heappop(queue)
        if depth >= max_depth:
            continue
        adjacent = []
        if direction in {"downstream", "both"}:
            adjacent.extend(out_adj.get(current, []))
        if direction in {"upstream", "both"}:
            adjacent.extend(in_adj.get(current, []))
        for edge in adjacent[:max_branching]:
            next_id = edge.to_node if edge.from_node == current else edge.from_node
            if next_id in path_nodes or next_id in visited:
                continue
            if len(edges) >= max_edges or len(nodes) >= max_nodes:
                break
            visited.add(next_id)
            edge_dict = {
                "id": edge.id, "kind": edge.kind, "from": edge.from_node, "to": edge.to_node,
                "confidence": edge.confidence, "source": edge.source,
                "evidence": [item.to_dict() for item in edge.evidence],
            }
            edges[edge.id] = edge_dict
            node = node_by_id.get(next_id)
            if node is not None:
                nodes[next_id] = {"id": node.id, "name": node.name, "kind": node.kind, "properties": node.properties}
            confidence = min(edge.confidence, -neg_score if neg_score else edge.confidence)
            new_path_edges = path_edges + (edge.id,)
            new_path_nodes = path_nodes + (next_id,)
            paths.append({"target": next_id, "depth": depth + 1, "confidence": confidence, "status": "confirmed" if confidence >= .9 else "likely", "edges": list(new_path_edges)})
            heapq.heappush(queue, (-confidence, depth + 1, next_id, new_path_edges, new_path_nodes))

    ranking = [
        {"node_id": item["target"], "impact_score": round(float(item["confidence"]) / max(1, int(item["depth"])), 6), "distance": item["depth"]}
        for item in paths
    ]
    if matched is None and target not in nodes:
        return {"matched_nodes": [], "affected_nodes": list(nodes.values()), "affected_edges": list(edges.values()), "impact_paths": paths, "impact_ranking": ranking, "warnings": ["no_matching_node_or_edge_endpoint"]}
    return {"matched_nodes": [{"id": matched.id, "name": matched.name, "kind": matched.kind, "properties": matched.properties}] if matched else [], "affected_nodes": list(nodes.values()), "affected_edges": list(edges.values()), "impact_paths": paths, "impact_ranking": ranking, "warnings": []}


def _candidate(node: dict[str, Any], score: float, factors: list[str], edge_ids: list[str], line: Any) -> dict[str, Any]:
    properties = node.get("properties") or {}
    return {"entity_id": node["id"], "label": node.get("name") or node["id"], "kind": node.get("kind", "SYMBOL"), "class": "direct" if "direct_changed_symbol" in factors else "transitive", "rank_score": round(float(score), 6), "score_factors": factors, "confidence": "medium", "why": {"edge_ids": edge_ids, "evidence_locations": []}, "line": line, "file": properties.get("file") or properties.get("path")}


def _merge_candidate(old: dict[str, Any] | None, new: dict[str, Any]) -> dict[str, Any]:
    if old is None or (new["rank_score"], new["entity_id"]) > (old["rank_score"], old["entity_id"]):
        return new
    old["score_factors"] = sorted(set(old["score_factors"] + new["score_factors"]))
    return old


def _node_by_id(graph: GraphDocument, node_id: str):
    return next((node for node in graph.nodes if node.id == node_id), None)


def _diversify_visible(items: list[dict[str, Any]], changed_paths: set[str], limit: int) -> list[dict[str, Any]]:
    """Keep daily cards useful when one changed file contains many symbols."""
    if limit <= 0:
        return []
    ordered = sorted(items, key=lambda x: (-float(x["rank_score"]), x["entity_id"]))
    selected: list[dict[str, Any]] = []
    per_file: dict[str, int] = {}
    max_per_file = 3
    for item in ordered:
        file_name = str(item.get("file") or "")
        if not file_name:
            node_file = str(item.get("entity_id", "")).split(":", 1)[0]
            file_name = node_file
        if per_file.get(file_name, 0) >= max_per_file:
            continue
        per_file[file_name] = per_file.get(file_name, 0) + 1
        selected.append(item)
        if len(selected) >= limit:
            break
    return selected


def _suppressed(node, allow_boundary: bool = False) -> bool:
    props = node.properties or {}
    file_name = str(props.get("file") or props.get("path") or "").lower()
    kind = node.kind.upper()
    if kind == "CALL_EXPR":
        boundary = bool(props.get("boundary") or props.get("is_boundary") or props.get("api_boundary"))
        boundary = boundary or str(props.get("role") or props.get("semantic_role") or "").lower() in {"api", "route", "queue", "database", "http", "rpc"}
        if not (allow_boundary and boundary):
            return True
    return kind in SUPPRESSED_KINDS - {"CALL_EXPR"} or kind == "LIBRARY" or bool(props.get("generated")) or any(part in file_name for part in ("/generated/", "/dist/", "/build/", "/vendor/", "\\generated\\", "\\vendor\\"))


def _evidence_for_item(item: dict[str, Any], edges: dict[str, dict[str, Any]], graph: GraphDocument) -> dict[str, Any]:
    ids, locations = [], []
    for edge in edges.values():
        if item["entity_id"] not in {edge.get("from"), edge.get("to")}:
            continue
        ids.append(edge["id"])
        for ev in edge.get("evidence", []):
            if ev.get("file") or ev.get("line"):
                locations.append({"file": ev.get("file"), "line": ev.get("line"), "description": ev.get("description", "")})
    return {"edge_ids": sorted(set(ids)), "locations": locations[:10]}


def _select_chains(paths: list[dict[str, Any]], edges: dict[str, dict[str, Any]], graph: GraphDocument, max_count: int) -> list[dict[str, Any]]:
    selected, boundaries = [], set()
    for path in sorted(paths, key=lambda p: (-float(p.get("confidence", 0)), int(p.get("depth", 0)), str(p.get("target", "")))):
        edge_ids = list(path.get("edges", []))[:5]
        if not edge_ids or len(set(edge_ids)) != len(edge_ids):
            continue
        first = edges.get(edge_ids[0], {})
        boundary = first.get("kind", "unknown")
        if boundary in boundaries and len(selected) < max_count:
            continue
        boundaries.add(boundary)
        evidence = []
        ordered_nodes = _walk_edge_nodes(edge_ids, edges)
        for edge_id in edge_ids:
            edge = edges.get(edge_id, {})
            if _node_by_id(graph, edge.get("from")) is None or _node_by_id(graph, edge.get("to")) is None:
                ordered_nodes = []
                break
            evidence.extend(edge.get("evidence", []))
        meaningful_ids = []
        for node_id in ordered_nodes:
            node = _node_by_id(graph, node_id)
            if node is not None and _chain_visible(node) and node_id not in meaningful_ids:
                meaningful_ids.append(node_id)
        if len(meaningful_ids) < 2:
            continue
        if not evidence:
            continue
        selected.append({
            "target": meaningful_ids[-1],
            "node_ids": meaningful_ids,
            "status": path.get("status", "likely"),
            "confidence": path.get("confidence", 0),
            "edge_ids": edge_ids,
            "evidence_locations": evidence[:10],
        })
        if len(selected) >= max_count:
            break
    return selected


def _review_entity_id(entity_id: str) -> str:
    """Collapse extractor kind aliases in the legacy concise card only."""
    for prefix in ("method:", "function:", "class:"):
        if entity_id.startswith(prefix):
            return entity_id[len(prefix):]
    return entity_id


def _chain_visible(node) -> bool:
    """Nodes allowed in concise chains; technical hops are only deep context."""
    return node.kind.upper() not in {
        "CALL_EXPR", "ASSIGNMENT", "EXTERNAL_LIBRARY", "SUPPORT_PACK", "LIBRARY",
    } and not bool((node.properties or {}).get("generated"))


def _walk_edge_nodes(edge_ids: list[str], edges: dict[str, dict[str, Any]]) -> list[str]:
    """Recover an undirected path for traversal paths that mix directions."""
    if not edge_ids:
        return []
    first = edges.get(edge_ids[0], {})
    starts = [first.get("from"), first.get("to")]
    walks: list[list[str]] = []
    for start in starts:
        if not start:
            continue
        walk = [start]
        for edge_id in edge_ids:
            edge = edges.get(edge_id, {})
            current = walk[-1]
            if current == edge.get("from"):
                walk.append(edge.get("to"))
            elif current == edge.get("to"):
                walk.append(edge.get("from"))
            else:
                walk = []
                break
        if walk:
            walks.append(walk)
    return max(walks, key=len, default=[])


def _review_graph_integrity(graph: GraphDocument) -> dict[str, Any]:
    """Return the strict endpoint contract used by concise review.

    Alias metadata may help diagnostics, but it cannot make an edge safe for
    daily review: projection requires both literal endpoint IDs to exist.
    """
    node_ids = {node.id for node in graph.nodes}
    missing_by_kind: dict[str, int] = {}
    dangling = 0
    for edge in graph.edges:
        if edge.from_node in node_ids and edge.to_node in node_ids:
            continue
        dangling += 1
        missing_by_kind[edge.kind] = missing_by_kind.get(edge.kind, 0) + 1
    edge_count = len(graph.edges)
    return {
        "status": "warning" if dangling else "ok",
        "node_count": len(graph.nodes),
        "edge_count": edge_count,
        "dangling_endpoint_edges": dangling,
        "dangling_endpoint_ratio": round(dangling / edge_count, 6) if edge_count else 0.0,
        "edges_by_kind_with_missing_endpoint": dict(sorted(missing_by_kind.items())),
        "concise_policy": "exclude_dangling_edges",
    }


def _coverage(graph: GraphDocument, paths: set[str]) -> list[dict[str, Any]]:
    language_capabilities = graph.metadata.get("language_semantic_capabilities", {}) or {}
    csharp_features = graph.metadata.get("csharp_framework_features", {}) or {}
    csharp_usable_features = sorted({feature for item in csharp_features.values() if isinstance(item, dict) and item.get("review_usable") for feature in item.get("review_usable_features", []) or []})
    result = []
    precision = graph.metadata.get("precision_resolution", {}) or {}
    partial_exact = precision.get("status") == "partial_exact_import_resolution"
    for path in sorted(paths):
        suffix = Path(path).suffix.lower()
        language = {".py": "python", ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".ts": "typescript", ".tsx": "typescript", ".mts": "typescript", ".cts": "typescript", ".go": "go", ".java": "java", ".cs": "csharp", ".c": "cpp", ".h": "cpp", ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp", ".hh": "cpp", ".hpp": "cpp", ".hxx": "cpp", ".rs": "rust", ".kt": "kotlin", ".kts": "kotlin", ".php": "php", ".rb": "ruby", ".html": "html", ".htm": "html", ".xhtml": "html", ".css": "css", ".scss": "css", ".sass": "css", ".less": "css", ".vue": "vue", ".svelte": "svelte", ".astro": "astro"}.get(suffix, "unknown")
        cap = language_capabilities.get(language, {}) if isinstance(language_capabilities, dict) else {}
        capability_values = cap.get("capabilities", cap) if isinstance(cap, dict) else {}
        production = bool(capability_values.get("production_semantic_baseline"))
        declared_call_resolution = str(capability_values.get("call_resolution") or "none")
        call_resolution = "bounded_exact_imports" if language == "python" and partial_exact else declared_call_resolution
        if suffix not in SUPPORTED_SUFFIXES or not capability_values:
            status = "unsupported"
        elif production and (declared_call_resolution == "semantic" or partial_exact):
            status = "supported"
        else:
            status = "limited"
        declared_features = capability_values.get("review_usable_features", []) if isinstance(capability_values, dict) else []
        if not isinstance(declared_features, list):
            declared_features = []
        if language == "csharp":
            review_features = csharp_usable_features
            review_usable = bool(review_features)
            review_reason = "framework feature coverage is enabled" if review_usable else "no review-usable framework features were recorded"
        elif "review_usable" in capability_values:
            review_usable = bool(capability_values.get("review_usable"))
            review_features = sorted({str(item) for item in declared_features})
            review_reason = "declared by the language capability contract"
        elif partial_exact and language == "python":
            review_usable = True
            review_features = ["source_declarations", "local_imports", "exact_import_call_resolution"]
            review_reason = "bounded exact import-call resolution completed; full type/data-flow resolution was skipped for scale"
        elif status == "supported":
            review_usable = True
            review_features = ["source_declarations", "local_imports", "semantic_call_resolution"]
            review_reason = "production semantic baseline with semantic call resolution"
        else:
            review_usable = False
            review_features = []
            review_reason = "semantic review coverage is partial or unavailable"
        result.append({
            "language": language, "path": path, "status": status,
            "extractor": cap.get("provider_id") or cap.get("extractor") if isinstance(cap, dict) else None,
            "resolver": call_resolution,
            "production_semantic_baseline": production,
            "may_be_incomplete": status != "supported" or (language == "python" and partial_exact),
            "review_usable": review_usable,
            "review_usable_features": review_features,
            "review_usable_reason": review_reason,
        })
    return result


def _coverage_warnings(coverage: list[dict[str, Any]]) -> list[str]:
    warnings = [f"coverage for {item['path']} is {item['status']}" for item in coverage if item["status"] in {"unsupported", "limited"}]
    warnings.extend(
        f"coverage for {item['path']} is bounded: exact import calls are available, full type/data-flow resolution was skipped"
        for item in coverage
        if item.get("may_be_incomplete") and item["status"] == "supported"
    )
    return warnings


def _is_test_path(path: str) -> bool:
    parts = {part.lower() for part in Path(path).parts}
    name = Path(path).name.lower()
    return bool(parts & {"test", "tests", "spec", "specs"}) or name.startswith(("test_", "test.", "spec_", "spec."))


def _test_items(tests: dict[str, list[dict[str, Any]]], edges: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for category in ("required", "recommended"):
        for item in tests.get(category, []):
            result.append({**item, "priority": category, "evidence": [{"edge_id": e["id"], "locations": e.get("evidence", [])} for e in edges.values() if item.get("node") in {e.get("from"), e.get("to")}][:3], "heuristic": category == "recommended"})
    return result


def _hunks(files) -> list[dict[str, Any]]:
    return [{"path": item.path, "added_lines": item.to_dict()["lines"]} for item in files]
