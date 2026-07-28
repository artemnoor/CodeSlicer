from __future__ import annotations

from pathlib import Path

import pytest

from impact_engine.adapters.gortex import build_gortex_overlay
from impact_engine.adapters.registry import AdapterRegistry
from impact_engine.graph_workspaces import build_workspace
from impact_engine.models import GraphDocument, Node


FIXTURE = Path(__file__).parent / "fixtures" / "external_graphs" / "gortex.graphml"


def test_gortex_graphml_is_imported_as_a_separate_non_ranking_graph(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    registry = AdapterRegistry(project)
    result = registry.import_artifact("gortex", FIXTURE)
    registry.set_enabled("gortex", True)
    overlay = registry.overlay("gortex")
    assert result["adapter"]["manifest"]["affects_review_ranking"] is False
    assert overlay and overlay["privacy"]["network_used"] is False
    assert [node["name"] for node in overlay["nodes"]] == ["app.py", "app.py::create_app", "config.py"]
    assert [edge["kind"] for edge in overlay["edges"]] == ["DEFINES", "IMPORTS"]
    assert all(edge["participates_in_ranking"] is False for edge in overlay["edges"])


def test_gortex_workspace_uses_namespaced_nodes_and_only_confirmed_file_bridge(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    registry = AdapterRegistry(project)
    registry.import_artifact("gortex", FIXTURE)
    registry.set_enabled("gortex", True)
    canonical = GraphDocument()
    canonical.add_node(Node(id="file:app.py", kind="FILE", name="app.py", properties={"file": "app.py"}))
    workspace = build_workspace(project, canonical, workspace_id="gortex")
    assert workspace["status"] == "ready"
    assert all(node["id"].startswith("gortex::") for node in workspace["nodes"])
    assert workspace["ranking"]["external_graphs_affect_ranking"] is False
    bridges = build_workspace(project, canonical, workspace_id="bridges")
    assert bridges["total_bridges"] == 1
    assert bridges["edges"][0]["kind"] == "BRIDGES_TO"


def test_gortex_rejects_non_graphml_and_unsafe_xml(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    empty_json = tmp_path / "graph.json"
    empty_json.write_text("{}", encoding="utf-8")
    unsupported = build_gortex_overlay(empty_json, project_root=project)
    assert unsupported["availability"] == "unsupported"
    unsafe = tmp_path / "unsafe.graphml"
    unsafe.write_text("<!DOCTYPE graphml><graphml/>", encoding="utf-8")
    overlay = build_gortex_overlay(unsafe, project_root=project)
    assert overlay["availability"] == "unsupported"
    assert overlay["nodes"] == []


def test_gortex_query_json_subgraph_is_supported(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    source = tmp_path / "gortex-subgraph.json"
    source.write_text("""{
      "nodes": [
        {"id": "src/app.py::main", "kind": "function", "name": "main", "file_path": "src/app.py", "language": "python"},
        {"id": "src/db.py::load", "kind": "function", "name": "load", "file_path": "src/db.py", "language": "python"}
      ],
      "edges": [{"from": "src/app.py::main", "to": "src/db.py::load", "kind": "calls", "confidence_label": "EXTRACTED", "origin": "ast_resolved"}]
    }""", encoding="utf-8")
    registry = AdapterRegistry(project)
    registry.import_artifact("gortex", source)
    registry.set_enabled("gortex", True)
    overlay = registry.overlay("gortex")
    assert overlay and overlay["source_kind"] == "GORTEX_QUERY_JSON"
    assert overlay["edges"][0]["kind"] == "CALLS"
    assert overlay["edges"][0]["confirmed"] is True
