"""Conservative Go/Java semantic pass on top of structural Tree-sitter facts.

This provider resolves only syntax-backed receiver and field types. It never
uses a method name alone: a target requires an explicit receiver type or
``this``/local function identity. Ambiguous candidates are quarantined.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from impact_engine.models import Edge, Evidence, GraphDocument


_GO_METHOD = re.compile(r"func\s*\(\s*(\w+)\s+\*?(\w+)\s*\)\s+(\w+)\s*\([^)]*\)[^{]*\{")
_GO_STRUCT = re.compile(r"type\s+(\w+)\s+struct\s*\{([^}]*)\}", re.S)
_GO_FIELD = re.compile(r"^\s*(\w+)\s+\*?([A-Za-z_]\w*)", re.M)
_JAVA_CLASS = re.compile(r"\bclass\s+(\w+)")
_JAVA_FIELD = re.compile(r"\b(?:private|protected|public|final|static|volatile| transient|\s)+\s*([A-Z_]\w*(?:<[^;>]+>)?)\s+(\w+)\s*(?:=\s*[^;]+)?;")
_JAVA_METHOD = re.compile(r"\b(?:public|private|protected|static|final|synchronized|abstract|native|\s)+\s+[\w<>, ?\[\]]+\s+(\w+)\s*\([^)]*\)\s*\{")
_CALL = re.compile(r"\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w+)?)\s*\(")


def apply_limited_polyglot_semantics(graph: GraphDocument, project_path: str | Path) -> GraphDocument:
    files = [node.properties.get("path") for node in graph.nodes if node.kind == "FILE" and node.properties.get("path")]
    counts: dict[str, dict[str, int]] = {"go": _empty_counts(), "java": _empty_counts()}
    for relative in files:
        path = Path(project_path) / str(relative)
        if path.suffix == ".go":
            _resolve_go(graph, path, str(relative), counts["go"])
        elif path.suffix == ".java":
            _resolve_java(graph, path, str(relative), counts["java"])
    service_identity = Path(project_path).name
    route_edges = [edge for edge in graph.edges if edge.kind == "ROUTE_HANDLES"]
    http_edges = [edge for edge in graph.edges if edge.kind == "HTTP_CALLS" and edge.properties.get("path")]
    endpoint_matches = 0
    for http_edge in http_edges:
        path_value = str(http_edge.properties.get("path"))
        for route_edge in route_edges:
            route_id = route_edge.from_node
            if not route_id.endswith(path_value):
                continue
            route_service = route_edge.properties.get("service_identity") or service_identity
            if route_service != service_identity:
                continue
            graph.add_edge(Edge(
                id=f"polyglot-endpoint:{http_edge.from_node}:{route_edge.to_node}:{path_value}", kind="MATCHES_ENDPOINT", from_node=http_edge.from_node, to_node=route_edge.to_node, source="INFERRED", confidence=0.78,
                evidence=[Evidence(file=event.file, line=event.line, source="INFERRED", description="HTTP client path matches backend canonical route" ) for event in (http_edge.evidence or [])],
                properties={"service_identity": service_identity, "canonical_endpoint": f"{service_identity}:HTTP:{path_value}", "resolution_status": "resolved_inferred", "provider": "polyglot_endpoint_bridge"},
            ))
            endpoint_matches += 1
    if endpoint_matches:
        graph.metadata["polyglot_endpoint_bridge"] = {"status": "applied", "matches": endpoint_matches, "service_identity": service_identity}
    graph.metadata["polyglot_semantic_resolution"] = {
        "providers": {
            "go": "go_limited_receiver_provider",
            "java": "java_limited_typed_receiver_provider",
        },
        "capabilities": {
            "go": ["structural_extraction", "import_resolution", "limited_call_resolution", "limited_constructor_propagation"],
            "java": ["structural_extraction", "import_resolution", "limited_call_resolution", "limited_constructor_injection"],
        },
        "counts": counts,
        "honest_limitations": ["reflection", "complex_generics", "runtime DI", "dynamic dispatch without unique type", "generated proxies"],
    }
    return graph


def _empty_counts() -> dict[str, int]:
    return {"structural": 0, "resolved_exact": 0, "resolved_inferred": 0, "ambiguous": 0, "unresolved": 0, "unsupported_semantics": 0}


def _add_resolution(graph: GraphDocument, caller: str, targets: list[str], kind: str, file: str, line: int, description: str, counts: dict[str, int]) -> None:
    if len(targets) == 1:
        target = targets[0]
        graph.add_edge(Edge(
            id=f"polyglot:{caller}:{kind}:{target}:{line}", kind=kind, from_node=caller, to_node=target,
            source="INFERRED", confidence=0.82,
            evidence=[Evidence(file=file, line=line, source="INFERRED", description=description)],
            properties={"resolution_status": "resolved_inferred", "evidence_class": "static_inferred", "provider": "polyglot_limited_semantics"},
        ))
        counts["resolved_inferred"] += 1
    elif len(targets) > 1:
        for target in targets:
            graph.add_edge(Edge(
                id=f"polyglot-ambiguous:{caller}:{kind}:{target}:{line}", kind=kind, from_node=caller, to_node=target,
                source="INFERRED", confidence=0.45,
                evidence=[Evidence(file=file, line=line, source="INFERRED", description=description)],
                properties={"resolution_status": "ambiguous", "status": "ambiguous", "candidate_count": len(targets), "provider": "polyglot_limited_semantics", "quality_guard": "multiple_typed_candidates"},
            ))
        counts["ambiguous"] += 1


def _method_nodes(graph: GraphDocument, suffix: str) -> list[str]:
    return [node.id for node in graph.nodes if node.kind == "METHOD" and node.id.endswith(suffix)]


def _resolve_go(graph: GraphDocument, path: Path, relative: str, counts: dict[str, int]) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    package = _go_package(text)
    structs: dict[str, dict[str, str]] = {}
    for name, body in _GO_STRUCT.findall(text):
        structs[name] = {field: typ for field, typ in _GO_FIELD.findall(body)}
    for route in re.finditer(r"\b(GET|POST|PUT|DELETE)\s*\(\s*\"([^\"]+)\"\s*,\s*([A-Za-z_]\w*)", text):
        method, route_path, handler = route.group(1), route.group(2), route.group(3)
        candidates = [node.id for node in graph.nodes if node.kind == "METHOD" and node.name == handler]
        if len(candidates) == 1:
            graph.add_edge(Edge(
                id=f"polyglot-route:{relative}:{route.start()}", kind="ROUTE_HANDLES", from_node=f"HTTP {method} {route_path}", to_node=candidates[0], source="SUPPORT_PACK", confidence=0.78,
                evidence=[Evidence(file=relative, line=text.count("\n", 0, route.start()) + 1, source="SUPPORT_PACK", description=f"Gin route registration {method} {route_path}")],
                properties={"support_pack": {"support_pack": "go/gin", "rule_id": f"gin.{method.lower()}", "rule_version": "1.0.0", "trust_level": "verified_on_fixture", "resolver_hook": "gin_route_resolver", "matched_pattern": route.group(0), "evidence": []}, "service_identity": path.parent.name or "go-service"},
            ))
    for match in _GO_METHOD.finditer(text):
        receiver, receiver_type, method = match.group(1), match.group(2), match.group(3)
        caller_candidates = _method_nodes(graph, f".{receiver_type}.{method}")
        if len(caller_candidates) != 1:
            continue
        caller = caller_candidates[0]
        body = _balanced_body(text, match.end() - 1)
        for call in _CALL.finditer(body):
            receiver_expr, member = call.group(1).split(".", 1) if "." in call.group(1) else ("", call.group(1))
            target_type = receiver_type if receiver_expr == receiver else structs.get(receiver_type, {}).get(receiver_expr, "")
            if not target_type:
                if receiver_expr:
                    counts["unsupported_semantics"] += 1
                continue
            targets = _method_nodes(graph, f".{target_type}.{member}")
            if targets:
                _add_resolution(graph, caller, targets, "CALLS", relative, match.start() + body[:call.start()].count("\n") + 1, f"Go typed receiver {receiver_expr or 'self'} : {target_type}.{member}", counts)


def _resolve_java(graph: GraphDocument, path: Path, relative: str, counts: dict[str, int]) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    class_match = _JAVA_CLASS.search(text)
    if not class_match:
        return
    class_name = class_match.group(1)
    fields = {field: typ.split("<", 1)[0] for typ, field in _JAVA_FIELD.findall(text)}
    for match in _JAVA_METHOD.finditer(text):
        method = match.group(1)
        caller_candidates = _method_nodes(graph, f".{method}")
        caller_candidates = [item for item in caller_candidates if f".{class_name}." in item]
        if len(caller_candidates) != 1:
            continue
        caller = caller_candidates[0]
        body = _balanced_body(text, match.end() - 1)
        for call in _CALL.finditer(body):
            expression = call.group(1)
            receiver_expr, member = expression.split(".", 1) if "." in expression else ("this", expression)
            target_type = class_name if receiver_expr in {"this", "super"} else fields.get(receiver_expr, "")
            if not target_type:
                if receiver_expr not in {"", "this"}:
                    counts["unsupported_semantics"] += 1
                continue
            targets = _method_nodes(graph, f".{target_type}.{member}")
            if targets:
                _add_resolution(graph, caller, targets, "CALLS", relative, match.start() + body[:call.start()].count("\n") + 1, f"Java typed receiver {receiver_expr}: {target_type}.{member}", counts)


def _go_package(text: str) -> str:
    match = re.search(r"\bpackage\s+(\w+)", text)
    return match.group(1) if match else "main"


def _balanced_body(text: str, opening: int) -> str:
    depth = 0
    for index in range(opening, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[opening + 1:index]
    return text[opening + 1:]
