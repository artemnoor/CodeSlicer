import json
import sys
import threading
from pathlib import Path
from urllib.request import Request, urlopen

from impact_engine.local_api import LOCAL_API_CONTRACT_VERSION, LocalApiState, _test_command_for_file, create_server
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


def test_local_api_state_marks_missing_default_project(tmp_path):
    missing = tmp_path / "missing-project"
    state = LocalApiState(str(missing), "support_packs")

    snapshot = state.snapshot(include_graph=False)

    assert snapshot["project_path"] == str(missing)
    assert snapshot["project_exists"] is False


def test_local_api_can_load_explicit_graph_path(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    graph_path = _write_graph(project)
    state = LocalApiState(None, "support_packs")

    state.project_path = str(project)
    assert state._load_existing_graph(str(graph_path)) is True
    assert state.snapshot(include_graph=False)["has_analysis"] is True


def test_local_api_does_not_enable_wildcard_cors_for_review(tmp_path):
    from urllib.error import HTTPError
    _write_graph(tmp_path)
    state = LocalApiState(str(tmp_path), "support_packs")
    server = create_server("127.0.0.1", 0, str(tmp_path), state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/review",
            data=json.dumps({"project_path": str(tmp_path), "diff_text": "", "refresh": "never"}).encode(),
            method="POST",
            headers={"Content-Type": "application/json", "Origin": "http://evil.example"},
        )
        try:
            urlopen(request, timeout=5)
        except HTTPError as error:
            assert error.code == 403
            assert json.loads(error.read())["error"] == "cross_origin_request_rejected"
        else:
            raise AssertionError("cross-origin POST must be rejected")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_local_api_health_advertises_managed_tools_capability(tmp_path):
    _write_graph(tmp_path)
    state = LocalApiState(str(tmp_path), "support_packs")
    server = create_server("127.0.0.1", 0, str(tmp_path), state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(f"http://127.0.0.1:{server.server_port}/api/health", timeout=5) as response:
            payload = json.loads(response.read())
        assert payload["api_contract_version"] == LOCAL_API_CONTRACT_VERSION
        assert payload["capabilities"]["managed_tools"] is True
        assert payload["capabilities"]["tools_endpoint"] == "/api/tools"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_local_api_test_execution_requires_one_time_approval(tmp_path):
    from urllib.error import HTTPError

    _write_graph(tmp_path)
    test_file = tmp_path / "test_example.py"
    test_file.write_text("def test_example():\n    assert True\n", encoding="utf-8")
    state = LocalApiState(str(tmp_path), "support_packs")
    server = create_server("127.0.0.1", 0, str(tmp_path), state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/review/run-test",
            data=json.dumps({"project_path": str(tmp_path), "file": "test_example.py"}).encode(),
            method="POST", headers={"Content-Type": "application/json", "X-CodeSlicer-Session": server.session_token},
        )
        try:
            urlopen(request, timeout=5)
        except HTTPError as error:
            payload = json.loads(error.read())
            assert error.code == 409
            assert payload["status"] == "pending_approval"
            assert payload["approval"]["action"] == "review.run_test"
        else:
            raise AssertionError("test execution must require local approval")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_local_api_review_preserves_loaded_external_graph_path(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    default_graph = _write_graph(project)
    external_graph = tmp_path / "external.json"
    external_graph.write_text(default_graph.read_text(encoding="utf-8"), encoding="utf-8")
    state = LocalApiState(str(project), "support_packs")
    state.project_path = str(project)
    state.analysis["graph_path"] = str(external_graph.resolve())
    server = create_server("127.0.0.1", 0, str(project), state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/review",
            data=json.dumps({"project_path": str(project), "diff_text": "", "refresh": "never"}).encode(),
            method="POST", headers={"Content-Type": "application/json", "X-CodeSlicer-Session": server.session_token},
        )
        with urlopen(request, timeout=5) as response:
            payload = json.loads(response.read())
        assert payload["report"]["graph_freshness"]["graph_path"] == str(external_graph.resolve())
        assert payload["report"]["graph_freshness"]["external_graph"] is True
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_local_api_review_marks_loaded_project_graph_fresh(tmp_path):
    graph_path = _write_graph(tmp_path)
    state = LocalApiState(str(tmp_path), "support_packs")
    server = create_server("127.0.0.1", 0, str(tmp_path), state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/review",
            data=json.dumps({"project_path": str(tmp_path), "diff_text": "", "refresh": "never"}).encode(),
            method="POST", headers={"Content-Type": "application/json", "X-CodeSlicer-Session": server.session_token},
        )
        with urlopen(request, timeout=5) as response:
            payload = json.loads(response.read())
        freshness = payload["report"]["graph_freshness"]
        assert freshness["graph_path"] == str(graph_path.resolve())
        assert freshness["status"] == "fresh"
        assert freshness.get("external_graph") is not True
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_local_api_overview_returns_clear_error_for_missing_project(tmp_path):
    missing = tmp_path / "missing-project"
    state = LocalApiState(str(missing), "support_packs")
    server = create_server("127.0.0.1", 0, str(tmp_path), state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        from urllib.error import HTTPError
        try:
            urlopen(f"http://127.0.0.1:{server.server_port}/api/overview", timeout=5)
        except HTTPError as error:
            payload = json.loads(error.read())
            assert error.code == 404
            assert payload["error"] == "project_not_found"
            assert "does not exist" in payload["message"]
        else:
            raise AssertionError("missing project overview must return HTTP 404")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_local_api_selects_language_specific_test_runners(tmp_path):
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "go.mod").write_text("module fixture", encoding="utf-8")
    (tmp_path / "fixture.sln").write_text("", encoding="utf-8")
    (tmp_path / "pom.xml").write_text("<project/>", encoding="utf-8")
    assert _test_command_for_file(tmp_path, "tests/test_api.py") == [sys.executable, "-m", "pytest", "tests/test_api.py", "-q"]
    assert _test_command_for_file(tmp_path, "src/app.ts") == ["npm", "test", "--", "src/app.ts"]
    assert _test_command_for_file(tmp_path, "pkg/app.go") == ["go", "test", "./..."]
    assert _test_command_for_file(tmp_path, "src/App.cs") == ["dotnet", "test"]
    assert _test_command_for_file(tmp_path, "src/App.java") == ["mvn", "test"]


def test_local_api_exposes_independent_graph_workspace(tmp_path):
    graph = GraphDocument()
    graph.add_node(Node(id="service", kind="FUNCTION", name="service", properties={"file": "src/service.py"}))
    graph_path = tmp_path / ".impact_engine" / "graph.json"
    graph_path.parent.mkdir()
    graph_path.write_text(json.dumps(graph.to_dict()), encoding="utf-8")
    state = LocalApiState(str(tmp_path), "support_packs")
    server = create_server("127.0.0.1", 0, str(tmp_path), state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/graph-workspace",
            data=json.dumps({"project_path": str(tmp_path), "workspace": "impact"}).encode(),
            method="POST", headers={"Content-Type": "application/json", "X-CodeSlicer-Session": server.session_token},
        )
        with urlopen(request, timeout=5) as response:
            payload = json.loads(response.read())
        assert payload["status"] == "ready"
        assert payload["workspace"]["id"] == "impact"
        assert payload["ranking"]["external_graphs_affect_ranking"] is False
        assert payload["nodes"][0]["source"] == "codeslicer"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
