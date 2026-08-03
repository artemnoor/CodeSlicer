"""Collision-safe deterministic graph identity helpers."""
from __future__ import annotations

import hashlib
import re


def stable_symbol_id(project_root: str, file_path: str, qualified_name: str, kind: str) -> str:
    """Build a path-qualified ID; the digest prevents unsafe path characters."""
    root = str(project_root).replace("\\", "/").rstrip("/")
    path = str(file_path).replace("\\", "/")
    if path.startswith(root):
        path = path[len(root):].lstrip("/")
    slug = re.sub(r"[^A-Za-z0-9_.:/-]+", "_", f"{path}:{qualified_name}").strip("_")
    digest = hashlib.sha1(f"{root}/{path}:{qualified_name}:{kind}".encode("utf-8")).hexdigest()[:12]
    return f"{kind.lower()}:{slug}:{digest}"


def annotate_stable_identities(graph, project_root: str):
    """Attach stable identities without changing legacy node IDs.

    Keeping ``Node.id`` backward compatible avoids breaking existing clients;
    new integrations can use ``properties.stable_id`` for cross-run joins.
    """
    for node in graph.nodes:
        props = node.properties or {}
        file_path = props.get("file") or props.get("path") or props.get("source_file") or "<external>"
        node.properties["stable_id"] = stable_symbol_id(project_root, str(file_path), node.id or node.name, node.kind)
        node.properties["canonical_identity"] = {
            "language": _language_for_file(str(file_path)),
            "workspace": _workspace_name(project_root),
            "module": node.properties.get("module") or str(node.properties.get("scope") or "").rsplit(".", 1)[0],
            "qualname": node.properties.get("scope") or node.id,
            "signature": node.properties.get("signature") or node.properties.get("param_order"),
            "location": {"file": str(file_path), "line": node.properties.get("line")},
        }
    # Normalization deliberately materializes unresolved endpoints as
    # EXTERNAL_LIBRARY nodes so every edge has a valid endpoint.  Once a
    # matching workspace declaration is present, that placeholder is not an
    # external library at all: it is a legacy alias for a local symbol.  Keep
    # it suppressed in concise views, but label it accurately for identity,
    # ranking and test-linking consumers.
    node_by_id = {node.id: node for node in graph.nodes}
    declarations_by_scope: dict[str, list] = {}
    for node in graph.nodes:
        if node.kind in {"EXTERNAL_LIBRARY", "CANONICAL_ALIAS"}:
            continue
        scope = str(node.properties.get("scope") or "")
        if scope:
            declarations_by_scope.setdefault(scope, []).append(node)
    local_aliases = 0
    for node in graph.nodes:
        canonical = node_by_id.get(str(node.properties.get("canonical_alias_of") or ""))
        if node.kind == "EXTERNAL_LIBRARY" and (node.properties.get("unresolved_endpoint") or node.properties.get("unresolved")):
            candidates = declarations_by_scope.get(node.id, [])
            if len(candidates) != 1:
                continue
            canonical = candidates[0]
            node.kind = "CANONICAL_ALIAS"
            node.properties["canonical_alias_of"] = canonical.id
        if node.kind != "CANONICAL_ALIAS" or canonical is None:
            continue
        node.properties["canonical_identity"]["origin"] = "workspace_alias"
        node.properties["canonical_identity"]["canonical_entity_id"] = canonical.id
        local_aliases += 1
    graph.metadata["identity"] = {
        "strategy": "path_qualified_sha1",
        "backward_compatible_node_ids": True,
        "annotated_nodes": len(graph.nodes),
        "workspace_aliases": local_aliases,
    }
    return graph


def _language_for_file(file_path: str) -> str:
    suffix = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
    return {"py": "python", "js": "javascript", "jsx": "javascript", "mjs": "javascript", "cjs": "javascript", "ts": "typescript", "tsx": "typescript", "mts": "typescript", "cts": "typescript", "go": "go", "java": "java", "cs": "csharp", "c": "cpp", "h": "cpp", "cc": "cpp", "cpp": "cpp", "cxx": "cpp", "hh": "cpp", "hpp": "cpp", "hxx": "cpp", "rs": "rust", "kt": "kotlin", "kts": "kotlin", "php": "php", "rb": "ruby", "html": "html", "htm": "html", "xhtml": "html", "css": "css", "scss": "css", "sass": "css", "less": "css", "vue": "vue", "svelte": "svelte", "astro": "astro"}.get(suffix, "unknown")


def _workspace_name(project_root: str) -> str:
    return str(project_root).replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
