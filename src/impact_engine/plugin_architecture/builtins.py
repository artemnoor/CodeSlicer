"""Compatibility discovery fallback for manifest-backed plugins.

There is deliberately no language or framework dispatch in this module. The
manifest packages are the architectural path; this function only discovers
them when an embedding application asks for a compatibility fallback.
"""
from __future__ import annotations

import sys
from pathlib import Path

from .registry import PluginRegistry, packaged_plugin_root


def builtin_registry() -> PluginRegistry:
    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    plugin_root = packaged_plugin_root(repo_root)
    registry = PluginRegistry().discover([plugin_root] if plugin_root else [])
    if not registry.manifests:
        registry.diagnostics.append({
            "code": "plugin_packages_unavailable",
            "message": "No manifest-backed plugin packages were found locally",
        })
    return registry
