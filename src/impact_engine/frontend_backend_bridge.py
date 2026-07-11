"""Adapter for deterministic frontend-to-backend endpoint resolution."""
from __future__ import annotations

import re
import ast
from copy import deepcopy
from pathlib import Path
from typing import Any

from frontend_backend_endpoint_resolver import resolve_frontend_backend_endpoints

from impact_engine.models import Edge, Evidence, GraphDocument, Node


_HTTP_ROUTE_RE = re.compile(r"^HTTP\s+(?P<method>[A-Z]+)\s+(?P<path>/.*)$")
_ALLOWED_EDGE_KINDS = {"HTTP_CALLS", "MATCHES_ENDPOINT", "DEPENDS_ON"}
_ACTIVE_STATUSES = {"confirmed", "likely", "weak"}
_JS_TS_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx"}
_SKIP_DIRS = {".git", ".venv", "venv", "env", "__pycache__", "node_modules", "dist", "build", ".next"}


def build_frontend_backend_endpoint_input(graph: GraphDocument) -> dict[str, Any]:
    """Build endpoint resolver facts from graph metadata plus route nodes.

    The rich frontend facts are intentionally supplied by extractor/adapter
    metadata. This adapter does not invent JavaScript expression facts from weak
    call edges. Backend routes can be supplied explicitly or inferred from
    schema-valid route nodes and route-handler edges.
    """

    raw = graph.metadata.get("frontend_backend_endpoint_facts") or graph.metadata.get("endpoint_resolver_facts") or {}
    facts: dict[str, Any] = deepcopy(raw) if isinstance(raw, dict) else {}
    facts.setdefault("modules", [])
    facts.setdefault("frontend_functions", [])
    facts.setdefault("components", [])
    facts.setdefault("hooks", [])
    facts.setdefault("wrapper_recipes", [])

    if not facts.get("modules") and not facts.get("frontend_functions"):
        source_facts = _collect_frontend_source_facts(graph)
        for key, value in source_facts.items():
            if value:
                facts[key] = value

    explicit_routes = facts.get("backend_routes")
    if not isinstance(explicit_routes, list):
        facts["backend_routes"] = _collect_backend_routes_from_graph(graph)
    elif not explicit_routes:
        facts["backend_routes"] = _collect_backend_routes_from_graph(graph)
    source_backend_routes = _collect_fastapi_backend_routes_from_source(graph)
    if source_backend_routes:
        existing = {
            (str(route.get("method")).upper(), str(route.get("path")), str(route.get("handler")))
            for route in facts.get("backend_routes", [])
        }
        for route in source_backend_routes:
            key = (str(route.get("method")).upper(), str(route.get("path")), str(route.get("handler")))
            if key not in existing:
                facts["backend_routes"].append(route)
                existing.add(key)

    return facts


def _collect_frontend_source_facts(graph: GraphDocument) -> dict[str, Any]:
    root_value = graph.metadata.get("project_path") or graph.metadata.get("path")
    if not root_value:
        return {}
    root = Path(str(root_value))
    if not root.exists():
        return {}

    modules: list[dict[str, Any]] = []
    frontend_functions: list[dict[str, Any]] = []
    components: list[dict[str, Any]] = []
    hooks: list[dict[str, Any]] = []
    tests: list[dict[str, Any]] = []
    for path in _iter_frontend_files(root):
        module = _module_id_for_path(root, path)
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        module_fact = {
            "id": module,
            "path": path.relative_to(root).as_posix(),
            "imports": _parse_imports(text, module),
            "constants": _parse_constants(text, module),
            "functions": [],
        }
        import_map = {item["local"]: item["target"] for item in module_fact["imports"] if item.get("local") and item.get("target")}
        for function in _parse_functions(text, module):
            module_fact["functions"].append(function)
            if function.get("calls"):
                frontend_functions.append(function)
            _classify_frontend_function(function, module, import_map, path, components, hooks, tests)
        _append_file_level_frontend_test_fact(path, module, import_map, text, tests)
        modules.append(module_fact)

    if not modules:
        return {}
    _resolve_frontend_relation_targets(modules, components, hooks, tests)
    return {
        "modules": modules,
        "frontend_functions": frontend_functions,
        "components": components,
        "hooks": hooks,
        "tests": tests,
        "wrapper_recipes": [
            {"wrapper_name": "transport", "method": "GET", "url_arg_index": 0, "confidence": 0.82},
            {"wrapper_name": "globalThis.fetch", "method": "GET", "url_arg_index": 0, "confidence": 0.82},
            {"wrapper_name": "apiFetch", "url_arg_index": 0, "options_arg_index": 1, "default_method": "GET", "confidence": 0.84},
            {"wrapper_name": "apiClient.get", "method": "GET", "url_arg_index": 0, "confidence": 0.86},
            {"wrapper_name": "apiClient.post", "method": "POST", "url_arg_index": 0, "confidence": 0.87},
            {"wrapper_name": "apiClient.put", "method": "PUT", "url_arg_index": 0, "confidence": 0.87},
            {"wrapper_name": "apiClient.patch", "method": "PATCH", "url_arg_index": 0, "confidence": 0.87},
            {"wrapper_name": "apiClient.delete", "method": "DELETE", "url_arg_index": 0, "confidence": 0.87},
        ],
    }


def _resolve_frontend_relation_targets(
    modules: list[dict[str, Any]],
    components: list[dict[str, Any]],
    hooks: list[dict[str, Any]],
    tests: list[dict[str, Any]],
) -> None:
    import_maps = {
        str(module.get("id")): {item["local"]: item["target"] for item in module.get("imports", []) or [] if item.get("local") and item.get("target")}
        for module in modules
    }

    def resolve(target: str) -> str:
        module, _, name = target.rpartition(".")
        next_target = import_maps.get(module, {}).get(name)
        if not next_target:
            next_target = import_maps.get(f"{module}.index", {}).get(name)
        return next_target or target

    for component in components:
        component["uses_hooks"] = [resolve(str(target)) for target in component.get("uses_hooks", []) or []]
    for hook in hooks:
        exposes = hook.get("exposes")
        if isinstance(exposes, dict):
            hook["exposes"] = {name: resolve(str(target)) for name, target in exposes.items()}
    for test in tests:
        test["targets"] = sorted({resolve(str(target)) for target in test.get("targets", []) or []})


def apply_frontend_backend_endpoint_bridge(graph: GraphDocument) -> GraphDocument:
    """Run FE->HTTP->BE endpoint matching and merge schema-valid edges."""

    graph = apply_backend_route_source_composer(graph)
    input_data = build_frontend_backend_endpoint_input(graph)
    has_frontend = bool(input_data.get("modules") or input_data.get("frontend_functions"))
    has_backend = bool(input_data.get("backend_routes"))
    if not has_frontend or not has_backend:
        graph.metadata["frontend_backend_endpoint_bridge"] = {
            "status": "skipped",
            "reason": "requires frontend endpoint facts and backend route facts",
            "frontend_fact_count": len(input_data.get("frontend_functions", []) or []),
            "backend_route_count": len(input_data.get("backend_routes", []) or []),
        }
        return graph

    result = resolve_frontend_backend_endpoints(input_data)
    if result.get("status") != "ok":
        graph.metadata["frontend_backend_endpoint_bridge"] = {
            "status": "error",
            "errors": result.get("errors", []),
        }
        return graph

    _add_endpoint_nodes(graph, result)
    added_edges = 0
    for edge_data in result.get("edges", []):
        if _add_endpoint_edge(graph, edge_data):
            added_edges += 1
    added_edges += _add_frontend_relation_edges(graph, input_data)

    graph.metadata["frontend_backend_endpoint_bridge"] = {
        "status": "applied",
        "frontend_http_nodes": len(result.get("frontend_http_nodes", []) or []),
        "backend_route_nodes": len(result.get("backend_route_nodes", []) or []),
        "edges_added": added_edges,
        "confirmed": len(result.get("confirmed", []) or []),
        "likely": len(result.get("likely", []) or []),
        "weak": len(result.get("weak", []) or []),
        "suspicious": len(result.get("suspicious", []) or []),
        "rejected": len(result.get("rejected", []) or []),
        "diagnostics": result.get("diagnostics", []),
        "unresolved": result.get("unresolved", []),
    }
    return graph


def apply_backend_route_source_composer(graph: GraphDocument) -> GraphDocument:
    """Compose backend routes from source-level router object identity.

    This is intentionally independent from the frontend bridge. Backend-only
    projects still need module-qualified FastAPI route composition, and weak
    support-pack route guesses must not survive when source identity disagrees.
    """

    routes = _collect_fastapi_backend_routes_from_source(graph)
    if not routes:
        graph.metadata.setdefault("backend_route_source_composer", {"status": "skipped", "routes": 0})
        return graph

    route_keys = {(str(route["method"]).upper(), str(route["path"]), str(route["handler"])) for route in routes}
    added_edges = 0
    for route in routes:
        node_id = f"HTTP {str(route['method']).upper()} {route['path']}"
        graph.add_node(
            Node(
                id=node_id,
                kind="ROUTE",
                name=node_id,
                properties={
                    "method": str(route["method"]).upper(),
                    "path": route["path"],
                    "handler": route["handler"],
                    "framework": "fastapi",
                    "backend_endpoint": True,
                    "route_source_composer": True,
                    "confidence": route.get("confidence", 0.92),
                },
            )
        )
        edge_id = f"backend_route_source_composer__ROUTE_HANDLES__{node_id}__{route['handler']}"
        if any(
            (edge.id == edge_id)
            or (edge.kind == "ROUTE_HANDLES" and edge.from_node == node_id and edge.to_node == str(route["handler"]))
            for edge in graph.edges
        ):
            continue
        graph.add_edge(
            Edge(
                id=edge_id,
                kind="ROUTE_HANDLES",
                from_node=node_id,
                to_node=str(route["handler"]),
                source="INFERRED",
                confidence=float(route.get("confidence", 0.92)),
                evidence=[Evidence(description="FastAPI route composed from module-qualified router identity", source="INFERRED")],
                properties={
                    "resolver": "backend_route_source_composer",
                    "status": "confirmed",
                    "framework": "fastapi",
                },
            )
        )
        added_edges += 1

    rejected = _reject_conflicting_fastapi_route_edges(graph, route_keys)
    graph.metadata["backend_route_source_composer"] = {
        "status": "applied",
        "routes": len(routes),
        "edges_added": added_edges,
        "conflicting_edges_rejected": rejected,
    }
    return graph


def _reject_conflicting_fastapi_route_edges(graph: GraphDocument, route_keys: set[tuple[str, str, str]]) -> int:
    by_handler_method: dict[tuple[str, str], set[str]] = {}
    for method, path, handler in route_keys:
        by_handler_method.setdefault((handler, method), set()).add(path)

    rejected = 0
    for edge in graph.edges:
        if edge.kind not in {"ROUTE_HANDLES", "MATCHES_ENDPOINT"}:
            continue
        parsed = _parse_http_node(edge.from_node)
        if parsed is None:
            continue
        method, path = parsed
        allowed_paths = by_handler_method.get((edge.to_node, method.upper()))
        if not allowed_paths or _canonical_route_path(path) in {_canonical_route_path(item) for item in allowed_paths}:
            continue
        if edge.properties.get("resolver") == "backend_route_source_composer":
            continue
        edge.kind = "AFFECTS"
        edge.confidence = min(edge.confidence, 0.20)
        edge.properties["status"] = "rejected"
        edge.properties["rejected_by"] = "backend_route_source_composer"
        edge.properties["rejection_reason"] = "route path conflicts with module-qualified source route composition"
        edge.evidence.append(
            Evidence(
                description=f"Rejected route {method} {path}; source-composed paths for handler are {sorted(allowed_paths)}",
                source="INFERRED",
            )
        )
        rejected += 1
    return rejected


def _collect_backend_routes_from_graph(graph: GraphDocument) -> list[dict[str, Any]]:
    route_nodes = {}
    for node in graph.nodes:
        if node.kind != "ROUTE":
            continue
        parsed = _parse_http_node(node.id)
        if parsed is None:
            method = node.properties.get("method")
            path = node.properties.get("path")
            if not method or not path:
                continue
            parsed = (str(method).upper(), str(path))
        route_nodes[node.id] = {
            "method": parsed[0],
            "path": parsed[1],
            "handler": node.properties.get("handler", ""),
            "framework": node.properties.get("framework", "unknown"),
            "confidence": float(node.properties.get("confidence", 0.85)),
        }

    for edge in graph.edges:
        if edge.kind not in {"ROUTE_HANDLES", "MATCHES_ENDPOINT"}:
            continue
        if edge.from_node not in route_nodes:
            continue
        route = route_nodes[edge.from_node]
        if not route.get("handler"):
            route["handler"] = edge.to_node
        route["confidence"] = max(float(route.get("confidence", 0.0)), edge.confidence)
        if edge.properties.get("framework"):
            route["framework"] = edge.properties["framework"]
        elif edge.properties.get("support_pack_library"):
            route["framework"] = edge.properties["support_pack_library"]

    return [route for route in route_nodes.values() if route.get("handler")]


def _collect_fastapi_backend_routes_from_source(graph: GraphDocument) -> list[dict[str, Any]]:
    root_value = graph.metadata.get("project_path") or graph.metadata.get("path")
    if not root_value:
        return []
    root = Path(str(root_value))
    if not root.exists():
        return []

    routers: dict[str, str] = {}
    includes: list[tuple[str, str, str]] = []
    route_defs: list[dict[str, Any]] = []
    reexports: dict[str, str] = {}

    from impact_engine.scope import iter_project_files
    for path in iter_project_files(root, {".py"}):
        if any(part in _SKIP_DIRS or part.startswith(".") for part in path.relative_to(root).parts):
            continue
        module = _python_module_id(root, path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except Exception:
            continue
        is_package_module = path.name == "__init__.py"
        import_map = _python_import_map(tree, module, is_package_module=is_package_module)
        reexports.update(_python_reexports(tree, module, import_map, is_package_module=is_package_module))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                _collect_router_assignment(node, module, routers)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                route_defs.extend(_collect_route_decorators(node, module, path, root))
            elif isinstance(node, ast.Call):
                include = _collect_include_router_call(node, module, import_map)
                if include:
                    includes.append(include)

    includes = [(_resolve_reexport(parent, reexports, routers), _resolve_reexport(child, reexports, routers), prefix) for parent, child, prefix in includes]
    prefixes_by_router: dict[str, set[str]] = {}

    def prefixes_for(router_id: str, seen: set[str] | None = None) -> set[str]:
        if router_id in prefixes_by_router:
            return prefixes_by_router[router_id]
        seen = set(seen or set())
        if router_id in seen:
            return {routers.get(router_id, "")}
        seen.add(router_id)
        local_prefix = routers.get(router_id, "")
        parents = [(parent, include_prefix) for parent, child, include_prefix in includes if child == router_id]
        if not parents:
            prefixes_by_router[router_id] = {_join_paths(local_prefix)}
            return prefixes_by_router[router_id]
        result: set[str] = set()
        for parent, include_prefix in parents:
            for parent_prefix in prefixes_for(parent, seen):
                result.add(_join_paths(parent_prefix, include_prefix, local_prefix))
        prefixes_by_router[router_id] = result
        return result

    output: list[dict[str, Any]] = []
    for route in route_defs:
        router_id = _resolve_reexport(str(route["router_id"]), reexports, routers)
        for prefix in prefixes_for(router_id):
            output.append(
                {
                    "method": route["method"],
                    "path": _join_paths(prefix, route["path"]),
                    "handler": route["handler"],
                    "framework": "fastapi",
                    "confidence": 0.92,
                }
            )
    return output


def _add_endpoint_nodes(graph: GraphDocument, result: dict[str, Any]) -> None:
    for node_data in result.get("frontend_http_nodes", []) or []:
        node_id = str(node_data.get("id") or "")
        if not node_id:
            continue
        graph.add_node(
            Node(
                id=node_id,
                kind="ROUTE",
                name=node_id,
                properties={
                    "method": node_data.get("method"),
                    "path": node_data.get("path"),
                    "query": node_data.get("query", ""),
                    "frontend_endpoint": True,
                    "endpoint_bridge": True,
                    "confidence": node_data.get("confidence"),
                    "warnings": node_data.get("warnings", []),
                },
            )
        )

    for node_data in result.get("backend_route_nodes", []) or []:
        node_id = str(node_data.get("id") or "")
        if not node_id:
            continue
        graph.add_node(
            Node(
                id=node_id,
                kind="ROUTE",
                name=node_id,
                properties={
                    "method": node_data.get("method"),
                    "path": node_data.get("path"),
                    "handler": node_data.get("handler"),
                    "framework": node_data.get("framework"),
                    "backend_endpoint": True,
                    "endpoint_bridge": True,
                },
            )
        )


def _add_endpoint_edge(graph: GraphDocument, edge_data: dict[str, Any]) -> bool:
    status = str(edge_data.get("status", "weak"))
    if status not in _ACTIVE_STATUSES:
        return False

    kind = _map_edge_kind(str(edge_data.get("kind", "")))
    if kind not in _ALLOWED_EDGE_KINDS:
        return False

    source = str(edge_data.get("from") or "")
    target = str(edge_data.get("to") or "")
    if not source or not target:
        return False

    evidence = [
        Evidence(description=str(item), source="INFERRED")
        for item in edge_data.get("evidence", []) or ["frontend/backend endpoint bridge"]
    ]
    confidence = float(edge_data.get("confidence", 0.0))
    graph.add_edge(
        Edge(
            id=f"frontend_backend_endpoint_bridge__{kind}__{source}__{target}",
            kind=kind,
            from_node=source,
            to_node=target,
            source="INFERRED",
            confidence=confidence,
            evidence=evidence,
            properties={
                "resolver": "frontend_backend_endpoint_bridge",
                "original_kind": edge_data.get("kind"),
                "status": status,
                "warnings": edge_data.get("warnings", []),
                **dict(edge_data.get("metadata", {}) or {}),
            },
        )
    )
    return True


def _add_frontend_relation_edges(graph: GraphDocument, input_data: dict[str, Any]) -> int:
    added = 0
    for edge_data in _frontend_relation_edge_facts(input_data):
        source = edge_data["from"]
        target = edge_data["to"]
        kind = edge_data["kind"]
        edge_id = f"frontend_semantic_relation__{kind}__{source}__{target}"
        if any(edge.id == edge_id for edge in graph.edges):
            continue
        _ensure_frontend_symbol_node(graph, source)
        _ensure_frontend_symbol_node(graph, target)
        graph.add_edge(
            Edge(
                id=edge_id,
                kind=kind,
                from_node=source,
                to_node=target,
                source="INFERRED",
                confidence=float(edge_data.get("confidence", 0.78)),
                evidence=[Evidence(description=edge_data.get("evidence", "frontend semantic relation"), source="INFERRED")],
                properties={
                    "resolver": "frontend_backend_endpoint_bridge",
                    "status": edge_data.get("status", "likely"),
                    "frontend_relation": True,
                    "relation_type": edge_data.get("relation_type", kind),
                },
            )
        )
        added += 1
    return added


def _ensure_frontend_symbol_node(graph: GraphDocument, symbol_id: str) -> None:
    if any(node.id == symbol_id for node in graph.nodes):
        return
    kind = "TEST" if ".test" in symbol_id or ".__tests__." in symbol_id else "FUNCTION"
    semantic_role = "function"
    if symbol_id.rsplit(".", 1)[-1].startswith("use"):
        semantic_role = "hook"
    elif symbol_id.rsplit(".", 1)[-1][:1].isupper():
        semantic_role = "component"
    if kind == "TEST":
        semantic_role = "test"
    graph.add_node(Node(id=symbol_id, name=symbol_id.rsplit(".", 1)[-1], kind=kind, properties={"frontend_semantic": True, "frontend_role": semantic_role}))


def _frontend_relation_edge_facts(input_data: dict[str, Any]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for component in input_data.get("components", []) or []:
        component_id = str(component.get("id") or "")
        for hook_ref in component.get("uses_hooks", []) or []:
            if component_id and hook_ref:
                edges.append({
                    "from": component_id,
                    "to": str(hook_ref),
                    "kind": "DEPENDS_ON",
                    "confidence": 0.88,
                    "status": "confirmed",
                    "relation_type": "USES_HOOK",
                    "evidence": "React component calls hook",
                })
    for hook in input_data.get("hooks", []) or []:
        hook_id = str(hook.get("id") or "")
        exposes = hook.get("exposes", {}) or {}
        iterable = [{"name": key, "target": value} for key, value in exposes.items()] if isinstance(exposes, dict) else exposes
        for exposed in iterable:
            target = exposed.get("target") if isinstance(exposed, dict) else None
            if hook_id and target:
                edges.append({
                    "from": hook_id,
                    "to": str(target),
                    "kind": "DEPENDS_ON",
                    "confidence": 0.84,
                    "status": "likely",
                    "relation_type": "EXPOSES_ACTION",
                    "evidence": f"React hook exposes or calls action {exposed.get('name')}",
                })
    for test in input_data.get("tests", []) or []:
        test_id = str(test.get("id") or "")
        for target in test.get("targets", []) or []:
            if test_id and target:
                edges.append({
                    "from": test_id,
                    "to": str(target),
                    "kind": "TESTS",
                    "confidence": 0.82,
                    "status": "likely",
                    "relation_type": "FRONTEND_TEST_TARGET",
                    "evidence": "frontend test references component/hook/client symbol",
                })
    return edges


def _map_edge_kind(kind: str) -> str:
    if kind == "ROUTES_TO":
        return "MATCHES_ENDPOINT"
    if kind in {"USES_HOOK", "EXPOSES_ACTION"}:
        return "DEPENDS_ON"
    return kind


def _parse_http_node(node_id: str) -> tuple[str, str] | None:
    match = _HTTP_ROUTE_RE.match(node_id)
    if not match:
        return None
    return match.group("method"), match.group("path")


def _canonical_route_path(path: str) -> str:
    clean = "/" + str(path).strip("/")
    return "/" if clean == "/" else clean.rstrip("/")


def _python_module_id(root: Path, path: Path) -> str:
    rel = path.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _python_import_map(tree: ast.AST, module: str, *, is_package_module: bool = False) -> dict[str, str]:
    imports: dict[str, str] = {}
    package = module if is_package_module else (module.rsplit(".", 1)[0] if "." in module else "")
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ImportFrom):
            source = _resolve_python_import_module(package, node.module or "", node.level)
            for alias in node.names:
                local = alias.asname or alias.name
                imports[local] = f"{source}.{alias.name}" if source else alias.name
        elif isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".", 1)[0]
                imports[local] = alias.name
    return imports


def _python_reexports(tree: ast.AST, module: str, import_map: dict[str, str], *, is_package_module: bool = False) -> dict[str, str]:
    reexports: dict[str, str] = {}
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        package = module if is_package_module else (module.rsplit(".", 1)[0] if "." in module else "")
        source = _resolve_python_import_module(package, node.module or "", node.level)
        for alias in node.names:
            local = alias.asname or alias.name
            target = f"{source}.{alias.name}" if source else alias.name
            reexports[f"{module}.{local}"] = target
    return reexports


def _resolve_python_import_module(package: str, imported_module: str, level: int) -> str:
    if level <= 0:
        return _prefix_backend_module(imported_module)
    base_parts = package.split(".") if package else []
    keep = max(0, len(base_parts) - level + 1)
    parts = base_parts[:keep]
    if imported_module:
        parts.extend(imported_module.split("."))
    return ".".join(parts)


def _prefix_backend_module(module: str) -> str:
    if module.startswith("app."):
        return f"backend.{module}"
    return module


def _collect_router_assignment(node: ast.Assign, module: str, routers: dict[str, str]) -> None:
    if not isinstance(node.value, ast.Call):
        return
    if _call_name(node.value.func).split(".")[-1] != "APIRouter":
        return
    prefix = _kw_literal(node.value, "prefix") or ""
    for target in node.targets:
        if isinstance(target, ast.Name):
            routers[f"{module}.{target.id}"] = prefix


def _collect_route_decorators(node: ast.FunctionDef | ast.AsyncFunctionDef, module: str, path: Path, root: Path) -> list[dict[str, Any]]:
    routes: list[dict[str, Any]] = []
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
            continue
        method = decorator.func.attr.upper()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}:
            continue
        receiver = _expr_name(decorator.func.value)
        if not receiver:
            continue
        local_path = _first_arg_literal(decorator) or _kw_literal(decorator, "path") or ""
        routes.append(
            {
                "method": method,
                "path": local_path,
                "handler": f"{module}.{node.name}",
                "router_id": f"{module}.{receiver}",
                "file": path.relative_to(root).as_posix(),
                "line": node.lineno,
            }
        )
    return routes


def _collect_include_router_call(node: ast.Call, module: str, import_map: dict[str, str]) -> tuple[str, str, str] | None:
    if not isinstance(node.func, ast.Attribute) or node.func.attr != "include_router":
        return None
    parent_receiver = _expr_name(node.func.value)
    if not parent_receiver:
        return None
    if not node.args:
        return None
    child_name = _expr_name(node.args[0])
    if not child_name:
        return None
    parent = f"{module}.{parent_receiver}"
    child = import_map.get(child_name, f"{module}.{child_name}")
    prefix = _kw_literal(node, "prefix") or ""
    return parent, child, prefix


def _resolve_reexport(symbol: str, reexports: dict[str, str], routers: dict[str, str]) -> str:
    seen: set[str] = set()
    current = symbol
    while current in reexports and current not in seen:
        seen.add(current)
        current = reexports[current]
    if current in routers:
        return current
    if current.startswith("backend.") and current[len("backend.") :] in routers:
        return current[len("backend.") :]
    suffix_matches = [router for router in routers if current.endswith("." + router) or router.endswith("." + current)]
    if len(suffix_matches) == 1:
        return suffix_matches[0]
    # Do not infer arbitrary package members (for example ``app``) as routers.
    # A package-level fallback is only safe for an explicitly router-shaped
    # symbol; otherwise same-package variables can collapse parent/child
    # identities and duplicate route prefixes.
    if "." in current and current.rsplit(".", 1)[-1].lower() in {"router", "api_router"}:
        package = current.rsplit(".", 1)[0]
        candidates = [router for router in routers if router.startswith(package + ".") and router.endswith(".router")]
        if len(candidates) == 1:
            return candidates[0]
    return current


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _expr_name(node: ast.AST) -> str:
    return _call_name(node)


def _first_arg_literal(node: ast.Call) -> str | None:
    if not node.args:
        return None
    return _literal(node.args[0])


def _kw_literal(node: ast.Call, name: str) -> str | None:
    for kw in node.keywords:
        if kw.arg == name:
            return _literal(kw.value)
    return None


def _literal(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _join_paths(*parts: str) -> str:
    cleaned: list[str] = []
    for part in parts:
        if not part:
            continue
        cleaned.append(str(part).strip("/"))
    if not cleaned:
        return "/"
    return "/" + "/".join(item for item in cleaned if item)


def _iter_frontend_files(root: Path):
    from impact_engine.scope import iter_project_files
    for path in iter_project_files(root):
        if not path.is_file() or path.suffix.lower() not in _JS_TS_EXTENSIONS:
            continue
        try:
            parts = path.relative_to(root).parts
        except ValueError:
            parts = path.parts
        if any(part in _SKIP_DIRS or part.startswith(".") for part in parts):
            continue
        yield path


def _module_id_for_path(root: Path, path: Path) -> str:
    rel = path.relative_to(root)
    parts = list(rel.with_suffix("").parts)
    if "src" in parts:
        parts = parts[parts.index("src") + 1 :]
    return ".".join(parts) or path.stem


def _parse_imports(text: str, module: str) -> list[dict[str, str]]:
    imports: list[dict[str, str]] = []
    export_pattern = re.compile(r"export\s+\{(?P<items>.*?)\}\s+from\s+['\"](?P<source>[^'\"]+)['\"]", re.S)
    for match in export_pattern.finditer(text):
        source_module = _resolve_import_module(module, match.group("source"))
        for raw in match.group("items").split(","):
            item = raw.strip()
            if not item:
                continue
            if " as " in item:
                imported, local = [part.strip() for part in item.split(" as ", 1)]
            else:
                imported = local = item
            imports.append({"local": local, "imported": imported, "from_module": source_module, "target": f"{source_module}.{imported}", "reexport": "true"})
    pattern = re.compile(r"import\s+\{(?P<items>.*?)\}\s+from\s+['\"](?P<source>[^'\"]+)['\"]", re.S)
    for match in pattern.finditer(text):
        source_module = _resolve_import_module(module, match.group("source"))
        for raw in match.group("items").split(","):
            item = raw.strip()
            if not item or item.startswith("type "):
                continue
            if " as " in item:
                imported, local = [part.strip() for part in item.split(" as ", 1)]
            else:
                imported = local = item
            imports.append({"local": local, "imported": imported, "from_module": source_module, "target": f"{source_module}.{imported}"})
    default_pattern = re.compile(r"import\s+(?P<local>\w+)\s+from\s+['\"](?P<source>[^'\"]+)['\"]")
    for match in default_pattern.finditer(text):
        source_module = _resolve_import_module(module, match.group("source"))
        imports.append({"local": match.group("local"), "imported": "default", "from_module": source_module, "target": f"{source_module}.default"})
    namespace_pattern = re.compile(r"import\s+\*\s+as\s+(?P<local>\w+)\s+from\s+['\"](?P<source>[^'\"]+)['\"]")
    for match in namespace_pattern.finditer(text):
        source_module = _resolve_import_module(module, match.group("source"))
        imports.append({"local": match.group("local"), "imported": "*", "from_module": source_module, "target": source_module})
    return imports


def _resolve_import_module(current_module: str, source: str) -> str:
    source = source.strip()
    if source.startswith("@/"):
        return source[2:].replace("/", ".")
    if source.startswith("@"):
        return source[1:].replace("/", ".")
    if source.startswith("."):
        base = current_module.split(".")[:-1]
        parts = base + [part for part in source.split("/") if part and part != "."]
        normalized: list[str] = []
        for part in parts:
            if part == "..":
                if normalized:
                    normalized.pop()
            else:
                normalized.append(part)
        if normalized and normalized[-1] == "index":
            normalized.pop()
        return ".".join(normalized)
    return source.replace("/", ".")


def _parse_constants(text: str, module: str) -> list[dict[str, Any]]:
    constants: list[dict[str, Any]] = []
    pattern = re.compile(r"(?:export\s+)?const\s+(?P<name>\w+)\s*(?::[^=]+)?=\s*(?P<expr>[^;\n]+)", re.S)
    for match in pattern.finditer(text):
        expr_text = match.group("expr").strip()
        if expr_text.startswith("{") or expr_text.startswith("["):
            continue
        name = match.group("name")
        constants.append({"id": f"{module}.{name}", "name": name, "module": module, "expression": _expr_from_text(expr_text)})
    return constants


def _parse_functions(text: str, module: str) -> list[dict[str, Any]]:
    functions: list[dict[str, Any]] = []
    ranges: list[tuple[int, int]] = []

    declaration = re.compile(
        r"(?:export\s+)?(?:async\s+)?function\s+(?P<name>\w+)\s*\((?P<params>[^)]*)\)[^{]*\{",
        re.S,
    )
    for match in declaration.finditer(text):
        open_brace = text.find("{", match.end() - 1)
        close_brace = _matching_brace(text, open_brace)
        if close_brace <= open_brace:
            continue
        ranges.append((match.start(), close_brace))
        functions.append(_function_fact(module, match.group("name"), match.group("params"), text[open_brace + 1 : close_brace]))

    arrow = re.compile(
        r"(?:export\s+)?const\s+(?P<name>\w+)\s*=\s*(?:async\s*)?\((?P<params>[^)]*)\)\s*(?::[^=]+)?=>\s*",
        re.S,
    )
    for match in arrow.finditer(text):
        if any(start <= match.start() <= end for start, end in ranges):
            continue
        body_start = match.end()
        if body_start < len(text) and text[body_start] == "{":
            close_brace = _matching_brace(text, body_start)
            if close_brace <= body_start:
                continue
            body = text[body_start + 1 : close_brace]
            ranges.append((match.start(), close_brace))
        else:
            line_end = text.find("\n", body_start)
            if line_end == -1:
                line_end = len(text)
            body = "return " + text[body_start:line_end].strip()
            ranges.append((match.start(), line_end))
        functions.append(_function_fact(module, match.group("name"), match.group("params"), body))

    return functions


def _function_fact(module: str, name: str, params_text: str, body: str) -> dict[str, Any]:
    params = [_clean_param(part) for part in _split_args(params_text) if _clean_param(part)]
    local_exprs = _parse_local_expressions(body)
    calls = _parse_calls(body, local_exprs)
    fact: dict[str, Any] = {
        "id": f"{module}.{name}",
        "name": name,
        "module": module,
        "params": params,
        "calls": calls,
    }
    return_expr = _parse_return_expression(body)
    if return_expr is not None:
        fact["returns"] = return_expr
    return fact


def _parse_local_expressions(body: str) -> dict[str, Any]:
    local_exprs: dict[str, Any] = {}
    pattern = re.compile(r"(?:const|let|var)\s+(?P<name>\w+)\s*(?::[^=]+)?=\s*(?:await\s+)?(?P<expr>.+?)(?:\n|;)")
    for match in pattern.finditer(body):
        expr_text = match.group("expr").strip()
        if expr_text.startswith("{") or expr_text.startswith("["):
            continue
        local_exprs[match.group("name")] = _expr_from_text(expr_text)
    return local_exprs


def _parse_return_expression(body: str) -> Any | None:
    return_match = re.search(r"\breturn\b", body)
    if return_match:
        cursor = return_match.end()
        while cursor < len(body) and body[cursor].isspace():
            cursor += 1
        if cursor < len(body) and body[cursor] == "{":
            close_brace = _matching_brace(body, cursor)
            if close_brace > cursor:
                return _expr_from_text(body[cursor : close_brace + 1])
    match = re.search(r"return\s+(?P<expr>.+?)(?:\n|;|$)", body, re.S)
    if not match:
        return None
    expr_text = match.group("expr").strip()
    if expr_text.startswith("["):
        return None
    return _expr_from_text(expr_text)


def _parse_calls(body: str, local_exprs: dict[str, Any]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for callee, args_text in _iter_call_texts(body):
        if callee in {"if", "for", "while", "switch", "catch", "return", "function"}:
            continue
        args = []
        for arg in _split_args(args_text):
            expr = _expr_from_text(arg)
            if isinstance(expr, dict) and expr.get("type") == "ref" and expr.get("name") in local_exprs:
                expr = local_exprs[expr["name"]]
            args.append(expr)
        calls.append({"callee": callee, "args": args})
    return calls


def _classify_frontend_function(
    function: dict[str, Any],
    module: str,
    import_map: dict[str, str],
    path: Path,
    components: list[dict[str, Any]],
    hooks: list[dict[str, Any]],
    tests: list[dict[str, Any]],
) -> None:
    name = str(function.get("name") or "")
    function_id = str(function.get("id") or "")
    calls = function.get("calls", []) or []
    is_test_file = path.name.endswith((".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx")) or "__tests__" in path.parts

    if name.startswith("use") and len(name) > 3 and name[3].isupper():
        exposes: dict[str, str] = {}
        returns = function.get("returns")
        if isinstance(returns, dict) and returns.get("type") == "object":
            for exposed_name, expr in (returns.get("properties") or {}).items():
                if isinstance(expr, dict) and expr.get("type") == "ref":
                    local_name = str(expr.get("name") or "")
                    if local_name in import_map:
                        exposes[str(exposed_name)] = _resolve_barrel_target(import_map[local_name], import_map)
                    elif local_name:
                        exposes[str(exposed_name)] = f"{module}.{local_name}"
        for call in calls:
            callee = str(call.get("callee") or "")
            simple = callee.split(".", 1)[0]
            target = import_map.get(simple)
            if target:
                exposes[callee.rsplit(".", 1)[-1]] = _resolve_barrel_target(target, import_map)
            elif callee and not _is_builtin_frontend_call(callee):
                exposes[callee.rsplit(".", 1)[-1]] = f"{module}.{callee}"
        hooks.append({"id": function_id, "name": name, "module": module, "exposes": exposes})

    if name and name[0].isupper():
        used_hooks: list[str] = []
        for call in calls:
            callee = str(call.get("callee") or "")
            if callee.startswith("use") and len(callee) > 3 and callee[3].isupper():
                used_hooks.append(_resolve_barrel_target(import_map.get(callee, f"{module}.{callee}"), import_map))
        if used_hooks:
            components.append({"id": function_id, "name": name, "module": module, "uses_hooks": used_hooks})

    if is_test_file or name.lower().startswith(("test", "it", "should")):
        targets: list[str] = []
        for call in calls:
            callee = str(call.get("callee") or "")
            simple = callee.split(".", 1)[0]
            target = import_map.get(simple)
            if target:
                targets.append(_resolve_barrel_target(target, import_map))
        if targets:
            tests.append({"id": function_id, "name": name, "module": module, "targets": sorted(set(targets))})


def _append_file_level_frontend_test_fact(
    path: Path,
    module: str,
    import_map: dict[str, str],
    text: str,
    tests: list[dict[str, Any]],
) -> None:
    is_test_file = path.name.endswith((".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx")) or "__tests__" in path.parts
    if not is_test_file:
        return
    targets: set[str] = set()
    for tag in re.findall(r"<\s*([A-Z]\w*)\b", text):
        target = import_map.get(tag)
        if target:
            targets.add(_resolve_barrel_target(target, import_map))
    for local, target in import_map.items():
        if local[:1].isupper() or local.startswith("use"):
            targets.add(_resolve_barrel_target(target, import_map))
    if targets:
        tests.append({"id": f"{module}.__file__", "name": path.stem, "module": module, "targets": sorted(targets)})


def _resolve_barrel_target(target: str, import_map: dict[str, str]) -> str:
    # If a symbol resolves to a barrel module symbol and the same local name is
    # re-exported by that module, prefer the concrete target.
    local = target.rsplit(".", 1)[-1]
    reexport = import_map.get(local)
    return reexport or target


def _is_builtin_frontend_call(callee: str) -> bool:
    return callee in {
        "fetch",
        "axios.get",
        "axios.post",
        "axios.put",
        "axios.patch",
        "axios.delete",
        "render",
        "screen.getByText",
        "expect",
    } or callee.startswith(("console.", "React.", "screen.", "expect."))


def _iter_call_texts(body: str):
    index = 0
    pattern = re.compile(r"(?P<callee>\b[\w.]+)\s*(?:<[^>\n]+>)?\s*\(")
    while True:
        match = pattern.search(body, index)
        if not match:
            break
        open_paren = body.find("(", match.end() - 1)
        close_paren = _matching_pair(body, open_paren, "(", ")")
        if close_paren <= open_paren:
            index = match.end()
            continue
        yield match.group("callee"), body[open_paren + 1 : close_paren]
        index = close_paren + 1


def _expr_from_text(text: str) -> Any:
    text = _strip_ts_noise(text.strip())
    if not text:
        return {"type": "unknown", "name": "empty"}
    if (text[0:1], text[-1:]) in {( "'", "'" ), ('"', '"')}:
        return {"type": "literal", "value": text[1:-1]}
    if text.startswith("`") and text.endswith("`"):
        return _template_expr(text[1:-1])
    conditional = _split_conditional(text)
    if conditional is not None:
        condition, when_true, when_false = conditional
        return {
            "type": "conditional",
            "condition": _expr_from_text(condition),
            "when_true": _expr_from_text(when_true),
            "when_false": _expr_from_text(when_false),
        }
    if text.startswith("{") and text.endswith("}"):
        return _object_expr(text[1:-1])
    parts = _split_top_level(text, "+")
    if len(parts) > 1:
        return {"type": "concat", "parts": [_expr_from_text(part) for part in parts]}
    call = re.match(r"^(?P<name>[\w.]+)\s*\((?P<args>.*)\)$", text, re.S)
    if call:
        name = call.group("name")
        args = [_expr_from_text(arg) for arg in _split_args(call.group("args"))]
        return _special_call_expr(name, args)
    if re.match(r"^[A-Za-z_$]\w*$", text):
        return {"type": "ref", "name": text}
    return {"type": "unknown", "name": text}


def _split_conditional(text: str) -> tuple[str, str, str] | None:
    """Split a top-level JavaScript ternary without touching template literals."""
    question_parts = _split_top_level(text, "?")
    if len(question_parts) != 2:
        return None
    condition, branches = question_parts
    colon_parts = _split_top_level(branches, ":")
    if len(colon_parts) != 2:
        return None
    return condition, colon_parts[0], colon_parts[1]


def _object_expr(text: str) -> dict[str, Any]:
    props: dict[str, Any] = {}
    for item in _split_top_level(text, ","):
        if not item:
            continue
        if ":" in item:
            key, value = item.split(":", 1)
            props[key.strip().strip("'\"")] = _expr_from_text(value.strip())
        elif re.match(r"^[A-Za-z_$]\w*$", item.strip()):
            name = item.strip()
            props[name] = {"type": "ref", "name": name}
    return {"type": "object", "properties": props}


def _special_call_expr(name: str, args: list[Any]) -> Any:
    simple_name = name.rsplit(".", 1)[-1]
    if simple_name in {"buildUrl", "makeUrl"}:
        parts: list[Any] = []
        for index, arg in enumerate(args):
            if index:
                parts.append({"type": "literal", "value": "/"})
            parts.append(arg)
        return {"type": "concat", "parts": parts}
    if simple_name == "appendPath" and len(args) >= 2:
        return {"type": "concat", "parts": [args[0], {"type": "literal", "value": "/"}, args[1]]}
    if simple_name in {"encodePath", "encodeURIComponent"} and args:
        return args[0]
    return {"type": "call", "name": name, "args": args}


def _template_expr(text: str) -> dict[str, Any]:
    parts: list[Any] = []
    cursor = 0
    for match in re.finditer(r"\$\{(?P<expr>[^}]+)\}", text):
        if match.start() > cursor:
            parts.append({"type": "literal", "value": text[cursor : match.start()]})
        parts.append(_expr_from_text(match.group("expr")))
        cursor = match.end()
    if cursor < len(text):
        parts.append({"type": "literal", "value": text[cursor:]})
    return {"type": "template", "parts": parts}


def _strip_ts_noise(text: str) -> str:
    text = re.sub(r"\s+as\s+const$", "", text)
    text = re.sub(r"\s+as\s+[\w.<>]+$", "", text)
    return text.strip()


def _clean_param(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    text = text.split("=", 1)[0].strip()
    text = text.split(":", 1)[0].strip()
    text = text.lstrip("...")
    text = text.rstrip("?").strip()
    return text


def _split_args(text: str) -> list[str]:
    return _split_top_level(text, ",")


def _split_top_level(text: str, delimiter: str) -> list[str]:
    result: list[str] = []
    current: list[str] = []
    depth = 0
    quote: str | None = None
    escape = False
    for ch in text:
        if escape:
            current.append(ch)
            escape = False
            continue
        if ch == "\\":
            current.append(ch)
            escape = True
            continue
        if quote:
            current.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in {"'", '"', "`"}:
            quote = ch
            current.append(ch)
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == delimiter and depth == 0:
            result.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current or text:
        result.append("".join(current).strip())
    return [item for item in result if item]


def _matching_brace(text: str, open_index: int) -> int:
    return _matching_pair(text, open_index, "{", "}")


def _matching_pair(text: str, open_index: int, open_char: str, close_char: str) -> int:
    if open_index < 0 or open_index >= len(text) or text[open_index] != open_char:
        return -1
    depth = 0
    quote: str | None = None
    escape = False
    for index in range(open_index, len(text)):
        ch = text[index]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in {"'", '"', "`"}:
            quote = ch
            continue
        if ch == open_char:
            depth += 1
        elif ch == close_char:
            depth -= 1
            if depth == 0:
                return index
    return -1
