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


def project_snapshot(project_path: str | Path) -> dict[str, str]:
    root = validate_project_path(project_path)
    snapshot: dict[str, str] = {}
    ignored = {".git", ".impact_engine", "__pycache__", "node_modules", ".venv"}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in ignored for part in path.parts):
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        snapshot[str(path.relative_to(root)).replace("\\", "/")] = digest
    return snapshot


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
    previous_snapshot: dict[str, str] | None = None,
    out_path: str | None = None,
    previous_graph_path: str | None = None,
) -> dict[str, Any]:
    current_snapshot = project_snapshot(project_path)
    changed = sorted(set(current_snapshot) ^ set(previous_snapshot or {}) | {
        path for path in current_snapshot if previous_snapshot and current_snapshot[path] != previous_snapshot.get(path)
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
                "files_total": len(current_snapshot),
                "files_reused": len(current_snapshot),
                "files_reanalyzed": 0,
            },
        }
    parameters = inspect.signature(analyzer).parameters
    result = analyzer(changed) if parameters else analyzer()
    graph = GraphDocument.from_dict(result.get("graph", {}))
    new_facts = FactDocument.from_graph(graph)
    old_facts = FactDocument.from_graph(GraphDocument.from_json(Path(previous_graph_path).read_text(encoding="utf-8"))) if previous_graph_path and Path(previous_graph_path).exists() else FactDocument()
    fact_diff = diff_fact_documents(old_facts, new_facts, changed)
    result["fact_diff"] = fact_diff.to_dict()
    graph.metadata["fact_diff"] = fact_diff.to_dict()
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
        fallback_reasons=["resolver handlers are not yet wired to the existing semantic pipeline"],
    )
    result["resolver_execution_plan"] = plan.to_dict()
    result["resolver_context"] = {"fact_count": len(context_facts), "fact_ids": plan.required_context_fact_ids}
    result["selective_execution"] = {"execution_mode": "planning_only", "full_pipeline_called": True, "executed_resolvers": [], "unexpected_resolvers_executed": [], "reason": "existing analyzer callback still invokes compatibility semantic orchestration"}
    result["selective_resolver"] = {
        "all_resolvers_total": len(list_resolver_contracts()),
        "resolvers_rerun": closure["affected_resolver_ids"],
        "resolvers_skipped": closure["skipped_resolver_ids"],
        "semantic_edges_invalidated": closure["affected_edge_ids"],
        "semantic_edges_reused": max(0, len(graph.edges) - len(closure["affected_edge_ids"])),
        "execution_mode": "full_pipeline_compatibility",
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
    return result


def load_snapshot(path: str | Path) -> dict[str, str]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_snapshot(snapshot: dict[str, str], path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")
