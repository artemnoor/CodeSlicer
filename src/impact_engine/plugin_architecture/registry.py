"""Manifest discovery and implementation registry."""
from __future__ import annotations

import json
from importlib.util import find_spec
import sys
from pathlib import Path
from typing import Any, Iterable

from .contracts import Plugin, PluginManifest, load_entrypoint


def packaged_plugin_root(repo_root: Path) -> Path | None:
    """Return the manifest directory for a checkout or an installed wheel.

    In development, manifests live at ``<repo>/plugins``.  A wheel installs
    the same directory as the top-level ``plugins`` Python package, so using
    a path relative to ``impact_engine.__file__`` would otherwise point at the
    virtual environment's ``Lib`` folder instead of the installed assets.
    """
    checkout_root = repo_root / "plugins"
    if checkout_root.is_dir():
        return checkout_root
    specification = find_spec("plugins")
    locations = specification.submodule_search_locations if specification else None
    if locations:
        return Path(next(iter(locations)))
    return None


class PluginRegistry:
    def __init__(self) -> None:
        self.manifests: dict[str, PluginManifest] = {}
        self.implementations: dict[str, Plugin] = {}
        self.diagnostics: list[dict[str, Any]] = []

    def register(self, manifest: PluginManifest, implementation: Plugin | None = None) -> None:
        errors = manifest.validate()
        if errors:
            self.diagnostics.append({"plugin_id": manifest.id, "code": "invalid_manifest", "errors": errors})
            return
        self.manifests[manifest.id] = manifest
        if implementation is not None:
            self.implementations[manifest.id] = implementation

    def discover(self, roots: Iterable[str | Path]) -> "PluginRegistry":
        for root_value in roots:
            root = Path(root_value)
            if not root.exists():
                continue
            for path in sorted(root.rglob("plugin.json")) + sorted(root.rglob("pack.json")):
                # Adapter manifests have a separate SDK/contract and must not
                # be interpreted as language/framework plugins.
                if path.parent.parent.name == "adapters":
                    continue
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    manifest = PluginManifest.from_dict(data, path=str(path))
                    errors = manifest.validate()
                    if errors:
                        self.diagnostics.append({"plugin_id": manifest.id, "code": "invalid_manifest", "errors": errors, "path": str(path)})
                        continue
                    implementation = load_entrypoint(manifest.entrypoint)(manifest)
                    self.register(manifest, implementation)
                except Exception as exc:
                    self.diagnostics.append({"path": str(path), "code": "plugin_discovery_error", "error": str(exc)})
        return self

    def get(self, plugin_id: str) -> Plugin | None:
        return self.implementations.get(plugin_id)

    def language_plugins(self) -> list[Plugin]:
        result = []
        for key, manifest in self.manifests.items():
            if manifest.kind == "language" and key in self.implementations:
                self.implementations[key].manifest = manifest
                result.append(self.implementations[key])
        return result

    def framework_plugins(self) -> list[Plugin]:
        result = []
        for key, manifest in self.manifests.items():
            if manifest.kind == "framework" and key in self.implementations:
                self.implementations[key].manifest = manifest
                result.append(self.implementations[key])
        return result


def discover_plugin_registry(project_path: str | Path | None = None, plugin_root: str | Path | None = None) -> PluginRegistry:
    repo_root = Path(__file__).resolve().parents[3]
    # Manifest entrypoints are repository-owned packages.  CLI callers are
    # commonly launched from a temporary working directory, so make the
    # repository root importable without requiring callers to mutate
    # PYTHONPATH beyond the documented ``src`` entry.
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    root = Path(plugin_root) if plugin_root else packaged_plugin_root(repo_root)
    roots = [root] if root else []
    registry = PluginRegistry().discover(roots)
    if not registry.manifests:
        from .builtins import builtin_registry
        registry = builtin_registry()
    return registry
