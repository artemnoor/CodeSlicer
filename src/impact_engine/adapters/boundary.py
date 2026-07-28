"""Local OpenAPI/AsyncAPI boundary overlays.

This module parses already materialized local specifications only.  It creates
contract facts and bounded mapping metadata; it never contacts a server,
broker, URL, generator, or the canonical CodeSlicer graph.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from impact_engine.models import GraphDocument

try:  # YAML support is an optional import for source checkouts without extras.
    import yaml
except ImportError:  # pragma: no cover - exercised in minimal installations
    yaml = None


BOUNDARY_OVERLAY_SCHEMA = "CodeSlicerBoundaryOverlay/v1"
MAX_BOUNDARY_SPEC_BYTES = 16 * 1024 * 1024
HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pointer_get(document: dict[str, Any], reference: str) -> Any:
    if not isinstance(reference, str) or not reference.startswith("#/"):
        raise ValueError("only internal document references are supported")
    value: Any = document
    for token in reference[2:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, dict) or token not in value:
            raise KeyError(reference)
        value = value[token]
    return value


def _resolve(document: dict[str, Any], value: Any, diagnostics: list[dict[str, Any]], stack: tuple[str, ...] = ()) -> Any:
    if not isinstance(value, dict) or "$ref" not in value:
        return value
    reference = str(value.get("$ref"))
    if not reference.startswith("#/"):
        diagnostics.append({"code": "external_ref", "severity": "warning", "message": f"External reference is not imported: {reference}"})
        return value
    if reference in stack:
        diagnostics.append({"code": "cyclic_ref", "severity": "warning", "message": f"Cyclic local reference: {reference}"})
        return value
    try:
        target = _resolve(document, _pointer_get(document, reference), diagnostics, (*stack, reference))
    except (KeyError, ValueError):
        diagnostics.append({"code": "broken_ref", "severity": "warning", "message": f"Broken local reference: {reference}"})
        return value
    if len(value) == 1:
        return target
    merged = copy.deepcopy(target) if isinstance(target, dict) else {}
    merged.update({key: item for key, item in value.items() if key != "$ref"})
    return merged


def _collect_refs(document: dict[str, Any], value: Any, diagnostics: list[dict[str, Any]]) -> list[str]:
    references: list[str] = []
    if isinstance(value, dict):
        if "$ref" in value:
            ref = str(value["$ref"])
            references.append(ref)
            _resolve(document, value, diagnostics)
        for child in value.values():
            references.extend(_collect_refs(document, child, diagnostics))
    elif isinstance(value, list):
        for child in value:
            references.extend(_collect_refs(document, child, diagnostics))
    return list(dict.fromkeys(references))


def _source(path: str, pointer: str) -> dict[str, str]:
    return {"path": path, "pointer": pointer}


def _load(path: Path) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
    if path.stat().st_size > MAX_BOUNDARY_SPEC_BYTES:
        raise ValueError(f"boundary specification exceeds {MAX_BOUNDARY_SPEC_BYTES} bytes")
    raw = path.read_text(encoding="utf-8")
    diagnostics: list[dict[str, Any]] = []
    if path.suffix.lower() == ".json":
        document = json.loads(raw)
        format_name = "json"
    else:
        if yaml is None:
            raise ValueError("YAML support is unavailable; install the declared PyYAML dependency locally")
        document = yaml.safe_load(raw)
        format_name = "yaml"
    if not isinstance(document, dict):
        raise ValueError("boundary specification root must be an object")
    if document.get("x-generated") or document.get("x-generated-by") or (isinstance(document.get("info"), dict) and document["info"].get("x-generated")):
        diagnostics.append({"code": "generated_spec", "severity": "warning", "message": "Specification declares generated provenance; route mappings may be incomplete."})
    return document, format_name, diagnostics


def _schema_name(reference: str) -> str | None:
    if "/schemas/" in reference or "/definitions/" in reference:
        return reference.rsplit("/", 1)[-1].replace("~1", "/").replace("~0", "~")
    return None


def _node(node_id: str, kind: str, name: str, source: dict[str, str], **properties: Any) -> dict[str, Any]:
    return {"id": node_id, "kind": kind, "name": name, "source": source, "properties": properties, "mapping": {"status": "unresolved"}, "evidence_class": "CONTRACT_CONFIRMED"}


def _edge(edge_id: str, source: str, target: str, kind: str, source_ref: dict[str, str]) -> dict[str, Any]:
    return {"id": edge_id, "from": source, "to": target, "kind": kind, "source": source_ref, "evidence_class": "CONTRACT_CONFIRMED", "confidence": "confirmed", "resolution": "confirmed", "confirmed": True}


def _openapi(document: dict[str, Any], source_path: str, diagnostics: list[dict[str, Any]]) -> dict[str, Any]:
    version = str(document.get("openapi") or document.get("swagger") or "")
    if not (version.startswith("3.") or version == "2.0"):
        diagnostics.append({"code": "unsupported_version", "severity": "error", "message": f"Unsupported OpenAPI/Swagger version: {version or 'missing'}"})
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    schema_root = "#/components/schemas" if version.startswith("3.") else "#/definitions"
    schemas = document.get("components", {}).get("schemas", {}) if version.startswith("3.") else document.get("definitions", {})
    base_path = "" if version.startswith("3.") else str(document.get("basePath") or "")
    for name, schema in (schemas or {}).items():
        pointer = f"{schema_root}/{name}"
        _resolve(document, schema, diagnostics)
        nodes.append(_node(f"openapi:schema:{name}", "API_SCHEMA", str(name), _source(source_path, pointer), schema_name=str(name), ref=pointer))
    paths = document.get("paths") or {}
    for path_name, path_item_raw in paths.items():
        path_item = _resolve(document, path_item_raw, diagnostics)
        if not isinstance(path_item, dict):
            continue
        for method, raw_operation in path_item.items():
            method_lower = str(method).lower()
            if method_lower not in HTTP_METHODS:
                continue
            pointer = f"#/paths/{str(path_name).replace('~', '~0').replace('/', '~1')}/{method_lower}"
            operation = _resolve(document, raw_operation, diagnostics)
            if not isinstance(operation, dict):
                continue
            operation_id = str(operation.get("operationId") or f"{method_lower} {path_name}")
            route_path = f"{base_path.rstrip('/')}/{str(path_name).lstrip('/')}" if base_path else str(path_name)
            route_path = route_path if route_path.startswith("/") else f"/{route_path}"
            operation_node = f"openapi:operation:{method_lower}:{path_name}"
            route_node = f"openapi:route:{method_lower}:{path_name}"
            nodes.append(_node(operation_node, "API_OPERATION", operation_id, _source(source_path, pointer), method=method_lower.upper(), path=route_path, operation_id=operation_id, tags=operation.get("tags") or [], parameters=operation.get("parameters") or [], has_request_body=bool(operation.get("requestBody") or operation.get("parameters")), response_codes=sorted(str(code) for code in (operation.get("responses") or {}))))
            nodes.append(_node(route_node, "HTTP_ROUTE", f"{method_lower.upper()} {route_path}", _source(source_path, pointer), method=method_lower.upper(), path=route_path, operation_id=operation_id))
            edges.append(_edge(f"{operation_node}:route", operation_node, route_node, "ROUTES_TO", _source(source_path, pointer)))
            for ref in _collect_refs(document, operation, diagnostics):
                schema_name = _schema_name(ref)
                if schema_name:
                    schema_node = f"openapi:schema:{schema_name}"
                    if any(item["id"] == schema_node for item in nodes):
                        edges.append(_edge(f"{operation_node}:schema:{schema_name}", operation_node, schema_node, "USES_SCHEMA", _source(source_path, pointer)))
            for parameter in operation.get("parameters", []) if isinstance(operation.get("parameters"), list) else []:
                _resolve(document, parameter, diagnostics)
            _resolve(document, operation.get("requestBody"), diagnostics)
            _resolve(document, operation.get("responses"), diagnostics)
    return {"format": "openapi", "version": version, "nodes": nodes, "edges": edges, "diagnostics": diagnostics, "summary": {"operations": sum(1 for item in nodes if item["kind"] == "API_OPERATION"), "routes": sum(1 for item in nodes if item["kind"] == "HTTP_ROUTE"), "schemas": sum(1 for item in nodes if item["kind"] == "API_SCHEMA")}}


def _asyncapi(document: dict[str, Any], source_path: str, diagnostics: list[dict[str, Any]]) -> dict[str, Any]:
    version = str(document.get("asyncapi") or "")
    if not (version.startswith("2.") or version.startswith("3.")):
        diagnostics.append({"code": "unsupported_version", "severity": "error", "message": f"Unsupported AsyncAPI version: {version or 'missing'}"})
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    schemas = document.get("components", {}).get("schemas", {})
    for name, schema in (schemas or {}).items():
        pointer = f"#/components/schemas/{name}"
        _resolve(document, schema, diagnostics)
        nodes.append(_node(f"asyncapi:schema:{name}", "EVENT_SCHEMA", str(name), _source(source_path, pointer), schema_name=str(name), ref=pointer))
    for name, server in (document.get("servers") or {}).items():
        url = str(server.get("url") if isinstance(server, dict) else server)
        nodes.append(_node(f"asyncapi:server:{name}", "BROKER_SERVER", str(name), _source(source_path, f"#/servers/{name}"), server=str(name), url=url, network_contacted=False))
    channels = document.get("channels") or {}
    for channel_name, raw_channel in channels.items():
        channel = _resolve(document, raw_channel, diagnostics)
        if not isinstance(channel, dict):
            continue
        channel_id = f"asyncapi:channel:{channel_name}"
        channel_pointer = f"#/channels/{str(channel_name).replace('~', '~0').replace('/', '~1')}"
        nodes.append(_node(channel_id, "EVENT_CHANNEL", str(channel_name), _source(source_path, channel_pointer), channel=str(channel_name), address=channel.get("address", channel_name)))
        operations: list[tuple[str, str, Any, str]] = []
        if version.startswith("2."):
            if "publish" in channel:
                operations.append(("producer", "publish", channel["publish"], f"{channel_pointer}/publish"))
            if "subscribe" in channel:
                operations.append(("consumer", "subscribe", channel["subscribe"], f"{channel_pointer}/subscribe"))
        for operation_name, raw_operation in (document.get("operations") or {}).items() if version.startswith("3.") else []:
            operation = _resolve(document, raw_operation, diagnostics)
            if not isinstance(operation, dict):
                continue
            operation_channel = operation.get("channel")
            if isinstance(operation_channel, dict) and "$ref" in operation_channel:
                try:
                    operation_channel = _pointer_get(document, operation_channel["$ref"])
                    operation_channel = operation_channel.get("address") if isinstance(operation_channel, dict) else operation_channel
                except (KeyError, ValueError):
                    operation_channel = None
            if operation_channel in {channel_name, channel.get("address")}:
                role = "producer" if str(operation.get("action")) == "send" else "consumer"
                operations.append((role, str(operation_name), operation, f"#/operations/{operation_name}"))
        for role, operation_name, raw_operation, operation_pointer in operations:
            operation = _resolve(document, raw_operation, diagnostics)
            operation_id = str(operation.get("operationId") or operation.get("summary") or operation_name) if isinstance(operation, dict) else operation_name
            node_id = f"asyncapi:{role}:{channel_name}:{operation_name}"
            kind = "EVENT_PRODUCER" if role == "producer" else "EVENT_CONSUMER"
            nodes.append(_node(node_id, kind, operation_id, _source(source_path, operation_pointer), operation_id=operation_id, channel=str(channel_name), role=role))
            if role == "producer":
                edges.append(_edge(f"{node_id}:channel", node_id, channel_id, "PRODUCES", _source(source_path, operation_pointer)))
            else:
                # Consumers are downstream of a channel. Keeping this edge
                # channel -> consumer makes bounded investigations follow the
                # event flow producer -> channel -> consumer.
                edges.append(_edge(f"{channel_id}:consumer:{operation_name}", channel_id, node_id, "CONSUMES", _source(source_path, operation_pointer)))
            messages = operation.get("message") if isinstance(operation, dict) else None
            if messages is None and isinstance(operation, dict):
                messages = operation.get("messages")
            if not isinstance(messages, list):
                messages = [messages] if messages else []
            for index, raw_message in enumerate(messages):
                message = _resolve(document, raw_message, diagnostics)
                if not isinstance(message, dict):
                    continue
                message_name = str(message.get("name") or message.get("title") or f"{operation_name}-message")
                message_id = f"asyncapi:message:{channel_name}:{message_name}"
                message_pointer = f"{operation_pointer}/message" if len(messages) == 1 else f"{operation_pointer}/messages/{index}"
                if not any(item["id"] == message_id for item in nodes):
                    nodes.append(_node(message_id, "EVENT_MESSAGE", message_name, _source(source_path, message_pointer), message_name=message_name))
                edges.append(_edge(f"{node_id}:message:{index}", node_id, message_id, "CARRIES_MESSAGE", _source(source_path, message_pointer)))
                payload = message.get("payload")
                if isinstance(payload, dict) and isinstance(payload.get("$ref"), str):
                    schema_name = _schema_name(payload["$ref"])
                    schema_id = f"asyncapi:schema:{schema_name}" if schema_name else None
                    if schema_id and any(item["id"] == schema_id for item in nodes):
                        edges.append(_edge(f"{message_id}:schema:{schema_name}", message_id, schema_id, "CARRIES_SCHEMA", _source(source_path, message_pointer)))
    return {"format": "asyncapi", "version": version, "nodes": nodes, "edges": edges, "diagnostics": diagnostics, "summary": {"channels": sum(1 for item in nodes if item["kind"] == "EVENT_CHANNEL"), "messages": sum(1 for item in nodes if item["kind"] == "EVENT_MESSAGE"), "producers": sum(1 for item in nodes if item["kind"] == "EVENT_PRODUCER"), "consumers": sum(1 for item in nodes if item["kind"] == "EVENT_CONSUMER")}}


def parse_boundary_spec(path: str | Path, adapter_id: str) -> dict[str, Any]:
    source = Path(path)
    document, format_name, diagnostics = _load(source)
    if adapter_id == "openapi":
        parsed = _openapi(document, str(source.resolve()), diagnostics)
    elif adapter_id == "asyncapi":
        parsed = _asyncapi(document, str(source.resolve()), diagnostics)
    else:
        raise ValueError(f"unsupported boundary adapter: {adapter_id}")
    parsed.update({"adapter_id": adapter_id, "document_format": format_name, "document": document})
    return parsed


def build_boundary_overlay(parsed: dict[str, Any], adapter_id: str, artifact_path: str, *, source_spec_path: str | None = None, project_root: str | Path | None = None, freshness: dict[str, Any] | None = None, enabled: bool = False) -> dict[str, Any]:
    source_path = source_spec_path or artifact_path
    nodes = copy.deepcopy(parsed.get("nodes") or [])
    for node in nodes:
        node["source"]["path"] = source_path
    return {
        "schema_version": BOUNDARY_OVERLAY_SCHEMA, "adapter_id": adapter_id, "evidence_class": "CONTRACT_CONFIRMED",
        "confidence": "confirmed_if_spec_exact", "freshness": freshness or {"status": "fresh", "verified": True},
        "source_spec": source_path, "spec_format": parsed.get("document_format"), "spec_version": parsed.get("version"),
        "nodes": nodes, "edges": copy.deepcopy(parsed.get("edges") or []), "diagnostics": list(parsed.get("diagnostics") or []),
        "summary": parsed.get("summary") or {}, "network_used": False, "privacy": {"mode": "local-only", "network_used": False, "external_urls_contacted": False},
        "enabled": enabled, "project_root": str(project_root) if project_root else None,
    }


def _normalized(value: Any) -> str:
    return str(value or "").replace("\\", "/").strip().lower()


def _canonical_candidates(graph: GraphDocument, boundary_node: dict[str, Any]) -> list[tuple[Any, str]]:
    props = boundary_node.get("properties") or {}
    kind = boundary_node.get("kind")
    candidates: list[tuple[Any, str]] = []
    for node in graph.nodes:
        node_props = node.properties or {}
        if props.get("semantic_id") and node_props.get("semantic_id") == props["semantic_id"]:
            candidates.append((node, "stable semantic ID"))
            continue
        source_file = props.get("source_file") or props.get("file")
        source_range = props.get("definition_range") or props.get("range")
        canonical_file = node_props.get("file") or node_props.get("path")
        canonical_range = node_props.get("definition_range") or node_props.get("range")
        if source_file and source_range and canonical_file and canonical_range and _normalized(source_file) == _normalized(canonical_file) and source_range == canonical_range:
            expected_kind = props.get("canonical_kind")
            if not expected_kind or expected_kind == node.kind:
                candidates.append((node, "exact file + range + kind"))
                continue
        if kind in {"HTTP_ROUTE", "API_OPERATION"}:
            path = props.get("path")
            method = _normalized(props.get("method"))
            route = node_props.get("route") or node_props.get("path") or node_props.get("api_path") or node_props.get("http_path")
            node_method = _normalized(node_props.get("method") or node_props.get("http_method"))
            if path and route and _normalized(route) == _normalized(path) and method and node_method == method:
                candidates.append((node, "exact route + method"))
                continue
            if props.get("operation_id") and node_props.get("operation_id") == props["operation_id"]:
                candidates.append((node, "exact operationId"))
                continue
        if kind == "EVENT_CHANNEL":
            channel = props.get("channel")
            node_channel = node_props.get("channel") or node_props.get("topic") or node_props.get("event_channel")
            if channel and node_channel and _normalized(channel) == _normalized(node_channel):
                candidates.append((node, "exact channel/topic"))
                continue
        name = _normalized(boundary_node.get("name"))
        node_name = _normalized(node.name)
        if name and node_name == name:
            candidates.append((node, "name-only candidate"))
    return candidates


def map_boundary_overlay(overlay: dict[str, Any], canonical_graph: GraphDocument) -> dict[str, Any]:
    result = copy.deepcopy(overlay)
    freshness = (result.get("freshness") or {}).get("status")
    for node in result.get("nodes", []):
        candidates = _canonical_candidates(canonical_graph, node)
        exact = [item for item in candidates if item[1] != "name-only candidate"]
        if len(exact) == 1:
            canonical, strategy = exact[0]
            if strategy == "exact operationId":
                node["mapping"] = {"status": "likely", "strategy": "operationId-only candidate; route/method evidence is absent", "canonical_node_id": None}
                node["confidence"] = "likely"
            else:
                node["mapping"] = {"status": "confirmed" if freshness == "fresh" else "stale", "strategy": strategy, "canonical_node_id": canonical.id if freshness == "fresh" else None}
                node["confidence"] = "confirmed" if freshness == "fresh" else "stale"
        elif len(exact) > 1:
            node["mapping"] = {"status": "ambiguous", "strategy": "multiple exact candidates", "canonical_node_id": None}
            node["confidence"] = "unresolved"
        elif candidates:
            node["mapping"] = {"status": "likely", "strategy": "name-only candidate; not confirmed", "canonical_node_id": None}
            node["confidence"] = "likely"
        else:
            node["mapping"] = {"status": "unresolved", "strategy": "no exact route/operationId/channel mapping", "canonical_node_id": None}
            node["confidence"] = "unresolved"
    for edge in result.get("edges", []):
        source = next((item for item in result["nodes"] if item.get("id") == edge.get("from")), None)
        target = next((item for item in result["nodes"] if item.get("id") == edge.get("to")), None)
        source_status = source.get("mapping", {}).get("status") if source else ("confirmed" if any(node.id == edge.get("from") for node in canonical_graph.nodes) else "unresolved")
        target_status = target.get("mapping", {}).get("status") if target else ("confirmed" if any(node.id == edge.get("to") for node in canonical_graph.nodes) else "unresolved")
        if source_status == target_status == "confirmed" and freshness == "fresh":
            edge.update({"resolution": "confirmed", "confidence": "confirmed", "confirmed": True})
        elif source_status in {"confirmed", "likely"} and target_status in {"confirmed", "likely"}:
            edge.update({"resolution": "likely", "confidence": "likely", "confirmed": False})
        else:
            edge.update({"resolution": "unresolved", "confidence": "unresolved", "confirmed": False})
    canonical_by_id = {
        node.get("mapping", {}).get("canonical_node_id"): node.get("id")
        for node in result.get("nodes", [])
        if node.get("mapping", {}).get("canonical_node_id")
    }
    canonical_links: list[dict[str, Any]] = []
    for edge in canonical_graph.edges:
        if edge.kind not in {"HTTP_CALLS", "MATCHES_ENDPOINT", "ROUTE_HANDLES"}:
            continue
        if edge.from_node not in canonical_by_id and edge.to_node not in canonical_by_id:
            continue
        canonical_links.append({
            "id": f"boundary:canonical:{edge.id}",
            "from": canonical_by_id.get(edge.from_node, edge.from_node),
            "to": canonical_by_id.get(edge.to_node, edge.to_node),
            "canonical_from": edge.from_node, "canonical_to": edge.to_node,
            "kind": edge.kind, "source": edge.source, "confidence": edge.confidence,
            "resolution": "confirmed" if freshness == "fresh" else "stale",
            "evidence_class": "CONTRACT_CONFIRMED",
        })
    result["canonical_links"] = canonical_links
    result["mapping_summary"] = {
        "confirmed": sum(1 for item in result.get("nodes", []) if item.get("mapping", {}).get("status") == "confirmed"),
        "likely": sum(1 for item in result.get("nodes", []) if item.get("mapping", {}).get("status") == "likely"),
        "unresolved": sum(1 for item in result.get("nodes", []) if item.get("mapping", {}).get("status") == "unresolved"),
        "ambiguous": sum(1 for item in result.get("nodes", []) if item.get("mapping", {}).get("status") == "ambiguous"),
    }
    return result
