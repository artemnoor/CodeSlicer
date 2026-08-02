"""Cheap, evidence-labelled discovery scopes for progressive analysis.

The index intentionally records only lexical, local import references.  It is
not a semantic graph and must never be used as a merge decision on its own.
Its single responsibility is to choose a bounded candidate file set for a
second, evidence-producing analysis pass.
"""
from __future__ import annotations

import ast
import re
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Iterable

from impact_engine.scope import iter_project_files


_SOURCE_SUFFIXES = {".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".go"}
_JS_IMPORT = re.compile(r"(?:from\s+|import\s*\(|require\s*\()\s*[\"']([^\"']+)[\"']")
_GO_IMPORT = re.compile(r"[\"']([^\"']+)[\"']")


def _normalise_relative(root: Path, value: str | Path) -> str | None:
    candidate = Path(value)
    try:
        if candidate.is_absolute():
            candidate = candidate.resolve().relative_to(root)
    except (OSError, ValueError):
        return None
    result = candidate.as_posix().removeprefix("./")
    return result or None


def _module_aliases(relative: str) -> set[str]:
    path = Path(relative)
    stem = path.with_suffix("")
    pieces = list(stem.parts)
    if pieces and pieces[-1] == "__init__":
        pieces.pop()
    if not pieces:
        return set()
    dotted = ".".join(pieces)
    # A package directory can be imported both as its canonical module and
    # through the package root.  This is intentionally conservative: aliases
    # only choose a *possible* scope, never create confirmed graph edges.
    return {dotted}


def _python_imports(source: str, relative: str) -> set[str]:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return set()
    current = list(Path(relative).with_suffix("").parts)
    if current and current[-1] != "__init__":
        current.pop()
    refs: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            refs.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # Absolute imports are already rooted at the project/package name;
            # only relative imports inherit the importing module's package.
            base = list(current) if node.level else []
            if node.level:
                base = base[: max(0, len(base) - node.level + 1)]
            module_parts = str(node.module or "").split(".") if node.module else []
            target = ".".join([*base, *module_parts]).strip(".")
            if target:
                refs.add(target)
            # ``from package import member`` may designate either an exported
            # name or a sibling module.  Including the latter is valid only at
            # discovery tier and helps choose the subsequent deep scope.
            for alias in node.names:
                member = alias.name
                if target and member != "*":
                    refs.add(f"{target}.{member}")
    return refs


def _relative_target(relative: str, raw: str, known_files: set[str]) -> set[str]:
    if not raw.startswith("."):
        return set()
    base = (Path(relative).parent / raw).as_posix()
    candidates = {base}
    if Path(base).suffix:
        candidates.add(Path(base).with_suffix("").as_posix())
    expanded: set[str] = set()
    for candidate in candidates:
        expanded.update({candidate, f"{candidate}.js", f"{candidate}.jsx", f"{candidate}.mjs", f"{candidate}.cjs", f"{candidate}.ts", f"{candidate}.tsx", f"{candidate}.py", f"{candidate}/__init__.py", f"{candidate}/index.js", f"{candidate}/index.ts"})
    return {candidate for candidate in expanded if candidate in known_files}


def _lexical_imports(path: Path, relative: str, known_files: set[str]) -> tuple[set[str], set[str]]:
    """Return (module references, relative file references), without execution."""
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set(), set()
    suffix = path.suffix.lower()
    if suffix == ".py":
        return _python_imports(source, relative), set()
    if suffix in {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}:
        values = set(_JS_IMPORT.findall(source))
        return set(), {target for value in values for target in _relative_target(relative, value, known_files)}
    if suffix == ".go":
        # Go package imports usually include module paths that cannot be
        # resolved without go.mod. Preserve only explicit local ./ imports.
        values = set(_GO_IMPORT.findall(source))
        return set(), {target for value in values for target in _relative_target(relative, value, known_files)}
    return set(), set()


def build_discovery_scope(
    project_path: str | Path,
    changed_files: Iterable[str | Path],
    *,
    max_files: int = 250,
    max_depth: int = 4,
) -> dict:
    """Build a fast broad candidate scope from local lexical imports.

    ``complete`` refers to the discovery traversal only.  A complete discovery
    traversal remains noncanonical because reflection, framework registration
    and dynamic imports are deliberately outside this cheap stage.
    """
    if max_files < 1:
        raise ValueError("max_files must be positive")
    root = Path(project_path).resolve()
    started = time.perf_counter()
    files = [
        path for path in iter_project_files(root)
        if path.is_file() and path.suffix.lower() in _SOURCE_SUFFIXES
    ]
    relatives = {path.relative_to(root).as_posix(): path for path in files}
    aliases: dict[str, set[str]] = defaultdict(set)
    for relative in relatives:
        for alias in _module_aliases(relative):
            aliases[alias].add(relative)

    adjacent: dict[str, set[str]] = defaultdict(set)
    for relative, path in relatives.items():
        modules, local_files = _lexical_imports(path, relative, set(relatives))
        targets = set(local_files)
        for module in modules:
            targets.update(aliases.get(module, ()))
        for target in targets:
            if target != relative:
                adjacent[relative].add(target)
                adjacent[target].add(relative)

    seeds = sorted({item for value in changed_files if (item := _normalise_relative(root, value))})
    selected: set[str] = set(seeds)
    queue = deque((item, 0) for item in seeds if item in relatives)
    traversal_truncated = False
    while queue:
        current, depth = queue.popleft()
        if depth >= max_depth:
            if adjacent.get(current):
                traversal_truncated = True
            continue
        for neighbour in sorted(adjacent.get(current, ())):
            if neighbour in selected:
                continue
            if len(selected) >= max_files:
                traversal_truncated = True
                queue.clear()
                break
            selected.add(neighbour)
            queue.append((neighbour, depth + 1))

    selected_existing = sorted(item for item in selected if item in relatives)
    missing_seeds = sorted(item for item in seeds if item not in relatives)
    return {
        "schema_version": "impact_engine.discovery_scope.v1",
        "mode": "lexical_broad_discovery",
        "files": selected_existing,
        "seed_files": seeds,
        "missing_seed_files": missing_seeds,
        "complete": not traversal_truncated,
        "max_files": max_files,
        "max_depth": max_depth,
        "file_count": len(selected_existing),
        "source_file_count": len(relatives),
        "static_local_links": sum(len(values) for values in adjacent.values()) // 2,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "limitations": [
            "lexical import discovery only; no runtime, reflection or framework registration resolution",
            "candidate files require focused semantic analysis before they can influence a review decision",
        ],
    }
