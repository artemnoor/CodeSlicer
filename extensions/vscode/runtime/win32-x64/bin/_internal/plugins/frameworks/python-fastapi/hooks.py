"""FastAPI pack hooks; loaded only after dependency/import activation."""
import re

from impact_engine.models import Edge, Evidence, Node
from impact_engine.plugin_architecture.contracts import PluginResult


def backend_route_source_composer(context, graph):
    from impact_engine.support_packs.compatibility_bridge import _legacy_apply_backend_route_source_composer

    updated = _legacy_apply_backend_route_source_composer(graph)
    for edge in updated.edges:
        if edge.kind == "ROUTE_HANDLES" and edge.properties.get("resolver") == "backend_route_source_composer":
            edge.properties.update({
                "support_pack_library": "fastapi",
                "support_pack_id": "fastapi",
                "support_pack_rule_id": "fastapi-router-prefix-resolver-rule",
                "resolver_hook_name": "fastapi_router_resolver",
                "plugin_id": "framework.python.fastapi",
                "pack_id": "framework.python.fastapi",
                "rule_id": "fastapi-router-prefix-resolver-rule",
                "provenance": {"plugin_id": "framework.python.fastapi", "rule_id": "fastapi-router-prefix-resolver-rule"},
            })
    route_facts = updated.metadata.get("backend_route_source_composer", {}).get("route_facts", [])
    route_by_endpoint = {
        (f"HTTP {str(route.get('method')).upper()} {str(route.get('path') or '')}", str(route.get("handler") or "")): route
        for route in route_facts
    }
    for edge in updated.edges:
        route = route_by_endpoint.get((edge.from_node, edge.to_node))
        if edge.kind != "ROUTE_HANDLES" or route is None:
            continue
        # Preserve the historical direct-app route contract while keeping
        # router-object composition as an inferred source-level fact.
        if str(route.get("router_id") or "").endswith(".app"):
            edge.source = "SUPPORT_PACK"
            edge.properties["support_pack_rule_id"] = "fastapi-post-route"
            edge.properties["rule_id"] = "fastapi-post-route"
            edge.properties["provenance"] = {"plugin_id": "framework.python.fastapi", "rule_id": "fastapi-post-route"}
    existing_ids = {edge.id for edge in updated.edges}
    for route in route_facts:
        if not route.get("trailing_slash"):
            continue
        path = str(route.get("path") or "")
        if path.endswith("/"):
            continue
        canonical = f"HTTP {str(route.get('method')).upper()} {path}/"
        handler = str(route.get("handler") or "")
        if not handler:
            continue
        if not any(node.id == canonical for node in updated.nodes):
            updated.add_node(Node(id=canonical, kind="ROUTE", name=canonical, properties={"method": route.get("method"), "path": f"{path}/", "handler": handler, "framework": "fastapi", "backend_endpoint": True, "plugin_id": "framework.python.fastapi"}))
        edge_id = f"plugin_fastapi_route_alias__{canonical}__{handler}"
        if edge_id in existing_ids:
            continue
        updated.add_edge(Edge(
            id=edge_id,
            kind="ROUTE_HANDLES",
            from_node=canonical,
            to_node=handler,
            source="INFERRED",
            confidence=0.85,
            evidence=[Evidence(file=route.get("file"), line=route.get("line"), description="FastAPI route preserves decorator trailing slash", source="INFERRED")],
            properties={
                "resolver": "fastapi_pack_hook",
                "status": "confirmed",
                "framework": "fastapi",
                "support_pack_library": "fastapi",
                "support_pack_id": "fastapi",
                "support_pack_rule_id": "fastapi-router-post-route",
                # Keep the public edge-level resolver name stable for the
                # pack-owned route hook.  The nested unified provenance keeps
                # the original decorator rule attribution when this alias
                # merges with the compatibility edge.
                "resolver_hook_name": "fastapi_router_resolver",
                "plugin_id": "framework.python.fastapi",
                "pack_id": "framework.python.fastapi",
                "rule_id": "fastapi-router-post-route",
                "provenance": {"plugin_id": "framework.python.fastapi", "rule_id": "fastapi-router-post-route"},
            },
        ))
        existing_ids.add(edge_id)
    return PluginResult(
        graph=updated,
        provenance={"pack_id": "framework.python.fastapi", "rule_id": "fastapi.router_object_flow"},
    )


def dependency_resolver(context, graph):
    """Resolve Depends defaults without entering the legacy rule dispatcher."""
    from impact_engine.resolution.engine import build_symbol_index, get_node_location, module_for_scope, resolve_class_name

    index = build_symbol_index(graph)
    existing = {edge.id for edge in graph.edges}
    for node in list(graph.nodes):
        if node.kind != "METHOD":
            continue
        scope = str(node.properties.get("scope") or node.id)
        for key, value in node.properties.items():
            if not str(key).startswith("param_default:") or "Depends(" not in str(value):
                continue
            match = re.search(r"Depends\(([^)]+)\)", str(value))
            if not match:
                continue
            provider = match.group(1).strip()
            current_module = module_for_scope(scope, graph)
            resolved = resolve_class_name(provider, current_module, index) or f"{current_module}.{provider}"
            edge_id = f"plugin_fastapi_depends__{scope}__{resolved}"
            if edge_id in existing:
                continue
            file_name = node.properties.get("file")
            line = node.properties.get("line")
            if not file_name:
                file_name, line = get_node_location(node.id, graph)
            graph.add_edge(Edge(
                id=edge_id,
                kind="CALLS",
                from_node=scope,
                to_node=resolved,
                source="INFERRED",
                confidence=0.85,
                evidence=[Evidence(file=file_name, line=line, description=f"FastAPI Depends provider: {scope} -> {resolved}", source="INFERRED")],
                properties={
                    "support_pack_library": "fastapi",
                    "support_pack_id": "fastapi",
                    "support_pack_rule_id": "fastapi-depends-resolver-rule",
                    "resolver_hook_name": "fastapi_depends_resolver",
                    "plugin_id": "framework.python.fastapi",
                    "pack_id": "framework.python.fastapi",
                    "rule_id": "fastapi-depends-resolver-rule",
                    "provenance": {"plugin_id": "framework.python.fastapi", "rule_id": "fastapi-depends-resolver-rule"},
                },
            ))
            existing.add(edge_id)
    return PluginResult(
        graph=graph,
        provenance={"pack_id": "framework.python.fastapi", "rule_id": "fastapi-depends-resolver-rule"},
    )
