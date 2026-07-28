"""Dependency-free, evidence-first C# structural extraction.

The provider deliberately does not invoke dotnet, restore packages, or fetch a
parser. It is a deterministic fallback that covers the syntax needed for a
bounded impact projection. Compiler/Roslyn binding can be added as a local
augmentation without changing these canonical IDs.
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from impact_engine.models import Edge, Evidence, GraphDocument, Node


_TYPE_RE = re.compile(r"\b(?:public|internal|private|protected|static|abstract|sealed|partial|new|file|readonly|unsafe|\s)*(class|interface|record|struct)\s+([A-Za-z_]\w*)(?:\s*<[^>{}]+>)?(?:\s*\([^)]*\))?(?:\s*:\s*([^\{]+))?\s*\{", re.MULTILINE)
_METHOD_RE = re.compile(r"(?:^|[;{}])\s*(?:public|private|protected|internal|static|virtual|override|abstract|sealed|async|extern|unsafe|new|partial|readonly|ref|out|in|[A-Za-z_][\w<>,.?\[\]]*\s+)*([A-Za-z_]\w*)\s*\(([^(){};]*)\)\s*(?:where\s+[^\{]+)?(?:\{|=>)", re.MULTILINE)
_CTOR_RE = re.compile(r"(?:^|[;{}])\s*(?:public|private|protected|internal|static)\s*([A-Za-z_]\w*)\s*\(([^(){};]*)\)\s*\{", re.MULTILINE)
_PROPERTY_RE = re.compile(r"(?:^|[;{}])\s*(?:public|private|protected|internal|static|virtual|override|sealed|readonly|required|new|\s)+([A-Za-z_]\w*(?:<[^>{}]+>)?(?:\[\])?)\s+([A-Za-z_]\w*)\s*\{\s*(?:get|set|init)\b", re.MULTILINE)
_USING_RE = re.compile(r"^\s*using\s+(?:static\s+)?(?:[A-Za-z_]\w*\s*=\s*)?([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*;", re.MULTILINE)
_NAMESPACE_RE = re.compile(r"\bnamespace\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*(?:;|\{)")
_CALL_RE = re.compile(r"\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)\s*\(")
_KEYWORDS = {"if", "for", "foreach", "while", "switch", "catch", "using", "lock", "nameof", "typeof", "return", "new", "when", "fixed", "checked", "unchecked", "base", "this"}
_BUILTINS = {"Assert", "Configure", "Get", "Set", "Add", "Remove", "ToString", "Equals", "GetHashCode", "WriteLine", "WriteAsync", "ReadLine", "Select", "Where", "Any", "First", "FirstOrDefault", "Single", "Count", "ToList", "ToArray", "Contains", "CreateScope", "Build", "Use", "MapControllers"}
_BUILTINS.update({"Ok", "BadRequest", "NotFound", "NoContent", "CreatedAtAction", "StatusCode", "Send", "Publish", "AnyAsync", "ToListAsync", "FirstAsync", "FirstOrDefaultAsync", "Include", "ThenInclude", "ConfigureAwait", "AddControllers", "AddDbContext", "AddHealthChecks", "AddOpenApi"})
_TEST_ATTRS = {"Fact", "Theory", "Test", "TestCase", "TestMethod", "DataTestMethod", "TestFixture"}


@dataclass
class _Type:
    name: str
    qualified: str
    node_id: str
    file: str
    line: int
    kind: str
    bases: tuple[str, ...]
    body_start: int
    body_end: int
    attributes: tuple[str, ...] = ()


@dataclass
class _Member:
    name: str
    node_id: str
    owner: _Type
    file: str
    line: int
    body: str
    kind: str
    parameters: tuple[str, ...] = ()
    attributes: tuple[str, ...] = ()


def _mask(text: str) -> str:
    chars = list(text)
    i = 0
    while i < len(chars):
        if text.startswith("//", i):
            end = text.find("\n", i)
            end = len(text) if end < 0 else end
            for j in range(i, end):
                chars[j] = " "
            i = end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            end = len(text) - 2 if end < 0 else end
            for j in range(i, min(len(chars), end + 2)):
                if chars[j] != "\n":
                    chars[j] = " "
            i = end + 2
        elif chars[i] in {'"', "'"}:
            quote = chars[i]
            j = i + 1
            while j < len(chars):
                if chars[j] == "\\":
                    chars[j] = " "
                    if j + 1 < len(chars) and chars[j + 1] != "\n":
                        chars[j + 1] = " "
                    j += 2
                    continue
                if chars[j] == quote:
                    break
                if chars[j] != "\n":
                    chars[j] = " "
                j += 1
            i = j + 1
        else:
            i += 1
    return "".join(chars)


def _matching_brace(text: str, opening: int) -> int:
    depth = 0
    for index in range(opening, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    return len(text)


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _evidence(description: str, file: str, line: int) -> list[Evidence]:
    return [Evidence(description=description, file=file, line=line, source="csharp-local-structural")]


def _is_generated_csharp(path: Path, text: str = "") -> bool:
    name = path.name.lower()
    parts = {part.lower() for part in path.parts}
    return name.endswith(".designer.cs") or "<auto-generated" in text[:1200].lower() or bool(parts & {"bin", "obj", "vendor", "generated"})


def _add_edge(graph: GraphDocument, edge_id: str, kind: str, source: str, target: str, file: str, line: int, *, confidence: float = 1.0, relationship: str | None = None, **properties) -> None:
    if not graph.get_node(source) or not graph.get_node(target):
        return
    if relationship:
        properties["relationship"] = relationship
    graph.add_edge(Edge(edge_id, kind, source, target, source="EXTRACTED", confidence=confidence, evidence=_evidence(f"C# {relationship or kind.lower()} evidence", file, line), properties=properties))


def _type_id(namespace: str, name: str) -> str:
    return f"class:{namespace + '.' if namespace else ''}{name}"


def _method_id(owner: str, name: str, kind: str = "method") -> str:
    return f"{kind}:{owner}.{name}"


def _parse_cs_file(root: Path, path: Path, graph: GraphDocument, types: list[_Type], members: list[_Member], file_texts: dict[str, str]) -> None:
    rel = _rel(root, path)
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        graph.metadata.setdefault("csharp_diagnostics", []).append({"code": "file_read_error", "file": rel, "message": str(exc), "status": "limited"})
        return
    generated = _is_generated_csharp(path, text)
    file_texts[rel] = text
    masked = _mask(text)
    file_id = f"file:{rel}"
    graph.add_node(Node(file_id, "FILE", path.name, {"file": rel, "language": "csharp", "extractor_id": "csharp-local-structural", "generated": generated, "actionable": not generated}))
    if generated:
        graph.metadata.setdefault("csharp_generated_files", []).append(rel)
        graph.metadata.setdefault("csharp_files", []).append(rel)
        return
    namespaces = list(_NAMESPACE_RE.finditer(masked))
    file_namespace = namespaces[0].group(1) if namespaces else ""
    module_id = f"module:{file_namespace or Path(rel).parent.as_posix().replace('/', '.') or Path(rel).stem}"
    graph.add_node(Node(module_id, "MODULE", file_namespace or Path(rel).stem, {"file": rel, "language": "csharp", "namespace": file_namespace, "line": _line(text, namespaces[0].start()) if namespaces else 1}))
    _add_edge(graph, f"declares:{module_id}:{file_id}", "DECLARES", module_id, file_id, rel, 1, relationship="module_file")
    for using in _USING_RE.finditer(masked):
        imported = using.group(1)
        ext = imported.split(".", 1)[0] in {"System", "Microsoft", "Newtonsoft", "Serilog", "MediatR", "FluentAssertions", "Xunit", "NUnit"}
        target = f"external:{imported}" if ext else f"module:{imported}"
        graph.add_node(Node(target, "EXTERNAL_LIBRARY" if ext else "MODULE", imported, {"external": ext, "actionable": False, "language": "csharp", "namespace": imported}))
        _add_edge(graph, f"imports:{file_id}:{target}", "IMPORTS", file_id, target, rel, _line(text, using.start()), confidence=1.0, relationship="using", external=ext)
    for match in _TYPE_RE.finditer(masked):
        namespace = file_namespace
        for candidate in namespaces:
            if candidate.start() <= match.start():
                namespace = candidate.group(1)
        kind, name, base_text = match.group(1), match.group(2), match.group(3) or ""
        qualified = f"{namespace}.{name}" if namespace else name
        opening = masked.find("{", match.start())
        ending = _matching_brace(masked, opening)
        attrs = tuple(re.findall(r"\[\s*([A-Za-z_]\w*)", text[max(0, text.rfind("\n", 0, match.start() - 1) - 600):match.start()]))
        # Keep generic base text intact for MediatR/EF rules; local inheritance
        # resolution below derives a simple name separately.
        base_items = tuple(item.strip() for item in re.split(r",\s*(?![^<]*>)", base_text) if item.strip())
        type_item = _Type(name, qualified, _type_id(namespace, name), rel, _line(text, match.start()), kind, base_items, opening, ending, attrs)
        types.append(type_item)
        graph.add_node(Node(type_item.node_id, "CLASS", name, {"file": rel, "line": type_item.line, "language": "csharp", "namespace": namespace, "qualified_name": qualified, "type_kind": kind, "attributes": list(attrs), "scope": "source"}))
        _add_edge(graph, f"declares:{module_id}:{type_item.node_id}", "DECLARES", module_id, type_item.node_id, rel, type_item.line, relationship="namespace_type")
        for base in type_item.bases:
            graph.metadata.setdefault("csharp_base_relations", []).append({"source": type_item.node_id, "base": base, "file": rel, "line": type_item.line, "kind": "interface" if base.startswith("I") else "base_class"})
        body = masked[opening + 1:ending]
        body_offset = opening + 1
        seen_members: set[tuple[str, int]] = set()
        for property_match in _PROPERTY_RE.finditer(body):
            prop = property_match.group(2)
            absolute = body_offset + property_match.start()
            member = _Member(prop, _method_id(qualified, prop, "property"), type_item, rel, _line(text, absolute), "", "property", (), ())
            if (prop, absolute) not in seen_members:
                seen_members.add((prop, absolute)); members.append(member)
                graph.add_node(Node(member.node_id, "METHOD", prop, {"file": rel, "line": member.line, "language": "csharp", "owner": type_item.node_id, "member_kind": "property", "scope": "source"}))
                _add_edge(graph, f"declares:{type_item.node_id}:{member.node_id}", "DECLARES", type_item.node_id, member.node_id, rel, member.line, relationship="property")
        for method_match in _METHOD_RE.finditer(body):
            name = method_match.group(1)
            # The expression deliberately accepts a preceding ``}`` or ``;``
            # to find members after another member.  ``match.start()`` then
            # points at that delimiter, often on the *previous* source line.
            # Store the captured method-name location instead: graph lines are
            # user-facing/Git 1-based lines and must anchor the actual member.
            absolute = body_offset + method_match.start(1)
            if name in _KEYWORDS or (name, absolute) in seen_members:
                continue
            expression_bodied = body[method_match.start():method_match.end()].rstrip().endswith("=>")
            opening_method = body_offset + body.find("{", method_match.start()) if not expression_bodied else body_offset + method_match.end() - 1
            ending_method = (masked.find(";", method_match.end()) if expression_bodied else _matching_brace(masked, opening_method))
            if ending_method < 0:
                ending_method = len(masked)
            attrs = tuple(re.findall(r"\[\s*([A-Za-z_]\w*)", text[max(0, text.rfind("\n", 0, absolute) - 500):absolute]))
            params = tuple(item.strip() for item in method_match.group(2).split(",") if item.strip())
            member_kind = "test" if set(attrs).intersection(_TEST_ATTRS) or "Tests" in type_item.name or type_item.name.endswith("Test") else "method"
            node_kind = "TEST" if member_kind == "test" else "METHOD"
            member_id = _method_id(qualified, name, "test" if node_kind == "TEST" else "method")
            member_body = text[method_match.end():ending_method] if expression_bodied else text[opening_method + 1:ending_method]
            member = _Member(name, member_id, type_item, rel, _line(text, absolute), member_body, member_kind, params, attrs)
            seen_members.add((name, absolute)); members.append(member)
            graph.add_node(Node(member_id, node_kind, name, {"file": rel, "line": member.line, "language": "csharp", "owner": type_item.node_id, "parameters": list(params), "attributes": list(attrs), "scope": "source", "framework_role": "test" if node_kind == "TEST" else "method"}))
            _add_edge(graph, f"declares:{type_item.node_id}:{member_id}", "DECLARES", type_item.node_id, member_id, rel, member.line, relationship="test" if node_kind == "TEST" else "member")
    graph.metadata.setdefault("csharp_files", []).append(rel)


def _parse_projects(root: Path, graph: GraphDocument) -> None:
    for path in root.rglob("*.csproj"):
        if any(part in {"bin", "obj", "vendor", "generated"} for part in path.relative_to(root).parts):
            continue
        rel = _rel(root, path); project_id = f"project:{rel}"
        graph.add_node(Node(project_id, "PROJECT", path.stem, {"file": rel, "language": "csharp", "project_file": rel}))
        text = path.read_text(encoding="utf-8", errors="ignore")
        for ref in re.findall(r"<ProjectReference\s+Include=[\"']([^\"']+)", text, flags=re.I):
            target = f"project:{Path(rel).parent.joinpath(ref).as_posix()}"
            graph.add_node(Node(target, "PROJECT", Path(ref).stem, {"file": Path(rel).parent.joinpath(ref).as_posix(), "language": "csharp", "project_reference": True}))
            _add_edge(graph, f"projectref:{project_id}:{target}", "DEPENDS_ON", project_id, target, rel, 1, relationship="project_reference", confidence=1.0, boundary_category="package")
        for package in re.findall(r"<PackageReference\s+Include=[\"']([^\"']+)", text, flags=re.I):
            target = f"external:nuget:{package}"
            graph.add_node(Node(target, "EXTERNAL_LIBRARY", package, {"external": True, "actionable": False, "package_manager": "nuget", "file": rel, "language": "csharp"}))
            _add_edge(graph, f"package:{project_id}:{target}", "DEPENDS_ON", project_id, target, rel, 1, relationship="package_reference", confidence=1.0, external=True, actionable=False)


def _resolve_structural_relations(graph: GraphDocument, types: list[_Type], members: list[_Member], file_texts: dict[str, str]) -> None:
    def base_name(value: str) -> str:
        return value.split("<", 1)[0].split(".")[-1].strip()

    by_name: dict[str, list[_Type]] = {}
    for item in types:
        by_name.setdefault(item.name, []).append(item)
        by_name.setdefault(item.qualified, []).append(item)
    for item in types:
        for base in item.bases:
            candidates = by_name.get(base_name(base), [])
            if candidates:
                _add_edge(graph, f"base:{item.node_id}:{candidates[0].node_id}", "DEPENDS_ON", item.node_id, candidates[0].node_id, item.file, item.line, confidence=1.0 if len(candidates) == 1 else .55, relationship="inherits" if not base.startswith("I") else "implements", inheritance_kind="class" if not base.startswith("I") else "interface")
    methods_by_name: dict[str, list[_Member]] = {}
    for member in members:
        if member.kind in {"method", "test"}:
            methods_by_name.setdefault(member.name, []).append(member)
    for member in members:
        if member.kind not in {"method", "test"}:
            continue
        caller_node = graph.get_node(member.node_id)
        if caller_node is None:
            continue
        for call in _CALL_RE.finditer(_mask(member.body)):
            raw_name = call.group(1); name = raw_name.split(".")[-1]
            if name in _KEYWORDS or name in _BUILTINS:
                continue
            candidates = methods_by_name.get(name, [])
            if len(candidates) == 1 and candidates[0].node_id != member.node_id:
                target = candidates[0]
                _add_edge(graph, f"call:{member.node_id}:{target.node_id}", "TESTS" if member.kind == "test" else "CALLS", member.node_id, target.node_id, member.file, member.line, confidence=.92, relationship="direct_call", resolution_status="resolved_exact", evidence_class="syntax_name_unique")
            elif not candidates and name not in {"Send", "Publish", "GetRequiredService", "GetService", "MapGet", "MapPost", "MapPut", "MapDelete"}:
                call_id = f"call:{member.node_id}:{raw_name}"
                graph.add_node(Node(call_id, "CALL_EXPR", raw_name, {"file": member.file, "line": member.line, "language": "csharp", "call_name": raw_name, "receiver": raw_name.rsplit(".", 1)[0] if "." in raw_name else None, "actionable": False, "resolution_status": "unresolved"}))
                _add_edge(graph, f"callsite:{member.node_id}:{call_id}", "CALLS", member.node_id, call_id, member.file, member.line, confidence=.3, relationship="unresolved_call", resolution_status="unresolved")


def extract_csharp_project(
    project_path: str,
    files: Iterable[str] | None = None,
    *,
    cancellation=None,
    progress_callback=None,
) -> GraphDocument:
    root = Path(project_path).resolve()
    graph = GraphDocument(metadata={"language": "csharp", "csharp_provider": {"status": "limited", "parser": "local_structural", "network": False}, "csharp_roslyn_available": bool(shutil.which("dotnet")), "csharp_coverage": {"status": "limited", "supported": ["namespace", "declarations", "members", "imports", "calls", "project_references"], "limited": ["DI", "ASP.NET", "MediatR", "EF Core", "test mapping", "overload resolution"], "unsupported": ["source generators", "reflection", "dynamic dispatch", "compiler diagnostics"]}})
    selected = set(str(item).replace("\\", "/") for item in files) if files is not None else None
    if selected is not None:
        # The pipeline already owns the pruned inventory. Do not recursively
        # walk the repository again for a full or incremental run.
        paths = [
            candidate for rel in selected
            if rel.lower().endswith(".cs")
            for candidate in [root / rel]
            if candidate.is_file()
            and not any(part in {"bin", "obj", "vendor", "generated"} for part in candidate.relative_to(root).parts)
        ]
    else:
        paths = [
            path for path in root.rglob("*.cs")
            if not any(part in {"bin", "obj", "vendor", "generated"} for part in path.relative_to(root).parts)
        ]
    types: list[_Type] = []; members: list[_Member] = []; texts: dict[str, str] = {}
    total_paths = len(paths)
    for index, path in enumerate(sorted(paths), start=1):
        if cancellation is not None:
            check = getattr(cancellation, "check", None)
            if callable(check):
                check()
            elif getattr(cancellation, "is_set", lambda: False)():
                raise TimeoutError("csharp extraction cancelled")
        try:
            _parse_cs_file(root, path, graph, types, members, texts)
        except Exception as exc:
            graph.metadata.setdefault("csharp_diagnostics", []).append({"code": "parse_error", "file": _rel(root, path), "message": str(exc), "status": "limited"})
        if progress_callback is not None:
            progress_callback(
                file=_rel(root, path),
                processed=index,
                total=total_paths,
                message=f"C#: {_rel(root, path)}",
            )
    _parse_projects(root, graph)
    _resolve_structural_relations(graph, types, members, texts)
    graph.metadata["csharp_counts"] = {"files": len(paths), "types": len(types), "members": len(members)}
    graph.metadata["csharp_diagnostics"] = graph.metadata.get("csharp_diagnostics", [])
    graph.metadata["csharp_feature_status"] = {"syntax": "supported", "project_references": "supported", "calls": "limited", "frameworks": "limited", "compiler_binding": "unavailable"}
    return graph
