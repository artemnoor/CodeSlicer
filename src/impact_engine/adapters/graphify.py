"""Optional Graphify adapter implementation. Stage 11."""
import json
import re
from pathlib import Path
from typing import Any, Dict
from impact_engine.models import GraphDocument
from impact_engine.normalization import normalize_external_graph
from impact_engine.graph_identity import stable_symbol_id
from impact_engine.adapters.contracts import normalize_overlay


_SAFE_COMMUNITY_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_SAFE_POINTER_RE = re.compile(r"^/(?:nodes|edges|links)/[0-9]+(?:/[A-Za-z0-9_.-]+)*$")


def _safe_text(value: Any, *, max_length: int = 512) -> str | None:
    if not isinstance(value, str) or not value or len(value) > max_length:
        return None
    return value


def _recursive_allowlist(value: Any, allowed: dict[str, Any] | None = None) -> Any:
    """Recursively retain only explicitly named scalar/container fields."""
    if isinstance(value, dict):
        if not isinstance(allowed, dict):
            return {}
        return {key: _recursive_allowlist(value[key], child_allowed) for key, child_allowed in allowed.items() if key in value}
    if isinstance(value, list):
        return [_recursive_allowlist(item, allowed if isinstance(allowed, dict) else None) for item in value]
    return value if isinstance(value, (str, int, float, bool)) else None


def _safe_relative_path(value: Any, project_root: str | Path) -> str | None:
    raw = _safe_text(value, max_length=1024)
    if raw is None or "://" in raw or "\x00" in raw:
        return None
    normalized = raw.replace("\\", "/")
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        try:
            normalized = candidate.resolve().relative_to(Path(project_root).resolve()).as_posix()
        except (OSError, ValueError):
            return None
    parts = [part for part in normalized.split("/") if part not in {"", "."}]
    if not parts or ".." in parts or any("\x00" in part for part in parts):
        return None
    return "/".join(parts)


def _safe_range(value: Any) -> dict[str, dict[str, int]] | None:
    if not isinstance(value, dict):
        return None
    value = _recursive_allowlist(value, {
        "start": {"line": None, "character": None, "column": None, "start_line": None, "start_column": None},
        "end": {"line": None, "character": None, "column": None, "end_line": None, "end_column": None},
        "line": None, "character": None, "column": None,
        "start_line": None, "start_column": None, "end_line": None, "end_column": None,
    })
    start = value.get("start") if isinstance(value.get("start"), dict) else value
    end = value.get("end") if isinstance(value.get("end"), dict) else value
    def point(item: dict[str, Any], line_keys: tuple[str, ...], character_keys: tuple[str, ...]) -> dict[str, int] | None:
        line = next((item.get(key) for key in line_keys if isinstance(item.get(key), int)), None)
        character = next((item.get(key) for key in character_keys if isinstance(item.get(key), int)), None)
        if line is None or character is None or line < 0 or character < 0:
            return None
        return {"line": line, "character": character}
    start_point = point(start, ("line", "start_line"), ("character", "column", "start_column"))
    end_point = point(end, ("line", "end_line"), ("character", "column", "end_column"))
    return {"start": start_point, "end": end_point} if start_point and end_point else None


def _safe_pointer(value: Any) -> str | None:
    text = _safe_text(value, max_length=256)
    return text if text and _SAFE_POINTER_RE.fullmatch(text) else None


def _safe_community(value: Any) -> str | None:
    text = _safe_text(value, max_length=128)
    if not text or not _SAFE_COMMUNITY_RE.fullmatch(text):
        return None
    # Preserve the historical fixture identifiers while dropping arbitrary
    # community labels/metadata that are not needed for evidence navigation.
    return text if text in {"core", "default", "root"} or re.fullmatch(r"(?:community[-_:])?[0-9]+", text) else None


def _sanitize_graphify_input(graphify_json: dict[str, Any], project_root: str | Path) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Keep only the external overlay's deliberately small evidence surface."""
    diagnostics: list[dict[str, str]] = []
    safe_nodes: list[dict[str, Any]] = []
    for index, raw in enumerate(graphify_json.get("nodes") or []):
        if not isinstance(raw, dict):
            diagnostics.append({"code": "unsafe_node", "severity": "warning", "message": f"Skipped non-object Graphify node {index}"})
            continue
        raw_properties = raw.get("properties") if isinstance(raw.get("properties"), dict) else {}
        safe_properties = _recursive_allowlist(raw_properties, {"path": None, "range": {
            "start": {"line": None, "character": None, "column": None, "start_line": None, "start_column": None},
            "end": {"line": None, "character": None, "column": None, "end_line": None, "end_column": None},
            "line": None, "character": None, "column": None,
            "start_line": None, "start_column": None, "end_line": None, "end_column": None,
        }})
        path = _safe_relative_path(raw.get("source_file") or raw.get("file") or safe_properties.get("path"), project_root)
        location = _safe_range(raw.get("source_location") or raw.get("location") or raw.get("range") or safe_properties.get("range"))
        node_id = _safe_text(raw.get("id") or raw.get("key"))
        kind = _safe_text(raw.get("kind") or raw.get("type"), max_length=80) or "FUNCTION"
        name = _safe_text(raw.get("name"), max_length=512)
        if node_id is None:
            node_id = stable_symbol_id(str(project_root), path or "external", name or "anonymous", kind.upper())
        safe_node: dict[str, Any] = {"id": node_id, "kind": kind, "name": name or node_id}
        if path:
            safe_node["source_file"] = path
        if location:
            safe_node["source_location"] = location
        community = _safe_community(raw.get("community") or raw.get("community_id") or raw.get("cluster"))
        if community:
            safe_node["community_id"] = community
        safe_nodes.append(safe_node)

    safe_edges: list[dict[str, Any]] = []
    for index, raw in enumerate(graphify_json.get("edges") or graphify_json.get("links") or []):
        if not isinstance(raw, dict):
            diagnostics.append({"code": "unsafe_edge", "severity": "warning", "message": f"Skipped non-object Graphify edge {index}"})
            continue
        source_id = _safe_text(raw.get("from") or raw.get("source"), max_length=512)
        target_id = _safe_text(raw.get("to") or raw.get("target"), max_length=512)
        kind = _safe_text(raw.get("kind") or raw.get("type") or raw.get("relation"), max_length=80)
        if not source_id or not target_id:
            diagnostics.append({"code": "unsafe_edge", "severity": "warning", "message": f"Skipped Graphify edge {index} without safe endpoints"})
            continue
        safe_edge: dict[str, Any] = {
            "id": _safe_text(raw.get("id"), max_length=512) or f"edge_{source_id}_{target_id}_{kind or 'CALLS'}",
            "from": source_id, "to": target_id, "kind": kind or "CALLS",
        }
        source_kind = _safe_text(raw.get("source_kind"), max_length=80)
        confidence = _safe_text(raw.get("confidence"), max_length=80)
        if source_kind:
            safe_edge["source_kind"] = source_kind
        if confidence:
            safe_edge["confidence"] = confidence
        path = _safe_relative_path(raw.get("source_file") or raw.get("file"), project_root)
        location = _safe_range(raw.get("source_location") or raw.get("location") or raw.get("range"))
        if path:
            safe_edge["source_file"] = path
        if location:
            safe_edge["source_location"] = location
        pointer = _safe_pointer(raw.get("json_pointer") or raw.get("pointer"))
        if pointer:
            safe_edge["pointer"] = pointer
        safe_edges.append(safe_edge)
    return {"nodes": safe_nodes, "edges": safe_edges}, diagnostics


def from_graphify_json(data: Dict[str, Any]) -> GraphDocument:
    if "links" in data or any(
        "source" in edge and "target" in edge
        for edge in data.get("edges", []) or []
    ):
        return normalize_graphify_json(data)
    graph = normalize_external_graph(data, source_name="graphify")
    if graph.metadata is None:
        graph.metadata = {}
    graph.metadata["adapter"] = "graphify"
    return graph


def from_graphify_file(path: str | Path) -> GraphDocument:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    return from_graphify_json(data)


def is_graphify_available() -> bool:
    try:
        import graphify
        return True
    except ImportError:
        return False


def build_graphify_overlay(
    graphify_json: dict[str, Any],
    *,
    artifact_path: str,
    project_root: str | Path,
    freshness: dict[str, Any] | None = None,
    enabled: bool = False,
) -> dict[str, Any]:
    """Normalize Graphify as a display/investigation overlay, never core evidence.

    The existing ``from_graphify_json`` remains the compatibility importer for
    the legacy ``--graphify`` command.  New adapter API callers use this
    bounded contract, where every edge is explicitly non-ranking evidence.
    """
    if not isinstance(graphify_json, dict):
        raise ValueError("Graphify artifact must be a JSON object")
    raw_nodes = graphify_json.get("nodes")
    raw_edges = graphify_json.get("edges") or graphify_json.get("links") or []
    if not isinstance(raw_nodes, list):
        return normalize_overlay(
            adapter_id="graphify", adapter_version="1.0", source_kind="GRAPHIFY_OVERLAY",
            evidence_class="DOC_INFERRED", confidence="unresolved",
            freshness=freshness or {"status": "unverified", "verified": False},
            local_artifact_reference={"path": str(Path(artifact_path).resolve())}, nodes=[], edges=[],
            diagnostics=[{"code": "unsupported_schema", "severity": "error", "message": "Graphify artifact requires a nodes array"}],
            enabled=enabled, availability="unsupported",
        )
    if not isinstance(raw_edges, list):
        raw_edges = []
    sanitized_graph, sanitize_diagnostics = _sanitize_graphify_input(graphify_json, project_root)
    raw_nodes = sanitized_graph["nodes"]
    raw_edges = sanitized_graph["edges"]
    document = normalize_graphify_json(sanitized_graph, project_root=str(project_root))
    raw_by_id = {}
    for raw in raw_edges:
        if isinstance(raw, dict):
            key = raw.get("id") or f"edge_{raw.get('source') or raw.get('from')}_{raw.get('target') or raw.get('to')}_{raw.get('kind') or raw.get('type') or raw.get('relation') or 'CALLS'}"
            raw_by_id[str(key)] = raw
    edges = []
    for edge in document.edges:
        raw = raw_by_id.get(edge.id, {})
        source_kind = _graphify_source_kind(raw)
        confidence, resolution = {
            "EXTRACTED": ("medium", "likely"),
            "INFERRED": ("likely", "likely"),
            "AMBIGUOUS": ("unresolved", "unresolved"),
        }[source_kind]
        edges.append({
            "id": edge.id, "kind": edge.kind, "from": edge.from_node, "to": edge.to_node,
            "source_kind": source_kind, "evidence_class": "DOC_INFERRED",
            "confidence": confidence, "resolution": resolution,
            "confirmed": False, "participates_in_ranking": False,
            "source": "graphify", "properties": {
                "external_tool": "graphify", "overlay_only": True,
                **({"external_source_file": raw["source_file"]} if raw.get("source_file") else {}),
                **({"external_source_location": raw["source_location"]} if raw.get("source_location") else {}),
            },
            "provenance": {
                "adapter_id": "graphify", "source": "graphify",
                "source_artifact_path": str(Path(artifact_path).resolve()),
                "source_pointer": raw.get("pointer"),
                "source_file": raw.get("source_file"),
                "source_location": raw.get("source_location"),
            },
        })
    nodes = []
    raw_by_node_id = {}
    for index, raw in enumerate(raw_nodes):
        if isinstance(raw, dict):
            raw_by_node_id[str(raw.get("id") or raw.get("key") or f"node_{index}")] = raw
    for node in document.nodes:
        raw = raw_by_node_id.get(node.id, {})
        safe_properties: dict[str, Any] = {"external_tool": "graphify", "overlay_only": True}
        if raw.get("source_file"):
            safe_properties["external_source_file"] = raw["source_file"]
        if raw.get("source_location"):
            safe_properties["external_source_location"] = raw["source_location"]
        item = {"id": node.id, "kind": node.kind, "name": node.name, "properties": safe_properties}
        item.update({
            "source": "graphify", "evidence_class": "DOC_INFERRED", "resolution": "likely",
            "confidence": "likely", "confirmed": False, "participates_in_ranking": False,
            "provenance": {
                "adapter_id": "graphify", "source": "graphify",
                "source_artifact_path": str(Path(artifact_path).resolve()),
                "source_pointer": raw.get("pointer"),
                "source_file": raw.get("source_file"),
                "source_location": raw.get("source_location"),
            },
        })
        nodes.append(item)
    community_counts: dict[str, int] = {}
    for node, raw in zip(document.nodes, raw_nodes):
        if isinstance(raw, dict):
            community = raw.get("community") or raw.get("community_id") or raw.get("cluster")
            if community is not None:
                community_counts[str(community)] = community_counts.get(str(community), 0) + 1
    diagnostics = list(sanitize_diagnostics)
    if not edges and raw_edges:
        diagnostics.append({"code": "no_valid_edges", "severity": "warning", "message": "No valid Graphify edges were normalized"})
    if not raw_edges:
        diagnostics.append({"code": "incomplete_schema", "severity": "warning", "message": "Graphify artifact has no edges/links array"})
    availability = "incomplete" if diagnostics else "ready"
    return normalize_overlay(
        adapter_id="graphify", adapter_version="1.0", source_kind="GRAPHIFY_OVERLAY",
        evidence_class="DOC_INFERRED", confidence="unresolved_or_likely",
        freshness=freshness or {"status": "unverified", "verified": False},
        local_artifact_reference={"path": str(Path(artifact_path).resolve())},
        nodes=nodes, edges=edges, diagnostics=diagnostics, enabled=enabled,
        availability=availability if enabled else "disabled",
    ) | {"communities": [{"id": key, "nodes": count} for key, count in sorted(community_counts.items())]}


def _graphify_source_kind(edge: dict[str, Any]) -> str:
    raw = str(edge.get("source_kind") or edge.get("provenance") or edge.get("confidence") or "EXTRACTED").upper()
    if "AMBIG" in raw or raw in {"UNRESOLVED", "UNKNOWN"}:
        return "AMBIGUOUS"
    if "INFER" in raw or raw in {"LIKELY", "POSSIBLE"}:
        return "INFERRED"
    return "EXTRACTED"


def normalize_graphify_json(graphify_json: dict, project_root: str = ".") -> GraphDocument:
    from impact_engine.models import NODE_KINDS, EDGE_KINDS
    
    nodes = []
    for gn in graphify_json.get("nodes", []):
        nid = gn.get("id") or gn.get("key")
        if not nid:
            nid = stable_symbol_id(
                project_root,
                str(gn.get("source_file") or gn.get("file") or "external"),
                str(gn.get("name") or gn.get("label") or "anonymous"),
                str(gn.get("kind") or gn.get("type") or "FUNCTION").upper(),
            )
        if not nid:
            continue
        gkind = gn.get("kind") or gn.get("type") or gn.get("label") or "FUNCTION"
        gkind = str(gkind).upper()
        if gkind not in NODE_KINDS:
            gkind = "FUNCTION"
        name = gn.get("name") or gn.get("label") or nid
        nodes.append({
            "id": nid,
            "kind": gkind,
            "name": name,
            "properties": {
                **dict(gn.get("properties", {}) or {}),
                "external_source_file": gn.get("source_file") or gn.get("file"),
                "external_source_location": gn.get("source_location"),
                "external_tool": "graphify",
            }
        })
        
    edges = []
    raw_edges = graphify_json.get("edges") or graphify_json.get("links") or []
    node_ids = {item["id"] for item in nodes}
    for ge in raw_edges:
        gfrom = ge.get("from") or ge.get("source")
        gto = ge.get("to") or ge.get("target")
        if not gfrom or not gto:
            continue
        gkind = ge.get("kind") or ge.get("type") or ge.get("label") or "CALLS"
        gkind = str(gkind).upper()
        if gkind not in EDGE_KINDS:
            gkind = "CALLS"
        edge_id = ge.get("id") or f"edge_{gfrom}_{gto}_{gkind}"
        raw_confidence = ge.get("confidence", 0.5)
        confidence = {
            "EXTRACTED": 0.60,
            "INFERRED": 0.55,
            "AMBIGUOUS": 0.35,
        }.get(str(raw_confidence).upper(), raw_confidence)
        try:
            confidence = min(0.70, max(0.0, float(confidence)))
        except (TypeError, ValueError):
            confidence = 0.50
        properties = dict(ge.get("properties", {}) or {})
        properties.update({
            "external_tool": "graphify",
            "external_relation": ge.get("relation") or ge.get("kind") or ge.get("type"),
            "external_source_file": ge.get("source_file"),
            "external_source_location": ge.get("source_location"),
        })
        if gfrom not in node_ids or gto not in node_ids:
            properties["quality_warning"] = "dangling_external_reference"
        edges.append({
            "id": edge_id,
            "kind": gkind,
            "from": gfrom,
            "to": gto,
            "source": "EXTERNAL_TOOL",
            "confidence": confidence,
            "properties": properties
        })
        
    normalized_data = {
        "nodes": nodes,
        "edges": edges
    }
    return from_graphify_json(normalized_data)
