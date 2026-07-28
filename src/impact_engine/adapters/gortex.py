"""Local GraphML importer for the Gortex knowledge graph.

Gortex owns its index and daemon.  CodeSlicer deliberately consumes only an
explicit GraphML export created by the user with ``gortex export --format
graphml``.  This avoids hidden localhost calls, keeps the graph provenance
clear, and never lets Gortex relationships affect CodeSlicer review ranking.
"""
from __future__ import annotations

import re
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .contracts import normalize_overlay
from .graphify import _safe_relative_path, _safe_text


_EDGE_KINDS = {
    "calls": "CALLS", "imports": "IMPORTS", "defines": "DEFINES",
    "implements": "IMPLEMENTS", "extends": "EXTENDS", "references": "REFERENCES",
    "member_of": "MEMBER_OF", "instantiates": "INSTANTIATES",
}
_SAFE_KIND = re.compile(r"^[A-Z][A-Z0-9_]{0,79}$")


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _diagnostic(code: str, message: str, severity: str = "warning") -> dict[str, str]:
    return {"code": code, "severity": severity, "message": message}


def _data_values(element: ET.Element) -> dict[str, str]:
    return {
        str(child.attrib.get("key") or ""): (child.text or "").strip()
        for child in element if _tag(child) == "data" and child.attrib.get("key")
    }


def parse_gortex_graphml(path: str | Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, str]]]:
    """Read the documented Gortex GraphML export without retaining meta JSON."""
    source = Path(path)
    raw = source.read_bytes()
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        return [], [], [_diagnostic("unsafe_xml", "Gortex GraphML must not contain DTD or entity declarations", "error")]
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        return [], [], [_diagnostic("invalid_graphml", f"Invalid Gortex GraphML: {exc}", "error")]
    if _tag(root) != "graphml":
        return [], [], [_diagnostic("unsupported_schema", "Gortex artifact must be a GraphML document", "error")]

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    diagnostics: list[dict[str, str]] = []
    node_ids: set[str] = set()
    for element in root.iter():
        if _tag(element) != "node":
            continue
        node_id = _safe_text(element.attrib.get("id"), max_length=512)
        if not node_id:
            diagnostics.append(_diagnostic("invalid_node", "Skipped Gortex node without id"))
            continue
        data = _data_values(element)
        node_ids.add(node_id)
        nodes.append({
            "id": node_id,
            "kind": (_safe_text(data.get("kind"), max_length=80) or "SYMBOL").upper(),
            "name": _safe_text(data.get("qual_name") or data.get("name") or node_id, max_length=512),
            "file": _safe_text(data.get("file_path"), max_length=1024),
            "start_line": _safe_text(data.get("start_line"), max_length=16),
            "language": _safe_text(data.get("language"), max_length=80),
        })
    for index, element in enumerate(root.iter()):
        if _tag(element) != "edge":
            continue
        source_id = _safe_text(element.attrib.get("source"), max_length=512)
        target_id = _safe_text(element.attrib.get("target"), max_length=512)
        if not source_id or not target_id or source_id not in node_ids or target_id not in node_ids:
            diagnostics.append(_diagnostic("unresolved_edge", f"Skipped Gortex edge {index} with unresolved endpoints"))
            continue
        data = _data_values(element)
        raw_kind = _safe_text(data.get("edge_kind") or "RELATED", max_length=80).lower()
        kind = _EDGE_KINDS.get(raw_kind, raw_kind.upper())
        if not _SAFE_KIND.fullmatch(kind):
            diagnostics.append(_diagnostic("unsupported_edge_kind", f"Skipped unsafe Gortex edge kind: {raw_kind or 'missing'}"))
            continue
        edges.append({
            "id": _safe_text(element.attrib.get("id"), max_length=512) or f"gortex_edge_{index}",
            "from": source_id, "to": target_id, "kind": kind,
            "confidence": _safe_text(data.get("confidence"), max_length=32),
            "confidence_label": _safe_text(data.get("confidence_label"), max_length=80),
            "origin": _safe_text(data.get("origin"), max_length=120),
            "file": _safe_text(data.get("edge_file_path"), max_length=1024),
        })
    return nodes, edges, diagnostics


def parse_gortex_json(path: str | Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, str]]]:
    """Read the JSON returned by ``gortex query … --format json``.

    A query returns a bounded subgraph (``nodes``/``edges``); symbol search
    returns ``results`` and is accepted as a node-only navigation graph.
    Unknown payload fields, including free-form metadata, are intentionally
    discarded.
    """
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [], [], [_diagnostic("invalid_gortex_json", f"Invalid Gortex JSON: {exc}", "error")]
    if not isinstance(payload, dict):
        return [], [], [_diagnostic("unsupported_schema", "Gortex JSON must be an object", "error")]
    raw_nodes = payload.get("nodes") if isinstance(payload.get("nodes"), list) else payload.get("results")
    raw_edges = payload.get("edges") if isinstance(payload.get("edges"), list) else []
    if not isinstance(raw_nodes, list):
        return [], [], [_diagnostic("unsupported_schema", "Gortex JSON requires nodes or results", "error")]
    nodes: list[dict[str, Any]] = []
    node_ids: set[str] = set()
    for item in raw_nodes:
        if not isinstance(item, dict):
            continue
        node_id = _safe_text(item.get("id"), max_length=512)
        if not node_id:
            continue
        node_ids.add(node_id)
        nodes.append({
            "id": node_id,
            "kind": (_safe_text(item.get("kind"), max_length=80) or "SYMBOL").upper(),
            "name": _safe_text(item.get("qual_name") or item.get("name") or node_id, max_length=512),
            "file": _safe_text(item.get("file_path"), max_length=1024),
            "start_line": _safe_text(item.get("start_line"), max_length=16),
            "language": _safe_text(item.get("language"), max_length=80),
        })
    diagnostics: list[dict[str, str]] = []
    edges: list[dict[str, Any]] = []
    for index, item in enumerate(raw_edges):
        if not isinstance(item, dict):
            continue
        source_id = _safe_text(item.get("from"), max_length=512)
        target_id = _safe_text(item.get("to"), max_length=512)
        if not source_id or not target_id or source_id not in node_ids or target_id not in node_ids:
            diagnostics.append(_diagnostic("unresolved_edge", f"Skipped Gortex JSON edge {index} with unresolved endpoints"))
            continue
        raw_kind = _safe_text(item.get("kind") or "RELATED", max_length=80).lower()
        kind = _EDGE_KINDS.get(raw_kind, raw_kind.upper())
        if not _SAFE_KIND.fullmatch(kind):
            diagnostics.append(_diagnostic("unsupported_edge_kind", f"Skipped unsafe Gortex edge kind: {raw_kind or 'missing'}"))
            continue
        edges.append({
            "id": f"gortex_json_edge_{index}_{source_id}_{target_id}", "from": source_id, "to": target_id, "kind": kind,
            "confidence": _safe_text(item.get("confidence"), max_length=32),
            "confidence_label": _safe_text(item.get("confidence_label") or item.get("tier"), max_length=80),
            "origin": _safe_text(item.get("origin"), max_length=120),
            "file": _safe_text(item.get("file_path"), max_length=1024),
        })
    return nodes, edges, diagnostics


def _resolution(raw: dict[str, Any]) -> tuple[str, str]:
    label = str(raw.get("confidence_label") or "").upper()
    if label in {"EXTRACTED", "CONFIRMED", "EXACT"}:
        return "confirmed", "confirmed"
    try:
        value = float(raw.get("confidence") or 0)
    except (TypeError, ValueError):
        value = 0.0
    return ("likely", "likely") if value >= 0.5 else ("unresolved", "unresolved")


def build_gortex_overlay(
    path: str | Path,
    *,
    project_root: str | Path,
    freshness: dict[str, Any] | None = None,
    enabled: bool = False,
) -> dict[str, Any]:
    """Normalize a user-exported Gortex GraphML graph into a local overlay."""
    artifact_path = Path(path)
    if artifact_path.suffix.lower() == ".json":
        raw_nodes, raw_edges, diagnostics = parse_gortex_json(artifact_path)
        source_kind = "GORTEX_QUERY_JSON"
    else:
        raw_nodes, raw_edges, diagnostics = parse_gortex_graphml(artifact_path)
        source_kind = "GORTEX_GRAPHML"
    nodes: list[dict[str, Any]] = []
    for raw in raw_nodes:
        file_path = _safe_relative_path(raw.get("file"), project_root)
        resolution = "confirmed" if raw.get("kind") else "likely"
        nodes.append({
            "id": raw["id"], "kind": raw["kind"], "name": raw["name"],
            "resolution": resolution, "confidence": resolution, "confirmed": resolution == "confirmed",
            "source": "gortex", "evidence_class": "SEMANTIC_INDEX", "participates_in_ranking": False,
            "provenance": {"adapter_id": "gortex", "source": "gortex", "source_artifact_path": str(artifact_path.resolve()), "source_file": file_path or None},
            "properties": {"overlay_only": True, "external_tool": "gortex", "file": file_path or None, "language": raw.get("language") or None, "start_line": raw.get("start_line") or None},
        })
    edges: list[dict[str, Any]] = []
    for raw in raw_edges:
        resolution, confidence = _resolution(raw)
        edges.append({
            "id": raw["id"], "kind": raw["kind"], "from": raw["from"], "to": raw["to"],
            "resolution": resolution, "confidence": confidence, "confirmed": resolution == "confirmed",
            "source": "gortex", "evidence_class": "SEMANTIC_INDEX", "participates_in_ranking": False,
            "provenance": {"adapter_id": "gortex", "source": "gortex", "source_artifact_path": str(artifact_path.resolve()), "source_file": _safe_relative_path(raw.get("file"), project_root) or None},
            "properties": {"overlay_only": True, "external_tool": "gortex", "origin": raw.get("origin") or None},
        })
    has_error = any(item.get("severity") == "error" for item in diagnostics)
    return normalize_overlay(
        adapter_id="gortex", adapter_version="1.0", source_kind=source_kind,
        evidence_class="SEMANTIC_INDEX", confidence="extracted_or_likely",
        freshness=freshness or {"status": "unverified", "verified": False},
        local_artifact_reference={"path": str(artifact_path.resolve())}, nodes=nodes, edges=edges,
        diagnostics=diagnostics, enabled=enabled,
        availability="unsupported" if has_error else "ready",
    )
