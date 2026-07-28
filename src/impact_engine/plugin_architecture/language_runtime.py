"""Neutral reusable runtime for manifest-owned language plugins."""
from __future__ import annotations

from dataclasses import dataclass
import inspect
from typing import Any, Callable, Sequence

from impact_engine.extractors.tree_sitter.adapter import extract_tree_sitter_project

from .contracts import PluginContext, PluginDiagnostic, PluginManifest, PluginResult


@dataclass
class ManifestLanguagePlugin:
    manifest: PluginManifest
    extractor: Callable[..., Any]
    resolver: Callable[[PluginContext, Any], Any] | None = None

    def detect(self, context: PluginContext) -> bool:
        return self.manifest.language.lower() in {str(item).lower() for item in context.inventory.get("languages", [])}

    def plan(self, context: PluginContext) -> dict[str, Any]:
        return {"plugin_id": self.manifest.id, "cache_key": self.manifest.cache_key, "files": context.inventory.get("files", [])}

    def extract(self, context: PluginContext, files: Sequence[str] | None = None) -> PluginResult:
        context.check_cancelled()
        parameters = inspect.signature(self.extractor).parameters
        kwargs: dict[str, Any] = {"files": list(files) if files is not None else None}
        # Older third-party extractors remain compatible.  First-party
        # extractors opt in to these two cooperative controls.
        if "cancellation" in parameters:
            kwargs["cancellation"] = context.cancellation
        if "progress_callback" in parameters:
            kwargs["progress_callback"] = context.report_progress
        graph = self.extractor(str(context.project_path), **kwargs)
        graph.metadata.setdefault("plugin_provenance", []).append({
            "plugin_id": self.manifest.id,
            "version": self.manifest.version,
            "cache_key": self.manifest.cache_key,
            "phase": "extract",
        })
        return PluginResult(graph=graph, provenance={"plugin_id": self.manifest.id, "extractor_id": self.manifest.id})

    def resolve(self, context: PluginContext, graph: Any) -> PluginResult:
        if self.resolver is not None:
            graph = self.resolver(context, graph)
        return PluginResult(graph=graph, provenance={"plugin_id": self.manifest.id, "phase": "resolve"})

    def validate(self, context: PluginContext, graph: Any) -> list[PluginDiagnostic]:
        return []

    def diagnostics(self) -> list[PluginDiagnostic]:
        return []


def tree_sitter_extractor(language: str) -> Callable[..., Any]:
    """Return a language-bound extractor without language branching in core."""
    def extract(project_path: str, files: Sequence[str] | None = None, *, cancellation=None, progress_callback=None):
        return extract_tree_sitter_project(
            project_path,
            languages=[language],
            files=list(files) if files is not None else None,
            cancellation=cancellation,
            progress_callback=progress_callback,
        )
    return extract
