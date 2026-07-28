"""Concise-review suppression rules.

Suppression only affects the projection.  No node or edge is removed from the
full GraphDocument.
"""
from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any


DEFAULT_SUPPRESSED_KINDS = {"ASSIGNMENT", "CALL_EXPR", "EXTERNAL_LIBRARY", "SUPPORT_PACK", "LIBRARY"}
BUILTIN_NAMES = {"len", "str", "int", "float", "bool", "dict", "list", "set", "tuple", "print", "range", "fetch"}


def node_file(node: Any) -> str | None:
    properties = getattr(node, "properties", {}) or {}
    return properties.get("file") or properties.get("path")


def is_boundary_node(node: Any) -> bool:
    properties = getattr(node, "properties", {}) or {}
    kind = str(getattr(node, "kind", "")).upper()
    role = str(properties.get("role") or properties.get("semantic_role") or properties.get("boundary_category") or "").lower()
    return bool(properties.get("boundary") or properties.get("public") or properties.get("api_boundary") or kind in {"ROUTE", "HTTP_ROUTE"} or role in {"api", "route", "queue", "database", "db", "http", "rpc", "package", "test"})


def is_test_node(node: Any) -> bool:
    properties = getattr(node, "properties", {}) or {}
    file_name = str(node_file(node) or "").lower()
    name = str(getattr(node, "name", "")).lower()
    parts = set(PurePosixPath(file_name).parts)
    return str(getattr(node, "kind", "")).upper() == "TEST" or bool(parts & {"test", "tests", "spec", "specs"}) or name.startswith(("test_", "test", "spec_", "spec."))


def suppression_reason(node: Any, *, allow_boundary: bool = False) -> str | None:
    properties = getattr(node, "properties", {}) or {}
    kind = str(getattr(node, "kind", "")).upper()
    name = str(getattr(node, "name", "")).strip().lower()
    file_name = str(node_file(node) or "").replace("\\", "/").lower()
    if kind == "CALL_EXPR" and not (allow_boundary and is_boundary_node(node)):
        return "technical call expression"
    if kind in DEFAULT_SUPPRESSED_KINDS and not (allow_boundary and is_boundary_node(node)):
        return f"default noise kind: {kind}"
    if properties.get("builtin") or name in BUILTIN_NAMES:
        return "built-in node"
    if properties.get("generated") or any(part in file_name for part in ("/generated/", "/dist/", "/build/", "/vendor/", "/node_modules/", "\\generated\\", "\\vendor\\")):
        return "generated/vendor dependency"
    if properties.get("support_pack_implementation"):
        return "support-pack implementation"
    if properties.get("unresolved_endpoint") or properties.get("resolution_status") in {"unresolved", "ambiguous"}:
        return "unresolved or ambiguous endpoint"
    return None


def is_actionable(node: Any) -> bool:
    return suppression_reason(node, allow_boundary=True) is None


def semantic_cluster(node: Any) -> str:
    properties = getattr(node, "properties", {}) or {}
    explicit = properties.get("semantic_cluster") or properties.get("cluster") or properties.get("semantic_role")
    if explicit:
        return str(explicit)
    file_name = str(node_file(node) or "").replace("\\", "/")
    parts = PurePosixPath(file_name).parts
    return str(parts[-2] if len(parts) > 1 else getattr(node, "kind", "unknown")).lower()
