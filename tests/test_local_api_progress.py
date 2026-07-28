from __future__ import annotations

import json
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from impact_engine.local_api import LocalApiState, create_server


def _post(server, path, payload):
    request = Request(
        f"http://127.0.0.1:{server.server_port}{path}",
        data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        return error.code, json.loads(error.read())


def test_local_api_exposes_progress_and_cancel(monkeypatch, tmp_path):
    def fake_analyze(path, **kwargs):
        callback = kwargs["progress_callback"]
        token = kwargs["cancellation"]
        for index in range(1, 20):
            token.check()
            callback({
                "stage": "extraction", "processed": index, "total": 20,
                "overall_percent": index * 3.0, "eta_seconds": 2.0,
                "cancellable": True,
            })
            time.sleep(0.01)
        return {"status": "ok", "project_path": path, "graph_path": None, "progress": {"status": "completed"}}

    monkeypatch.setattr("impact_engine.local_api.analyze_project_core", fake_analyze)
    state = LocalApiState(str(tmp_path), "support_packs")
    server = create_server("127.0.0.1", 0, str(tmp_path), state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        worker = threading.Thread(target=lambda: _post(server, "/api/analyze", {"project_path": str(tmp_path)}), daemon=True)
        worker.start()
        for _ in range(30):
            if state.progress.get("status") == "running":
                break
            time.sleep(0.01)
        assert state.progress["current"]["eta_seconds"] == 2.0
        status, body = _post(server, "/api/analyze/cancel", {})
        assert status == 200
        assert body["status"] == "cancelling"
        worker.join(timeout=5)
        assert state.progress["status"] == "cancelled"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
