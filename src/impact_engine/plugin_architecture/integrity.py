"""Plugin graph integrity gate with explicit diagnostics."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from impact_engine.models import GraphDocument, Node
from .selection import PluginSelectionPlan


def plugin_graph_integrity_gate(graph: GraphDocument, plugin_id: str) -> GraphDocument:
    node_ids = {node.id for node in graph.nodes}
    before = {
        "edge_count": len(graph.edges),
        "dangling": sum(
            1 for edge in graph.edges
            if edge.from_node not in node_ids or edge.to_node not in node_ids
        ),
    }
    # Materialize unresolved endpoints without rewriting existing ids. The
    # gate can run between extraction and resolution; a full canonicalizing
    # normalization there would discard import evidence needed by later
    # resolvers. Explicit suppressed nodes preserve the edge and its
    # diagnostic provenance while keeping the persisted document closed.
    normalized = graph
    missing_endpoints = {
        endpoint
        for edge in normalized.edges
        for endpoint in (edge.from_node, edge.to_node)
        if endpoint not in node_ids
    }
    for endpoint in sorted(missing_endpoints):
        normalized.add_node(Node(
            id=endpoint,
            kind="EXTERNAL_LIBRARY",
            name=endpoint,
            properties={
                "unresolved": True,
                "suppressed": True,
                "provenance": {
                    "plugin_id": plugin_id,
                    "rule_id": "graph.integrity.unresolved_endpoint",
                    "reason": "endpoint was absent after plugin phase",
                },
            },
        ))
    node_ids = {node.id for node in normalized.nodes}
    missing = [edge for edge in normalized.edges if edge.from_node not in node_ids or edge.to_node not in node_ids]
    diagnostics = normalized.metadata.setdefault("plugin_graph_integrity", [])
    dangling_after = sum(
        1 for edge in normalized.edges
        if edge.from_node not in node_ids or edge.to_node not in node_ids
    )
    diagnostics.append({
        "plugin_id": plugin_id,
        "before_dangling_edges": before["dangling"],
        "materialized_edges": max(0, before["dangling"] - len(missing)),
        "rejected_edges": [{"id": edge.id, "kind": edge.kind, "from": edge.from_node, "to": edge.to_node} for edge in missing],
        "dangling_edges_after": dangling_after,
    })
    return normalized


def annotate_plugin_provenance(graph: GraphDocument, plan: PluginSelectionPlan) -> GraphDocument:
    """Attach stable plugin/pack provenance to facts emitted by plugins."""
    selected_frameworks = {
        plugin_id: plan.registry.manifests[plugin_id]
        for plugin_id in plan.selected_framework_ids
        if plan.registry and plugin_id in plan.registry.manifests
    }
    selected_languages = {
        plugin_id: plan.registry.manifests[plugin_id]
        for plugin_id in plan.selected_language_ids
        if plan.registry and plugin_id in plan.registry.manifests
    }
    node_by_id = {node.id: node for node in graph.nodes}

    def language_plugin_for_edge(edge: Any) -> str | None:
        """Resolve extractor provenance from concrete source locations only.

        A polyglot graph can contain several selected language plugins.  Using
        their iteration order would silently mislabel facts from every language
        after the first one.  Evidence locations and endpoint file metadata are
        stable, local facts, so an unambiguous extension match is safe.  Unknown
        extensions deliberately remain unannotated rather than guessed.
        """
        files: set[str] = set()
        for evidence in getattr(edge, "evidence", []) or []:
            file_name = getattr(evidence, "file", None)
            if file_name:
                files.add(str(file_name))
        for endpoint in (edge.from_node, edge.to_node):
            node = node_by_id.get(endpoint)
            if node is None:
                continue
            file_name = (node.properties or {}).get("file") or (node.properties or {}).get("path")
            if file_name:
                files.add(str(file_name))
        candidates = {
            plugin_id
            for file_name in files
            for plugin_id, manifest in selected_languages.items()
            if Path(file_name).suffix.lower() in {str(item).lower() for item in manifest.file_extensions}
        }
        return next(iter(candidates)) if len(candidates) == 1 else None
    for edge in graph.edges:
        props = edge.properties
        library = str(props.get("support_pack_library") or props.get("support_pack_id") or "").lower()
        if library and not props.get("plugin_id"):
            normalized_library = library.replace("_", "-").replace(" ", "-")
            candidates = []
            for plugin_id, manifest in selected_frameworks.items():
                plugin_name = plugin_id.rsplit(".", 1)[-1].lower().replace("_", "-")
                activation_values = {
                    str(value).lower().replace("_", "-")
                    for key in ("dependencies", "imports")
                    for value in (manifest.activation.get(key, []) or [])
                }
                if normalized_library == plugin_name or normalized_library in activation_values or any(
                    normalized_library == item.split("/", 1)[-1] for item in activation_values
                ):
                    candidates.append(plugin_id)
            if len(candidates) == 1:
                props.setdefault("plugin_id", candidates[0])
                props.setdefault("pack_id", candidates[0])
        if props.get("plugin_id") is None and props.get("framework"):
            framework_name = str(props.get("framework")).lower()
            for plugin_id, manifest in selected_frameworks.items():
                if plugin_id.rsplit(".", 1)[-1].lower() == framework_name:
                    props.setdefault("plugin_id", plugin_id)
                    props.setdefault("pack_id", plugin_id)
                    break
                if manifest.id.rsplit(".", 1)[-1].lower() == framework_name:
                    props.setdefault("plugin_id", plugin_id)
                    props.setdefault("pack_id", plugin_id)
                    break
        if props.get("plugin_id") is None and edge.source == "EXTRACTED":
            language_plugin = language_plugin_for_edge(edge)
            if language_plugin:
                props.setdefault("plugin_id", language_plugin)
        if props.get("support_pack_rule_id") and props.get("plugin_id"):
            props.setdefault("rule_id", props.get("support_pack_rule_id"))
        if props.get("plugin_id"):
            manifest = selected_frameworks.get(props["plugin_id"]) or (
                plan.registry.manifests.get(props["plugin_id"]) if plan.registry else None
            )
            if manifest:
                props.setdefault("plugin_version", manifest.version)
                props.setdefault("plugin_cache_key", manifest.cache_key)
                props.setdefault(
                    "plugin_trust_level",
                    manifest.capabilities.get("trust_level")
                    or manifest.confidence_policy.get("trust_level")
                    or props.get("support_pack_trust_level")
                    or "experimental",
                )
            props.setdefault("rule_id", props.get("resolver_hook_name") or f"{props['plugin_id']}:{edge.kind}")
            provenance = props.setdefault("provenance", {})
            provenance.setdefault("plugin_id", props["plugin_id"])
            provenance.setdefault("pack_id", props.get("pack_id"))
            provenance.setdefault("rule_id", props.get("rule_id"))
            if manifest:
                provenance.setdefault("plugin_version", manifest.version)
                provenance.setdefault("cache_key", manifest.cache_key)
                provenance.setdefault("trust_level", props.get("plugin_trust_level"))
    return graph
