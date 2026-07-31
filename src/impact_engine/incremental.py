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
from impact_engine.incremental_index import affected_closure
from impact_engine.resolver_registry import list_resolver_contracts
from impact_engine.selective_execution import ResolverExecutionPlan, ResolverContextBuilder
from impact_engine.security import validate_project_path


SNAPSHOT_SCHEMA_VERSION = 2
MAX_INCREMENTAL_FACT_DELTA = 5_000
MAX_INCREMENTAL_PLANNING_NODES = 30_000
MAX_INCREMENTAL_PLANNING_CALLS = 12_000


def _iter_project_files(project_path: str | Path):
    root = validate_project_path(project_path)
    ignored = {".git", ".impact_engine", "__pycache__", "node_modules", ".venv"}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in ignored for part in path.parts):
            continue
        yield root, path


def snapshot_hashes(snapshot: dict[str, Any] | None) -> dict[str, str]:
    """Read both legacy hash maps and versioned snapshot documents."""
    if not isinstance(snapshot, dict):
        return {}
    files = snapshot.get("files")
    if isinstance(files, dict):
        return {
            str(path): str(record.get("sha256", ""))
            for path, record in files.items()
            if isinstance(record, dict) and record.get("sha256")
        }
    return {str(path): str(digest) for path, digest in snapshot.items() if isinstance(digest, str)}


def project_snapshot_state(
    project_path: str | Path,
    previous_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a snapshot without rehashing files whose stat metadata is unchanged."""
    previous_files = previous_snapshot.get("files", {}) if isinstance(previous_snapshot, dict) else {}
    files: dict[str, dict[str, int | str]] = {}
    for root, path in _iter_project_files(project_path):
        relative = str(path.relative_to(root)).replace("\\", "/")
        stat = path.stat()
        prior = previous_files.get(relative) if isinstance(previous_files, dict) else None
        if (
            isinstance(prior, dict)
            and prior.get("size") == stat.st_size
            and prior.get("mtime_ns") == stat.st_mtime_ns
            and isinstance(prior.get("sha256"), str)
        ):
            digest = prior["sha256"]
        else:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        files[relative] = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": digest}
    return {"schema_version": SNAPSHOT_SCHEMA_VERSION, "files": files}


def project_snapshot(project_path: str | Path) -> dict[str, str]:
    """Return the legacy path-to-content-hash map used by public callers."""
    return snapshot_hashes(project_snapshot_state(project_path))


def project_file_count(project_path: str | Path) -> int:
    """Count included files without reading their contents."""
    return sum(1 for _root, _path in _iter_project_files(project_path))


def normalize_changed_files(project_path: str | Path, paths: list[str] | None) -> list[str] | None:
    """Convert user-supplied change paths to safe project-relative paths.

    Callers may receive either Git-style relative paths or absolute editor
    paths.  Keeping one canonical form prevents a cache refresh from silently
    missing a file on Windows, where separators and drive letters differ.
    """
    if paths is None:
        return None
    root = validate_project_path(project_path)
    normalized: set[str] = set()
    for value in paths:
        candidate = Path(value)
        resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
        try:
            relative = resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"Changed path is outside the project: {value}") from exc
        normalized.add(relative.as_posix())
    return sorted(normalized)


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


def incremental_update(
    project_path: str,
    analyzer: Callable[[], dict[str, Any]],
    previous_snapshot: dict[str, Any] | None = None,
    out_path: str | None = None,
    previous_graph_path: str | None = None,
) -> dict[str, Any]:
    current_snapshot = project_snapshot_state(project_path, previous_snapshot)
    current_hashes = snapshot_hashes(current_snapshot)
    previous_hashes = snapshot_hashes(previous_snapshot)
    changed = sorted(set(current_hashes) ^ set(previous_hashes) | {
        path for path in current_hashes if previous_hashes and current_hashes[path] != previous_hashes.get(path)
    })
    if not changed and previous_graph_path and Path(previous_graph_path).exists():
        graph = GraphDocument.from_json(Path(previous_graph_path).read_text(encoding="utf-8"))
        annotate_graph_quality(graph)
        return {
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
                "files_total": len(current_hashes),
                "files_reused": len(current_hashes),
                "files_reanalyzed": 0,
            },
        }
    parameters = inspect.signature(analyzer).parameters
    result = analyzer(changed) if parameters else analyzer()
    graph = GraphDocument.from_dict(result.get("graph", {}))
    call_count = sum(1 for node in graph.nodes if node.kind == "CALL_EXPR")
    if len(graph.nodes) > MAX_INCREMENTAL_PLANNING_NODES or call_count > MAX_INCREMENTAL_PLANNING_CALLS:
        # The graph itself is current because the analyzer above completed.
        # Only optional planner metadata is deferred; claiming a selective
        # resolver plan for a graph this large would be both slow and false.
        deferred = {
            "status": "deferred_by_scale_budget",
            "reason": "Large graph: structural refresh completed, fact-level selective planning was deferred.",
            "nodes": len(graph.nodes),
            "calls": call_count,
            "max_nodes": MAX_INCREMENTAL_PLANNING_NODES,
            "max_calls": MAX_INCREMENTAL_PLANNING_CALLS,
        }
        fact_diff = {"changed_files": changed, "status": "deferred_by_scale_budget", **deferred}
        closure = {
            "affected_fact_ids": [], "affected_dependency_keys": [], "affected_edge_ids": [],
            "affected_resolver_ids": [], "skipped_resolver_ids": [item["resolver_id"] for item in list_resolver_contracts()],
            "affected_node_ids": [], **deferred,
        }
        graph.metadata["fact_diff"] = fact_diff
        graph.metadata["incremental_planning"] = deferred
        result["fact_diff"] = fact_diff
        result["affected_closure"] = closure
        result["resolver_execution_plan"] = {
            "resolvers_to_run": [], "resolvers_to_skip": closure["skipped_resolver_ids"],
            "affected_fact_ids": [], "affected_dependency_keys": [], "edges_to_remove": [],
            "nodes_to_refresh": [], "required_context_fact_ids": [],
            "fallback_reasons": [deferred["reason"]],
        }
        result["resolver_context"] = {"fact_count": 0, "fact_ids": []}
        result["selective_execution"] = {
            "execution_mode": "raw_extraction_selective_planning_deferred",
            "full_pipeline_called": True,
            "executed_resolvers": [], "unexpected_resolvers_executed": [],
            "reason": deferred["reason"],
        }
        result["selective_resolver"] = {
            "all_resolvers_total": len(list_resolver_contracts()),
            "resolvers_rerun": [], "resolvers_skipped": closure["skipped_resolver_ids"],
            "semantic_edges_invalidated": [], "semantic_edges_reused": len(graph.edges),
            "execution_mode": "planning_deferred_by_scale_budget",
            "selective_execution_proven": False,
        }
        cache_stats = graph.metadata.get("incremental_cache", {}) if isinstance(graph.metadata, dict) else {}
        result["graph"] = graph.to_dict()
        result["incremental"] = {
            "status": "updated", "changed_files": changed, "changed_file_count": len(changed),
            "snapshot": current_snapshot, "safe_replace": True,
            "analysis_reused": bool("incremental_raw_cache" in result.get("extractors_used", [])),
            "raw_extraction_reused": "incremental_raw_cache" in result.get("extractors_used", []),
            "files_total": len(current_hashes),
            "files_reused": int(cache_stats.get("files_reused", 0)),
            "files_reanalyzed": int(cache_stats.get("files_reanalyzed", len(changed)),),
            "cache_hit_rate": float(cache_stats.get("cache_hit_rate", 0.0)),
            "planning": deferred,
        }
        if out_path:
            atomic_write_graph(graph, out_path)
            result["graph_path"] = str(Path(out_path).resolve())
        return result
    new_facts = FactDocument.from_graph(graph)
    old_facts = FactDocument.from_graph(GraphDocument.from_json(Path(previous_graph_path).read_text(encoding="utf-8"))) if previous_graph_path and Path(previous_graph_path).exists() else FactDocument()
    fact_diff = diff_fact_documents(old_facts, new_facts, changed)
    result["fact_diff"] = fact_diff.to_dict()
    graph.metadata["fact_diff"] = fact_diff.to_dict()
    fact_by_location = {(fact.get("file"), fact.get("evidence_line")): fact for fact in new_facts.facts}
    fact_ids_by_symbol: dict[str, list[str]] = {}
    for fact in new_facts.facts:
        fact_id = fact.get("fact_id")
        if not fact_id:
            continue
        for symbol in (fact.get("canonical_subject"), fact.get("canonical_target")):
            if symbol:
                fact_ids_by_symbol.setdefault(str(symbol), []).append(str(fact_id))
    for edge in graph.edges:
        ids = []
        for evidence in edge.evidence:
            fact = fact_by_location.get((evidence.file, evidence.line))
            if fact and fact.get("fact_id"):
                ids.append(fact["fact_id"])
        if not ids:
            # Index lookup avoids scanning every fact for every graph edge on
            # a large incremental run.  The same source/target association is
            # retained, just computed once for the whole graph.
            ids = (fact_ids_by_symbol.get(edge.from_node, []) + fact_ids_by_symbol.get(edge.to_node, []))[:8]
        if ids:
            edge.properties.setdefault("source_fact_ids", sorted(set(ids)))
            edge.properties.setdefault("dependency_keys", sorted({f"symbol:{value}" for value in (edge.from_node, edge.to_node)}))
            edge.properties.setdefault("resolver_id", edge.properties.get("resolver_hook_name") or edge.properties.get("extractor_id") or "unknown")
    fact_delta_count = len(fact_diff.added_fact_ids) + len(fact_diff.removed_fact_ids) + len(fact_diff.modified_fact_ids)
    if fact_delta_count > MAX_INCREMENTAL_FACT_DELTA:
        # A changed fact identity on most of the graph means an old artifact
        # was produced by a different schema/version or a genuinely broad
        # change occurred.  Building a context for every fact is neither
        # selective nor responsive, so report that truth explicitly.
        closure = {
            "affected_fact_ids": [],
            "affected_dependency_keys": [],
            "affected_edge_ids": [],
            "affected_resolver_ids": [],
            "skipped_resolver_ids": [item["resolver_id"] for item in list_resolver_contracts()],
            "affected_node_ids": [],
            "status": "deferred_by_fact_delta_budget",
            "fact_delta_count": fact_delta_count,
            "max_fact_delta": MAX_INCREMENTAL_FACT_DELTA,
        }
    else:
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
        fallback_reasons=(
            ["Fact delta exceeded the selective-context budget; no partial resolver claim is made."]
            if closure.get("status") == "deferred_by_fact_delta_budget"
            else ["Semantic resolver passes currently reconcile the full graph after selective raw extraction."]
        ),
    )
    result["resolver_execution_plan"] = plan.to_dict()
    result["resolver_context"] = {"fact_count": len(context_facts), "fact_ids": plan.required_context_fact_ids}
    result["selective_execution"] = {
        "execution_mode": "raw_extraction_selective",
        "full_pipeline_called": True,
        "executed_resolvers": [],
        "unexpected_resolvers_executed": [],
        "reason": (
            "Fact delta exceeded the selective-context budget; raw extraction completed, while semantic selection is deferred."
            if closure.get("status") == "deferred_by_fact_delta_budget"
            else "Changed-file extraction is reused when a raw cache is available; semantic reconciliation remains whole-graph until resolver passes expose stable invalidation contracts."
        ),
    }
    result["selective_resolver"] = {
        "all_resolvers_total": len(list_resolver_contracts()),
        "resolvers_rerun": closure["affected_resolver_ids"],
        "resolvers_skipped": closure["skipped_resolver_ids"],
        "semantic_edges_invalidated": closure["affected_edge_ids"],
        "semantic_edges_reused": max(0, len(graph.edges) - len(closure["affected_edge_ids"])),
        "execution_mode": "raw_extraction_selective_with_full_semantic_reconciliation",
        "selective_execution_proven": False,
    }
    graph.metadata["selective_resolver"] = result["selective_resolver"]
    annotate_graph_quality(graph)
    result["graph"] = graph.to_dict()
    cache_stats = graph.metadata.get("incremental_cache", {}) if isinstance(graph.metadata, dict) else {}
    raw_reused = "incremental_raw_cache" in result.get("extractors_used", [])
    result["incremental"] = {
        "status": "updated",
        "changed_files": changed,
        "changed_file_count": len(changed),
        "snapshot": current_snapshot,
        "safe_replace": True,
        "analysis_reused": bool(raw_reused and cache_stats.get("files_reused", 0) > 0),
        "raw_extraction_reused": raw_reused,
        "files_total": len(current_hashes),
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
    return result


def load_snapshot(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    value = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Invalid snapshot document (expected object): {source}")
    return value


def save_snapshot(snapshot: dict[str, Any], path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(snapshot, indent=2, sort_keys=True)
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
