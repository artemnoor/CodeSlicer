"""Local GraphSON/CPGQL export bridge for the Joern adapter.

The bridge is deliberately separate from the canonical graph and from the
Joern adapter parser. It converts a bounded, safe subset of native GraphSON or
an explicit CPGQL path result into ``CodeSlicerJoernInterchange/v1``. It never
starts Joern, invokes a subprocess, accesses a network, or stores raw
GraphSON properties.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


JOERN_INTERCHANGE_SCHEMA = "CodeSlicerJoernInterchange/v1"
BRIDGE_SCHEMA = "CodeSlicerJoernBridge/v1"
MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_VERTICES = 5_000
MAX_EDGES = 12_000
MAX_PATHS = 500
MAX_SNIPPET = 256
SAFE_NODE_KINDS = {"METHOD", "CALL", "IDENTIFIER", "METHOD_PARAMETER_IN", "FILE", "LITERAL", "CONTROL_STRUCTURE"}
SAFE_EDGE_KINDS = {"AST", "CFG", "REACHING_DEF", "CDG", "CALL", "REF"}
SECRET_LIKE = re.compile(r"(?:secret|token|password|passwd|authorization|bearer|cookie|api[_-]?key|private[_-]?key|credential)", re.I)
SAFE_TEXT = re.compile(r"^[A-Za-z0-9_.$:<>~#/@+\- ]{1,160}$")
SAFE_POINTER = re.compile(r"^/(?:vertices|edges|paths|taint_paths)(?:/[0-9]+)+$")


def _diagnostic(code: str, message: str, severity: str = "warning") -> dict[str, Any]:
    return {"code": code, "severity": severity, "message": message}


def _unwrap(value: Any) -> Any:
    """Unwrap GraphSON ``@type``/``@value`` recursively."""
    if isinstance(value, list):
        return [_unwrap(item) for item in value]
    if isinstance(value, dict):
        if "@value" in value:
            unwrapped = _unwrap(value["@value"])
            graphson_type = str(value.get("@type") or "")
            if graphson_type.endswith("Map") and isinstance(unwrapped, list) and len(unwrapped) % 2 == 0:
                return {str(unwrapped[index]): unwrapped[index + 1] for index in range(0, len(unwrapped), 2)}
            return unwrapped
        return {str(key): _unwrap(item) for key, item in value.items() if key != "@type"}
    return value


def _key(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _opaque_id(value: Any, prefix: str = "joern") -> str:
    return f"{prefix}_{hashlib.sha256(_key(value).encode('utf-8', 'replace')).hexdigest()[:24]}"


def _text(value: Any, maximum: int = MAX_SNIPPET) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.replace("\x00", " ").split())[:maximum]
    if not value or SECRET_LIKE.search(value):
        return None
    return value


def _safe_name(value: Any) -> str | None:
    text = _text(value, 160)
    if not text or not SAFE_TEXT.fullmatch(text):
        return None
    return text


def _first(values: dict[str, Any], *names: str) -> Any:
    lowered = {str(key).lower(): value for key, value in values.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value is not None:
            if isinstance(value, list):
                return value[0] if value else None
            if isinstance(value, dict) and "value" in value:
                return value.get("value")
            return value
    return None


def _properties(vertex: dict[str, Any]) -> dict[str, Any]:
    raw = vertex.get("properties")
    if not isinstance(raw, dict):
        return {}
    result: dict[str, Any] = {}
    for key, value in raw.items():
        # GraphSON vertex properties often wrap values as a list of
        # {id, value}; unwrap only the value-bearing shape.
        item = value[0] if isinstance(value, list) and value else value
        if isinstance(item, dict) and "value" in item:
            item = item["value"]
        result[str(key)] = item
    return result


def _relative_file(value: Any, project: Path, diagnostics: list[dict[str, str]]) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.replace("\\", "/")
    if not text or "\x00" in text or "://" in text:
        return None
    candidate = Path(text)
    if candidate.is_absolute():
        try:
            text = candidate.resolve().relative_to(project.resolve()).as_posix()
        except ValueError:
            diagnostics.append(_diagnostic("joern_bridge_foreign_file", "GraphSON file location is outside the selected project"))
            return None
    normalized = Path(text).as_posix()
    if normalized in {"", "."} or normalized.startswith("../") or "/../" in f"/{normalized}" or len(normalized) > 512:
        return None
    return normalized


def _number(value: Any, minimum: int = 0, maximum: int = 10_000_000) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if minimum <= number <= maximum else None


def _location(properties: dict[str, Any], project: Path, diagnostics: list[dict[str, str]]) -> dict[str, Any] | None:
    file = _relative_file(_first(properties, "filename", "fileName", "file", "path", "sourceFile"), project, diagnostics)
    line = _number(_first(properties, "lineNumber", "line", "startLine", "line_number"), 1)
    end_line = _number(_first(properties, "lineNumberEnd", "endLine", "end_line"), 1) or line
    column = _number(_first(properties, "columnNumber", "column", "startColumn", "column_number")) or 0
    end_column = _number(_first(properties, "columnNumberEnd", "endColumn", "end_column"))
    has_location_fields = any(str(key).lower() in {"filename", "filename", "file", "path", "sourcefile", "linenumber", "line", "startline", "linenumberend", "endline"} for key in properties)
    if not file or line is None or end_line is None or end_line < line:
        if has_location_fields:
            diagnostics.append(_diagnostic("joern_bridge_location_unresolved", "GraphSON location was omitted because file/range was incomplete"))
        return None
    return {"file": file, "range": {"start_line": line, "start_character": column, "end_line": end_line, "end_character": end_column if end_column is not None else column}}


def _path_location(raw: dict[str, Any], project: Path, diagnostics: list[dict[str, str]]) -> dict[str, Any] | None:
    if isinstance(raw.get("range"), dict):
        file = _relative_file(raw.get("file") or raw.get("path") or raw.get("filename"), project, diagnostics)
        range_value = raw["range"]
        start = range_value.get("start") if isinstance(range_value.get("start"), dict) else range_value
        end = range_value.get("end") if isinstance(range_value.get("end"), dict) else range_value
        start_line = _number(start.get("line", start.get("start_line")), 1)
        end_line = _number(end.get("line", end.get("end_line")), 1)
        start_character = _number(start.get("character", start.get("start_character", 0))) or 0
        end_character = _number(end.get("character", end.get("end_character", start_character)))
        if file and start_line is not None and end_line is not None and end_line >= start_line:
            return {"file": file, "range": {"start_line": start_line, "start_character": start_character, "end_line": end_line, "end_character": end_character if end_character is not None else start_character}}
        return None
    return _location(raw, project, diagnostics)


def _normalized_edge_kind(label: Any) -> tuple[str | None, str | None]:
    original = str(label or "").upper()
    if original not in SAFE_EDGE_KINDS:
        return None, None
    return ({"AST": "CONTAINS", "CFG": "CONTROL_FLOW", "CDG": "CONTROL_FLOW", "REACHING_DEF": "DATA_FLOW", "REF": "DATA_FLOW", "CALL": "CALL"}).get(original), original


def _records(data: Any, *keys: str) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)] if any(key in {"paths", "taint_paths", "dataflow_paths"} for key in keys) else []
    if not isinstance(data, dict):
        return []
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _path_id(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("id") if "id" in value else value.get("vertex") or value.get("node")
    return value


def _path_value(raw: dict[str, Any], *keys: str) -> Any:
    """Return the first present path field without treating numeric zero as missing."""
    for key in keys:
        if key in raw and raw.get(key) is not None:
            return raw.get(key)
    return None


def _convert_path(raw: dict[str, Any], index: int, vertex_map: dict[str, str], locations: dict[str, dict[str, Any]], project: Path, diagnostics: list[dict[str, str]]) -> dict[str, Any] | None:
    source_raw = _path_id(_path_value(raw, "source", "src", "from"))
    sink_raw = _path_id(_path_value(raw, "sink", "dst", "to"))
    step_values = raw.get("steps") or raw.get("path") or []
    if not isinstance(step_values, list):
        return None
    source = vertex_map.get(_key(source_raw))
    sink = vertex_map.get(_key(sink_raw))
    steps = [vertex_map.get(_key(_path_id(item))) for item in step_values]
    steps = [item for item in steps if item]
    if not source or not sink:
        return None
    path_id = _opaque_id(raw.get("id") or f"path-{index}", "joern_path")
    raw_confidence = str(raw.get("confidence") or raw.get("resolution") or "likely").lower()
    confidence = raw_confidence if raw_confidence in {"confirmed", "likely", "unresolved"} else "likely"
    if not steps:
        confidence = "unresolved"
    path_locations = raw.get("locations") if isinstance(raw.get("locations"), list) else []
    safe_locations = []
    # Normalize optional path locations through the same file/range allowlist
    # used for vertex locations; never copy a raw query result location.
    for item in path_locations:
        if isinstance(item, dict):
            location = _path_location(item, project, diagnostics)
            if location:
                safe_locations.append(location)
    if not safe_locations:
        safe_locations = [locations[item] for item in (source, sink) if item in locations]
    return {"id": path_id, "source": source, "sink": sink, "steps": steps, "confidence": confidence, "resolution": confidence, "locations": safe_locations[:12], "pointer": f"/paths/{index}"}


def convert_graphson(data: Any, *, project_path: str | Path, artifact_path: str | Path) -> dict[str, Any]:
    """Convert unwrapped GraphSON or explicit CPGQL records to interchange."""
    project_input = Path(project_path).expanduser()
    if not project_input.is_absolute():
        raise ValueError("project_path must be an absolute local path")
    project = project_input.resolve()
    if not project.is_dir():
        raise FileNotFoundError(f"project directory does not exist: {project}")
    diagnostics: list[dict[str, str]] = []
    data = _unwrap(data)
    vertices = _records(data, "vertices")
    edges = _records(data, "edges")
    paths = _records(data, "taint_paths", "paths", "dataflow_paths")
    # CPGQL result exports may contain only path records with embedded vertex
    # objects rather than a top-level GraphSON vertices array.
    if not vertices and paths:
        embedded: list[dict[str, Any]] = []
        for path in paths:
            values = [path.get("source"), path.get("sink"), *(path.get("steps") or [])] if isinstance(path.get("steps"), list) else [path.get("source"), path.get("sink")]
            for value in values:
                if isinstance(value, dict) and value.get("id") is not None and (value.get("label") or value.get("properties")):
                    embedded.append(value)
        vertices = embedded
    if not vertices and not edges and not paths:
        raise ValueError("unsupported GraphSON/CPGQL shape: expected vertices, edges, or explicit paths")
    vertex_map: dict[str, str] = {}
    locations: dict[str, dict[str, Any]] = {}
    nodes: list[dict[str, Any]] = []
    for index, raw in enumerate(vertices[:MAX_VERTICES]):
        properties = _properties(raw)
        original_kind = str(raw.get("label") or _first(properties, "label", "kind") or "").upper()
        if original_kind not in SAFE_NODE_KINDS:
            continue
        raw_id = raw.get("id")
        if raw_id is None:
            diagnostics.append(_diagnostic("joern_bridge_vertex_id_missing", "GraphSON vertex was omitted because its ID is missing"))
            continue
        node_id = _opaque_id(raw_id, "joern_vertex")
        vertex_map[_key(raw_id)] = node_id
        location = _location(properties, project, diagnostics)
        node: dict[str, Any] = {"id": node_id, "kind": original_kind, "confidence": "likely", "resolution": "likely", "evidence_class": "CPG_STATIC", "pointer": f"/vertices/{index}"}
        name = _safe_name(_first(properties, "name", "method", "fullName", "code"))
        if name:
            node["name"] = name
        snippet = _text(_first(properties, "code", "snippet"), MAX_SNIPPET)
        if snippet:
            node["code_snippet"] = snippet
        if location:
            location["pointer"] = f"/vertices/{index}"
            node["location"] = location
            locations[node_id] = location
        nodes.append(node)
    if len(vertices) > MAX_VERTICES:
        diagnostics.append(_diagnostic("joern_bridge_vertices_bounded", f"GraphSON vertices bounded to {MAX_VERTICES}"))
    converted_edges: list[dict[str, Any]] = []
    unresolved_edge_reasons: dict[str, int] = {}
    for index, raw in enumerate(edges[:MAX_EDGES]):
        kind, source_kind = _normalized_edge_kind(raw.get("label") or raw.get("kind"))
        out_value = raw.get("outV") if raw.get("outV") is not None else raw.get("from") or raw.get("source")
        in_value = raw.get("inV") if raw.get("inV") is not None else raw.get("to") or raw.get("target")
        from_id = vertex_map.get(_key(_path_id(out_value)))
        to_id = vertex_map.get(_key(_path_id(in_value)))
        if not kind:
            unresolved_edge_reasons["unsupported_edge_kind"] = unresolved_edge_reasons.get("unsupported_edge_kind", 0) + 1
            continue
        if not from_id or not to_id:
            unresolved_edge_reasons["unresolved_endpoint"] = unresolved_edge_reasons.get("unresolved_endpoint", 0) + 1
            continue
        converted_edges.append({"id": _opaque_id(raw.get("id") or f"edge-{index}", "joern_edge"), "from": from_id, "to": to_id, "kind": kind, "source_kind": source_kind, "confidence": "likely", "resolution": "likely", "pointer": f"/edges/{index}"})
    if unresolved_edge_reasons:
        total_unresolved = sum(unresolved_edge_reasons.values())
        examples = sorted(unresolved_edge_reasons)[:4]
        edge_diagnostic = _diagnostic(
            "joern_bridge_edge_unresolved",
            f"{total_unresolved} GraphSON edges were omitted; examples: {', '.join(examples)}",
        )
        edge_diagnostic["count"] = total_unresolved
        edge_diagnostic["examples"] = examples
        diagnostics.append(edge_diagnostic)
    if len(edges) > MAX_EDGES:
        diagnostics.append(_diagnostic("joern_bridge_edges_bounded", f"GraphSON edges bounded to {MAX_EDGES}"))
    converted_paths: list[dict[str, Any]] = []
    for index, raw in enumerate(paths[:MAX_PATHS]):
        converted = _convert_path(raw, index, vertex_map, locations, project, diagnostics)
        if converted:
            converted_paths.append(converted)
        else:
            diagnostics.append(_diagnostic("joern_bridge_path_unresolved", "Explicit CPGQL path was omitted because source/sink IDs did not resolve"))
    if len(paths) > MAX_PATHS:
        diagnostics.append(_diagnostic("joern_bridge_paths_bounded", f"Explicit paths bounded to {MAX_PATHS}"))
    if not converted_paths:
        diagnostics.append(_diagnostic("joern_bridge_no_explicit_taint_paths", "AST/CFG/data-flow edges do not create a confirmed security path", "info"))
    source_path = str(Path(artifact_path).expanduser().resolve())
    return {
        "schema_version": JOERN_INTERCHANGE_SCHEMA,
        "metadata": {"tool": "joern", "tool_version": "unknown", "project_path": str(project), "source_format": "graphson-or-cpgql", "source_artifact": source_path},
        "nodes": nodes,
        "edges": converted_edges,
        "taint_paths": converted_paths,
        "findings": [],
        "diagnostics": diagnostics,
        "bridge": {"schema_version": BRIDGE_SCHEMA, "network_used": False, "source_kind": "local-artifact", "confirmed_security_paths_require_explicit_taint": True},
    }


def convert_graphson_file(input_path: str | Path, *, project_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    source = Path(input_path).expanduser().resolve()
    project = Path(project_path).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()
    source_input = Path(input_path).expanduser()
    project_input = Path(project_path).expanduser()
    output_input = Path(output_path).expanduser()
    if not source_input.is_absolute() or not output_input.is_absolute() or not project_input.is_absolute():
        raise ValueError("GraphSON, project, and output paths must be absolute local paths")
    source = source_input.resolve()
    project = project_input.resolve()
    output = output_input.resolve()
    if not source.is_file():
        raise FileNotFoundError(f"GraphSON artifact does not exist: {source}")
    if source.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError(f"GraphSON artifact exceeds {MAX_INPUT_BYTES} bytes")
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError("GraphSON artifact must be UTF-8 JSON") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid GraphSON JSON: {exc.msg}") from exc
    interchange = convert_graphson(data, project_path=project, artifact_path=source)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(interchange, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"status": "converted", "input_path": str(source), "output_path": str(output), "schema_version": JOERN_INTERCHANGE_SCHEMA, "nodes": len(interchange["nodes"]), "edges": len(interchange["edges"]), "paths": len(interchange["taint_paths"]), "diagnostics": interchange["diagnostics"], "privacy": {"mode": "local-only", "network_used": False, "raw_properties_stored": False, "full_source_stored": False}}
