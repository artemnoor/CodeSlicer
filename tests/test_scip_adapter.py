from __future__ import annotations

import json
import base64
import threading
from pathlib import Path
from urllib.request import Request, urlopen

import pytest

from impact_engine.adapters.registry import MAX_ARTIFACT_BYTES, AdapterRegistry
from impact_engine.adapters.scip import map_scip_overlay, parse_scip_artifact
from impact_engine.local_api import LocalApiState, create_server
from impact_engine.models import GraphDocument, Node
from impact_engine.review import build_review_report


ROOT = Path(__file__).parent
FIXTURE = ROOT / "fixtures" / "scip" / "python.scip"


def _graph(project: Path, *, ambiguous: bool = False) -> GraphDocument:
    graph = GraphDocument(metadata={"project_path": str(project)})
    graph.add_node(Node(id="fn:add", kind="FUNCTION", name="add", properties={"file": "app/util.py", "line": 1, "column": 0, "definition_range": {"start_line": 1, "start_column": 0, "end_line": 1, "end_column": 15}}))
    if ambiguous:
        graph.add_node(Node(id="fn:add-2", kind="FUNCTION", name="add", properties={"file": "app/util.py", "line": 1, "column": 0, "definition_range": {"start_line": 1, "start_column": 0, "end_line": 1, "end_column": 15}}))
    return graph


def _write_graph(project: Path, graph: GraphDocument) -> Path:
    path = project / ".impact_engine" / "graph.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(graph.to_json(), encoding="utf-8")
    return path


def _call(server, path: str, payload: dict | None = None) -> dict:
    request = Request(
        f"http://127.0.0.1:{server.server_port}{path}",
        method="POST" if payload is not None else "GET",
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json", "X-CodeSlicer-Session": server.session_token} if payload is not None else {},
    )
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read())


def test_scip_manifest_and_registry_discover_both_adapters(tmp_path):
    registry = AdapterRegistry(tmp_path)
    statuses = registry.list()
    assert {item["id"] for item in statuses} >= {"graphify", "scip"}
    scip = registry.status("scip")
    assert scip["manifest"]["evidence_class"] == "SEMANTIC_INDEX"
    assert scip["manifest"]["affects_review_ranking"] is False
    assert scip["status"] == "disabled"


def test_scip_disabled_or_missing_does_not_change_core_review(tmp_path):
    graph = _graph(tmp_path)
    before = build_review_report(str(tmp_path), graph=graph, diff_text="", refresh="never")
    assert AdapterRegistry(tmp_path).status("scip")["status"] == "disabled"
    after = build_review_report(str(tmp_path), graph=graph, diff_text="", refresh="never")
    assert (before["risk"], before["top_impacts"], before["test_recommendations"]) == (after["risk"], after["top_impacts"], after["test_recommendations"])


def test_valid_local_import_has_exact_fresh_mapping_and_keeps_impact_graph_separate(tmp_path):
    registry = AdapterRegistry(tmp_path)
    imported = registry.import_artifact("scip", FIXTURE.resolve())
    assert imported["status"] == "imported"
    assert (tmp_path / ".codeslicer" / "artifacts" / "scip" / "index.scip").is_file()
    assert not (tmp_path / ".impact_engine" / "graph.json").exists()
    registry.set_enabled("scip", True)
    mapped = map_scip_overlay(registry.overlay("scip"), _graph(tmp_path))
    assert mapped["mapping_summary"]["exact"] == 1
    assert mapped["nodes"][0]["mapping"]["status"] == "confirmed"
    assert mapped["network_used"] is False


def test_scip_rejects_relative_url_invalid_and_oversized_artifacts(tmp_path):
    registry = AdapterRegistry(tmp_path)
    with pytest.raises(ValueError, match="absolute local"):
        registry.import_artifact("scip", "https://example.test/index.scip")
    with pytest.raises(FileNotFoundError):
        registry.import_artifact("scip", str((tmp_path / "missing.scip").resolve()))
    invalid = tmp_path / "invalid.scip"
    invalid.write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError):
        registry.import_artifact("scip", invalid.resolve())
    oversized = tmp_path / "oversized.scip"
    oversized.write_bytes(b"{" + b"x" * MAX_ARTIFACT_BYTES)
    with pytest.raises(ValueError, match="exceeds"):
        registry.import_artifact("scip", oversized.resolve())


def test_malformed_binary_scip_is_rejected_with_diagnostic(tmp_path):
    for name, payload, message in [("empty.scip", b"", "empty SCIP protobuf artifact"), ("whitespace.scip", b" \r\n", "empty SCIP protobuf artifact"), ("binary.scip", b"\x0a\x03SCIP", "invalid binary SCIP protobuf")]:
        binary = tmp_path / name
        binary.write_bytes(payload)
        with pytest.raises(ValueError, match=message):
            parse_scip_artifact(binary)


@pytest.mark.parametrize("fixture_name, relative_path, symbol_name, kind", [
    ("typescript.binary.scip.base64", "src/service.ts", "say", "method"),
    ("csharp.binary.scip.base64", "src/Clock.cs", "Now", "method"),
    ("python.binary.scip.base64", "app/util.py", "add", "function"),
])
def test_real_binary_scip_fixtures_decode_and_map(tmp_path, fixture_name, relative_path, symbol_name, kind):
    encoded = (ROOT / "fixtures" / "scip" / fixture_name).read_text(encoding="ascii").strip()
    binary = tmp_path / "index.scip"
    binary.write_bytes(base64.b64decode(encoded))
    parsed = parse_scip_artifact(binary)
    assert parsed["format"] == "binary-protobuf"
    assert parsed["symbols"]
    registry = AdapterRegistry(tmp_path)
    imported = registry.import_artifact("scip", binary)
    registry.set_enabled("scip", True)
    graph = GraphDocument(metadata={"project_path": str(tmp_path)})
    graph.add_node(Node(id="semantic-target", kind="METHOD" if kind == "method" else "FUNCTION", name=symbol_name, properties={"file": relative_path, "line": 2, "column": 0, "definition_range": {"start_line": 2, "start_column": 0, "end_line": 2, "end_column": len(symbol_name)}}))
    mapped = map_scip_overlay(registry.overlay("scip"), graph)
    assert imported["overlay"]["diagnostics"][-1]["code"] == "binary_protobuf_decoder"
    assert mapped["mapping_summary"]["exact"] == 1
    assert mapped["nodes"][0]["mapping"]["status"] == "confirmed"


def test_binary_scip_implementation_relationship_is_confirmed_when_both_symbols_map(tmp_path):
    encoded = (ROOT / "fixtures" / "scip" / "typescript.implementation.binary.scip.base64").read_text(encoding="ascii").strip()
    binary = tmp_path / "index.scip"
    binary.write_bytes(base64.b64decode(encoded))
    registry = AdapterRegistry(tmp_path)
    registry.import_artifact("scip", binary)
    registry.set_enabled("scip", True)
    graph = GraphDocument(metadata={"project_path": str(tmp_path)})
    graph.add_node(Node(id="iface", kind="CLASS", name="Greeter", properties={"file": "src/service.ts", "line": 2, "column": 0, "definition_range": {"start_line": 2, "start_column": 0, "end_line": 2, "end_column": 7}}))
    graph.add_node(Node(id="impl", kind="CLASS", name="GreeterImpl", properties={"file": "src/service.ts", "line": 6, "column": 0, "definition_range": {"start_line": 6, "start_column": 0, "end_line": 6, "end_column": 11}}))
    mapped = map_scip_overlay(registry.overlay("scip"), graph)
    implementation_edges = [edge for edge in mapped["edges"] if edge["kind"] == "IMPLEMENTS"]
    assert implementation_edges and implementation_edges[0]["confirmed"] is True


def test_name_only_cross_file_and_ambiguous_matches_remain_unresolved(tmp_path):
    data = parse_scip_artifact(FIXTURE)
    registry = AdapterRegistry(tmp_path)
    overlay = registry.import_artifact("scip", FIXTURE)["overlay"]
    other = _graph(tmp_path)
    other.nodes[0].properties["file"] = "other/util.py"
    mapped = map_scip_overlay(overlay, other)
    assert mapped["nodes"][0]["mapping"]["status"] == "unresolved"
    same_file_name_only = GraphDocument(metadata={"project_path": str(tmp_path)})
    same_file_name_only.add_node(Node(id="fn:wrong-range", kind="FUNCTION", name="add", properties={"file": "app/util.py", "line": 99, "column": 0, "definition_range": {"start_line": 99, "start_column": 0, "end_line": 99, "end_column": 15}}))
    assert map_scip_overlay(overlay, same_file_name_only)["nodes"][0]["mapping"]["status"] == "unresolved"
    ambiguous = map_scip_overlay(overlay, _graph(tmp_path, ambiguous=True))
    assert ambiguous["nodes"][0]["mapping"]["status"] == "ambiguous"
    assert data["schema_version"] == "CodeSlicerScipInterchange/v1"


def test_stale_scip_is_visible_and_not_confirmed(tmp_path):
    source = tmp_path / "index.scip"
    source.write_bytes(FIXTURE.read_bytes())
    registry = AdapterRegistry(tmp_path)
    registry.import_artifact("scip", source)
    registry.set_enabled("scip", True)
    source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert registry.status("scip")["status"] == "stale"
    mapped = map_scip_overlay(registry.overlay("scip"), _graph(tmp_path))
    assert mapped["nodes"][0]["mapping"]["status"] == "stale"
    assert all(edge["confirmed"] is False for edge in mapped["edges"])


def test_scip_project_root_is_validated_as_file_uri(tmp_path):
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data.setdefault("index", {})["project_root"] = tmp_path.as_uri()
    source = tmp_path / "index.scip"
    source.write_text(json.dumps(data), encoding="utf-8")
    registry = AdapterRegistry(tmp_path)
    registry.import_artifact("scip", source)
    assert registry.status("scip")["freshness"]["status"] == "fresh"

    other = tmp_path / "other"
    other.mkdir()
    data["index"]["project_root"] = other.as_uri()
    source.write_text(json.dumps(data), encoding="utf-8")
    registry.import_artifact("scip", source)
    assert registry.status("scip")["freshness"]["status"] == "stale"


def test_scip_project_root_accepts_go_windows_file_uri(tmp_path):
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    encoded = str(tmp_path.resolve()).replace("\\", "%5C")
    data.setdefault("index", {})["project_root"] = f"file://{encoded}"
    source = tmp_path / "index.scip"
    source.write_text(json.dumps(data), encoding="utf-8")
    registry = AdapterRegistry(tmp_path)
    registry.import_artifact("scip", source)
    assert registry.status("scip")["freshness"]["status"] == "fresh"


def test_api_scip_import_enable_disable_inspect_and_bounded_investigate(tmp_path):
    _write_graph(tmp_path, _graph(tmp_path))
    state = LocalApiState(str(tmp_path), "support_packs")
    server = create_server("127.0.0.1", 0, str(tmp_path), state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        listed = _call(server, "/api/adapters")
        assert {item["id"] for item in listed["adapters"]} >= {"graphify", "scip"}
        imported = _call(server, "/api/adapters/scip/import", {"project_path": str(tmp_path), "artifact_path": str(FIXTURE.resolve())})
        assert imported["import_status"] == "imported"
        _call(server, "/api/adapters/scip/enable", {"project_path": str(tmp_path)})
        inspected = _call(server, "/api/inspect", {"project_path": str(tmp_path), "entity": "fn:add", "refresh": "never"})
        evidence = inspected["result"]["semantic_evidence"]
        assert evidence["symbol_id"] == "py/app/util.py#add()."
        assert evidence["mapping"]["status"] == "confirmed"
        investigated = _call(server, "/api/investigate", {"project_path": str(tmp_path), "entity": "fn:add", "refresh": "never", "semantic_context": True, "max_nodes": 4, "max_edges": 4})
        assert investigated["result"]["semantic_context"]["bounded"] is True
        assert len(investigated["result"]["semantic_context"]["reference_ranges"]) <= 40
        disabled = _call(server, "/api/adapters/scip/disable", {"project_path": str(tmp_path)})
        assert disabled["adapter"]["status"] == "imported"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_scip_client_remains_local_only_when_its_controls_are_not_in_the_minimal_hub():
    frontend = ROOT.parent / "frontend"
    html = (frontend / "index.html").read_text(encoding="utf-8")
    app = (frontend / "app.js").read_text(encoding="utf-8")
    client = (frontend / "api-client.js").read_text(encoding="utf-8")
    assert "adapterLabels" in app and "scip: 'SCIP'" in app
    assert "/api/adapters/scip/import" in client
    assert 'data-route-view="map"' in html
    assert "SCIP-контекст" not in html
    assert "http://" not in client and "https://" not in client
