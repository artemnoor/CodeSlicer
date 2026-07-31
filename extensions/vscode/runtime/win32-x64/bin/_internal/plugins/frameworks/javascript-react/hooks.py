"""React pack hooks; loaded only after dependency/import activation."""
from impact_engine.models import Edge, Evidence
from impact_engine.plugin_architecture.contracts import PluginResult


def endpoint_bridge(context, graph):
    """Run endpoint matching only in the selected React pack phase."""
    from impact_engine.support_packs.compatibility_bridge import apply_frontend_backend_endpoint_bridge

    return PluginResult(
        graph=apply_frontend_backend_endpoint_bridge(graph),
        provenance={"pack_id": "framework.javascript.react", "rule_id": "react.endpoint_bridge"},
    )


def frontend_source_facts(context, graph):
    from impact_engine.support_packs.compatibility_bridge import _legacy_collect_frontend_source_facts

    facts = _legacy_collect_frontend_source_facts(graph)
    if facts:
        graph.metadata["frontend_backend_endpoint_facts"] = facts
    return PluginResult(
        graph=graph,
        provenance={"pack_id": "framework.javascript.react", "rule_id": "react.source_endpoint_facts"},
    )


def semantic_relations(context, graph):
    """Emit React component/hook relations with pack-owned provenance."""
    existing = {edge.id for edge in graph.edges}
    nodes_by_id = {node.id: node for node in graph.nodes}
    method_ids = {
        node.id for node in graph.nodes
        if node.kind == "METHOD" and (node.name[:1].isupper() or node.name.startswith("use"))
    }
    for node in graph.nodes:
        if node.kind != "CALL_EXPR" or not str(node.properties.get("file", "")).lower().endswith((".js", ".jsx", ".ts", ".tsx")):
            continue
        call_name = str(node.properties.get("call_name") or node.name or "")
        scope = str(node.properties.get("scope") or "")
        if not scope:
            continue
        rule_id = "react-component-hook-resolver"
        target = None
        if call_name.startswith("use") and len(call_name) > 3 and call_name[3].isupper():
            target = call_name
        elif scope in method_ids and call_name not in {"fetch", "JSON.stringify", "console.log", "console"}:
            target = node.id
        elif call_name == "fetch" and node.properties.get("args"):
            path = str(node.properties["args"][0]).strip("'\"")
            method = "GET"
            options = " ".join(str(item) for item in node.properties.get("args", [])[1:])
            if "POST" in options.upper():
                method = "POST"
            candidate = f"HTTP {method} {path}"
            if candidate in nodes_by_id:
                target = candidate
        if not target:
            continue
        updated_existing = False
        for existing_edge in graph.edges:
            if existing_edge.kind == "CALLS" and existing_edge.from_node == scope and existing_edge.to_node == target:
                existing_edge.confidence = min(float(existing_edge.confidence), 0.60)
                existing_edge.properties.update({
                    "support_pack_library": "react",
                    "support_pack_id": "react",
                    "support_pack_rule_id": rule_id,
                    "resolver_hook_name": "react_resolver",
                    "plugin_id": "framework.javascript.react",
                    "pack_id": "framework.javascript.react",
                    "rule_id": rule_id,
                    "provenance": {"plugin_id": "framework.javascript.react", "rule_id": rule_id},
                })
                existing.add(existing_edge.id)
                updated_existing = True
                break
        if updated_existing:
            continue
        edge_id = f"plugin_react_relation__{scope}__{target}"
        if edge_id in existing:
            continue
        graph.add_edge(Edge(
            id=edge_id,
            kind="CALLS",
            from_node=scope,
            to_node=target,
            source="SUPPORT_PACK",
            confidence=0.65 if target.startswith("HTTP ") else 0.60,
            evidence=[Evidence(file=node.properties.get("file"), line=node.properties.get("line"), description=f"React relation: {scope} -> {call_name}", source="INFERRED")],
            properties={
                "support_pack_library": "react",
                "support_pack_id": "react",
                "support_pack_rule_id": rule_id,
                "resolver_hook_name": "react_resolver",
                "plugin_id": "framework.javascript.react",
                "pack_id": "framework.javascript.react",
                "rule_id": rule_id,
                "provenance": {"plugin_id": "framework.javascript.react", "rule_id": rule_id},
            },
        ))
        existing.add(edge_id)
    return PluginResult(
        graph=graph,
        provenance={"pack_id": "framework.javascript.react", "rule_id": "react-component-hook-resolver"},
    )
