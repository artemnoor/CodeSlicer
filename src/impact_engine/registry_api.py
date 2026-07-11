"""Small registry HTTP API for the website/server boundary.

The API deliberately uses the standard library so the local engine remains
lightweight. A hosted deployment can put the same resource contract behind a
managed HTTP service without requiring an external database.
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from typing import Any

from impact_engine.remote_registry import RegistryClient, ResearchRequestRecord


def _json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("content-length", "0"))
    if length > 1_000_000:
        raise ValueError("Request body exceeds 1 MB")
    value = json.loads(handler.rfile.read(length) or b"{}")
    if not isinstance(value, dict):
        raise ValueError("Request body must be a JSON object")
    return value


class RegistryAPIHandler(BaseHTTPRequestHandler):
    server_version = "ImpactRegistryAPI/0.4"

    @property
    def client(self) -> RegistryClient:
        return self.server.registry_client  # type: ignore[attr-defined]

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", self._allowed_origin())
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Registry-Admin-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(raw)

    def _allowed_origin(self) -> str:
        allowed = [item.strip() for item in os.getenv("IMPACT_REGISTRY_CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")]
        origin = self.headers.get("Origin", "")
        return origin if origin in allowed else allowed[0]

    def _admin_required(self) -> bool:
        expected = os.getenv("IMPACT_REGISTRY_ADMIN_TOKEN")
        return bool(expected and self.headers.get("X-Registry-Admin-Token") == expected)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send(204, {})

    def do_GET(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            parts = [part for part in parsed.path.split("/") if part]
            query = parse_qs(parsed.query)
            if parts == ["api", "health"]:
                return self._send(200, {"status": "ok"})
            if parts == ["api", "languages"]:
                return self._send(200, {"items": self.client.list_languages()})
            if parts == ["api", "libraries"]:
                return self._send(200, {"items": self.client.list_libraries(_first(query, "ecosystem"), _first(query, "status"), _first(query, "search"))})
            if len(parts) == 4 and parts[:2] == ["api", "libraries"]:
                detail = self.client.library_detail(parts[2], parts[3])
                return self._send(200 if detail else 404, detail or {"error": "library_not_found"})
            if parts == ["api", "support-packs"]:
                detail = self.client.list_libraries(_first(query, "ecosystem"), _first(query, "status"), _first(query, "search"))
                packs = []
                for library in detail:
                    item = self.client.library_detail(library["ecosystem"], library["name"])
                    packs.extend(item.get("support_packs", []) if item else [])
                return self._send(200, {"items": packs})
            if parts == ["api", "research-requests"]:
                return self._send(200, {"items": self.client.list_research_requests(_first(query, "status"))})
            if parts == ["api", "documentation-sources"]:
                return self._send(200, {"items": self.client.list_documentation_sources(_first(query, "ecosystem"), _first(query, "library"))})
            if parts == ["api", "registry", "overview"]:
                return self._send(200, self.client.overview())
            return self._send(404, {"error": "not_found"})
        except Exception as exc:
            self._send(500, {"error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            parts = [part for part in parsed.path.split("/") if part]
            body = _json_body(self)
            if parts == ["api", "research-requests"]:
                for field in ("ecosystem", "library_name"):
                    if not body.get(field):
                        return self._send(400, {"error": f"missing_{field}"})
                result = self.client.create_research_request(ResearchRequestRecord(
                    ecosystem=str(body["ecosystem"]), library_name=str(body["library_name"]),
                    package_name=body.get("package_name"), project_fingerprint=body.get("project_fingerprint"),
                    priority=int(body.get("priority", 100)), input=body.get("input", {}),
                ))
                return self._send(201, result)
            if parts[:2] == ["api", "admin"] and not self._admin_required():
                return self._send(401, {"error": "admin_auth_required"})
            if len(parts) == 5 and parts[:3] == ["api", "admin", "support-packs"] and parts[4] == "approve":
                result = self.client.approve_support_pack(str(body.get("pack_id") or parts[3]), str(body["trust_level"]), str(body["reviewer"]), body.get("note"))
                return self._send(200 if result.get("status") == "ok" else 400, result)
            if parts == ["api", "admin", "documentation-checks"]:
                result = self.client.record_documentation_check(str(body["ecosystem"]), str(body["library"]), str(body["url"]), str(body["content_hash"]), str(body.get("source_type", "docs")))
                return self._send(200, result)
            return self._send(404, {"error": "not_found"})
        except (KeyError, ValueError, TypeError) as exc:
            self._send(400, {"error": str(exc)})
        except Exception as exc:
            self._send(500, {"error": str(exc)})

    def log_message(self, format: str, *args: Any) -> None:
        return


def _first(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    return values[0] if values else None


def create_server(host: str = "127.0.0.1", port: int = 8787, client: RegistryClient | None = None) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), RegistryAPIHandler)
    server.registry_client = client or RegistryClient()  # type: ignore[attr-defined]
    return server


def main() -> None:
    host = os.getenv("IMPACT_REGISTRY_API_HOST", "127.0.0.1")
    port = int(os.getenv("IMPACT_REGISTRY_API_PORT", "8787"))
    server = create_server(host, port)
    print(f"Impact Registry API listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
