"""Persistent local-UI state and analysis lifecycle."""
from impact_engine.local_api_domain import *

class LocalApiState:
    def __init__(self, default_project: str | None, support_pack_root: str, *, allow_remote: bool = False, remote_token: str | None = None, docker_local_ui: bool = False, allowed_hosts: list[str] | None = None, docker_project_id: str | None = None) -> None:
        self.default_project = default_project
        self.support_pack_root = support_pack_root
        self.project_path: str | None = default_project
        self.analysis: dict[str, Any] | None = None
        self.last_error: str | None = None
        self.analyzed_at: float | None = None
        self.progress: dict[str, Any] = {"status": "idle"}
        self.lock = threading.RLock()
        self.cancellation: CancellationToken | None = None
        self.analysis_running = False
        self.session_token = secrets.token_urlsafe(32)
        self.allow_remote = allow_remote
        self.remote_token = remote_token
        self.docker_local_ui = docker_local_ui
        self.docker_project_id = docker_project_id
        self.allowed_hosts = {host.lower() for host in (allowed_hosts or [])}
        if default_project:
            try:
                ensure_project_storage(default_project)
            except (FileNotFoundError, OSError):
                pass
        self._load_existing_graph()

    def _identity_path(self, project: Path) -> Path:
        return project / ".impact_engine" / "codeslicer-project-identity"

    def _identity_matches(self, project: Path) -> bool:
        path = self._identity_path(project)
        if not path.is_file():
            return not self.docker_local_ui
        try:
            return secrets.compare_digest(path.read_text(encoding="utf-8").strip(), _project_identity(project, self.docker_project_id))
        except OSError:
            return False

    def _write_identity(self, project: Path) -> None:
        path = self._identity_path(project)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(_project_identity(project, self.docker_project_id) + "\n", encoding="utf-8")
        os.replace(temporary, path)

    @staticmethod
    def _persistent_optional_state_exists(project: Path) -> bool:
        """Ignore directory scaffolding, but never silently reuse adapter state."""
        candidates = (
            project / ".impact_engine" / "graph.json",
            project / ".codeslicer" / "adapters",
            project / ".codeslicer" / "artifacts",
            project / ".codeslicer" / "tool-runtime",
            project / ".codeslicer" / "tool-runtime-location.json",
        )
        for candidate in candidates:
            if candidate.is_file():
                return True
            if candidate.is_dir() and any(path.is_file() for path in candidate.rglob("*")):
                return True
        return False

    def project_state(self) -> dict[str, Any]:
        """Never expose a prior Docker namespace as the selected project."""
        if not self.docker_local_ui or not self.project_path:
            return {"status": "not_applicable", "verified": True}
        project = Path(self.project_path).expanduser().resolve()
        identity = self._identity_path(project)
        if identity.is_file() and self._identity_matches(project):
            return {"status": "matched", "verified": True, "project_id": self.docker_project_id}
        if not identity.is_file() and not self._persistent_optional_state_exists(project):
            return {"status": "fresh", "verified": True, "project_id": self.docker_project_id}
        return {
            "status": "project_state_mismatch", "verified": False, "project_id": self.docker_project_id,
            "message": "Persistent Docker state belongs to a different project namespace. Set a new CODESLICER_PROJECT_ID or remove that namespace's named volumes before analysis.",
        }

    def project_state_mismatch(self) -> bool:
        return self.project_state().get("status") == "project_state_mismatch"

    def _load_existing_graph(self, graph_path: str | None = None) -> bool:
        """Hydrate API state from a graph produced by the CLI.

        CLI and the local UI are separate processes.  Without this handoff a
        successful CLI analysis leaves the UI in the misleading ``idle`` state
        until the analysis is run a second time through the browser.
        """
        if not self.project_path:
            return False
        project = Path(self.project_path).expanduser().resolve()
        if self.docker_local_ui and self.project_state_mismatch():
            return False
        candidates = [Path(graph_path).expanduser().resolve()] if graph_path else [
            project / ".impact_engine" / "graph.json",
            project / "graph.json",
        ]
        for candidate in candidates:
            if not candidate.is_file():
                continue
            try:
                graph = GraphDocument.from_json(candidate.read_text(encoding="utf-8"))
                metadata = graph.metadata or {}
                recorded_project = metadata.get("project_path")
                if recorded_project and Path(str(recorded_project)).expanduser().resolve() != project:
                    continue
                inventory = asdict(scan_project_inventory(str(project)))
                progress = metadata.get("analysis_progress") or {
                    "status": "loaded",
                    "current": {"stage": "loaded", "message": "Граф загружен из cache"},
                }
                self.analysis = {
                    "status": "ok",
                    "path": str(project),
                    "project_path": str(project),
                    "graph_path": str(candidate),
                    "inventory": inventory,
                    "languages": inventory.get("languages", []),
                    "extractors_used": metadata.get("extractors", []),
                    "diagnostics": metadata.get("diagnostics", {}),
                    "nodes": len(graph.nodes),
                    "edges": len(graph.edges),
                    "graph": graph.to_dict(),
                    "progress": progress,
                    "loaded_from_existing_graph": True,
                }
                self.project_path = str(project)
                self.analyzed_at = candidate.stat().st_mtime
                self.progress = progress
                self.last_error = None
                return True
            except (OSError, ValueError, TypeError):
                continue
        return False

    def snapshot(self, include_graph: bool = True) -> dict[str, Any]:
        with self.lock:
            analysis = self.analysis or {}
            project_exists = False
            if self.project_path:
                try:
                    project_exists = Path(self.project_path).expanduser().is_dir()
                except OSError:
                    project_exists = False
            result = {
                "status": "error" if self.last_error else ("ready" if self.analysis else "idle"),
                "has_analysis": bool(self.analysis),
                "project_path": self.project_path,
                "project_exists": project_exists,
                "analyzed_at": self.analyzed_at,
                "error": self.last_error,
                "progress": self.progress,
                "project_state": self.project_state(),
                "analysis": {key: value for key, value in analysis.items() if key != "graph"},
            }
            if include_graph:
                result["graph"] = analysis.get("graph")
            return result

    def analyze(self, project_path: str) -> dict[str, Any]:
        path = Path(project_path).expanduser().resolve()
        if not path.exists() or not path.is_dir():
            raise FileNotFoundError(f"Project directory does not exist: {project_path}")
        if self.docker_local_ui and self.project_state_mismatch():
            raise RuntimeError(self.project_state()["message"])
        out_path = path / ".impact_engine" / "graph.json"
        with self.lock:
            if self.analysis_running:
                raise RuntimeError("analysis already running")
            token = CancellationToken()
            self.cancellation = token
            self.analysis_running = True
            self.last_error = None
            self.progress = {
                "status": "running",
                "current": {
                    "stage": "starting", "message": "Подготовка локального анализа",
                    "processed": 0, "total": 0, "overall_percent": 0.0,
                    "elapsed_seconds": 0.0, "eta_seconds": None, "cancellable": True,
                },
            }
        def report_progress(event: dict[str, Any]) -> None:
            with self.lock:
                self.progress = {"status": "running", "current": event}
        try:
            # Keep the public local_api monkeypatch seam intact for callers and
            # integration tests while keeping state management in this module.
            from impact_engine import local_api as local_api_facade

            result = local_api_facade.analyze_project_core(
                str(path),
                out_path=str(out_path),
                support_pack_root=self.support_pack_root,
                enable_remote_registry=False,
                create_research_requests=True,
                progress_callback=report_progress,
                cancellation=token,
            )
        except AnalysisCancelled:
            with self.lock:
                current = dict((self.progress or {}).get("current") or {})
                current.update({"cancellable": False, "eta_seconds": None})
                self.progress = {"status": "cancelled", "current": current}
            raise
        except Exception as exc:
            with self.lock:
                self.last_error = str(exc)
                self.progress = {"status": "failed", "error": str(exc), "current": self.progress.get("current", {})}
            raise
        finally:
            with self.lock:
                self.analysis_running = False
                self.cancellation = None
        with self.lock:
            self.project_path = str(path)
            self.analysis = result
            self.last_error = None
            self.analyzed_at = time.time()
            self.progress = result.get("progress", {"status": "completed"})
        if self.docker_local_ui:
            self._write_identity(path)
        return self.snapshot()

    def cancel_analysis(self) -> dict[str, Any]:
        with self.lock:
            if not self.analysis_running or self.cancellation is None:
                return {"status": "idle", "message": "No analysis is running", "progress": self.progress}
            self.cancellation.cancel()
            return {"status": "cancelling", "message": "Cancellation requested", "progress": self.progress}




__all__ = [name for name in globals() if not name.startswith("__")]
