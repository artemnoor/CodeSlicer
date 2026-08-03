"""Evidence-gated Express route extraction."""
from __future__ import annotations

import re
from pathlib import Path

from impact_engine.models import Edge, Evidence
from plugins.frameworks.polyglot_web_common import add_framework_candidate, add_literal_route, add_route, result, source_files


_ROUTE = re.compile(
    r"\b(?:app|router)\.(get|post|put|patch|delete|head|options)\s*\(\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)
_DIRECT_HANDLER = re.compile(
    r"\(\s*['\"][^'\"]+['\"]\s*,\s*(?:async\s+)?([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)?)\s*[,)]",
)
_MIDDLEWARE = re.compile(
    r"\b(app|router)\.use\s*\(\s*(?:['\"][^'\"]+['\"]\s*,\s*)?(?:async\s+)?([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)?)",
)
_LOCAL_REQUIRE = re.compile(
    r"\b(?:var|let|const)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*require\(\s*['\"](?P<path>\.{1,2}(?:/[^'\"]*)?)['\"]\s*\)",
)
_FACTORY_BINDING = re.compile(
    r"\b(?:var|let|const)\s+(?P<instance>[A-Za-z_$][\w$]*)\s*=\s*(?P<factory>[A-Za-z_$][\w$]*)\s*\(",
)


def _test_file(rel: str) -> bool:
    name = Path(rel).name.lower()
    return "test" in Path(rel).parts or name.endswith((".test.js", ".spec.js", "_test.js"))


def _likely_local_instance_calls(context, graph) -> int:
    """Connect source-backed local Express instances without overstating proof.

    JavaScript does not give the static extractor enough type information to
    claim that every ``app.use`` calls Express's implementation.  In a
    framework checkout, however, a local ``require('../')`` followed by
    ``const app = express()`` is strong local evidence.  We retain it as a
    *likely* edge (rather than a confirmed one), preserving both the useful
    cross-file review path and the dynamic-language limitation.
    """
    methods: dict[str, list[object]] = {}
    for node in graph.nodes:
        if node.kind == "METHOD" and str(node.properties.get("binding") or node.name):
            methods.setdefault(str(node.properties.get("binding") or node.name), []).append(node)
    call_nodes_by_file: dict[str, list[object]] = {}
    for node in graph.nodes:
        if node.kind == "CALL_EXPR":
            file_name = str(node.properties.get("file") or "").replace("\\", "/")
            if file_name:
                call_nodes_by_file.setdefault(file_name, []).append(node)

    linked = 0
    for rel, text in source_files(Path(context.project_path), (".js", ".mjs", ".cjs", ".ts", ".tsx")):
        factories = {match.group("name") for match in _LOCAL_REQUIRE.finditer(text)}
        instances = {
            match.group("instance")
            for match in _FACTORY_BINDING.finditer(text)
            if match.group("factory") in factories
        }
        if not instances:
            continue
        for call in call_nodes_by_file.get(rel, []):
            receiver = str(call.properties.get("receiver") or "")
            method_name = str(call.properties.get("method_name") or "")
            targets = methods.get(f"app.{method_name}", []) if receiver in instances else []
            if len(targets) != 1:
                continue
            target = targets[0]
            edge_id = f"plugin_express__likely_instance_call__{call.id}__{target.id}"
            if any(edge.id == edge_id for edge in graph.edges):
                continue
            line = int(call.properties.get("line") or 1)
            graph.add_edge(Edge(
                id=edge_id, kind="CALLS", from_node=call.id, to_node=target.id,
                source="SUPPORT_PACK", confidence=0.78,
                evidence=[Evidence(
                    file=rel, line=line, source="local-framework-pack",
                    description=(
                        f"express: {receiver} is created by a local require factory; "
                        f"{receiver}.{method_name} likely dispatches to the local Express method"
                    ),
                )],
                properties={
                    "framework": "express", "support_pack_library": "express",
                    "support_pack_id": "framework.javascript.express",
                    "support_pack_rule_id": "express-local-instance-likely-call",
                    "resolver_hook_name": "express_routes",
                    "resolution_status": "framework_likely_instance_binding",
                    "confidence_status": "likely",
                    "reason": "local CommonJS factory binding; JavaScript receiver type is dynamic",
                    "test_call_site": _test_file(rel),
                },
            ))
            if _test_file(rel):
                # A framework-resolved call site is still a CALL_EXPR in the
                # canonical graph. Mark only the explicit test call as a
                # review boundary so the projection can preserve its evidence
                # chain instead of discarding it as generic AST noise.
                call.properties.update({
                    "boundary": True, "boundary_category": "test",
                    "review_label": "Express application call in test",
                })
            linked += 1
    return linked


def express_routes(context, graph):
    """Record literal ``app/router.METHOD`` declarations.

    Inline callbacks are genuine local route declarations but do not have a
    canonical named method to attach.  They are intentionally represented as
    ROUTE nodes only; a ROUTE_HANDLES edge is reserved for an exact direct
    identifier in the source.
    """
    routes = 0
    for rel, text in source_files(Path(context.project_path), (".js", ".mjs", ".cjs", ".ts", ".tsx")):
        language = "typescript" if rel.endswith((".ts", ".tsx")) else "javascript"
        for match in _ROUTE.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            method, path = match.group(1), match.group(2)
            add_literal_route(
                graph, framework="express", language=language, method=method,
                path=path, file=rel, line=line,
            )
            declaration = text[match.start(): text.find("\n", match.start()) if text.find("\n", match.start()) != -1 else len(text)]
            handler = _DIRECT_HANDLER.search(declaration)
            if handler:
                add_route(
                    graph, framework="express", language=language, method=method,
                    path=path, handler=handler.group(1), file=rel, line=line,
                )
            routes += 1
        for match in _MIDDLEWARE.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            add_framework_candidate(
                graph, framework="express", language=language,
                registration=f"{match.group(1)}.use", handler=match.group(2), file=rel, line=line,
            )
    linked = _likely_local_instance_calls(context, graph)
    plugin_result = result(graph, "framework.javascript.express", "express", routes)
    graph.metadata.setdefault("polyglot_framework_features", {}).setdefault("express", {})["likely_local_instance_calls"] = linked
    return plugin_result
