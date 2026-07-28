from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path
from urllib.request import Request, urlopen

import pytest

from impact_engine.adapters.lsp import LSP_OVERLAY_SCHEMA, configure_lsp, disable_lsp, lsp_status, map_lsp_overlay, probe_lsp, query_lsp
from impact_engine.adapters.registry import AdapterRegistry
from impact_engine.local_api import LocalApiState, create_server
from impact_engine.models import GraphDocument, Node
from impact_engine.review import build_review_report


MOCK_SERVER = r'''
import json, sys, time

mode = sys.argv[1] if len(sys.argv) > 1 else "normal"

def read_message():
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        key, value = line.decode("ascii").split(":", 1)
        headers[key.lower().strip()] = value.strip()
    length = int(headers["content-length"])
    return json.loads(sys.stdin.buffer.read(length).decode("utf-8"))

def send(message):
    payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii") + payload)
    sys.stdout.buffer.flush()

while True:
    message = read_message()
    if message is None:
        break
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialize":
        capabilities = {"documentSymbolProvider": True, "definitionProvider": True, "referencesProvider": True, "implementationProvider": True, "workspaceSymbolProvider": True}
        if mode == "unsupported":
            capabilities = {"documentSymbolProvider": True}
        send({"jsonrpc": "2.0", "id": request_id, "result": {"capabilities": capabilities}})
    elif method == "initialized":
        continue
    elif method == "shutdown":
        send({"jsonrpc": "2.0", "id": request_id, "result": None})
    elif method == "exit":
        break
    elif method == "$/cancelRequest":
        continue
    elif mode == "malformed" and request_id:
        sys.stdout.buffer.write(b"Content-Length: 8\r\n\r\nnot-json")
        sys.stdout.buffer.flush()
    elif mode == "timeout" and method == "textDocument/definition":
        time.sleep(2)
    elif method == "textDocument/documentSymbol":
        send({"jsonrpc": "2.0", "id": request_id, "result": [{"name": "foo", "kind": 12, "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 3}}, "selectionRange": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 3}}}]})
    elif method in ("textDocument/definition", "textDocument/references", "textDocument/implementation"):
        uri = message.get("params", {}).get("textDocument", {}).get("uri", "")
        result = [{"uri": uri, "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 3}}}]
        send({"jsonrpc": "2.0", "id": request_id, "result": result})
    elif method == "workspace/symbol":
        uri = message.get("params", {}).get("query", "")
        send({"jsonrpc": "2.0", "id": request_id, "result": []})
    elif request_id:
        send({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "method not found"}})
'''


def _server(tmp_path: Path, mode: str = "normal") -> tuple[Path, list[str]]:
    script = tmp_path / "mock_lsp_server.py"
    script.write_text(textwrap.dedent(MOCK_SERVER), encoding="utf-8")
    return Path(sys.executable).resolve(), [str(script), mode]


def _configure(tmp_path: Path, mode: str = "normal", timeout_ms: int = 1000) -> Path:
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    (project / "main.ts").write_text("foo\n", encoding="utf-8")
    executable, arguments = _server(tmp_path, mode)
    configure_lsp(project, executable, [project], arguments=arguments, timeout_ms=timeout_ms)
    return project


def _graph(project: Path) -> GraphDocument:
    graph = GraphDocument(metadata={"project_path": str(project)})
    graph.add_node(Node(id="fn:foo", kind="FUNCTION", name="foo", properties={"file": "main.ts", "definition_range": {"start_line": 0, "start_column": 0, "end_line": 0, "end_column": 3}}))
    return graph


def test_lsp_disabled_by_default_and_config_state_is_local(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    initial = AdapterRegistry(project).status("lsp")
    assert initial["status"] == "disabled"
    assert not (project / ".codeslicer" / "adapters" / "lsp.json").exists()
    configured = _configure(tmp_path)
    state = json.loads((configured / ".codeslicer" / "adapters" / "lsp.json").read_text(encoding="utf-8"))
    assert state["enabled"] is True
    assert Path(state["executable"]).is_absolute()
    assert all(Path(root).is_absolute() for root in state["workspace_roots"])
    status = lsp_status(configured)
    assert status["status"] == "configured"
    assert status["privacy"]["network_used"] is False
    assert status["privacy"]["subprocess_network"] == "not_observed"
    executable, _ = _server(tmp_path, "normal")
    with pytest.raises(ValueError, match="URL or network"):
        configure_lsp(configured, executable, [configured], arguments=["https://example.invalid/lsp"])


def test_lsp_probe_and_definition_reference_implementation_are_bounded(tmp_path):
    project = _configure(tmp_path)
    probe = probe_lsp(project)
    assert probe["probe"]["status"] == "passed"
    assert probe["capabilities"]["definitionProvider"] is True
    for method in ("definition", "references", "implementation", "documentSymbol"):
        result = query_lsp(project, method=method, file="main.ts", line=0, character=0, entity_id="fn:foo")
        assert result["schema_version"] == LSP_OVERLAY_SCHEMA
        assert result["network_used"] is False
        assert result["privacy"]["subprocess_network"] == "not_observed"
        assert result["bounded"] is True
        assert len(result["nodes"]) <= 200
    document_symbols = query_lsp(project, method="documentSymbol", file="main.ts")
    mapped = map_lsp_overlay(document_symbols, _graph(project))
    assert mapped["mapping_summary"]["confirmed"] == 1
    assert mapped["nodes"][0]["mapping"]["strategy"] == "exact source file + complete range + kind"
    assert build_review_report(str(project), graph=_graph(project), diff_text="", refresh="never")["risk"] == build_review_report(str(project), graph=_graph(project), diff_text="", refresh="never")["risk"]


def test_lsp_name_only_and_outside_root_are_not_confirmed(tmp_path):
    project = _configure(tmp_path)
    overlay = query_lsp(project, method="documentSymbol", file="main.ts")
    graph = _graph(project)
    graph.nodes[0].properties["file"] = "other.ts"
    mapped = map_lsp_overlay(overlay, graph)
    assert mapped["nodes"][0]["mapping"]["status"] == "unresolved"
    other = tmp_path / "outside.ts"
    other.write_text("outside\n", encoding="utf-8")
    outside = query_lsp(project, method="definition", file=str(other), line=0, character=0)
    assert outside["status"] == "unavailable"


def test_lsp_maps_definition_by_local_line_and_name_when_range_is_not_recorded(tmp_path):
    project = _configure(tmp_path)
    overlay = query_lsp(project, method="documentSymbol", file="main.ts")
    graph = GraphDocument(metadata={"project_path": str(project)})
    graph.add_node(Node(id="fn:foo", kind="FUNCTION", name="foo", properties={"file": "main.ts", "line": 1}))
    mapped = map_lsp_overlay(overlay, graph)
    assert mapped["mapping_summary"]["confirmed"] == 1
    assert mapped["nodes"][0]["mapping"]["strategy"] == "local file + declaration line + symbol name"


@pytest.mark.parametrize("mode, expected", [("timeout", "timeout"), ("malformed", "unavailable"), ("unsupported", "unsupported")])
def test_lsp_timeout_malformed_and_unsupported_capability(tmp_path, mode, expected):
    project = _configure(tmp_path, mode, timeout_ms=1000)
    if mode == "timeout":
        state_path = project / ".codeslicer" / "adapters" / "lsp.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["timeout_ms"] = 100
        state_path.write_text(json.dumps(state), encoding="utf-8")
    result = query_lsp(project, method="definition", file="main.ts", line=0, character=0)
    assert result["status"] == expected
    assert result["network_used"] is False


def test_lsp_server_unavailable_and_stale_overlay_are_visible(tmp_path):
    project = _configure(tmp_path)
    state_path = project / ".codeslicer" / "adapters" / "lsp.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["executable"] = str(tmp_path / "missing-server.exe")
    state_path.write_text(json.dumps(state), encoding="utf-8")
    assert lsp_status(project)["status"] == "unavailable"
    fresh_root = tmp_path / "fresh"
    fresh_root.mkdir()
    project = _configure(fresh_root, timeout_ms=1000)
    query_lsp(project, method="documentSymbol", file="main.ts")
    (project / "main.ts").write_text("changed\n", encoding="utf-8")
    assert lsp_status(project)["status"] == "stale"


def test_lsp_api_configure_probe_disable_and_review_invariance(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    source = tmp_path / "api_server.py"
    source.write_text(textwrap.dedent(MOCK_SERVER), encoding="utf-8")
    state = LocalApiState(str(project), "support_packs")
    server = create_server("127.0.0.1", 0, str(project), state)
    import threading
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        def call(path, payload):
            request = Request(f"http://127.0.0.1:{server.server_port}{path}", method="POST", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
            with urlopen(request, timeout=10) as response:
                return json.loads(response.read())
        before = build_review_report(str(project), graph=_graph(project), diff_text="", refresh="never")
        executable = str(Path(sys.executable).resolve())
        configured = call("/api/adapters/lsp/configure", {"project_path": str(project), "executable": executable, "arguments": [str(source), "normal"], "workspace_roots": [str(project)]})
        assert configured["status"] == "ok"
        probed = call("/api/adapters/lsp/probe", {"project_path": str(project)})
        assert probed["adapter"]["probe"]["status"] == "passed"
        architecture = call("/api/architecture", {"project_path": str(project), "overlay": "codeslicer"})
        assert architecture["lsp"]["status"] == "ready"
        assert architecture["lsp"]["network_used"] is False
        disabled = call("/api/adapters/lsp/disable", {"project_path": str(project)})
        assert disabled["adapter"]["status"] == "disabled"
        after = build_review_report(str(project), graph=_graph(project), diff_text="", refresh="never")
        assert (before["risk"], before["top_impacts"], before["test_recommendations"]) == (after["risk"], after["top_impacts"], after["test_recommendations"])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
