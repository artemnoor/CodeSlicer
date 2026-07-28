"""Thin optional integration with the public Agent-LSP MCP runtime.

CodeSlicer deliberately does not manage language-server sessions here.  The
official ``agent-lsp`` binary owns server routing, warm indexes, skills, and
semantic workflows; this module only validates a configured local binary,
uses its documented stdio MCP surface, and writes a separate evidence overlay.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from impact_engine.persistence import git_context
from impact_engine.project_storage import ensure_project_storage

from .lsp import build_lsp_overlay, lsp_privacy


AGENT_LSP_ADAPTER_ID = "agent-lsp"
AGENT_LSP_MIN_VERSION = (0, 16, 0)
AGENT_LSP_MAX_VERSION = (0, 17, 0)
AGENT_LSP_PROTOCOL = "mcp-stdio"
MAX_AGENT_LSP_TIMEOUT_SECONDS = 30


class AgentLspError(RuntimeError):
    """A public MCP integration failure, isolated from canonical analysis."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state_path(project_path: str | Path) -> Path:
    return ensure_project_storage(project_path) / "adapters" / "agent_lsp.json"


def _read_state(project_path: str | Path) -> dict[str, Any]:
    project = Path(project_path).expanduser().resolve()
    path = project / ".codeslicer" / "adapters" / "agent_lsp.json"
    if not path.is_file():
        return {"enabled": False}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {"enabled": False, "status": "error"}
    except (OSError, ValueError, json.JSONDecodeError):
        return {"enabled": False, "status": "error", "diagnostics": ["invalid Agent-LSP adapter state"]}


def _write_state(project_path: str | Path, state: dict[str, Any]) -> None:
    _state_path(project_path).write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _parse_version(value: str) -> tuple[int, int, int] | None:
    text = value.strip().lstrip("v")
    parts = text.split(".")
    if len(parts) < 3:
        return None
    try:
        return tuple(int(part.split("-", 1)[0]) for part in parts[:3])  # type: ignore[return-value]
    except ValueError:
        return None


def _version_supported(value: str) -> bool:
    parsed = _parse_version(value)
    return bool(parsed and AGENT_LSP_MIN_VERSION <= parsed < AGENT_LSP_MAX_VERSION)


def discover_agent_lsp(executable: str | Path | None = None) -> Path | None:
    """Find only an existing local executable; never download or install."""
    if executable:
        candidate = Path(executable).expanduser()
        return candidate.resolve() if candidate.is_absolute() and candidate.is_file() else None
    found = shutil.which("agent-lsp")
    if found:
        return Path(found).resolve()
    if os.name == "nt":
        winget_root = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
        candidates = list(winget_root.glob("BlackwellSystems.agent-lsp_*/agent-lsp.exe")) if winget_root.is_dir() else []
        return candidates[0].resolve() if candidates else None
    return None


def agent_lsp_version(executable: str | Path) -> str:
    try:
        completed = subprocess.run([str(executable), "--version"], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AgentLspError(f"cannot execute agent-lsp: {exc}") from exc
    version = (completed.stdout or completed.stderr).strip().splitlines()
    if completed.returncode or not version:
        raise AgentLspError("agent-lsp --version did not return a version")
    return version[0].strip().lstrip("v")


class _McpStdio:
    """Small request/response client for documented MCP stdio, not an LSP client."""

    def __init__(self, executable: Path, server_args: list[str], timeout_seconds: int) -> None:
        env = dict(os.environ)
        # Agent-LSP's JSON response mode is public and keeps the overlay mapper
        # independent from its optional compact GCF rendering.
        env["AGENT_LSP_OUTPUT_FORMAT"] = "json"
        self.process = subprocess.Popen([str(executable), *server_args], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", env=env)
        self.timeout_seconds = max(1, min(timeout_seconds, MAX_AGENT_LSP_TIMEOUT_SECONDS))
        self._id = 0
        self._lock = threading.Lock()

    def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self.process.stdin or not self.process.stdout:
            raise AgentLspError("agent-lsp stdio is unavailable")
        with self._lock:
            self._id += 1
            request_id = self._id
            self.process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}) + "\n")
            self.process.stdin.flush()
            # Agent-LSP can send MCP notifications (for example tools/list_changed)
            # before the requested reply. They are intentionally ignored here.
            result: dict[str, Any] | None = None
            timer = threading.Timer(self.timeout_seconds, self.process.kill)
            timer.start()
            try:
                while True:
                    line = self.process.stdout.readline()
                    if not line:
                        raise AgentLspError("agent-lsp closed stdio before replying")
                    message = json.loads(line)
                    if message.get("id") == request_id:
                        result = message
                        break
            except (json.JSONDecodeError, OSError) as exc:
                raise AgentLspError(f"invalid Agent-LSP MCP response: {exc}") from exc
            finally:
                timer.cancel()
            if "error" in result:
                raise AgentLspError(str(result["error"].get("message", "Agent-LSP MCP error")))
            return result.get("result") or {}

    def close(self) -> None:
        if self.process.stdin:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()


def _mcp(executable: Path, server_args: list[str], timeout_seconds: int, operation: Any) -> Any:
    client = _McpStdio(executable, server_args, timeout_seconds)
    try:
        client.call("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "CodeSlicer", "version": "agent-lsp-adapter-v1"}})
        return operation(client)
    finally:
        client.close()


def configure_agent_lsp(project_path: str | Path, executable: str | Path, workspace_roots: list[str | Path], *, server_args: list[str], compile_commands: str | Path | None = None) -> dict[str, Any]:
    project = Path(project_path).expanduser().resolve()
    binary = discover_agent_lsp(executable)
    if not project.is_dir():
        raise FileNotFoundError(f"Project directory does not exist: {project}")
    if not binary:
        raise ValueError("agent-lsp executable must be an existing absolute local path")
    roots = [Path(root).expanduser().resolve() for root in workspace_roots]
    if not roots or not all(root.is_dir() for root in roots) or not any(project == root or root in project.parents for root in roots):
        raise ValueError("project must be inside an existing workspace root")
    version = agent_lsp_version(binary)
    if not _version_supported(version):
        raise ValueError(f"unsupported agent-lsp version {version}; supported range is >=0.16.0,<0.17.0")
    if not server_args:
        raise ValueError("Agent-LSP server arguments are required (for example cpp:clangd)")
    if any(str(item).startswith(("http://", "https://")) for item in server_args):
        raise ValueError("Agent-LSP arguments must not be network URLs")
    state = {
        "enabled": True, "backend": "agent_lsp", "adapter_id": AGENT_LSP_ADAPTER_ID,
        "executable": str(binary), "version": version, "server_args": list(server_args),
        "workspace_roots": [str(root) for root in roots], "compile_commands": str(Path(compile_commands).resolve()) if compile_commands else None,
        "configured_at": _now(), "project_path": str(project), "protocol": AGENT_LSP_PROTOCOL,
        "diagnostics": [], "project_head": git_context(project).get("head"),
    }
    _write_state(project, state)
    return agent_lsp_status(project)


def agent_lsp_status(project_path: str | Path) -> dict[str, Any]:
    project = Path(project_path).expanduser().resolve()
    state = _read_state(project)
    binary = discover_agent_lsp(state.get("executable"))
    version = state.get("version")
    diagnostics = list(state.get("diagnostics") or [])
    if state.get("enabled") and binary:
        try:
            version = agent_lsp_version(binary)
        except AgentLspError as exc:
            diagnostics.append(str(exc))
    available = bool(binary and version and _version_supported(str(version)))
    freshness = "fresh" if state.get("project_head") == git_context(project).get("head") else "stale"
    return {
        "id": AGENT_LSP_ADAPTER_ID, "backend": "agent_lsp", "status": "ready" if state.get("enabled") and available else ("disabled" if not state.get("enabled") else "unavailable"),
        "enabled": bool(state.get("enabled")), "executable": str(binary) if binary else state.get("executable"), "version": version,
        "version_supported": _version_supported(str(version)) if version else False, "protocol": AGENT_LSP_PROTOCOL,
        "server_args": list(state.get("server_args") or []), "workspace_roots": list(state.get("workspace_roots") or []),
        "capabilities": list(state.get("capabilities") or []), "skills": list(state.get("skills") or []),
        "freshness": {"status": freshness, "verified": freshness == "fresh"}, "diagnostics": diagnostics,
        "network_used": False, "privacy": lsp_privacy(),
    }


def probe_agent_lsp(project_path: str | Path, *, timeout_seconds: int = 10) -> dict[str, Any]:
    project = Path(project_path).expanduser().resolve()
    state = _read_state(project)
    status = agent_lsp_status(project)
    if status["status"] != "ready":
        return {**status, "probe": {"status": "skipped", "reason": "Agent-LSP is not configured and compatible"}}
    binary = Path(str(status["executable"])); args = list(state.get("server_args") or [])
    try:
        tools, prompts = _mcp(binary, args, timeout_seconds, lambda client: (client.call("tools/list", {}).get("tools", []), client.call("prompts/list", {}).get("prompts", [])))
        tool_names = sorted(str(item.get("name")) for item in tools if isinstance(item, dict) and item.get("name"))
        prompt_names = sorted(str(item.get("name")) for item in prompts if isinstance(item, dict) and item.get("name"))
        state.update({"capabilities": tool_names, "skills": prompt_names, "last_probe": _now(), "diagnostics": []})
        _write_state(project, state)
        return {**agent_lsp_status(project), "probe": {"status": "passed", "tools": tool_names, "skills": prompt_names}}
    except AgentLspError as exc:
        state["diagnostics"] = [str(exc)]; _write_state(project, state)
        return {**agent_lsp_status(project), "probe": {"status": "error", "error": str(exc)}}


_TOOLS = {"definition": "go_to_definition", "references": "find_references", "implementation": "go_to_implementation", "callHierarchy": "find_callers", "typeHierarchy": "type_hierarchy", "hover": "inspect_symbol", "diagnostics": "get_diagnostics"}


def _content_payload(result: dict[str, Any]) -> Any:
    texts = [str(item.get("text", "")) for item in result.get("content", []) if isinstance(item, dict) and item.get("type") == "text"]
    for text in texts:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            continue
    return {"message": texts[0] if texts else "Agent-LSP returned no structured content"}


def query_agent_lsp(project_path: str | Path, *, method: str, file: str | None, line: int = 0, character: int = 0, timeout_seconds: int = 15, entity_id: str | None = None) -> dict[str, Any]:
    project = Path(project_path).expanduser().resolve(); state = _read_state(project); status = agent_lsp_status(project)
    tool = _TOOLS.get(method)
    if status["status"] != "ready" or not tool:
        return {"status": "unavailable" if status["status"] != "ready" else "unsupported", "error": "Agent-LSP is unavailable or does not expose this delegated method", "privacy": lsp_privacy()}
    file_path = (Path(file).expanduser() if file and Path(file).is_absolute() else project / str(file or "")).resolve() if file else None
    if method != "diagnostics" and (not file_path or not file_path.is_file() or project not in file_path.parents):
        return {"status": "unavailable", "error": "source file is outside the selected project or does not exist", "privacy": lsp_privacy()}
    if file_path and (not file_path.is_file() or (project not in file_path.parents and file_path != project)):
        return {"status": "unavailable", "error": "source file is outside the selected project or does not exist", "privacy": lsp_privacy()}
    args: dict[str, Any] = {"file_path": str(file_path)} if file_path else {}
    if method != "diagnostics":
        args.update({"line": int(line) + 1, "column": int(character) + 1})
    if method == "references": args["include_declaration"] = True
    if method in {"callHierarchy", "typeHierarchy"}: args["direction"] = "both"
    try:
        payload = _mcp(Path(str(status["executable"])), list(state.get("server_args") or []), timeout_seconds, lambda client: _content_payload(client.call("tools/call", {"name": tool, "arguments": args})))
        locations = payload if isinstance(payload, list) else []
        raw_diagnostics: list[dict[str, Any]] = []
        if method == "diagnostics" and isinstance(payload, dict):
            for uri, entries in payload.items():
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    raw_diagnostics.append({"source": "agent-lsp", "uri": str(uri), **entry})
        normalized = []
        for value in locations:
            if not isinstance(value, dict) or not value.get("file"):
                continue
            try:
                target = Path(str(value["file"])).resolve()
                if project not in target.parents and target != project:
                    continue
                normalized.append({"uri": target.as_uri(), "file": target.relative_to(project).as_posix(), "range": {"start_line": max(0, int(value.get("line", 1)) - 1), "start_column": max(0, int(value.get("column", 1)) - 1), "end_line": max(0, int(value.get("end_line", value.get("line", 1))) - 1), "end_column": max(0, int(value.get("end_column", value.get("column", 1))) - 1)}, "source": "agent-lsp"})
            except (OSError, ValueError, TypeError):
                continue
        overlay = build_lsp_overlay(project, method=tool, locations=normalized, entity_id=entity_id, diagnostics=raw_diagnostics, adapter_id=AGENT_LSP_ADAPTER_ID, source="agent-lsp", provenance={"runtime": "agent-lsp", "version": status.get("version"), "tool": tool, "workspace": str(project), "timestamp": _now(), "confidence_cap": "likely" if status["freshness"]["status"] == "fresh" else "limited"})
        if method == "hover" and isinstance(payload, dict):
            overlay["semantic_result"] = payload
        overlay["status"] = "ok"
        target = ensure_project_storage(project) / "artifacts" / "agent-lsp" / "overlay.json"; target.parent.mkdir(parents=True, exist_ok=True); target.write_text(json.dumps(overlay, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        state.update({"overlay_path": str(target), "last_query": _now(), "last_tool": tool, "project_head": git_context(project).get("head")}); _write_state(project, state)
        return overlay
    except AgentLspError as exc:
        return {"status": "unavailable", "error": str(exc), "diagnostics": [{"code": "agent_lsp", "severity": "warning", "message": str(exc)}], "privacy": lsp_privacy()}


def load_agent_lsp_overlay(project_path: str | Path) -> dict[str, Any] | None:
    """Load only the separate Agent-LSP overlay; never mutate canonical data."""
    project = Path(project_path).expanduser().resolve(); state = _read_state(project)
    if not state.get("enabled") or not state.get("overlay_path"):
        return None
    try:
        overlay = json.loads(Path(str(state["overlay_path"])).read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    freshness = "fresh" if state.get("project_head") == git_context(project).get("head") else "stale"
    overlay["freshness"] = {"status": freshness, "verified": freshness == "fresh"}
    return overlay
