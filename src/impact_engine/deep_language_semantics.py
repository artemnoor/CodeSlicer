"""Evidence-first local semantic resolution for JS and TypeScript.

This is deliberately smaller than a compiler.  It resolves only declarations
reachable through an explicit local import/re-export and direct call syntax.
That makes the resulting edge useful for impact analysis without turning a
same-name function elsewhere in a repository into a false positive.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from impact_engine.models import Edge, Evidence, GraphDocument


_IMPORT = re.compile(r"^\s*import\s+(?P<what>.+?)\s+from\s+['\"](?P<path>[^'\"]+)['\"]", re.M)
_REEXPORT = re.compile(r"^\s*export\s*\{(?P<what>[^}]+)\}\s*from\s*['\"](?P<path>[^'\"]+)['\"]", re.M)
# JavaScript and TypeScript projects commonly export arrow bindings rather
# than ``function`` declarations.  The parser already gives those bindings a
# METHOD node, but the semantic pass previously skipped their bodies entirely
# and made an otherwise explicit local import look unresolved.
_FUNCTION = re.compile(r"(?:export\s+)?(?:async\s+)?function\s+(?P<name>[A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{")
_BOUND_FUNCTION = re.compile(
    r"(?:export\s+)?(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)"
    r"(?:\s*:\s*[^=;\n]+)?\s*=\s*(?:async\s+)?"
    r"(?:function(?:\s+[A-Za-z_$][\w$]*)?\s*\([^)]*\)\s*\{|\([^)]*\)\s*=>|[A-Za-z_$][\w$]*\s*=>)"
)
_METHOD = re.compile(
    r"(?m)^\s*(?:public\s+|private\s+|protected\s+|static\s+|async\s+|readonly\s+|override\s+)*"
    r"(?P<name>[A-Za-z_$][\w$]*)\s*\([^)]*\)\s*(?::\s*[^\{=>\n]+)?\s*\{"
)
_CALL = re.compile(r"\b(?P<receiver>[A-Za-z_$][\w$]*)?(?:\.(?P<member>[A-Za-z_$][\w$]*))?\s*\(")
_SKIP = {"if", "for", "while", "switch", "catch", "return", "function", "await", "setTimeout", "fetch"}


def apply_js_ts_semantics(graph: GraphDocument, project_path: str | Path, language: str) -> GraphDocument:
    """Add exact local-import call edges for one JS-family language plugin."""
    root = Path(project_path)
    suffixes = {"javascript": {".js", ".jsx", ".mjs", ".cjs"}, "typescript": {".ts", ".tsx", ".mts", ".cts"}}[language]
    sources = _sources(graph, root, suffixes)
    symbols = _symbols(graph, sources)
    exports = _exports(sources)
    counts = {"resolved_exact": 0, "unresolved": 0, "ambiguous": 0}

    for rel, text in sources.items():
        imports = _imports(rel, text, sources, exports, symbols)
        for match in _callable_matches(text):
            name = match.group("name")
            callers = symbols.get((rel, name), [])
            if len(callers) != 1:
                continue
            body = _callable_body(text, match)
            base_line = text.count("\n", 0, match.start()) + 1
            for call in _CALL.finditer(body):
                raw = call.group(0).strip()
                receiver, member = call.group("receiver"), call.group("member")
                callee = member or receiver
                if not callee or callee in _SKIP or raw.startswith("function"):
                    continue
                # React hooks have a dedicated support pack which records
                # component/hook semantics with richer provenance.
                if member is None and callee.startswith("use"):
                    continue
                candidates: list[str] = []
                # ``foo()`` is exact only if ``foo`` is locally declared or
                # explicitly imported from a resolved local module.
                if member is None:
                    candidates = list(symbols.get((rel, callee), [])) + list(imports.get(callee, []))
                elif receiver == "this":
                    candidates = [item for (file_name, symbol), ids in symbols.items() if file_name == rel and symbol == callee for item in ids]
                if len(candidates) == 1 and candidates[0] != callers[0]:
                    line = base_line + body[:call.start()].count("\n")
                    _add_exact_call(graph, callers[0], candidates[0], rel, line, language, "explicit local import/declaration")
                    counts["resolved_exact"] += 1
                elif len(candidates) > 1:
                    counts["ambiguous"] += 1
                elif member is None and callee not in _SKIP:
                    counts["unresolved"] += 1

    graph.metadata.setdefault("deep_language_semantics", {})[language] = {
        "status": "supported",
        "provider": f"{language}_local_import_resolver",
        "counts": counts,
        "capabilities": ["local_import_resolution", "reexport_resolution", "direct_call_resolution"],
        "limitations": ["dynamic import", "prototype mutation", "runtime monkey patching", "overload/type narrowing"],
    }
    return graph


def _callable_matches(text: str):
    """Yield unique named function/arrow/method bodies in source order.

    The resolver deliberately requires a corresponding parser declaration
    below, so a permissive source regex cannot create a speculative edge.
    """
    seen: set[tuple[str, int]] = set()
    for pattern in (_FUNCTION, _BOUND_FUNCTION, _METHOD):
        for match in pattern.finditer(text):
            key = (match.group("name"), match.start())
            if key not in seen:
                seen.add(key)
                yield match


def _callable_body(text: str, match: re.Match[str]) -> str:
    """Return a block body, or the bounded expression of an arrow binding."""
    prefix = match.group(0).rstrip()
    if prefix.endswith("{"):
        return _body(text, match.end() - 1)
    # Expression arrows are a declaration with an explicit, single-statement
    # body.  Stop at the statement terminator rather than scanning into the
    # next declaration.
    end = text.find(";", match.end())
    return text[match.end() : end if end >= 0 else len(text)]


def _sources(graph: GraphDocument, root: Path, suffixes: set[str]) -> dict[str, str]:
    paths = {str(node.properties.get("file") or node.properties.get("path") or "").replace("\\", "/") for node in graph.nodes}
    result: dict[str, str] = {}
    for rel in paths:
        if not rel or Path(rel).suffix.lower() not in suffixes:
            continue
        try:
            result[rel] = (root / rel).read_text(encoding="utf-8")
        except OSError:
            continue
    return result


def _symbols(graph: GraphDocument, sources: dict[str, str]) -> dict[tuple[str, str], list[str]]:
    result: dict[tuple[str, str], list[str]] = {}
    for node in graph.nodes:
        rel = str(node.properties.get("file") or node.properties.get("path") or "").replace("\\", "/")
        if rel in sources and node.kind in {"METHOD", "FUNCTION", "TEST"}:
            result.setdefault((rel, node.name), []).append(node.id)
    return result


def _module_candidates(rel: str, raw: str, sources: dict[str, str]) -> list[str]:
    if raw.startswith("@/"):
        # ``@/`` is the conventional tsconfig baseUrl=src alias.  Only accept
        # a unique source candidate; ambiguity remains unresolved.
        tail = raw[2:]
        candidates = [path for path in sources if any(path.endswith("/src/" + tail + ext) or path.endswith("/src/" + tail + "/index" + ext) for ext in (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs"))]
        return candidates
    if not raw.startswith("."):
        return []
    base = (Path(rel).parent / raw).as_posix()
    extensions = (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs")
    return [candidate for candidate in sources if candidate in {base + ext for ext in extensions} or candidate in {base + "/index" + ext for ext in extensions}]


def _exports(sources: dict[str, str]) -> dict[tuple[str, str], tuple[str, str]]:
    result: dict[tuple[str, str], tuple[str, str]] = {}
    for rel, text in sources.items():
        for match in _REEXPORT.finditer(text):
            targets = _module_candidates(rel, match.group("path"), sources)
            if len(targets) != 1:
                continue
            for item in match.group("what").split(","):
                parts = re.split(r"\s+as\s+", item.strip())
                original, exported = parts[0].strip(), parts[-1].strip()
                result[(rel, exported)] = (targets[0], original)
    return result


def _imports(rel: str, text: str, sources: dict[str, str], exports: dict[tuple[str, str], tuple[str, str]], symbol_ids: dict[tuple[str, str], list[str]]) -> dict[str, list[str]]:
    symbols: dict[str, list[str]] = {}
    # Build from source text rather than names across the project: an import is
    # the required syntactic proof for an inter-file edge.
    for match in _IMPORT.finditer(text):
        targets = _module_candidates(rel, match.group("path"), sources)
        if len(targets) != 1:
            continue
        target = targets[0]
        entries = match.group("what").strip().strip("{}")
        for item in entries.split(","):
            parts = re.split(r"\s+as\s+", item.strip())
            origin, local = parts[0].strip(), parts[-1].strip()
            if not origin:
                continue
            resolved_target, resolved_name = exports.get((target, origin), (target, origin))
            symbols.setdefault(local, []).extend(symbol_ids.get((resolved_target, resolved_name), []))
    return symbols


def _body(text: str, opening: int) -> str:
    depth = 0
    for index in range(opening, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[opening + 1:index]
    return text[opening + 1:]


def _add_exact_call(graph: GraphDocument, caller: str, target: str, rel: str, line: int, language: str, description: str) -> None:
    # Framework packs add richer, framework-specific provenance (for example
    # React component-to-hook evidence).  Keep that attribution intact rather
    # than replacing it with a generic local-import edge for the same pair.
    if any(
        edge.kind == "CALLS" and edge.from_node == caller and edge.to_node == target
        and (edge.properties.get("support_pack_id") or edge.properties.get("support_pack_rule_id"))
        for edge in graph.edges
    ):
        return
    graph.add_edge(Edge(
        id=f"deep-{language}:call:{caller}:{target}:{line}", kind="CALLS", from_node=caller, to_node=target,
        source="EXTRACTED", confidence=.96,
        evidence=[Evidence(file=rel, line=line, source="local-semantic", description=f"{language} {description}")],
        properties={"provider": f"{language}_local_import_resolver", "resolution_status": "resolved_exact", "evidence_class": "explicit_local_import"},
    ))
