from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from impact_engine.plugin_architecture.contracts import PluginContext, PluginDiagnostic, PluginResult

from .extractor import extract_csharp_project


@dataclass
class CSharpLanguagePlugin:
    manifest: Any

    def detect(self, context: PluginContext) -> bool:
        return "csharp" in {str(item).lower() for item in context.inventory.get("languages", [])}

    def plan(self, context: PluginContext) -> dict[str, Any]:
        return {"plugin_id": self.manifest.id, "cache_key": self.manifest.cache_key, "parser": "local_structural", "network": False}

    def extract(self, context: PluginContext, files: Sequence[str] | None = None) -> PluginResult:
        context.check_cancelled()
        graph = extract_csharp_project(
            str(context.project_path),
            files=files,
            cancellation=context.cancellation,
            progress_callback=context.report_progress,
        )
        graph.metadata.setdefault("plugin_provenance", []).append({
            "plugin_id": self.manifest.id,
            "version": self.manifest.version,
            "cache_key": self.manifest.cache_key,
            "phase": "extract",
            "parser": "local_structural",
        })
        return PluginResult(graph=graph, provenance={"plugin_id": self.manifest.id, "extractor_id": self.manifest.id})

    def resolve(self, context: PluginContext, graph: Any) -> PluginResult:
        graph.metadata.setdefault("csharp_provider", {}).update({
            "status": "supported",
            "parser": "local_semantic",
            "roslyn": "available" if graph.metadata.get("csharp_roslyn_available") else "unavailable",
            "network": False,
        })
        return PluginResult(graph=graph, provenance={"plugin_id": self.manifest.id, "phase": "resolve"})

    def validate(self, context: PluginContext, graph: Any) -> list[PluginDiagnostic]:
        diagnostics = []
        for item in graph.metadata.get("csharp_diagnostics", []) or []:
            diagnostics.append(PluginDiagnostic(self.manifest.id, "warning", item.get("code", "csharp_parse_warning"), item.get("message", "C# parse warning"), item))
        return diagnostics

    def diagnostics(self) -> list[PluginDiagnostic]:
        return []


def create_plugin(manifest):
    return CSharpLanguagePlugin(manifest)
