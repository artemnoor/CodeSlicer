"""Deterministic execution helpers for selected plugins."""
from __future__ import annotations

from typing import Any, Sequence
from .contracts import PluginContext, PluginDiagnostic, PluginResult
from .sandbox import PluginSandboxViolation, execute_in_process
from .selection import PluginSelectionPlan


def _integrity_gate(graph: Any, plugin_id: str) -> Any:
    """Run the shared graph gate immediately after a plugin contribution."""
    from .integrity import plugin_graph_integrity_gate

    return plugin_graph_integrity_gate(graph, plugin_id)


def extract_selected_languages(
    plan: PluginSelectionPlan,
    context: PluginContext,
    files: Sequence[str] | None = None,
    selected_ids: Sequence[str] | None = None,
) -> tuple[list[Any], list[str], list[PluginDiagnostic]]:
    graphs: list[Any] = []
    extractors: list[str] = []
    diagnostics: list[PluginDiagnostic] = []
    allowed = set(selected_ids) if selected_ids is not None else set(plan.selected_language_ids)
    for plugin_id in plan.selected_language_ids:
        if plugin_id not in allowed:
            continue
        plugin = plan.registry.get(plugin_id) if plan.registry else None
        if plugin is None:
            diagnostics.append(PluginDiagnostic(plugin_id, "error", "plugin_missing", "Selected plugin implementation is unavailable"))
            continue
        try:
            context.check_cancelled()
            result: PluginResult = plugin.extract(context, files=files)
            if result.graph is not None:
                graphs.append(_integrity_gate(result.graph, plugin_id))
            extractor_id = result.provenance.get("extractor_id")
            if extractor_id:
                extractors.append(str(extractor_id))
            if result.graph is not None and result.graph.metadata.get("tree_sitter_status"):
                # Preserve the public legacy extractor label while the
                # manifest-owned plugin id remains available in provenance.
                if "tree_sitter" not in extractors:
                    extractors.append("tree_sitter")
            diagnostics.extend(result.diagnostics)
        except Exception as exc:
            # A cancellation raised inside a long-running extractor must never
            # be downgraded to a plugin diagnostic. Let the pipeline/local API
            # transition to its explicit `cancelled` state instead.
            if context.cancellation is not None and getattr(context.cancellation, "is_set", lambda: False)():
                check = getattr(context.cancellation, "check", None)
                if callable(check):
                    check()
                raise
            diagnostics.append(PluginDiagnostic(plugin_id, "error", getattr(exc, "code", "plugin_execution_error"), str(exc)))
    return graphs, extractors, diagnostics


def selected_compatibility_packs(plan: PluginSelectionPlan) -> list[Any]:
    packs: list[Any] = []
    for plugin_id in plan.selected_framework_ids:
        plugin = plan.registry.get(plugin_id) if plan.registry else None
        loader = getattr(plugin, "load_compatibility_pack", None)
        if not loader:
            continue
        try:
            pack = loader()
            if pack is not None:
                packs.append(pack)
        except Exception as exc:
            plan.diagnostics.append(PluginDiagnostic(plugin_id, "warning", "compat_pack_load_error", str(exc)))
    return packs


def selected_semantic_recipes(plan: PluginSelectionPlan) -> list[Any]:
    recipes: list[Any] = []
    for plugin_id in plan.selected_framework_ids:
        plugin = plan.registry.get(plugin_id) if plan.registry else None
        provider = getattr(plugin, "semantic_recipes", None)
        if provider:
            recipes.extend(provider())
    return recipes


def resolve_selected_languages(plan: PluginSelectionPlan, context: PluginContext, graph: Any, *, selected_ids: Sequence[str] | None = None) -> tuple[Any, list[PluginDiagnostic]]:
    diagnostics: list[PluginDiagnostic] = []
    current = graph
    allowed = set(selected_ids) if selected_ids is not None else set(plan.selected_language_ids)
    for plugin_id in plan.selected_language_ids:
        if plugin_id not in allowed:
            continue
        plugin = plan.registry.get(plugin_id) if plan.registry else None
        if plugin is None:
            continue
        try:
            result = plugin.resolve(context, current)
            current = result.graph or current
            current = _integrity_gate(current, plugin_id)
            diagnostics.extend(result.diagnostics)
        except Exception as exc:
            diagnostics.append(PluginDiagnostic(plugin_id, "warning", getattr(exc, "code", "plugin_resolve_error"), str(exc)))
    return current, diagnostics


def execute_selected_framework_hooks(
    plan: PluginSelectionPlan,
    context: PluginContext,
    graph: Any,
    *,
    phase: str = "pre_resolution",
) -> tuple[Any, list[PluginDiagnostic]]:
    """Run only hooks declared by selected packs, behind the common boundary."""
    current = graph
    diagnostics: list[PluginDiagnostic] = []
    execution_meta = current.metadata.setdefault("plugin_hook_execution", [])
    current.metadata["plugin_hook_execution_phase"] = phase
    tasks: list[tuple[str, Any, Any, str, tuple[str, ...]]] = []
    provided = set()
    for plugin_id in plan.selected_framework_ids:
        plugin = plan.registry.get(plugin_id) if plan.registry else None
        manifest = plan.registry.manifests.get(plugin_id) if plan.registry else None
        if plugin is None or manifest is None:
            continue
        entrypoints = manifest.capabilities.get("hook_entrypoints", {})
        if not isinstance(entrypoints, dict):
            continue
        handled_rule_types = manifest.capabilities.get("handled_rule_types", [])
        if handled_rule_types:
            current.metadata.setdefault("plugin_handled_rule_types", [])
            current.metadata["plugin_handled_rule_types"] = sorted(
                set(current.metadata["plugin_handled_rule_types"]) | {str(item) for item in handled_rule_types}
            )
        handled_rule_ids = manifest.capabilities.get("handled_rule_ids", [])
        if handled_rule_ids:
            current.metadata.setdefault("plugin_handled_rule_ids", [])
            current.metadata["plugin_handled_rule_ids"] = sorted(
                set(current.metadata["plugin_handled_rule_ids"]) | {str(item) for item in handled_rule_ids}
            )
        for capability in sorted(entrypoints):
            hook_phases = manifest.capabilities.get("hook_phases", {}) or {}
            if str(hook_phases.get(capability, "pre_resolution")) != phase:
                continue
            hook = getattr(plugin, "hook_for", lambda _name: None)(capability)
            if hook is None:
                diagnostics.append(PluginDiagnostic(plugin_id, "warning", "hook_missing", f"No local hook implementation for {capability}"))
                continue
            requirements = manifest.capabilities.get("requires_capabilities", {}) or {}
            tasks.append((plugin_id, plugin, hook, capability, tuple(str(item) for item in requirements.get(capability, []) or [])))
    while tasks:
        runnable = next((item for item in tasks if set(item[4]).issubset(provided)), tasks[0])
        tasks.remove(runnable)
        plugin_id, _plugin, hook, capability, requirements = runnable
        if not set(requirements).issubset(provided):
            diagnostics.append(PluginDiagnostic(plugin_id, "info", "hook_dependency_unmet", f"Executing {capability} without all optional capability prerequisites", {"requires": list(requirements)}))
        try:
            result = execute_plugin_hook(hook, context, current)
            current = result.graph or current
            current = _integrity_gate(current, plugin_id)
            diagnostics.extend(result.diagnostics)
            execution_meta = current.metadata.setdefault("plugin_hook_execution", [])
            execution_meta.append({"plugin_id": plugin_id, "capability": capability, "status": "applied", "provenance": dict(result.provenance)})
            provided.add(capability)
        except Exception as exc:
            diagnostics.append(PluginDiagnostic(plugin_id, "warning", getattr(exc, "code", "hook_execution_error"), str(exc), {"capability": capability}))
            execution_meta = current.metadata.setdefault("plugin_hook_execution", [])
            execution_meta.append({"plugin_id": plugin_id, "capability": capability, "status": "error", "error": str(exc)})
    if phase == "pre_resolution" and "backend_route_source_composer" not in current.metadata:
        has_route_composer = any(
            "backend_route_source_composer" in (plan.registry.manifests[plugin_id].capabilities.get("hook_entrypoints", {}) or {})
            for plugin_id in plan.selected_framework_ids
            if plan.registry and plugin_id in plan.registry.manifests
        )
        if not has_route_composer:
            current.metadata["backend_route_source_composer"] = {
                "status": "skipped",
                "routes": 0,
                "reason": "no selected framework plugin owns this capability",
            }
    return current, diagnostics


def execute_plugin_hook(hook, context: PluginContext, graph: Any, *, timeout_seconds: float | None = None) -> PluginResult:
    """Run a pack hook in a killable local process with a hard timeout."""
    timeout = float(timeout_seconds or context.timeout_seconds)
    context.check_cancelled()
    try:
        return execute_in_process(hook, context, graph, timeout_seconds=timeout)
    except PluginSandboxViolation:
        raise
