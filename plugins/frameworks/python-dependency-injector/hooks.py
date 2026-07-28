"""Project-local dependency-injector semantics owned by this pack."""
from impact_engine.models import Edge, Evidence
from impact_engine.plugin_architecture.contracts import PluginResult


def dependency_resolver(context, graph):
    from impact_engine.resolution.engine import build_symbol_index, get_node_location, module_for_scope, resolve_class_name

    index = build_symbol_index(graph)
    existing = {edge.id for edge in graph.edges}
    for node in list(graph.nodes):
        if node.kind == "ASSIGNMENT":
            call_name = str(node.properties.get("call_name") or "")
            if call_name not in {"providers.Singleton", "providers.Factory"}:
                continue
            args = node.properties.get("args", []) or []
            if not args:
                continue
            scope = str(node.properties.get("scope") or "")
            target = str(node.properties.get("target") or "")
            current_module = module_for_scope(scope, graph)
            provided = resolve_class_name(str(args[0]), current_module, index) or str(args[0])
            container_attr = f"{scope}.{target}" if scope else target
            file_name = node.properties.get("file")
            line = node.properties.get("line")
            if not file_name:
                file_name, line = get_node_location(node.id, graph)

            def add_edge(edge_id, kind, source, target_node, confidence, description):
                if edge_id in existing:
                    return
                graph.add_edge(Edge(
                    id=edge_id,
                    kind=kind,
                    from_node=source,
                    to_node=target_node,
                    source="INFERRED",
                    confidence=confidence,
                    evidence=[Evidence(file=file_name, line=line, description=description, source="INFERRED")],
                    properties={
                        "support_pack_library": "dependency_injector",
                        "support_pack_id": "dependency_injector",
                        "support_pack_rule_id": "dependency-injector-resolver-rule",
                        "resolver_hook_name": "dependency_injector_resolver",
                        "plugin_id": "framework.python.dependency-injector",
                        "pack_id": "framework.python.dependency-injector",
                        "rule_id": "dependency-injector-resolver-rule",
                        "provenance": {"plugin_id": "framework.python.dependency-injector", "rule_id": "dependency-injector-resolver-rule"},
                    },
                ))
                existing.add(edge_id)

            add_edge(
                f"support_pack_edge__dependency_injector__di_binding__{container_attr}__{provided}",
                "DEPENDS_ON", container_attr, provided, 0.85,
                f"dependency-injector provider binding: {container_attr} -> {provided}",
            )
            for _key, value in dict(node.properties.get("keyword_args", {}) or {}).items():
                dependency = next((candidate for candidate in graph.nodes if candidate.kind == "ASSIGNMENT" and candidate.properties.get("scope") == scope and candidate.properties.get("target") == value), None)
                if dependency is None:
                    continue
                dep_args = dependency.properties.get("args", []) or []
                if dependency.properties.get("call_name") not in {"providers.Singleton", "providers.Factory"} or not dep_args:
                    continue
                dep_class = resolve_class_name(str(dep_args[0]), current_module, index) or str(dep_args[0])
                add_edge(
                    f"support_pack_edge__dependency_injector__di_dep__{provided}__{dep_class}",
                    "DEPENDS_ON", provided, dep_class, 0.80,
                    f"dependency-injector constructor dependency: {provided} -> {dep_class}",
                )
        elif node.kind == "CALL_EXPR":
            call_name = str(node.properties.get("call_name") or "")
            scope = str(node.properties.get("scope") or "")
            if "." not in call_name:
                continue
            method_name = call_name.rsplit(".", 1)[-1]
            for provider in graph.nodes:
                if provider.kind != "ASSIGNMENT" or provider.properties.get("target") != method_name:
                    continue
                args = provider.properties.get("args", []) or []
                if provider.properties.get("call_name") not in {"providers.Singleton", "providers.Factory"} or not args:
                    continue
                target_class = resolve_class_name(str(args[0]), module_for_scope(provider.properties.get("scope", ""), graph), index) or str(args[0])
                file_name = node.properties.get("file")
                line = node.properties.get("line")
                if not file_name:
                    file_name, line = get_node_location(node.id, graph)
                edge_id = f"support_pack_edge__dependency_injector__di_call__{scope}__{target_class}"
                if edge_id in existing:
                    continue
                graph.add_edge(Edge(
                    id=edge_id,
                    kind="CALLS",
                    from_node=scope,
                    to_node=target_class,
                    source="INFERRED",
                    confidence=0.85,
                    evidence=[Evidence(file=file_name, line=line, description=f"dependency-injector provider invocation: {call_name} -> {target_class}", source="INFERRED")],
                    properties={
                        "support_pack_library": "dependency_injector",
                        "support_pack_id": "dependency_injector",
                        "support_pack_rule_id": "dependency-injector-resolver-rule",
                        "resolver_hook_name": "dependency_injector_resolver",
                        "plugin_id": "framework.python.dependency-injector",
                        "pack_id": "framework.python.dependency-injector",
                        "rule_id": "dependency-injector-resolver-rule",
                        "provenance": {"plugin_id": "framework.python.dependency-injector", "rule_id": "dependency-injector-resolver-rule"},
                    },
                ))
                existing.add(edge_id)
    return PluginResult(graph=graph, provenance={"pack_id": "framework.python.dependency-injector", "rule_id": "dependency-injector-resolver-rule"})
