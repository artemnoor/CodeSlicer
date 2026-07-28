"""Language/framework plugin boundary for the language-neutral core."""

from .contracts import (
    PluginContext,
    PluginDiagnostic,
    PluginManifest,
    PluginResult,
    PluginTrust,
)
from .registry import PluginRegistry, discover_plugin_registry
from .selection import PluginSelectionPlan, build_plugin_selection_plan

__all__ = [
    "PluginContext",
    "PluginDiagnostic",
    "PluginManifest",
    "PluginResult",
    "PluginTrust",
    "PluginRegistry",
    "PluginSelectionPlan",
    "build_plugin_selection_plan",
    "discover_plugin_registry",
]
