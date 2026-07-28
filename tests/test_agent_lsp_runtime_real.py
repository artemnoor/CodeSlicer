"""Opt-in real-server E2E; CI enables it with IMPACT_AGENT_LSP_REAL_E2E=1."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest
import psutil

from impact_engine.adapters.agent_lsp import (
    _RUNTIMES,
    discover_agent_lsp,
    notify_agent_lsp_file_changes,
    shutdown_agent_lsp_runtime,
    start_agent_lsp_runtime,
    agent_lsp_status,
)
from impact_engine.adapters.lsp import configure_lsp, disable_lsp, preflight_lsp, query_lsp


pytestmark = pytest.mark.real_server


def _require() -> tuple[Path, Path, Path, Path]:
    if os.environ.get("IMPACT_AGENT_LSP_REAL_E2E") != "1":
        pytest.skip("opt-in real Agent-LSP E2E; CI sets IMPACT_AGENT_LSP_REAL_E2E=1")
    agent = discover_agent_lsp()
    clangd = shutil.which("clangd") or str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "LLVM-22.1.8" / "bin" / "clangd.exe")
    pyright = shutil.which("pyright-langserver")
    typescript = shutil.which("typescript-language-server")
    assert agent and Path(clangd).is_file() and pyright and typescript, "real E2E requires Agent-LSP, clangd, Pyright and TypeScript LSP"
    return Path(agent), Path(clangd), Path(pyright), Path(typescript)


def _configure(project: Path, agent: Path, argument: str) -> None:
    configure_lsp(project, agent, [project], backend="agent_lsp", arguments=[argument])


def _runtime_project(tmp_path: Path, name: str) -> Path:
    """Keep real-server fixtures under the checkout so Agent-LSP finds a workspace."""
    project = Path.cwd() / ".impact_engine" / "runtime" / "pytest-agent-lsp" / tmp_path.name / name
    project.mkdir(parents=True, exist_ok=True)
    return project


def _definition_when_ready(project: Path, line: int):
    deadline = time.monotonic() + 15
    latest = None
    while time.monotonic() < deadline:
        latest = query_lsp(project, method="definition", file="main.ts", line=line, character=24, timeout_ms=30_000)
        if latest["nodes"]:
            return latest
        time.sleep(0.2)
    raise AssertionError(f"TypeScript server did not return a definition: {latest}")


def _language_server_pids(agent_pid: int) -> set[int]:
    """Select the actual TypeScript LS process, excluding Agent-LSP helper children."""
    pids = set()
    for child in psutil.Process(agent_pid).children(recursive=True):
        if child.is_running() and "typescript-language-server" in " ".join(child.cmdline()).casefold():
            pids.add(child.pid)
    return pids


def _write_report(name: str, payload: dict) -> None:
    """Optionally retain CI evidence without committing a runtime artifact."""
    value = os.environ.get("IMPACT_AGENT_LSP_E2E_REPORT")
    if not value:
        return
    target = Path(value)
    target.parent.mkdir(parents=True, exist_ok=True)
    report = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {}
    report[name] = payload
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_persistent_runtime_reuses_agent_lsp_for_ten_queries_and_cleans_up(tmp_path: Path):
    agent, _clangd, _pyright, typescript = _require()
    project = _runtime_project(tmp_path, "typescript")
    (project / "tsconfig.json").write_text('{"compilerOptions":{"target":"ES2020"}}\n', encoding="utf-8")
    source = project / "main.ts"
    source.write_text("export const marker = 1;\nexport const consume = marker;\n", encoding="utf-8")
    _configure(project, agent, f"typescript:{typescript},--stdio")
    started = start_agent_lsp_runtime(project, timeout_seconds=30)
    agent_pid = started["runtime"]["agent_lsp_pid"]
    results = [_definition_when_ready(project, 1)]
    query_times = [time.time()]
    language_server_pids = _language_server_pids(agent_pid)
    assert language_server_pids, "Agent-LSP did not retain a real child language-server process"
    for _ in range(9):
        results.append(query_lsp(project, method="definition", file="main.ts", line=1, character=24, timeout_ms=30_000))
        query_times.append(time.time())
    assert all(item["status"] == "ok" for item in results)
    assert {item["runtime"]["agent_lsp_pid"] for item in results} == {agent_pid}
    assert _language_server_pids(agent_pid) == language_server_pids
    for method in ("references", "implementation", "callHierarchy", "diagnostics"):
        result = query_lsp(project, method=method, file="main.ts", line=1, character=24, timeout_ms=30_000)
        assert result["status"] == "ok"
        assert result["runtime"]["agent_lsp_pid"] == agent_pid
    source.write_text("// shifted\nexport const marker = 1;\nexport const consume = marker;\n", encoding="utf-8")
    changed = notify_agent_lsp_file_changes(project, [source])
    assert changed["status"] == "ok"
    updated = _definition_when_ready(project, 2)
    assert updated["nodes"][0]["range"]["start_line"] == 1
    shutdown = shutdown_agent_lsp_runtime(project)
    deadline = time.monotonic() + 5
    while psutil.pid_exists(agent_pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not psutil.pid_exists(agent_pid), "Agent-LSP process survived graceful shutdown"
    report = {
        "agent_lsp_pid": agent_pid,
        "language_server_pids": sorted(language_server_pids),
        "queries": [{"at": timestamp, "runtime": item["runtime"], "status": item["status"]} for timestamp, item in zip(query_times, results)],
        "changed": changed,
        "updated": updated,
        "shutdown": shutdown,
        "agent_lsp_pid_exists_after_shutdown": psutil.pid_exists(agent_pid),
    }
    (tmp_path / "persistent-runtime.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    _write_report("typescript_persistent_runtime", report)
    assert project.resolve().as_posix().casefold() not in _RUNTIMES


def test_real_pyright_and_clangd_chain_preserves_overlay_boundary(tmp_path: Path):
    agent, clangd, pyright, _typescript = _require()
    python_project = _runtime_project(tmp_path, "python")
    py = python_project / "sample.py"
    py.write_text("def make(value: int) -> int:\n    return value\n\nresult = make(1)\n", encoding="utf-8")
    _configure(python_project, agent, f"python:{pyright},--stdio")
    python_started = start_agent_lsp_runtime(python_project, timeout_seconds=30)
    python_pid = python_started["runtime"]["agent_lsp_pid"]
    pyright_results = {}
    for method in ("definition", "references", "hover", "diagnostics"):
        pyright_results[method] = query_lsp(python_project, method=method, file="sample.py", line=3, character=12, timeout_ms=30_000)
        assert pyright_results[method]["status"] == "ok"
    py.write_text("def make(value: int) -> int:\n    return value\n\nresult = make(\"wrong\")\n", encoding="utf-8")
    assert notify_agent_lsp_file_changes(python_project, [py])["status"] == "ok"
    updated_diagnostics = query_lsp(python_project, method="diagnostics", file="sample.py", line=3, character=12, timeout_ms=30_000)
    assert updated_diagnostics["status"] == "ok"
    assert updated_diagnostics["runtime"]["agent_lsp_pid"] == python_pid
    assert updated_diagnostics["timestamp"] != pyright_results["diagnostics"]["timestamp"]
    mypy = subprocess.run(["mypy", str(py)], capture_output=True, text=True, check=False, timeout=30)
    assert mypy.returncode == 1, "mypy result is reported separately from LSP diagnostics"
    python_shutdown = shutdown_agent_lsp_runtime(python_project)

    cpp_project = _runtime_project(tmp_path, "cpp")
    (cpp_project / "greeter.hpp").write_text("int greet();\n", encoding="utf-8")
    (cpp_project / "greeter.cpp").write_text('#include "greeter.hpp"\nint greet() { return 1; }\n', encoding="utf-8")
    (cpp_project / "main.cpp").write_text('#include "greeter.hpp"\nint main() { return greet(); }\n', encoding="utf-8")
    _configure(cpp_project, agent, f"cpp:{clangd}")
    cpp_started = start_agent_lsp_runtime(cpp_project, timeout_seconds=30)
    cpp_pid = cpp_started["runtime"]["agent_lsp_pid"]
    clangd_results = {}
    for method in ("definition", "references", "implementation", "callHierarchy", "diagnostics"):
        clangd_results[method] = query_lsp(cpp_project, method=method, file="main.cpp", line=1, character=20, timeout_ms=30_000)
        assert clangd_results[method]["status"] == "ok"
        assert clangd_results[method]["runtime"]["agent_lsp_pid"] == cpp_pid
    cpp_shutdown = shutdown_agent_lsp_runtime(cpp_project)
    _write_report("pyright_and_clangd", {
        "pyright_agent_lsp_pid": python_pid,
        "pyright_methods": {method: result["status"] for method, result in pyright_results.items()},
        "pyright_updated_diagnostics": updated_diagnostics["diagnostics"],
        "pyright_diagnostics_requeried_after_change": updated_diagnostics["timestamp"] != pyright_results["diagnostics"]["timestamp"],
        "mypy": {"returncode": mypy.returncode, "stdout": mypy.stdout, "stderr": mypy.stderr},
        "pyright_shutdown": python_shutdown,
        "clangd_agent_lsp_pid": cpp_pid,
        "clangd_methods": {method: result["status"] for method, result in clangd_results.items()},
        "clangd_shutdown": cpp_shutdown,
    })


def test_agent_lsp_missing_and_crash_degrade_without_blocking_native_fallback(tmp_path: Path):
    agent, clangd, _pyright, _typescript = _require()
    missing_project = _runtime_project(tmp_path, "missing")
    (missing_project / "main.cpp").write_text("int main() { return 0; }\n", encoding="utf-8")
    _configure(missing_project, agent, f"cpp:{clangd}")
    state_path = missing_project / ".codeslicer" / "adapters" / "agent_lsp.json"
    state = json.loads(state_path.read_text(encoding="utf-8")); state["executable"] = str(missing_project / "agent-lsp-missing")
    state_path.write_text(json.dumps(state), encoding="utf-8")
    missing_preflight = preflight_lsp(missing_project)
    assert agent_lsp_status(missing_project)["status"] == "unavailable"
    assert missing_preflight["server"]["status"] == "not_configured"

    project = _runtime_project(tmp_path, "crash")
    (project / "greeter.hpp").write_text("int greet();\n", encoding="utf-8")
    (project / "greeter.cpp").write_text('#include "greeter.hpp"\nint greet() { return 1; }\n', encoding="utf-8")
    (project / "main.cpp").write_text('#include "greeter.hpp"\nint main() { return greet(); }\n', encoding="utf-8")
    _configure(project, agent, f"cpp:{clangd}")
    started = start_agent_lsp_runtime(project, timeout_seconds=30)
    runtime = _RUNTIMES[str(project.resolve()).casefold()]
    runtime.client.process.kill(); runtime.client.process.wait(timeout=5)
    crashed = query_lsp(project, method="definition", file="main.cpp", line=1, character=20, timeout_ms=30_000)
    assert crashed["status"] == "degraded"
    assert agent_lsp_status(project)["status"] == "degraded"
    shutdown_agent_lsp_runtime(project)
    disable_lsp(project)
    configure_lsp(project, clangd, [project], backend="native_stdio")
    fallback = query_lsp(project, method="definition", file="main.cpp", line=1, character=20, timeout_ms=30_000)
    assert fallback["status"] == "ok"
    _write_report("missing_and_crash_fallback", {
        "missing_agent_preflight": missing_preflight["server"],
        "crashed_agent_lsp_pid": started["runtime"]["agent_lsp_pid"],
        "crash_query_status": crashed["status"],
        "native_fallback_status": fallback["status"],
    })
