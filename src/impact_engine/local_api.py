"""Local HTTP API and static frontend host for the Impact Engine UI.

The browser never runs analysis logic and never receives a mock graph.  This
module is a thin same-origin boundary around the existing analysis and impact
query APIs.  It intentionally uses only the Python standard library so the
local distribution stays lightweight.
"""
from __future__ import annotations

import argparse
import json
import threading
import time
from dataclasses import asdict
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from impact_engine.analysis.pipeline import analyze_project_core
from impact_engine.inventory.scanner import scan_project_inventory
from impact_engine.impact import explain_edge, impact_query
from impact_engine.models import GraphDocument


class LocalApiState:
    def __init__(self, default_project: str | None, support_pack_root: str) -> None:
        self.default_project = default_project
        self.support_pack_root = support_pack_root
        self.project_path: str | None = default_project
        self.analysis: dict[str, Any] | None = None
        self.last_error: str | None = None
        self.analyzed_at: float | None = None
        self.progress: dict[str, Any] = {"status": "idle"}
        self.lock = threading.RLock()
        self._load_existing_graph()

    def _load_existing_graph(self, graph_path: str | None = None) -> bool:
        """Hydrate API state from a graph produced by the CLI.

        CLI and the local UI are separate processes.  Without this handoff a
        successful CLI analysis leaves the UI in the misleading ``idle`` state
        until the analysis is run a second time through the browser.
        """
        if not self.project_path:
            return False
        project = Path(self.project_path).expanduser().resolve()
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
            result = {
                "status": "error" if self.last_error else ("ready" if self.analysis else "idle"),
                "has_analysis": bool(self.analysis),
                "project_path": self.project_path,
                "analyzed_at": self.analyzed_at,
                "error": self.last_error,
                "progress": self.progress,
                "analysis": {key: value for key, value in analysis.items() if key != "graph"},
            }
            if include_graph:
                result["graph"] = analysis.get("graph")
            return result

    def analyze(self, project_path: str) -> dict[str, Any]:
        path = Path(project_path).expanduser().resolve()
        if not path.exists() or not path.is_dir():
            raise FileNotFoundError(f"Project directory does not exist: {project_path}")
        out_path = path / ".impact_engine" / "graph.json"
        def report_progress(event: dict[str, Any]) -> None:
            with self.lock:
                self.progress = {"status": "running", "current": event}
        result = analyze_project_core(
            str(path),
            out_path=str(out_path),
            support_pack_root=self.support_pack_root,
            enable_remote_registry=False,
            create_research_requests=True,
            progress_callback=report_progress,
        )
        with self.lock:
            self.project_path = str(path)
            self.analysis = result
            self.last_error = None
            self.analyzed_at = time.time()
            self.progress = result.get("progress", {"status": "completed"})
        return self.snapshot()


class LocalApiHandler(SimpleHTTPRequestHandler):
    server_version = "ImpactEngineLocalAPI/0.4"

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
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
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

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send_json(204, {})

    def do_GET(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/api/health":
                return self._send_json(200, {"status": "ok", "service": "impact-engine-local-api"})
            if parsed.path == "/api/state":
                return self._send_json(200, self.state.snapshot(include_graph=False))
            if parsed.path == "/api/progress":
                return self._send_json(200, {"status": "ok", "progress": self.state.progress})
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
            return super().do_GET()
        except Exception as exc:
            self._send_json(500, {"status": "error", "error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            body = self._read_json()
            if parsed.path == "/api/analyze":
                project_path = str(body.get("project_path") or self.state.default_project or "").strip()
                if not project_path:
                    return self._send_json(400, {"status": "error", "error": "project_path is required"})
                try:
                    return self._send_json(200, self.state.analyze(project_path))
                except Exception as exc:
                    with self.state.lock:
                        self.state.last_error = str(exc)
                    return self._send_json(422, {"status": "error", "error": str(exc)})
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
    return server


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="impact-engine-local-api")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--frontend-dir", default=str(Path(__file__).resolve().parents[2] / "frontend"))
    parser.add_argument("--default-project", default=None)
    args = parser.parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    state = LocalApiState(args.default_project, str(repo_root / "support_packs"))
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
