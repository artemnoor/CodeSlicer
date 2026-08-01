"""Unified analysis orchestration layer."""
from __future__ import annotations

from dataclasses import asdict, replace
import json
import hashlib
from pathlib import Path
from typing import Any

from impact_engine.analysis.contracts import AnalysisOptions, AnalysisResult
from impact_engine.analysis.diagnostics import DiagnosticsCollector
from impact_engine.inventory.scanner import scan_project_inventory
from impact_engine.languages.semantics import build_language_capability_diagnostics
from impact_engine.models import GraphDocument, FactDocument
from impact_engine.normalization.graph import merge_graph_documents, normalize_graph_document
from impact_engine.resolution.precision import resolve_precision
from impact_engine.semantic import apply_semantic_resolution
from impact_engine.semantic_hygiene import apply_post_project_hygiene, build_pre_project_hygiene
from impact_engine.community import annotate_communities
from impact_engine.graph_quality import annotate_graph_quality, apply_quality_guard, run_quality_gate, annotate_edge_contracts
from impact_engine.security import validate_project_path
from impact_engine.graph_identity import annotate_stable_identities
from impact_engine.unknown_regions import analyze_unknown_regions, build_research_requests, write_research_requests
from impact_engine.resolution_coverage import build_resolution_coverage
from impact_engine.incremental_index import build_reverse_dependency_index
from impact_engine.nextjs_routes import apply_nextjs_routes
from impact_engine.plugin_architecture.contracts import PluginContext
from impact_engine.plugin_architecture.execution import extract_selected_languages, execute_selected_framework_hooks, resolve_selected_languages, selected_compatibility_packs, selected_semantic_recipes
from impact_engine.plugin_architecture.integrity import annotate_plugin_provenance, plugin_graph_integrity_gate
from impact_engine.plugin_architecture.selection import PluginSelectionPlan, build_plugin_selection_plan
from impact_engine.persistence import (
    AtomicCacheStore,
    CacheMetadata,
    git_context,
    project_snapshot_stats,
    project_snapshot as persistent_project_snapshot,
    root_identity,
    write_json_atomic,
)
from impact_engine.profiling import AnalysisProfiler


class AnalysisPipeline:
    """Coordinates extractors, normalization, semantic binding, and resolution."""

    def __init__(self, options: AnalysisOptions) -> None:
        self.options = options
        self.project_path = str(validate_project_path(options.project_path))
        self.diagnostics = DiagnosticsCollector()
        self.support_pack_load_errors: list[str] = []
        self.extractors_used: list[str] = []
        self.stage_timings: dict[str, float] = {}
        self.incremental_cache_stats: dict[str, Any] = {}
        self.invalidated_node_ids: set[str] = set()
        self.progress_events: list[dict[str, Any]] = []
        self.progress_started = __import__("time").perf_counter()
        self.selection_plan: PluginSelectionPlan | None = None
        self.plugin_diagnostics: list[dict[str, Any]] = []
        self.cancellation = options.cancellation
        self.cache_store = AtomicCacheStore(self.project_path)
        self.cache_metadata: CacheMetadata | None = None
        self.cache_load = None
        self.selective_language_ids: list[str] | None = None
        self.selective_execution_fallback: str | None = None
        self.reusable_final_graph: GraphDocument | None = None
        self.reusable_final_graph_payload: dict[str, Any] | None = None
        self.prefetched_incremental_graphs: list[GraphDocument] | None = None
        self.current_snapshot: dict[str, str] | None = None
        self.profiler = AnalysisProfiler()

    def _progress(self, stage: str, processed: int, total: int, message: str) -> None:
        if self.cancellation is not None:
            check = getattr(self.cancellation, "check", None)
            if check:
                check()
        weights = {
            "inventory": 0.10, "preparation": 0.05, "extraction": 0.35,
            "normalization": 0.10, "semantic": 0.15, "resolution": 0.15,
            "final": 0.10,
        }
        stage_percent = 100.0 if total <= 0 else min(100.0, max(0.0, processed / total * 100.0))
        ordered = list(weights)
        overall = sum(weights[name] * (stage_percent / 100.0 if name == stage else (1.0 if ordered.index(name) < ordered.index(stage) else 0.0)) for name in ordered)
        elapsed = __import__("time").perf_counter() - self.progress_started
        eta = None
        if processed >= 2 and total > processed and elapsed > 0:
            eta = round((elapsed / processed) * (total - processed), 3)
        event = {
            "phase": stage,
            "stage": stage,
            "message": message,
            "processed": processed,
            "total": total,
            "stage_percent": round(stage_percent, 1),
            "overall_percent": round(overall * 100.0, 1),
            "elapsed_seconds": round(elapsed, 3),
            "eta_seconds": eta,
            "cancellable": self.cancellation is not None,
        }
        self.progress_events.append(event)
        callback = self.options.progress_callback
        if callback:
            callback(event)

    def run(self) -> AnalysisResult:
        import time
        fast_result = self._try_fast_cache_hit()
        if fast_result is not None:
            return fast_result
        self._progress("inventory", 0, 1, "Сканирование файлов и manifest-файлов")
        with self.profiler.measure("inventory"):
            inventory_data = self._scan_inventory()
        self.profiler.add_work(files_seen=len(inventory_data.get("files", [])))
        self._progress("inventory", 1, 1, f"Inventory завершён: {inventory_data.get('files_count', len(inventory_data.get('files', [])))} файлов")
        with self.profiler.measure("plugin_selection"):
            self.selection_plan = build_plugin_selection_plan(self.project_path, inventory_data)
        selected_ids = self.selection_plan.selected_ids() if self.selection_plan else []
        all_plugin_ids = list(self.selection_plan.registry.manifests) if self.selection_plan and self.selection_plan.registry else []
        self.profiler.add_work(
            plugins_executed=selected_ids,
            plugins_skipped=[item for item in all_plugin_ids if item not in selected_ids],
        )
        with self.profiler.measure("snapshot_hashing"):
            self.current_snapshot = persistent_project_snapshot(self.project_path, self.options.scope)
        self.cache_metadata = CacheMetadata.from_project(
            self.project_path,
            scope=self.options.scope,
            plugin_plan=self.selection_plan,
            snapshot=self.current_snapshot,
            cache_status="miss",
            cache_reason="initial_scan" if not self.options.changed_files else "incremental_update",
        )
        with self.profiler.measure("cache_lookup"):
            self.cache_load = self.cache_store.load(self.cache_metadata)
        if (
            self.cache_load.hit
            and not self.options.changed_files
            and not self.options.graphify_path
            and self.options.support_packs is None
            and not self.options.enable_remote_registry
        ):
            cached_graph = self.cache_load.artifacts.get("graph.json", {})
            cached_graph.setdefault("metadata", {})["cache"] = {
                "status": "hit",
                "reason": "cache_hit",
                "cache_status": "hit",
                "cache_reason": "cache_hit",
                "branch": self.cache_metadata.branch,
                "snapshot": self.cache_metadata.source_snapshot_hash,
                "scope": self.cache_metadata.scan_scope,
                "plugins": list(self.cache_metadata.selected_plugins),
                "files_reused": len(self.cache_load.artifacts.get("snapshot.json", {})),
                "files_reanalyzed": 0,
                "facts_reused": len(self.cache_load.artifacts.get("facts.json", {}).get("facts", [])),
                "facts_rebuilt": 0,
            }
            progress_event = {
                "phase": "cache", "stage": "cache", "message": "Persistent cache reused",
                "completed": 1, "processed": 1, "total": 1,
                "stage_percent": 100.0, "overall_percent": 100.0,
                "elapsed_seconds": 0.0, "eta_seconds": None, "cancellable": False,
            }
            if self.options.progress_callback:
                self.options.progress_callback(progress_event)
            progress = {"status": "completed", "events": [progress_event], "current": progress_event}
            cached_graph["metadata"]["analysis_progress"] = progress
            graph_path = self._write_graph_payload(cached_graph)
            return AnalysisResult(
                status="ok", path=self.project_path, project_path=self.project_path,
                graph_path=graph_path, inventory=inventory_data,
                languages=self.selection_plan.languages,
                extractors_used=list(cached_graph.get("metadata", {}).get("extractors_used", [])) + ["persistent_cache"],
                diagnostics=cached_graph.get("metadata", {}).get("analysis_diagnostics", {"items": [], "normal_analyze_requires_internet": False}),
                support_pack_load_errors=list(cached_graph.get("metadata", {}).get("support_pack_load_errors", [])),
                nodes=len(cached_graph.get("nodes", [])), edges=len(cached_graph.get("edges", [])), graph=cached_graph, progress=progress,
                profiling=self.profiler.snapshot(),
            )
        languages = self.selection_plan.languages
        pre_hygiene = self._build_pre_hygiene(inventory_data)
        self._progress("preparation", 1, 1, "Языки, зависимости и pre-hygiene определены")
        language_capabilities = build_language_capability_diagnostics(languages)
        with self.profiler.measure("extraction"):
            raw_graphs = self._extract_graphs(self.selection_plan)
        if self.reusable_final_graph is not None or self.reusable_final_graph_payload is not None:
            return self._finish_no_graph_delta_incremental(inventory_data)
        self._extract_graphify(raw_graphs)
        self._progress("normalization", 0, 1, "Нормализация фактов и структурного графа")
        with self.profiler.measure("normalization"):
            graph = self._merge_and_normalize(raw_graphs)
            graph = apply_nextjs_routes(graph, self.project_path)
        self._progress("normalization", 1, 1, "Нормализация завершена")
        fact_document = FactDocument.from_graph(graph)
        graph.metadata["fact_document"] = fact_document.summary()
        if Path(self.project_path).is_dir():
            fact_path = Path(self.project_path) / ".impact_engine" / "facts.json"
            fact_path.parent.mkdir(parents=True, exist_ok=True)
            write_json_atomic(fact_path, fact_document.to_dict())
            graph.metadata["fact_document_path"] = str(fact_path.resolve())
        run_quality_gate(graph, "extraction_normalization")
        graph.metadata["language_semantic_capabilities"] = language_capabilities
        graph.metadata["plugin_selection_plan"] = self.selection_plan.to_dict() if self.selection_plan else {}
        if pre_hygiene:
            graph.metadata["pre_project_hygiene"] = pre_hygiene
            graph.metadata["pre_project_hygiene_status"] = "applied"
        # Packs are a rules context available to binding, resolver and validation;
        # they are not a terminal post-processing stage.
        support_packs = self._load_support_packs()
        graph.metadata["support_pack_context"] = [
            {
                "library": getattr(pack, "library", pack.get("library", "unknown") if isinstance(pack, dict) else "unknown"),
                "language": getattr(pack, "language", pack.get("language", "") if isinstance(pack, dict) else ""),
                "trust_level": getattr(pack, "trust_level", pack.get("trust_level", "") if isinstance(pack, dict) else ""),
                "scope": getattr(pack, "scope", pack.get("scope", "global") if isinstance(pack, dict) else "global"),
                "project_scope": getattr(pack, "project_scope", pack.get("project_scope", {}) if isinstance(pack, dict) else {}),
                "available_phases": ["semantic_binding", "precision_resolver", "validation"],
            }
            for pack in support_packs
        ]
        deep_resolution_enabled = self._deep_resolution_enabled(graph)
        started = time.perf_counter()
        self._progress("semantic", 0, 1, "Semantic binding и support-pack context")
        if deep_resolution_enabled:
            with self.profiler.measure("semantic_binding"):
                graph = self._apply_semantic_layer(graph)
        else:
            graph.metadata["semantic_binding_layer"] = {"status": "skipped_by_scale_budget", "reason": "Structural extraction is current; use --full-resolution for unbounded semantic binding."}
        self.stage_timings["semantic_binding"] = round(time.perf_counter() - started, 4)
        self._progress("semantic", 1, 1, "Semantic binding завершён")
        run_quality_gate(graph, "semantic_binding")
        if self.selection_plan and deep_resolution_enabled:
            plugin_context = PluginContext(
                Path(self.project_path),
                getattr(self, "_inventory_data", {}),
                self.selection_plan.selected_ids(),
                cancellation=self.cancellation,
            )
            with self.profiler.measure("framework_hooks"):
                graph, hook_diags = execute_selected_framework_hooks(
                    self.selection_plan, plugin_context, graph, phase="pre_resolution"
                )
            self.plugin_diagnostics.extend(item.to_dict() for item in hook_diags)
        local_registry_summary = self._sync_local_registry(inventory_data)
        started = time.perf_counter()
        self._progress("resolution", 0, 1, "Precision и framework resolution")
        if deep_resolution_enabled:
            with self.profiler.measure("precision_resolution"):
                resolved = resolve_precision(graph, support_packs=support_packs)
                resolved.metadata["plugin_hook_execution_phase"] = "completed"
                if self.selection_plan:
                    plugin_context = PluginContext(Path(self.project_path), getattr(self, "_inventory_data", {}), self.selection_plan.selected_ids(), cancellation=self.cancellation)
                    resolved, plugin_diags = resolve_selected_languages(
                        self.selection_plan, plugin_context, resolved,
                        selected_ids=self.selective_language_ids,
                    )
                    self.plugin_diagnostics.extend(item.to_dict() for item in plugin_diags)
        else:
            resolved = graph
            resolved.metadata["precision_resolution"] = {"status": "skipped_by_scale_budget", "reason": "Structural extraction is current; use --full-resolution for unbounded precision resolution."}
        self.stage_timings["resolution"] = round(time.perf_counter() - started, 4)
        self._progress("resolution", 1, 1, "Resolution завершён")
        run_quality_gate(resolved, "generic_and_framework_resolution")
        if local_registry_summary:
            resolved.metadata["local_registry"] = local_registry_summary
        if self.selection_plan and deep_resolution_enabled:
            plugin_context = PluginContext(Path(self.project_path), getattr(self, "_inventory_data", {}), self.selection_plan.selected_ids(), cancellation=self.cancellation)
            with self.profiler.measure("framework_hooks"):
                resolved, post_hook_diags = execute_selected_framework_hooks(
                    self.selection_plan, plugin_context, resolved, phase="post_resolution"
                )
            self.plugin_diagnostics.extend(item.to_dict() for item in post_hook_diags)
        started = time.perf_counter()
        with self.profiler.measure("frontend_backend_projection"):
            resolved = self._apply_post_hygiene_layer(resolved, inventory_data)
        # Resolution and endpoint bridging can add CALLS/DEPENDS_ON edges
        # after the initial extraction normalization. Re-run the endpoint
        # materialization gate before final quality checks so the persisted
        # GraphDocument never contains dangling semantic edges.
        with self.profiler.measure("normalization"):
            resolved = normalize_graph_document(resolved)
        self.stage_timings["post_hygiene_and_quality"] = round(time.perf_counter() - started, 4)
        with self.profiler.measure("graph_quality"):
            resolved = apply_quality_guard(resolved)
            if self.selection_plan:
                resolved = annotate_plugin_provenance(resolved, self.selection_plan)
                for plugin_id in self.selection_plan.selected_ids():
                    resolved = plugin_graph_integrity_gate(resolved, plugin_id)
                self.plugin_diagnostics.extend(item.to_dict() for item in self.selection_plan.diagnostics)
                for item in self.selection_plan.registry.diagnostics if self.selection_plan.registry else ():
                    self.plugin_diagnostics.append(item.to_dict() if hasattr(item, "to_dict") else dict(item))
                resolved.metadata["plugin_diagnostics"] = list(self.plugin_diagnostics)
            resolved = annotate_communities(resolved)
            resolved = annotate_stable_identities(resolved, self.project_path)
            resolved = annotate_edge_contracts(resolved)
            resolved = annotate_graph_quality(resolved)
            run_quality_gate(resolved, "final_graph")
        if self._should_defer_unknown_regions(resolved):
            resolved.metadata["unknown_regions"] = {"status": "deferred_by_scale_budget", "policy": "full workspace inventory deferred", "counts": {}, "regions": []}
            resolved.metadata["all_unknown_regions"] = {}
            resolved.metadata["unknown_region_research_requests"] = []
            self.diagnostics.add("unknown_regions_deferred_by_scale_budget", "Large analysis deferred the global unknown-region inventory; request it separately when that report is needed.", component="unknown_regions", severity="info", actionable=False)
        else:
            self._annotate_unknown_regions(resolved)
        resolved.metadata["resolution_coverage"] = build_resolution_coverage(resolved)
        resolved.metadata["coverage_quality_gate"] = {
            "status": "ok" if resolved.metadata["resolution_coverage"].get("accounting", {}).get("valid") else "warning",
            "accounting": resolved.metadata["resolution_coverage"].get("accounting", {}),
        }
        resolved.metadata["stage_timings_seconds"] = dict(self.stage_timings)
        self._progress("final", 0, 1, "Quality guard, diagnostics и fingerprint")
        self._record_graph_metadata(resolved)
        resolved.metadata["analysis_diagnostics"] = self.diagnostics.to_legacy_dict()
        resolved.metadata["extractors_used"] = list(self.extractors_used)
        resolved.metadata["support_pack_load_errors"] = list(self.support_pack_load_errors)
        if self.options.changed_files is not None and self.options.raw_graph_cache_path and self.selective_language_ids is not None:
            resolved.metadata["selective_execution"] = {
                "execution_mode": "selective_plugin_execution",
                "full_pipeline_called": False,
                "selective_execution_proven": True,
                "selected_language_plugins": list(self.selective_language_ids),
                "skipped_language_plugins": [
                    item for item in (self.selection_plan.selected_language_ids if self.selection_plan else [])
                    if item not in self.selective_language_ids
                ],
                "fallback_reason": self.selective_execution_fallback,
            }
        else:
            resolved.metadata["selective_execution"] = {
                "execution_mode": "full_initial_scan",
                "full_pipeline_called": True,
                "selective_execution_proven": False,
                "fallback_reason": "initial_or_non_incremental_analysis",
            }
        self._progress("final", 1, 1, "Анализ завершён")
        progress = {"status": "completed", "events": self.progress_events, "current": self.progress_events[-1]}
        resolved.metadata["analysis_progress"] = progress
        self._record_profile_work()
        resolved.metadata["analysis_profile"] = self.profiler.snapshot()
        with self.profiler.measure("serialization"):
            graph_payload = resolved.to_dict()
            if self.cache_metadata is not None:
                cache_status = "miss"
                cache_reason = "cache_not_initialized"
                if self.cache_load is not None:
                    cache_status, cache_reason = self.cache_load.status, self.cache_load.reason
                self.cache_metadata = CacheMetadata.from_project(
                    self.project_path,
                    scope=self.options.scope,
                    plugin_plan=self.selection_plan,
                    snapshot=self.current_snapshot or persistent_project_snapshot(self.project_path, self.options.scope),
                    cache_status=cache_status,
                    cache_reason=cache_reason,
                )
                resolved.metadata["cache"] = self.cache_metadata.to_dict()
                graph_payload = resolved.to_dict()
                facts = FactDocument.from_graph(resolved)
                reverse = build_reverse_dependency_index(resolved).to_dict()
                self.cache_store.write_bundle(
                    self.cache_metadata,
                    {
                        "graph.json": graph_payload,
                        "facts.json": facts.to_dict(),
                        "reverse_index.json": reverse,
                        "snapshot.json": self.current_snapshot or persistent_project_snapshot(self.project_path, self.options.scope),
                        "snapshot_stats.json": project_snapshot_stats(self.project_path, self.options.scope),
                        "inventory.json": inventory_data,
                        "raw_file_fragments.json": resolved.metadata.get("raw_file_fragments", {}),
                        "raw_extraction_file_fragments.json": resolved.metadata.get("raw_extraction_file_fragments", {}),
                    },
                )
            graph_path = self._write_graph_payload(graph_payload)
        profiling = self.profiler.snapshot()

        return AnalysisResult(
            status="ok",
            path=self.project_path,
            project_path=self.project_path,
            graph_path=graph_path,
            inventory=inventory_data,
            languages=languages,
            extractors_used=self.extractors_used,
            diagnostics=self.diagnostics.to_legacy_dict(),
            support_pack_load_errors=self.support_pack_load_errors,
            nodes=len(resolved.nodes),
            edges=len(resolved.edges),
            graph=graph_payload,
            progress=progress,
            profiling=profiling,
        )

    def _finish_no_graph_delta_incremental(self, inventory_data: dict[str, Any]) -> AnalysisResult:
        """Commit a content-only change without rerunning semantic resolution."""
        graph = self.reusable_final_graph
        graph_payload = self.reusable_final_graph_payload
        if graph is None and graph_payload is None:
            raise RuntimeError("incremental graph reuse requested without a graph")
        if graph_payload is None:
            graph_payload = graph.to_dict()
        metadata = dict(graph_payload.get("metadata", {}))
        metadata["incremental_cache"] = dict(self.incremental_cache_stats)
        metadata["selective_execution"] = {
            "execution_mode": "selective_plugin_execution",
            "full_pipeline_called": False,
            "selective_execution_proven": True,
            "selected_language_plugins": list(self.selective_language_ids or []),
            "skipped_language_plugins": [
                item for item in (self.selection_plan.selected_language_ids if self.selection_plan else [])
                if item not in (self.selective_language_ids or [])
            ],
            "fallback_reason": None,
            "graph_delta": "none",
        }
        if self.cache_metadata is not None:
            self.cache_metadata = replace(self.cache_metadata, cache_status="partial", cache_reason="incremental_no_graph_delta")
            metadata["cache"] = self.cache_metadata.to_dict()
            self.cache_store.update_metadata(
                self.cache_metadata,
                {
                    "snapshot.json": self.current_snapshot or persistent_project_snapshot(self.project_path, self.options.scope),
                    "snapshot_stats.json": project_snapshot_stats(self.project_path, self.options.scope),
                    "inventory.json": inventory_data,
                },
            )
        self._progress("final", 1, 1, "Изменение не меняет граф; semantic cache переиспользован")
        progress = {"status": "completed", "events": self.progress_events, "current": self.progress_events[-1]}
        metadata["analysis_progress"] = progress
        self._record_profile_work()
        metadata["analysis_profile"] = self.profiler.snapshot()
        graph_payload["metadata"] = metadata
        with self.profiler.measure("serialization"):
            graph_path = self._write_graph_payload(graph_payload)
        profiling = self.profiler.snapshot()
        nodes = len(graph_payload.get("nodes", []))
        edges = len(graph_payload.get("edges", []))
        return AnalysisResult(
            status="ok", path=self.project_path, project_path=self.project_path, graph_path=graph_path,
            inventory=inventory_data, languages=self.selection_plan.languages if self.selection_plan else [],
            extractors_used=list(self.extractors_used) + ["persistent_final_graph_cache"],
            diagnostics=self.diagnostics.to_legacy_dict(), support_pack_load_errors=self.support_pack_load_errors,
            nodes=nodes, edges=edges, graph=graph_payload, progress=progress, profiling=profiling,
        )

    def _record_profile_work(self) -> None:
        stats = self.incremental_cache_stats
        if not stats:
            return
        self.profiler.add_work(
            files_reused=stats.get("files_reused", 0),
            files_reparsed=stats.get("files_reanalyzed", 0),
            facts_reused=stats.get("facts_reused", 0),
            facts_rebuilt=stats.get("facts_rebuilt", 0),
            edges_reused=stats.get("edges_reused", 0),
            edges_rebuilt=len(stats.get("invalidated_edges", []) or []),
        )

    def _try_fast_cache_hit(self) -> AnalysisResult | None:
        """Reuse a complete cache after a stat-only no-change validation."""
        if (
            self.options.changed_files is not None
            or self.options.graphify_path
            or self.options.support_packs is not None
            or self.options.enable_remote_registry
        ):
            return None
        with self.profiler.measure("cache_lookup"):
            loaded = self.cache_store.load(
                artifact_names=("graph.json", "facts.json", "snapshot.json", "snapshot_stats.json", "inventory.json")
            )
        metadata = loaded.metadata or {}
        stats = loaded.artifacts.get("snapshot_stats.json") if loaded.hit else None
        inventory = loaded.artifacts.get("inventory.json") if loaded.hit else None
        if not loaded.hit or not isinstance(stats, dict) or not isinstance(inventory, dict):
            return None
        expected_scope = (self.options.scope or ".").replace("\\", "/").strip("/") or "."
        if metadata.get("project_root_identity") != root_identity(self.project_path) or metadata.get("scan_scope") != expected_scope:
            return None
        current_git = git_context(self.project_path)
        for key in ("branch", "ref", "head_fingerprint", "base_fingerprint"):
            if metadata.get(key) != current_git.get(key):
                return None
        with self.profiler.measure("snapshot_hashing"):
            current_stats = project_snapshot_stats(self.project_path, self.options.scope)
        if stats != current_stats:
            # Editors and copy tools can rewrite mtime metadata without
            # changing bytes. Confirm only the cached snapshot in that case;
            # a real content delta still falls through to full inventory.
            with self.profiler.measure("snapshot_hashing"):
                current_snapshot = persistent_project_snapshot(self.project_path, self.options.scope)
            if current_snapshot != loaded.artifacts.get("snapshot.json", {}):
                return None
        graph_payload = loaded.artifacts.get("graph.json", {})
        graph_metadata = graph_payload.setdefault("metadata", {})
        cached_tree_sitter_status = graph_metadata.get("tree_sitter_status")
        if cached_tree_sitter_status in {"native", "partial_local_fallback"}:
            try:
                from impact_engine.extractors.tree_sitter.adapter import is_tree_sitter_available

                current_tree_sitter_status = "native" if is_tree_sitter_available() else "partial_local_fallback"
                if current_tree_sitter_status != cached_tree_sitter_status:
                    return None
            except Exception:
                return None
        snapshot = loaded.artifacts.get("snapshot.json", {})
        # A source snapshot says nothing about upgraded framework packs. Check
        # their small registry fingerprint, not a second inventory traversal
        # of the user's complete project, before accepting the fast path.
        current_metadata = CacheMetadata.from_project(
            self.project_path,
            scope=self.options.scope,
            snapshot=snapshot if isinstance(snapshot, dict) else None,
            cache_status="hit",
            cache_reason="fast_cache_validation",
        )
        if metadata.get("plugin_registry_fingerprint") != current_metadata.plugin_registry_fingerprint:
            return None
        # The fast path intentionally avoids a full plugin scan, but it must
        # still reject a graph made by a different semantic pipeline or runtime.
        # Without this check an upgraded CodeSlicer executable can silently
        # serve pre-upgrade resolver results until a source file changes.
        for key in ("engine_version", "analysis_pipeline_version", "runtime_dependency_version", "graph_schema_version"):
            if metadata.get(key) != getattr(current_metadata, key):
                return None
        facts_payload = loaded.artifacts.get("facts.json", {})
        facts_reused = len(facts_payload.get("facts", [])) if isinstance(facts_payload, dict) else 0
        self.profiler.add_work(files_seen=len(snapshot), files_reused=len(snapshot), facts_reused=facts_reused)
        graph_metadata["cache"] = {
            "status": "hit", "reason": "cache_hit", "cache_status": "hit", "cache_reason": "cache_hit",
            "branch": metadata.get("branch"), "snapshot": metadata.get("source_snapshot_hash"),
            "scope": metadata.get("scan_scope", "."), "plugins": metadata.get("selected_plugins", []),
            "files_reused": len(snapshot), "files_reanalyzed": 0,
            "facts_reused": facts_reused, "facts_rebuilt": 0,
        }
        event = {
            "phase": "cache", "stage": "cache", "message": "Persistent cache reused",
            "completed": 1, "processed": 1, "total": 1, "stage_percent": 100.0,
            "overall_percent": 100.0, "elapsed_seconds": 0.0, "eta_seconds": None, "cancellable": False,
        }
        if self.options.progress_callback:
            self.options.progress_callback(event)
        progress = {"status": "completed", "events": [event], "current": event}
        graph_metadata["analysis_progress"] = progress
        with self.profiler.measure("serialization"):
            graph_path = self._write_graph_payload(graph_payload)
        selected = metadata.get("selected_plugins", [])
        languages = sorted({
            str(item.get("language") or str(item.get("id", "")).removeprefix("language."))
            for item in selected if item.get("kind") == "language"
        })
        return AnalysisResult(
            status="ok", path=self.project_path, project_path=self.project_path, graph_path=graph_path,
            inventory=inventory, languages=languages,
            extractors_used=list(graph_metadata.get("extractors_used", [])) + ["persistent_cache"],
            diagnostics=graph_metadata.get("analysis_diagnostics", {"items": [], "normal_analyze_requires_internet": False}),
            support_pack_load_errors=list(graph_metadata.get("support_pack_load_errors", [])),
            nodes=len(graph_payload.get("nodes", [])), edges=len(graph_payload.get("edges", [])), graph=graph_payload, progress=progress,
            profiling=self.profiler.snapshot(),
        )

    def _deep_resolution_enabled(self, graph: GraphDocument) -> bool:
        calls = sum(1 for node in graph.nodes if node.kind == "CALL_EXPR")
        budget = {"max_nodes": 30_000, "max_calls": 12_000}
        enabled = self.options.force_full_resolution or (len(graph.nodes) <= budget["max_nodes"] and calls <= budget["max_calls"])
        graph.metadata["deep_resolution_budget"] = {"status": "enabled" if enabled else "skipped_by_scale_budget", "force_full_resolution": self.options.force_full_resolution, "nodes": len(graph.nodes), "calls": calls, **budget}
        if not enabled:
            self.diagnostics.add("deep_resolution_skipped_by_scale_budget", "Large project: semantic and precision enrichment skipped; structural extraction is complete. Re-run with --full-resolution to opt in.", component="analysis.scale_budget", severity="warning", actionable=True, details=graph.metadata["deep_resolution_budget"])
        return enabled

    def _should_defer_unknown_regions(self, graph: GraphDocument) -> bool:
        """Avoid materializing a global gaps report that would dominate a large run.

        The structural graph and its explicit deep-resolution coverage marker
        remain available. A detailed unknown-region inventory can be requested
        separately; it is not required to return a useful, evidence-backed
        graph for a large workspace.
        """
        return bool(
            len(graph.nodes) > 30_000
            or sum(1 for node in graph.nodes if node.kind == "CALL_EXPR") > 12_000
        )

    def _annotate_unknown_regions(self, graph: GraphDocument) -> None:
        """Record unresolved regions without changing semantic graph edges."""
        try:
            report = analyze_unknown_regions(graph)
            graph.metadata["unknown_regions"] = report
            requests = build_research_requests(
                report, project_path=self.project_path
            )
            graph.metadata["all_unknown_regions"] = report.get("counts", {})
            graph.metadata["candidate_ai_tasks"] = report.get("research_selection", {}).get("candidate_count", 0)
            graph.metadata["selected_ai_tasks"] = len(requests)
            graph.metadata["research_patterns"] = report.get("research_selection", {}).get("unique_patterns", 0)
            graph.metadata["unknown_region_research_requests"] = requests
            if Path(self.project_path).is_dir():
                task_path = write_research_requests(
                    graph.metadata["unknown_region_research_requests"],
                    Path(self.project_path) / ".impact_engine" / "unknown_region_tasks.json",
                )
                graph.metadata["unknown_region_tasks_path"] = task_path
        except Exception as exc:
            self.diagnostics.add(
                "unknown_regions_error",
                str(exc),
                component="unknown_regions",
                severity="warning",
                actionable=True,
            )

    def _build_pre_hygiene(self, inventory_data: dict[str, Any]) -> dict[str, Any]:
        try:
            return build_pre_project_hygiene(inventory_data, self.project_path)
        except Exception as exc:
            self.diagnostics.add(
                "pre_project_hygiene_error",
                str(exc),
                component="project_hygiene.pre",
                severity="warning",
                actionable=True,
            )
            return {}

    def _scan_inventory(self) -> dict[str, Any]:
        import time
        started = time.perf_counter()
        try:
            project_root = Path(self.options.project_path).resolve()
            prefix = (self.options.scope or "").replace("\\", "/").strip("/")
            if prefix == ".":
                prefix = ""
            scan_root = project_root / prefix if prefix else project_root
            result = asdict(scan_project_inventory(scan_root))
            if prefix:
                # Scan the package itself, not the monorepo root. This keeps
                # dependency/import evidence local to the requested scope and
                # prevents a backend pack from activating for a frontend app.
                result["files"] = [f"{prefix}/{value}" for value in result.get("files", [])]
                result["package_manifests"] = [f"{prefix}/{value}" for value in result.get("package_manifests", [])]
                result["root_path"] = str(project_root.as_posix())
                result["scope"] = self.options.scope
            result["files_count"] = len(result.get("files", []))
            self._inventory_data = result
            self._inventory_files = result.get("files", [])
            self.stage_timings["inventory"] = round(time.perf_counter() - started, 4)
            return result
        except Exception as exc:
            self.diagnostics.add(
                "inventory_error",
                str(exc),
                component="inventory",
                severity="error",
                actionable=True,
            )
            return {}

    def _extract_graphs(self, plan: PluginSelectionPlan) -> list[GraphDocument]:
        import time
        started = time.perf_counter()
        inventory_files = list(getattr(self, "_inventory_files", []) or [])
        selected_language_ids = set(self.selective_language_ids or plan.selected_language_ids)
        extensions: set[str] = set()
        if plan.registry is not None:
            for plugin_id in selected_language_ids:
                manifest = plan.registry.manifests.get(plugin_id)
                if manifest is not None:
                    extensions.update(str(item).lower() for item in manifest.file_extensions)
        source_files = [item for item in inventory_files if Path(str(item)).suffix.lower() in extensions]
        extraction_scope = self.options.changed_files if self.options.changed_files is not None else inventory_files
        if self.options.changed_files is not None:
            total_files = sum(1 for item in extraction_scope if Path(str(item)).suffix.lower() in extensions)
        else:
            total_files = len(source_files)
        self._progress("extraction", 0, max(1, total_files), "Извлечение исходных фактов")
        if self.options.changed_files is not None and self.options.raw_graph_cache_path:
            if self._try_reuse_final_graph_fragments(plan):
                self.stage_timings["extraction"] = round(time.perf_counter() - started, 4)
                self._progress("extraction", total_files, max(1, total_files), "Изменённый файл не изменил raw graph")
                return []
            cached = self._load_raw_cache()
            if cached is not None:
                result = self._refresh_changed_files(cached, plan)
                self.stage_timings["extraction"] = round(time.perf_counter() - started, 4)
                self._progress("extraction", total_files, max(1, total_files), "Извлечение из cache завершено")
                return result
        completed_files: set[str] = set()

        def report_extraction_progress(event: dict[str, Any]) -> None:
            # A file belongs to one language extractor.  Count unique paths so
            # multi-language projects get monotonically increasing progress.
            path = str(event.get("file") or "").replace("\\", "/")
            if path:
                completed_files.add(path)
            processed = min(total_files, len(completed_files))
            message = str(event.get("message") or "Извлечение исходных фактов")
            self._progress("extraction", processed, max(1, total_files), message)

        context = PluginContext(
            project_path=Path(self.project_path),
            inventory=getattr(self, "_inventory_data", {}),
            selected_plugins=plan.selected_ids(),
            cancellation=self.cancellation,
            timeout_seconds=30.0,
            progress_callback=report_extraction_progress,
        )
        # Inventory is the authoritative, pruned source set.  Passing it on a
        # full scan prevents every language extractor from walking the project
        # again (including non-source documentation and cache directories).
        extraction_files = extraction_scope
        raw_graphs, extractors, diagnostics = extract_selected_languages(
            plan, context, extraction_files, selected_ids=self.selective_language_ids
        )
        self.extractors_used.extend(extractors)
        self.plugin_diagnostics.extend(item.to_dict() for item in diagnostics)
        self.stage_timings["extraction"] = round(time.perf_counter() - started, 4)
        self._progress("extraction", total_files, max(1, total_files), "Извлечение исходных фактов завершено")
        return raw_graphs

    def _try_reuse_final_graph_fragments(self, plan: PluginSelectionPlan) -> bool:
        """Prove a content-only change without parsing the large raw graph cache."""
        with self.profiler.measure("cache_lookup"):
            fragment_cache = self.cache_store.load(artifact_names=("raw_extraction_file_fragments.json",))
        raw_fragments = None
        if fragment_cache.hit:
            raw_fragments = fragment_cache.artifacts.get("raw_extraction_file_fragments.json")
        # Caches written before the raw-extraction artifact existed remain
        # readable, but only pay for the legacy large artifact when needed.
        if not isinstance(raw_fragments, dict):
            with self.profiler.measure("cache_lookup"):
                legacy_cache = self.cache_store.load(artifact_names=("raw_file_fragments.json",))
            raw_fragments = legacy_cache.artifacts.get("raw_file_fragments.json") if legacy_cache.hit else None
        if not isinstance(raw_fragments, dict) or not raw_fragments:
            return False

        def relative(value: Any) -> str:
            text = str(value or "").replace("\\", "/")
            try:
                path = Path(text)
                if path.is_absolute():
                    text = path.resolve().relative_to(Path(self.project_path).resolve()).as_posix()
            except (ValueError, OSError):
                pass
            return text

        changed = {relative(item) for item in self.options.changed_files or []}
        changed_suffixes = {Path(item).suffix.lower() for item in changed if Path(item).suffix}
        selected = [
            plugin_id for plugin_id in plan.selected_language_ids
            if changed_suffixes.intersection(set(plan.registry.manifests[plugin_id].file_extensions))
        ] if plan.registry else []
        if not selected:
            self.selective_execution_fallback = "changed files have no manifest-owned language extension; all selected language plugins rerun"
            selected = list(plan.selected_language_ids)
        self.selective_language_ids = sorted(selected)

        context = PluginContext(
            project_path=Path(self.project_path), inventory=getattr(self, "_inventory_data", {}),
            selected_plugins=plan.selected_ids(), cancellation=self.cancellation, timeout_seconds=30.0,
        )
        rebuilt, extractors, diagnostics = extract_selected_languages(
            plan, context, list(changed), selected_ids=self.selective_language_ids
        )
        self.extractors_used.extend(extractors)
        self.plugin_diagnostics.extend(item.to_dict() for item in diagnostics)
        early_document = GraphDocument()
        for document in rebuilt:
            for node in document.nodes:
                early_document.add_node(node)
            for edge in document.edges:
                early_document.add_edge(edge)
        current_fragments = self._raw_file_fragments(early_document, changed)
        if not all(raw_fragments.get(file_name) == current_fragments.get(file_name) for file_name in changed):
            return False

        with self.profiler.measure("cache_lookup"):
            final_cache = self.cache_store.load(artifact_names=("graph.json",))
        previous_graph = final_cache.artifacts.get("graph.json") if final_cache.hit else None
        if not isinstance(previous_graph, dict):
            return False
        self.reusable_final_graph_payload = previous_graph
        total_files = len(getattr(self, "_inventory_files", []) or [])
        node_count = len(previous_graph.get("nodes", []))
        edge_count = len(previous_graph.get("edges", []))
        self.incremental_cache_stats = {
            "files_total": total_files, "files_reused": max(0, total_files - len(changed)),
            "files_reanalyzed": len(changed), "facts_reused": node_count, "facts_rebuilt": 0,
            "nodes_reused": node_count, "edges_reused": edge_count,
            "invalidated_nodes": [], "invalidated_edges": [],
            "cache_hit_rate": round(max(0, total_files - len(changed)) / total_files, 6) if total_files else 1.0,
            "dependency_invalidation": "none_raw_graph_delta", "graph_delta": "none",
        }
        return True

    def _extract_graphify(self, raw_graphs: list[GraphDocument]) -> None:
        if not self.options.graphify_path:
            return
        try:
            from impact_engine.adapters.graphify import from_graphify_file

            graph = from_graphify_file(self.options.graphify_path)
            raw_graphs.append(graph)
            self.extractors_used.append("graphify_adapter")
            self.diagnostics.add(
                "graphify_adapter",
                "Optional Graphify graph normalized as external structural input.",
                component="adapter.graphify",
                severity="info",
                actionable=False,
                details=graph.metadata,
            )
        except Exception as exc:
            self.diagnostics.add(
                "graphify_adapter_error",
                str(exc),
                component="adapter.graphify",
                severity="warning",
                actionable=True,
            )
            return

    def _load_raw_cache(self) -> GraphDocument | None:
        try:
            path = Path(self.options.raw_graph_cache_path or "")
            if not path.exists():
                return None
            # Raw graph caches are the largest incremental-only artifact. Use
            # the persistence decoder (orjson when available) instead of
            # materializing a second large UTF-8 string through stdlib json.
            from impact_engine.persistence import _read_json
            return GraphDocument.from_dict(_read_json(path))
        except Exception as exc:
            self.diagnostics.add(
                "raw_graph_cache_error",
                str(exc),
                component="incremental.raw_cache",
                severity="warning",
                actionable=True,
            )
            return None

    @staticmethod
    def _raw_file_fragments(graph: GraphDocument, files: set[str] | None = None) -> dict[str, str]:
        fragments: dict[str, dict[str, list[dict[str, Any]]]] = {}
        node_files: dict[str, set[str]] = {}
        for node in graph.nodes:
            file_name = str(node.properties.get("file") or node.properties.get("path") or node.properties.get("source_file") or "").replace("\\", "/")
            if file_name:
                node_files.setdefault(file_name, set()).add(node.id)
                fragments.setdefault(file_name, {"nodes": [], "edges": []})["nodes"].append(node.to_dict())
        for edge in graph.edges:
            owners = {str(ev.file).replace("\\", "/") for ev in edge.evidence if ev.file}
            owners |= {file_name for file_name, ids in node_files.items() if edge.from_node in ids or edge.to_node in ids}
            for file_name in owners:
                if files is None or file_name in files:
                    fragments.setdefault(file_name, {"nodes": [], "edges": []})["edges"].append(edge.to_dict())
        result = {}
        for file_name, fragment in fragments.items():
            if files is not None and file_name not in files:
                continue
            payload = json.dumps(fragment, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            result[file_name] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return result

    def _refresh_changed_files(self, cached: GraphDocument, plan: PluginSelectionPlan) -> list[GraphDocument]:
        from impact_engine.incremental import project_snapshot

        def relative(value: Any) -> str:
            text = str(value or "").replace("\\", "/")
            try:
                path = Path(text)
                if path.is_absolute():
                    text = path.resolve().relative_to(Path(self.project_path).resolve()).as_posix()
            except (ValueError, OSError):
                pass
            return text

        changed = {relative(item) for item in self.options.changed_files or []}
        # Extract only the changed language once. If its raw contribution is
        # byte-for-byte equivalent to the cached fragment, skip the expensive
        # reverse-index and whole-graph invalidation passes entirely.
        changed_suffixes = {Path(item).suffix.lower() for item in changed if Path(item).suffix}
        selected = [
            plugin_id for plugin_id in plan.selected_language_ids
            if changed_suffixes.intersection(set(plan.registry.manifests[plugin_id].file_extensions))
        ] if plan.registry else []
        if not selected:
            self.selective_execution_fallback = "changed files have no manifest-owned language extension; all selected language plugins rerun"
            selected = list(plan.selected_language_ids)
        self.selective_language_ids = sorted(selected)
        raw_fragments = cached.metadata.get("raw_file_fragments", {}) if isinstance(cached.metadata, dict) else {}
        if isinstance(raw_fragments, dict) and raw_fragments:
            context = PluginContext(
                project_path=Path(self.project_path), inventory=getattr(self, "_inventory_data", {}),
                selected_plugins=plan.selected_ids(), cancellation=self.cancellation, timeout_seconds=30.0,
            )
            early_rebuilt, early_extractors, early_diagnostics = extract_selected_languages(
                plan, context, list(changed), selected_ids=self.selective_language_ids
            )
            self.extractors_used.extend(early_extractors)
            self.plugin_diagnostics.extend(item.to_dict() for item in early_diagnostics)
            early_document = GraphDocument()
            for document in early_rebuilt:
                for node in document.nodes:
                    early_document.add_node(node)
                for edge in document.edges:
                    early_document.add_edge(edge)
            current_fragments = self._raw_file_fragments(early_document, changed)
            if all(raw_fragments.get(file_name) == current_fragments.get(file_name) for file_name in changed):
                previous_final = self.cache_load if self.cache_load and self.cache_load.hit else self.cache_store.load()
                previous_graph = previous_final.artifacts.get("graph.json") if previous_final.hit else None
                if previous_graph:
                    self.reusable_final_graph_payload = previous_graph
                    total_files = len(getattr(self, "_inventory_files", []) or [])
                    self.incremental_cache_stats = {
                        "files_total": total_files, "files_reused": max(0, total_files - len(changed)),
                        "files_reanalyzed": len(changed), "facts_reused": len(cached.nodes), "facts_rebuilt": 0,
                        "nodes_reused": len(cached.nodes), "edges_reused": len(cached.edges),
                        "invalidated_nodes": [], "invalidated_edges": [],
                        "cache_hit_rate": round(max(0, total_files - len(changed)) / total_files, 6) if total_files else 1.0,
                        "dependency_invalidation": "none_raw_graph_delta",
                        "graph_delta": "none",
                    }
                    return [cached]
            # The probe already parsed the changed files. Keep its graph for
            # the real delta path so a changed fragment is not extracted again.
            self.prefetched_incremental_graphs = early_rebuilt
        node_ids_to_remove: set[str] = set()
        for node in cached.nodes:
            node_file = node.properties.get("file") or node.properties.get("path") or node.properties.get("source_file")
            if node_file and relative(node_file) in changed:
                node_ids_to_remove.add(node.id)
        invalidated_edge_ids: set[str] = set()
        for edge in cached.edges:
            if any(relative(ev.file) in changed for ev in edge.evidence):
                invalidated_edge_ids.add(edge.id)
        # The reverse index invalidates importers/callers of an exported symbol
        # without deleting their nodes.  Their edges are rebuilt by the
        # semantic pass, which prevents stale edges after rename/delete while
        # preserving unrelated declarations.
        reverse_index = build_reverse_dependency_index(cached)
        changed_symbols = set(node_ids_to_remove)
        for source_id in changed_symbols:
            for record in reverse_index.by_source.get(source_id, []):
                invalidated_edge_ids.update(
                    edge.id for edge in cached.edges
                    if edge.from_node == record.dependent_id and edge.to_node == record.source_id
                )
        invalidated_edge_ids.update(
            edge.id for edge in cached.edges
            if edge.from_node in node_ids_to_remove or edge.to_node in node_ids_to_remove
        )
        self.invalidated_node_ids = set(node_ids_to_remove)
        kept = GraphDocument(metadata=dict(cached.metadata))
        for node in cached.nodes:
            if node.id not in node_ids_to_remove:
                kept.add_node(node)
        for edge in cached.edges:
            edge_file_changed = edge.id in invalidated_edge_ids
            # Keep cross-file evidence owned by unchanged files. Removing an
            # edge merely because one endpoint belongs to the changed file
            # loses importer facts and makes incremental output diverge from a
            # clean rebuild. Edges whose own evidence changed are rebuilt.
            if not edge_file_changed:
                kept.add_edge(edge)

        context = PluginContext(
            project_path=Path(self.project_path),
            inventory=getattr(self, "_inventory_data", {}),
            selected_plugins=plan.selected_ids(),
            cancellation=self.cancellation,
            timeout_seconds=30.0,
        )
        extractors: list[str] = []
        diagnostics: list[Any] = []
        rebuilt = self.prefetched_incremental_graphs
        if rebuilt is None:
            rebuilt, extractors, diagnostics = extract_selected_languages(
                plan, context, list(changed), selected_ids=self.selective_language_ids
            )
        else:
            self.prefetched_incremental_graphs = None
        changed_node_ids = {
            node.id for node in cached.nodes
            if (node.properties.get("file") or node.properties.get("path") or node.properties.get("source_file"))
            and relative(node.properties.get("file") or node.properties.get("path") or node.properties.get("source_file")) in changed
        }

        def changed_fragment(document: GraphDocument, node_ids: set[str] | None = None) -> str:
            nodes = [
                node.to_dict() for node in document.nodes
                if relative(node.properties.get("file") or node.properties.get("path") or node.properties.get("source_file")) in changed
            ]
            affected_ids = node_ids or {item["id"] for item in nodes}
            edges = [
                edge.to_dict() for edge in document.edges
                if any(relative(ev.file) in changed for ev in edge.evidence)
                or edge.from_node in affected_ids or edge.to_node in affected_ids
            ]
            return json.dumps({"nodes": sorted(nodes, key=lambda item: item["id"]), "edges": sorted(edges, key=lambda item: item["id"])}, sort_keys=True, ensure_ascii=False)

        rebuilt_document = GraphDocument()
        for document in rebuilt:
            for node in document.nodes:
                rebuilt_document.add_node(node)
            for edge in document.edges:
                rebuilt_document.add_edge(edge)
        if changed_fragment(cached, changed_node_ids) == changed_fragment(rebuilt_document):
            previous_final = self.cache_store.load()
            previous_graph = previous_final.artifacts.get("graph.json") if previous_final.hit else None
            if previous_graph:
                self.reusable_final_graph = GraphDocument.from_dict(previous_graph)
        refreshed: list[GraphDocument] = [kept] + rebuilt
        self.extractors_used.extend(extractors)
        self.plugin_diagnostics.extend(item.to_dict() for item in diagnostics)
        self.extractors_used.append("incremental_raw_cache")
        total_files = len(project_snapshot(self.project_path, self.options.scope))
        self.incremental_cache_stats = {
            "files_total": total_files,
            "files_reused": max(0, total_files - len(changed)),
            "files_reanalyzed": len(changed),
            "facts_reused": max(0, len(cached.nodes) - len(node_ids_to_remove)),
            "facts_rebuilt": len(node_ids_to_remove),
            "nodes_reused": max(0, len(cached.nodes) - len(node_ids_to_remove)),
            "edges_reused": sum(
                1 for edge in cached.edges
                if not any((ev.file or "").replace("\\", "/") in changed for ev in edge.evidence)
            ),
            "invalidated_nodes": sorted(node_ids_to_remove),
            "invalidated_edges": sorted(invalidated_edge_ids),
            "cache_hit_rate": round(max(0, total_files - len(changed)) / total_files, 6) if total_files else 1.0,
            "dependency_invalidation": "evidence_and_receiver_subgraph",
        }
        if self.reusable_final_graph is not None:
            self.incremental_cache_stats["graph_delta"] = "none"
        kept.metadata["incremental_cache"] = dict(self.incremental_cache_stats)
        return refreshed

    def _merge_and_normalize(self, raw_graphs: list[GraphDocument]) -> GraphDocument:
        import time
        started = time.perf_counter()
        graph = merge_graph_documents(raw_graphs) if raw_graphs else GraphDocument()
        graph.metadata["raw_extraction_file_fragments"] = self._raw_file_fragments(graph)
        graph.metadata["project_path"] = self.project_path
        # Incremental refreshes merge a reused graph with rebuilt contributions
        # in a different arrival order than a clean scan. Canonical ordering
        # before semantic resolution prevents resolver tie-breaking from
        # changing unrelated call targets between the two paths.
        graph.nodes.sort(key=lambda item: item.id)
        graph.edges.sort(key=lambda item: (item.from_node, item.to_node, item.kind, item.source, item.id))
        graph._node_index.clear()
        graph._edge_id_index.clear()
        graph = normalize_graph_document(graph)
        graph.metadata["raw_file_fragments"] = self._raw_file_fragments(graph)
        # Stale-edge pruning remains evidence-driven until the reverse index is
        # used to distinguish removed symbols from unchanged cross-file facts.
        # Do not remove endpoint edges speculatively here.
        reverse_index = build_reverse_dependency_index(graph)
        reverse_summary = reverse_index.to_dict()
        # The full reverse index is persisted as a dedicated cache artifact
        # below. Duplicating every record inside graph.json makes a large
        # workspace graph needlessly expensive to load in a local UI, while
        # the graph itself does not consume these records at query time.
        graph.metadata["reverse_dependency_index"] = {
            key: reverse_summary[key]
            for key in ("record_count", "source_count", "dependent_count")
        }
        if self.incremental_cache_stats:
            graph.metadata["incremental_cache"] = dict(self.incremental_cache_stats)
        if self.options.raw_graph_cache_path:
            try:
                cache_path = Path(self.options.raw_graph_cache_path).resolve()
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                write_json_atomic(cache_path, graph.to_dict())
            except Exception as exc:
                self.diagnostics.add("raw_graph_cache_write_error", str(exc), component="incremental.raw_cache", severity="warning", actionable=True)
        self.stage_timings["normalization"] = round(time.perf_counter() - started, 4)
        return graph

    def _apply_semantic_layer(self, graph: GraphDocument) -> GraphDocument:
        try:
            recipes = selected_semantic_recipes(self.selection_plan) if self.selection_plan else None
            return apply_semantic_resolution(graph, recipes=recipes)
        except Exception as exc:
            self.diagnostics.add(
                "semantic_binding_error",
                str(exc),
                component="semantic_binding",
                severity="warning",
                actionable=True,
            )
            return graph

    def _apply_post_hygiene_layer(self, graph: GraphDocument, inventory_data: dict[str, Any]) -> GraphDocument:
        try:
            return apply_post_project_hygiene(graph, inventory_data, self.project_path)
        except Exception as exc:
            self.diagnostics.add(
                "post_project_hygiene_error",
                str(exc),
                component="project_hygiene.post",
                severity="warning",
                actionable=True,
            )
            graph.metadata["post_project_hygiene_status"] = "error"
            graph.metadata["project_hygiene_status"] = "error"
            return graph

    def _record_graph_metadata(self, graph: GraphDocument) -> None:
        self.diagnostics.set_legacy("normal_analyze_requires_internet", False)
        capability_meta = graph.metadata.get("language_semantic_capabilities")
        if isinstance(capability_meta, dict):
            self.diagnostics.extend_metadata(
                "languages",
                "language_semantic_capabilities",
                capability_meta,
            )
        if graph.metadata.get("tree_sitter_status"):
            self.diagnostics.set_legacy("tree_sitter_status", graph.metadata.get("tree_sitter_status"))
        if graph.metadata.get("tree_sitter_diagnostics"):
            self.diagnostics.extend_metadata(
                "extractor.tree_sitter",
                "tree_sitter_diagnostics",
                graph.metadata.get("tree_sitter_diagnostics"),
            )
        semantic_meta = graph.metadata.get("semantic_binding_layer")
        if isinstance(semantic_meta, dict) and semantic_meta.get("diagnostics"):
            self.diagnostics.extend_metadata(
                "semantic_binding",
                "semantic_binding_diagnostics",
                semantic_meta.get("diagnostics"),
            )
        bridge_meta = graph.metadata.get("frontend_backend_endpoint_bridge")
        if isinstance(bridge_meta, dict):
            self.diagnostics.set_legacy("frontend_backend_endpoint_bridge_status", bridge_meta.get("status"))
            self.diagnostics.extend_metadata(
                "frontend_backend_endpoint_bridge",
                "frontend_backend_endpoint_bridge_summary",
                bridge_meta,
            )
        hygiene_meta = graph.metadata.get("project_hygiene")
        if isinstance(hygiene_meta, dict):
            self.diagnostics.set_legacy("project_hygiene_status", graph.metadata.get("project_hygiene_status"))
            self.diagnostics.set_legacy("pre_project_hygiene_status", graph.metadata.get("pre_project_hygiene_status"))
            self.diagnostics.set_legacy("post_project_hygiene_status", graph.metadata.get("post_project_hygiene_status"))
            self.diagnostics.extend_metadata(
                "project_hygiene",
                "project_hygiene_summary",
                hygiene_meta.get("summary", {}),
            )
        pre_hygiene_meta = graph.metadata.get("pre_project_hygiene")
        if isinstance(pre_hygiene_meta, dict):
            self.diagnostics.extend_metadata(
                "project_hygiene.pre",
                "pre_project_hygiene_summary",
                pre_hygiene_meta.get("summary", {}),
            )

    def _load_support_packs(self) -> list[Any]:
        if self.options.support_packs is not None:
            return list(self.options.support_packs)

        support_packs: list[Any] = []
        from impact_engine.support_packs.registry import load_support_pack, list_local_support_packs, validate_support_pack_file

        try:
            loaded_keys: set[tuple[str, str]] = set()
            # Project-local packs are explicit personalization. They are loaded
            # before shared packs, so a validated project rule can refine a
            # private SDK or custom wrapper without changing the global registry.
            from impact_engine.project_packs import load_project_packs

            project_packs, project_pack_errors = load_project_packs(self.project_path)
            self.support_pack_load_errors.extend(project_pack_errors)
            for pack in project_packs:
                key = (pack.language.lower(), pack.library.lower())
                if key in loaded_keys:
                    continue
                loaded_keys.add(key)
                support_packs.append(pack)

            # Global packs are selected by the plugin plan. The compatibility
            # adapter is deliberately narrow: it may load an old JSON pack,
            # but only for a manifest whose dependency/import evidence matched.
            selected = selected_compatibility_packs(self.selection_plan) if self.selection_plan else []
            for pack in selected:
                key = (pack.language.lower(), pack.library.lower())
                if key not in loaded_keys:
                    loaded_keys.add(key)
                    support_packs.append(pack)

            selected_libraries = {pack.library.lower() for pack in support_packs}
            # A caller-provided pack root remains supported, but its packs are
            # subject to the same evidence gate as built-in packs.
            paths = list_local_support_packs(self.options.support_pack_root)
            for pack_path in paths:
                validation = validate_support_pack_file(pack_path)
                if validation["valid"]:
                    try:
                        pack = load_support_pack(pack_path)
                        key = (pack.language.lower(), pack.library.lower())
                        library = pack.library.lower()
                        declared = {str(v).lower() for v in (self._inventory_data.get("declared_dependencies_by_ecosystem", {}).get(pack.language, []) or [])}
                        imports = {str(v).lower() for v in (self._inventory_data.get("external_imports_by_ecosystem", {}).get(pack.language, []) or [])}
                        if key in loaded_keys or not any(name == library or name.startswith(library + ".") or library in name for name in declared | imports):
                            continue
                        loaded_keys.add(key)
                        support_packs.append(pack)
                    except Exception as exc:
                        self.support_pack_load_errors.append(f"Failed to load pack from {pack_path}: {exc}")
                else:
                    errors = ", ".join(validation.get("errors", []))
                    self.support_pack_load_errors.append(f"Invalid pack {pack_path}: {errors}")

        except Exception as exc:
            self.diagnostics.add(
                "support_pack_loading_error",
                str(exc),
                component="support_packs",
                severity="warning",
                actionable=True,
            )
        return support_packs

    def _sync_local_registry(self, inventory_data: dict[str, Any]) -> dict[str, Any]:
        if not self.options.enable_remote_registry:
            return {"status": "disabled"}
        try:
            from impact_engine.remote_registry.sync import sync_registry_for_inventory

            return sync_registry_for_inventory(
                inventory_data,
                support_pack_root=self.options.support_pack_root,
                create_research_requests=self.options.create_research_requests,
            )
        except Exception as exc:
            self.diagnostics.add(
                "local_registry_sync_error",
                str(exc),
                component="local_registry",
                severity="warning",
                actionable=True,
            )
            return {"status": "error", "error": str(exc)}

    def _write_graph(self, graph: GraphDocument) -> str | None:
        return self._write_graph_payload(graph.to_dict())

    def _write_graph_payload(self, payload: dict[str, Any]) -> str | None:
        if not self.options.out_path:
            return None
        try:
            out_path = Path(self.options.out_path).resolve()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            write_json_atomic(out_path, payload)
            return str(out_path)
        except Exception as exc:
            self.diagnostics.add(
                "write_error",
                str(exc),
                component="storage.output",
                severity="error",
                actionable=True,
            )
            return None


def analyze_project_core(
    path: str,
    out_path: str | None = None,
    support_packs: list | None = None,
    support_pack_root: str = "support_packs",
    enable_remote_registry: bool = False,
    create_research_requests: bool = True,
    graphify_path: str | None = None,
    changed_files: list[str] | None = None,
    raw_graph_cache_path: str | None = None,
    progress_callback=None,
    cancellation=None,
    scope: str | None = None,
    memory_budget_mb: int | None = None,
    time_budget_seconds: float | None = None,
    force_full_resolution: bool = False,
) -> dict[str, Any]:
    """Backward-compatible analysis entrypoint used by CLI, MCP, and tests."""
    options = AnalysisOptions(
        project_path=path,
        out_path=out_path,
        support_packs=support_packs,
        support_pack_root=support_pack_root,
        enable_remote_registry=enable_remote_registry,
        create_research_requests=create_research_requests,
        graphify_path=graphify_path,
        changed_files=changed_files,
        raw_graph_cache_path=raw_graph_cache_path,
        progress_callback=progress_callback,
        cancellation=cancellation,
        scope=scope,
        memory_budget_mb=memory_budget_mb,
        time_budget_seconds=time_budget_seconds,
        force_full_resolution=force_full_resolution,
    )
    pipeline = AnalysisPipeline(options)
    result = pipeline.run()
    with pipeline.profiler.measure("serialization"):
        output = result.to_dict()
    output["profiling"] = pipeline.profiler.snapshot()
    return output
