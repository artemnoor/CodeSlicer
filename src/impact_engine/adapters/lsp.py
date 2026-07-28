"""Local, opt-in Language Server Protocol evidence adapter.

The adapter owns a short-lived local subprocess per probe/query.  It never
starts a server during analysis or Review and never sends project data to a
network endpoint.  Only bounded semantic locations are persisted; source
text is not copied into CodeSlicer storage.
"""
from __future__ import annotations

import hashlib
import json
import os
import queue
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from impact_engine.models import GraphDocument
from impact_engine.build_context import inspect_build_context
from impact_engine.languages.registry import detect_languages
from impact_engine.persistence import git_context
from impact_engine.project_storage import ensure_project_storage


LSP_OVERLAY_SCHEMA = "CodeSlicerLspEvidenceOverlay/v1"
MAX_LSP_ITEMS = 200
MAX_LSP_RESPONSE_BYTES = 4 * 1024 * 1024
DEFAULT_LSP_TIMEOUT_MS = 5_000
MAX_LSP_TIMEOUT_MS = 30_000
LSP_PRIVACY_BOUNDARY = "user-configured-local-process-not-sandboxed"
LSP_NETWORK_OBSERVATION = "not_observed"


def lsp_privacy() -> dict[str, Any]:
    """Describe exactly what CodeSlicer can and cannot guarantee."""
    return {
        "mode": "local-only",
        "network_used": False,
        "network_observed": False,
        "subprocess_network": LSP_NETWORK_OBSERVATION,
        "boundary": LSP_PRIVACY_BOUNDARY,
        "note": "CodeSlicer opens no network transport; the user-configured executable is not sandboxed and may have its own network behavior.",
    }

_KIND_NAMES = {
    1: "FILE", 2: "MODULE", 3: "NAMESPACE", 4: "PACKAGE", 5: "CLASS",
    6: "METHOD", 7: "PROPERTY", 8: "FIELD", 9: "CONSTRUCTOR", 10: "ENUM",
    11: "INTERFACE", 12: "FUNCTION", 13: "VARIABLE", 14: "CONSTANT",
    15: "STRING", 16: "NUMBER", 17: "BOOLEAN", 18: "ARRAY", 19: "OBJECT",
    20: "KEY", 21: "NULL", 22: "ENUM_MEMBER", 23: "STRUCT", 24: "EVENT",
    25: "OPERATOR", 26: "TYPE_PARAMETER",
}


class LspError(RuntimeError):
    """A bounded, user-visible LSP transport or capability error."""


class LspTimeout(LspError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _absolute_path(value: str | Path, *, label: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute() or str(value).startswith(("http://", "https://", "file://")):
        raise ValueError(f"{label} must be an absolute local path")
    return path.resolve()


def _inside(path: Path, roots: list[Path]) -> bool:
    candidate = path.resolve()
    return any(candidate == root or root in candidate.parents for root in roots)


def _state_path(project_path: str | Path) -> Path:
    return ensure_project_storage(project_path) / "adapters" / "lsp.json"


def _read_state(project_path: str | Path) -> dict[str, Any]:
    path = _state_path(project_path)
    if not path.is_file():
        return {"enabled": False}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {"enabled": False, "status": "error"}
    except (OSError, ValueError, json.JSONDecodeError):
        return {"enabled": False, "status": "error", "diagnostics": ["invalid LSP adapter state"]}


def _read_existing_state(project_path: str | Path) -> dict[str, Any]:
    """Read state for no-write operations such as semantic preflight."""
    project = Path(project_path).expanduser().resolve()
    path = project / ".codeslicer" / "adapters" / "lsp.json"
    if not path.is_file():
        return {"enabled": False}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {"enabled": False, "status": "error"}
    except (OSError, ValueError, json.JSONDecodeError):
        return {"enabled": False, "status": "error", "diagnostics": ["invalid LSP adapter state"]}


def _write_state(project_path: str | Path, state: dict[str, Any]) -> None:
    _state_path(project_path).write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _roots(state: dict[str, Any]) -> list[Path]:
    roots: list[Path] = []
    for value in state.get("workspace_roots") or []:
        try:
            roots.append(_absolute_path(str(value), label="workspace root"))
        except ValueError:
            continue
    return roots


def _validate_configuration(executable: str | Path, workspace_roots: list[str | Path], arguments: list[str] | None = None) -> tuple[Path, list[Path], list[str]]:
    executable_path = _absolute_path(executable, label="LSP executable")
    if not executable_path.is_file():
        raise FileNotFoundError(f"LSP executable does not exist: {executable_path}")
    roots = [_absolute_path(value, label="workspace root") for value in workspace_roots]
    if not roots:
        raise ValueError("at least one absolute workspace root is required")
    missing = [str(root) for root in roots if not root.is_dir()]
    if missing:
        raise FileNotFoundError(f"workspace root does not exist: {missing[0]}")
    if arguments is not None and not isinstance(arguments, list):
        raise ValueError("LSP arguments must be a list of strings")
    args = [str(item) for item in (arguments or [])]
    if not all(isinstance(item, str) for item in (arguments or [])):
        raise ValueError("LSP arguments must be strings")
    for argument in args:
        parsed = urlparse(argument)
        if parsed.scheme.lower() in {"http", "https", "ws", "wss", "ftp"} or "://" in argument:
            raise ValueError("LSP arguments cannot contain URL or network endpoints")
    return executable_path, roots, args


def _project_allowed(project_path: Path, state: dict[str, Any]) -> tuple[bool, str | None]:
    roots = _roots(state)
    if not roots:
        return False, "no valid allowed workspace roots are configured"
    if not _inside(project_path, roots):
        return False, "project is outside the configured LSP workspace roots"
    return True, None


def _uri_to_path(uri: str) -> Path | None:
    parsed = urlparse(str(uri))
    if parsed.scheme.lower() != "file" or parsed.netloc not in {"", "localhost"}:
        return None
    try:
        return Path(url2pathname(unquote(parsed.path))).resolve()
    except (OSError, ValueError):
        return None


def _path_to_uri(path: Path) -> str:
    return path.resolve().as_uri()


def _language_id(path: Path) -> str:
    """Return the conservative LSP language identifier for a selected file."""
    return {
        ".py": "python", ".pyi": "python", ".ts": "typescript", ".tsx": "typescriptreact",
        ".js": "javascript", ".jsx": "javascriptreact", ".cs": "csharp",
        ".java": "java", ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp",
        ".cxx": "cpp", ".hpp": "cpp",
    }.get(path.suffix.lower(), "plaintext")


def _open_selected_document(client: _JsonRpcProcess, path: Path) -> None:
    """Make one explicit local file visible to a server before querying it.

    Some language servers, including Pyright, do not populate semantic results
    until they receive ``didOpen``.  The source stays in the LSP subprocess
    only; CodeSlicer persists only normalized locations in the resulting
    overlay.  Keep the input bounded by the same payload limit as JSON-RPC.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise LspError(f"cannot read selected LSP source file: {exc}") from exc
    if len(text.encode("utf-8")) > MAX_LSP_RESPONSE_BYTES:
        raise LspError("selected LSP source file exceeds the configured local payload limit")
    client.notify("textDocument/didOpen", {
        "textDocument": {
            "uri": _path_to_uri(path), "languageId": _language_id(path),
            "version": 1, "text": text,
        },
    })


def _range(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    start, end = value.get("start"), value.get("end")
    if not isinstance(start, dict) or not isinstance(end, dict):
        return None
    try:
        return {
            "start_line": int(start["line"]), "start_column": int(start["character"]),
            "end_line": int(end["line"]), "end_column": int(end["character"]),
        }
    except (KeyError, TypeError, ValueError):
        return None


def _lsp_range(value: dict[str, int]) -> dict[str, dict[str, int]]:
    return {
        "start": {"line": int(value["start_line"]), "character": int(value["start_column"])},
        "end": {"line": int(value["end_line"]), "character": int(value["end_column"])},
    }


def _kind(value: Any) -> str:
    if isinstance(value, int):
        return _KIND_NAMES.get(value, "SYMBOL")
    text = str(value or "SYMBOL").upper().replace(" ", "_")
    return {"INTERFACE": "INTERFACE", "FUNCTION": "FUNCTION", "METHOD": "METHOD", "CLASS": "CLASS"}.get(text, text)


def _overlay_kind(value: Any) -> str:
    return _kind(value)


def _kind_matches(canonical_kind: str, semantic_kind: str) -> bool:
    """Match LSP's generic FUNCTION with CodeSlicer's Python METHOD nodes.

    LSP SymbolKind has no language-specific distinction for a module-level
    Python function.  The canonical graph keeps its historical METHOD kind,
    so treating the two as different made exact Pyright results permanently
    unresolved despite identical file, line and name evidence.
    """
    left, right = str(canonical_kind or "").upper(), str(semantic_kind or "").upper()
    return left == right or {left, right} == {"METHOD", "FUNCTION"}


def _capability_supported(capabilities: dict[str, Any], method: str) -> bool:
    key = {
        "textDocument/documentSymbol": "documentSymbolProvider",
        "textDocument/definition": "definitionProvider",
        "textDocument/references": "referencesProvider",
        "textDocument/implementation": "implementationProvider",
        "textDocument/declaration": "declarationProvider",
        "textDocument/typeDefinition": "typeDefinitionProvider",
        "textDocument/hover": "hoverProvider",
        "textDocument/prepareCallHierarchy": "callHierarchyProvider",
        "textDocument/prepareTypeHierarchy": "typeHierarchyProvider",
        "workspace/symbol": "workspaceSymbolProvider",
    }.get(method)
    if not key:
        return False
    return bool(capabilities.get(key))


class _JsonRpcProcess:
    def __init__(self, executable: Path, arguments: list[str], cwd: Path, timeout_ms: int, max_response_bytes: int = MAX_LSP_RESPONSE_BYTES) -> None:
        self.executable = executable
        self.arguments = arguments
        self.cwd = cwd
        self.timeout = max(100, min(int(timeout_ms), MAX_LSP_TIMEOUT_MS)) / 1000
        self.max_response_bytes = max_response_bytes
        self.process: subprocess.Popen[bytes] | None = None
        self.messages: queue.Queue[dict[str, Any]] = queue.Queue()
        self.reader: threading.Thread | None = None
        self.next_id = 1

    def start(self) -> None:
        try:
            self.process = subprocess.Popen(
                [str(self.executable), *self.arguments], cwd=str(self.cwd), stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
            )
        except (OSError, ValueError) as exc:
            raise LspError(f"LSP server unavailable: {exc}") from exc
        self.reader = threading.Thread(target=self._read_loop, name="codeslicer-lsp-reader", daemon=True)
        self.reader.start()

    def _read_loop(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        stream = self.process.stdout
        try:
            while True:
                headers: dict[str, str] = {}
                while True:
                    line = stream.readline()
                    if not line:
                        self.messages.put({"_transport_error": "LSP server closed stdout"})
                        return
                    if line in {b"\r\n", b"\n"}:
                        break
                    try:
                        key, value = line.decode("ascii").split(":", 1)
                    except (UnicodeDecodeError, ValueError) as exc:
                        self.messages.put({"_transport_error": f"malformed LSP header: {exc}"})
                        return
                    headers[key.lower().strip()] = value.strip()
                try:
                    length = int(headers.get("content-length", "-1"))
                except ValueError:
                    length = -1
                if length < 0 or length > self.max_response_bytes:
                    self.messages.put({"_transport_error": "LSP response exceeds the configured size limit or has no Content-Length"})
                    return
                payload = stream.read(length)
                if len(payload) != length:
                    self.messages.put({"_transport_error": "truncated LSP response"})
                    return
                try:
                    message = json.loads(payload.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    self.messages.put({"_transport_error": f"malformed LSP JSON-RPC response: {exc}"})
                    return
                if isinstance(message, dict):
                    self.messages.put(message)
        except (OSError, ValueError) as exc:
            self.messages.put({"_transport_error": str(exc)})

    def _send(self, message: dict[str, Any]) -> None:
        if not self.process or not self.process.stdin:
            raise LspError("LSP server is not running")
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(payload) > self.max_response_bytes:
            raise LspError("LSP request exceeds the configured size limit")
        header = f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii")
        try:
            self.process.stdin.write(header + payload)
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise LspError(f"LSP server unavailable while sending request: {exc}") from exc

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        request_id = self.next_id
        self.next_id += 1
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                try:
                    self.notify("$/cancelRequest", {"id": request_id})
                except LspError:
                    pass
                raise LspTimeout(f"LSP request timed out: {method}")
            try:
                message = self.messages.get(timeout=remaining)
            except queue.Empty as exc:
                try:
                    self.notify("$/cancelRequest", {"id": request_id})
                except LspError:
                    pass
                raise LspTimeout(f"LSP request timed out: {method}") from exc
            if message.get("_transport_error"):
                raise LspError(str(message["_transport_error"]))
            if message.get("id") != request_id:
                continue
            if message.get("error"):
                error = message["error"]
                raise LspError(f"LSP {method} error: {error.get('message', error)}")
            return message.get("result")

    def close(self) -> None:
        if not self.process:
            return
        try:
            self.request("shutdown", {})
        except LspError:
            pass
        try:
            self.notify("exit")
        except LspError:
            pass
        try:
            if self.process.stdin:
                self.process.stdin.close()
        except OSError:
            pass
        try:
            self.process.wait(timeout=1)
        except (subprocess.TimeoutExpired, OSError):
            self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except (subprocess.TimeoutExpired, OSError):
                self.process.kill()
        self.process = None


def _client(project_path: Path, state: dict[str, Any], timeout_ms: int) -> _JsonRpcProcess:
    executable = _absolute_path(str(state.get("executable") or ""), label="LSP executable")
    if not executable.is_file():
        raise FileNotFoundError(f"LSP executable does not exist: {executable}")
    allowed, reason = _project_allowed(project_path, state)
    if not allowed:
        raise LspError(reason or "project is outside the configured workspace roots")
    client = _JsonRpcProcess(executable, [str(item) for item in state.get("arguments") or []], project_path, timeout_ms)
    client.start()
    try:
        result = client.request("initialize", {
            "processId": os.getpid(), "rootUri": _path_to_uri(project_path),
            "workspaceFolders": [{"uri": _path_to_uri(project_path), "name": project_path.name}],
            "capabilities": {"workspace": {"symbol": {"dynamicRegistration": False}}, "textDocument": {
                "definition": {"dynamicRegistration": False}, "references": {"dynamicRegistration": False},
                "implementation": {"dynamicRegistration": False}, "documentSymbol": {"dynamicRegistration": False},
            }},
            "clientInfo": {"name": "CodeSlicer", "version": "lsp-adapter-v1"},
        })
        client.notify("initialized", {})
        client.capabilities = result.get("capabilities", {}) if isinstance(result, dict) else {}
        return client
    except Exception:
        client.close()
        raise


def _normalize_location(value: Any, project_path: Path, roots: list[Path], diagnostics: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    uri = value.get("uri") or value.get("targetUri")
    raw_range = value.get("range") or value.get("targetSelectionRange")
    path = _uri_to_path(str(uri)) if uri else None
    source_range = _range(raw_range)
    if path is None or source_range is None:
        diagnostics.append({"code": "unresolved_location", "severity": "info", "message": "LSP returned a non-file URI or incomplete range"})
        return None
    if not _inside(path, roots):
        diagnostics.append({"code": "outside_workspace_root", "severity": "warning", "message": f"LSP location was outside the configured workspace roots: {uri}"})
        return None
    try:
        relative = path.relative_to(project_path).as_posix()
    except ValueError:
        relative = path.as_posix()
    return {"uri": str(uri), "file": relative, "range": source_range, "source": "local-lsp"}


def _locations(result: Any, project_path: Path, roots: list[Path], diagnostics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values = result if isinstance(result, list) else ([result] if isinstance(result, dict) else [])
    output = []
    for value in values[:MAX_LSP_ITEMS]:
        location = _normalize_location(value, project_path, roots, diagnostics)
        if location:
            output.append(location)
    if isinstance(values, list) and len(values) > MAX_LSP_ITEMS:
        diagnostics.append({"code": "response_truncated", "severity": "warning", "message": f"LSP response was bounded to {MAX_LSP_ITEMS} locations"})
    return output


def _document_symbols(result: Any, project_path: Path, roots: list[Path], diagnostics: list[dict[str, Any]], document_uri: str) -> list[dict[str, Any]]:
    values = result if isinstance(result, list) else []
    output: list[dict[str, Any]] = []
    def visit(items: list[Any]) -> None:
        for item in items:
            if len(output) >= MAX_LSP_ITEMS or not isinstance(item, dict):
                continue
            # LSP permits both DocumentSymbol (selectionRange/range on the
            # item) and SymbolInformation (a nested location).  Pyright uses
            # SymbolInformation here, so accepting only the former silently
            # turned every real document-symbol response into an unresolved
            # location.
            nested_location = item.get("location") if isinstance(item.get("location"), dict) else {}
            location = _normalize_location(
                {
                    "uri": item.get("uri") or nested_location.get("uri") or document_uri,
                    "range": item.get("selectionRange") or item.get("range") or nested_location.get("range"),
                },
                project_path,
                roots,
                diagnostics,
            )
            if location:
                location.update({"name": str(item.get("name") or ""), "kind": _kind(item.get("kind")), "semantic_id": (item.get("data") or {}).get("semantic_id") if isinstance(item.get("data"), dict) else None})
                output.append(location)
            children = item.get("children")
            if isinstance(children, list):
                visit(children)
    visit(values)
    return output


def _workspace_symbols(result: Any, project_path: Path, roots: list[Path], diagnostics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for item in (result if isinstance(result, list) else [])[:MAX_LSP_ITEMS]:
        if not isinstance(item, dict):
            continue
        location = _normalize_location(item.get("location") or {}, project_path, roots, diagnostics)
        if location:
            location.update({"name": str(item.get("name") or ""), "kind": _kind(item.get("kind")), "semantic_id": (item.get("data") or {}).get("semantic_id") if isinstance(item.get("data"), dict) else None})
            output.append(location)
    return output


def _source_server(state: dict[str, Any]) -> dict[str, Any]:
    return {"executable": str(state.get("executable") or ""), "name": Path(str(state.get("executable") or "lsp")).name}


def _build_overlay(project_path: Path, state: dict[str, Any], method: str, locations: list[dict[str, Any]], diagnostics: list[dict[str, Any]], *, query: dict[str, Any]) -> dict[str, Any]:
    capability = method
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    anchor_id = str(query.get("entity_id") or "")
    for index, location in enumerate(locations[:MAX_LSP_ITEMS]):
        node_id = f"lsp:{index}:{location.get('uri')}:{location['range']['start_line']}:{location['range']['start_column']}"
        node = {
            "id": node_id, "semantic_id": location.get("semantic_id"), "name": location.get("name") or Path(location["file"]).stem,
            "kind": location.get("kind") or "SYMBOL", "file": location["file"], "range": location["range"],
            "uri": location["uri"], "source_server": _source_server(state), "capability": capability,
            "evidence_class": "LSP_RUNTIME", "confidence": "unresolved", "mapping": {"status": "unresolved"},
        }
        nodes.append(node)
        if anchor_id:
            edge_kind = {"textDocument/definition": "DEFINES", "textDocument/references": "REFERENCES", "textDocument/implementation": "IMPLEMENTS"}.get(method, "LSP_CONTEXT")
            edges.append({"id": f"lsp-edge:{index}", "from": anchor_id, "to": node_id, "kind": edge_kind, "source": "lsp", "evidence_class": "LSP_RUNTIME", "confidence": "unresolved", "resolution": "unresolved", "confirmed": False})
    freshness = {"status": "fresh", "verified": True, "queried_at": _now()}
    return {
        "schema_version": LSP_OVERLAY_SCHEMA, "adapter_id": "lsp", "evidence_class": "LSP_RUNTIME",
        "confidence": "confirmed_if_exact", "freshness": freshness, "source_server": _source_server(state),
        "capability": capability, "method": method, "timestamp": _now(), "query": query,
        "nodes": nodes, "edges": edges, "diagnostics": diagnostics, "network_used": False, "privacy": lsp_privacy(),
        "bounded": True, "max_items": MAX_LSP_ITEMS,
    }


def build_lsp_overlay(project_path: str | Path, *, method: str, locations: list[dict[str, Any]], entity_id: str | None, diagnostics: list[dict[str, Any]], adapter_id: str = "lsp", source: str = "local-lsp", provenance: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a bounded, provenance-bearing semantic overlay for any LSP runtime.

    Mapping remains CodeSlicer-owned; this helper does not create canonical
    confirmed edges and is shared by the optional Agent-LSP integration.
    """
    project = Path(project_path).expanduser().resolve()
    state = {"executable": (provenance or {}).get("runtime", source)}
    overlay = _build_overlay(project, state, method, locations, diagnostics, query={"entity_id": entity_id})
    overlay["adapter_id"] = adapter_id
    overlay["provenance"] = dict(provenance or {})
    overlay["source"] = source
    for node in overlay["nodes"]:
        node["source"] = source
        node["provenance"] = dict(provenance or {})
    for edge in overlay["edges"]:
        edge["source"] = source
    return overlay


def _map_candidates(canonical: list[Any], semantic: dict[str, Any]) -> list[tuple[Any, str]]:
    semantic_id = str(semantic.get("semantic_id") or "")
    if semantic_id:
        matches = [(node, "stable semantic ID") for node in canonical if str(node.properties.get("semantic_id") or "") == semantic_id]
        if matches:
            return matches
    source_range = semantic.get("range") or {}
    matches = []
    for node in canonical:
        file_name = str(node.properties.get("file") or node.properties.get("path") or "").replace("\\", "/").lstrip("./").lower()
        target_file = str(semantic.get("file") or "").replace("\\", "/").lstrip("./").lower()
        if file_name != target_file or not _kind_matches(node.kind, _overlay_kind(semantic.get("kind"))):
            continue
        node_range = node.properties.get("definition_range") or {}
        if all(node_range.get(left) == source_range.get(right) for left, right in (("start_line", "start_line"), ("start_column", "start_column"), ("end_line", "end_line"), ("end_column", "end_column"))):
            matches.append((node, "exact source file + complete range + kind"))
    if matches:
        return matches
    # Pyright and similar servers commonly return a definition range while
    # CodeSlicer stores only the declaration line.  Preserve exact matching
    # above, then use the bounded local file/line/name fallback instead of
    # leaving a real local definition unresolved.
    semantic_name = str(semantic.get("name") or "").strip().lower()
    start_line = source_range.get("start_line")
    fallback: list[tuple[Any, str]] = []
    for node in canonical:
        file_name = str(node.properties.get("file") or node.properties.get("path") or "").replace("\\", "/").lstrip("./").lower()
        target_file = str(semantic.get("file") or "").replace("\\", "/").lstrip("./").lower()
        if file_name != target_file or not _kind_matches(node.kind, _overlay_kind(semantic.get("kind"))):
            continue
        node_line = node.properties.get("line")
        line_match = isinstance(start_line, int) and isinstance(node_line, int) and node_line in {start_line, start_line + 1}
        name_match = bool(semantic_name and semantic_name in {str(node.name or "").lower(), str(node.properties.get("name") or "").lower()})
        if line_match and (not semantic_name or name_match):
            strategy = "local file + declaration line + symbol name" if semantic_name else "local file + declaration line"
            fallback.append((node, strategy))
    if fallback:
        return fallback
    return matches


def map_lsp_overlay(overlay: dict[str, Any], canonical_graph: GraphDocument) -> dict[str, Any]:
    result = json.loads(json.dumps(overlay))
    canonical = list(canonical_graph.nodes)
    freshness = (result.get("freshness") or {}).get("status")
    for node in result.get("nodes", []):
        candidates = _map_candidates(canonical, node)
        if len(candidates) == 1:
            canonical_node, strategy = candidates[0]
            node["mapping"] = {"status": "confirmed" if freshness == "fresh" else "stale", "strategy": strategy, "canonical_node_id": canonical_node.id if freshness == "fresh" else None}
            node["confidence"] = "confirmed" if freshness == "fresh" else "stale"
        elif len(candidates) > 1:
            node["mapping"] = {"status": "ambiguous", "strategy": "multiple exact candidates", "canonical_node_id": None}
            node["confidence"] = "unresolved"
        else:
            node["mapping"] = {"status": "unresolved", "strategy": "no stable semantic ID or exact file/range/kind match", "canonical_node_id": None}
            node["confidence"] = "unresolved"
    node_by_id = {node.get("id"): node for node in result.get("nodes", [])}
    for edge in result.get("edges", []):
        target = node_by_id.get(edge.get("to"), {})
        anchor = next((item for item in canonical if item.id == edge.get("from")), None)
        target_status = target.get("mapping", {}).get("status")
        if anchor and target_status == "confirmed" and freshness == "fresh":
            edge.update({"resolution": "confirmed", "confidence": "confirmed", "confirmed": True})
        elif target_status in {"confirmed", "stale"}:
            edge.update({"resolution": "stale" if freshness != "fresh" else "likely", "confidence": "likely", "confirmed": False})
        else:
            edge.update({"resolution": "unresolved", "confidence": "unresolved", "confirmed": False})
    result["mapping_summary"] = {
        "confirmed": sum(1 for item in result.get("nodes", []) if item.get("mapping", {}).get("status") == "confirmed"),
        "ambiguous": sum(1 for item in result.get("nodes", []) if item.get("mapping", {}).get("status") == "ambiguous"),
        "unresolved": sum(1 for item in result.get("nodes", []) if item.get("mapping", {}).get("status") == "unresolved"),
    }
    return result


def _overlay_freshness(project_path: Path, state: dict[str, Any]) -> dict[str, Any]:
    overlay_path = Path(str(state.get("overlay_path") or ""))
    if not overlay_path.is_file():
        return {"status": "unknown", "verified": False}
    for item in state.get("source_fingerprints") or []:
        source = Path(str(item.get("path") or ""))
        if not source.is_file() or _sha256(source) != item.get("fingerprint"):
            return {"status": "stale", "verified": False, "reason": "queried source file changed"}
    recorded_head = state.get("project_head")
    current_head = git_context(project_path).get("head")
    if recorded_head and current_head and recorded_head != current_head:
        return {"status": "stale", "verified": False, "reason": "project Git HEAD changed"}
    return {"status": "fresh", "verified": True, "queried_at": state.get("queried_at")}


def lsp_status(project_path: str | Path) -> dict[str, Any]:
    project = Path(project_path).expanduser().resolve()
    state = _read_existing_state(project)
    if state.get("backend") == "agent_lsp":
        from .agent_lsp import agent_lsp_status
        return agent_lsp_status(project)
    if not state.get("enabled"):
        from .agent_lsp import agent_lsp_status
        agent_status = agent_lsp_status(project)
        if agent_status.get("enabled"):
            return agent_status
    diagnostics = list(state.get("diagnostics") or [])
    if state.get("status") == "error":
        return {"id": "lsp", "status": "error", "enabled": False, "freshness": {"status": "unknown", "verified": False}, "network_used": False, "privacy": lsp_privacy(), "diagnostics": diagnostics or ["invalid LSP adapter state"]}
    if not state.get("enabled"):
        return {"id": "lsp", "status": "disabled", "enabled": False, "freshness": {"status": "unknown", "verified": False}, "network_used": False, "privacy": lsp_privacy(), "diagnostics": diagnostics, "capabilities": state.get("capabilities", {})}
    try:
        executable = _absolute_path(str(state.get("executable") or ""), label="LSP executable")
    except ValueError as exc:
        return {"id": "lsp", "status": "unavailable", "enabled": True, "freshness": {"status": "unknown", "verified": False}, "network_used": False, "privacy": lsp_privacy(), "diagnostics": diagnostics + [str(exc)]}
    if not executable.is_file():
        return {"id": "lsp", "status": "unavailable", "enabled": True, "freshness": {"status": "unknown", "verified": False}, "network_used": False, "privacy": lsp_privacy(), "diagnostics": diagnostics + [f"LSP executable does not exist: {executable}"]}
    allowed, reason = _project_allowed(project, state)
    if not allowed:
        return {"id": "lsp", "status": "unavailable", "enabled": True, "freshness": {"status": "unknown", "verified": False}, "network_used": False, "privacy": lsp_privacy(), "diagnostics": diagnostics + [reason or "project is outside workspace roots"]}
    freshness = _overlay_freshness(project, state)
    status = "stale" if freshness["status"] == "stale" else ("ready" if state.get("last_probe_status") == "passed" else "configured")
    return {
        "id": "lsp", "status": status, "enabled": True, "freshness": freshness, "network_used": False, "privacy": lsp_privacy(),
        "executable": str(executable), "workspace_roots": [str(root) for root in _roots(state)],
        "config": {"executable": str(executable), "arguments": list(state.get("arguments") or []), "workspace_roots": [str(root) for root in _roots(state)], "backend": state.get("backend", "native_stdio"), "compile_commands": state.get("compile_commands")},
        "backend": state.get("backend", "native_stdio"), "server_family": state.get("server_family", "unknown"),
        "capabilities": state.get("capabilities", {}), "last_probe": state.get("last_probe"),
        "artifact": {"overlay_path": state.get("overlay_path"), "nodes": state.get("nodes", 0), "edges": state.get("edges", 0)},
        "diagnostics": diagnostics,
    }


def configure_lsp(project_path: str | Path, executable: str | Path, workspace_roots: list[str | Path], *, arguments: list[str] | None = None, timeout_ms: int = DEFAULT_LSP_TIMEOUT_MS, backend: str = "native_stdio", server_family: str = "unknown", compile_commands: str | Path | None = None) -> dict[str, Any]:
    project = Path(project_path).expanduser().resolve()
    if not project.is_dir():
        raise FileNotFoundError(f"Project directory does not exist: {project}")
    executable_path, roots, args = _validate_configuration(executable, workspace_roots, arguments)
    if not _inside(project, roots):
        raise ValueError("project must be inside one of the configured workspace roots")
    if backend not in {"native_stdio", "agent_lsp", "auto"}:
        raise ValueError("unsupported LSP backend; choose native_stdio, agent_lsp, or safe auto")
    if compile_commands is not None:
        # Validation is deliberately read-only.  An adapter configure action
        # must not copy/link a database or invoke a build tool.
        inspect_build_context(project, compile_commands=compile_commands)
    if backend == "agent_lsp":
        from .agent_lsp import configure_agent_lsp
        return configure_agent_lsp(project, executable_path, roots, server_args=args, compile_commands=compile_commands)
    state = _read_state(project)
    state.update({"enabled": True, "executable": str(executable_path), "arguments": args, "workspace_roots": [str(root) for root in roots], "timeout_ms": max(100, min(int(timeout_ms), MAX_LSP_TIMEOUT_MS)), "configured_at": _now(), "privacy_boundary": LSP_PRIVACY_BOUNDARY, "network_observed": False, "diagnostics": [], "backend": "native_stdio", "backend_selection_reason": "native short-lived fallback", "server_family": server_family, "compile_commands": str(Path(compile_commands).resolve()) if compile_commands is not None else None})
    _write_state(project, state)
    return lsp_status(project)


def preflight_lsp(project_path: str | Path, *, compile_commands: str | Path | None = None) -> dict[str, Any]:
    """Inspect semantic readiness without starting a server or changing files."""
    project = Path(project_path).expanduser().resolve()
    state = _read_existing_state(project)
    from .agent_lsp import agent_lsp_status
    agent_status = agent_lsp_status(project)
    if agent_status.get("enabled"):
        state = {**state, "backend": "agent_lsp", "executable": agent_status.get("executable"), "compile_commands": compile_commands or state.get("compile_commands")}
    languages = detect_languages(project)
    build_context = inspect_build_context(project, compile_commands=compile_commands or state.get("compile_commands"))
    executable_value = state.get("executable")
    executable = Path(str(executable_value)).expanduser() if executable_value else None
    available = bool(executable and executable.is_absolute() and executable.is_file())
    server_family = "agent-lsp" if state.get("backend") == "agent_lsp" else (state.get("server_family") or ("clangd" if "cpp" in languages else "unconfigured"))
    quality = dict(build_context["semantic_quality"])
    if "cpp" in languages and not available:
        quality["reasons"] = [*quality.get("reasons", []), "a local clangd executable has not been configured"]
    index_status = _overlay_freshness(project, state).get("status", "cold") if state.get("overlay_path") else "cold"
    next_steps: list[str] = []
    if not available:
        next_steps.append("Configure an already installed local language server")
    if "cpp" in languages and build_context["compile_commands"].get("status") != "available":
        next_steps.append("Generate or provide a fresh compilation database")
    if not next_steps and state.get("backend") == "agent_lsp":
        next_steps.append("Run an explicit Agent-LSP capability probe when semantic navigation is needed")
    return {
        "schema_version": "CodeSlicerSemanticPreflight/v1",
        "project_path": str(project),
        "write_policy": "read_only",
        "languages": languages,
        "server": {"family": server_family, "status": "available" if available else "not_configured", "executable": str(executable) if executable else None},
        "backend": {"selected": state.get("backend", "native_stdio"), "status": "available", "reason": "official Agent-LSP MCP runtime" if state.get("backend") == "agent_lsp" else state.get("backend_selection_reason", "native stdio is the safe local default")},
        "build_context": build_context,
        "index": {"status": index_status, "last_warm": state.get("last_warm")},
        "semantic_quality": quality,
        "next_steps": next_steps,
        "network_used": False,
        "privacy": lsp_privacy(),
    }


def disable_lsp(project_path: str | Path) -> dict[str, Any]:
    project = Path(project_path).expanduser().resolve()
    from .agent_lsp import agent_lsp_status
    if agent_lsp_status(project).get("enabled"):
        from .agent_lsp import shutdown_agent_lsp_runtime
        shutdown_agent_lsp_runtime(project)
        state = _read_state(project)
        state.update({"enabled": False, "updated_at": _now()})
        _write_state(project, state)
        agent_state = _state_path(project).with_name("agent_lsp.json")
        if agent_state.is_file():
            value = json.loads(agent_state.read_text(encoding="utf-8")); value["enabled"] = False; agent_state.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return agent_lsp_status(project)
    state = _read_state(project)
    state.update({"enabled": False, "updated_at": _now()})
    _write_state(project, state)
    return lsp_status(project)


def probe_lsp(project_path: str | Path, *, timeout_ms: int | None = None) -> dict[str, Any]:
    project = Path(project_path).expanduser().resolve()
    state = _read_state(project)
    from .agent_lsp import agent_lsp_status
    if agent_lsp_status(project).get("enabled"):
        from .agent_lsp import probe_agent_lsp
        return probe_agent_lsp(project, timeout_seconds=max(1, int((timeout_ms or DEFAULT_LSP_TIMEOUT_MS) / 1000)))
    if state.get("backend") == "agent_lsp":
        from .agent_lsp import probe_agent_lsp
        return probe_agent_lsp(project, timeout_seconds=max(1, int((timeout_ms or DEFAULT_LSP_TIMEOUT_MS) / 1000)))
    if not state.get("enabled"):
        return {**lsp_status(project), "probe": {"status": "skipped", "reason": "LSP adapter is disabled; configure it explicitly first"}}
    client = None
    try:
        client = _client(project, state, timeout_ms or int(state.get("timeout_ms", DEFAULT_LSP_TIMEOUT_MS)))
        capabilities = client.capabilities
        state.update({"last_probe_status": "passed", "last_probe": {"status": "passed", "timestamp": _now()}, "capabilities": capabilities, "diagnostics": []})
        _write_state(project, state)
        return {**lsp_status(project), "probe": {"status": "passed", "capabilities": capabilities}}
    except (LspError, FileNotFoundError, OSError, ValueError) as exc:
        state.update({"last_probe_status": "failed", "last_probe": {"status": "failed", "timestamp": _now(), "error": str(exc)}, "diagnostics": [str(exc)]})
        _write_state(project, state)
        return {**lsp_status(project), "probe": {"status": "error", "error": str(exc)}}
    finally:
        if client:
            client.close()


def query_lsp(project_path: str | Path, *, method: str, file: str | None = None, line: int = 0, character: int = 0, query: str = "", entity_id: str | None = None, timeout_ms: int | None = None) -> dict[str, Any]:
    project = Path(project_path).expanduser().resolve()
    state = _read_state(project)
    from .agent_lsp import agent_lsp_status
    if agent_lsp_status(project).get("enabled"):
        from .agent_lsp import query_agent_lsp
        return query_agent_lsp(project, method=method, file=file, line=line, character=character, entity_id=entity_id, timeout_seconds=max(1, int((timeout_ms or DEFAULT_LSP_TIMEOUT_MS) / 1000)))
    if state.get("backend") == "agent_lsp":
        from .agent_lsp import query_agent_lsp
        delegated = {"definition": "definition", "references": "references", "implementation": "implementation", "callHierarchy": "callHierarchy", "typeHierarchy": "typeHierarchy", "diagnostics": "diagnostics"}
        return query_agent_lsp(project, method=delegated.get(method, method), file=file, line=line, character=character, entity_id=entity_id, timeout_seconds=max(1, int((timeout_ms or DEFAULT_LSP_TIMEOUT_MS) / 1000)))
    allowed, reason = _project_allowed(project, state)
    if not state.get("enabled"):
        return {"status": "disabled", "error": "LSP adapter is disabled; configure it explicitly first", "network_used": False, "privacy": lsp_privacy()}
    if not allowed:
        return {"status": "unavailable", "error": reason, "network_used": False, "privacy": lsp_privacy()}
    methods = {"documentSymbol": "textDocument/documentSymbol", "definition": "textDocument/definition", "references": "textDocument/references", "implementation": "textDocument/implementation", "declaration": "textDocument/declaration", "typeDefinition": "textDocument/typeDefinition", "hover": "textDocument/hover", "workspace/symbol": "workspace/symbol"}
    rpc_method = methods.get(method, method if method in methods.values() else None)
    if not rpc_method:
        return {"status": "error", "error": f"unsupported LSP method: {method}", "network_used": False, "privacy": lsp_privacy()}
    if rpc_method != "workspace/symbol":
        if not file:
            return {"status": "error", "error": "file is required for this LSP method", "network_used": False, "privacy": lsp_privacy()}
        file_path = _absolute_path(file if Path(file).is_absolute() else project / file, label="LSP source file")
        if not _inside(file_path, [project]) or not file_path.is_file():
            return {"status": "unavailable", "error": "source file is outside the selected project or does not exist", "network_used": False, "privacy": lsp_privacy()}
        text_document = {"textDocument": {"uri": _path_to_uri(file_path)}}
    else:
        file_path = None
        text_document = {"query": query}
    client = None
    diagnostics: list[dict[str, Any]] = []
    try:
        client = _client(project, state, timeout_ms or int(state.get("timeout_ms", DEFAULT_LSP_TIMEOUT_MS)))
        if not _capability_supported(client.capabilities, rpc_method):
            diagnostics.append({"code": "unsupported_capability", "severity": "info", "message": f"Configured LSP server does not advertise {rpc_method}"})
            return {"status": "unsupported", "method": rpc_method, "diagnostics": diagnostics, "network_used": False, "privacy": lsp_privacy()}
        if rpc_method in {"textDocument/definition", "textDocument/references", "textDocument/implementation", "textDocument/declaration", "textDocument/typeDefinition", "textDocument/hover"}:
            params = {**text_document, "position": {"line": max(0, int(line)), "character": max(0, int(character))}}
            if rpc_method == "textDocument/references":
                params["context"] = {"includeDeclaration": True}
        else:
            params = text_document
        if file_path is not None:
            _open_selected_document(client, file_path)
        raw = client.request(rpc_method, params)
        roots = _roots(state)
        if rpc_method == "textDocument/documentSymbol":
            locations = _document_symbols(raw, project, roots, diagnostics, text_document.get("textDocument", {}).get("uri", ""))
        elif rpc_method == "workspace/symbol":
            locations = _workspace_symbols(raw, project, roots, diagnostics)
        elif rpc_method == "textDocument/hover":
            contents = raw.get("contents") if isinstance(raw, dict) else raw
            locations = [{"uri": _path_to_uri(file_path), "file": file_path.relative_to(project).as_posix(), "range": {"start_line": int(line), "start_column": int(character), "end_line": int(line), "end_column": int(character)}, "source": "local-lsp", "hover": contents}] if file_path else []
        else:
            locations = _locations(raw, project, roots, diagnostics)
        overlay = _build_overlay(project, state, rpc_method, locations, diagnostics, query={"file": str(file_path) if file_path else None, "line": line, "character": character, "entity_id": entity_id, "query": query})
        overlay["status"] = "ok"
        target = ensure_project_storage(project) / "artifacts" / "lsp" / "overlay.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(overlay, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        state.update({"overlay_path": str(target), "queried_at": overlay["timestamp"], "nodes": len(overlay["nodes"]), "edges": len(overlay["edges"]), "project_head": git_context(project).get("head"), "source_fingerprints": ([{"path": str(file_path), "fingerprint": _sha256(file_path)}] if file_path else []), "last_query": {"method": rpc_method, "timestamp": overlay["timestamp"]}, "diagnostics": diagnostics})
        _write_state(project, state)
        return overlay
    except LspTimeout as exc:
        return {"status": "timeout", "method": rpc_method, "diagnostics": [{"code": "timeout", "severity": "warning", "message": str(exc)}], "network_used": False, "privacy": lsp_privacy()}
    except (LspError, FileNotFoundError, OSError, ValueError) as exc:
        return {"status": "unavailable", "method": rpc_method, "diagnostics": [{"code": "server_unavailable", "severity": "warning", "message": str(exc)}], "network_used": False, "privacy": lsp_privacy()}
    finally:
        if client:
            client.close()


def load_lsp_overlay(project_path: str | Path) -> dict[str, Any] | None:
    project = Path(project_path).expanduser().resolve()
    state = _read_state(project)
    if not state.get("enabled"):
        from .agent_lsp import load_agent_lsp_overlay
        overlay = load_agent_lsp_overlay(project)
        if overlay is not None:
            return overlay
    if not state.get("enabled") or not state.get("overlay_path"):
        return None
    path = Path(str(state["overlay_path"]))
    if not path.is_file():
        return None
    try:
        overlay = json.loads(path.read_text(encoding="utf-8"))
        overlay["freshness"] = _overlay_freshness(project, state)
        return overlay
    except (OSError, ValueError, json.JSONDecodeError):
        return {"schema_version": LSP_OVERLAY_SCHEMA, "adapter_id": "lsp", "status": "error", "evidence_class": "LSP_RUNTIME", "freshness": {"status": "unknown", "verified": False}, "nodes": [], "edges": [], "diagnostics": [{"code": "invalid_overlay", "severity": "warning", "message": "invalid LSP overlay"}], "network_used": False, "privacy": lsp_privacy()}
