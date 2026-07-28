from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path
from urllib.request import Request, urlopen

import pytest

from impact_engine.local_api import LocalApiState, create_server
from impact_engine.approvals import ApprovalStore
from impact_engine.tool_runtime import ManagedToolDefinition, ToolRuntime


def _git(args: list[str], cwd: Path) -> None:
    result = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=False, timeout=30)
    assert result.returncode == 0, result.stderr


def _source_repository(tmp_path: Path) -> Path:
    source = tmp_path / "upstream"
    source.mkdir()
    _git(["init"], source)
    _git(["config", "user.email", "tests@example.invalid"], source)
    _git(["config", "user.name", "Tests"], source)
    (source / "README.md").write_text("# Demo Tool\n\nUse `demo scan` to build a graph.\n", encoding="utf-8")
    (source / "docs").mkdir()
    (source / "docs" / "commands.md").write_text("# Commands\n\n`demo query` searches the full graph.\n", encoding="utf-8")
    _git(["add", "."], source)
    _git(["commit", "-m", "fixture"], source)
    return source


def _definition(source: Path) -> ManagedToolDefinition:
    return ManagedToolDefinition("demo", "Demo tool", str(source), "fixture", ("demo",))


def test_runtime_clones_complete_local_upstream_repo_indexes_docs_and_runs_argv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = _source_repository(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("CODESLICER_TOOL_RUNTIME_ROOT", str(tmp_path / "runtime"))
    runtime = ToolRuntime(project, [_definition(source)])

    with pytest.raises(ValueError, match="confirmed=true"):
        runtime.connect("demo", confirmed=False)

    connected = runtime.connect("demo", confirmed=True)
    assert connected["connected"] is True
    assert connected["repository"]["commit"]
    assert (Path(connected["repository"]["path"]) / ".git").is_dir()
    docs = runtime.docs("demo", query="full graph")
    assert docs["documents"][0]["path"] == "docs/commands.md"
    assert "demo query" in runtime.read_document("demo", "docs/commands.md")["content"]
    paged = runtime.read_document("demo", "README.md", limit_bytes=8)
    assert paged["truncated"] is True
    assert paged["next_offset"] == 8
    assert runtime.read_document("demo", "README.md", offset=paged["next_offset"])["content"]

    executable = Path(sys.executable).resolve()
    runtime.configure_executable("demo", executable)
    help_result = runtime.help("demo")
    assert help_result["exit_code"] == 0
    run = runtime.run("demo", argv=["-c", "print('full upstream argv')"], confirmed=True)
    assert run["status"] == "completed"
    assert "full upstream argv" in run["stdout"]
    with pytest.raises(ValueError, match="confirmed=true"):
        runtime.run("demo", argv=["-c", "print(1)"], confirmed=False)


def test_local_api_exposes_tool_catalog_and_explicit_connect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = _source_repository(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("CODESLICER_TOOL_RUNTIME_ROOT", str(tmp_path / "runtime"))
    state = LocalApiState(str(project), "support_packs")
    server = create_server("127.0.0.1", 0, str(Path(__file__).parents[1] / "frontend"), state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # Use a local fixture definition without changing global production catalog.
        from impact_engine import tool_runtime
        monkeypatch.setattr(tool_runtime, "TOOL_CATALOG", (_definition(source),))
        monkeypatch.setattr(tool_runtime, "_BY_ID", {"demo": _definition(source)})
        port = server.server_address[1]
        def call(path: str, payload: dict):
            request = Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", "X-CodeSlicer-Session": server.session_token}, method="POST")
            with urlopen(request) as response:  # noqa: S310 - loopback test server
                return json.loads(response.read().decode())
        catalog = call("/api/tools", {"project_path": str(project)})
        assert [item["id"] for item in catalog["tools"]] == ["demo"]
        from urllib.error import HTTPError
        try:
            connected = call("/api/tools/demo/connect", {"project_path": str(project), "confirmed": True})
        except HTTPError as error:
            pending = json.loads(error.read().decode())
            assert pending["status"] == "pending_approval"
            approved = ApprovalStore(project).approve(pending["approval"]["approval_id"])
            connected = call("/api/tools/demo/connect", {"project_path": str(project), "confirmed": True, **approved})
        assert connected["tool"]["connected"] is True
        documents = call("/api/tools/demo/docs", {"project_path": str(project), "query": "scan"})
        assert documents["documents"]
    finally:
        server.shutdown(); server.server_close()
