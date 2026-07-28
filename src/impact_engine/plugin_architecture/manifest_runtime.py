"""Generic runtime for manifest-backed plugins.

This module intentionally has no knowledge of a particular language,
framework, or library. Pack-specific behavior is discovered from files beside
the manifest after the selection plan has activated the pack.
"""
from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .contracts import PluginContext, PluginDiagnostic, PluginManifest, PluginResult


def _load_module(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load plugin module {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@dataclass
class ManifestFrameworkPlugin:
    manifest: PluginManifest

    def detect(self, context: PluginContext) -> bool:
        return True

    def plan(self, context: PluginContext) -> dict[str, Any]:
        return {"plugin_id": self.manifest.id, "cache_key": self.manifest.cache_key}

    def extract(self, context: PluginContext, files: Sequence[str] | None = None) -> PluginResult:
        return PluginResult()

    def resolve(self, context: PluginContext, graph: Any) -> PluginResult:
        return PluginResult(graph=graph, provenance={"pack_id": self.manifest.id, "phase": "resolve"})

    def validate(self, context: PluginContext, graph: Any) -> list[PluginDiagnostic]:
        return []

    def diagnostics(self) -> list[PluginDiagnostic]:
        return []

    @property
    def _pack_dir(self) -> Path:
        if not self.manifest.path:
            raise ImportError(f"manifest path is unavailable for {self.manifest.id}")
        return Path(self.manifest.path).parent

    def load_compatibility_pack(self) -> Any:
        from impact_engine.support_packs.registry import load_support_pack
        from impact_engine.support_packs.paths import builtin_support_packs_root

        source = self.manifest.activation.get("compat_source")
        if not source:
            return None
        path = builtin_support_packs_root() / Path(str(source)).relative_to("support_packs")
        return load_support_pack(path) if path.is_file() else None

    def semantic_recipes(self) -> list[Any]:
        recipe_path = self._pack_dir / "recipes.py"
        if not recipe_path.is_file():
            return []
        module = _load_module(recipe_path, "impact_engine_pack_recipes_" + self.manifest.id.replace(".", "_"))
        provider = getattr(module, "semantic_recipes", None)
        return list(provider() or []) if callable(provider) else []

    def hook_for(self, capability: str):
        entrypoints = self.manifest.capabilities.get("hook_entrypoints", {})
        entrypoint = entrypoints.get(capability) if isinstance(entrypoints, dict) else None
        hook_path = self._pack_dir / "hooks.py"
        if not entrypoint or not hook_path.is_file():
            return None
        module = _load_module(hook_path, "impact_engine_pack_hook_" + self.manifest.id.replace(".", "_").replace("-", "_"))
        return getattr(module, str(entrypoint), None)


def create_framework_plugin(manifest: PluginManifest) -> ManifestFrameworkPlugin:
    return ManifestFrameworkPlugin(manifest)
