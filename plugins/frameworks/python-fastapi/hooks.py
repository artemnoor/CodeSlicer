"""FastAPI pack hooks; loaded only after dependency/import activation."""
import ast

from impact_engine.models import Edge, Evidence, Node
from impact_engine.plugin_architecture.contracts import PluginResult


def _depends_provider(default_value: object) -> str | None:
    """Return the explicit provider from a statically readable ``Depends`` call.

    ``ast.unparse`` keeps optional FastAPI arguments such as ``use_cache``.
    Parsing the expression instead of splitting its text prevents
    ``Depends(get_service, use_cache=False)`` from being resolved as a fake
    symbol named ``"get_service, use_cache=False"``.  Dynamic expressions stay
    unresolved deliberately: this hook must not manufacture an edge from a
    name-only guess.
    """
    try:
        expression = ast.parse(str(default_value), mode="eval").body
    except (SyntaxError, TypeError, ValueError):
        return None
    if not isinstance(expression, ast.Call):
        return None
    function_name = expression.func.id if isinstance(expression.func, ast.Name) else expression.func.attr if isinstance(expression.func, ast.Attribute) else None
    if function_name != "Depends":
        return None
    provider = expression.args[0] if expression.args else next(
        (keyword.value for keyword in expression.keywords if keyword.arg == "dependency"),
        None,
    )
    if not isinstance(provider, (ast.Name, ast.Attribute)):
        return None
    return ast.unparse(provider)


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
    from impact_engine.resolution.engine import build_symbol_index, get_node_location, module_for_scope

    index = build_symbol_index(graph)
    existing = {edge.id for edge in graph.edges}
    for node in list(graph.nodes):
        if node.kind != "METHOD":
            continue
        scope = str(node.properties.get("scope") or node.id)
        for key, value in node.properties.items():
            if not str(key).startswith("param_default:"):
                continue
            provider = _depends_provider(value)
            if not provider:
                continue
            current_module = module_for_scope(scope, graph)
            # ``Depends`` receives a callable, not a class.  Use the same
            # exact import-aware function resolver as ordinary Python calls;
            # the former class resolver made an imported provider look local
            # and could create a dangling, misleading edge.
            resolved = index.resolve_function_name(provider, current_module, scope.rsplit(".", 1)[0])
            if not resolved:
                continue
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
