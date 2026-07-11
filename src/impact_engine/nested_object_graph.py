"""Adapter for nested object graph call resolution."""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from nested_object_graph_resolver import resolve_nested_object_graph

from impact_engine.models import Edge, Evidence, GraphDocument


def apply_nested_object_graph_resolution(graph: GraphDocument) -> GraphDocument:
    """Resolve multi-hop object/dict/provider receiver chains into CALLS edges."""

    facts = build_nested_object_graph_input(graph)
    if not facts.get("classes") or not facts.get("calls"):
        graph.metadata["nested_object_graph_resolver"] = {
            "status": "skipped",
            "reason": "requires classes and receiver call facts",
            "classes": len(facts.get("classes", [])),
            "calls": len(facts.get("calls", [])),
        }
        return graph

    result = resolve_nested_object_graph(facts)
    if result.get("status") != "ok":
        graph.metadata["nested_object_graph_resolver"] = {
            "status": "error",
            "errors": result.get("errors", []),
        }
        return graph

    added = 0
    for edge_data in result.get("edges", []):
        if _add_nested_edge(graph, edge_data):
            added += 1

    graph.metadata["nested_object_graph_resolver"] = {
        "status": "applied",
        "bindings": len(result.get("bindings", []) or []),
        "edges_added": added,
        "confirmed": len(result.get("confirmed", []) or []),
        "likely": len(result.get("likely", []) or []),
        "weak": len(result.get("weak", []) or []),
        "suspicious": len(result.get("suspicious", []) or []),
        "rejected": len(result.get("rejected", []) or []),
        "diagnostics": result.get("diagnostics", []),
        "unresolved": result.get("unresolved", []),
    }
    return graph


def build_nested_object_graph_input(graph: GraphDocument) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "classes": [],
        "methods": [],
        "constructor_params": [],
        "assignments": [],
        "field_bindings": [],
        "dict_bindings": [],
        "provider_bindings": [],
        "returns": [],
        "calls": [],
        "aliases": [],
        "options": {},
    }
    class_ids = _class_ids(graph)
    method_names_by_class: dict[str, set[str]] = {class_id: set() for class_id in class_ids}

    for node in graph.nodes:
        if node.kind != "METHOD":
            continue
        scope = str(node.properties.get("scope") or _strip_prefix(node.id, "method:"))
        owner = _owner_class(scope, class_ids)
        name = str(node.properties.get("name") or scope.rsplit(".", 1)[-1])
        if owner:
            method_names_by_class.setdefault(owner, set()).add(name)
            facts["methods"].append({"id": scope, "class": owner, "name": name, "params": node.properties.get("param_order", [])})
            if name == "__init__":
                for key, value in node.properties.items():
                    if key.startswith("param_type:"):
                        param = key.split(":", 1)[1]
                        facts["constructor_params"].append(
                            {
                                "class": owner,
                                "param": param,
                                "type": _canonical_type(str(value), class_ids),
                                "confidence": 0.95,
                                "evidence": [f"{scope}: {param}: {value}"],
                            }
                        )

    for class_id in sorted(class_ids):
        facts["classes"].append({"id": class_id, "name": class_id.rsplit(".", 1)[-1], "methods": sorted(method_names_by_class.get(class_id, set()))})

    for node in graph.nodes:
        if node.kind == "ASSIGNMENT":
            props = node.properties
            scope = str(props.get("scope") or "")
            target = props.get("target")
            value = props.get("value")
            if scope and target and value is not None:
                facts["assignments"].append(
                    {
                        "scope": scope,
                        "target": str(target),
                        "value": str(value),
                        "confidence": 0.90,
                        "evidence": [_node_evidence_text(node, f"{scope}: {target} = {value}")],
                    }
                )
        elif node.kind == "CALL_EXPR":
            props = node.properties
            scope = str(props.get("scope") or "")
            receiver = props.get("receiver")
            method = props.get("method_name")
            if scope and receiver and method:
                facts["calls"].append(
                    {
                        "scope": scope,
                        "receiver_chain": str(receiver),
                        "method": str(method),
                        "args": list(props.get("args", []) or []),
                    }
                )

    source_facts = _collect_python_source_facts(graph, class_ids)
    for key in ("constructor_params", "assignments", "field_bindings", "dict_bindings", "aliases", "calls"):
        facts[key].extend(source_facts.get(key, []))

    return _dedupe_facts(facts)


def _add_nested_edge(graph: GraphDocument, edge_data: dict[str, Any]) -> bool:
    status = str(edge_data.get("status", "weak"))
    if status not in {"confirmed", "likely", "weak"}:
        return False
    source = str(edge_data.get("from") or "")
    target = str(edge_data.get("to") or "")
    if not source or not target:
        return False
    evidence = [Evidence(description=str(item), source="INFERRED") for item in edge_data.get("evidence", []) or []]
    if not evidence:
        return False
    graph.add_edge(
        Edge(
            id=f"nested_object_graph__CALLS__{source}__{target}",
            kind="CALLS",
            from_node=source,
            to_node=target,
            source="INFERRED",
            confidence=float(edge_data.get("confidence", 0.0)),
            evidence=evidence,
            properties={
                "resolver": "nested_object_graph_resolver",
                "status": status,
                "warnings": edge_data.get("warnings", []),
            },
        )
    )
    return True


def _collect_python_source_facts(graph: GraphDocument, class_ids: set[str]) -> dict[str, list[dict[str, Any]]]:
    root_value = graph.metadata.get("project_path") or graph.metadata.get("path")
    if not root_value:
        return {}
    root = Path(str(root_value))
    if not root.exists():
        return {}
    output: dict[str, list[dict[str, Any]]] = {
        "constructor_params": [],
        "assignments": [],
        "field_bindings": [],
        "dict_bindings": [],
        "aliases": [],
        "calls": [],
    }
    for path in root.rglob("*.py"):
        try:
            rel_parts = path.relative_to(root).parts
        except ValueError:
            rel_parts = path.parts
        if any(part.startswith(".") or part in {"__pycache__", "venv", "env", ".venv"} for part in rel_parts):
            continue
        module = ".".join(path.relative_to(root).with_suffix("").parts)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except Exception:
            continue
        imports = _python_imports(tree, module)
        for class_node in [n for n in ast.iter_child_nodes(tree) if isinstance(n, ast.ClassDef)]:
            class_id = f"{module}.{class_node.name}"
            if class_id not in class_ids:
                class_id = _canonical_type(class_id, class_ids)
            for func in [n for n in class_node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
                scope = f"{class_id}.{func.name}"
                if func.name == "__init__":
                    output["constructor_params"].extend(_constructor_params_from_ast(func, class_id, imports, class_ids))
                for stmt in ast.walk(func):
                    if isinstance(stmt, ast.Assign):
                        _append_assignment_facts(stmt, scope, output, imports, class_ids)
                    elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
                        _append_assignment_fact(stmt.target, stmt.value, scope, output, imports, class_ids)
                    elif isinstance(stmt, ast.Call):
                        call_fact = _call_fact_from_ast(stmt, scope)
                        if call_fact:
                            output["calls"].append(call_fact)
    return output


def _constructor_params_from_ast(func: ast.FunctionDef | ast.AsyncFunctionDef, class_id: str, imports: dict[str, str], class_ids: set[str]) -> list[dict[str, Any]]:
    facts = []
    for arg in func.args.args:
        if arg.arg == "self" or arg.annotation is None:
            continue
        try:
            annotation = ast.unparse(arg.annotation)
        except Exception:
            continue
        target_type = _canonical_type(_primary_annotation_type(annotation, imports), class_ids)
        facts.append({"class": class_id, "param": arg.arg, "type": target_type, "confidence": 0.95, "evidence": [f"{class_id}.__init__: {arg.arg}: {annotation}"]})
    return facts


def _append_assignment_facts(
    stmt: ast.Assign,
    scope: str,
    output: dict[str, list[dict[str, Any]]],
    imports: dict[str, str],
    class_ids: set[str],
) -> None:
    for target in stmt.targets:
        _append_assignment_fact(target, stmt.value, scope, output, imports, class_ids)


def _append_assignment_fact(
    target: ast.AST,
    value: ast.AST,
    scope: str,
    output: dict[str, list[dict[str, Any]]],
    imports: dict[str, str],
    class_ids: set[str],
) -> None:
        try:
            target_text = ast.unparse(target)
            value_text = ast.unparse(value)
        except Exception:
            return
        output["assignments"].append({"scope": scope, "target": target_text, "value": value_text, "confidence": 0.90, "evidence": [f"{scope}: {target_text} = {value_text}"]})
        target_type = _assignment_value_type(value, imports, class_ids)
        if target_text.startswith("self.") and target_type and "." in scope:
            owner = scope.rsplit(".", 1)[0]
            output["field_bindings"].append(
                {
                    "owner_type": owner,
                    "field": target_text.removeprefix("self."),
                    "target_type": target_type,
                    "confidence": 0.90,
                    "evidence": [f"{scope}: {target_text} = {value_text}"],
                }
            )
        if isinstance(value, ast.Dict) and target_text.startswith("self."):
            entries: dict[str, str] = {}
            value_types: dict[str, str] = {}
            for key, item_value in zip(value.keys, value.values):
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    try:
                        key_name = str(key.value)
                        entries[key_name] = ast.unparse(item_value)
                        resolved_value_type = _assignment_value_type(item_value, imports, class_ids)
                        if resolved_value_type:
                            value_types[key_name] = resolved_value_type
                    except Exception:
                        pass
            if entries:
                fact = {"scope": scope, "target": target_text, "entries": entries, "confidence": 0.82, "evidence": [f"{scope}: {target_text} dict literal"]}
                if value_types:
                    fact["value_types"] = value_types
                output["dict_bindings"].append(fact)
        if (
            target_text != value_text
            and _is_alias_value(value)
            and (_looks_pathlike(target_text) and _looks_pathlike(value_text))
        ):
            output["aliases"].append({"scope": scope, "alias": target_text, "target": value_text, "confidence": 0.88, "evidence": [f"{scope}: {target_text} aliases {value_text}"]})


def _call_fact_from_ast(stmt: ast.Call, scope: str) -> dict[str, Any] | None:
    if not isinstance(stmt.func, ast.Attribute):
        return None
    try:
        receiver = ast.unparse(stmt.func.value)
    except Exception:
        return None
    return {"scope": scope, "receiver_chain": receiver, "method": stmt.func.attr, "args": [_safe_unparse(arg) for arg in stmt.args]}


def _python_imports(tree: ast.AST, module: str) -> dict[str, str]:
    imports: dict[str, str] = {}
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            source = node.module
            for alias in node.names:
                imports[alias.asname or alias.name] = f"{source}.{alias.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports[alias.asname or alias.name] = alias.name
    return imports


def _primary_annotation_type(annotation: str, imports: dict[str, str]) -> str:
    """Return the first concrete type from common Optional/Union spellings."""

    text = annotation.strip()
    text = text.replace("typing.Optional[", "Optional[")
    text = text.replace("typing.Union[", "Union[")
    candidates: list[str] = []
    if "|" in text:
        candidates = [part.strip() for part in text.split("|")]
    elif text.startswith("Optional[") and text.endswith("]"):
        candidates = [text[len("Optional[") : -1].strip()]
    elif text.startswith("Union[") and text.endswith("]"):
        candidates = [part.strip() for part in text[len("Union[") : -1].split(",")]
    else:
        candidates = [text]
    for candidate in candidates:
        clean = candidate.strip()
        if clean in {"None", "NoneType", "Any"}:
            continue
        return imports.get(clean, clean)
    return imports.get(text, text)


def _assignment_value_type(value: ast.AST, imports: dict[str, str], class_ids: set[str]) -> str | None:
    """Infer a target type from constructor/default-factory assignment values."""

    call = value if isinstance(value, ast.Call) else None
    if isinstance(value, ast.BoolOp) and isinstance(value.op, ast.Or):
        for item in value.values:
            inferred = _assignment_value_type(item, imports, class_ids)
            if inferred:
                return inferred
    if not call:
        return None
    call_name = _safe_unparse(call.func)
    if not call_name:
        return None
    resolved = imports.get(call_name, call_name)
    return _canonical_type(resolved, class_ids)


def _class_ids(graph: GraphDocument) -> set[str]:
    ids = set()
    for node in graph.nodes:
        if node.kind != "CLASS":
            continue
        ids.add(_strip_prefix(node.id, "class:"))
    return ids


def _owner_class(scope: str, class_ids: set[str]) -> str | None:
    candidates = [class_id for class_id in class_ids if scope == class_id or scope.startswith(class_id + ".")]
    return max(candidates, key=len) if candidates else None


def _canonical_type(value: str, class_ids: set[str]) -> str:
    clean = value.replace("'", "").replace('"', "")
    if clean in class_ids:
        return clean
    tail = clean.rsplit(".", 1)[-1]
    matches = [class_id for class_id in class_ids if class_id == clean or class_id.endswith("." + tail)]
    return matches[0] if len(matches) == 1 else clean


def _strip_prefix(value: str, prefix: str) -> str:
    return value[len(prefix) :] if value.startswith(prefix) else value


def _node_evidence_text(node: Any, fallback: str) -> str:
    file_name = node.properties.get("file")
    line = node.properties.get("line")
    if file_name and line:
        return f"{fallback} ({file_name}:{line})"
    return fallback


def _safe_unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def _looks_pathlike(value: str) -> bool:
    return value == "self" or "." in value or "[" in value


def _is_alias_value(value: ast.AST) -> bool:
    return isinstance(value, (ast.Name, ast.Attribute, ast.Subscript))


def _dedupe_facts(facts: dict[str, Any]) -> dict[str, Any]:
    for key, value in list(facts.items()):
        if not isinstance(value, list):
            continue
        seen = set()
        deduped = []
        for item in value:
            marker = repr(sorted(item.items())) if isinstance(item, dict) else repr(item)
            if marker in seen:
                continue
            seen.add(marker)
            deduped.append(item)
        facts[key] = deduped
    return facts
