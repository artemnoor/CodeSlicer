import json
import os
import threading
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen

from impact_engine.local_api import LocalApiState, _graph_projection, _project_overview, create_server
from impact_engine.models import Edge, GraphDocument, Node


def _fixture_project(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "visual-project"
    (project / "src").mkdir(parents=True)
    (project / "src" / "app.py").write_text("def app():\n    return 1\n", encoding="utf-8")
    (project / "src" / "generated").mkdir()
    (project / "src" / "generated" / "schema.py").write_text("# generated\n", encoding="utf-8")
    (project / "node_modules" / "vendor").mkdir(parents=True)
    (project / "node_modules" / "vendor" / "index.js").write_text("secret-like vendor content", encoding="utf-8")
    graph = GraphDocument()
    graph.add_node(Node(id="project", kind="PROJECT", name="visual-project"))
    graph.add_node(Node(id="file", kind="FILE", name="app.py", properties={"file": "src/app.py"}))
    graph.add_node(Node(id="function", kind="FUNCTION", name="app", properties={"file": "src/app.py", "line": 1}))
    graph.add_edge(Edge(id="contains", kind="CONTAINS", from_node="file", to_node="function", confidence=0.9))
    graph.add_edge(Edge(id="transitive", kind="CALLS", from_node="function", to_node="file", confidence=0.8, properties={"transitive": True}))
    graph.metadata["project_path"] = str(project)
    graph_path = project / ".impact_engine" / "graph.json"
    graph_path.parent.mkdir(parents=True)
    graph_path.write_text(json.dumps(graph.to_dict()), encoding="utf-8")
    return project, graph_path


def test_overview_contract_is_bounded_and_reports_health_coverage_and_privacy(tmp_path):
    project, _ = _fixture_project(tmp_path)
    state = LocalApiState(str(project), "support_packs")
    state.analysis["inventory"]["files"].append("vendor/generated.py")
    overview = _project_overview(str(project), state)
    assert overview["status"] in {"ready", "unsupported"}
    assert overview["freshness"]["status"] == "fresh"
    assert "languages" in overview["coverage"]
    assert overview["coverage"]["languages"]
    assert overview["excluded"]["count"] >= 1
    assert overview["privacy"] == {"mode": "local-only", "network_used": False, "telemetry": False}
    assert {"codeslicer", "graphify", "scip"}.issubset({item["id"] for item in overview["evidence_sources"]})


def test_overview_marks_stale_and_unsupported_source_scope(tmp_path):
    project, graph_path = _fixture_project(tmp_path)
    (project / "src" / "new.swift").write_text("struct New {}", encoding="utf-8")
    os.utime(project / "src" / "new.swift", (graph_path.stat().st_mtime + 3, graph_path.stat().st_mtime + 3))
    overview = _project_overview(str(project))
    assert overview["status"] == "stale"
    assert overview["freshness"]["status"] == "stale"
    assert any(item["status"] == "unsupported" for item in overview["coverage"]["languages"])


def test_progressive_projection_is_canonical_only_and_bounded(tmp_path):
    project, _ = _fixture_project(tmp_path)
    projection = _graph_projection(str(project), {"level": "overview", "max_nodes": 1, "max_edges": 1})
    assert projection["status"] == "ready"
    assert projection["canonical_only"] is True
    assert len(projection["nodes"]) <= 1
    assert all(node["canonical"] and node["overlay"] is False for node in projection["nodes"])
    assert all(edge["canonical"] and edge["overlay"] is False for edge in projection["edges"])
    assert all(item["role"] in {"canonical", "supplemental"} for item in projection["evidence_sources"])
    detail = _graph_projection(str(project), {"level": "detail", "filters": {"node_kinds": ["FUNCTION"]}})
    assert [node["id"] for node in detail["nodes"]] == ["function"]
    transitive = _graph_projection(str(project), {"level": "detail", "filters": {"relation_scopes": ["transitive"], "evidence_sources": ["CodeSlicer"], "evidence_classes": ["STATIC_EXTRACTED"]}})
    assert [edge["id"] for edge in transitive["edges"]] == ["transitive"]
    assert transitive["edges"][0]["relation_scope"] == "transitive"


def test_projection_missing_graph_is_an_explicit_empty_state(tmp_path):
    project = tmp_path / "empty-project"
    project.mkdir()
    projection = _graph_projection(str(project), {"level": "overview"})
    assert projection["status"] == "missing"
    assert projection["nodes"] == []
    assert projection["privacy"]["network_used"] is False


def test_projection_keeps_valid_nodes_when_project_coverage_is_unsupported(tmp_path):
    project, _ = _fixture_project(tmp_path)
    with patch(
        "impact_engine.local_api._project_overview",
        return_value={"status": "unsupported", "freshness": {"status": "fresh", "verified": True}},
    ):
        projection = _graph_projection(str(project), {"level": "detail"})
    assert projection["status"] == "ready"
    assert projection["health_status"] == "unsupported"
    assert projection["nodes"]
    assert any("language coverage" in item for item in projection["diagnostics"])


def test_visual_hub_api_exposes_overview_and_projection(tmp_path):
    project, _ = _fixture_project(tmp_path)
    state = LocalApiState(str(project), "support_packs")
    server = create_server("127.0.0.1", 0, str(project), state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(f"http://127.0.0.1:{server.server_port}/api/overview", timeout=5) as response:
            overview = json.loads(response.read())
        assert overview["privacy"]["network_used"] is False
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/graph/projection",
            data=json.dumps({"project_path": str(project), "level": "overview", "max_nodes": 2, "max_edges": 2}).encode(),
            method="POST", headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=5) as response:
            projection = json.loads(response.read())
        assert projection["canonical_only"] is True
        assert projection["privacy"]["network_used"] is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_frontend_is_a_minimal_map_with_an_optional_graphify_entrypoint():
    root = Path(__file__).parents[1]
    html = (root / "frontend" / "index.html").read_text(encoding="utf-8")
    app = (root / "frontend" / "app.js").read_text(encoding="utf-8")
    assert 'data-route-view="map"' in html
    assert 'data-route-view="graphify"' in html
    assert 'id="graphViewSelect"' in html
    assert 'id="graphifyContent"' in html
    assert 'data-route-view="review"' not in html
    assert "дополнитель" in app.lower()
    assert "evidence" in app.lower()
    assert "external" in app.lower() and "not" in app.lower()
    assert "handleGraphifyAction" in app
    assert "toolConnect('graphify'" in app
    assert "graphify-native-frame" in app
    assert "navigate('graphify')" in app
    assert "original interaction model intact" in app
    assert "analyzedAt" in app
    assert "graphProjectionContent" in html
