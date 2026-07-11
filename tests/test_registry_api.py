from __future__ import annotations

import json
import threading
from urllib.request import Request, urlopen

from impact_engine.registry_api import create_server
from impact_engine.remote_registry import RegistryClient, RegistryConfig


def request(base: str, method: str, path: str, payload: dict | None = None, headers: dict | None = None):
    body = json.dumps(payload).encode() if payload is not None else None
    req = Request(base + path, data=body, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    with urlopen(req, timeout=5) as response:
        return response.status, json.loads(response.read())


def test_registry_api_public_and_admin_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("IMPACT_REGISTRY_ADMIN_TOKEN", "test-admin")
    client = RegistryClient(RegistryConfig(
        cache_root=str(tmp_path / "cache"),
        local_db_path=str(tmp_path / "registry.sqlite"),
    ))
    server = create_server("127.0.0.1", 0, client)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        status, health = request(base, "GET", "/api/health")
        assert status == 200 and health["status"] == "ok"

        status, created = request(base, "POST", "/api/research-requests", {
            "ecosystem": "python", "library_name": "api-lib", "package_name": "api-lib",
        })
        assert status == 201 and created["status"] == "queued_local_db"

        status, libraries = request(base, "GET", "/api/libraries?ecosystem=python")
        assert status == 200
        assert libraries["items"][0]["status"] == "research_requested"

        status, overview = request(base, "GET", "/api/registry/overview")
        assert status == 200 and overview["libraries_count"] == 1

        try:
            request(base, "POST", "/api/admin/documentation-checks", {"ecosystem": "python", "library": "api-lib", "url": "https://docs.example", "content_hash": "h1"})
        except Exception as exc:
            assert "401" in str(exc)
        status, checked = request(base, "POST", "/api/admin/documentation-checks", {"ecosystem": "python", "library": "api-lib", "url": "https://docs.example", "content_hash": "h1"}, {"X-Registry-Admin-Token": "test-admin"})
        assert status == 200 and checked["changed"] is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
