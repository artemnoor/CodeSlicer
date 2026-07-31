"""Local authenticated daemon for serialized analysis tasks.

The daemon deliberately uses loopback TCP rather than a platform-specific
named-pipe API: the state file publishes an ephemeral port and a random token,
so the same client contract works on Windows and POSIX without a broker.
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import secrets
import signal
import socket
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from impact_engine.persistence import CacheLock, daemon_state_path, write_json_atomic


@dataclass
class _Task:
    task_id: str
    method: str
    params: dict[str, Any]
    cancellation: Any
    done: threading.Event = field(default_factory=threading.Event)
    result: dict[str, Any] | None = None


class _Daemon:
    def __init__(self, root: Path, state_path: Path, token: str) -> None:
        self.root = root
        self.state_path = state_path
        self.token = token
        self.tasks: queue.Queue[_Task] = queue.Queue()
        self.active: dict[str, _Task] = {}
        self.stopping = threading.Event()
        self.server: socket.socket | None = None

    def dispatch(self, task: _Task) -> dict[str, Any]:
        from impact_engine.analysis.pipeline import analyze_project_core
        from impact_engine.incremental import incremental_update, load_snapshot, save_snapshot

        params = task.params
        method = task.method
        scope = params.get("scope")
        out_path = params.get("out_path")
        if method == "analyze":
            return analyze_project_core(
                str(self.root), out_path=out_path, changed_files=params.get("changed_files"),
                raw_graph_cache_path=params.get("raw_graph_cache_path"), scope=scope,
                create_research_requests=bool(params.get("create_research_requests", True)),
                enable_remote_registry=bool(params.get("enable_remote_registry", False)),
                force_full_resolution=bool(params.get("force_full_resolution", False)),
                cancellation=task.cancellation,
            )
        if method == "analyze-incremental":
            snapshot_path = Path(params.get("snapshot_path") or self.root / ".impact_engine" / "project.snapshot.json")
            previous = load_snapshot(snapshot_path) if snapshot_path.exists() else None
            raw_cache = params.get("raw_graph_cache_path") or str(self.root / ".impact_engine" / "raw_graph.json")
            result = incremental_update(
                str(self.root),
                lambda changed: analyze_project_core(
                    str(self.root), out_path=None, changed_files=changed, raw_graph_cache_path=raw_cache,
                    scope=scope, cancellation=task.cancellation,
                ),
                previous_snapshot=previous, out_path=out_path,
                previous_graph_path=out_path, forced_changed=params.get("changed_files"),
                scope=scope, cancellation=task.cancellation,
            )
            save_snapshot(result["incremental"]["snapshot"], snapshot_path)
            return result
        if method == "review":
            from impact_engine.review import build_review_report
            return build_review_report(
                str(self.root), graph_path=params.get("graph_path"), diff_text=params.get("diff_text"),
                diff_source=params.get("diff_source"), base=params.get("base"),
                refresh=params.get("refresh", "auto"), max_results=int(params.get("max_results", 10)),
                run_tests=params.get("run_tests", "suggested"), deep=bool(params.get("deep", False)),
                entity=params.get("entity"), scope=scope,
            )
        if method == "impact":
            from impact_engine.impact import impact_query
            from impact_engine.models import GraphDocument
            graph_path = Path(params.get("graph_path") or self.root / ".impact_engine" / "graph.json")
            graph = GraphDocument.from_json(graph_path.read_text(encoding="utf-8"))
            return impact_query(graph, target=params.get("target", ""), symbol=params.get("symbol"),
                                file_path=params.get("file_path"), direction=params.get("direction", "both"),
                                max_depth=params.get("max_depth"), min_confidence=float(params.get("min_confidence", 0.0)))
        if method == "watch":
            from impact_engine.watch import watch_project
            results = list(watch_project(
                str(self.root), lambda: analyze_project_core(str(self.root), out_path=None, scope=scope, cancellation=task.cancellation),
                interval_seconds=float(params.get("interval_seconds", 1.0)),
                iterations=int(params.get("iterations", 1)), out_path=out_path, scope=scope,
                cancellation=task.cancellation,
            ))
            return {"status": "ok", "iterations": results, **(results[-1] if results else {})}
        raise ValueError(f"unsupported daemon method: {method}")

    def worker(self) -> None:
        while not self.stopping.is_set():
            try:
                task = self.tasks.get(timeout=0.1)
            except queue.Empty:
                continue
            self.active[task.task_id] = task
            try:
                with CacheLock(self.root, owner=f"daemon-task:{task.task_id}"):
                    task.result = {"status": "ok", "task_id": task.task_id, "result": self.dispatch(task)}
            except Exception as exc:
                task.result = {"status": "error", "task_id": task.task_id, "error": str(exc), "incomplete": True}
            finally:
                self.active.pop(task.task_id, None)
                task.done.set()
                self.tasks.task_done()

    def client(self, connection: socket.socket) -> None:
        try:
            connection.settimeout(120.0)
            request = json.loads(connection.makefile("rb").readline().decode("utf-8"))
            if request.get("token") != self.token or Path(str(request.get("project", ""))).resolve() != self.root:
                response = {"status": "error", "error": "daemon authentication failed"}
            elif request.get("method") == "status":
                response = {"status": "ok", "daemon": "running", "pid": os.getpid(), "queue_depth": self.tasks.qsize(), "active_tasks": sorted(self.active)}
            elif request.get("method") == "cancel":
                task = self.active.get(str(request.get("task_id")))
                if task:
                    task.cancellation.cancel()
                response = {"status": "ok", "cancelled": bool(task)}
            else:
                task = _Task(secrets.token_hex(8), str(request.get("method")), dict(request.get("params") or {}), _Cancellation())
                self.tasks.put(task)
                task.done.wait(timeout=float((request.get("params") or {}).get("timeout", 120.0)))
                response = task.result or {"status": "error", "task_id": task.task_id, "error": "daemon task timeout", "incomplete": True}
                if response.get("status") == "ok":
                    response = {"status": "ok", "task_id": task.task_id, **response.get("result", {})}
        except Exception as exc:
            response = {"status": "error", "error": str(exc)}
        try:
            connection.sendall((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
        finally:
            connection.close()


class _Cancellation:
    def __init__(self) -> None:
        self._event = threading.Event()
    def is_set(self) -> bool:
        return self._event.is_set()
    def cancel(self) -> None:
        self._event.set()
    def check(self) -> None:
        if self._event.is_set():
            from impact_engine.persistence import AnalysisCancelled
            raise AnalysisCancelled("daemon task cancelled")


def serve(project: str) -> int:
    root = Path(project).resolve()
    state_path = daemon_state_path(root)
    daemon = _Daemon(root, state_path, secrets.token_urlsafe(32))
    def stop(*_args: Any) -> None:
        daemon.stopping.set()
        if daemon.server:
            try:
                daemon.server.close()
            except OSError:
                pass
    signal.signal(signal.SIGTERM, stop)
    if hasattr(signal, "SIGINT"):
        signal.signal(signal.SIGINT, stop)
    try:
        with CacheLock(root, owner="daemon", lock_name=".daemon.lock"):
            daemon.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            daemon.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            daemon.server.bind(("127.0.0.1", 0))
            daemon.server.listen(16)
            port = int(daemon.server.getsockname()[1])
            write_json_atomic(state_path, {"status": "running", "pid": os.getpid(), "project": str(root), "started_at": time.time(), "owner": "impact-engine", "host": "127.0.0.1", "port": port, "token": daemon.token})
            threading.Thread(target=daemon.worker, name="impact-engine-worker", daemon=True).start()
            daemon.server.settimeout(0.25)
            while not daemon.stopping.is_set():
                try:
                    connection, _ = daemon.server.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                threading.Thread(target=daemon.client, args=(connection,), daemon=True).start()
    except Exception as exc:
        write_json_atomic(state_path, {"status": "error", "project": str(root), "error": str(exc)})
        return 2
    try:
        state_path.unlink()
    except FileNotFoundError:
        pass
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="impact-engine-daemon")
    parser.add_argument("--project", required=True)
    args = parser.parse_args(argv)
    return serve(args.project)


if __name__ == "__main__":
    raise SystemExit(main())
