import json
import threading
from urllib.request import Request, urlopen

from impact_engine.local_api import LocalApiState, create_server
from impact_engine.models import Edge, Evidence, GraphDocument, Node


def _project(tmp_path):
    (tmp_path / ".impact_engine").mkdir()
    graph = GraphDocument(metadata={"project_path": str(tmp_path), "graph_fingerprint": "contract-fixture"})
    graph.add_node(Node("service", "FUNCTION", "service", {"file": "src/service.py", "line": 2}))
    graph.add_node(Node("test", "TEST", "test_service", {"file": "tests/test_service.py", "line": 2}))
    graph.add_edge(Edge("covers", "TESTS", "test", "service", confidence=.95, evidence=[Evidence("covers", "tests/test_service.py", 2)]))
    (tmp_path / ".impact_engine" / "graph.json").write_text(graph.to_json(), encoding="utf-8")
    return tmp_path


def _post(server, path, payload):
    request = Request(
        f"http://127.0.0.1:{server.server_port}{path}",
        data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json", "X-CodeSlicer-Session": server.session_token},
    )
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read())


def test_local_api_mode_contract_v2_is_present_for_all_modes(tmp_path):
    project = _project(tmp_path)
    state = LocalApiState(str(project), "support_packs")
    server = create_server("127.0.0.1", 0, str(project), state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        requests = {
            "review": ("/api/review", {"project_path": str(project), "diff_text": "", "refresh": "never"}),
            "inspect": ("/api/inspect", {"project_path": str(project), "entity": "service", "refresh": "never"}),
            "investigate": ("/api/investigate", {"project_path": str(project), "entity": "service", "refresh": "never", "max_nodes": 8, "max_edges": 8}),
            "ci": ("/api/ci", {"project_path": str(project), "refresh": "never"}),
        }
        for mode, (path, payload) in requests.items():
            response = _post(server, path, payload)
            assert response["schema_version"] == "CodeSlicerModeContract/v2"
            assert response["mode"] == mode
            assert response["project"]["path"] == str(project.resolve())
            assert response["freshness"]["status"] in {"fresh", "stale", "missing", "unknown"}
            assert isinstance(response["coverage"], dict)
            assert response["adapters"]
            assert response["adapters"][0]["id"] == "graphify"
            assert response["adapters"][0]["network_used"] is False
            assert response["privacy"] == {"mode": "local-only", "network_used": False}
            assert isinstance(response["warnings"], list)
            assert isinstance(response["result"], dict)
            assert response["report"]["schema_version"] == response["schema_version"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_missing_graph_is_visible_in_contract(tmp_path):
    state = LocalApiState(str(tmp_path), "support_packs")
    server = create_server("127.0.0.1", 0, str(tmp_path), state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        response = _post(server, "/api/inspect", {"project_path": str(tmp_path), "entity": "missing", "refresh": "never"})
        assert response["freshness"]["status"] == "missing"
        assert any("missing" in item for item in response["warnings"])
        assert response["result"]["status"] == "not_found"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
