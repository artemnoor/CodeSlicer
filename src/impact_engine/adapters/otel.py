"""Local OpenTelemetry/Jaeger runtime evidence importer.

The importer consumes already exported JSON only.  It never opens an OTLP
transport, starts a workload, or retains raw attributes.  Runtime evidence is
observational: an absent span is reported as not observed, never as proof of
absence.
"""
from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from impact_engine.models import GraphDocument

RUNTIME_OVERLAY_SCHEMA = "CodeSlicerRuntimeEvidenceOverlay/v1"
MAX_OTEL_FILE_BYTES = 32 * 1024 * 1024
MAX_OTEL_SPANS = 100_000
MAX_OTEL_DEPTH = 64
MAX_OTEL_ATTRIBUTES = 32
MAX_OTEL_ATTRIBUTE_BYTES = 512

_SENSITIVE = re.compile(r"(?:password|passwd|secret|token|authorization|cookie|set-cookie|request[-_.]?body|response[-_.]?body|api[-_.]?key|credential|private[-_.]?key)", re.I)
_ALLOWLIST = {
    "service.name", "service.version", "deployment.environment", "host.name",
    "http.request.method", "http.method", "http.route", "http.target", "url.path",
    "http.response.status_code", "http.status_code", "server.address",
    "server.port", "client.address", "client.port", "peer.service", "rpc.system",
    "rpc.service", "rpc.method", "db.system", "db.namespace", "db.operation.name",
    "db.operation", "db.collection.name", "messaging.system", "messaging.destination.name",
    "messaging.destination", "messaging.operation.type", "messaging.operation",
    "messaging.message.id", "code.filepath", "code.function.name", "code.lineno",
    "codeslicer.semantic_id", "codeslicer.definition_range", "codeslicer.canonical_kind", "http.request.id", "http.request.header.x-request-id", "span.kind",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _diag(code: str, message: str, severity: str = "warning") -> dict[str, str]:
    return {"code": code, "severity": severity, "message": message}


def _value(value: Any) -> Any:
    if isinstance(value, dict):
        for key in ("stringValue", "intValue", "doubleValue", "boolValue", "bytesValue"):
            if key in value:
                return value[key]
        return None
    return value


def _sanitize_attributes(raw: Any, diagnostics: list[dict[str, str]]) -> dict[str, Any]:
    pairs: list[tuple[str, Any]] = []
    if isinstance(raw, dict):
        pairs = [(str(key), value) for key, value in raw.items()]
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and "key" in item:
                pairs.append((str(item["key"]), _value(item.get("value"))) )
    result: dict[str, Any] = {}
    for key, raw_value in pairs:
        if _SENSITIVE.search(key) or key.lower() not in _ALLOWLIST:
            continue
        value = _value(raw_value)
        if isinstance(value, (dict, list)):
            continue
        if value is None:
            continue
        if key.lower() in {"url.full", "http.target"}:
            value = _normalize_path(value)
        text = str(value)
        if len(text.encode("utf-8")) > MAX_OTEL_ATTRIBUTE_BYTES:
            diagnostics.append(_diag("attribute_redacted", f"Attribute {key} exceeded the value limit and was redacted."))
            continue
        result[key] = value
        if len(result) >= MAX_OTEL_ATTRIBUTES:
            diagnostics.append(_diag("attribute_limit", "Attribute allowlist limit reached; remaining attributes were redacted."))
            break
    return result


def _attrs_to_map(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return {str(key): _value(value) for key, value in raw.items()}
    if isinstance(raw, list):
        return {str(item["key"]): _value(item.get("value")) for item in raw if isinstance(item, dict) and "key" in item}
    return {}


def _span_links(raw: Any, diagnostics: list[dict[str, str]], source: str) -> list[dict[str, Any]]:
    """Keep only well-formed span-link identity and sanitized link attributes."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        diagnostics.append(_diag("malformed_span_link", f"{source} span links must be an array."))
        return []
    links: list[dict[str, Any]] = []
    for index, link in enumerate(raw):
        if not isinstance(link, dict):
            diagnostics.append(_diag("malformed_span_link", f"{source} span link {index} is not an object."))
            continue
        trace_id = link.get("traceId") or link.get("traceID")
        span_id = link.get("spanId") or link.get("spanID")
        if not isinstance(trace_id, (str, int)) or not str(trace_id).strip() or not isinstance(span_id, (str, int)) or not str(span_id).strip():
            diagnostics.append(_diag("malformed_span_link", f"{source} span link {index} lacks a valid traceId/spanId; it remains unresolved."))
            continue
        links.append({
            "trace_id": str(trace_id),
            "span_id": str(span_id),
            "ref_type": str(link.get("refType") or link.get("ref_type") or "LINK"),
            "attributes": _sanitize_attributes(link.get("attributes"), diagnostics),
        })
    return links


def _kind(value: Any) -> str:
    if isinstance(value, int):
        return {1: "internal", 2: "server", 3: "client", 4: "producer", 5: "consumer"}.get(value, "internal")
    text = str(value or "internal").lower().replace("span_kind_", "").replace("producer", "producer")
    return text


def _id_part(value: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9_.:-]+", "_", str(value or "unknown"))
    return text[:160]


def _time_ns(value: Any, unit: str = "ns") -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if unit == "us":
        return number * 1_000
    if unit == "ms":
        return number * 1_000_000
    return number


def _normalize_path(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = text.split("?", 1)[0].split("#", 1)[0]
    if not text.startswith("/"):
        text = "/" + text
    text = re.sub(r"/+/", "/", text)
    return text.rstrip("/") or "/"


def _explicit_http_relation(client: dict[str, Any], server: dict[str, Any]) -> str | None:
    same_trace = client.get("trace_id") == server.get("trace_id")
    if same_trace and server.get("parent_span_id") == client.get("span_id"):
        return "explicit parent-child"
    client_key = {"trace_id": client.get("trace_id"), "span_id": client.get("span_id")}
    server_key = {"trace_id": server.get("trace_id"), "span_id": server.get("span_id")}
    for link in server.get("links") or []:
        if link.get("trace_id") == client_key["trace_id"] and link.get("span_id") == client_key["span_id"]:
            return "explicit span link"
    for link in client.get("links") or []:
        if link.get("trace_id") == server_key["trace_id"] and link.get("span_id") == server_key["span_id"]:
            return "explicit span link"
    client_ids = set(str(value) for value in client.get("correlation_ids") or [])
    server_ids = set(str(value) for value in server.get("correlation_ids") or [])
    if client_ids and client_ids.intersection(server_ids):
        return "explicit correlation identifier"
    return None


def _http(span: dict[str, Any]) -> tuple[str, str]:
    attrs = span.get("attributes") or {}
    method = str(attrs.get("http.request.method") or attrs.get("http.method") or "").upper()
    route = attrs.get("http.route") or attrs.get("url.path") or attrs.get("http.target")
    return method, _normalize_path(route)


def _make_node(node_id: str, kind: str, name: str, **properties: Any) -> dict[str, Any]:
    return {
        "id": node_id, "kind": kind, "name": name, "properties": properties,
        "evidence_class": "RUNTIME_OBSERVED", "observed": True,
    }


def _make_edge(edge_id: str, source: str, target: str, kind: str, **properties: Any) -> dict[str, Any]:
    return {
        "id": edge_id, "from": source, "to": target, "kind": kind,
        "evidence_class": "RUNTIME_OBSERVED", "confidence": "confirmed",
        "resolution": "confirmed", "confirmed": True, "observed": True,
        "properties": properties,
    }


def _load_json(path: Path) -> tuple[dict[str, Any], list[dict[str, str]]]:
    diagnostics: list[dict[str, str]] = []
    if path.stat().st_size > MAX_OTEL_FILE_BYTES:
        return {}, [_diag("oversized_artifact", f"Trace exceeds {MAX_OTEL_FILE_BYTES} bytes.", "error")]
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        return {}, [_diag("invalid_encoding", "Trace must be UTF-8 JSON.", "error")]
    except json.JSONDecodeError as exc:
        return {}, [_diag("malformed_json", f"Trace JSON is malformed: {exc.msg}.", "error")]
    if not isinstance(document, dict):
        return {}, [_diag("unsupported_format", "Trace root must be a JSON object.", "error")]
    return document, diagnostics


def _otlp_spans(document: dict[str, Any], diagnostics: list[dict[str, str]]) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    for resource_group in document.get("resourceSpans") or []:
        if not isinstance(resource_group, dict):
            diagnostics.append(_diag("invalid_resource_spans", "A resourceSpans item was skipped because it was not an object."))
            continue
        resource_attrs = _attrs_to_map((resource_group.get("resource") or {}).get("attributes"))
        service = str(resource_attrs.get("service.name") or "unknown-service")
        for scope_group in resource_group.get("scopeSpans") or resource_group.get("instrumentationLibrarySpans") or []:
            if not isinstance(scope_group, dict):
                diagnostics.append(_diag("invalid_scope_spans", "A scopeSpans item was skipped because it was not an object."))
                continue
            for raw in scope_group.get("spans") or []:
                if not isinstance(raw, dict):
                    continue
                attrs = _attrs_to_map(raw.get("attributes"))
                attrs = {**resource_attrs, **attrs}
                spans.append({
                    "trace_id": raw.get("traceId"), "span_id": raw.get("spanId"),
                    "parent_span_id": raw.get("parentSpanId"), "name": raw.get("name") or "unnamed",
                    "kind": _kind(raw.get("kind")), "service": service,
                    "attributes": attrs, "start_ns": _time_ns(raw.get("startTimeUnixNano")),
                    "end_ns": _time_ns(raw.get("endTimeUnixNano")),
                    "status": (raw.get("status") or {}).get("code") if isinstance(raw.get("status"), dict) else raw.get("status"),
                    "links": _span_links(raw.get("links"), diagnostics, "OTLP"),
                })
    return spans


def _jaeger_spans(document: dict[str, Any], diagnostics: list[dict[str, str]]) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    data = document.get("data") if isinstance(document.get("data"), list) else []
    processes: dict[str, dict[str, Any]] = {}
    for trace in data:
        if not isinstance(trace, dict):
            continue
        if isinstance(trace.get("processes"), dict):
            processes.update(trace.get("processes") or {})
    for trace in data:
        if not isinstance(trace, dict):
            continue
        for raw in trace.get("spans") or []:
            if not isinstance(raw, dict):
                continue
            tags = _attrs_to_map(raw.get("tags"))
            process = processes.get(str(raw.get("processID") or ""), {})
            process_tags = _attrs_to_map(process.get("tags")) if isinstance(process, dict) else {}
            attrs = {**process_tags, **tags}
            references = raw.get("references")
            parent = next((ref.get("spanID") for ref in references or [] if isinstance(ref, dict) and ref.get("refType") == "CHILD_OF"), None)
            start_ns = _time_ns(raw.get("startTime"), "us")
            try:
                duration_ns = int(raw.get("duration", 0)) * 1_000
            except (TypeError, ValueError):
                duration_ns = 0
                diagnostics.append(_diag("invalid_duration", "A Jaeger span had an invalid duration; zero was used."))
            spans.append({
                "trace_id": raw.get("traceID") or trace.get("traceID"), "span_id": raw.get("spanID"),
                "parent_span_id": parent, "name": raw.get("operationName") or "unnamed",
                "kind": _kind(attrs.get("span.kind") or "internal"),
                "service": str(process.get("serviceName") or attrs.get("service.name") or "unknown-service"),
                "attributes": attrs, "start_ns": start_ns,
                "end_ns": start_ns + duration_ns if start_ns is not None else None,
                "status": attrs.get("otel.status_code") or attrs.get("status.code"),
                "links": _span_links(references, diagnostics, "Jaeger"),
            })
    return spans


def parse_otel_document(document: dict[str, Any]) -> dict[str, Any]:
    """Normalize an already decoded OTLP/Jaeger document.

    Keeping this boundary separate from file I/O lets the loopback OTLP/HTTP
    receiver pass data directly into the same strict allowlist.  In
    particular, it never needs to persist a raw trace just to parse it.
    """
    diagnostics: list[dict[str, str]] = []
    if not document:
        return {"format": None, "spans": [], "diagnostics": diagnostics, "summary": {"spans": 0, "traces": 0, "services": 0}}
    if "resourceSpans" in document:
        format_name, spans = "otlp-json", _otlp_spans(document, diagnostics)
    elif isinstance(document.get("data"), list) and any(isinstance(item, dict) and "spans" in item for item in document["data"]):
        format_name, spans = "jaeger-json", _jaeger_spans(document, diagnostics)
    else:
        return {"format": None, "spans": [], "diagnostics": [_diag("unsupported_format", "Supported formats are OTLP JSON export and Jaeger JSON export.", "error")], "summary": {"spans": 0, "traces": 0, "services": 0}}
    if len(spans) > MAX_OTEL_SPANS:
        diagnostics.append(_diag("span_limit", f"Trace contains more than {MAX_OTEL_SPANS} spans; import was bounded.", "error"))
        spans = spans[:MAX_OTEL_SPANS]
    normalized: list[dict[str, Any]] = []
    for span in spans:
        span["attributes"] = _sanitize_attributes(span.get("attributes"), diagnostics)
        span["correlation_ids"] = [span["attributes"][key] for key in ("http.request.id", "http.request.header.x-request-id") if span["attributes"].get(key)]
        if not span.get("trace_id") or not span.get("span_id"):
            diagnostics.append(_diag("invalid_span", "A span without trace_id or span_id was skipped."))
            continue
        normalized.append(span)
    spans = normalized
    by_key = {(str(span["trace_id"]), str(span["span_id"])): span for span in spans}
    depth_limited = False
    for span in spans:
        depth = 0
        parent = span.get("parent_span_id")
        seen: set[str] = set()
        while parent and (str(span["trace_id"]), str(parent)) in by_key and str(parent) not in seen:
            seen.add(str(parent)); depth += 1
            parent = by_key[(str(span["trace_id"]), str(parent))].get("parent_span_id")
            if depth >= MAX_OTEL_DEPTH:
                break
        span["depth"] = depth
        if depth >= MAX_OTEL_DEPTH and span.get("parent_span_id"):
            span["parent_span_id"] = None
            depth_limited = True
    if depth_limited:
        diagnostics.append(_diag("depth_limit", f"Parent traversal was bounded at {MAX_OTEL_DEPTH} levels."))
    return {
        "format": format_name, "spans": spans, "diagnostics": diagnostics,
        "summary": {"spans": len(spans), "traces": len({span["trace_id"] for span in spans}), "services": len({span["service"] for span in spans})},
    }


def parse_otel_trace(path: str | Path) -> dict[str, Any]:
    """Parse a local JSON export without opening a runtime transport."""
    source = Path(path).resolve()
    document, diagnostics = _load_json(source)
    if not document:
        return {"format": None, "spans": [], "diagnostics": diagnostics, "summary": {"spans": 0, "traces": 0, "services": 0}}
    parsed = parse_otel_document(document)
    # I/O diagnostics (encoding, size) precede format diagnostics.
    parsed["diagnostics"] = diagnostics + list(parsed.get("diagnostics") or [])
    return parsed


def build_otel_overlay(parsed: dict[str, Any], artifact_path: str, *, project_root: str | Path | None = None, freshness: dict[str, Any] | None = None, enabled: bool = False) -> dict[str, Any]:
    diagnostics = list(parsed.get("diagnostics") or [])
    spans = list(parsed.get("spans") or [])
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    node_ids: set[str] = set()
    span_by_id: dict[str, dict[str, Any]] = {}
    service_ids: dict[str, str] = {}
    topic_ids: dict[str, str] = {}

    def add(node: dict[str, Any]) -> None:
        if node["id"] not in node_ids:
            nodes.append(node); node_ids.add(node["id"])

    for span in spans:
        trace_id, span_id = str(span["trace_id"]), str(span["span_id"])
        span_node_id = f"otel:span:{trace_id}:{span_id}"
        span_by_id[f"{trace_id}:{span_id}"] = span
        service = str(span.get("service") or "unknown-service")
        service_id = service_ids.setdefault(service, f"otel:service:{_id_part(service)}")
        add(_make_node(service_id, "SERVICE", service, service_name=service, trace_id=trace_id, source_artifact_path=artifact_path))
        method, route = _http(span)
        attrs = span.get("attributes") or {}
        definition_range = attrs.get("codeslicer.definition_range")
        if isinstance(definition_range, str):
            try:
                definition_range = json.loads(definition_range)
            except json.JSONDecodeError:
                definition_range = None
        kind = str(span.get("kind") or "internal")
        add(_make_node(span_node_id, "SPAN", str(span.get("name") or "unnamed"), trace_id=trace_id, span_id=span_id, parent_span_id=span.get("parent_span_id"), depth=span.get("depth", 0), service_name=service, operation_name=str(span.get("name") or ""), method=method, route=route, server_side=kind == "server", semantic_id=attrs.get("codeslicer.semantic_id"), source_file=attrs.get("code.filepath"), definition_range=definition_range, canonical_kind=attrs.get("codeslicer.canonical_kind"), correlation_ids=[attrs[key] for key in ("http.request.id", "http.request.header.x-request-id") if attrs.get(key)], span_links=span.get("links") or [], start_time_ns=span.get("start_ns"), end_time_ns=span.get("end_ns"), status=span.get("status"), attributes=attrs, source_artifact_path=artifact_path))
        edges.append(_make_edge(f"otel:service-span:{service_id}:{span_id}", service_id, span_node_id, "SERVICE_SPAN", trace_id=trace_id, span_id=span_id))
        if method or route:
            request_id = f"otel:http:{trace_id}:{span_id}"
            add(_make_node(request_id, "HTTP_REQUEST", f"{method} {route}".strip(), trace_id=trace_id, span_id=span_id, method=method, route=route, service_name=service, server_side=kind == "server", source_artifact_path=artifact_path))
            edges.append(_make_edge(f"otel:span-http:{span_id}", span_node_id, request_id, "OBSERVED_HTTP", trace_id=trace_id, span_id=span_id))
            if route and kind == "server":
                route_id = f"otel:route:{method}:{route}"
                add(_make_node(route_id, "HTTP_ROUTE", f"{method} {route}", method=method, route=route, service_name=service, server_side=True, trace_id=trace_id, span_id=span_id, source_artifact_path=artifact_path))
                edges.append(_make_edge(f"otel:http-route:{span_id}", request_id, route_id, "OBSERVED_ROUTE", trace_id=trace_id, span_id=span_id))
        db_operation = attrs.get("db.operation.name") or attrs.get("db.operation")
        if db_operation or attrs.get("db.system"):
            db_id = f"otel:db:{trace_id}:{span_id}"
            add(_make_node(db_id, "DB_OPERATION", str(db_operation or span.get("name")), db_system=attrs.get("db.system"), operation=str(db_operation or span.get("name")), service_name=service, trace_id=trace_id, span_id=span_id, source_artifact_path=artifact_path))
            edges.append(_make_edge(f"otel:span-db:{span_id}", span_node_id, db_id, "HANDLES_DB", trace_id=trace_id, span_id=span_id))
        topic = attrs.get("messaging.destination.name") or attrs.get("messaging.destination")
        if topic:
            topic = str(topic)
            topic_id = topic_ids.setdefault(topic, f"otel:topic:{_id_part(topic)}")
            add(_make_node(topic_id, "MESSAGING_TOPIC", topic, topic=topic, messaging_system=attrs.get("messaging.system"), source_artifact_path=artifact_path))
            role = str(attrs.get("messaging.operation.type") or attrs.get("messaging.operation") or kind).lower()
            role_kind = "producer" if role in {"producer", "send", "publish"} or kind == "producer" else "consumer" if role in {"consumer", "receive", "process", "subscribe"} or kind == "consumer" else "unknown"
            if role_kind == "producer":
                producer_id = f"otel:producer:{trace_id}:{span_id}"
                add(_make_node(producer_id, "EVENT_PRODUCER", str(span.get("name")), trace_id=trace_id, span_id=span_id, topic=topic, service_name=service, source_artifact_path=artifact_path))
                edges.append(_make_edge(f"otel:producer-topic:{span_id}", producer_id, topic_id, "PRODUCES_TOPIC", trace_id=trace_id, span_id=span_id))
            elif role_kind == "consumer":
                consumer_id = f"otel:consumer:{trace_id}:{span_id}"
                add(_make_node(consumer_id, "EVENT_CONSUMER", str(span.get("name")), trace_id=trace_id, span_id=span_id, topic=topic, service_name=service, source_artifact_path=artifact_path))
                edges.append(_make_edge(f"otel:topic-consumer:{span_id}", topic_id, consumer_id, "CONSUMES_TOPIC", trace_id=trace_id, span_id=span_id))
    for span in spans:
        trace_id, span_id = str(span["trace_id"]), str(span["span_id"])
        current_id = f"otel:span:{trace_id}:{span_id}"
        parent_id = span.get("parent_span_id")
        if parent_id and f"{trace_id}:{parent_id}" in span_by_id:
            edges.append(_make_edge(f"otel:parent:{trace_id}:{parent_id}:{span_id}", f"otel:span:{trace_id}:{parent_id}", current_id, "PARENT_CHILD", trace_id=trace_id, parent_span_id=parent_id, span_id=span_id))
        elif parent_id:
            diagnostics.append(_diag("orphan_parent", f"Parent span {parent_id} was not present; relationship remains unresolved."))
    http_spans = [span for span in spans if _http(span)[0] and _http(span)[1]]
    for client in http_spans:
        if str(client.get("kind")) not in {"client", "producer"}:
            continue
        method, route = _http(client)
        for server in http_spans:
            if str(server.get("kind")) != "server":
                continue
            server_method, server_route = _http(server)
            if method == server_method and route == server_route:
                relation = _explicit_http_relation(client, server)
                if relation:
                    edges.append(_make_edge(f"otel:http-correlation:{client['span_id']}:{server['span_id']}", f"otel:span:{client['trace_id']}:{client['span_id']}", f"otel:span:{server['trace_id']}:{server['span_id']}", "HTTP_CLIENT_SERVER", trace_id=client["trace_id"], client_span_id=client["span_id"], server_span_id=server["span_id"], method=method, route=route, correlation=relation))
    return {
        "schema_version": RUNTIME_OVERLAY_SCHEMA, "adapter_id": "otel", "evidence_class": "RUNTIME_OBSERVED",
        "confidence": "confirmed_if_observed", "freshness": freshness or {"status": "fresh", "verified": True},
        "format": parsed.get("format"), "source_artifact_path": artifact_path,
        "nodes": nodes, "edges": edges, "diagnostics": diagnostics, "summary": parsed.get("summary") or {},
        "network_used": False, "privacy": {"mode": "local-only", "network_used": False, "raw_attributes_stored": False, "redaction": "allowlist"},
        "enabled": enabled, "project_root": str(project_root) if project_root else None,
    }


def _normalized(value: Any) -> str:
    text = str(value or "").replace("\\", "/").strip().lower()
    if not text:
        return ""
    return text.rstrip("/") or "/"


def _candidates(graph: GraphDocument, runtime_node: dict[str, Any]) -> list[tuple[Any, str]]:
    props = runtime_node.get("properties") or {}
    candidates: list[tuple[Any, str]] = []
    for node in graph.nodes:
        node_props = node.properties or {}
        method, route = str(props.get("method") or "").upper(), _normalized(props.get("route"))
        node_method = str(node_props.get("method") or node_props.get("http_method") or "").upper()
        node_route = _normalized(node_props.get("route") or node_props.get("path") or node_props.get("api_path"))
        node_role = _normalized(node_props.get("role") or node_props.get("boundary_category") or node_props.get("runtime_role"))
        client_node = node_role in {"client", "http", "frontend", "frontend_backend", "http_client"} or node_props.get("is_http_client") is True or node.kind in {"HTTP_CLIENT_CALL", "HTTP_REQUEST"}
        server_side = props.get("server_side") is True
        client_http_observation = bool(method or route) and not server_side and runtime_node.get("kind") in {"SPAN", "HTTP_REQUEST"}
        if client_http_observation and not client_node:
            # A client HTTP observation cannot confirm a backend route or
            # arbitrary symbol.  It may only use strong evidence when the
            # canonical node is explicitly a frontend/client node.
            continue
        if props.get("semantic_id") and props.get("semantic_id") == node_props.get("semantic_id"):
            candidates.append((node, "stable semantic ID")); continue
        source_file = props.get("source_file") or props.get("file")
        source_range = props.get("definition_range") or props.get("range")
        node_file = node_props.get("file") or node_props.get("path")
        node_range = node_props.get("definition_range") or node_props.get("range")
        if source_file and source_range and props.get("canonical_kind") and node_file and node_range and _normalized(source_file) == _normalized(node_file) and source_range == node_range and props["canonical_kind"] == node.kind:
            candidates.append((node, "exact file + complete range + kind")); continue
        if server_side and method and route and node_method == method and node_route == route and not client_node:
            candidates.append((node, "exact HTTP method + normalized route")); continue
        service = _normalized(props.get("service_name"))
        operation = _normalized(props.get("operation_name"))
        node_service = _normalized(node_props.get("service_name") or node_props.get("service"))
        node_operation = _normalized(node_props.get("operation_name") or node_props.get("operation"))
        if service and operation and node_service == service and node_operation == operation and (server_side or (not server_side and client_node)):
            candidates.append((node, "exact normalized service + operation metadata")); continue
        if (route and node_route == route) or (service and node_service == service) or _normalized(runtime_node.get("name")) == _normalized(node.name):
            candidates.append((node, "weak runtime candidate"))
    return candidates


def map_otel_overlay(overlay: dict[str, Any], canonical_graph: GraphDocument) -> dict[str, Any]:
    result = copy.deepcopy(overlay)
    freshness = (result.get("freshness") or {}).get("status")
    for node in result.get("nodes", []):
        candidates = _candidates(canonical_graph, node)
        exact = [item for item in candidates if item[1] != "weak runtime candidate"]
        if len(exact) == 1:
            canonical, strategy = exact[0]
            if freshness == "fresh":
                node["mapping"] = {"status": "confirmed", "strategy": strategy, "canonical_node_id": canonical.id}
                node["confidence"] = "confirmed"
            else:
                node["mapping"] = {"status": "stale", "strategy": strategy, "canonical_node_id": None}
                node["confidence"] = "stale"
        elif len(exact) > 1:
            node["mapping"] = {"status": "ambiguous", "strategy": "multiple exact candidates", "canonical_node_id": None}
            node["confidence"] = "unresolved"
        elif candidates:
            node["mapping"] = {"status": "likely", "strategy": "weak runtime candidate; not confirmed", "canonical_node_id": None}
            node["confidence"] = "likely"
        else:
            node["mapping"] = {"status": "unresolved", "strategy": "not observed in canonical graph", "canonical_node_id": None}
            node["confidence"] = "unresolved"
    for edge in result.get("edges", []):
        source = next((node for node in result["nodes"] if node.get("id") == edge.get("from")), None)
        target = next((node for node in result["nodes"] if node.get("id") == edge.get("to")), None)
        if source and target and source.get("mapping", {}).get("status") == target.get("mapping", {}).get("status") == "confirmed" and freshness == "fresh":
            edge["resolution"] = "confirmed"
        elif source and target and source.get("mapping", {}).get("status") in {"confirmed", "likely"} and target.get("mapping", {}).get("status") in {"confirmed", "likely"}:
            edge.update({"resolution": "likely", "confirmed": False, "confidence": "likely"})
        else:
            edge.update({"resolution": "unresolved", "confirmed": False, "confidence": "unresolved"})
    result["mapping_summary"] = {
        key: sum(1 for node in result.get("nodes", []) if node.get("mapping", {}).get("status") == key)
        for key in ("confirmed", "likely", "unresolved", "ambiguous", "stale")
    }
    return result
