"""Adapter between Impact Engine graphs and the universal semantic binding layer."""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any, Iterable

from impact_engine.models import Edge, Evidence, GraphDocument, Node
from semantic_binding.facts import FactSet
from semantic_binding.integration import semantic_result_to_graph_edges
from semantic_binding.models import (
    AssignmentFact,
    CallFact,
    ClassFact,
    DecoratorFact,
    FunctionFact,
    ImportFact,
    Recipe,
    ReturnFact,
    Symbol,
)
from semantic_binding.resolver import SemanticResolver


_SKIP_DIRS = {
    ".git", ".venv", "venv", "env", "__pycache__", "node_modules", "dist",
    "build", "coverage", "external_tools", ".impact_engine",
}
_JS_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx"}
_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head"}


def _clean_literal(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"', "`"}:
        return text[1:-1]
    return text


def _split_call_name(call_name: str) -> tuple[str | None, str | None, str | None]:
    if "." not in call_name:
        return call_name, None, None
    receiver, method = call_name.rsplit(".", 1)
    return None, receiver, method


def _node_qname(node: Node) -> str:
    scope = node.properties.get("scope")
    if scope:
        return str(scope)
    for prefix in ("method:", "class:", "module:"):
        if node.id.startswith(prefix):
            return node.id.split(":", 1)[1]
    return node.name or node.id


def _module_from_file(root: Path, file_path: Path) -> str:
    try:
        rel = file_path.relative_to(root)
    except ValueError:
        rel = file_path
    return ".".join(rel.with_suffix("").parts)


def _iter_project_files(root: Path, suffixes: set[str]) -> Iterable[Path]:
    if root.is_file():
        if root.suffix in suffixes:
            yield root
        return
    from impact_engine.scope import iter_project_files
    for path in iter_project_files(root):
        if not path.is_file() or path.suffix not in suffixes:
            continue
        if any(part in _SKIP_DIRS or part.startswith(".") for part in path.relative_to(root).parts):
            continue
        yield path


def default_semantic_recipes() -> list[Recipe]:
    return [
        Recipe(
            id="builtin.fastapi_router_object_flow",
            type="object_graph",
            constructor="APIRouter",
            prefix_kwarg="prefix",
            include_method="include_router",
            decorator_methods=sorted(_HTTP_METHODS),
        ),
        Recipe(
            id="builtin.http_endpoint_sink_flow",
            type="endpoint_sink",
            sink_functions=[
                "fetch",
                "axios.get",
                "axios.post",
                "axios.put",
                "axios.patch",
                "axios.delete",
                "axios.request",
                "client.get",
                "client.post",
                "client.put",
                "client.patch",
                "client.delete",
                "http.get",
                "http.post",
                "http.put",
                "http.patch",
                "http.delete",
            ],
            wrapper_functions=["getJson", "postJson", "putJson", "patchJson", "deleteJson"],
            method_by_wrapper={
                "getJson": "GET",
                "postJson": "POST",
                "putJson": "PUT",
                "patchJson": "PATCH",
                "deleteJson": "DELETE",
            },
        ),
    ]


def graph_to_semantic_facts(graph: GraphDocument) -> FactSet:
    facts = FactSet()
    seen: set[str] = set()

    def add_once(bucket: list[Any], item: Any) -> None:
        key = f"{type(item).__name__}:{getattr(item, 'id', None)}:{getattr(item, 'file', None)}:{getattr(item, 'line', None)}"
        if key in seen:
            return
        seen.add(key)
        bucket.append(item)

    for node in graph.nodes:
        props = node.properties
        file_name = props.get("file") or props.get("path")
        line = props.get("line")
        qname = _node_qname(node)
        if node.kind in {"FUNCTION", "METHOD"}:
            params = list(props.get("param_order", []))
            add_once(facts.symbols, Symbol(node.name, qname, "function", file_name, line))
            add_once(facts.functions, FunctionFact(node.name, qname, params, file_name, line))
            for decorator in props.get("decorators", []):
                parsed = _parse_decorator(str(decorator), qname, file_name, line)
                if parsed:
                    add_once(facts.decorators, parsed)
        elif node.kind == "CLASS":
            add_once(facts.symbols, Symbol(node.name, qname, "class", file_name, line))
            add_once(facts.classes, ClassFact(node.name, qname, [], file_name, line))
        elif node.kind == "MODULE":
            for alias, target in dict(props.get("import_aliases", {})).items():
                module, name = _split_import_target(str(target))
                add_once(facts.imports, ImportFact(module=module, name=name, alias=str(alias), file=file_name, line=line))
        elif node.kind == "ASSIGNMENT":
            call_name = props.get("call_name")
            value_kind = "construct" if call_name and str(call_name).split(".")[-1][:1].isupper() else "symbol"
            add_once(
                facts.assignments,
                AssignmentFact(
                    target=str(props.get("target") or node.name),
                    value=_clean_literal(call_name or props.get("value")),
                    value_kind=value_kind,
                    caller=str(props.get("scope") or ""),
                    kwargs={k: _clean_literal(v) for k, v in dict(props.get("keyword_args", {})).items()},
                    file=file_name,
                    line=line,
                ),
            )
        elif node.kind == "CALL_EXPR":
            call_name = str(props.get("call_name") or node.name)
            function, receiver, method = _split_call_name(call_name)
            add_once(
                facts.calls,
                CallFact(
                    caller=str(props.get("scope") or ""),
                    function=function,
                    receiver=receiver,
                    method=method,
                    args=[_clean_literal(v) for v in props.get("args", [])],
                    kwargs={k: _clean_literal(v) for k, v in dict(props.get("keyword_args", {})).items()},
                    file=file_name,
                    line=line,
                ),
            )

    root = graph.metadata.get("path")
    if root:
        root_path = Path(str(root))
        if root_path.exists():
            _add_python_source_facts(root_path, facts, add_once)
            _add_js_source_facts(root_path, facts, add_once)

    facts.files = sorted({str(item) for item in facts.files})
    return facts


def apply_semantic_resolution(graph: GraphDocument, recipes: list[Recipe] | None = None) -> GraphDocument:
    facts = graph_to_semantic_facts(graph)
    active_recipes = list(recipes or default_semantic_recipes())
    result = SemanticResolver(facts, active_recipes).resolve()
    for edge_dict in semantic_result_to_graph_edges(result):
        if edge_dict.get("kind") not in {"ROUTE_HANDLES", "HTTP_CALLS", "MATCHES_ENDPOINT"}:
            continue
        _add_semantic_edge(graph, edge_dict)
    graph.metadata["semantic_binding_layer"] = {
        "status": "applied",
        "facts": {
            "symbols": len(facts.symbols),
            "assignments": len(facts.assignments),
            "calls": len(facts.calls),
            "decorators": len(facts.decorators),
            "returns": len(facts.returns),
        },
        "diagnostics": result.diagnostics,
    }
    return graph


def _add_semantic_edge(graph: GraphDocument, edge_dict: dict[str, Any]) -> None:
    source = str(edge_dict["from_node"])
    target = str(edge_dict["to_node"])
    if source.startswith("HTTP "):
        graph.add_node(Node(id=source, kind="ROUTE", name=source, properties={"semantic_layer": True}))
    if target.startswith("HTTP "):
        graph.add_node(Node(id=target, kind="ROUTE", name=target, properties={"semantic_layer": True}))
    evidence = [
        Evidence(
            description=str(ev.get("description", "semantic binding evidence")),
            file=ev.get("file"),
            line=ev.get("line"),
            source="INFERRED",
        )
        for ev in edge_dict.get("evidence", [])
    ]
    graph.add_edge(
        Edge(
            id=str(edge_dict["id"]),
            kind=str(edge_dict["kind"]),
            from_node=source,
            to_node=target,
            source=str(edge_dict.get("source", "INFERRED")),
            confidence=float(edge_dict.get("confidence", 0.8)),
            evidence=evidence,
            properties=dict(edge_dict.get("properties", {})),
        )
    )


def _split_import_target(target: str) -> tuple[str, str | None]:
    if "." not in target:
        return target, None
    module, name = target.rsplit(".", 1)
    return module, name


def _parse_decorator(text: str, target: str, file_name: Any, line: Any) -> DecoratorFact | None:
    match = re.match(r"^@?(?P<receiver>[\w.]+)\.(?P<method>\w+)\((?P<args>.*)\)$", text.strip())
    if not match:
        return None
    args_text = match.group("args").strip()
    args = []
    if args_text:
        first = args_text.split(",", 1)[0].strip()
        if "=" not in first:
            args.append(_clean_literal(first))
    return DecoratorFact(
        target=target,
        decorator=text,
        receiver=match.group("receiver"),
        method=match.group("method"),
        args=args,
        file=file_name,
        line=line,
    )


def _add_python_source_facts(root: Path, facts: FactSet, add_once: Any) -> None:
    for path in _iter_project_files(root, {".py"}):
        rel = path.relative_to(root).as_posix() if path != root else path.name
        facts.files.append(rel)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except Exception:
            continue
        module = _module_from_file(root, path)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qname = f"{module}.{node.name}"
                params = [arg.arg for arg in node.args.args if arg.arg != "self"]
                add_once(facts.functions, FunctionFact(node.name, qname, params, rel, node.lineno))
                add_once(facts.symbols, Symbol(node.name, qname, "function", rel, node.lineno))
                for dec in node.decorator_list:
                    try:
                        parsed = _parse_decorator("@" + ast.unparse(dec), qname, rel, node.lineno)
                    except Exception:
                        parsed = None
                    if parsed:
                        add_once(facts.decorators, parsed)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    _add_python_assignment(node, target, module, rel, facts, add_once)
            elif isinstance(node, ast.Call):
                _add_python_call(node, module, rel, facts, add_once)


def _add_python_assignment(node: ast.Assign, target: ast.AST, module: str, rel: str, facts: FactSet, add_once: Any) -> None:
    try:
        target_text = ast.unparse(target)
        value_text = ast.unparse(node.value)
    except Exception:
        return
    kwargs = {}
    value = value_text
    value_kind = "symbol"
    if isinstance(node.value, ast.Call):
        try:
            value = ast.unparse(node.value.func)
        except Exception:
            value = value_text
        value_kind = "construct" if str(value).split(".")[-1][:1].isupper() else "call"
        for kw in node.value.keywords:
            if kw.arg:
                kwargs[kw.arg] = _clean_literal(ast.unparse(kw.value))
    add_once(
        facts.assignments,
        AssignmentFact(target_text, _clean_literal(value), value_kind, rel, node.lineno, module, kwargs=kwargs),
    )


def _add_python_call(node: ast.Call, module: str, rel: str, facts: FactSet, add_once: Any) -> None:
    try:
        call_name = ast.unparse(node.func)
    except Exception:
        return
    function, receiver, method = _split_call_name(call_name)
    kwargs = {kw.arg: _clean_literal(ast.unparse(kw.value)) for kw in node.keywords if kw.arg}
    args = [_clean_literal(ast.unparse(arg)) for arg in node.args]
    add_once(facts.calls, CallFact(module, function, receiver, method, args, kwargs, rel, node.lineno))


def _add_js_source_facts(root: Path, facts: FactSet, add_once: Any) -> None:
    for path in _iter_project_files(root, _JS_EXTENSIONS):
        rel = path.relative_to(root).as_posix() if path != root else path.name
        facts.files.append(rel)
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        _scan_js_imports(text, rel, facts, add_once)
        for name, params, body, line in _iter_js_functions(text):
            add_once(facts.functions, FunctionFact(name, name, params, rel, line))
            add_once(facts.symbols, Symbol(name, name, "function", rel, line))
            _scan_js_body(name, body, rel, line, facts, add_once)


def _scan_js_imports(text: str, rel: str, facts: FactSet, add_once: Any) -> None:
    for match in re.finditer(r"import\s+\{(?P<names>[^}]+)\}\s+from\s+['\"](?P<module>[^'\"]+)['\"]", text):
        module = match.group("module")
        for raw in match.group("names").split(","):
            item = raw.strip()
            if not item:
                continue
            if " as " in item:
                name, alias = [part.strip() for part in item.split(" as ", 1)]
            else:
                name = alias = item
            add_once(facts.imports, ImportFact(module, name, alias, rel, _line_for_offset(text, match.start())))


def _iter_js_functions(text: str) -> Iterable[tuple[str, list[str], str, int]]:
    pattern = re.compile(r"(?:export\s+)?(?:async\s+)?function\s+(?P<name>\w+)\s*\((?P<params>[^)]*)\)\s*\{")
    for match in pattern.finditer(text):
        start = match.end() - 1
        end = _matching_brace(text, start)
        if end <= start:
            continue
        params = [p.strip().split(":")[0].strip() for p in match.group("params").split(",") if p.strip()]
        yield match.group("name"), params, text[start + 1:end], _line_for_offset(text, match.start())


def _scan_js_body(function: str, body: str, rel: str, base_line: int, facts: FactSet, add_once: Any) -> None:
    for match in re.finditer(r"(?P<callee>\b\w+(?:\.\w+)?)\s*\((?P<args>[^()]*)\)", body):
        callee = match.group("callee")
        if callee in {"if", "for", "while", "switch", "return", "function"}:
            continue
        function_name, receiver, method = _split_call_name(callee)
        args = [_clean_literal(arg.strip()) for arg in _split_args(match.group("args")) if arg.strip()]
        kwargs = _extract_js_options(args[1] if len(args) > 1 else "")
        add_once(facts.calls, CallFact(function, function_name, receiver, method, args, kwargs, rel, base_line + body[:match.start()].count("\n")))

    for match in re.finditer(r"return\s+\{(?P<keys>[^}]+)\}", body, re.DOTALL):
        object_keys: dict[str, str] = {}
        for raw in match.group("keys").split(","):
            item = raw.strip()
            if not item:
                continue
            if ":" in item:
                key, value = [part.strip() for part in item.split(":", 1)]
            else:
                key = value = item
            object_keys[key] = value
        if object_keys:
            add_once(facts.returns, ReturnFact(function, value_kind="object", object_keys=object_keys, file=rel, line=base_line + body[:match.start()].count("\n")))

    for match in re.finditer(r"const\s+\{(?P<keys>[^}]+)\}\s*=\s*(?P<fn>\w+)\s*\(\s*\)", body):
        for raw in match.group("keys").split(","):
            key = raw.strip()
            if key:
                add_once(facts.assignments, AssignmentFact(key, f"{match.group('fn')}()", "destructure", rel, base_line + body[:match.start()].count("\n"), function, key=key))


def _matching_brace(text: str, start: int) -> int:
    depth = 0
    in_quote: str | None = None
    escape = False
    for index in range(start, len(text)):
        ch = text[index]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if in_quote:
            if ch == in_quote:
                in_quote = None
            continue
        if ch in {"'", '"', "`"}:
            in_quote = ch
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _split_args(text: str) -> list[str]:
    result: list[str] = []
    current: list[str] = []
    depth = 0
    quote: str | None = None
    for ch in text:
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
        if ch == "," and depth == 0:
            result.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        result.append("".join(current).strip())
    return result


def _extract_js_options(text: str) -> dict[str, Any]:
    match = re.search(r"method\s*:\s*['\"](?P<method>\w+)['\"]", text)
    return {"method": match.group("method")} if match else {}


def _line_for_offset(text: str, offset: int) -> int:
    return text[:offset].count("\n") + 1
