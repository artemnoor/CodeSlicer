import json

from impact_engine.local_api import LocalApiState
from impact_engine.models import GraphDocument, Node


def _write_graph(project, project_path=None):
    graph = GraphDocument()
    graph.add_node(Node(id="project", kind="PROJECT", name="fixture"))
    graph.metadata["project_path"] = str(project_path or project)
    path = project / ".impact_engine" / "graph.json"
    path.parent.mkdir()
    path.write_text(json.dumps(graph.to_dict()), encoding="utf-8")
    return path


def test_local_api_hydrates_cli_graph_from_default_project(tmp_path):
    graph_path = _write_graph(tmp_path)

    state = LocalApiState(str(tmp_path), "support_packs")

    snapshot = state.snapshot(include_graph=False)
    assert snapshot["has_analysis"] is True
    assert snapshot["status"] == "ready"
    assert snapshot["analysis"]["loaded_from_existing_graph"] is True
    assert snapshot["analysis"]["graph_path"] == str(graph_path.resolve())
    assert state.snapshot()["graph"]["nodes"][0]["id"] == "project"


def test_local_api_rejects_graph_from_different_project(tmp_path):
    other_project = tmp_path / "other"
    other_project.mkdir()
    graph = GraphDocument()
    graph.add_node(Node(id="other", kind="PROJECT", name="other"))
    graph.metadata["project_path"] = str(other_project)
    (tmp_path / "graph.json").write_text(json.dumps(graph.to_dict()), encoding="utf-8")

    state = LocalApiState(str(tmp_path), "support_packs")

    assert state.snapshot(include_graph=False)["has_analysis"] is False


def test_local_api_can_load_explicit_graph_path(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    graph_path = _write_graph(project)
    state = LocalApiState(None, "support_packs")

    state.project_path = str(project)
    assert state._load_existing_graph(str(graph_path)) is True
    assert state.snapshot(include_graph=False)["has_analysis"] is True
