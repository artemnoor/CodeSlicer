"""Main frontend/backend endpoint resolution pipeline."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .canonicalize import canonicalize_path, canonicalize_route, path_suffix_equal
from .evaluator import ModuleIndex, PathEvaluator
from .models import BackendRoute, Edge, EvalResult, HttpEndpointNode
from .quality import backend_match_confidence, frontend_http_confidence, status_for_confidence
from .wrappers import WrapperResolver


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _validate_input(input_data: Any) -> list[str]:
    if not isinstance(input_data, dict):
        return ["input_data must be a dictionary"]
    if "backend_routes" not in input_data:
        return ["missing required key: backend_routes"]
    if not isinstance(input_data.get("backend_routes"), list):
        return ["backend_routes must be a list"]
    return []


def _collect_frontend_functions(input_data: dict[str, Any], index: ModuleIndex) -> list[dict[str, Any]]:
    seen: set[str] = set()
    functions: list[dict[str, Any]] = []
    for fact in list(input_data.get("frontend_functions", []) or []) + list(input_data.get("functions", []) or []):
        fqn = fact.get("id")
        if fqn and fqn not in seen:
            functions.append(fact)
            seen.add(fqn)
    for fact in index.functions_by_fqn.values():
        fqn = fact.get("id")
        if fqn and fqn not in seen and fact.get("calls"):
            functions.append(fact)
            seen.add(fqn)
    return functions


def _collect_backend_routes(input_data: dict[str, Any]) -> list[BackendRoute]:
    routes: list[BackendRoute] = []
    for item in input_data.get("backend_routes", []) or []:
        if not isinstance(item, dict):
            continue
        routes.append(
            BackendRoute(
                method=str(item.get("method", "GET")).upper(),
                path=str(item.get("path", "")),
                handler=str(item.get("handler", "")),
                framework=str(item.get("framework", "unknown")),
                confidence=float(item.get("confidence", 0.9)),
                service=str(item.get("service") or item.get("service_identity") or ""),
                raw=item,
            )
        )
    return routes


def _dedupe_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for node in nodes:
        node_id = str(node.get("id"))
        if node_id not in seen:
            output.append(node)
            seen.add(node_id)
    return output


def _edge_key(edge: Edge) -> tuple[str, str, str]:
    return edge.from_id, edge.to_id, edge.kind


def _categorize_edges(edges: list[Edge]) -> dict[str, list[dict[str, Any]]]:
    buckets: dict[str, list[dict[str, Any]]] = {k: [] for k in ["confirmed", "likely", "weak", "suspicious", "rejected"]}
    for edge in edges:
        buckets[edge.status].append(edge.to_dict())
    return buckets


def _build_component_hook_edges(input_data: dict[str, Any]) -> list[Edge]:
    edges: list[Edge] = []
    hooks_by_id = {h.get("id") or h.get("name"): h for h in input_data.get("hooks", []) or []}

    for component in input_data.get("components", []) or []:
        component_id = str(component.get("id") or component.get("name"))
        for hook_ref in _as_list(component.get("uses_hooks")):
            hook_id = str(hook_ref)
            if hook_id in hooks_by_id or hook_id:
                edges.append(
                    Edge(
                        from_id=component_id,
                        to_id=hook_id,
                        kind="USES_HOOK",
                        confidence=0.90,
                        source="FACT",
                        status="confirmed",
                        evidence=["component uses hook fact"],
                    )
                )
    for hook in input_data.get("hooks", []) or []:
        hook_id = str(hook.get("id") or hook.get("name"))
        exposes = hook.get("exposes", {}) or {}
        if isinstance(exposes, dict):
            iterable = [{"name": key, "target": value} for key, value in exposes.items()]
        else:
            iterable = exposes
        for exposed in iterable:
            target = exposed.get("target") if isinstance(exposed, dict) else None
            action_name = exposed.get("name") if isinstance(exposed, dict) else None
            if target:
                edges.append(
                    Edge(
                        from_id=hook_id,
                        to_id=str(target),
                        kind="EXPOSES_ACTION",
                        confidence=0.86,
                        source="FACT",
                        status="likely",
                        evidence=[f"hook exposes action:{action_name}"],
                    )
                )
    return edges


def _extract_frontend_http(
    input_data: dict[str, Any],
    evaluator: PathEvaluator,
    wrapper_resolver: WrapperResolver,
    index: ModuleIndex,
) -> tuple[list[HttpEndpointNode], list[Edge], list[dict[str, Any]], list[dict[str, Any]]]:
    nodes_by_id: dict[str, HttpEndpointNode] = {}
    edges: list[Edge] = []
    unresolved: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []

    for function in _collect_frontend_functions(input_data, index):
        function_id = str(function.get("id") or function.get("name"))
        module = function.get("module")
        calls = function.get("calls", []) or []
        for call_index, call in enumerate(calls):
            if not isinstance(call, dict):
                continue
            wrapper = wrapper_resolver.resolve_call(call)
            if wrapper is None:
                diagnostics.append({"kind": "non_http_call", "function": function_id, "callee": call.get("callee")})
                continue

            function_scope = {
                str(param): EvalResult("{param}", confidence=0.90, evidence=[f"function param:{param}"])
                for param in function.get("params", []) or []
            }
            eval_result = evaluator.evaluate(wrapper.url_expr, module=module, scope=function_scope)
            if not eval_result.ok or eval_result.value is None:
                unresolved.append(
                    {
                        "kind": "frontend_path",
                        "function": function_id,
                        "callee": call.get("callee"),
                        "reason": "path expression unresolved",
                        "details": eval_result.to_dict(),
                    }
                )
                continue

            canonical = canonicalize_path(eval_result.value)
            if not canonical.path:
                unresolved.append(
                    {
                        "kind": "frontend_path",
                        "function": function_id,
                        "callee": call.get("callee"),
                        "reason": "canonical path is empty",
                    }
                )
                continue

            has_dynamic = canonical.dynamic_segments > 0
            confidence, status, quality_warnings = frontend_http_confidence(
                wrapper.confidence,
                eval_result.confidence,
                has_dynamic_param=has_dynamic,
                unresolved=bool(eval_result.unresolved),
            )
            evidence = [*wrapper.evidence, *eval_result.evidence, f"canonical:{canonical.path}"]
            warnings = [*wrapper.warnings, *eval_result.warnings, *quality_warnings]
            node = HttpEndpointNode(
                method=wrapper.method,
                path=canonical.path,
                query=canonical.query,
                confidence=confidence,
                evidence=evidence,
                warnings=warnings,
                service=str(call.get("service") or function.get("service") or ""),
            )
            nodes_by_id[node.id or ""] = node
            edges.append(
                Edge(
                    from_id=function_id,
                    to_id=node.id or "",
                    kind="HTTP_CALLS",
                    confidence=confidence,
                    source="INFERRED",
                    status=status,
                    evidence=evidence,
                    warnings=warnings,
                    metadata={
                        "call_index": call_index,
                        "raw_path": eval_result.value,
                        "canonical_path": canonical.path,
                        "method": wrapper.method,
                    },
                )
            )

    return list(nodes_by_id.values()), edges, diagnostics, unresolved


def _match_backend_routes(
    frontend_nodes: list[HttpEndpointNode],
    backend_routes: list[BackendRoute],
) -> tuple[list[dict[str, Any]], list[Edge], list[dict[str, Any]], list[dict[str, Any]]]:
    backend_nodes: list[dict[str, Any]] = []
    edges: list[Edge] = []
    diagnostics: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []

    route_index: dict[tuple[str, str, str], list[tuple[BackendRoute, str]]] = defaultdict(list)
    routes_by_path: dict[tuple[str, str], list[BackendRoute]] = defaultdict(list)
    for route in backend_routes:
        method, canonical = canonicalize_route(route.method, route.path)
        node_id = f"{route.service}:{method}:{canonical.path}" if route.service else f"HTTP {method} {canonical.path}"
        backend_nodes.append(
            {
                "id": node_id,
                "method": method,
                "path": canonical.path,
                "raw_path": route.path,
                "handler": route.handler,
                "framework": route.framework,
                "confidence": round(route.confidence, 4),
                "service": route.service,
            }
        )
        route_index[(route.service, method, canonical.path)].append((route, node_id))
        routes_by_path[(route.service, canonical.path)].append(route)

    for node in frontend_nodes:
        key = (node.service, node.method.upper(), node.path)
        exact_matches = route_index.get(key, [])
        path_matches_wrong_method = [route for route in routes_by_path.get((node.service, node.path), []) if route.method.upper() != node.method.upper()]
        if path_matches_wrong_method and not exact_matches:
            for route in path_matches_wrong_method:
                edges.append(
                    Edge(
                        from_id=node.id or f"HTTP {node.method} {node.path}",
                        to_id=route.handler,
                        kind="ROUTES_TO",
                        confidence=0.0,
                        source="INFERRED",
                        status="rejected",
                        evidence=["canonical path matched but HTTP method differed"],
                        warnings=[f"method mismatch: frontend {node.method}, backend {route.method.upper()}"],
                    )
                )
            continue

        suffix_candidates = []
        for route in backend_routes:
            method, canonical = canonicalize_route(route.method, route.path)
            if route.service == node.service and method == node.method.upper() and path_suffix_equal(node.path, canonical.path):
                suffix_candidates.append((route, canonical.path))

        if not exact_matches:
            if suffix_candidates:
                for route, candidate_path in suffix_candidates:
                    edges.append(
                        Edge(
                            from_id=node.id or f"HTTP {node.method} {node.path}",
                            to_id=route.handler,
                            kind="ROUTES_TO",
                            confidence=0.50,
                            source="INFERRED",
                            status="suspicious",
                            evidence=["same method and suffix-compatible path only"],
                            warnings=[f"prefix differs: frontend {node.path}, backend {candidate_path}"],
                        )
                    )
            else:
                unresolved.append(
                    {
                        "kind": "backend_route",
                        "frontend_http_node": node.id,
                        "method": node.method,
                        "path": node.path,
                        "reason": "no backend route with same canonical method/path",
                    }
                )
            continue

        multiple = len(exact_matches) > 1
        for route, _route_node_id in exact_matches:
            confidence, status, warnings = backend_match_confidence(node.confidence, route.confidence, multiple=multiple)
            edges.append(
                Edge(
                    from_id=node.id or f"HTTP {node.method} {node.path}",
                    to_id=route.handler,
                    kind="ROUTES_TO",
                    confidence=confidence,
                    source="INFERRED",
                    status=status,
                    evidence=[
                        "canonical method/path match",
                        f"frontend:{node.method} {node.path}",
                        f"backend:{route.method.upper()} {canonicalize_path(route.path).path}",
                    ],
                    warnings=warnings,
                    metadata={"framework": route.framework},
                )
            )

    return _dedupe_nodes(backend_nodes), edges, diagnostics, unresolved


def resolve_frontend_backend_endpoints(input_data: dict[str, Any]) -> dict[str, Any]:
    """Resolve frontend HTTP endpoint facts to backend route facts.

    Parameters
    ----------
    input_data:
        JSON-compatible dictionary containing modules, frontend function facts,
        wrapper recipes, frontend component/hook facts, and backend route facts.

    Returns
    -------
    dict
        JSON-compatible result with nodes, edges, status buckets, diagnostics,
        and unresolved facts.
    """

    errors = _validate_input(input_data)
    if errors:
        return {"status": "error", "errors": errors}

    index = ModuleIndex.from_input(input_data)
    evaluator = PathEvaluator(index)
    wrapper_resolver = WrapperResolver.from_input(input_data)
    backend_routes = _collect_backend_routes(input_data)

    component_edges = _build_component_hook_edges(input_data)
    frontend_nodes, http_edges, frontend_diag, frontend_unresolved = _extract_frontend_http(
        input_data, evaluator, wrapper_resolver, index
    )
    backend_nodes, route_edges, backend_diag, backend_unresolved = _match_backend_routes(frontend_nodes, backend_routes)

    edges_by_key: dict[tuple[str, str, str], Edge] = {}
    for edge in [*component_edges, *http_edges, *route_edges]:
        key = _edge_key(edge)
        current = edges_by_key.get(key)
        if current is None or edge.confidence > current.confidence:
            edges_by_key[key] = edge
    edges = list(edges_by_key.values())
    edge_dicts = [edge.to_dict() for edge in edges]
    buckets = _categorize_edges(edges)

    return {
        "status": "ok",
        "frontend_http_nodes": [node.to_dict() for node in frontend_nodes],
        "backend_route_nodes": backend_nodes,
        "edges": edge_dicts,
        "confirmed": buckets["confirmed"],
        "likely": buckets["likely"],
        "weak": buckets["weak"],
        "suspicious": buckets["suspicious"],
        "rejected": buckets["rejected"],
        "diagnostics": [*frontend_diag, *backend_diag],
        "unresolved": [*frontend_unresolved, *backend_unresolved],
    }
