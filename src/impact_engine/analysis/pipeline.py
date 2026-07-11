"""Unified analysis orchestration layer."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from impact_engine.analysis.contracts import AnalysisOptions, AnalysisResult
from impact_engine.analysis.diagnostics import DiagnosticsCollector
from impact_engine.extractors.python_ast import extract_project
from impact_engine.extractors.tree_sitter.adapter import extract_tree_sitter_project, is_tree_sitter_available
from impact_engine.frontend_backend_bridge import apply_frontend_backend_endpoint_bridge
from impact_engine.inventory.scanner import scan_project_inventory
from impact_engine.languages.registry import detect_languages
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
from impact_engine.polyglot_semantics import apply_limited_polyglot_semantics
from impact_engine.incremental_index import build_reverse_dependency_index


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

    def _progress(self, stage: str, processed: int, total: int, message: str) -> None:
        weights = {
            "inventory": 0.10, "preparation": 0.05, "extraction": 0.35,
            "normalization": 0.10, "semantic": 0.15, "resolution": 0.15,
            "final": 0.10,
        }
        stage_percent = 100.0 if total <= 0 else min(100.0, max(0.0, processed / total * 100.0))
        ordered = list(weights)
        overall = sum(weights[name] * (stage_percent / 100.0 if name == stage else (1.0 if ordered.index(name) < ordered.index(stage) else 0.0)) for name in ordered)
        event = {
            "stage": stage,
            "message": message,
            "processed": processed,
            "total": total,
            "stage_percent": round(stage_percent, 1),
            "overall_percent": round(overall * 100.0, 1),
            "elapsed_seconds": round(__import__("time").perf_counter() - self.progress_started, 3),
        }
        self.progress_events.append(event)
        callback = self.options.progress_callback
        if callback:
            callback(event)

    def run(self) -> AnalysisResult:
        import time
        self._progress("inventory", 0, 1, "Сканирование файлов и manifest-файлов")
        inventory_data = self._scan_inventory()
        self._progress("inventory", 1, 1, f"Inventory завершён: {inventory_data.get('files_count', len(inventory_data.get('files', [])))} файлов")
        languages = self._detect_languages(inventory_data)
        pre_hygiene = self._build_pre_hygiene(inventory_data)
        self._progress("preparation", 1, 1, "Языки, зависимости и pre-hygiene определены")
        language_capabilities = build_language_capability_diagnostics(languages)
        raw_graphs = self._extract_graphs(languages)
        self._extract_graphify(raw_graphs)
        self._progress("normalization", 0, 1, "Нормализация фактов и структурного графа")
        graph = self._merge_and_normalize(raw_graphs)
        self._progress("normalization", 1, 1, "Нормализация завершена")
        fact_document = FactDocument.from_graph(graph)
        graph.metadata["fact_document"] = fact_document.summary()
        if Path(self.project_path).is_dir():
            fact_path = Path(self.project_path) / ".impact_engine" / "facts.json"
            fact_path.parent.mkdir(parents=True, exist_ok=True)
            fact_path.write_text(fact_document.to_json(), encoding="utf-8")
            graph.metadata["fact_document_path"] = str(fact_path.resolve())
        run_quality_gate(graph, "extraction_normalization")
        graph.metadata["language_semantic_capabilities"] = language_capabilities
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
        started = time.perf_counter()
        self._progress("semantic", 0, 1, "Semantic binding и support-pack context")
        graph = self._apply_semantic_layer(graph)
        self.stage_timings["semantic_binding"] = round(time.perf_counter() - started, 4)
        self._progress("semantic", 1, 1, "Semantic binding завершён")
        run_quality_gate(graph, "semantic_binding")
        local_registry_summary = self._sync_local_registry(inventory_data)
        started = time.perf_counter()
        self._progress("resolution", 0, 1, "Precision и framework resolution")
        resolved = resolve_precision(graph, support_packs=support_packs)
        resolved = apply_limited_polyglot_semantics(resolved, self.project_path)
        self.stage_timings["resolution"] = round(time.perf_counter() - started, 4)
        self._progress("resolution", 1, 1, "Resolution завершён")
        run_quality_gate(resolved, "generic_and_framework_resolution")
        if local_registry_summary:
            resolved.metadata["local_registry"] = local_registry_summary
        resolved = self._apply_frontend_backend_bridge(resolved)
        started = time.perf_counter()
        resolved = self._apply_post_hygiene_layer(resolved, inventory_data)
        self.stage_timings["post_hygiene_and_quality"] = round(time.perf_counter() - started, 4)
        resolved = apply_quality_guard(resolved)
        resolved = annotate_communities(resolved)
        resolved = annotate_stable_identities(resolved, self.project_path)
        resolved = annotate_edge_contracts(resolved)
        resolved = annotate_graph_quality(resolved)
        run_quality_gate(resolved, "final_graph")
        self._annotate_unknown_regions(resolved)
        resolved.metadata["resolution_coverage"] = build_resolution_coverage(resolved)
        resolved.metadata["coverage_quality_gate"] = {
            "status": "ok" if resolved.metadata["resolution_coverage"].get("accounting", {}).get("valid") else "warning",
            "accounting": resolved.metadata["resolution_coverage"].get("accounting", {}),
        }
        resolved.metadata["stage_timings_seconds"] = dict(self.stage_timings)
        self._progress("final", 0, 1, "Quality guard, diagnostics и fingerprint")
        self._record_graph_metadata(resolved)
        self._progress("final", 1, 1, "Анализ завершён")
        progress = {"status": "completed", "events": self.progress_events, "current": self.progress_events[-1]}
        resolved.metadata["analysis_progress"] = progress
        graph_path = self._write_graph(resolved)

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
            graph=resolved.to_dict(),
            progress=progress,
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
            result = asdict(scan_project_inventory(self.options.project_path))
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

    def _detect_languages(self, inventory_data: dict[str, Any]) -> list[str]:
        languages = list(inventory_data.get("languages", []))
        if languages:
            return languages
        try:
            return list(detect_languages(self.options.project_path))
        except Exception as exc:
            self.diagnostics.add(
                "language_detection_error",
                str(exc),
                component="languages",
                severity="warning",
                actionable=True,
            )
            return []

    def _extract_graphs(self, languages: list[str]) -> list[GraphDocument]:
        import time
        started = time.perf_counter()
        total_files = len(getattr(self, "_inventory_files", []) or [])
        self._progress("extraction", 0, max(1, total_files), "Извлечение исходных фактов")
        if self.options.changed_files is not None and self.options.raw_graph_cache_path:
            cached = self._load_raw_cache()
            if cached is not None:
                result = self._refresh_changed_files(cached, languages)
                self.stage_timings["extraction"] = round(time.perf_counter() - started, 4)
                self._progress("extraction", total_files, max(1, total_files), "Извлечение из cache завершено")
                return result
        raw_graphs: list[GraphDocument] = []
        if "python" in languages or not languages:
            self._extract_python(raw_graphs, self.options.changed_files)
        tree_sitter_languages = [lang for lang in languages if lang in {"javascript", "typescript", "go", "java"}]
        if tree_sitter_languages:
            self._extract_tree_sitter(raw_graphs, tree_sitter_languages, self.options.changed_files)
        self.stage_timings["extraction"] = round(time.perf_counter() - started, 4)
        self._progress("extraction", total_files, max(1, total_files), "Извлечение исходных фактов завершено")
        return raw_graphs

    def _extract_python(self, raw_graphs: list[GraphDocument], files: list[str] | None = None) -> None:
        try:
            raw_graphs.append(extract_project(self.options.project_path, files=files))
            self.extractors_used.append("python_ast")
        except Exception as exc:
            self.diagnostics.add(
                "python_extractor_error",
                str(exc),
                component="extractor.python_ast",
                severity="error",
                actionable=True,
            )

    def _extract_tree_sitter(self, raw_graphs: list[GraphDocument], languages: list[str], files: list[str] | None = None) -> None:
        if not is_tree_sitter_available():
            self.diagnostics.add(
                "tree_sitter_diagnostic",
                "Tree-sitter is unavailable; multi-language analysis skipped.",
                component="extractor.tree_sitter",
                severity="warning",
                actionable=True,
            )
            return
        try:
            graph = extract_tree_sitter_project(self.options.project_path, languages=languages, files=files)
            raw_graphs.append(graph)
            self.extractors_used.append("tree_sitter")
            errors = graph.metadata.get("tree_sitter_errors", [])
            if errors:
                self.diagnostics.add(
                    "tree_sitter_errors",
                    errors,
                    component="extractor.tree_sitter",
                    severity="warning",
                    actionable=True,
                    details=errors,
                )
        except Exception as exc:
            self.diagnostics.add(
                "tree_sitter_extractor_error",
                str(exc),
                component="extractor.tree_sitter",
                severity="warning",
                actionable=True,
            )

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
            return GraphDocument.from_json(path.read_text(encoding="utf-8"))
        except Exception as exc:
            self.diagnostics.add(
                "raw_graph_cache_error",
                str(exc),
                component="incremental.raw_cache",
                severity="warning",
                actionable=True,
            )
            return None

    def _refresh_changed_files(self, cached: GraphDocument, languages: list[str]) -> list[GraphDocument]:
        from impact_engine.incremental import project_snapshot

        changed = {str(item).replace("\\", "/") for item in self.options.changed_files or []}
        node_ids_to_remove: set[str] = set()
        for node in cached.nodes:
            node_file = node.properties.get("file") or node.properties.get("path") or node.properties.get("source_file")
            if node_file and str(node_file).replace("\\", "/") in changed:
                node_ids_to_remove.add(node.id)
        for edge in cached.edges:
            if any((ev.file or "").replace("\\", "/") in changed for ev in edge.evidence):
                node_ids_to_remove.update((edge.from_node, edge.to_node))
        self.invalidated_node_ids = set(node_ids_to_remove)
        kept = GraphDocument(metadata=dict(cached.metadata))
        for node in cached.nodes:
            if node.id not in node_ids_to_remove:
                kept.add_node(node)
        for edge in cached.edges:
            edge_file_changed = any((ev.file or "").replace("\\", "/") in changed for ev in edge.evidence)
            # Keep cross-file evidence owned by unchanged files. Removing an
            # edge merely because one endpoint belongs to the changed file
            # loses importer facts and makes incremental output diverge from a
            # clean rebuild. Edges whose own evidence changed are rebuilt.
            if not edge_file_changed:
                kept.add_edge(edge)

        refreshed: list[GraphDocument] = [kept]
        if "python" in languages or not languages:
            self._extract_python(refreshed, list(changed))
        tree_sitter_languages = [lang for lang in languages if lang in {"javascript", "typescript", "go", "java"}]
        if tree_sitter_languages:
            self._extract_tree_sitter(refreshed, tree_sitter_languages, list(changed))
        self.extractors_used.append("incremental_raw_cache")
        total_files = len(project_snapshot(self.project_path))
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
            "cache_hit_rate": round(max(0, total_files - len(changed)) / total_files, 6) if total_files else 1.0,
            "dependency_invalidation": "evidence_and_receiver_subgraph",
        }
        kept.metadata["incremental_cache"] = dict(self.incremental_cache_stats)
        return refreshed

    def _merge_and_normalize(self, raw_graphs: list[GraphDocument]) -> GraphDocument:
        import time
        started = time.perf_counter()
        graph = merge_graph_documents(raw_graphs) if raw_graphs else GraphDocument()
        graph.metadata["project_path"] = self.project_path
        graph = normalize_graph_document(graph)
        # Stale-edge pruning remains evidence-driven until the reverse index is
        # used to distinguish removed symbols from unchanged cross-file facts.
        # Do not remove endpoint edges speculatively here.
        reverse_index = build_reverse_dependency_index(graph)
        reverse_summary = reverse_index.to_dict()
        graph.metadata["reverse_dependency_index"] = {key: reverse_summary[key] for key in ("record_count", "source_count", "dependent_count")}
        if self.incremental_cache_stats:
            graph.metadata["incremental_cache"] = dict(self.incremental_cache_stats)
        if self.options.raw_graph_cache_path:
            try:
                cache_path = Path(self.options.raw_graph_cache_path).resolve()
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(graph.to_json(), encoding="utf-8")
            except Exception as exc:
                self.diagnostics.add("raw_graph_cache_write_error", str(exc), component="incremental.raw_cache", severity="warning", actionable=True)
        self.stage_timings["normalization"] = round(time.perf_counter() - started, 4)
        return graph

    def _apply_semantic_layer(self, graph: GraphDocument) -> GraphDocument:
        try:
            return apply_semantic_resolution(graph)
        except Exception as exc:
            self.diagnostics.add(
                "semantic_binding_error",
                str(exc),
                component="semantic_binding",
                severity="warning",
                actionable=True,
            )
            return graph

    def _apply_frontend_backend_bridge(self, graph: GraphDocument) -> GraphDocument:
        try:
            return apply_frontend_backend_endpoint_bridge(graph)
        except Exception as exc:
            self.diagnostics.add(
                "frontend_backend_endpoint_bridge_error",
                str(exc),
                component="frontend_backend_endpoint_bridge",
                severity="warning",
                actionable=True,
            )
            graph.metadata["frontend_backend_endpoint_bridge"] = {"status": "error", "error": str(exc)}
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
        from impact_engine.support_packs.schema import support_pack_from_dict

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

            # A checked-in/project pack is the source of truth for the current
            # analysis. Registry and cache copies are fallbacks only; otherwise
            # a stale SQLite row can silently shadow a newer pack on disk.
            paths = list_local_support_packs(self.options.support_pack_root)
            cache_root = ".impact_engine/registry_cache/support_packs"
            for pack_path in paths:
                validation = validate_support_pack_file(pack_path)
                if validation["valid"]:
                    try:
                        pack = load_support_pack(pack_path)
                        key = (pack.language.lower(), pack.library.lower())
                        # The project registry wins over a compatibility/cache
                        # export. Duplicate packs can otherwise emit conflicting
                        # route identities and duplicate inferred edges.
                        if key in loaded_keys:
                            continue
                        loaded_keys.add(key)
                        support_packs.append(pack)
                    except Exception as exc:
                        self.support_pack_load_errors.append(f"Failed to load pack from {pack_path}: {exc}")
                else:
                    errors = ", ".join(validation.get("errors", []))
                    self.support_pack_load_errors.append(f"Invalid pack {pack_path}: {errors}")

            # SQLite registry and exported cache provide reusable packs when a
            # project does not ship its own copy. They must never override one.
            try:
                from impact_engine.remote_registry import RegistryClient

                for data in RegistryClient().list_local_support_packs():
                    pack = support_pack_from_dict(data)
                    key = (pack.language.lower(), pack.library.lower())
                    if key in loaded_keys:
                        continue
                    support_packs.append(pack)
                    loaded_keys.add(key)
            except Exception as exc:
                self.support_pack_load_errors.append(f"Failed to load local registry packs: {exc}")

            for pack_path in list_local_support_packs(cache_root):
                validation = validate_support_pack_file(pack_path)
                if not validation["valid"]:
                    continue
                try:
                    pack = load_support_pack(pack_path)
                    key = (pack.language.lower(), pack.library.lower())
                    if key in loaded_keys:
                        continue
                    support_packs.append(pack)
                    loaded_keys.add(key)
                except Exception as exc:
                    self.support_pack_load_errors.append(f"Failed to load cached pack from {pack_path}: {exc}")
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
        if not self.options.out_path:
            return None
        try:
            out_path = Path(self.options.out_path).resolve()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(graph.to_json(), encoding="utf-8")
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
    )
    return AnalysisPipeline(options).run().to_dict()
