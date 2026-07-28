"""Small, local framework rule helpers shared by C# packs.

Rules consume already extracted canonical nodes and source evidence. They do
not invent a chain when a type or endpoint cannot be found.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from impact_engine.models import Edge, Evidence, Node
from impact_engine.plugin_architecture.contracts import PluginResult


def _add(graph, edge_id, kind, source, target, file, line, *, confidence=1.0, relationship=None, **props):
    if not graph.get_node(source) or not graph.get_node(target):
        return
    if relationship:
        props["relationship"] = relationship
    graph.add_edge(Edge(edge_id, kind, source, target, source="SUPPORT_PACK", confidence=confidence, evidence=[Evidence(f"C# framework rule: {relationship or kind}", file=file, line=line, source="local-framework-pack")], properties={"support_pack_rule_id": edge_id, "framework_pattern": relationship or kind, **props}))


def _read_cs(root: Path):
    for path in root.rglob("*.cs"):
        if any(part in {"bin", "obj", "vendor", "generated"} for part in path.relative_to(root).parts):
            continue
        try:
            yield path.relative_to(root).as_posix(), path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue


def _simple_types(graph):
    return {node.name: node for node in graph.nodes if node.kind == "CLASS" and node.properties.get("language") == "csharp"}


def apply_aspnet(graph, root: Path) -> None:
    methods = [node for node in graph.nodes if node.kind == "METHOD" and node.properties.get("language") == "csharp"]
    types = _simple_types(graph)
    route_count = 0
    for rel, text in _read_cs(root):
        if "[Route" not in text and "MapGet" not in text and "MapPost" not in text and "MapPut" not in text and "MapDelete" not in text and "Client." not in text:
            continue
        lines = text.splitlines()
        for match in re.finditer(r"\b(MapGet|MapPost|MapPut|MapDelete|MapPatch)\s*\(\s*[\"']([^\"']+)[\"']\s*,\s*(?:async\s+)?(?:\([^)]*\)\s*=>\s*)?([A-Za-z_]\w*)", text):
            handler = next((node for node in methods if node.name == match.group(3)), None)
            if not handler:
                continue
            line = text.count("\n", 0, match.start()) + 1
            route_id = f"route:{match.group(1).lower()}:{match.group(2)}"
            graph.add_node(Node(route_id, "ROUTE", match.group(2), {"file": rel, "line": line, "language": "csharp", "http_method": match.group(1)[3:].upper(), "path": match.group(2), "boundary_category": "api", "confidence_status": "confirmed", "framework": "aspnetcore"}))
            _add(graph, f"route:{route_id}:{handler.id}", "ROUTE_HANDLES", route_id, handler.id, rel, line, relationship="minimal_api_route", confidence=.98, boundary_category="api", http_method=match.group(1)[3:].upper(), path=match.group(2))
            route_count += 1
        # Keep the class/attribute lookahead line-bounded. A dot-star across a
        # whole generated controller file can otherwise create catastrophic
        # backtracking in a regex fallback parser.
        class_route = re.search(r"\[\s*Route\s*\(\s*[\"']([^\"']+)[\"']\s*\)\s*\]\s*(?:[^\n]*\r?\n\s*){0,5}(?:public\s+)?(?:sealed\s+)?class\s+([A-Za-z_]\w*)", text)
        if class_route:
            controller = types.get(class_route.group(2)); prefix = class_route.group(1)
            if controller:
                for method in re.finditer(r"\[\s*(HttpGet|HttpPost|HttpPut|HttpDelete|HttpPatch)\s*(?:\(\s*[\"']([^\"']*)[\"']\s*\))?\s*\]\s*(?:[^\n]*\r?\n\s*){0,5}(?:(?:public|private|protected|internal|static|async|virtual|override|sealed|new|partial)\s+)*[\w<>,.?\[\]]+\s+([A-Za-z_]\w*)\s*\(", text):
                    handler = next((node for node in methods if node.name == method.group(3) and node.properties.get("owner") == controller.id), None); path = "/".join(item.strip("/") for item in (prefix, method.group(2) or "") if item) or "/"
                    if not handler:
                        continue
                    line = text.count("\n", 0, method.start()) + 1
                    route_id = f"route:{rel}:{method.group(1).lower()}:{path}"
                    composed = "[controller]" in path or "[action]" in path
                    resolved_path = path.replace("[controller]", controller.name[:-10].lower() if controller.name.lower().endswith("controller") else controller.name.lower()).replace("[action]", handler.name.lower())
                    graph.add_node(Node(route_id, "ROUTE", resolved_path, {"file": rel, "line": line, "language": "csharp", "http_method": method.group(1)[4:].upper(), "path": resolved_path, "raw_path": path, "handler_id": handler.id, "boundary_category": "api", "confidence_status": "likely" if composed else "confirmed", "framework": "aspnetcore"}))
                    _add(graph, f"route:{route_id}:{handler.id}", "ROUTE_HANDLES", route_id, handler.id, rel, line, relationship="controller_route", confidence=.72 if composed else .96, boundary_category="api", http_method=method.group(1)[4:].upper(), path=path, resolution_status="likely" if composed else "resolved_exact")
                    route_count += 1
        # Integration tests with a literal HttpClient path are direct local
        # contract evidence. They are intentionally separate from frontend
        # bridging and do not claim runtime route discovery.
        route_nodes = [node for node in graph.nodes if node.kind == "ROUTE"]
        test_nodes = [node for node in graph.nodes if node.kind == "TEST" and node.properties.get("file") == rel]
        for test in test_nodes:
            test_name = test.name.lower()
            for route in route_nodes:
                handler_name = str(route.properties.get("handler_id") or "").rsplit(".", 1)[-1].lower()
                route_path = str(route.properties.get("path") or "").lower()
                route_tail = route_path.rsplit("/", 1)[-1].strip("{}")
                if handler_name and handler_name not in test_name and route_tail and route_tail not in test_name:
                    continue
                method = str(route.properties.get("http_method") or "GET").lower()
                http_call = re.search(rf"\b(?:Client|HttpClient)\s*\.\s*{method}(?:Async|AsJsonAsync)?\s*\(\s*\$?[\"']([^\"']+)", text, flags=re.I)
                if not http_call:
                    continue
                call_path = http_call.group(1).replace("$", "")
                normalized_route = route_path.replace("{id:guid}", "{id}").replace("{id}", "")
                call_norm = "/" + call_path.strip("/").lower()
                route_norm = "/" + normalized_route.strip("/").lower()
                if not (call_norm.startswith(route_norm.rstrip("/")) or route_norm.startswith(call_norm.rstrip("/"))):
                    continue
                call_line = text.count("\n", 0, http_call.start()) + 1
                _add(graph, f"http-test:{test.id}:{route.id}", "HTTP_CALLS", test.id, route.id, rel, call_line, confidence=.96 if route.properties.get("confidence_status") == "confirmed" else .78, relationship="test_literal_http_call", boundary_category="api", http_method=route.properties.get("http_method"), path=call_path, resolution_status="resolved_exact" if route.properties.get("confidence_status") == "confirmed" else "likely")
    graph.metadata.setdefault("csharp_framework_features", {})["aspnetcore"] = {"status": "supported" if route_count else "limited", "routes": route_count, "review_usable": bool(route_count), "review_usable_features": ["literal_route", "controller_route", "literal_test_http_call"], "note": "Only literal method/path pairs are confirmed; composed routes remain likely."}


def apply_di(graph, root: Path) -> None:
    types = _simple_types(graph)
    registrations = 0
    for rel, text in _read_cs(root):
        for match in re.finditer(r"\b(AddSingleton|AddScoped|AddTransient)\s*<\s*([A-Za-z_]\w*)\s*,\s*([A-Za-z_]\w*)\s*>", text):
            interface, implementation = types.get(match.group(2)), types.get(match.group(3))
            if interface and implementation:
                line = text.count("\n", 0, match.start()) + 1
                _add(graph, f"di:{rel}:{line}", "DEPENDS_ON", interface.id, implementation.id, rel, line, confidence=.98, relationship="di_registration", lifetime=match.group(1)[3:].lower(), confidence_status="confirmed", boundary_category="service")
                registrations += 1
        for match in re.finditer(r"\b(GetRequiredService|GetService)\s*<\s*([A-Za-z_]\w*)\s*>", text):
            target = types.get(match.group(2))
            if target:
                line = text.count("\n", 0, match.start()) + 1
                graph.metadata.setdefault("csharp_unresolved_resolutions", []).append({"file": rel, "line": line, "type": match.group(2), "status": "likely", "reason": "service-provider runtime resolution"})
    graph.metadata.setdefault("csharp_framework_features", {})["di"] = {"status": "supported" if registrations else "limited", "registrations": registrations, "review_usable": bool(registrations), "review_usable_features": ["explicit_di_registration"], "note": "Explicit generic registrations are confirmed; factory/scanning/reflection resolution is not."}


def apply_mediatr(graph, root: Path) -> None:
    types = _simple_types(graph); handled = 0
    for node in list(graph.nodes):
        if node.kind != "CLASS" or node.properties.get("language") != "csharp":
            continue
        for relation in graph.metadata.get("csharp_base_relations", []):
            if relation.get("source") != node.id or not ("RequestHandler" in str(relation.get("base")) or "INotificationHandler" in str(relation.get("base"))):
                continue
            base = str(relation.get("base")); generic = re.search(r"<\s*([A-Za-z_]\w*)", base)
            request = types.get(generic.group(1)) if generic else None
            if request:
                _add(graph, f"mediatr:{node.id}:{request.id}", "DEPENDS_ON", node.id, request.id, node.properties.get("file", ""), int(node.properties.get("line", 1)), confidence=.9, relationship="handles_request", framework="mediatr", boundary_category="service", confidence_status="likely")
                handled += 1
    graph.metadata.setdefault("csharp_framework_features", {})["mediatr"] = {"status": "supported" if handled else "limited", "handlers": handled, "review_usable": bool(handled), "review_usable_features": ["generic_request_handler"], "note": "Generic handler declarations are mapped; runtime pipeline behaviors remain unresolved."}


def apply_efcore(graph, root: Path) -> None:
    types = _simple_types(graph); contexts = [node for node in graph.nodes if node.kind == "CLASS" and "DbContext" in node.name]
    relations = 0
    for rel, text in _read_cs(root):
        for match in re.finditer(r"\bDbSet\s*<\s*([A-Za-z_]\w*)\s*>\s+([A-Za-z_]\w*)", text):
            context = next((node for node in contexts if node.properties.get("file") == rel), None); entity = types.get(match.group(1))
            if context and entity:
                line = text.count("\n", 0, match.start()) + 1
                _add(graph, f"ef:dbset:{rel}:{line}", "DEPENDS_ON", context.id, entity.id, rel, line, confidence=.98, relationship="dbset_entity", framework="entityframework", boundary_category="database", confidence_status="confirmed")
                relations += 1
    graph.metadata.setdefault("csharp_framework_features", {})["entityframework"] = {"status": "supported" if relations else "limited", "dbset_relations": relations, "review_usable": bool(relations), "review_usable_features": ["dbset_entity_boundary"], "note": "DbSet<TEntity> is confirmed; migrations/generated model details require compiler/project evaluation."}


def apply_tests(graph, root: Path) -> None:
    tests = sum(1 for node in graph.nodes if node.kind == "TEST")
    graph.metadata.setdefault("csharp_framework_features", {})["dotnet_tests"] = {"status": "supported" if tests else "limited", "tests": tests, "review_usable": bool(tests), "review_usable_features": ["test_attribute"], "note": "xUnit/NUnit/MSTest attributes are evidence-backed; runtime fixture coverage is not inferred."}


def hook_result(graph, pack_id: str) -> PluginResult:
    graph.metadata.setdefault("plugin_provenance", []).append({"plugin_id": pack_id, "phase": "framework_rules", "source": "local"})
    return PluginResult(graph=graph, provenance={"pack_id": pack_id, "phase": "framework_rules"})
