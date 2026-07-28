from __future__ import annotations

import json
from pathlib import Path

import pytest

from impact_engine.adapters.codegraph import build_codegraph_overlay
from impact_engine.adapters.registry import AdapterRegistry


ROOT = Path(__file__).parent / "fixtures" / "external_graphs"


def test_registry_discovers_graphify_and_codegraph() -> None:
    statuses = {item["id"]: item for item in AdapterRegistry(ROOT).list()}
    assert {"graphify", "codegraph"}.issubset(statuses)
    assert statuses["codegraph"]["manifest"]["affects_review_ranking"] is False


def test_graphify_import_is_sanitized_overlay_with_provenance(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    source = ROOT / "graphify-out" / "graph.json"
    if not source.is_file():
        pytest.skip("external Graphify output fixture is not materialized in this checkout")
    result = AdapterRegistry(project).import_artifact("graphify", source)
    artifact = project / ".codeslicer" / "artifacts" / "graphify" / "graph.json"
    stored = json.loads(artifact.read_text(encoding="utf-8"))
    assert stored["schema_version"] == "CodeSlicerEvidenceOverlay/v1"
    assert stored["privacy"]["network_used"] is False
    assert stored["edges"][0]["provenance"]["source"] == "graphify"
    assert result["adapter"]["status"] in {"incomplete", "imported", "disabled"}
    assert not (project / ".impact_engine" / "graph.json").exists()


def test_codegraph_supported_edges_and_confidence(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    result = AdapterRegistry(project).import_artifact("codegraph", ROOT / "codegraph.json")
    overlay = result["overlay"]
    assert overlay["edges"][0]["kind"] == "CONTAINS"
    assert overlay["edges"][0]["resolution"] == "confirmed"
    assert overlay["edges"][0]["participates_in_ranking"] is False
    AdapterRegistry(project).set_enabled("codegraph", True)
    assert AdapterRegistry(project).overlay("codegraph")["privacy"]["network_used"] is False


def test_unknown_schema_is_diagnostic_without_invented_edges() -> None:
    overlay = build_codegraph_overlay(json.loads((ROOT / "unsupported.json").read_text()), artifact_path=str(ROOT / "unsupported.json"), project_root=ROOT)
    assert overlay["availability"] == "unsupported"
    assert overlay["nodes"] == [] and overlay["edges"] == []
    assert any(item["code"] == "unsupported_schema" for item in overlay["diagnostics"])


def test_malformed_and_non_absolute_import_rejected(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    with pytest.raises(ValueError, match="invalid CodeGraph JSON"):
        AdapterRegistry(project).import_artifact("codegraph", ROOT / "malformed.json")
    with pytest.raises(ValueError, match="absolute local path"):
        AdapterRegistry(project).import_artifact("codegraph", "relative.json")
    with pytest.raises(ValueError, match="absolute local path"):
        AdapterRegistry(project).import_artifact("codegraph", "https://example.invalid/graph.json")


def test_stale_source_is_visible_and_canonical_storage_untouched(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    source = tmp_path / "graph.json"
    source.write_text((ROOT / "codegraph.json").read_text(encoding="utf-8"), encoding="utf-8")
    registry = AdapterRegistry(project)
    registry.import_artifact("codegraph", source)
    registry.set_enabled("codegraph", True)
    source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert registry.status("codegraph")["status"] == "stale"
    assert not (project / ".impact_engine" / "graph.json").exists()


def test_external_overlay_does_not_change_review_projection_contract() -> None:
    overlay = build_codegraph_overlay(json.loads((ROOT / "codegraph.json").read_text()), artifact_path=str(ROOT / "codegraph.json"), project_root=ROOT)
    assert all(edge["participates_in_ranking"] is False for edge in overlay["edges"])
    assert overlay["evidence_class"] == "DOC_INFERRED"


def test_graphify_overlay_recursively_drops_secrets_from_nodes_edges_and_provenance(tmp_path: Path) -> None:
    marker = "EXTERNAL_GRAPH_SECRET_9F4"
    project = tmp_path / "project"
    project.mkdir()
    source = tmp_path / "graph.json"
    source.write_text(json.dumps({
        "nodes": [{
            "id": "node:api", "kind": "FUNCTION", "name": "api", "file": "src/api.py",
            "properties": {"token": marker, "nested": {"headers": {"authorization": marker}}},
            "metadata": {"description": marker}, "provenance": {"payload": {"secret": marker}},
        }, {
            "id": "node:db", "kind": "DATABASE", "name": "db", "file": "src/db.py",
        }],
        "edges": [{
            "id": "edge:api:db", "from": "node:api", "to": "node:db", "kind": "CALLS",
            "properties": {"token": marker, "nested": {"payload": marker}},
            "metadata": {"description": marker}, "provenance": {"metadata": {"token": marker}},
        }],
    }), encoding="utf-8")
    registry = AdapterRegistry(project)
    imported = registry.import_artifact("graphify", source)
    registry.set_enabled("graphify", True)
    returned = json.dumps(imported["overlay"], ensure_ascii=False)
    enabled_overlay = json.dumps(registry.overlay("graphify"), ensure_ascii=False)
    stored_files = [path.read_bytes() for path in (project / ".codeslicer").rglob("*") if path.is_file()]
    assert marker not in returned
    assert marker not in enabled_overlay
    assert all(marker.encode() not in content for content in stored_files)
    assert not (project / ".impact_engine" / "graph.json").exists()


def test_codegraph_overlay_drops_provenance_evidence_properties_and_bad_pointer(tmp_path: Path) -> None:
    marker = "CODEGRAPH_PROVENANCE_SECRET_7C"
    project = tmp_path / "project"
    project.mkdir()
    source = tmp_path / "codegraph.json"
    source.write_text(json.dumps({
        "nodes": [{
            "id": "node:api", "kind": "SYMBOL", "name": "api", "file": "src/api.py",
            "range": {"start": {"line": 1, "character": 0}, "end": {"line": 2, "character": 0}},
            "pointer": marker,
            "provenance": {"token": marker}, "evidence": {"secret": marker},
            "metadata": {"description": marker}, "properties": {"nested": {"token": marker}},
        }, {
            "id": "node:db", "kind": "FILE", "name": "db.py", "file": "src/db.py",
        }],
        "edges": [{
            "id": "edge:api:db", "from": "node:api", "to": "node:db", "kind": "CALLS",
            "pointer": marker, "provenance": {"token": marker}, "evidence": {"secret": marker},
            "metadata": {"payload": marker}, "properties": {"headers": {"authorization": marker}},
            "file": "src/api.py", "range": {"start": {"line": 1, "character": 0}, "end": {"line": 1, "character": 3}},
            "confidence": "extracted",
        }],
    }), encoding="utf-8")
    registry = AdapterRegistry(project)
    imported = registry.import_artifact("codegraph", source)
    registry.set_enabled("codegraph", True)
    returned = json.dumps(imported["overlay"], ensure_ascii=False)
    enabled_overlay = json.dumps(registry.overlay("codegraph"), ensure_ascii=False)
    stored_files = [path.read_bytes() for path in (project / ".codeslicer").rglob("*") if path.is_file()]
    assert marker not in returned
    assert marker not in enabled_overlay
    assert all(marker.encode() not in content for content in stored_files)
    assert not (project / ".impact_engine" / "graph.json").exists()
    assert registry.overlay("codegraph")["edges"][0]["resolution"] == "confirmed"
