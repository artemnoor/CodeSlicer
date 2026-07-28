"""Local upstream-tool runtime used by the CodeSlicer orchestration hub.

This module is deliberately separate from adapters.  An adapter imports a
small, provenance-bearing result into an optional graph workspace.  A managed
tool is the *actual upstream project*: its Git checkout, documentation,
executable and raw CLI stay independent and are controlled from one local UI.

Nothing is cloned, installed, built, started or sent over a network until the
caller explicitly confirms that individual action.  Commands never go through
a shell; a user supplies an argv array and the configured executable is called
directly.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Iterable

from impact_engine.project_storage import ensure_project_storage


# The upstream repository is the source of truth. Do not silently stop at a
# convenient UI-sized number of documents: callers can paginate documents and
# the UI chooses a small result page itself.
MAX_DOC_BYTES = 128 * 1024
MAX_OUTPUT_CHARS = 32_000
MAX_ARGUMENTS = 96
MAX_ARGUMENT_CHARS = 4096
MAX_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class ManagedToolDefinition:
    id: str
    title: str
    repository_url: str | None
    purpose: str
    executable_hints: tuple[str, ...] = ()
    category: str = "upstream-repository"


TOOL_CATALOG: tuple[ManagedToolDefinition, ...] = (
    ManagedToolDefinition("graphify", "Graphify", "https://github.com/Graphify-Labs/graphify.git", "Архитектурный граф, сообщества, документация и graph queries.", ("graphify",)),
    ManagedToolDefinition("codegraph", "CodeGraph", "https://github.com/colbymchenry/codegraph.git", "Семантический индекс, MCP и impact/caller/callee queries.", ("codegraph",)),
    ManagedToolDefinition("gortex", "Gortex", "https://github.com/zzet/gortex.git", "Multi-repo knowledge graph, daemon, MCP, HTTP API и code intelligence.", ("gortex",)),
    ManagedToolDefinition("joern", "Joern", "https://github.com/joernio/joern.git", "CPG, data-flow, taint analysis и security investigations.", ("joern", "joern.bat")),
    ManagedToolDefinition("scip", "SCIP", "https://github.com/sourcegraph/scip.git", "Semantic index protocol и language indexers.", ("scip", "scip-typescript")),
    ManagedToolDefinition("openapi", "Redocly CLI", "https://github.com/Redocly/redocly-cli.git", "OpenAPI lint, bundle, contract validation и docs.", ("redocly",)),
    ManagedToolDefinition("asyncapi", "AsyncAPI CLI", "https://github.com/asyncapi/cli.git", "AsyncAPI validation, generation и event contracts.", ("asyncapi",)),
    ManagedToolDefinition("otel", "OpenTelemetry Collector", "https://github.com/open-telemetry/opentelemetry-collector-contrib.git", "Runtime collectors, receivers, processors and exporters.", ("otelcol-contrib",)),
    ManagedToolDefinition("cyclonedx", "CycloneDX Python", "https://github.com/CycloneDX/cyclonedx-python.git", "CycloneDX SBOM generation.", ("cyclonedx-py",)),
    ManagedToolDefinition("spdx", "Syft", "https://github.com/anchore/syft.git", "SBOM generation including SPDX and CycloneDX.", ("syft",)),
    ManagedToolDefinition("sarif", "Semgrep", "https://github.com/semgrep/semgrep.git", "Local SAST execution and SARIF findings.", ("semgrep",)),
    ManagedToolDefinition("lsp", "Language Server Protocol", None, "LSP is a protocol: connect a locally installed language server rather than cloning a fake universal server.", (), "protocol"),
)

_BY_ID = {item.id: item for item in TOOL_CATALOG}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bounded(value: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    return value[-limit:] if len(value) > limit else value


class ToolRuntime:
    """Owns only per-project local tool copies and their execution metadata."""

    def __init__(self, project_path: str | Path, definitions: Iterable[ManagedToolDefinition] | None = None) -> None:
        self.project_path = Path(project_path).expanduser().resolve()
        self.root = self._runtime_root()
        self.definitions = {item.id: item for item in (TOOL_CATALOG if definitions is None else definitions)}

    def _runtime_root(self) -> Path:
        """Pick a short Windows checkout root so upstream test paths survive.

        Some real projects (Joern, Semgrep, Redocly and the OTel contrib tree)
        contain valid paths that exceed MAX_PATH when nested below a normal
        project directory.  A hash keeps this still per-project and local, but
        avoids silently producing a partial checkout.
        """
        project_storage = ensure_project_storage(self.project_path)
        default_root = project_storage / "tool-runtime"
        if os.name != "nt":
            default_root.mkdir(parents=True, exist_ok=True)
            return default_root

        configured = os.environ.get("CODESLICER_TOOL_RUNTIME_ROOT")
        drive_root = Path(self.project_path.anchor or "C:\\") / "csrt"
        short_base = Path(configured).expanduser() if configured else drive_root
        project_key = hashlib.sha256(str(self.project_path).casefold().encode("utf-8")).hexdigest()[:20]
        candidate = short_base / project_key
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            pointer = project_storage / "tool-runtime-location.json"
            pointer.write_text(
                json.dumps({"path": str(candidate), "reason": "windows-long-path-safe"}, indent=2) + "\n",
                encoding="utf-8",
            )
            return candidate
        except OSError:
            # Keep a functional fallback for locked-down corporate machines.
            default_root.mkdir(parents=True, exist_ok=True)
            return default_root

    def _definition(self, tool_id: str) -> ManagedToolDefinition:
        item = self.definitions.get(str(tool_id))
        if item is None:
            raise ValueError(f"unknown managed tool: {tool_id}")
        return item

    def _tool_root(self, tool_id: str) -> Path:
        return self.root / tool_id

    def _state_path(self, tool_id: str) -> Path:
        return self._tool_root(tool_id) / "state.json"

    def _state(self, tool_id: str) -> dict[str, Any]:
        path = self._state_path(tool_id)
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {"status": "error", "diagnostics": ["invalid local tool state"]}

    def _write_state(self, tool_id: str, data: dict[str, Any]) -> None:
        path = self._state_path(tool_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def _repo(self, tool_id: str) -> Path:
        return self._tool_root(tool_id) / "repository"

    def _run(self, args: list[str], *, cwd: Path, timeout: int = 60) -> subprocess.CompletedProcess[str]:
        return subprocess.run(args, cwd=str(cwd), text=True, capture_output=True, shell=False, timeout=timeout, check=False)

    def _git_commit(self, repo: Path) -> str | None:
        try:
            result = self._run(["git", "rev-parse", "HEAD"], cwd=repo, timeout=20)
            return result.stdout.strip() if result.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            return None

    def _doc_files(self, repo: Path) -> list[Path]:
        allowed = {".md", ".mdx", ".rst", ".txt", ".adoc"}
        result: list[Path] = []
        for path in repo.rglob("*"):
            if not path.is_file() or ".git" in path.parts or "node_modules" in path.parts:
                continue
            if path.suffix.lower() in allowed or path.name.upper() in {"README", "LICENSE", "CHANGELOG", "CONTRIBUTING"}:
                result.append(path)
        return sorted(result)

    def _index_docs(self, tool_id: str) -> list[dict[str, Any]]:
        repo = self._repo(tool_id)
        if not repo.is_dir():
            return []
        index: list[dict[str, Any]] = []
        for path in self._doc_files(repo):
            try:
                content = path.read_text(encoding="utf-8", errors="replace")[:MAX_DOC_BYTES]
            except OSError:
                continue
            title = next((line.lstrip("# ").strip() for line in content.splitlines() if line.strip()), path.name)
            index.append({"path": path.relative_to(repo).as_posix(), "title": title[:240], "chars": len(content)})
        target = self._tool_root(tool_id) / "docs-index.json"
        target.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return index

    def _docs_index(self, tool_id: str) -> list[dict[str, Any]]:
        path = self._tool_root(tool_id) / "docs-index.json"
        if not path.is_file():
            return self._index_docs(tool_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else self._index_docs(tool_id)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return self._index_docs(tool_id)

    def status(self, tool_id: str) -> dict[str, Any]:
        definition = self._definition(tool_id)
        state = self._state(tool_id)
        repo = self._repo(tool_id)
        cloned = repo.is_dir() and (repo / ".git").exists()
        executable = state.get("executable")
        executable_ready = bool(executable and Path(str(executable)).is_absolute() and Path(str(executable)).is_file())
        return {
            "id": definition.id, "title": definition.title, "purpose": definition.purpose,
            "category": definition.category, "repository_url": definition.repository_url,
            "executable_hints": list(definition.executable_hints), "connected": cloned or (definition.category == "protocol" and bool(state.get("connected_at"))),
            "repository": {"path": str(repo.resolve()) if repo.exists() else None, "cloned": cloned, "commit": state.get("commit"), "ref": state.get("ref")},
            "executable": {"path": executable, "configured": executable_ready},
            "documentation": {"indexed": len(self._docs_index(tool_id)) if cloned else 0},
            "last_help": state.get("last_help"), "last_run": state.get("last_run"),
            "diagnostics": list(state.get("diagnostics") or []),
            "privacy": {"mode": "local-only", "network_used": False, "clone_requires_confirmation": True},
        }

    def catalog(self) -> list[dict[str, Any]]:
        return [self.status(item.id) for item in self.definitions.values()]

    def connect(self, tool_id: str, *, confirmed: bool, ref: str | None = None) -> dict[str, Any]:
        """Clone the complete upstream Git repository after an explicit opt-in."""
        definition = self._definition(tool_id)
        if definition.category == "protocol":
            state = self._state(tool_id); state.update({"connected_at": _now(), "status": "protocol-ready"}); self._write_state(tool_id, state)
            return self.status(tool_id)
        if not confirmed:
            raise ValueError("connecting an upstream repository requires confirmed=true")
        if not definition.repository_url:
            raise ValueError(f"{tool_id} has no upstream repository URL")
        repo = self._repo(tool_id)
        repo.parent.mkdir(parents=True, exist_ok=True)
        if not repo.exists():
            try:
                clone_command = ["git"]
                if os.name == "nt":
                    clone_command.extend(["-c", "core.longpaths=true"])
                clone_command.extend(["clone", definition.repository_url, str(repo)])
                result = self._run(clone_command, cwd=repo.parent, timeout=MAX_TIMEOUT_SECONDS)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise RuntimeError(f"could not clone {tool_id}: {exc}") from exc
            if result.returncode:
                raise RuntimeError(_bounded(result.stderr or result.stdout or f"git clone failed with {result.returncode}"))
        if not (repo / ".git").is_dir():
            raise ValueError(f"managed repository path is not a Git checkout: {repo}")
        if ref:
            try:
                checked = self._run(["git", "checkout", "--detach", ref], cwd=repo, timeout=60)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise RuntimeError(f"could not checkout {ref}: {exc}") from exc
            if checked.returncode:
                raise RuntimeError(_bounded(checked.stderr or checked.stdout or f"git checkout failed with {checked.returncode}"))
        docs = self._index_docs(tool_id)
        state = self._state(tool_id)
        state.update({"connected_at": _now(), "repository_url": definition.repository_url, "commit": self._git_commit(repo), "ref": ref, "docs_indexed": len(docs), "status": "connected"})
        self._write_state(tool_id, state)
        return self.status(tool_id)

    def configure_executable(self, tool_id: str, executable: str | Path) -> dict[str, Any]:
        self._definition(tool_id)
        candidate = Path(str(executable)).expanduser()
        if not candidate.is_absolute() or not candidate.is_file():
            raise ValueError("executable must be an existing absolute local file")
        state = self._state(tool_id); state.update({"executable": str(candidate.resolve()), "configured_at": _now()}); self._write_state(tool_id, state)
        return self.status(tool_id)

    def docs(self, tool_id: str, *, query: str = "", limit: int = 40) -> dict[str, Any]:
        self._definition(tool_id)
        repo = self._repo(tool_id)
        if not repo.is_dir():
            raise ValueError("connect this upstream repository before reading its documentation")
        q = query.strip().lower()
        results: list[dict[str, Any]] = []
        for item in self._docs_index(tool_id):
            path = repo / item["path"]
            try:
                content = path.read_text(encoding="utf-8", errors="replace")[:MAX_DOC_BYTES]
            except OSError:
                continue
            haystack = f"{item.get('title', '')}\n{content}".lower()
            if q and q not in haystack:
                continue
            position = haystack.find(q) if q else 0
            start = max(position - 300, 0)
            results.append({**item, "excerpt": content[start:start + 1200]})
            if len(results) >= min(max(int(limit), 1), 100):
                break
        return {"tool": self.status(tool_id), "query": query, "documents": results, "privacy": {"mode": "local-only", "network_used": False}}

    def read_document(self, tool_id: str, relative_path: str, *, offset: int = 0, limit_bytes: int = MAX_DOC_BYTES) -> dict[str, Any]:
        self._definition(tool_id)
        repo = self._repo(tool_id)
        candidate = (repo / relative_path).resolve()
        resolved_repo = repo.resolve()
        if (candidate != resolved_repo and resolved_repo not in candidate.parents) or not candidate.is_file():
            raise ValueError("document path must resolve inside the connected local repository")
        start = max(int(offset), 0)
        page_limit = min(max(int(limit_bytes), 1), MAX_DOC_BYTES)
        content = candidate.read_text(encoding="utf-8", errors="replace")
        page = content[start:start + page_limit]
        next_offset = start + len(page)
        return {
            "tool_id": tool_id,
            "path": candidate.relative_to(repo).as_posix(),
            "content": page,
            "offset": start,
            "next_offset": next_offset if next_offset < len(content) else None,
            "total_chars": len(content),
            "truncated": next_offset < len(content),
            "privacy": {"mode": "local-only", "network_used": False},
        }

    def help(self, tool_id: str) -> dict[str, Any]:
        state = self._state(tool_id); executable = state.get("executable")
        if not executable:
            raise ValueError("configure the local upstream executable before requesting command help")
        try:
            result = self._run([str(executable), "--help"], cwd=self.project_path, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"could not run upstream help: {exc}") from exc
        output = _bounded((result.stdout or "") + ("\n" + result.stderr if result.stderr else ""))
        state.update({"last_help": {"at": _now(), "exit_code": result.returncode, "output": output}}); self._write_state(tool_id, state)
        return {"tool": self.status(tool_id), "command": [str(executable), "--help"], "exit_code": result.returncode, "output": output, "privacy": {"mode": "local-only", "network_used": False}}

    def run(self, tool_id: str, *, argv: list[str], confirmed: bool, workspace: str = "project", timeout_seconds: int = 60) -> dict[str, Any]:
        self._definition(tool_id)
        if not confirmed:
            raise ValueError("running a complete upstream command requires confirmed=true")
        if not isinstance(argv, list) or len(argv) > MAX_ARGUMENTS or any(not isinstance(item, str) or len(item) > MAX_ARGUMENT_CHARS for item in argv):
            raise ValueError("argv must be a bounded list of strings")
        state = self._state(tool_id); executable = state.get("executable")
        if not executable:
            raise ValueError("configure the local upstream executable before running commands")
        cwd = self._repo(tool_id) if workspace == "tool" else self.project_path
        if not cwd.is_dir():
            raise ValueError("requested local workspace is unavailable")
        timeout = min(max(int(timeout_seconds), 1), MAX_TIMEOUT_SECONDS)
        command = [str(executable), *argv]
        try:
            result = self._run(command, cwd=cwd, timeout=timeout)
            status = "completed" if result.returncode == 0 else "failed"
            payload = {"status": status, "command": command, "cwd": str(cwd), "exit_code": result.returncode, "stdout": _bounded(result.stdout or ""), "stderr": _bounded(result.stderr or ""), "privacy": {"mode": "local-only", "network_used": False}}
        except subprocess.TimeoutExpired as exc:
            payload = {"status": "timeout", "command": command, "cwd": str(cwd), "exit_code": None, "stdout": _bounded(exc.stdout or ""), "stderr": _bounded(exc.stderr or ""), "privacy": {"mode": "local-only", "network_used": False}}
        except OSError as exc:
            payload = {"status": "error", "command": command, "cwd": str(cwd), "exit_code": None, "stdout": "", "stderr": str(exc), "privacy": {"mode": "local-only", "network_used": False}}
        state.update({"last_run": {"at": _now(), "status": payload["status"], "command": command, "cwd": str(cwd), "exit_code": payload["exit_code"]}}); self._write_state(tool_id, state)
        return payload
