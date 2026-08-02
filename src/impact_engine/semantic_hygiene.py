"""Adapter between Impact Engine graphs and the portable hygiene layer."""
from __future__ import annotations

import gzip
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from impact_engine.models import GraphDocument
from project_semantics_hygiene import HygienePipeline, ProjectFile


_ROUTE_RE = re.compile(r"^(?:HTTP\s+)?(GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)\s+(.+)$", re.IGNORECASE)
_HYGIENE_SIDECAR_THRESHOLD = 20_000
_HYGIENE_SIDECAR_NAME = "project_hygiene.json.gz"


def build_pre_project_hygiene(inventory_data: dict[str, Any], project_path: str | Path) -> dict[str, Any]:
    """Classify project files/dependencies before extraction and resolution."""
    root = Path(project_path).resolve()
    report = HygienePipeline().run(
        files=_project_files(root, inventory_data),
        dependencies=_dependency_inputs(inventory_data),
        declared_dependencies=_declared_dependencies(inventory_data),
        local_modules=_local_modules(inventory_data),
        dev_dependencies=_dev_dependencies(inventory_data),
        graph=None,
        routes=[],
    )
    data = report.to_dict()
    data["stage"] = "pre"
    return data


def apply_post_project_hygiene(graph: GraphDocument, inventory_data: dict[str, Any], project_path: str | Path) -> GraphDocument:
    """Annotate a resolved graph with post-resolution hygiene metadata.

    This layer is intentionally non-semantic: it does not create inferred edges.
    It only classifies files, dependencies, routes, and existing graph nodes/edges
    so downstream impact queries can separate runtime signal from generated/dead
    code noise.
    """
    root = Path(project_path).resolve()
    files = _project_files(root, inventory_data)
    dependencies = _dependency_inputs(inventory_data)
    declared = _declared_dependencies(inventory_data)
    local_modules = _local_modules(inventory_data)
    routes = _route_inputs(graph)

    report = HygienePipeline().run(
        files=files,
        dependencies=dependencies,
        declared_dependencies=declared,
        local_modules=local_modules,
        dev_dependencies=_dev_dependencies(inventory_data),
        # GraphAnnotator only needs node/edge identity and file properties.
        # Passing GraphDocument avoids creating a second full graph-sized
        # dictionary (and its nested evidence/properties) during analysis.
        graph=graph,
        routes=routes,
    )

    data = report.to_dict()
    data["stage"] = "post"
    # Keep the complete report under the long-standing public key.  The
    # compatibility alias below used to serialize the same potentially large
    # annotation map a second time in every graph artifact.
    graph.metadata["post_project_hygiene"] = {
        "stage": "post",
        "summary": data.get("summary", {}),
    }
    graph.metadata["post_project_hygiene_status"] = "applied"
    # Backward-compatible canonical payload consumed by current CLI/tests.
    graph.metadata["project_hygiene"] = data
    graph.metadata["project_hygiene_status"] = "applied"
    return graph


def apply_project_hygiene(graph: GraphDocument, inventory_data: dict[str, Any], project_path: str | Path) -> GraphDocument:
    """Backward-compatible alias for post-resolution hygiene."""
    return apply_post_project_hygiene(graph, inventory_data, project_path)


def externalize_large_hygiene(graph: GraphDocument, *, threshold: int = _HYGIENE_SIDECAR_THRESHOLD) -> bool:
    """Move verbose hygiene annotations out of large canonical graph JSON.

    The sidecar is local, atomically replaced, and referenced from the graph.
    It retains the complete legacy report for explicit deep investigation while
    keeping normal graph/review loads proportional to the actual graph rather
    than to duplicated annotation prose.
    """
    hygiene = graph.metadata.get("project_hygiene") if isinstance(graph.metadata, dict) else None
    if not isinstance(hygiene, dict) or hygiene.get("storage"):
        return False
    node_annotations = hygiene.get("node_annotations") or []
    edge_annotations = hygiene.get("edge_annotations") or []
    if len(node_annotations) + len(edge_annotations) < threshold:
        return False
    root = Path(str(graph.metadata.get("project_path") or "")).expanduser()
    if not root.is_dir():
        return False
    destination = root / ".impact_engine" / _HYGIENE_SIDECAR_NAME
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    try:
        with os.fdopen(handle, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed:
            compressed.write(json.dumps(hygiene, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        os.replace(temporary_name, destination)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    compact = {key: value for key, value in hygiene.items() if key not in {"node_annotations", "edge_annotations"}}
    compact["storage"] = {
        "format": "gzip-json-v1",
        "path": f".impact_engine/{_HYGIENE_SIDECAR_NAME}",
        "node_annotations": len(node_annotations),
        "edge_annotations": len(edge_annotations),
    }
    graph.metadata["project_hygiene"] = compact
    graph.metadata["project_hygiene_storage"] = compact["storage"]
    return True


def _project_files(root: Path, inventory_data: dict[str, Any]) -> list[ProjectFile]:
    result: list[ProjectFile] = []
    for rel in inventory_data.get("files", []) or []:
        rel_str = str(rel).replace("\\", "/")
        content = None
        path = root / rel_str
        if path.is_file():
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")[:16384]
            except Exception:
                content = None
        result.append(ProjectFile(rel_str, content))
    return result


def _dependency_inputs(inventory_data: dict[str, Any]) -> list[tuple[str, str]]:
    languages = set(inventory_data.get("languages", []) or [])
    deps: list[tuple[str, str]] = []
    by_eco = inventory_data.get("external_imports_by_ecosystem", {}) or {}
    declared_by_eco = inventory_data.get("declared_dependencies_by_ecosystem", {}) or {}
    for ecosystem, names in by_eco.items():
        for name in names or []:
            deps.append((str(name), str(ecosystem)))
    for ecosystem, names in declared_by_eco.items():
        for name in names or []:
            deps.append((str(name), str(ecosystem)))
    if not deps:
        for name in inventory_data.get("external_imports", []) or []:
            deps.append((str(name), _guess_ecosystem(str(name), languages)))
        for name in inventory_data.get("declared_dependencies", []) or []:
            deps.append((str(name), _guess_ecosystem(str(name), languages)))
    seen = set()
    unique = []
    for item in deps:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def _guess_ecosystem(name: str, languages: set[str]) -> str:
    if name.startswith("@"):
        return "typescript" if "typescript" in languages else "javascript"
    if name.startswith("github.com/"):
        return "go"
    if name.startswith(("java.", "javax.", "org.", "com.")):
        return "java"
    if "python" in languages:
        return "python"
    if "typescript" in languages:
        return "typescript"
    if "javascript" in languages:
        return "javascript"
    if "go" in languages:
        return "go"
    if "java" in languages:
        return "java"
    return "python"


def _declared_dependencies(inventory_data: dict[str, Any]) -> dict[str, set[str]]:
    languages = set(inventory_data.get("languages", []) or [])
    declared_by_eco = inventory_data.get("declared_dependencies_by_ecosystem", {}) or {}
    if declared_by_eco:
        return {str(ecosystem): {str(dep) for dep in deps or []} for ecosystem, deps in declared_by_eco.items()}
    declared: dict[str, set[str]] = {}
    for dep in inventory_data.get("declared_dependencies", []) or []:
        ecosystem = _guess_ecosystem(str(dep), languages)
        declared.setdefault(ecosystem, set()).add(str(dep))
    return declared


def _local_modules(inventory_data: dict[str, Any]) -> dict[str, set[str]]:
    local_by_eco = inventory_data.get("local_modules_by_ecosystem", {}) or {}
    if local_by_eco:
        return {str(ecosystem): {str(module) for module in modules or []} for ecosystem, modules in local_by_eco.items()}
    languages = inventory_data.get("languages", []) or ["python"]
    modules = {str(m) for m in inventory_data.get("local_modules", []) or []}
    return {str(lang): set(modules) for lang in languages}


def _dev_dependencies(inventory_data: dict[str, Any]) -> dict[str, set[str]]:
    dev_by_eco = inventory_data.get("dev_dependencies_by_ecosystem", {}) or {}
    return {str(ecosystem): {str(dep) for dep in deps or []} for ecosystem, deps in dev_by_eco.items()}


def _route_inputs(graph: GraphDocument) -> list[tuple[str | None, str, str | None]]:
    routes: list[tuple[str | None, str, str | None]] = []
    for node in graph.nodes:
        if node.kind != "ROUTE" and not node.id.upper().startswith("HTTP "):
            continue
        raw = node.name or node.id
        match = _ROUTE_RE.match(raw)
        if not match:
            match = _ROUTE_RE.match(node.id)
        if match:
            routes.append((match.group(1).upper(), match.group(2), node.properties.get("file")))
        else:
            routes.append((None, raw, node.properties.get("file")))
    return routes
