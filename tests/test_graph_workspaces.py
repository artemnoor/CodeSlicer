import json
from pathlib import Path

import pytest

from impact_engine.adapters.registry import AdapterRegistry
from impact_engine.graph_workspaces import build_workspace, workspace_catalog
from impact_engine.models import Edge, GraphDocument, Node


def _canonical() -> GraphDocument:
    graph = GraphDocument()
    graph.add_node(Node(id="service", kind="FUNCTION", name="service", properties={"file": "src/service.py"}))
    graph.add_node(Node(id="repository", kind="FUNCTION", name="repository", properties={"file": "src/repository.py"}))
    graph.add_edge(Edge(id="service_calls_repository", kind="CALLS", from_node="service", to_node="repository"))
    return graph


def _ready_graphify(project: Path) -> None:
    artifact = project / "graphify.json"
    artifact.write_text(json.dumps({
        "nodes": [
            {"id": "service", "kind": "FUNCTION", "name": "service", "file": "src/service.py"},
            {"id": "external-cache", "kind": "MODULE", "name": "external-cache", "file": "src/cache.py"},
        ],
        "edges": [{"id": "service_cache", "from": "service", "to": "external-cache", "kind": "CALLS"}],
    }), encoding="utf-8")
    registry = AdapterRegistry(project)
    registry.import_artifact("graphify", artifact)
    registry.set_enabled("graphify", True)


def test_workspaces_keep_external_graph_separate_and_emit_only_explicit_bridges(tmp_path: Path) -> None:
    _ready_graphify(tmp_path)
    canonical = _canonical()

    architecture = build_workspace(tmp_path, canonical, workspace_id="architecture", source_id="graphify")

    assert architecture["status"] == "ready"
    assert architecture["workspace"]["ranking_owner"] is False
    assert {node["id"] for node in architecture["nodes"]} == {"graphify::service", "graphify::external-cache"}
    assert all(node["canonical"] is False for node in architecture["nodes"])
    assert all(edge["participates_in_ranking"] is False for edge in architecture["edges"])
    assert architecture["total_bridges"] == 1
    assert architecture["bridges"][0]["from"] == "graphify::service"
    assert architecture["bridges"][0]["to"] == "service"


def test_bridges_workspace_shows_only_confirmed_cross_graph_links(tmp_path: Path) -> None:
    _ready_graphify(tmp_path)
    bridges = build_workspace(tmp_path, _canonical(), workspace_id="bridges")

    assert bridges["status"] == "ready"
    assert bridges["total_edges"] == 1
    assert {node["id"] for node in bridges["nodes"]} == {"graphify::service", "service"}
    assert bridges["edges"][0]["kind"] == "BRIDGES_TO"
    assert bridges["edges"][0]["confirmed"] is True


def test_impact_workspace_remains_canonical_even_when_external_graph_is_ready(tmp_path: Path) -> None:
    _ready_graphify(tmp_path)
    impact = build_workspace(tmp_path, _canonical(), workspace_id="impact")

    assert impact["workspace"]["ranking_owner"] is True
    assert {node["id"] for node in impact["nodes"]} == {"service", "repository"}
    assert all(node["source"] == "codeslicer" for node in impact["nodes"])
    assert impact["total_bridges"] == 0


def test_workspace_catalog_and_invalid_workspace_are_explicit(tmp_path: Path) -> None:
    catalog = {item["id"]: item for item in workspace_catalog(tmp_path)}
    assert catalog["impact"]["ranking_owner"] is True
    assert catalog["architecture"]["source_ids"] == ["graphify", "codegraph"]
    with pytest.raises(ValueError, match="workspace must be one of"):
        build_workspace(tmp_path, _canonical(), workspace_id="everything")
