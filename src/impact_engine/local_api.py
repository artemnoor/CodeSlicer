"""HTTP transport facade for the local CodeSlicer UI."""
from impact_engine.local_api_domain import *
from impact_engine.local_api_state import *

class LocalApiHandler(SimpleHTTPRequestHandler):
    server_version = "ImpactEngineLocalAPI/0.5"

    @property
    def state(self) -> LocalApiState:
        return self.server.impact_state  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:
        # Keep stdout clean for callers that launch the server from a terminal.
        return

    def _send_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 2_000_000:
            raise ValueError("Request body exceeds 2 MB")
        value = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(value, dict):
            raise ValueError("Request body must be a JSON object")
        return value

    def _host_allowed(self) -> bool:
        """Apply the Host boundary to API *and* static routes."""
        host = (urlsplit("//" + self.headers.get("Host", "")).hostname or "").lower()
        if self.state.docker_local_ui or not self.state.allow_remote:
            allowed = {"localhost", "127.0.0.1", "::1"}
        else:
            allowed = self.state.allowed_hosts
        if host in allowed:
            return True
        self._send_json(403, {"status": "error", "error": "local_host_required"})
        return False

    def _api_access_allowed(self) -> bool:
        """Remote API is API-only and needs both allowlisted Host and secret."""
        if not self._host_allowed():
            return False
        if self.state.allow_remote and not self.state.docker_local_ui:
            supplied = self.headers.get("X-CodeSlicer-Remote-Token", "")
            if self.state.remote_token and secrets.compare_digest(supplied, self.state.remote_token):
                return True
            self._send_json(403, {"status": "error", "error": "remote_api_token_required"})
            return False
        return True

    def _project_state_allowed(self) -> bool:
        if not self.state.project_state_mismatch():
            return True
        self._send_json(409, {"status": "project_state_mismatch", "project_state": self.state.project_state()})
        return False

    def _process_approval(self, project_path: str, action: str, payload: dict[str, Any], body: dict[str, Any]) -> bool:
        """Consume an exact one-time approval or return an actionable pending record.

        Browser-side ``window.confirm`` is intentionally not trusted: only a
        separately issued local-host token can authorize a subprocess or a
        network-capable upstream action.
        """
        approval_id = body.get("approval_id")
        approval_token = body.get("approval_token")
        if approval_id and approval_token:
            ApprovalStore(project_path).consume(str(approval_id), str(approval_token), action, payload)
            return True
        pending = ApprovalStore(project_path).request(action, payload)
        command = f"impact-engine --json approvals approve \"{Path(project_path).resolve()}\" \"{pending['approval_id']}\""
        self._send_json(409, {
            "status": "pending_approval", "approval": pending,
            "message": f"Approval required. Run locally: {command}",
            "next_step": command,
        })
        return False

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send_json(204, {})

    def do_GET(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            if not self._host_allowed():
                return
            if parsed.path.startswith("/api/") and not self._api_access_allowed():
                return
            if parsed.path.startswith("/api/") and parsed.path != "/api/health" and not self._project_state_allowed():
                return
            if parsed.path == "/api/health":
                return self._send_json(200, {
                    "status": "ok",
                    "service": "impact-engine-local-api",
                    "api_contract_version": LOCAL_API_CONTRACT_VERSION,
                    "capabilities": {
                        "managed_tools": True,
                        "tools_endpoint": "/api/tools",
                    },
                    "session_token": self.state.session_token,
                })
            if parsed.path == "/api/state":
                return self._send_json(200, self.state.snapshot(include_graph=False))
            if parsed.path == "/api/progress":
                return self._send_json(200, {"status": "ok", "progress": self.state.progress})
            if parsed.path == "/api/overview":
                project_path = self.state.project_path or self.state.default_project
                if not project_path:
                    return self._send_json(200, {"status": "incomplete", "project": None, "freshness": {"status": "missing", "verified": False}, "coverage": {"status": "unknown", "languages": []}, "evidence_sources": [], "privacy": {"mode": "local-only", "network_used": False}})
                project = Path(str(project_path)).expanduser().resolve()
                if not project.is_dir():
                    return self._send_json(404, {
                        "status": "error", "error": "project_not_found",
                        "message": f"Project directory does not exist: {project}",
                        "project_path": str(project),
                    })
                return self._send_json(200, _project_overview(str(project_path), self.state))
            if parsed.path == "/api/graph":
                snapshot = self.state.snapshot()
                if not snapshot.get("graph"):
                    return self._send_json(404, {"error": "no_analysis", "message": "Analyze a project first"})
                return self._send_json(200, {"status": "ok", "project_path": snapshot["project_path"], "graph": snapshot["graph"]})
            if parsed.path == "/api/libraries":
                return self._send_json(200, {"status": "ok", "items": self._libraries()})
            if parsed.path == "/api/inventory":
                analysis = self.state.snapshot(include_graph=False).get("analysis") or {}
                return self._send_json(200, {"status": "ok", "inventory": analysis.get("inventory", {})})
            if parsed.path == "/api/adapters":
                project_path = self.state.project_path or self.state.default_project
                if not project_path:
                    return self._send_json(200, {"status": "ok", "project_path": None, "adapters": []})
                return self._send_json(200, {"status": "ok", "project_path": str(Path(project_path).resolve()), "adapters": AdapterRegistry(project_path).list(), "privacy": {"mode": "local-only", "network_used": False}})
            if parsed.path == "/api/tools":
                project_path = self.state.project_path or self.state.default_project
                if not project_path:
                    return self._send_json(200, {"status": "ok", "api_contract_version": LOCAL_API_CONTRACT_VERSION, "project_path": None, "tools": []})
                return self._send_json(200, {"status": "ok", "api_contract_version": LOCAL_API_CONTRACT_VERSION, "project_path": str(Path(project_path).resolve()), "tools": ToolRuntime(project_path).catalog(), "privacy": {"mode": "local-only", "network_used": False}})
            if parsed.path == "/api/adapters/graphify/viewer/status":
                project_path = self.state.project_path or self.state.default_project
                graph_file = find_graphify_graph(project_path) if project_path else None
                graph_available = bool(graph_file and graph_file.is_file())
                cache = _graphify_viewer_cache_path(project_path) if project_path else None
                viewer_available = bool(cache and graphify_viewer_ready(project_path))
                viewer_stale = bool(viewer_available and graph_available and cache.stat().st_mtime < graph_file.stat().st_mtime)
                viewer_status = (
                    "missing" if not graph_available
                    else "viewer_missing" if not viewer_available
                    else "stale" if viewer_stale
                    else "ready"
                )
                return self._send_json(200, {
                    "status": viewer_status,
                    "available": viewer_available and not viewer_stale,
                    "graph_available": graph_available,
                    "viewer_available": viewer_available,
                    "viewer_stale": viewer_stale,
                    "artifact": str(graph_file) if graph_file else None,
                    "artifact_bytes": graph_file.stat().st_size if graph_available else 0,
                    "renderer": "graphify-upstream-html",
                    "privacy": {"mode": "local-only", "network_used": False},
                })
            if parsed.path == "/api/adapters/graphify/viewer":
                project_path = self.state.project_path or self.state.default_project
                if not project_path:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"No active project")
                    return
                # This endpoint is deliberately independent from the status
                # endpoint above: every HTTP request has its own handler
                # invocation, so never rely on variables from another route.
                graph_file = find_graphify_graph(project_path)
                graph_available = graph_file.is_file()
                cache = _graphify_viewer_cache_path(project_path)
                stale = bool(cache.is_file() and graph_available and cache.stat().st_mtime < graph_file.stat().st_mtime)
                if cache.is_file() and graphify_viewer_ready(project_path) and not stale:
                    html = cache.read_text(encoding="utf-8")[:4 * 1024 * 1024]
                    response_code = 200
                else:
                    detail = "Кэш устарел: граф Graphify изменился после последнего renderer." if stale else "Визуализация ещё не подготовлена. Запустите подтверждённое обновление Graphify — renderer сохранит локальный HTML-артефакт."
                    html = f"<!DOCTYPE html><html><body style='background:#0f0f1a;color:#e0e0e0;font-family:sans-serif;padding:40px;'><h2>Graphify Native Viewer</h2><p>{detail}</p><p>Этот GET не запускает внешний процесс.</p></body></html>"
                    response_code = 409
                encoded = html.encode("utf-8")
                self.send_response(response_code)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'; media-src 'none'; object-src 'none'; base-uri 'none'; frame-ancestors 'self'")
                self.end_headers()
                self.wfile.write(encoded)
                return
            if parsed.path == "/api/adapters/lsp/status":
                project_path = self.state.project_path or self.state.default_project
                if not project_path:
                    return self._send_json(200, {"status": "disabled", "adapter_id": "lsp", "network_used": False, "privacy": lsp_privacy()})
                return self._send_json(200, {"status": "ok", "adapter": AdapterRegistry(project_path).status("lsp"), "privacy": lsp_privacy()})
            return super().do_GET()
        except Exception as exc:
            self._send_json(500, {"status": "error", "error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            if not self._host_allowed():
                return
            if parsed.path.startswith("/api/") and not self._api_access_allowed():
                return
            origin = self.headers.get("Origin")
            if origin:
                origin_host = urlparse(origin).netloc.lower()
                host = self.headers.get("Host", "").lower()
                if not host or origin_host != host:
                    return self._send_json(403, {"status": "error", "error": "cross_origin_request_rejected"})
            if parsed.path.startswith("/api/"):
                provided = self.headers.get("X-CodeSlicer-Session", "")
                if not provided or not secrets.compare_digest(provided, self.state.session_token):
                    return self._send_json(403, {"status": "error", "error": "local_session_required"})
            if not self._project_state_allowed():
                return
            body = self._read_json()
            # A deliberately narrow live OpenTelemetry receiver. It accepts
            # OTLP/HTTP *JSON* only, on a loopback-bound local API, and only
            # after the project owner opted in via /api/adapters/otel/live.
            # The raw request is never persisted; AdapterRegistry writes the
            # sanitized evidence overlay instead.
            if parsed.path == "/v1/traces":
                if self.client_address[0] not in {"127.0.0.1", "::1"}:
                    return self._send_json(403, {"status": "error", "error": "OTLP receiver accepts loopback clients only"})
                project_path = str(self.state.project_path or self.state.default_project or "").strip()
                if not project_path:
                    return self._send_json(409, {"status": "error", "error": "Select and analyze a local project before enabling OTLP capture"})
                registry = AdapterRegistry(project_path)
                receiver = registry.otel_live_receiver()
                if not receiver.get("enabled"):
                    return self._send_json(403, {"status": "disabled", "error": "OTLP live receiver is disabled; enable it explicitly in Sources"})
                endpoint = str(receiver.get("endpoint") or "otlp-http-json-loopback")
                imported = registry.import_otel_document(body, source_label=endpoint)
                summary = (imported.get("overlay") or {}).get("summary") or {}
                return self._send_json(200, {"status": "accepted", "spans": summary.get("spans", 0), "traces": summary.get("traces", 0), "raw_payload_stored": False, "adapter": imported.get("adapter")})
            if parsed.path == "/api/analyze":
                project_path = str(body.get("project_path") or self.state.default_project or "").strip()
                if not project_path:
                    return self._send_json(400, {"status": "error", "error": "project_path is required"})
                try:
                    return self._send_json(200, self.state.analyze(project_path))
                except AnalysisCancelled:
                    return self._send_json(409, {"status": "cancelled", "progress": self.state.progress})
                except Exception as exc:
                    with self.state.lock:
                        self.state.last_error = str(exc)
                    return self._send_json(422, {"status": "error", "error": str(exc)})
            if parsed.path == "/api/analyze/cancel":
                return self._send_json(200, self.state.cancel_analysis())
            if parsed.path == "/api/graph/projection":
                project_path = str(body.get("project_path") or self.state.project_path or self.state.default_project or "").strip()
                if not project_path:
                    return self._send_json(400, {"status": "error", "error": "project_path is required"})
                try:
                    return self._send_json(200, _graph_projection(project_path, body))
                except (ValueError, OSError, TypeError) as exc:
                    return self._send_json(422, {"status": "error", "error": str(exc)})
            if parsed.path == "/api/graph-workspace":
                project_path = str(body.get("project_path") or self.state.project_path or self.state.default_project or "").strip()
                if not project_path:
                    return self._send_json(400, {"status": "error", "error": "project_path is required"})
                try:
                    return self._send_json(200, _graph_workspace(project_path, body))
                except (ValueError, OSError, TypeError) as exc:
                    return self._send_json(422, {"status": "error", "error": str(exc)})
            tool_parts = parsed.path.strip("/").split("/")
            if len(tool_parts) >= 2 and tool_parts[:2] == ["api", "tools"]:
                project_path = str(body.get("project_path") or self.state.project_path or self.state.default_project or "").strip()
                if not project_path:
                    return self._send_json(400, {"status": "error", "error": "project_path is required"})
                runtime = ToolRuntime(project_path)
                if len(tool_parts) == 2:
                    return self._send_json(200, {"status": "ok", "tools": runtime.catalog(), "privacy": {"mode": "local-only", "network_used": False}})
                if len(tool_parts) != 4:
                    return self._send_json(404, {"status": "error", "error": "unknown tool runtime endpoint"})
                tool_id, action = tool_parts[2], tool_parts[3]
                try:
                    if action == "connect":
                        payload = {"tool_id": tool_id, "ref": body.get("ref") or ""}
                        if not self._process_approval(project_path, "managed_tool.connect", payload, body):
                            return
                        tool = runtime.connect(tool_id, confirmed=True, ref=body.get("ref"))
                        return self._send_json(200, {"status": "ok", "tool": tool, "privacy": {"mode": "local-only", "network_used": True, "network_action": "explicit-git-clone"}})
                    if action == "executable":
                        tool = runtime.configure_executable(tool_id, body.get("executable") or "")
                        return self._send_json(200, {"status": "ok", "tool": tool, "privacy": {"mode": "local-only", "network_used": False}})
                    if action == "docs":
                        return self._send_json(200, {"status": "ok", **runtime.docs(tool_id, query=str(body.get("query") or ""), limit=int(body.get("limit", 40)))})
                    if action == "document":
                        return self._send_json(200, {"status": "ok", **runtime.read_document(
                            tool_id,
                            str(body.get("path") or ""),
                            offset=int(body.get("offset") or 0),
                            limit_bytes=int(body.get("limit_bytes") or 128 * 1024),
                        )})
                    if action == "help":
                        executable = runtime.status(tool_id).get("executable") or ""
                        payload = {"executable": executable, "argv": ["--help"], "cwd": str(Path(project_path).resolve()), "timeout_seconds": 30, "network_expected": False, "tool_id": tool_id}
                        if not self._process_approval(project_path, "managed_tool.help", payload, body):
                            return
                        return self._send_json(200, {"status": "ok", **runtime.help(tool_id)})
                    if action == "run":
                        argv = body.get("argv") or []
                        workspace = str(body.get("workspace") or "project")
                        timeout_seconds = int(body.get("timeout_seconds", 60))
                        payload = {"tool_id": tool_id, "argv": argv, "workspace": workspace, "timeout_seconds": timeout_seconds}
                        if not self._process_approval(project_path, "managed_tool.run", payload, body):
                            return
                        return self._send_json(200, runtime.run(tool_id, argv=argv, confirmed=True, workspace=workspace, timeout_seconds=timeout_seconds))
                    return self._send_json(404, {"status": "error", "error": "unknown tool runtime action"})
                except (FileNotFoundError, ValueError, OSError, RuntimeError) as exc:
                    return self._send_json(422, {"status": "error", "error": str(exc)})
            adapter_parts = parsed.path.strip("/").split("/")
            if len(adapter_parts) == 4 and adapter_parts[:3] == ["api", "adapters", "otel"] and adapter_parts[3] in {"live-enable", "live-disable", "live-status"}:
                project_path = str(body.get("project_path") or self.state.project_path or self.state.default_project or "").strip()
                if not project_path:
                    return self._send_json(400, {"status": "error", "error": "project_path is required"})
                registry = AdapterRegistry(project_path)
                endpoint = f"http://127.0.0.1:{self.server.server_address[1]}/v1/traces"
                action = adapter_parts[3]
                if action == "live-enable":
                    adapter = registry.set_otel_live_receiver(True, endpoint=endpoint)
                    return self._send_json(200, {"status": "ok", "adapter": adapter, "receiver": registry.otel_live_receiver(), "privacy": {"mode": "loopback-otlp-json", "network_used": False, "raw_payload_stored": False}})
                if action == "live-disable":
                    adapter = registry.set_otel_live_receiver(False, endpoint=endpoint)
                    return self._send_json(200, {"status": "ok", "adapter": adapter, "receiver": registry.otel_live_receiver(), "privacy": {"mode": "loopback-otlp-json", "network_used": False, "raw_payload_stored": False}})
                return self._send_json(200, {"status": "ok", "adapter": registry.status("otel"), "receiver": registry.otel_live_receiver(), "privacy": {"mode": "loopback-otlp-json", "network_used": False, "raw_payload_stored": False}})
            if len(adapter_parts) == 4 and adapter_parts[:2] == ["api", "adapters"] and adapter_parts[3] in {"native-profile", "native-run", "native-config"}:
                adapter_id = adapter_parts[2]
                project_path = str(body.get("project_path") or self.state.project_path or self.state.default_project or "").strip()
                if not project_path:
                    return self._send_json(400, {"status": "error", "error": "project_path is required"})
                try:
                    registry = AdapterRegistry(project_path)
                    if adapter_parts[3] == "native-profile":
                        return self._send_json(200, {"status": "ok", "adapter_id": adapter_id, "native": registry.status(adapter_id).get("native", native_profile(adapter_id)), "privacy": {"mode": "local-only", "network_used": False}})
                    if adapter_parts[3] == "native-config":
                        adapter = registry.configure_native_executable(adapter_id, body.get("executable"))
                        return self._send_json(200, {"status": "ok", "adapter": adapter, "privacy": {"mode": "local-only", "network_used": False}})
                    operation = str(body.get("operation") or "")
                    query = str(body.get("query") or "")
                    timeout_seconds = int(body.get("timeout_seconds", 60))
                    payload = {"adapter_id": adapter_id, "operation": operation, "query": query, "cwd": str(Path(project_path).resolve()), "timeout_seconds": timeout_seconds, "network_expected": False}
                    if not self._process_approval(project_path, "native_tool.run", payload, body):
                        return
                    result = run_native_operation(
                        project_path, adapter_id, operation,
                        confirmed=True, query=query,
                        configured_executable=registry._state(adapter_id).get("native_executable"),
                        timeout_seconds=timeout_seconds,
                    )
                    generated = result.get("generated_artifact")
                    if result.get("status") == "completed" and generated and adapter_id in {"openapi", "scip", "cyclonedx", "spdx", "sarif"}:
                        try:
                            # A native generator is an explicit user action;
                            # importing its local output is safe and leaves it
                            # disabled until the user chooses to enable it.
                            result["imported_artifact"] = registry.import_artifact(adapter_id, generated)
                        except (ValueError, OSError) as exc:
                            result["import_error"] = str(exc)
                    return self._send_json(200, result)
                except (FileNotFoundError, ValueError, OSError) as exc:
                    return self._send_json(422, {"status": "error", "error": str(exc)})
            adapter_action = None
            adapter_id = None
            if len(adapter_parts) == 4 and adapter_parts[:3] == ["api", "adapters", "lsp"] and adapter_parts[3] in {"configure", "preflight", "probe", "disable", "query"}:
                project_path = str(body.get("project_path") or self.state.project_path or self.state.default_project or "").strip()
                if not project_path:
                    return self._send_json(400, {"status": "error", "error": "project_path is required"})
                try:
                    action = adapter_parts[3]
                    if action == "configure":
                        adapter = configure_lsp(project_path, body.get("executable") or "", body.get("workspace_roots") or [], arguments=body.get("arguments") or [], timeout_ms=int(body.get("timeout_ms", 5000)), backend=str(body.get("backend") or "native_stdio"), server_family=str(body.get("server_family") or "unknown"), compile_commands=body.get("compile_commands"))
                        return self._send_json(200, {"status": "ok", "adapter": adapter, "privacy": lsp_privacy()})
                    if action == "preflight":
                        return self._send_json(200, {"status": "ok", "preflight": preflight_lsp(project_path, compile_commands=body.get("compile_commands")), "privacy": lsp_privacy()})
                    if action == "probe":
                        configured = AdapterRegistry(project_path).status("lsp").get("config") or {}
                        payload = {"executable": configured.get("executable", ""), "argv": list(configured.get("arguments") or []), "cwd": str(Path(project_path).resolve()), "timeout_ms": int(body.get("timeout_ms", 5000)), "network_expected": False}
                        if not self._process_approval(project_path, "lsp.probe", payload, body):
                            return
                        return self._send_json(200, {"status": "ok", "adapter": probe_lsp(project_path), "privacy": lsp_privacy()})
                    if action == "disable":
                        return self._send_json(200, {"status": "ok", "adapter": disable_lsp(project_path), "privacy": lsp_privacy()})
                    configured = AdapterRegistry(project_path).status("lsp").get("config") or {}
                    payload = {"executable": configured.get("executable", ""), "argv": list(configured.get("arguments") or []), "cwd": str(Path(project_path).resolve()), "method": str(body.get("method") or ""), "file": body.get("file") or "", "line": int(body.get("line", 0)), "character": int(body.get("character", 0)), "query": str(body.get("query") or ""), "entity_id": body.get("entity_id") or "", "timeout_ms": int(body.get("timeout_ms", 5000)), "network_expected": False}
                    if not self._process_approval(project_path, "lsp.query", payload, body):
                        return
                    result = query_lsp(project_path, method=payload["method"], file=body.get("file"), line=payload["line"], character=payload["character"], query=payload["query"], entity_id=body.get("entity_id"), timeout_ms=payload["timeout_ms"])
                    graph = _semantic_graph(project_path, {}, body.get("graph_path"))
                    if result.get("nodes") and graph:
                        result = {**result, "mapped_overlay": map_lsp_overlay(result, graph)}
                    return self._send_json(200, {"status": result.get("status", "ok"), "result": result, "privacy": lsp_privacy()})
                except (FileNotFoundError, ValueError, OSError) as exc:
                    return self._send_json(422, {"status": "error", "error": str(exc)})
            if len(adapter_parts) == 4 and adapter_parts[:2] == ["api", "adapters"] and adapter_parts[3] in {"enable", "disable"}:
                adapter_id, adapter_action = adapter_parts[2], adapter_parts[3]
            if adapter_action:
                project_path = str(body.get("project_path") or self.state.project_path or self.state.default_project or "").strip()
                if not project_path:
                    return self._send_json(400, {"status": "error", "error": "project_path is required"})
                try:
                    enabled = adapter_action == "enable"
                    adapter = AdapterRegistry(project_path).set_enabled(adapter_id, enabled)
                    return self._send_json(200, {"status": "ok", "adapter": adapter, "privacy": {"mode": "local-only", "network_used": False}})
                except (FileNotFoundError, ValueError, OSError) as exc:
                    return self._send_json(422, {"status": "error", "error": str(exc)})
            if len(adapter_parts) == 4 and adapter_parts[:2] == ["api", "adapters"] and adapter_parts[3] == "import":
                adapter_id = adapter_parts[2]
                project_path = str(body.get("project_path") or self.state.project_path or self.state.default_project or "").strip()
                artifact_path = str(body.get("artifact_path") or body.get("path") or "").strip()
                if not project_path or not artifact_path:
                    return self._send_json(400, {"status": "error", "error": "project_path and artifact_path are required"})
                try:
                    result = AdapterRegistry(project_path).import_artifact(adapter_id, artifact_path)
                    return self._send_json(200, {"status": "ok", "import_status": result.get("status"), **{key: value for key, value in result.items() if key != "status"}, "privacy": {"mode": "local-only", "network_used": False}})
                except (FileNotFoundError, ValueError, OSError) as exc:
                    return self._send_json(422, {"status": "error", "error": str(exc)})
            if parsed.path == "/api/architecture":
                project_path = str(body.get("project_path") or self.state.project_path or self.state.default_project or "").strip()
                if not project_path:
                    return self._send_json(400, {"status": "error", "error": "project_path is required"})
                overlay_mode = str(body.get("overlay") or "codeslicer").lower()
                if overlay_mode not in {"codeslicer", "graphify", "combined"}:
                    return self._send_json(400, {"status": "error", "error": "overlay must be codeslicer, graphify, or combined"})
                registry = AdapterRegistry(project_path)
                overlay = _bounded_overlay(registry.overlay("graphify")) if overlay_mode in {"graphify", "combined"} else None
                status = registry.status("graphify")
                scip_status = registry.status("scip")
                openapi_status = registry.status("openapi")
                asyncapi_status = registry.status("asyncapi")
                otel_status = registry.status("otel")
                joern_status = registry.status("joern")
                security_statuses = {adapter_id: registry.status(adapter_id) for adapter_id in ("cyclonedx", "spdx", "sarif")}
                external_graph_statuses = {adapter_id: registry.status(adapter_id) for adapter_id in ("graphify", "codegraph")}
                overview = _project_overview(project_path, self.state)
                result = {
                    "mode": "architecture", "overlay_mode": overlay_mode,
                    "status": "ok", "code_slicer": {"enabled": True},
                    "health_status": overview.get("status", "unknown"),
                    "freshness": overview.get("freshness", {"status": "unknown", "verified": False}),
                    "coverage": overview.get("coverage", {"status": "unknown"}),
                    "diagnostics": overview.get("diagnostics", []),
                    "evidence_sources": _adapter_evidence_sources(project_path),
                    "graphify": overlay or {"status": status["status"], "message": "Import and enable a local Graphify graph.json to inspect the architecture overlay."},
                    "external_graphs": {
                        adapter_id: {
                            "status": external_status.get("status"), "enabled": external_status.get("enabled", False),
                            "freshness": external_status.get("freshness"), "entities": external_status.get("artifact", {}).get("nodes", 0),
                            "relationships": external_status.get("artifact", {}).get("edges", 0),
                            "diagnostics": external_status.get("diagnostics", [])[:8], "network_used": False,
                            "instruction": "Import an existing local external graph. CodeSlicer never downloads, runs, or uploads graph tools.",
                        } for adapter_id, external_status in external_graph_statuses.items()
                    },
                    "scip": {
                        "status": scip_status.get("status"), "enabled": scip_status.get("enabled", False),
                        "freshness": scip_status.get("freshness"), "network_used": False,
                        "symbols": scip_status.get("artifact", {}).get("nodes", 0),
                        "references_and_implementations": scip_status.get("artifact", {}).get("edges", 0),
                        "instruction": "Import an existing local .scip index. CodeSlicer does not generate or upload it automatically.",
                    },
                    "lsp": {
                        "status": registry.status("lsp").get("status"), "enabled": registry.status("lsp").get("enabled", False),
                        "freshness": registry.status("lsp").get("freshness"), "network_used": False, "privacy": lsp_privacy(),
                        "capabilities": registry.status("lsp").get("capabilities", {}),
                        "instruction": "Configure an existing local LSP executable and probe it explicitly. CodeSlicer never installs or starts one automatically.",
                    },
                    "openapi": {
                        "status": openapi_status.get("status"), "enabled": openapi_status.get("enabled", False),
                        "freshness": openapi_status.get("freshness"), "network_used": False,
                        "boundaries": openapi_status.get("artifact", {}).get("nodes", 0),
                        "diagnostics": openapi_status.get("diagnostics", [])[:8],
                        "instruction": "Import an existing local OpenAPI/Swagger document. CodeSlicer never downloads or generates one.",
                    },
                    "asyncapi": {
                        "status": asyncapi_status.get("status"), "enabled": asyncapi_status.get("enabled", False),
                        "freshness": asyncapi_status.get("freshness"), "network_used": False,
                        "boundaries": asyncapi_status.get("artifact", {}).get("nodes", 0),
                        "diagnostics": asyncapi_status.get("diagnostics", [])[:8],
                        "instruction": "Import an existing local AsyncAPI document. Broker URLs are metadata only; CodeSlicer never connects.",
                    },
                    "otel": {
                        "status": otel_status.get("status"), "enabled": otel_status.get("enabled", False),
                        "freshness": otel_status.get("freshness"), "network_used": False,
                        "privacy": {"mode": "local-only", "network_used": False, "raw_attributes_stored": False, "redaction": "allowlist"},
                        "format": otel_status.get("artifact", {}).get("format"),
                        "traces": otel_status.get("artifact", {}).get("traces", 0),
                        "spans": otel_status.get("artifact", {}).get("spans", 0),
                        "services": otel_status.get("artifact", {}).get("services", 0),
                        "diagnostics": otel_status.get("diagnostics", [])[:8],
                        "instruction": "Import an existing local OTLP JSON or Jaeger JSON trace. CodeSlicer never connects to a collector or endpoint.",
                    },
                    "joern": {
                        "status": joern_status.get("status"), "enabled": joern_status.get("enabled", False),
                        "freshness": joern_status.get("freshness"), "network_used": False, "overlay_only": True,
                        "participates_in_ranking": False, "nodes": joern_status.get("artifact", {}).get("nodes", 0),
                        "edges": joern_status.get("artifact", {}).get("edges", 0), "paths": joern_status.get("paths", 0),
                        "findings": joern_status.get("findings", 0), "diagnostics": joern_status.get("diagnostics", [])[:8],
                        "instruction": "Import an existing local Joern JSON interchange artifact. CodeSlicer never installs or starts Joern automatically.",
                    },
                    "security": {
                        adapter_id: {
                            "status": status.get("status"), "enabled": status.get("enabled", False),
                            "freshness": status.get("freshness"), "network_used": False,
                            "components": status.get("components", 0), "findings": status.get("findings", 0),
                            "licenses": status.get("licenses", 0), "severity": status.get("severity", {}),
                            "tool": status.get("artifact", {}).get("tool", {}),
                            "diagnostics": status.get("diagnostics", [])[:8],
                            "instruction": "Import an existing local security report. CodeSlicer does not scan, resolve advisories, or upload it.",
                        } for adapter_id, status in security_statuses.items()
                    },
                    "adapters": registry.list(), "privacy": {"mode": "local-only", "network_used": False},
                    "visualize_compare": {
                        "available": bool((Path(project_path).resolve() / ".impact_engine" / "graph.json").is_file() and status.get("artifact", {}).get("artifact_path")),
                        "command": f"impact-engine visualize-compare {Path(project_path).resolve() / '.impact_engine' / 'graph.json'} {status.get('artifact', {}).get('artifact_path') or '<local-graphify.json>'}",
                    },
                }
                mapping_summaries = {item.get("id"): _adapter_mapping_summary(project_path, str(item.get("id"))) for item in result.get("adapters", []) if item.get("id")}
                for adapter_id, summary in mapping_summaries.items():
                    if adapter_id in result and isinstance(result[adapter_id], dict):
                        result[adapter_id]["mapping_summary"] = summary
                    if adapter_id in result.get("security", {}) and isinstance(result["security"].get(adapter_id), dict):
                        result["security"][adapter_id]["mapping_summary"] = summary
                result["adapters"] = [{**item, "mapping_summary": mapping_summaries.get(item.get("id"), item.get("mapping_summary"))} for item in result.get("adapters", [])]
                return self._send_json(200, result)
            if parsed.path == "/api/load-graph":
                project_path = str(body.get("project_path") or self.state.default_project or "").strip()
                graph_path = str(body.get("graph_path") or "").strip()
                if not project_path or not graph_path:
                    return self._send_json(400, {"status": "error", "error": "project_path and graph_path are required"})
                project = Path(project_path).expanduser().resolve()
                candidate = Path(graph_path).expanduser().resolve()
                if not project.is_dir() or not candidate.is_file():
                    return self._send_json(422, {"status": "error", "error": "project_path or graph_path does not exist"})
                with self.state.lock:
                    self.state.project_path = str(project)
                    self.state.analysis = None
                if not self.state._load_existing_graph(str(candidate)):
                    return self._send_json(422, {"status": "error", "error": "graph does not belong to project or is invalid"})
                return self._send_json(200, self.state.snapshot())
            if parsed.path == "/api/impact":
                graph = self._graph_document()
                result = impact_query(
                    graph,
                    target=str(body.get("target") or ""),
                    symbol=body.get("symbol"),
                    direction=str(body.get("direction") or "both"),
                    max_depth=int(body.get("max_depth", 20)),
                    min_confidence=float(body.get("min_confidence", 0.0)),
                )
                return self._send_json(200, {"status": "ok", "result": result})
            if parsed.path == "/api/review":
                project_path = str(body.get("project_path") or self.state.project_path or self.state.default_project or "").strip()
                if not project_path:
                    return self._send_json(400, {"status": "error", "error": "project_path is required"})
                project = Path(project_path).expanduser().resolve()
                if not project.is_dir():
                    return self._send_json(422, {"status": "error", "error": "project_path must be an existing directory"})
                ensure_project_storage(project)
                analysis = self.state.snapshot(include_graph=False).get("analysis") or {}
                requested_graph_path = str(body.get("graph_path") or analysis.get("graph_path") or "").strip()
                graph = None
                current = self.state.snapshot().get("graph")
                loaded_graph_path = str(analysis.get("graph_path") or "").strip()
                if current and Path(str(self.state.project_path)).resolve() == project and (
                    not requested_graph_path or Path(loaded_graph_path).expanduser().resolve() == Path(requested_graph_path).expanduser().resolve()
                ):
                    graph = GraphDocument.from_dict(current)
                local_graph_paths = {(project / ".impact_engine" / "graph.json").resolve(), (project / "graph.json").resolve()}
                review_graph_path = None if requested_graph_path and Path(requested_graph_path).expanduser().resolve() in local_graph_paths and graph is not None else (requested_graph_path or None)
                report = build_review_report(
                    str(project), graph=graph, diff_text=body.get("diff_text"),
                    graph_path=review_graph_path,
                    base=body.get("base"), refresh=str(body.get("refresh") or "auto"),
                    max_results=int(body.get("max_results", 10)),
                    run_tests=str(body.get("run_tests") or "suggested"),
                    deep=bool(body.get("deep", False)),
                    entity=str(body.get("entity")) if body.get("entity") else None,
                )
                # Metadata only: external graph overlays are never fed back
                # into review scoring, impact ranking, or test selection.
                review_registry = AdapterRegistry(str(project))
                report["external_graph_sources"] = []
                for adapter_id in ("graphify", "codegraph"):
                    external_status = review_registry.status(adapter_id)
                    external_artifact = external_status.get("artifact") or {}
                    report["external_graph_sources"].append({
                        "adapter_id": adapter_id, "source": adapter_id, "evidence_class": "DOC_INFERRED",
                        "status": external_status.get("status"), "freshness": external_status.get("freshness"),
                        "entities": external_artifact.get("nodes", 0), "relationships": external_artifact.get("edges", 0),
                        "source_path": external_artifact.get("source_path"), "fingerprint": external_artifact.get("source_fingerprint"),
                        "confidence": "confirmed_or_likely", "network_used": False,
                    })
                from impact_engine.review_history import record_review
                report["review_id"] = record_review(str(project), report)
                return self._send_json(200, _mode_api_response("review", report))
            if parsed.path == "/api/inspect":
                project_path = str(body.get("project_path") or self.state.project_path or self.state.default_project or "").strip()
                entity = str(body.get("entity") or "").strip()
                if not project_path or not entity:
                    return self._send_json(400, {"status": "error", "error": "project_path and entity are required"})
                ensure_project_storage(project_path)
                report = build_inspect_report(
                    project_path,
                    entity=entity,
                    graph_path=body.get("graph_path"),
                    refresh=str(body.get("refresh") or "never"),
                    max_context=int(body.get("max_context", 12)),
                )
                report["semantic_evidence"] = _semantic_evidence(project_path, report, body.get("graph_path"))
                report["lsp_evidence"] = _lsp_evidence(project_path, report, body.get("graph_path"))
                report["boundary_evidence"] = _boundary_evidence(project_path, report, body.get("graph_path"))
                report["otel_evidence"] = _otel_evidence(project_path, report, body.get("graph_path"))
                report["security_evidence"] = _security_evidence(project_path, report, body.get("graph_path"))
                report["external_graph_evidence"] = _external_graph_evidence(project_path, report)
                return self._send_json(200, _mode_api_response("inspect", report))
            if parsed.path == "/api/investigate":
                project_path = str(body.get("project_path") or self.state.project_path or self.state.default_project or "").strip()
                entity = str(body.get("entity") or "").strip()
                if not project_path or not entity:
                    return self._send_json(400, {"status": "error", "error": "project_path and entity are required"})
                ensure_project_storage(project_path)
                if bool(body.get("runtime_validate", False)):
                    payload = {"executable": "python", "argv": ["-m", "pytest"], "cwd": str(Path(project_path).resolve()), "timeout_seconds": 60, "network_expected": False, "entity": entity, "graph_path": body.get("graph_path") or ""}
                    if not self._process_approval(project_path, "investigate.runtime_validate", payload, body):
                        return
                report = build_investigate_report(
                    project_path,
                    entity=entity,
                    graph_path=body.get("graph_path"),
                    direction=str(body.get("direction") or "both"),
                    depth=int(body.get("depth", 8)),
                    runtime_validate=bool(body.get("runtime_validate", False)),
                    max_nodes=int(body.get("max_nodes", 500)),
                    max_edges=int(body.get("max_edges", 1000)),
                    refresh=str(body.get("refresh") or "never"),
                )
                overlay_mode = str(body.get("overlay") or "codeslicer").lower()
                if overlay_mode in {"graphify", "combined"}:
                    overlay = _bounded_overlay(AdapterRegistry(project_path).overlay("graphify"))
                    report["architecture_overlay"] = overlay or {"status": "unavailable", "message": "Graphify overlay is not enabled with a fresh local artifact."}
                if bool(body.get("semantic_context", False)):
                    report["semantic_context"] = _bounded_semantic_context(project_path, report, body.get("graph_path"), max_items=min(max(int(body.get("semantic_max_items", 40)), 1), 100))
                if bool(body.get("lsp_context", False)):
                    report["lsp_context"] = _bounded_lsp_context(project_path, report, body.get("graph_path"), max_items=min(max(int(body.get("lsp_max_items", 40)), 1), 100))
                if bool(body.get("boundary_context", False)):
                    report["boundary_context"] = _bounded_boundary_context(project_path, report, body.get("graph_path"), max_items=min(max(int(body.get("boundary_max_items", 40)), 1), 100))
                if bool(body.get("otel_context", False)):
                    report["otel_context"] = _bounded_otel_context(project_path, report, body.get("graph_path"), max_items=min(max(int(body.get("otel_max_items", 40)), 1), 100))
                if bool(body.get("security_context", False)):
                    report["security_context"] = _bounded_security_context(project_path, report, body.get("graph_path"), max_items=min(max(int(body.get("security_max_items", 40)), 1), 100))
                if bool(body.get("joern_context", False)):
                    report["joern_context"] = _bounded_joern_context(
                        project_path, report,
                        max_nodes=min(max(int(body.get("joern_max_nodes", 80)), 1), 200),
                        max_edges=min(max(int(body.get("joern_max_edges", 160)), 1), 400),
                        max_paths=min(max(int(body.get("joern_max_paths", 40)), 1), 100),
                    )
                if bool(body.get("external_graph_context", False)):
                    report["external_graph_context"] = _external_graph_evidence(project_path, report, max_items=min(max(int(body.get("external_graph_max_items", 40)), 1), 100))
                return self._send_json(200, _mode_api_response("investigate", report))
            if parsed.path == "/api/ci":
                project_path = str(body.get("project_path") or self.state.project_path or self.state.default_project or "").strip()
                if not project_path:
                    return self._send_json(400, {"status": "error", "error": "project_path is required"})
                ensure_project_storage(project_path)
                diff_text = body.get("diff_text")
                if body.get("diff_file") and diff_text is None:
                    diff_text = Path(str(body["diff_file"])).expanduser().resolve().read_text(encoding="utf-8")
                if bool(body.get("run_tests", False)):
                    command = body.get("test_command") or "<configured test command>"
                    payload = {"executable": "test-runner", "argv": [str(command)], "cwd": str(Path(project_path).resolve()), "timeout_seconds": 600, "network_expected": False}
                    if not self._process_approval(project_path, "ci.run_tests", payload, body):
                        return
                report = build_ci_report(
                    project_path,
                    base=body.get("base"),
                    policy_path=body.get("policy_path") or body.get("policy"),
                    graph_path=body.get("graph_path"),
                    diff_text=diff_text,
                    refresh=str(body.get("refresh") or "auto"),
                    run_tests=bool(body.get("run_tests", False)),
                    test_command=body.get("test_command"),
                )
                response: dict[str, Any] = _mode_api_response("ci", report)
                if str(body.get("format") or "json") == "sarif":
                    response["sarif"] = to_sarif(report)
                return self._send_json(200, response)
            if parsed.path == "/api/review/run-test":
                project_path = str(body.get("project_path") or self.state.project_path or "").strip()
                file_name = str(body.get("file") or "").strip().replace("\\", "/")
                if not project_path or not file_name:
                    return self._send_json(400, {"status": "error", "error": "project_path and file are required"})
                project = Path(project_path).expanduser().resolve()
                candidate = (project / file_name).resolve()
                if not project.is_dir() or not candidate.is_file() or project not in candidate.parents:
                    return self._send_json(422, {"status": "error", "error": "file must be an existing file inside project_path"})
                command = _test_command_for_file(project, file_name)
                if not command:
                    return self._send_json(422, {"status": "unsupported", "error": "No safe test runner is configured for this file"})
                timeout = min(max(int(body.get("timeout", 120)), 1), 600)
                payload = {"executable": command[0], "argv": command[1:], "cwd": str(project), "timeout_seconds": timeout, "network_expected": False, "test_file": file_name}
                if not self._process_approval(str(project), "review.run_test", payload, body):
                    return
                try:
                    completed = subprocess.run(
                        command, cwd=project, capture_output=True, text=True,
                        timeout=timeout, shell=False,
                    )
                except subprocess.TimeoutExpired as exc:
                    return self._send_json(504, {"status": "timeout", "command": command, "stdout": exc.stdout or "", "stderr": exc.stderr or ""})
                return self._send_json(200, {
                    "status": "ok", "command": command, "exit_code": completed.returncode,
                    "passed": completed.returncode == 0,
                    "stdout": completed.stdout[-12000:], "stderr": completed.stderr[-12000:],
                })
            if parsed.path == "/api/review/feedback":
                project_path = str(body.get("project_path") or self.state.project_path or "").strip()
                from impact_engine.review_history import add_feedback
                add_feedback(project_path, str(body.get("review_id") or ""), str(body.get("value") or ""), body.get("reason"))
                return self._send_json(200, {"status": "ok"})
            if parsed.path == "/api/review/history":
                project_path = str(body.get("project_path") or self.state.project_path or "").strip()
                from impact_engine.review_history import list_history
                return self._send_json(200, {"status": "ok", "items": list_history(project_path, int(body.get("limit", 20)))})
            if parsed.path == "/api/query":
                return self._send_json(200, {"status": "ok", "result": self._run_typed_query(body)})
            if parsed.path == "/api/incremental":
                return self._send_json(501, {"status": "unsupported", "message": "Use impact-engine analyze-incremental for a real changed-file comparison."})
            return self._send_json(404, {"status": "error", "error": "not_found"})
        except Exception as exc:
            self._send_json(500, {"status": "error", "error": str(exc)})

    def _graph_document(self) -> GraphDocument:
        graph = self.state.snapshot().get("graph")
        if not graph:
            raise RuntimeError("No analyzed graph. Run /api/analyze first.")
        return GraphDocument.from_dict(graph)

    def _run_typed_query(self, body: dict[str, Any]) -> dict[str, Any]:
        graph = self._graph_document()
        query_type = str(body.get("type") or "impact")
        if query_type.startswith("diagnostics"):
            metadata = graph.metadata
            return {
                "request": body,
                "response": {
                    "unknown_regions": metadata.get("unknown_regions", {}),
                    "diagnostics": metadata.get("diagnostics", {}),
                },
            }
        if query_type.startswith("explain") and body.get("from") and body.get("to"):
            return {"request": body, "response": explain_edge(graph, str(body["from"]), str(body["to"]), body.get("kind"))}
        result = impact_query(
            graph,
            target=str(body.get("target") or ""),
            direction="downstream" if "database" in query_type else "upstream",
            max_depth=int(body.get("max_depth", 8)),
            min_confidence=float(body.get("min_confidence", 0.0)),
        )
        return {"request": body, "response": result}

    def _libraries(self) -> list[dict[str, Any]]:
        analysis = self.state.snapshot(include_graph=False).get("analysis") or {}
        inventory = analysis.get("inventory") or {}
        graph = self.state.snapshot().get("graph") or {}
        contexts = {
            str(item.get("library")): item
            for item in (graph.get("metadata", {}).get("support_pack_context", []) or [])
            if isinstance(item, dict)
        }
        names: list[tuple[str, str, str]] = []
        for ecosystem, values in (inventory.get("declared_dependencies_by_ecosystem", {}) or {}).items():
            for value in values or []:
                names.append((str(value), str(ecosystem), "declared"))
        for ecosystem, values in (inventory.get("external_imports_by_ecosystem", {}) or {}).items():
            for value in values or []:
                names.append((str(value), str(ecosystem), "external_import"))
        result = []
        seen = set()
        for name, ecosystem, source in sorted(names):
            key = (name, ecosystem)
            if key in seen:
                continue
            seen.add(key)
            context = contexts.get(name, {})
            result.append({
                "name": name,
                "ecosystem": ecosystem,
                "version": None,
                "status": source,
                "trust_level": context.get("trust_level"),
                "confidence_cap": None,
                "coverage": "unknown",
                "last_checked": None,
                "source": source,
            })
        return result


def create_server(host: str, port: int, frontend_dir: str, state: LocalApiState) -> ThreadingHTTPServer:
    directory = str(Path(frontend_dir).resolve())

    class Handler(LocalApiHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=directory, **kwargs)

    server = ThreadingHTTPServer((host, port), Handler)
    server.impact_state = state  # type: ignore[attr-defined]
    server.session_token = state.session_token  # type: ignore[attr-defined]
    return server


def default_frontend_dir() -> str:
    """Locate the UI in a checkout first and in an installed wheel second."""
    source_frontend = Path(__file__).resolve().parents[2] / "frontend"
    if source_frontend.is_dir():
        return str(source_frontend)
    packaged_frontend = package_files("impact_engine").joinpath("frontend")
    if packaged_frontend.is_dir():
        return str(packaged_frontend)
    # Keep the old path as a useful diagnostic if a broken third-party build
    # omits static files; the release E2E test guards this case.
    return str(source_frontend)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="impact-engine-local-api")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--allow-remote", action="store_true", help="Allow a non-loopback bind; this exposes the local API to the network.")
    parser.add_argument("--remote-token", default=None, help="Required secret for generic --allow-remote API mode. It is never returned by /api/health.")
    parser.add_argument("--allowed-host", action="append", default=[], help="Allowed Host in generic remote API mode; repeat for each host.")
    parser.add_argument("--docker-local-ui", action="store_true", help="Permit a Docker-bound UI only through a loopback-published port; keeps loopback Host validation and uses no remote bearer token.")
    parser.add_argument("--project-id", default=None, help="Required stable Docker state namespace for --docker-local-ui (letters, numbers, dot, underscore and hyphen only).")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--frontend-dir", default=default_frontend_dir())
    parser.add_argument("--default-project", default=None)
    args = parser.parse_args(argv)
    try:
        loopback = ipaddress.ip_address(args.host).is_loopback
    except ValueError:
        loopback = args.host.lower() == "localhost"
    if not loopback and not args.allow_remote:
        parser.error("non-loopback --host requires explicit --allow-remote")
    if args.docker_local_ui and not args.allow_remote:
        parser.error("--docker-local-ui requires --allow-remote because Docker binds 0.0.0.0 inside its network namespace")
    if args.docker_local_ui and (not args.project_id or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", args.project_id)):
        parser.error("--docker-local-ui requires --project-id with 1-64 letters, numbers, dot, underscore or hyphen")
    if args.allow_remote and not args.docker_local_ui and (not args.remote_token or not args.allowed_host):
        parser.error("generic --allow-remote requires both --remote-token and at least one --allowed-host")
    # This path must work from both a source checkout and an installed wheel.
    # ``local_api.py`` itself lives under site-packages in the latter case.
    from impact_engine.support_packs.paths import builtin_support_packs_root
    state = LocalApiState(args.default_project, str(builtin_support_packs_root()), allow_remote=args.allow_remote, remote_token=args.remote_token, docker_local_ui=args.docker_local_ui, allowed_hosts=args.allowed_host, docker_project_id=args.project_id)
    server = create_server(args.host, args.port, args.frontend_dir, state)
    print(f"Impact Engine local API: http://{args.host}:{args.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
