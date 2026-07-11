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
    assert si_content["version"] == "0.4.0"


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
    content = json.loads(res[0]["result"]["content"][0]["text"])
    assert content["status"] == "error"
    assert "timed out" in content["error"]


def test_mcp_subprocess_real(tmp_path):
    import subprocess
    import sys
    
    cmd = [sys.executable, "-m", "impact_engine.mcp.server"]
    
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(tmp_path)
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
