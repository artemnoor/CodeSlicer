from __future__ import annotations

import json
import threading
from pathlib import Path
from urllib.request import Request, urlopen

import pytest

from impact_engine.adapters.otel import MAX_OTEL_FILE_BYTES, build_otel_overlay, map_otel_overlay, parse_otel_trace
from impact_engine.adapters.registry import AdapterRegistry
from impact_engine.local_api import LocalApiState, create_server
from impact_engine.models import GraphDocument, Node
from impact_engine.review import build_review_report


FIXTURES = Path(__file__).parent / "fixtures" / "otel"


def test_otlp_fixture_builds_observed_runtime_chain_and_redacts_secrets():
    parsed = parse_otel_trace(FIXTURES / "frontend_python_db_queue.json")
    overlay = build_otel_overlay(parsed, str((FIXTURES / "frontend_python_db_queue.json").resolve()))
    assert parsed["format"] == "otlp-json"
    assert parsed["summary"] == {"spans": 5, "traces": 1, "services": 3}
    assert overlay["evidence_class"] == "RUNTIME_OBSERVED"
    assert overlay["privacy"]["raw_attributes_stored"] is False
    assert "SHOULD_NOT_APPEAR" not in json.dumps(overlay)
    assert any(edge["kind"] == "PARENT_CHILD" for edge in overlay["edges"])
    assert any(edge["kind"] == "HTTP_CLIENT_SERVER" for edge in overlay["edges"])
    assert any(edge["kind"] == "HANDLES_DB" for edge in overlay["edges"])
    producer = next(node["id"] for node in overlay["nodes"] if node["kind"] == "EVENT_PRODUCER")
    topic = next(node["id"] for node in overlay["nodes"] if node["kind"] == "MESSAGING_TOPIC")
    consumer = next(node["id"] for node in overlay["nodes"] if node["kind"] == "EVENT_CONSUMER")
    assert any(edge["from"] == producer and edge["to"] == topic for edge in overlay["edges"])
    assert any(edge["from"] == topic and edge["to"] == consumer for edge in overlay["edges"])


def test_jaeger_json_is_supported():
    parsed = parse_otel_trace(FIXTURES / "react_csharp_queue_jaeger.json")
    assert parsed["format"] == "jaeger-json"
    assert parsed["summary"]["spans"] == 4
    assert parsed["summary"]["services"] == 3
    consumer = next(span for span in parsed["spans"] if span["span_id"] == "1000000000000004")
    assert any(link["ref_type"] == "FOLLOWS_FROM" and link["span_id"] == "1000000000000003" for link in consumer["links"])


def test_otlp_span_links_confirm_only_linked_http_pairs_and_redact_link_attributes():
    parsed = parse_otel_trace(FIXTURES / "otlp_span_links.json")
    overlay = build_otel_overlay(parsed, str(FIXTURES / "otlp_span_links.json"))
    correlations = [edge for edge in overlay["edges"] if edge["kind"] == "HTTP_CLIENT_SERVER"]
    assert len(correlations) == 2
    assert {(edge["properties"]["client_span_id"], edge["properties"]["server_span_id"]) for edge in correlations} == {
        ("link-client-1", "link-server-1"), ("link-client-2", "link-server-2")
    }
    assert all(edge["properties"]["correlation"] == "explicit span link" for edge in correlations)
    assert not any(edge["kind"] == "PARENT_CHILD" for edge in overlay["edges"])
    assert any(link["attributes"].get("http.request.id") == "request-1" for span in parsed["spans"] for link in span["links"])
    assert "SHOULD_NOT_APPEAR" not in json.dumps(overlay)
    assert any(item["code"] == "malformed_span_link" for item in parsed["diagnostics"])


def test_missing_span_links_never_create_http_client_server_edge():
    parsed = parse_otel_trace(FIXTURES / "otlp_span_links.json")
    for span in parsed["spans"]:
        span["links"] = []
    overlay = build_otel_overlay(parsed, str(FIXTURES / "otlp_span_links.json"))
    assert not [edge for edge in overlay["edges"] if edge["kind"] == "HTTP_CLIENT_SERVER"]


def test_runtime_mapping_requires_strong_evidence(tmp_path):
    parsed = parse_otel_trace(FIXTURES / "frontend_python_db_queue.json")
    overlay = build_otel_overlay(parsed, str(FIXTURES / "trace.json"), freshness={"status": "fresh", "verified": True})
    graph = GraphDocument(nodes=[
        Node("route", "ROUTE", "orders", {"route": "/api/orders", "method": "GET"}),
        Node("weak", "FUNCTION", "orders-api", {"service": "orders-api"}),
    ])
    mapped = map_otel_overlay(overlay, graph)
    route = next(node for node in mapped["nodes"] if node["kind"] == "HTTP_ROUTE")
    assert route["mapping"]["status"] == "confirmed"
    service = next(node for node in mapped["nodes"] if node["kind"] == "SERVICE" and node["name"] == "orders-api")
    assert service["mapping"]["status"] in {"likely", "unresolved"}
    client_spans = [node for node in mapped["nodes"] if node["kind"] == "SPAN" and node["properties"].get("server_side") is False]
    assert client_spans
    assert all(node["mapping"]["status"] != "confirmed" for node in client_spans)

    client_overlay = build_otel_overlay(parsed, str(FIXTURES / "frontend_python_db_queue.json"), freshness={"status": "fresh", "verified": True})
    client_span = next(node for node in client_overlay["nodes"] if node["kind"] == "SPAN" and node["properties"].get("server_side") is False)
    client_span["properties"]["semantic_id"] = "backend-route-semantic-id"
    backend_graph = GraphDocument(nodes=[Node("backend", "FUNCTION", "orders", {"semantic_id": "backend-route-semantic-id"})])
    mapped_client = map_otel_overlay(client_overlay, backend_graph)
    assert next(node for node in mapped_client["nodes"] if node["id"] == client_span["id"])["mapping"]["status"] != "confirmed"


def test_duplicate_http_requests_do_not_create_cross_product_correlations():
    parsed = parse_otel_trace(FIXTURES / "duplicate_http_requests.json")
    overlay = build_otel_overlay(parsed, str(FIXTURES / "duplicate_http_requests.json"))
    correlations = [edge for edge in overlay["edges"] if edge["kind"] == "HTTP_CLIENT_SERVER"]
    assert len(correlations) == 2
    assert {(edge["properties"]["client_span_id"], edge["properties"]["server_span_id"]) for edge in correlations} == {
        ("c-client-1", "c-server-1"), ("c-client-2", "c-server-2")
    }
    assert all(edge["properties"]["correlation"] == "explicit parent-child" for edge in correlations)
    for span in parsed["spans"]:
        span["parent_span_id"] = None
    no_explicit = build_otel_overlay(parsed, str(FIXTURES / "duplicate_http_requests.json"))
    assert not [edge for edge in no_explicit["edges"] if edge["kind"] == "HTTP_CLIENT_SERVER"]


def test_stale_trace_is_context_only_and_review_is_unchanged(tmp_path):
    source = tmp_path / "trace.json"
    source.write_text((FIXTURES / "frontend_python_db_queue.json").read_text(encoding="utf-8"), encoding="utf-8")
    registry = AdapterRegistry(tmp_path)
    imported = registry.import_artifact("otel", source.resolve())
    assert imported["adapter"]["status"] == "imported"
    assert imported["adapter"]["spans"] == 5
    assert imported["adapter"]["traces"] == 1
    assert imported["adapter"]["services"] == 3
    registry.set_enabled("otel", True)
    before = build_review_report(str(tmp_path), graph=GraphDocument(metadata={"project_path": str(tmp_path)}), diff_text="", refresh="never")
    source.write_text(source.read_text(encoding="utf-8").replace("orders-api", "orders-api-v2"), encoding="utf-8")
    assert registry.status("otel")["status"] == "stale"
    overlay = registry.overlay("otel")
    assert overlay["freshness"]["status"] == "stale"
    after = build_review_report(str(tmp_path), graph=GraphDocument(metadata={"project_path": str(tmp_path)}), diff_text="", refresh="never")
    assert (before["risk"], before["top_impacts"], before["test_recommendations"]) == (after["risk"], after["top_impacts"], after["test_recommendations"])


def test_invalid_oversized_and_nonlocal_inputs_are_diagnostic_or_rejected(tmp_path):
    registry = AdapterRegistry(tmp_path)
    with pytest.raises(ValueError, match="absolute local"):
        registry.import_artifact("otel", "trace.json")
    with pytest.raises(ValueError, match="absolute local"):
        registry.import_artifact("otel", "https://example.test/trace.json")
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{not json", encoding="utf-8")
    result = registry.import_artifact("otel", malformed.resolve())
    assert result["adapter"]["status"] == "error"
    assert any(item["code"] == "malformed_json" for item in result["overlay"]["diagnostics"])
    unsupported = tmp_path / "unsupported.json"
    unsupported.write_text(json.dumps({"spans": []}), encoding="utf-8")
    result = registry.import_artifact("otel", unsupported.resolve())
    assert any(item["code"] == "unsupported_format" for item in result["overlay"]["diagnostics"])
    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b"{" + b"x" * MAX_OTEL_FILE_BYTES)
    result = registry.import_artifact("otel", oversized.resolve())
    assert any(item["code"] == "oversized_artifact" for item in result["overlay"]["diagnostics"])


def test_otel_api_lifecycle_and_privacy(tmp_path):
    state = LocalApiState(str(tmp_path), "support_packs")
    server = create_server("127.0.0.1", 0, str(tmp_path), state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def call(path, payload=None):
        request = Request(f"http://127.0.0.1:{server.server_port}{path}", method="POST" if payload is not None else "GET", data=json.dumps(payload).encode() if payload is not None else None, headers={"Content-Type": "application/json", "X-CodeSlicer-Session": server.session_token} if payload is not None else {})
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read())

    try:
        initial = call("/api/adapters")
        assert any(item["id"] == "otel" and item["enabled"] is False for item in initial["adapters"])
        imported = call("/api/adapters/otel/import", {"project_path": str(tmp_path), "artifact_path": str((FIXTURES / "frontend_python_db_queue.json").resolve())})
        assert imported["privacy"]["network_used"] is False
        enabled = call("/api/adapters/otel/enable", {"project_path": str(tmp_path)})
        assert enabled["adapter"]["status"] == "ready"
        architecture = call("/api/architecture", {"project_path": str(tmp_path)})
        assert architecture["otel"]["spans"] == 5
        assert architecture["otel"]["privacy"]["raw_attributes_stored"] is False
        assert call("/api/adapters/otel/disable", {"project_path": str(tmp_path)})["status"] == "ok"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_otel_loopback_receiver_sanitizes_before_persisting(tmp_path):
    state = LocalApiState(str(tmp_path), "support_packs")
    server = create_server("127.0.0.1", 0, str(tmp_path), state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def call(path, payload):
        request = Request(f"http://127.0.0.1:{server.server_port}{path}", method="POST", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", "X-CodeSlicer-Session": server.session_token})
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read())

    try:
        enabled = call("/api/adapters/otel/live-enable", {"project_path": str(tmp_path)})
        assert enabled["receiver"]["enabled"] is True
        payload = json.loads((FIXTURES / "frontend_python_db_queue.json").read_text(encoding="utf-8"))
        # Sensitive fields must never survive the receiver -> overlay path.
        payload["resourceSpans"][0]["resource"]["attributes"].append({"key": "authorization", "value": {"stringValue": "Bearer must-not-persist"}})
        accepted = call("/v1/traces", payload)
        assert accepted["status"] == "accepted"
        assert accepted["raw_payload_stored"] is False
        stored = tmp_path / ".codeslicer" / "artifacts" / "otel" / "trace.json"
        text = stored.read_text(encoding="utf-8")
        assert "must-not-persist" not in text
        overlay = AdapterRegistry(tmp_path).overlay("otel")
        assert overlay and overlay["enabled"] is True
        assert overlay["source"]["source_kind"] == "otlp-http-json-loopback"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_otel_client_remains_available_without_exposing_advanced_controls_in_the_minimal_hub():
    frontend = Path(__file__).parents[1]
    html = (frontend / "frontend" / "index.html").read_text(encoding="utf-8")
    client = (frontend / "frontend" / "api-client.js").read_text(encoding="utf-8")
    app = (frontend / "frontend" / "app.js").read_text(encoding="utf-8")
    assert "otelImport" in client and "otelEnable" in client and "otelLiveEnable" in client
    assert "OpenTelemetry" in app and "otel_context" in app
    assert "OpenTelemetry" not in html
    assert "http://" not in client and "https://" not in client
