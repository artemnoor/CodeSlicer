"""Evidence-gated Gin route extraction."""
from __future__ import annotations

import re
from pathlib import Path

from impact_engine.models import Edge, Evidence
from plugins.frameworks.polyglot_web_common import add_framework_candidate, add_literal_route, add_route, result, source_files


_ROUTE = re.compile(
    r"\b[A-Za-z_]\w*\.(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s*\(\s*['\"]([^'\"]+)['\"]",
)
_DIRECT_HANDLER = re.compile(
    r"\(\s*['\"][^'\"]+['\"]\s*,\s*([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)\s*[,)]",
)
_MIDDLEWARE = re.compile(r"\b([A-Za-z_]\w*)\.Use\s*\(\s*([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)")
_ENGINE_FACTORY = re.compile(
    r"\b(?P<instance>[A-Za-z_]\w*)\s*:=\s*(?:(?:gin\.)?(?:New|Default))\s*\(",
)


def _likely_engine_calls(context, graph) -> int:
    """Add bounded, source-backed likely links from ``New``/``Default`` instances.

    Go's extractor records the selector call but does not run the compiler or
    type checker.  A variable created directly by Gin's documented factories
    is therefore useful, but not enough for a confirmed dispatch edge.  The
    resulting relation is deliberately `likely` and carries the factory and
    call-site evidence needed for review.
    """
    targets = [node for node in graph.nodes if node.kind == "METHOD" and node.id == "gin.Engine.Use"]
    if len(targets) != 1:
        return 0
    target = targets[0]
    calls_by_file: dict[str, list[object]] = {}
    for node in graph.nodes:
        if node.kind == "CALL_EXPR":
            rel = str(node.properties.get("file") or "").replace("\\", "/")
            if rel:
                calls_by_file.setdefault(rel, []).append(node)
    linked = 0
    for rel, text in source_files(Path(context.project_path), (".go",)):
        instances = {match.group("instance") for match in _ENGINE_FACTORY.finditer(text)}
        if not instances:
            continue
        for call in calls_by_file.get(rel, []):
            receiver = str(call.properties.get("receiver") or "")
            if receiver not in instances or str(call.properties.get("method_name") or "") != "Use":
                continue
            edge_id = f"plugin_gin__likely_engine_call__{call.id}__{target.id}"
            if any(edge.id == edge_id for edge in graph.edges):
                continue
            line = int(call.properties.get("line") or 1)
            graph.add_edge(Edge(
                id=edge_id, kind="CALLS", from_node=call.id, to_node=target.id,
                source="SUPPORT_PACK", confidence=0.82,
                evidence=[Evidence(file=rel, line=line, source="local-framework-pack", description=f"gin: {receiver} is created by New/Default and calls Use")],
                properties={
                    "framework": "gin", "support_pack_library": "gin",
                    "support_pack_id": "framework.go.gin", "support_pack_rule_id": "gin-local-engine-likely-call",
                    "resolver_hook_name": "gin_routes", "resolution_status": "framework_likely_factory_binding",
                    "confidence_status": "likely", "reason": "factory binding is explicit; full Go type checking was not run",
                    "test_call_site": rel.endswith("_test.go"),
                },
            ))
            if rel.endswith("_test.go"):
                call.properties.update({
                    "boundary": True, "boundary_category": "test",
                    "review_label": "Gin Engine call in test",
                })
            linked += 1
    return linked


def gin_routes(context, graph):
    """Record literal Gin route declarations and exact local handlers."""
    routes = 0
    for rel, text in source_files(Path(context.project_path), (".go",)):
        for match in _ROUTE.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            method, path = match.group(1), match.group(2)
            add_literal_route(
                graph, framework="gin", language="go", method=method,
                path=path, file=rel, line=line,
            )
            declaration = text[match.start(): text.find("\n", match.start()) if text.find("\n", match.start()) != -1 else len(text)]
            handler = _DIRECT_HANDLER.search(declaration)
            if handler:
                add_route(
                    graph, framework="gin", language="go", method=method,
                    path=path, handler=handler.group(1), file=rel, line=line,
                )
            routes += 1
        for match in _MIDDLEWARE.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            receiver = match.group(1)
            add_framework_candidate(
                graph, framework="gin", language="go",
                registration=f"{receiver}.Use (Engine_or_RouterGroup)",
                handler=match.group(2), file=rel, line=line,
            )
    linked = _likely_engine_calls(context, graph)
    plugin_result = result(graph, "framework.go.gin", "gin", routes)
    graph.metadata.setdefault("polyglot_framework_features", {}).setdefault("gin", {})["likely_local_engine_calls"] = linked
    return plugin_result
