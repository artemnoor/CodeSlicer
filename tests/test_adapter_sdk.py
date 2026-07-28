from __future__ import annotations

import json
from pathlib import Path
from urllib.request import Request, urlopen

import pytest

from impact_engine.adapters.contracts import validate_manifest
from impact_engine.adapters.registry import MAX_ARTIFACT_BYTES, AdapterRegistry
from impact_engine.adapters.graphify import build_graphify_overlay
from impact_engine.local_api import LocalApiState, create_server
from impact_engine.review import build_review_report
from impact_engine.models import GraphDocument, Node


def _graphify_fixture(path: Path, *, source_kind: str = "INFERRED") -> Path:
    path.write_text(json.dumps({
        "nodes": [
            {"id": "module:a", "kind": "MODULE", "name": "a", "community_id": "core"},
            {"id": "module:b", "kind": "MODULE", "name": "b", "community_id": "core"},
        ],
        "edges": [{"id": "edge:a:b", "from": "module:a", "to": "module:b", "kind": "CALLS", "confidence": source_kind}],
    }), encoding="utf-8")
    return path


def test_adapter_manifest_validation_and_discovery(tmp_path):
    assert validate_manifest({"id": "bad"})
    registry = AdapterRegistry(tmp_path)
    status = registry.list()[0]
    assert status["id"] == "graphify"
    assert status["status"] == "disabled"
    assert status["manifest"]["affects_review_ranking"] is False


def test_preflight_covers_every_adapter_and_enable_requires_local_evidence(tmp_path):
    registry = AdapterRegistry(tmp_path)
    preflight = registry.preflight()
    adapter_ids = {item["id"] for item in preflight["adapters"]}
    assert {"graphify", "codegraph", "lsp", "scip", "openapi", "asyncapi", "otel", "joern", "cyclonedx", "spdx", "sarif"} <= adapter_ids
    assert all(item["affects_review_ranking"] is False for item in preflight["adapters"])
    graphify = next(item for item in preflight["adapters"] if item["id"] == "graphify")
    assert graphify["next_action"] == "import"
    assert "--enable" in graphify["command"]
    with pytest.raises(ValueError, match="explicit local artifact"):
        registry.set_enabled("graphify", True)


def test_valid_import_is_local_and_inferred_edges_are_not_confirmed(tmp_path):
    source = _graphify_fixture(tmp_path / "graph.json")
    registry = AdapterRegistry(tmp_path)
    imported = registry.import_graphify(source)
    assert imported["status"] == "imported"
    assert (tmp_path / ".codeslicer" / "artifacts" / "graphify" / "graph.json").is_file()
    assert not (tmp_path / ".impact_engine" / "graph.json").exists()
    registry.set_enabled("graphify", True)
    overlay = registry.overlay()
    edge = overlay["edges"][0]
    assert edge["evidence_class"] == "DOC_INFERRED"
    assert edge["confidence"] == "likely"
    assert edge["confirmed"] is False
    assert edge["participates_in_ranking"] is False
    assert overlay["network_used"] is False
    assert overlay["communities"] == [{"id": "core", "nodes": 2}]


def test_invalid_missing_and_oversized_graphify_inputs_are_rejected(tmp_path):
    registry = AdapterRegistry(tmp_path)
    with pytest.raises(FileNotFoundError):
        registry.import_graphify(str((tmp_path / "missing.json").resolve()))
    invalid = tmp_path / "invalid.json"
    invalid.write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid Graphify JSON"):
        registry.import_graphify(invalid.resolve())
    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b"{" + b"x" * MAX_ARTIFACT_BYTES)
    with pytest.raises(ValueError, match="exceeds"):
        registry.import_graphify(oversized.resolve())


def test_stale_artifact_is_visible_and_review_is_unchanged(tmp_path):
    source = _graphify_fixture(tmp_path / "graph.json")
    registry = AdapterRegistry(tmp_path)
    registry.import_graphify(source)
    registry.set_enabled("graphify", True)
    before = build_review_report(str(tmp_path), graph=GraphDocument(metadata={"project_path": str(tmp_path)}), diff_text="", refresh="never")
    source.write_text(source.read_text(encoding="utf-8").replace('"module:b"', '"module:c"'), encoding="utf-8")
    assert registry.status()["status"] == "stale"
    after = build_review_report(str(tmp_path), graph=GraphDocument(metadata={"project_path": str(tmp_path)}), diff_text="", refresh="never")
    assert (before["risk"], before["top_impacts"], before["test_recommendations"]) == (after["risk"], after["top_impacts"], after["test_recommendations"])


def test_local_api_adapter_endpoints_and_architecture_overlay(tmp_path):
    source = _graphify_fixture(tmp_path.parent / f"{tmp_path.name}-graphify.json")
    state = LocalApiState(str(tmp_path), "support_packs")
    server = create_server("127.0.0.1", 0, str(tmp_path), state)
    server_thread = __import__("threading").Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    def call(path, payload=None):
        request = Request(
            f"http://127.0.0.1:{server.server_port}{path}",
            method="POST" if payload is not None else "GET",
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Content-Type": "application/json", "X-CodeSlicer-Session": server.session_token} if payload is not None else {},
        )
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read())

    try:
        initial = call("/api/adapters")
        assert initial["adapters"][0]["status"] == "disabled"
        imported = call("/api/adapters/graphify/import", {"project_path": str(tmp_path), "artifact_path": str(source.resolve())})
        assert imported["status"] == "ok"
        call("/api/adapters/graphify/enable", {"project_path": str(tmp_path)})
        architecture = call("/api/architecture", {"project_path": str(tmp_path), "overlay": "graphify"})
        assert architecture["graphify"]["schema_version"] == "CodeSlicerEvidenceOverlay/v1"
        investigation = call("/api/investigate", {"project_path": str(tmp_path), "entity": "missing", "refresh": "never", "overlay": "graphify", "max_nodes": 4, "max_edges": 4})
        assert investigation["result"]["architecture_overlay"]["adapter_id"] == "graphify"
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)


def test_frontend_defaults_to_local_code_slicer_only_without_external_requests():
    frontend = Path(__file__).parents[1] / "frontend"
    html = (frontend / "index.html").read_text(encoding="utf-8")
    client = (frontend / "api-client.js").read_text(encoding="utf-8")
    assert "CodeSlicer" in html and "Graphify" in html
    assert "/api/adapters" in client
    assert "http://" not in client and "https://" not in client


def test_frontend_treats_lsp_as_an_explicit_local_process_not_an_imported_file():
    app = (Path(__file__).parents[1] / "frontend" / "app.js").read_text(encoding="utf-8")
    assert "data-adapter-action=\"configure-lsp\"" in app
    assert "ImpactApi.lspConfigure" in app
    assert "LSP — локальный процесс, не файл" in app
