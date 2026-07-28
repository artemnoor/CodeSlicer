"""Sanitized local Joern/CPG interchange adapter.

The adapter consumes an explicit JSON export produced by a local Joern query
or converter. It never starts Joern and never stores source snippets, raw
properties, literals, query payloads, URLs, or arbitrary provenance.
"""
from __future__ import annotations

import json
import hashlib
import re
from pathlib import Path
from typing import Any


JOERN_SCHEMA = "CodeSlicerJoernInterchange/v1"
JOERN_OVERLAY_SCHEMA = "CodeSlicerJoernEvidenceOverlay/v1"
MAX_NODES = 5_000
MAX_EDGES = 12_000
MAX_PATHS = 500
MAX_FINDINGS = 1_000
MAX_LOCATIONS_PER_PATH = 12
MAX_STRING = 256
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/#@$+~<>-]{0,255}$")
SAFE_LABEL = re.compile(r"^[A-Za-z0-9_.$:<>~#/@+\-]{1,160}$")
SAFE_POINTER = re.compile(r"^(?:\$|/)[A-Za-z0-9_./~\-]{0,180}$")
SAFE_COMMIT = re.compile(r"^[0-9a-fA-F]{7,64}$")
SAFE_KIND = {
    "METHOD", "FUNCTION", "CALL", "IDENTIFIER", "METHOD_PARAMETER_IN", "FILE", "LITERAL", "CONTROL_STRUCTURE", "CONTROL_FLOW", "DATA_FLOW", "SOURCE",
    "SINK", "DANGEROUS_CALL", "TAINT_PATH", "FILE", "LITERAL", "PARAMETER",
    "VARIABLE", "UNKNOWN",
}
SAFE_EDGE_KIND = {
    "CALL", "CONTROL_FLOW", "DATA_FLOW", "FLOWS_TO", "TAINT_STEP", "CONTAINS",
    "REACHES", "DANGEROUS_CALL", "SOURCE_TO_SINK",
}
SAFE_SOURCE_EDGE_KIND = {"AST", "CFG", "REACHING_DEF", "CDG", "CALL", "REF"}
SAFE_CONFIDENCE = {"confirmed", "likely", "unresolved", "stale"}
SECRET_WORDS = re.compile(r"(?:secret|token|password|passwd|authorization|bearer|cookie|api[_-]?key|private[_-]?key|credential)", re.I)


def _diagnostic(code: str, message: str, severity: str = "warning") -> dict[str, str]:
    return {"code": code, "severity": severity, "message": message}


def _safe_id(value: Any) -> str | None:
    text = str(value or "")
    if not text or len(text) > 4096:
        return None
    if SAFE_ID.fullmatch(text) and not SECRET_WORDS.search(text):
        return text
    # Preserve graph connectivity without retaining an unsafe external ID.
    # The digest is deterministic within/between imports but is not reversible
    # into the source marker or raw Joern identifier.
    return f"joern_{hashlib.sha256(text.encode('utf-8', 'replace')).hexdigest()[:24]}"


def _safe_label(value: Any) -> str | None:
    text = str(value or "")
    if len(text) > MAX_STRING or SECRET_WORDS.search(text) or not SAFE_LABEL.fullmatch(text):
        return None
    return text


def _safe_pointer(value: Any) -> str | None:
    text = str(value or "")
    if len(text) > 180 or SECRET_WORDS.search(text) or not SAFE_POINTER.fullmatch(text):
        return None
    return text


def _safe_relative_file(value: Any, project_root: Path | None) -> str | None:
    text = str(value or "").replace("\\", "/")
    if not text or "://" in text or "\x00" in text:
        return None
    candidate = Path(text)
    if candidate.is_absolute():
        if project_root is None:
            return None
        try:
            text = candidate.resolve().relative_to(project_root.resolve()).as_posix()
        except ValueError:
            return None
    normalized = Path(text).as_posix()
    if normalized in {"", "."} or normalized.startswith("../") or "/../" in f"/{normalized}" or len(normalized) > 512:
        return None
    return normalized


def _number(value: Any, minimum: int, maximum: int) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if minimum <= number <= maximum else None


def _safe_range(raw: Any) -> dict[str, dict[str, int]] | None:
    if isinstance(raw, (list, tuple)) and len(raw) >= 4:
        raw = {"start_line": raw[0], "start_character": raw[1], "end_line": raw[2], "end_character": raw[3]}
    if not isinstance(raw, dict):
        return None
    start = raw.get("start") if isinstance(raw.get("start"), dict) else raw
    end = raw.get("end") if isinstance(raw.get("end"), dict) else raw
    start_line = _number(start.get("line", start.get("start_line")), 1, 10_000_000)
    end_line = _number(end.get("line", end.get("end_line")), 1, 10_000_000)
    start_character = _number(start.get("character", start.get("start_character", 0)), 0, 100_000)
    end_character = _number(end.get("character", end.get("end_character", start_character)), 0, 100_000)
    if None in {start_line, end_line, start_character, end_character} or end_line < start_line:
        return None
    return {"start": {"line": start_line, "character": start_character}, "end": {"line": end_line, "character": end_character}}


def _confidence(value: Any, default: str = "unresolved") -> str:
    text = str(value or default).lower()
    return text if text in SAFE_CONFIDENCE else default


def _project_root(metadata: dict[str, Any], project_root: Path | None, diagnostics: list[dict[str, str]]) -> tuple[str | None, str | None]:
    raw = metadata.get("project_root") or metadata.get("project_path")
    if not raw:
        return None, None
    text = str(raw)
    if "://" in text or not Path(text).is_absolute():
        diagnostics.append(_diagnostic("joern_project_root_unverified", "Joern project root is not an absolute local path"))
        return None, None
    candidate = Path(text).expanduser().resolve()
    if project_root is not None and candidate != project_root.resolve():
        diagnostics.append(_diagnostic("joern_foreign_project", "Joern artifact project root differs from selected project"))
    return str(candidate), str(candidate)


def _provenance(artifact_path: str, pointer: Any = None, file: str | None = None, range_value: dict[str, Any] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"adapter_id": "joern", "source_artifact_path": artifact_path}
    safe_pointer = _safe_pointer(pointer)
    if safe_pointer:
        result["source_pointer"] = safe_pointer
    if file:
        result["file"] = file
    if range_value:
        result["range"] = range_value
    return result


def _location(raw: Any, project_root: Path | None, artifact_path: str, diagnostics: list[dict[str, str]]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    # Locations are optional for structural CPG nodes such as FILE. Only
    # diagnose a malformed location when the artifact explicitly attempted to
    # provide one; taint confirmation is calibrated separately and still
    # requires complete source/sink/path locations.
    location_fields = {"file", "path", "filename", "range", "location", "line", "start_line", "startLine", "lineNumber"}
    if not any(field in raw for field in location_fields):
        return None
    file = _safe_relative_file(raw.get("file") or raw.get("path") or raw.get("filename"), project_root)
    range_value = _safe_range(raw.get("range") or raw.get("location") or raw)
    if not file or not range_value:
        diagnostics.append(_diagnostic("joern_location_unresolved", "Joern location was omitted because file/range was incomplete"))
        return None
    return {"file": file, "range": range_value, "provenance": _provenance(artifact_path, raw.get("pointer") or raw.get("source_pointer"), file, range_value)}


def parse_joern_artifact(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError("Joern artifact must be UTF-8 JSON") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid Joern JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        return {"availability": "unsupported", "diagnostics": [_diagnostic("joern_schema_unknown", "Joern artifact must be a JSON object", "error")], "nodes": [], "edges": [], "taint_paths": [], "findings": []}
    if data.get("schema_version") != JOERN_SCHEMA:
        return {"availability": "unsupported", "diagnostics": [_diagnostic("joern_schema_unknown", "Unsupported Joern interchange schema", "error")], "nodes": [], "edges": [], "taint_paths": [], "findings": []}
    diagnostics: list[dict[str, str]] = []
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    if not isinstance(data.get("nodes", []), list) or not isinstance(data.get("edges", []), list):
        return {"availability": "incomplete", "diagnostics": [_diagnostic("joern_shape_invalid", "Joern interchange requires nodes and edges arrays", "error")], "nodes": [], "edges": [], "taint_paths": [], "findings": []}
    project_root_text, _ = _project_root(metadata, None, diagnostics)
    root = Path(project_root_text) if project_root_text else None
    nodes: list[dict[str, Any]] = []
    node_ids: set[str] = set()
    for raw in data.get("nodes", [])[:MAX_NODES]:
        if not isinstance(raw, dict):
            diagnostics.append(_diagnostic("joern_node_invalid", "Joern node was omitted because it is not an object"))
            continue
        node_id = _safe_id(raw.get("id"))
        if not node_id or node_id in node_ids:
            diagnostics.append(_diagnostic("joern_node_id_invalid", "Joern node was omitted because its stable id is invalid or duplicated"))
            continue
        kind = str(raw.get("kind") or "UNKNOWN").upper()
        if kind not in SAFE_KIND:
            diagnostics.append(_diagnostic("joern_node_kind_unsupported", "Joern node kind was normalized to UNKNOWN"))
            kind = "UNKNOWN"
        location = _location(raw.get("location") or raw, root, str(source.resolve()), diagnostics)
        node: dict[str, Any] = {"id": node_id, "kind": kind, "confidence": _confidence(raw.get("confidence")), "resolution": _confidence(raw.get("resolution"), _confidence(raw.get("confidence")))}
        label = _safe_label(raw.get("name") or raw.get("method") or raw.get("symbol"))
        if label:
            node["name"] = label
        if location:
            node.update({"file": location["file"], "range": location["range"], "provenance": location["provenance"]})
        else:
            node["provenance"] = _provenance(str(source.resolve()))
        node["evidence_class"] = "CPG_DATAFLOW" if kind in {"SOURCE", "SINK", "DATA_FLOW", "TAINT_PATH", "DANGEROUS_CALL"} else "CPG_STATIC"
        nodes.append(node)
        node_ids.add(node_id)
    if len(data.get("nodes", [])) > MAX_NODES:
        diagnostics.append(_diagnostic("joern_nodes_bounded", f"Joern nodes bounded to {MAX_NODES}"))
    edges: list[dict[str, Any]] = []
    for raw in data.get("edges", [])[:MAX_EDGES]:
        if not isinstance(raw, dict):
            continue
        edge_id = _safe_id(raw.get("id"))
        from_id = _safe_id(raw.get("from") or raw.get("source"))
        to_id = _safe_id(raw.get("to") or raw.get("target"))
        kind = str(raw.get("kind") or "").upper()
        if not edge_id or not from_id or not to_id or from_id not in node_ids or to_id not in node_ids:
            diagnostics.append(_diagnostic("joern_edge_unresolved", "Joern edge was omitted because its identifiers were incomplete"))
            continue
        if kind not in SAFE_EDGE_KIND:
            diagnostics.append(_diagnostic("joern_edge_unsupported", "Joern edge kind was omitted because it is outside the supported subset"))
            continue
        edge: dict[str, Any] = {"id": edge_id, "from": from_id, "to": to_id, "kind": kind, "confidence": _confidence(raw.get("confidence")), "resolution": _confidence(raw.get("resolution"), _confidence(raw.get("confidence"))), "evidence_class": "CPG_DATAFLOW" if kind in {"DATA_FLOW", "FLOWS_TO", "TAINT_STEP", "SOURCE_TO_SINK"} else "CPG_STATIC", "provenance": _provenance(str(source.resolve()), raw.get("pointer") or raw.get("source_pointer"))}
        source_kind = str(raw.get("source_kind") or "").upper()
        if source_kind in SAFE_SOURCE_EDGE_KIND:
            edge["source_kind"] = source_kind
        path_id = _safe_id(raw.get("path_id"))
        if path_id:
            edge["path_id"] = path_id
        edges.append(edge)
    if len(data.get("edges", [])) > MAX_EDGES:
        diagnostics.append(_diagnostic("joern_edges_bounded", f"Joern edges bounded to {MAX_EDGES}"))
    paths: list[dict[str, Any]] = []
    for raw in (data.get("taint_paths") if isinstance(data.get("taint_paths"), list) else [])[:MAX_PATHS]:
        if not isinstance(raw, dict):
            continue
        path_id = _safe_id(raw.get("id"))
        source_id = _safe_id(raw.get("source"))
        sink_id = _safe_id(raw.get("sink"))
        steps = [_safe_id(item) for item in (raw.get("steps") or [])]
        steps = [item for item in steps if item]
        complete = bool(path_id and source_id and sink_id and steps and source_id in node_ids and sink_id in node_ids and all(item in node_ids for item in steps))
        confidence = _confidence(raw.get("confidence"), "unresolved")
        if complete and confidence == "confirmed":
            resolution = "confirmed"
        elif complete:
            resolution = "likely"
            confidence = "likely" if confidence == "confirmed" else confidence
        else:
            resolution = "unresolved"
            confidence = "unresolved"
            diagnostics.append(_diagnostic("joern_taint_path_incomplete", "Taint path is unresolved because source, sink, steps, or identifiers are incomplete"))
        if not path_id:
            continue
        locations = []
        for item in (raw.get("locations") or [])[:MAX_LOCATIONS_PER_PATH]:
            location = _location(item, root, str(source.resolve()), diagnostics)
            if location:
                locations.append(location)
        paths.append({"id": path_id, "source": source_id, "sink": sink_id, "steps": steps[:100], "confidence": confidence, "resolution": resolution, "locations": locations, "evidence_class": "CPG_DATAFLOW", "provenance": _provenance(str(source.resolve()), raw.get("pointer") or raw.get("source_pointer"))})
    findings: list[dict[str, Any]] = []
    for raw in (data.get("findings") if isinstance(data.get("findings"), list) else [])[:MAX_FINDINGS]:
        if not isinstance(raw, dict):
            continue
        finding_id = _safe_id(raw.get("id"))
        node_id = _safe_id(raw.get("node") or raw.get("node_id"))
        if not finding_id or not node_id or node_id not in node_ids:
            continue
        path_id = _safe_id(raw.get("taint_path_id"))
        path = next((item for item in paths if item["id"] == path_id), None) if path_id else None
        findings.append({"id": finding_id, "kind": "DANGEROUS_CALL" if str(raw.get("kind") or "").upper() in {"DANGEROUS_CALL", "DANGEROUS_CALL_PATTERN"} else "CPG_FINDING", "node": node_id, "category": _safe_label(raw.get("category")) or "unknown", "severity": _safe_label(raw.get("severity")) or "unknown", "confidence": path["confidence"] if path else _confidence(raw.get("confidence"), "likely"), "resolution": path["resolution"] if path else "likely", "taint_path_id": path_id, "evidence_class": "CPG_DATAFLOW" if path else "CPG_STATIC", "provenance": _provenance(str(source.resolve()), raw.get("pointer") or raw.get("source_pointer"))})
    availability = "incomplete" if any(item.get("code", "").endswith(("invalid", "unresolved")) for item in diagnostics) else "ready"
    return {"availability": availability, "diagnostics": diagnostics, "metadata": {"format": JOERN_SCHEMA, "tool": _safe_label(metadata.get("tool") or "joern") or "joern", "tool_version": _safe_label(metadata.get("tool_version")), "project_path": project_root_text, "commit": metadata.get("commit") if SAFE_COMMIT.fullmatch(str(metadata.get("commit") or "")) else None, "created_at": str(metadata.get("created_at"))[:64] if metadata.get("created_at") else None}, "nodes": nodes, "edges": edges, "taint_paths": paths, "findings": findings}


def _has_complete_location(node: dict[str, Any] | None) -> bool:
    location = node or {}
    range_value = location.get("range") if isinstance(location.get("range"), dict) else {}
    return bool(location.get("file") and isinstance(range_value.get("start"), dict) and isinstance(range_value.get("end"), dict))


def _calibrate_taint_paths(overlay: dict[str, Any], freshness: dict[str, Any], diagnostics: list[dict[str, str]]) -> None:
    nodes = {str(item.get("id")): item for item in overlay.get("nodes", []) if isinstance(item, dict) and item.get("id")}
    fresh_verified = freshness.get("status") == "fresh" and freshness.get("verified") is True
    for path in overlay.get("taint_paths", []):
        source_id = path.get("source")
        sink_id = path.get("sink")
        steps = path.get("steps") or []
        structural = bool(source_id and sink_id and steps and source_id in nodes and sink_id in nodes and all(item in nodes for item in steps))
        source_location = _has_complete_location(nodes.get(str(source_id)))
        sink_location = _has_complete_location(nodes.get(str(sink_id)))
        path_locations = path.get("locations") if isinstance(path.get("locations"), list) else []
        complete_path_locations = len(path_locations) >= 2 and all(_has_complete_location(item) for item in path_locations[:2])
        reasons: list[str] = []
        if not structural:
            reasons.append("joern_taint_ids_incomplete")
        if not source_location:
            reasons.append("joern_taint_source_location_missing")
        if not sink_location:
            reasons.append("joern_taint_sink_location_missing")
        if not complete_path_locations:
            reasons.append("joern_taint_locations_missing")
        if not fresh_verified:
            reasons.append("joern_taint_freshness_unverified")
        if path.get("confidence") == "confirmed" and structural and source_location and sink_location and complete_path_locations and fresh_verified:
            path["resolution"] = "confirmed"
            path["confidence"] = "confirmed"
            continue
        if path.get("confidence") == "confirmed" or path.get("resolution") == "confirmed":
            path["resolution"] = "unresolved"
            path["confidence"] = "unresolved"
        elif path.get("confidence") not in {"likely", "unresolved"}:
            path["resolution"] = "likely"
            path["confidence"] = "likely"
        for reason in reasons:
            diagnostics.append(_diagnostic(reason, "Joern taint path cannot be confirmed without the required complete IDs, source/sink locations, and verified freshness"))


def calibrate_joern_overlay(overlay: dict[str, Any], freshness: dict[str, Any]) -> dict[str, Any]:
    diagnostics = list(overlay.get("diagnostics") or [])
    overlay["freshness"] = freshness
    _calibrate_taint_paths(overlay, freshness, diagnostics)
    overlay["diagnostics"] = diagnostics
    overlay["summary"] = {**(overlay.get("summary") or {}), "confirmed_paths": sum(1 for item in overlay.get("taint_paths", []) if item.get("resolution") == "confirmed")}
    return overlay


def build_joern_overlay(parsed: dict[str, Any], *, artifact_path: str, project_root: str | Path, freshness: dict[str, Any] | None = None, enabled: bool = False) -> dict[str, Any]:
    diagnostics = list(parsed.get("diagnostics") or [])
    metadata = parsed.get("metadata") if isinstance(parsed.get("metadata"), dict) else {}
    availability = parsed.get("availability", "ready")
    project_text = metadata.get("project_path")
    paths = list(parsed.get("taint_paths") or [])
    findings = list(parsed.get("findings") or [])
    overlay = {
        "schema_version": JOERN_OVERLAY_SCHEMA, "adapter_id": "joern", "adapter_version": "1.0",
        "evidence_class": "CPG_DATAFLOW", "confidence": "confirmed_if_complete_and_fresh",
        "freshness": freshness or {"status": "fresh", "verified": True}, "source": {"adapter_id": "joern", "source": "joern", "source_artifact_path": str(Path(artifact_path).resolve()), "source_kind": "local-artifact", "fingerprint": None},
        "project_path": project_text, "tool": metadata.get("tool") or "joern", "tool_version": metadata.get("tool_version"), "timestamp": metadata.get("created_at"),
        "nodes": list(parsed.get("nodes") or []), "edges": list(parsed.get("edges") or []), "taint_paths": paths, "findings": findings,
        "summary": {"nodes": len(parsed.get("nodes") or []), "edges": len(parsed.get("edges") or []), "paths": len(paths), "findings": len(findings), "confirmed_paths": sum(1 for item in paths if item.get("resolution") == "confirmed")},
        "diagnostics": diagnostics, "privacy": {"mode": "local-only", "network_used": False, "raw_properties_stored": False, "snippets_stored": False, "redaction": "strict-allowlist"}, "network_used": False,
        "enabled": enabled, "overlay_only": True, "participates_in_ranking": False, "availability": availability,
    }
    return calibrate_joern_overlay(overlay, freshness or {"status": "fresh", "verified": True})


def bounded_joern_context(overlay: dict[str, Any] | None, *, entity: str | None = None, max_nodes: int = 80, max_edges: int = 160, max_paths: int = 40) -> dict[str, Any]:
    if not overlay:
        return {"status": "unavailable", "adapter_id": "joern", "evidence_class": "CPG_DATAFLOW", "nodes": [], "edges": [], "taint_paths": [], "findings": [], "diagnostics": ["Joern overlay is not enabled or imported"], "network_used": False, "overlay_only": True, "participates_in_ranking": False}
    selected_paths = list(overlay.get("taint_paths") or [])
    if entity:
        selected_paths = [item for item in selected_paths if entity in {item.get("source"), item.get("sink"), *(item.get("steps") or [])}]
    selected_paths = selected_paths[:max_paths]
    selected_ids = {node_id for item in selected_paths for node_id in [item.get("source"), item.get("sink"), *(item.get("steps") or [])] if node_id}
    nodes = [item for item in (overlay.get("nodes") or []) if not selected_ids or item.get("id") in selected_ids][:max_nodes]
    node_ids = {item.get("id") for item in nodes}
    edges = [item for item in (overlay.get("edges") or []) if item.get("from") in node_ids and item.get("to") in node_ids][:max_edges]
    findings = [item for item in (overlay.get("findings") or []) if not node_ids or item.get("node") in node_ids][:max_paths]
    diagnostics = list(overlay.get("diagnostics") or [])
    if len(overlay.get("taint_paths") or []) > max_paths or len(overlay.get("nodes") or []) > max_nodes or len(overlay.get("edges") or []) > max_edges:
        diagnostics.append(_diagnostic("joern_context_bounded", f"Joern context bounded to {max_paths} paths, {max_nodes} nodes, and {max_edges} edges", "info"))
    return {"status": overlay.get("availability", "ready"), "adapter_id": "joern", "evidence_class": "CPG_DATAFLOW", "freshness": overlay.get("freshness", {"status": "unknown", "verified": False}), "nodes": nodes, "edges": edges, "taint_paths": selected_paths, "findings": findings, "diagnostics": diagnostics, "privacy": overlay.get("privacy", {"mode": "local-only", "network_used": False}), "network_used": False, "overlay_only": True, "participates_in_ranking": False, "supplemental": True}
