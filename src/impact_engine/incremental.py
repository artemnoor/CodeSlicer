"""Safe incremental analysis primitives.

The first implementation is correctness-first: it fingerprints files, runs the
configured analyzer, and atomically replaces the previous graph only when the
new graph passes validation. This gives callers a safe incremental contract
without pretending that a partial extractor result is complete.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import inspect
from pathlib import Path
from typing import Any, Callable

from impact_engine.graph_quality import annotate_graph_quality
from impact_engine.models import GraphDocument, FactDocument, diff_fact_documents
from impact_engine.persistence import AtomicCacheStore
from impact_engine.incremental_index import affected_closure
from impact_engine.resolver_registry import list_resolver_contracts
from impact_engine.selective_execution import ResolverExecutionPlan, ResolverContextBuilder
from impact_engine.security import validate_project_path
from impact_engine.persistence import (
    CancellationToken,
    project_snapshot as persistent_project_snapshot,
    project_snapshot_stats,
)


SNAPSHOT_SCHEMA_VERSION = 2
MAX_INCREMENTAL_FACT_DELTA = 5_000
MAX_INCREMENTAL_GRAPH_NODES = 30_000
MAX_INCREMENTAL_CALL_SITES = 12_000


def project_snapshot_state(
    project_path: str | Path,
    previous_snapshot: dict[str, Any] | None = None,
    scope: str | None = None,
) -> dict[str, Any]:
    """Return a versioned snapshot and reuse hashes for unchanged files.

    The persistent cache remains the source of truth for scope decisions.  The
    stat record is only a fast path: a changed size or mtime always causes a
    content hash to be recomputed.
    """
    root = validate_project_path(project_path)
    previous_files = previous_snapshot.get("files", {}) if isinstance(previous_snapshot, dict) else {}
    stats = project_snapshot_stats(root, scope)
    files: dict[str, dict[str, int | str]] = {}
    for relative, stat in stats.items():
        prior = previous_files.get(relative) if isinstance(previous_files, dict) else None
        if (
            isinstance(prior, dict)
            and prior.get("size") == stat.get("size")
            and prior.get("mtime_ns") == stat.get("mtime_ns")
            and isinstance(prior.get("sha256"), str)
        ):
            digest = prior["sha256"]
        else:
            try:
                digest = hashlib.sha256((root / relative).read_bytes()).hexdigest()
            except OSError:
                continue
        files[relative] = {
            "size": int(stat.get("size", 0)),
            "mtime_ns": int(stat.get("mtime_ns", 0)),
            "sha256": digest,
        }
    return {"schema_version": SNAPSHOT_SCHEMA_VERSION, "files": files}


def normalize_changed_files(project_path: str | Path, paths: list[str] | None) -> list[str] | None:
    """Canonicalize editor or Git paths and reject paths outside the project."""
    if paths is None:
        return None
    root = validate_project_path(project_path)
    normalized: set[str] = set()
    for value in paths:
        # Git and editors can report a relative path with either separator,
        # regardless of the host where CodeSlicer is running.  Normalize the
        # transport representation before asking the host filesystem to
        # resolve it; otherwise Linux treats ``nested\\main.py`` as one
        # literal filename and creates a duplicate changed-file anchor.
        candidate = Path(value.replace("\\", "/"))
        resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
        try:
            normalized.add(resolved.relative_to(root).as_posix())
        except ValueError as exc:
            raise ValueError(f"Changed path is outside the project: {value}") from exc
    return sorted(normalized)


def project_snapshot(project_path: str | Path, scope: str | None = None) -> dict[str, str]:
    """Return the same source snapshot used by the persistent graph cache.

    Incremental invalidation and review freshness must have one definition of
    the project boundary.  Delegating prevents editor caches, hidden tooling
    directories, generated output, and user-configured scan-plan exclusions
    from making a graph appear stale when they were never analyzed.
    """
    return persistent_project_snapshot(validate_project_path(project_path), scope)


def atomic_write_graph(graph: GraphDocument, output_path: str | Path) -> Path:
    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = graph.to_json()
    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return destination


def _cached_fact_document(project_path: str | Path, graph: GraphDocument | None = None) -> FactDocument | None:
    """Load an atomically committed FactDocument when it belongs to ``graph``.

    The cache is an optimisation only: any incomplete bundle, unsupported
    legacy cache, or snapshot mismatch returns ``None`` and the caller rebuilds
    facts from the graph.  That preserves the original evidence contract.
    """
    try:
        loaded = AtomicCacheStore(project_path).load(artifact_names=("facts.json",))
        payload = loaded.artifacts.get("facts.json") if loaded.hit else None
        if not isinstance(payload, dict):
            return None
        if graph is not None:
            expected = graph.metadata.get("cache", {}).get("source_snapshot_hash") if isinstance(graph.metadata, dict) else None
            actual = (loaded.metadata or {}).get("source_snapshot_hash")
            if expected and expected != actual:
                return None
        return FactDocument.from_dict(payload)
    except (OSError, ValueError, TypeError):
        return None


def incremental_update(
    project_path: str,
    analyzer: Callable[[], dict[str, Any]],
    previous_snapshot: dict[str, str] | None = None,
    out_path: str | None = None,
    previous_graph_path: str | None = None,
    cancellation: CancellationToken | None = None,
    forced_changed: list[str] | None = None,
    scope: str | None = None,
    previous_graph: GraphDocument | None = None,
) -> dict[str, Any]:
    if cancellation is not None:
        cancellation.check()
    current_snapshot = project_snapshot(project_path, scope)
    changed = sorted(set(current_snapshot) ^ set(previous_snapshot or {}) | {
        path for path in current_snapshot if previous_snapshot and current_snapshot[path] != previous_snapshot.get(path)
    } | {str(item).replace("\\", "/") for item in (forced_changed or [])})
    if not changed and previous_graph_path and Path(previous_graph_path).exists():
        if cancellation is not None:
            cancellation.check()
        graph = GraphDocument.from_json(Path(previous_graph_path).read_text(encoding="utf-8"))
        annotate_graph_quality(graph)
        result = {
            "status": "ok",
            "graph": graph.to_dict(),
            "graph_path": str(Path(previous_graph_path).resolve()),
            "incremental": {
                "status": "reused",
                "changed_files": [],
                "changed_file_count": 0,
                "snapshot": current_snapshot,
                "safe_replace": False,
                "analysis_reused": True,
                "cache_hit_rate": 1.0,
                "files_total": len(current_snapshot),
                "files_reused": len(current_snapshot),
                "files_reanalyzed": 0,
            },
        }
        result["cache"] = {
            "status": "hit", "reason": "cache_hit", "scope": scope or ".",
            "files_reused": len(current_snapshot), "files_reanalyzed": 0,
            "facts_reused": 0, "facts_rebuilt": 0,
        }
        result["progress"] = {"phase": "cache", "completed": 1, "total": 1, "elapsed_seconds": 0.0, "eta_seconds": None, "cancellable": cancellation is not None}
        result["coverage"] = []
        result["incomplete"] = False
        return result
    # A changed-file analyzer is allowed to return a bounded candidate graph.
    # It is *not* allowed to replace the durable project graph with that
    # candidate unless it represents the project as a whole.  In particular,
    # treating a one-file fragment as the new canonical graph silently drops
    # unrelated routes, callers, and tests.  Callers can handle this explicit
    # result by running a full refresh or a future proven graph merge.
    prior_graph = previous_graph
    if prior_graph is None and previous_graph_path and Path(previous_graph_path).exists():
        try:
            prior_graph = GraphDocument.from_json(Path(previous_graph_path).read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            prior_graph = None

    # The analysis pipeline persists the exact final FactDocument atomically
    # with its graph.  Rebuilding every fact from a large previous graph on
    # each review was pure duplicate CPU work.  Read that durable artifact
    # before the analyzer replaces it; fall back to graph reconstruction for
    # legacy/external callers or incomplete cache bundles.
    previous_facts = _cached_fact_document(project_path)
    parameters = inspect.signature(analyzer).parameters
    result = analyzer(changed) if parameters else analyzer()
    if cancellation is not None:
        cancellation.check()
    graph = GraphDocument.from_dict(result.get("graph", {}))
    source_files_total = len(current_snapshot)
    changed_fraction = len(changed) / max(1, source_files_total)
    candidate_is_partial = (
        prior_graph is not None
        and len(prior_graph.nodes) > 0
        and len(graph.nodes) < len(prior_graph.nodes)
        and changed_fraction < 0.5
    )
    if candidate_is_partial:
        result["incremental"] = {
            "status": "partial_candidate_rejected",
            "reason": "changed-file analysis produced a smaller graph without a proven whole-project merge",
            "changed_files": changed,
            "changed_file_count": len(changed),
            "files_total": source_files_total,
            "candidate_nodes": len(graph.nodes),
            "previous_nodes": len(prior_graph.nodes),
            "safe_replace": False,
            "requires_full_refresh": True,
        }
        result["graph"] = prior_graph.to_dict()
        result["graph_path"] = str(Path(previous_graph_path).resolve()) if previous_graph_path else None
        result["cache"] = {
            "status": "miss",
            "reason": "partial_candidate_rejected",
            "scope": scope or ".",
        }
        result["incomplete"] = True
        return result
    new_facts = _cached_fact_document(project_path, graph) or FactDocument.from_graph(graph)
    old_facts = previous_facts or (FactDocument.from_graph(GraphDocument.from_json(Path(previous_graph_path).read_text(encoding="utf-8"))) if previous_graph_path and Path(previous_graph_path).exists() else FactDocument())
    fact_diff = diff_fact_documents(old_facts, new_facts, changed)
    result["fact_diff"] = fact_diff.to_dict()
    graph.metadata["fact_diff"] = fact_diff.to_dict()
    fact_delta = sum(
        len(value) for value in result["fact_diff"].values()
        if isinstance(value, (list, tuple, set, dict))
    )
    call_sites = sum(1 for node in graph.nodes if node.kind == "CALL_EXPR")
    if len(graph.nodes) > MAX_INCREMENTAL_GRAPH_NODES or call_sites > MAX_INCREMENTAL_CALL_SITES:
        closure = {
            "status": "deferred_by_scale_budget",
            "reason": "Graph scale exceeds the bounded incremental-planning budget; a partial resolver claim is not made.",
            "affected_fact_ids": [],
            "affected_dependency_keys": [],
            "affected_edge_ids": [],
            "affected_node_ids": [],
            "affected_resolver_ids": [],
            "skipped_resolver_ids": [item["resolver_id"] for item in list_resolver_contracts()],
        }
    elif fact_delta > MAX_INCREMENTAL_FACT_DELTA:
        closure = {
            "status": "deferred_by_fact_delta_budget",
            "reason": "Fact delta exceeded the selective-context budget; a partial resolver claim is not made.",
            "affected_fact_ids": [],
            "affected_dependency_keys": [],
            "affected_edge_ids": [],
            "affected_node_ids": [],
            "affected_resolver_ids": [],
            "skipped_resolver_ids": [item["resolver_id"] for item in list_resolver_contracts()],
        }
    else:
        fact_by_location = {(fact.get("file"), fact.get("evidence_line")): fact for fact in new_facts.facts}
        for edge in graph.edges:
            ids = []
            for evidence in edge.evidence:
                fact = fact_by_location.get((evidence.file, evidence.line))
                if fact and fact.get("fact_id"):
                    ids.append(fact["fact_id"])
            if not ids:
                ids = [fact["fact_id"] for fact in new_facts.facts if fact.get("canonical_subject") in {edge.from_node, edge.to_node}][:8]
            if ids:
                edge.properties.setdefault("source_fact_ids", sorted(set(ids)))
                edge.properties.setdefault("dependency_keys", sorted({f"symbol:{value}" for value in (edge.from_node, edge.to_node)}))
                edge.properties.setdefault("resolver_id", edge.properties.get("resolver_hook_name") or edge.properties.get("extractor_id") or "unknown")
        closure = affected_closure(graph, fact_diff.to_dict(), (old_facts, new_facts))
    result["affected_closure"] = closure
    graph.metadata["affected_closure"] = closure
    context_builder = ResolverContextBuilder(new_facts.facts)
    context_facts = context_builder.build(closure["affected_fact_ids"], closure["affected_dependency_keys"])
    plan = ResolverExecutionPlan(
        resolvers_to_run=closure["affected_resolver_ids"],
        resolvers_to_skip=closure["skipped_resolver_ids"],
        affected_fact_ids=closure["affected_fact_ids"],
        affected_dependency_keys=closure["affected_dependency_keys"],
        edges_to_remove=closure["affected_edge_ids"],
        nodes_to_refresh=closure["affected_node_ids"],
        required_context_fact_ids=[str(fact.get("fact_id")) for fact in context_facts],
        fallback_reasons=[] if graph.metadata.get("selective_execution", {}).get("selective_execution_proven") else [
            "no safe selective plugin execution proof was emitted by the analyzer"
        ],
    )
    result["resolver_execution_plan"] = plan.to_dict()
    result["resolver_context"] = {"fact_count": len(context_facts), "fact_ids": plan.required_context_fact_ids}
    selective_meta = dict(graph.metadata.get("selective_execution") or {})
    result["selective_execution"] = {
        **selective_meta,
        "executed_resolvers": closure["affected_resolver_ids"],
        "skipped_resolvers": closure["skipped_resolver_ids"],
        "unexpected_resolvers_executed": [],
        "resolver_plan_applied": bool(selective_meta.get("selective_execution_proven")),
        "reason": selective_meta.get("fallback_reason"),
    }
    result["selective_resolver"] = {
        "all_resolvers_total": len(list_resolver_contracts()),
        "resolvers_rerun": closure["affected_resolver_ids"],
        "resolvers_skipped": closure["skipped_resolver_ids"],
        "semantic_edges_invalidated": closure["affected_edge_ids"],
        "semantic_edges_reused": max(0, len(graph.edges) - len(closure["affected_edge_ids"])),
        "execution_mode": selective_meta.get("execution_mode", "resolver_plan_only"),
        "selective_execution_proven": bool(selective_meta.get("selective_execution_proven")),
        "fallback_reason": selective_meta.get("fallback_reason"),
    }
    graph.metadata["selective_resolver"] = result["selective_resolver"]
    annotate_graph_quality(graph)
    result["graph"] = graph.to_dict()
    cache_stats = graph.metadata.get("incremental_cache", {}) if isinstance(graph.metadata, dict) else {}
    # A no-semantic-delta update may reuse the final persisted graph directly;
    # it is at least as strong as raw extraction reuse and must be visible to
    # callers as a real cache hit rather than a misleading full refresh.
    raw_reused = any(
        marker in result.get("extractors_used", [])
        for marker in ("incremental_raw_cache", "persistent_final_graph_cache")
    )
    result["incremental"] = {
        "status": "updated",
        "changed_files": changed,
        "changed_file_count": len(changed),
        "snapshot": current_snapshot,
        "safe_replace": True,
        "analysis_reused": bool(raw_reused and cache_stats.get("files_reused", 0) > 0),
        "raw_extraction_reused": raw_reused,
        "files_total": len(current_snapshot),
        "files_reused": int(cache_stats.get("files_reused", 0)),
        "files_reanalyzed": int(cache_stats.get("files_reanalyzed", len(changed))),
        "facts_reused": int(cache_stats.get("facts_reused", 0)),
        "facts_rebuilt": int(cache_stats.get("facts_rebuilt", 0)),
        "nodes_reused": int(cache_stats.get("nodes_reused", 0)),
        "edges_reused": int(cache_stats.get("edges_reused", 0)),
        "invalidated_nodes": cache_stats.get("invalidated_nodes", []),
        "cache_hit_rate": float(cache_stats.get("cache_hit_rate", 0.0)),
    }
    if out_path:
        atomic_write_graph(graph, out_path)
        result["graph_path"] = str(Path(out_path).resolve())
    cache_meta = graph.metadata.get("cache", {}) if isinstance(graph.metadata, dict) else {}
    result["cache"] = {
        "status": cache_meta.get("cache_status", "miss"),
        "reason": cache_meta.get("cache_reason", "incremental_update"),
        "branch": cache_meta.get("branch"), "snapshot": cache_meta.get("source_snapshot_hash"),
        "scope": scope or cache_meta.get("scan_scope", "."),
        "plugins": cache_meta.get("selected_plugins", []),
        "files_reused": result["incremental"]["files_reused"],
        "files_reanalyzed": result["incremental"]["files_reanalyzed"],
        "facts_reused": result["incremental"]["facts_reused"],
        "facts_rebuilt": result["incremental"]["facts_rebuilt"],
    }
    progress_meta = graph.metadata.get("analysis_progress", {}) if isinstance(graph.metadata, dict) else {}
    current = progress_meta.get("current", {}) if isinstance(progress_meta, dict) else {}
    result["progress"] = {
        "phase": current.get("phase", current.get("stage", "completed")),
        "completed": current.get("completed", current.get("processed", 1)),
        "total": current.get("total", 1), "elapsed_seconds": current.get("elapsed_seconds", 0.0),
        "eta_seconds": current.get("eta_seconds"), "cancellable": cancellation is not None,
    }
    result["coverage"] = graph.metadata.get("resolution_coverage", [])
    result["incomplete"] = bool(graph.metadata.get("incomplete", False))
    return result


def load_snapshot(path: str | Path) -> dict[str, str]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_snapshot(snapshot: dict[str, str], path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")
