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
    graph.metadata["identity"] = {
        "strategy": "path_qualified_sha1",
        "backward_compatible_node_ids": True,
        "annotated_nodes": len(graph.nodes),
    }
    return graph


def _language_for_file(file_path: str) -> str:
    suffix = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
    return {"py": "python", "js": "javascript", "jsx": "javascript", "ts": "typescript", "tsx": "typescript", "go": "go", "java": "java"}.get(suffix, "unknown")


def _workspace_name(project_root: str) -> str:
    return str(project_root).replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
