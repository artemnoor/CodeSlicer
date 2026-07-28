import json
import threading
from pathlib import Path
from urllib.request import Request, urlopen

import pytest

from impact_engine.adapters.joern import parse_joern_artifact
from impact_engine.adapters.registry import AdapterRegistry, MAX_ARTIFACT_BYTES
from impact_engine.local_api import LocalApiState, create_server
from impact_engine.models import GraphDocument, Node
from impact_engine.review import build_review_report


ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "joern"


def _artifact(tmp_path: Path, name: str) -> Path:
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    source = tmp_path / name
    source.write_text((FIXTURES / name).read_text(encoding="utf-8").replace("__PROJECT__", project.as_posix()), encoding="utf-8")
    return project, source


def test_joern_manifest_and_registry_discovery():
    registry = AdapterRegistry(str(ROOT))
    listed = {item["id"]: item for item in registry.list()}
    assert "joern" in listed
    assert listed["joern"]["manifest"]["evidence_class"] == "CPG_DATAFLOW"
    assert listed["joern"]["manifest"]["affects_review_ranking"] is False
    assert listed["joern"]["status"] == "disabled"


@pytest.mark.parametrize("fixture", ["c_taint.json", "java_taint.json"])
def test_realistic_language_taint_fixtures_are_confirmed_only_with_complete_path(tmp_path, fixture):
    project, source = _artifact(tmp_path, fixture)
    result = AdapterRegistry(str(project)).import_artifact("joern", str(source))
    overlay = result["overlay"]
    assert overlay["schema_version"] == "CodeSlicerJoernEvidenceOverlay/v1"
    assert overlay["overlay_only"] is True
    assert overlay["participates_in_ranking"] is False
    assert len(overlay["taint_paths"]) == 1
    assert overlay["taint_paths"][0]["resolution"] == "confirmed"
    assert overlay["taint_paths"][0]["confidence"] == "confirmed"
    assert all("properties" not in item for item in overlay["nodes"] + overlay["edges"])


def test_dangerous_call_without_taint_path_is_context_not_vulnerability(tmp_path):
    project, source = _artifact(tmp_path, "dangerous_call.json")
    overlay = AdapterRegistry(str(project)).import_artifact("joern", str(source))["overlay"]
    assert overlay["findings"][0]["kind"] == "DANGEROUS_CALL"
    assert overlay["findings"][0]["resolution"] == "likely"
    assert overlay["taint_paths"] == []


def test_incomplete_taint_path_is_unresolved(tmp_path):
    project, source = _artifact(tmp_path, "incomplete.json")
    overlay = AdapterRegistry(str(project)).import_artifact("joern", str(source))["overlay"]
    assert overlay["taint_paths"][0]["resolution"] == "unresolved"
    assert any(item["code"] == "joern_taint_path_incomplete" for item in overlay["diagnostics"])


@pytest.mark.parametrize("mutation, diagnostic", [
    (lambda data: data["taint_paths"][0].update({"locations": []}), "joern_taint_locations_missing"),
    (lambda data: data["taint_paths"][0].update({"locations": [data["taint_paths"][0]["locations"][0]]}), "joern_taint_locations_missing"),
    (lambda data: data["taint_paths"][0]["locations"][1]["range"].update({"end_line": None}), "joern_taint_locations_missing"),
])
def test_confirmed_taint_requires_complete_source_and_sink_locations(tmp_path, mutation, diagnostic):
    project, source = _artifact(tmp_path, "c_taint.json")
    data = json.loads(source.read_text(encoding="utf-8"))
    mutation(data)
    source.write_text(json.dumps(data), encoding="utf-8")
    overlay = AdapterRegistry(str(project)).import_artifact("joern", str(source))["overlay"]
    assert overlay["taint_paths"][0]["resolution"] == "unresolved"
    assert overlay["taint_paths"][0]["confidence"] == "unresolved"
    assert any(item["code"] == diagnostic for item in overlay["diagnostics"])


def test_stale_source_artifact_downgrades_confirmed_taint(tmp_path):
    project, source = _artifact(tmp_path, "c_taint.json")
    registry = AdapterRegistry(str(project))
    registry.import_artifact("joern", str(source))
    registry.set_enabled("joern", True)
    source.write_text(source.read_text(encoding="utf-8") + "\nchanged", encoding="utf-8")
    overlay = registry.overlay("joern")
    assert registry.status("joern")["status"] == "stale"
    assert overlay["freshness"]["verified"] is False
    assert overlay["taint_paths"][0]["resolution"] == "unresolved"
    assert any(item["code"] == "joern_taint_freshness_unverified" for item in overlay["diagnostics"])


def test_unknown_schema_is_unsupported_without_invented_evidence(tmp_path):
    project, source = _artifact(tmp_path, "unknown.json")
    result = AdapterRegistry(str(project)).import_artifact("joern", str(source))
    assert result["adapter"]["status"] == "unsupported"
    assert result["overlay"]["nodes"] == []
    assert result["overlay"]["edges"] == []
    assert any(item["code"] == "joern_schema_unknown" for item in result["overlay"]["diagnostics"])


def test_strict_sanitization_removes_nested_secrets_from_overlay_and_storage(tmp_path):
    project, source = _artifact(tmp_path, "secrets.json")
    registry = AdapterRegistry(str(project))
    imported = registry.import_artifact("joern", str(source))
    registry.set_enabled("joern", True)
    enabled = registry.overlay("joern")
    for value in (imported["overlay"], enabled):
        text = json.dumps(value, ensure_ascii=False)
        assert "JOERN_NESTED_SECRET_7F" not in text
        assert "JOERN_EDGE_SECRET" not in text
        assert "JOERN_PROVENANCE_SECRET" not in text
        assert "JOERN_PASSWORD_SECRET" not in text
    for path in (project / ".codeslicer").rglob("*"):
        if path.is_file():
            assert "JOERN_NESTED_SECRET_7F" not in path.read_text(encoding="utf-8", errors="ignore")
            assert "JOERN_EDGE_SECRET" not in path.read_text(encoding="utf-8", errors="ignore")


def test_secret_like_external_ids_are_opaque_remapped_and_keep_connectivity(tmp_path):
    project, source = _artifact(tmp_path, "c_taint.json")
    data = json.loads(source.read_text(encoding="utf-8"))
    markers = {
        "c-source": "JOERN_ID_SECRET_SOURCE_9A", "c-call": "JOERN_ID_SECRET_STEP_9A", "c-sink": "JOERN_ID_SECRET_SINK_9A",
        "c-flow-1": "JOERN_ID_SECRET_EDGE_9A", "c-flow-2": "JOERN_ID_SECRET_EDGE_9B", "c-path-1": "JOERN_ID_SECRET_PATH_9A",
    }
    for node in data["nodes"]:
        node["id"] = markers[node["id"]]
    for edge in data["edges"]:
        edge["id"] = markers[edge["id"]]
        edge["from"] = markers[edge["from"]]
        edge["to"] = markers[edge["to"]]
    path = data["taint_paths"][0]
    path["id"] = markers[path["id"]]
    path["source"] = markers[path["source"]]
    path["sink"] = markers[path["sink"]]
    path["steps"] = [markers[item] for item in path["steps"]]
    data["findings"] = [{"id": "JOERN_ID_SECRET_FINDING_9A", "kind": "DANGEROUS_CALL", "node": markers["c-sink"], "category": "sql", "severity": "high", "provenance": {"token": "JOERN_ID_SECRET_NESTED_9A"}}]
    source.write_text(json.dumps(data), encoding="utf-8")
    registry = AdapterRegistry(str(project))
    imported = registry.import_artifact("joern", str(source))
    registry.set_enabled("joern", True)
    enabled = registry.overlay("joern")
    for value in (imported["overlay"], enabled):
        text = json.dumps(value, ensure_ascii=False)
        for marker in markers.values():
            assert marker not in text
        assert "JOERN_ID_SECRET_FINDING_9A" not in text
        assert "JOERN_ID_SECRET_NESTED_9A" not in text
    assert len(enabled["taint_paths"][0]["steps"]) == 3
    node_ids = {node["id"] for node in enabled["nodes"]}
    assert enabled["taint_paths"][0]["source"] in node_ids
    assert enabled["taint_paths"][0]["sink"] in node_ids
    for stored in (project / ".codeslicer").rglob("*"):
        if stored.is_file():
            text = stored.read_text(encoding="utf-8", errors="ignore")
            assert "JOERN_ID_SECRET" not in text


def test_import_enable_disable_and_stale_freshness_do_not_mutate_canonical_graph(tmp_path):
    project, source = _artifact(tmp_path, "c_taint.json")
    graph = GraphDocument()
    graph.add_node(Node(id="root", kind="PROJECT", name="project"))
    graph.metadata["project_path"] = str(project)
    graph_path = project / ".impact_engine" / "graph.json"
    graph_path.parent.mkdir()
    graph_path.write_text(json.dumps(graph.to_dict()), encoding="utf-8")
    before = graph_path.read_text(encoding="utf-8")
    registry = AdapterRegistry(str(project))
    imported = registry.import_artifact("joern", str(source))
    assert imported["adapter"]["status"] == "imported"
    assert registry.set_enabled("joern", True)["status"] == "ready"
    assert registry.set_enabled("joern", False)["status"] in {"imported", "disabled"}
    source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert registry.status("joern")["status"] == "stale"
    assert graph_path.read_text(encoding="utf-8") == before


def test_joern_overlay_does_not_change_review_projection(tmp_path):
    project, source = _artifact(tmp_path, "c_taint.json")
    graph = GraphDocument()
    graph.add_node(Node(id="root", kind="PROJECT", name="project"))
    graph.metadata["project_path"] = str(project)
    before = build_review_report(str(project), graph=graph, diff_text="", refresh="force", run_tests="none")
    registry = AdapterRegistry(str(project))
    registry.import_artifact("joern", str(source))
    registry.set_enabled("joern", True)
    after = build_review_report(str(project), graph=graph, diff_text="", refresh="force", run_tests="none")
    assert (before.get("risk"), before.get("top_impacts"), before.get("test_recommendations")) == (after.get("risk"), after.get("top_impacts"), after.get("test_recommendations"))


def test_invalid_relative_and_oversized_artifacts_are_rejected(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    registry = AdapterRegistry(str(project))
    with pytest.raises(ValueError, match="absolute local path"):
        registry.import_artifact("joern", "relative.json")
    oversized = tmp_path / "oversized.json"
    with oversized.open("wb") as handle:
        handle.truncate(MAX_ARTIFACT_BYTES + 1)
    with pytest.raises(ValueError, match="exceeds"):
        registry.import_artifact("joern", str(oversized))


def test_malformed_json_has_clear_error(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{not-json", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid Joern JSON"):
        AdapterRegistry(str(project)).import_artifact("joern", str(malformed))


def test_architecture_and_investigate_api_expose_bounded_joern_context(tmp_path):
    project, source = _artifact(tmp_path, "c_taint.json")
    registry = AdapterRegistry(str(project))
    registry.import_artifact("joern", str(source))
    registry.set_enabled("joern", True)
    state = LocalApiState(str(project), str(ROOT / "support_packs"))
    server = create_server("127.0.0.1", 0, str(ROOT / "frontend"), state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        headers = {"Content-Type": "application/json", "X-CodeSlicer-Session": server.session_token}
        architecture_request = Request(f"http://127.0.0.1:{server.server_port}/api/architecture", data=json.dumps({"project_path": str(project)}).encode(), method="POST", headers=headers)
        with urlopen(architecture_request, timeout=10) as response:
            architecture = json.loads(response.read())
        assert architecture["joern"]["status"] == "ready"
        assert architecture["joern"]["participates_in_ranking"] is False
        investigate_request = Request(f"http://127.0.0.1:{server.server_port}/api/investigate", data=json.dumps({"project_path": str(project), "entity": "c-source", "joern_context": True, "max_nodes": 10, "max_edges": 10}).encode(), method="POST", headers=headers)
        with urlopen(investigate_request, timeout=10) as response:
            investigate = json.loads(response.read())
        context = investigate["report"]["result"]["joern_context"]
        assert context["overlay_only"] is True
        assert len(context["taint_paths"]) <= 40
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
