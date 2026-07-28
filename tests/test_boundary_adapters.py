from __future__ import annotations

import json
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import Request, urlopen

import pytest

from impact_engine.adapters.boundary import MAX_BOUNDARY_SPEC_BYTES, map_boundary_overlay, parse_boundary_spec
from impact_engine.adapters.registry import AdapterRegistry
from impact_engine.local_api import LocalApiState, create_server
from impact_engine.models import Edge, GraphDocument, Node
from impact_engine.review import build_review_report


FIXTURES = Path(__file__).parent / "fixtures" / "boundaries"


def test_boundary_manifests_discover_without_changing_graphify_order(tmp_path):
    adapters = AdapterRegistry(tmp_path).list()
    assert [item["id"] for item in adapters][:3] == ["graphify", "asyncapi", "lsp"]
    assert {item["id"] for item in adapters} >= {"graphify", "openapi", "asyncapi", "scip", "lsp"}
    assert all(item["enabled"] is False or item["id"] == "scip" for item in adapters)


@pytest.mark.parametrize("adapter_id, filename, version", [
    ("openapi", "openapi3.yaml", "3.0.3"),
    ("openapi", "swagger2.json", "2.0"),
    ("asyncapi", "asyncapi2.yaml", "2.6.0"),
    ("asyncapi", "asyncapi3.yaml", "3.0.0"),
])
def test_supported_boundary_documents_parse(adapter_id, filename, version):
    parsed = parse_boundary_spec(FIXTURES / filename, adapter_id)
    assert parsed["version"] == version
    assert parsed["nodes"] and parsed["edges"]
    assert all(node["source"]["pointer"].startswith("#/") for node in parsed["nodes"])


def test_refs_cycles_broken_and_generated_are_diagnostics():
    assert any(item["code"] == "cyclic_ref" for item in parse_boundary_spec(FIXTURES / "openapi_cycle.yaml", "openapi")["diagnostics"])
    assert any(item["code"] == "broken_ref" for item in parse_boundary_spec(FIXTURES / "openapi_broken.yaml", "openapi")["diagnostics"])
    generated = FIXTURES / "generated.yaml"
    generated.write_text("openapi: 3.0.3\ninfo: {title: generated, version: 1}\nx-generated: true\npaths: {}\n", encoding="utf-8")
    try:
        assert any(item["code"] == "generated_spec" for item in parse_boundary_spec(generated, "openapi")["diagnostics"])
    finally:
        generated.unlink(missing_ok=True)


def test_import_is_absolute_local_bounded_and_does_not_touch_impact_engine(tmp_path):
    registry = AdapterRegistry(tmp_path)
    imported = registry.import_artifact("openapi", (FIXTURES / "openapi3.yaml").resolve())
    assert imported["overlay"]["privacy"] == {"mode": "local-only", "network_used": False, "external_urls_contacted": False}
    assert (tmp_path / ".codeslicer" / "artifacts" / "openapi" / "spec.yaml").is_file()
    assert not (tmp_path / ".impact_engine").exists()
    with pytest.raises(ValueError, match="absolute local"):
        registry.import_artifact("openapi", "openapi3.yaml")
    with pytest.raises(ValueError, match="absolute local"):
        registry.import_artifact("openapi", "https://example.test/openapi.yaml")
    huge = tmp_path / "huge.yaml"
    huge.write_bytes(b"x" * (MAX_BOUNDARY_SPEC_BYTES + 1))
    with pytest.raises(ValueError, match="exceeds"):
        registry.import_artifact("openapi", huge.resolve())


def test_exact_mapping_confirmed_name_only_never_confirmed(tmp_path):
    registry = AdapterRegistry(tmp_path)
    registry.import_artifact("openapi", (FIXTURES / "openapi3.yaml").resolve())
    registry.set_enabled("openapi", True)
    overlay = registry.overlay("openapi")
    graph = GraphDocument(nodes=[
        Node("route:get-user", "ROUTE", "getUser", {"path": "/users/{id}", "method": "GET", "operation_id": "getUser"}),
        Node("function:other", "FUNCTION", "getUser", {"file": "other.py"}),
        Node("client:users", "FUNCTION", "loadUser", {"file": "web/users.ts"}),
    ], edges=[Edge("http:get-user", "HTTP_CALLS", "client:users", "route:get-user", confidence=0.9)])
    mapped = map_boundary_overlay(overlay, graph)
    route = next(item for item in mapped["nodes"] if item["kind"] == "HTTP_ROUTE")
    assert route["mapping"]["status"] == "confirmed"
    assert route["mapping"]["strategy"] == "exact route + method"
    operation = next(item for item in mapped["nodes"] if item["kind"] == "API_OPERATION")
    assert operation["mapping"]["status"] == "confirmed"
    assert all(item["mapping"]["status"] != "confirmed" for item in mapped["nodes"] if item["name"] == "User")
    assert mapped["canonical_links"][0]["canonical_from"] == "client:users"


def test_operation_id_only_is_likely_not_confirmed(tmp_path):
    registry = AdapterRegistry(tmp_path)
    registry.import_artifact("openapi", (FIXTURES / "openapi3.yaml").resolve())
    registry.set_enabled("openapi", True)
    overlay = registry.overlay("openapi")
    graph = GraphDocument(nodes=[Node("handler", "FUNCTION", "handler", {"operation_id": "getUser"})])
    mapped = map_boundary_overlay(overlay, graph)
    operation = next(item for item in mapped["nodes"] if item["kind"] == "API_OPERATION" and item["name"] == "getUser")
    assert operation["mapping"]["status"] == "likely"
    assert operation["mapping"]["canonical_node_id"] is None
    assert "operationId-only" in operation["mapping"]["strategy"]


def test_asyncapi_consumer_edge_follows_channel_downstream():
    parsed = parse_boundary_spec(FIXTURES / "asyncapi2.yaml", "asyncapi")
    channel_id = "asyncapi:channel:user.created"
    consumer = next(node["id"] for node in parsed["nodes"] if node["kind"] == "EVENT_CONSUMER")
    producer = next(node["id"] for node in parsed["nodes"] if node["kind"] == "EVENT_PRODUCER")
    assert any(edge["from"] == producer and edge["to"] == channel_id and edge["kind"] == "PRODUCES" for edge in parsed["edges"])
    assert any(edge["from"] == channel_id and edge["to"] == consumer and edge["kind"] == "CONSUMES" for edge in parsed["edges"])


def test_stale_spec_is_visible_and_review_is_unchanged(tmp_path):
    source = tmp_path / "openapi.yaml"
    source.write_text((FIXTURES / "openapi3.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    registry = AdapterRegistry(tmp_path)
    registry.import_artifact("openapi", source.resolve())
    registry.set_enabled("openapi", True)
    before = build_review_report(str(tmp_path), graph=GraphDocument(metadata={"project_path": str(tmp_path)}), diff_text="", refresh="never")
    source.write_text(source.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
    assert registry.status("openapi")["status"] == "stale"
    after = build_review_report(str(tmp_path), graph=GraphDocument(metadata={"project_path": str(tmp_path)}), diff_text="", refresh="never")
    assert (before["risk"], before["top_impacts"], before["test_recommendations"]) == (after["risk"], after["top_impacts"], after["test_recommendations"])


def test_boundary_api_lifecycle_architecture_and_bounded_context(tmp_path):
    state = LocalApiState(str(tmp_path), "support_packs")
    server = create_server("127.0.0.1", 0, str(tmp_path), state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def call(path, payload=None):
        req = Request(f"http://127.0.0.1:{server.server_port}{path}", method="POST" if payload is not None else "GET", data=json.dumps(payload).encode() if payload is not None else None, headers={"Content-Type": "application/json", "X-CodeSlicer-Session": server.session_token} if payload is not None else {})
        with urlopen(req, timeout=10) as response:
            return json.loads(response.read())

    try:
        initial = call("/api/adapters")
        assert {item["id"] for item in initial["adapters"]} >= {"openapi", "asyncapi"}
        imported = call("/api/adapters/openapi/import", {"project_path": str(tmp_path), "artifact_path": str((FIXTURES / "openapi3.yaml").resolve())})
        assert imported["status"] == "ok"
        assert call("/api/adapters/openapi/enable", {"project_path": str(tmp_path)})["adapter"]["status"] == "ready"
        architecture = call("/api/architecture", {"project_path": str(tmp_path)})
        assert architecture["openapi"]["status"] == "ready"
        assert architecture["openapi"]["network_used"] is False
        assert call("/api/adapters/openapi/disable", {"project_path": str(tmp_path)})["status"] == "ok"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
