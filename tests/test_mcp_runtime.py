import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

PROJECT_PATH = Path(__file__).parent.parent / "examples" / "golden_cases" / "python_di_basic"


def run_mcp_messages(messages: list, monkeypatch) -> list[dict]:
    from impact_engine.mcp import server

    payload_parts = []
    for m in messages:
        if isinstance(m, str):
            payload_parts.append(m + "\n")
        else:
            payload_parts.append(json.dumps(m) + "\n")
            
    input_payload = "".join(payload_parts)
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO(input_payload))
    with redirect_stdout(stdout):
        server.main()
    return [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]


def test_mcp_initialize_and_tools_list(monkeypatch):
    responses = run_mcp_messages([
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0.0"},
            },
        },
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ], monkeypatch)

    init_resp, list_resp = responses
    assert init_resp["id"] == 1
    assert "result" in init_resp
    assert init_resp["result"]["serverInfo"]["name"] == "impact-engine"

    assert list_resp["id"] == 2
    tools = list_resp["result"]["tools"]
    expected_tools = {
        "analyze_project",
        "impact_query",
        "explain_edge",
        "detect_unknown_libraries",
        "detect_languages",
        "project_inventory",
        "list_support_packs",
        "validate_support_pack",
        "import_support_pack",
        "create_library_research_request",
        "create_library_research_workflow",
        "prepare_library_research_input",
        "validate_library_research_candidate",
        "install_library_support_pack",
    }
    tool_names = {t["name"] for t in tools}
    assert expected_tools.issubset(tool_names)


def test_mcp_tool_call_and_error(monkeypatch):
    responses = run_mcp_messages([
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "detect_languages",
                "arguments": {"project_path": str(PROJECT_PATH)},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "non_existent_tool", "arguments": {}},
        },
    ], monkeypatch)

    call_resp, invalid_resp = responses
    assert call_resp["id"] == 3
    content = call_resp["result"]["content"][0]
    assert content["type"] == "text"
    res_data = json.loads(content["text"])
    assert "python" in res_data["languages"]

    assert invalid_resp["id"] == 4
    assert "error" in invalid_resp
    assert invalid_resp["error"]["code"] == -32601


def test_mcp_invalid_json_rpc(monkeypatch):
    # Parse error (-32700)
    res1 = run_mcp_messages(["{invalid json"], monkeypatch)
    assert len(res1) == 1
    assert res1[0]["error"]["code"] == -32700

    # Invalid request (-32600)
    res2 = run_mcp_messages([[]], monkeypatch)
    assert len(res2) == 1
    assert res2[0]["error"]["code"] == -32600

    # Method not found (-32601)
    res3 = run_mcp_messages([{"jsonrpc": "2.0", "id": 99, "method": "unknown_mcp_method"}], monkeypatch)
    assert len(res3) == 1
    assert res3[0]["error"]["code"] == -32601

    # Invalid params (-32602) - missing required 'project_path'
    res4 = run_mcp_messages([{
        "jsonrpc": "2.0",
        "id": 100,
        "method": "tools/call",
        "params": {
            "name": "analyze_project",
            "arguments": {}
        }
    }], monkeypatch)
    assert len(res4) == 1
    assert res4[0]["error"]["code"] == -32602

    # Notifications (messages without id) do not return response
    res5 = run_mcp_messages([
        {"jsonrpc": "2.0", "method": "initialized"},
        {"jsonrpc": "2.0", "method": "some_notification"}
    ], monkeypatch)
    assert len(res5) == 0


def test_mcp_server_info_and_health_check(monkeypatch):
    res = run_mcp_messages([
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "health_check", "arguments": {}}
        },
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "server_info", "arguments": {}}
        }
    ], monkeypatch)
    assert len(res) == 2
    
    hc_content = json.loads(res[0]["result"]["content"][0]["text"])
    assert hc_content["health"] == "healthy"
    
    si_content = json.loads(res[1]["result"]["content"][0]["text"])
    assert si_content["name"] == "impact-engine"
    assert si_content["version"] == "0.5.1"


def test_mcp_managed_upstream_tool_catalog_is_available_to_agents(tmp_path, monkeypatch):
    """MCP must expose the complete-tool runtime, not just its graph adapters."""
    import subprocess
    from impact_engine.mcp import server
    from impact_engine.tool_runtime import ManagedToolDefinition, ToolRuntime

    upstream = tmp_path / "upstream"
    upstream.mkdir()
    for command in (
        ["git", "init"],
        ["git", "config", "user.email", "tests@example.invalid"],
        ["git", "config", "user.name", "Tests"],
    ):
        completed = subprocess.run(command, cwd=upstream, text=True, capture_output=True, timeout=30, check=False)
        assert completed.returncode == 0, completed.stderr
    (upstream / "README.md").write_text("# Upstream\n\nThe real command is `demo inspect`.\n", encoding="utf-8")
    completed = subprocess.run(["git", "add", "."], cwd=upstream, text=True, capture_output=True, timeout=30, check=False)
    assert completed.returncode == 0, completed.stderr
    completed = subprocess.run(["git", "commit", "-m", "fixture"], cwd=upstream, text=True, capture_output=True, timeout=30, check=False)
    assert completed.returncode == 0, completed.stderr

    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("CODESLICER_TOOL_RUNTIME_ROOT", str(tmp_path / "runtime"))
    definition = ManagedToolDefinition("demo", "Demo", str(upstream), "fixture")
    monkeypatch.setattr(server, "ToolRuntime", lambda project_path: ToolRuntime(project_path, [definition]))
    pending = server.request_action_approval(
        str(project), "managed_tool.connect", {"tool_id": "demo", "ref": ""},
    )
    approval = server.approve_action_locally(str(project), pending["approval"]["approval_id"])
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "list_managed_tools", "arguments": {"project_path": str(project)}}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "connect_managed_tool", "arguments": {"project_path": str(project), "tool_id": "demo", "approval_id": approval["approval_id"], "approval_token": approval["approval_token"]}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "read_managed_tool_docs", "arguments": {"project_path": str(project), "tool_id": "demo", "query": "inspect"}}},
    ]
    responses = run_mcp_messages(messages, monkeypatch)
    tool_names = {tool["name"] for tool in responses[0]["result"]["tools"]}
    assert {"list_managed_tools", "connect_managed_tool", "read_managed_tool_docs", "run_managed_tool"}.issubset(tool_names)
    listed = json.loads(responses[1]["result"]["content"][0]["text"])
    assert listed["tools"][0]["id"] == "demo"
    connected = json.loads(responses[2]["result"]["content"][0]["text"])
    assert connected["managed_tool"]["repository"]["cloned"] is True
    docs = json.loads(responses[3]["result"]["content"][0]["text"])
    assert docs["documents"][0]["path"] == "README.md"


def test_mcp_analyze_project_timeout(monkeypatch):
    res = run_mcp_messages([{
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {
            "name": "analyze_project",
            "arguments": {
                "project_path": str(PROJECT_PATH),
                "timeout_seconds": 0
            }
        }
    }], monkeypatch)
    assert len(res) == 1
    assert res[0]["error"]["code"] == -32602
    assert "minimum" in res[0]["error"]["message"]


def test_mcp_project_onboarding_preflight_is_available_without_terminal_access():
    from impact_engine.mcp.server import project_status, scan_plan

    plan = scan_plan(str(PROJECT_PATH))
    assert plan["status"] == "ok"
    assert plan["inventory"]["files"] > 0
    status = project_status(str(PROJECT_PATH))
    assert status["status"] == "ok"
    assert status["privacy"]["network_used"] is False


def test_mcp_subprocess_real(tmp_path):
    import os
    import subprocess
    import sys
    
    cmd = [sys.executable, "-m", "impact_engine.mcp.server"]
    env = os.environ.copy()
    source_root = str(Path(__file__).resolve().parents[1] / "src")
    # The subprocess intentionally runs in an isolated temp project.  Keep an
    # absolute import root so the repository's documented PYTHONPATH=src setup
    # does not become relative to that temporary cwd.
    env["PYTHONPATH"] = source_root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(tmp_path),
        env=env,
    )
    
    try:
        # 1. Send initialize
        init_req = {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-sub", "version": "1.0"}
            }
        }
        proc.stdin.write((json.dumps(init_req) + "\n").encode("utf-8"))
        proc.stdin.flush()
        
        line = proc.stdout.readline()
        resp = json.loads(line.decode("utf-8"))
        assert resp["id"] == 10
        assert "result" in resp
        
        # 2. Send tools/list
        list_req = {"jsonrpc": "2.0", "id": 11, "method": "tools/list"}
        proc.stdin.write((json.dumps(list_req) + "\n").encode("utf-8"))
        proc.stdin.flush()
        
        line = proc.stdout.readline()
        resp = json.loads(line.decode("utf-8"))
        assert resp["id"] == 11
        assert "tools" in resp["result"]
        
    finally:
        proc.stdin.close()
        proc.terminate()
        proc.wait(timeout=5)
