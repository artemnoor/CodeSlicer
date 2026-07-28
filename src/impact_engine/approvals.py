"""One-time human approval records for action-bearing MCP requests.

MCP callers can request an action, but cannot mint an approval token. A local
host/UI must approve the pending record and hand the one-time token back to the
caller. This is intentionally a stronger boundary than ``confirmed: true``.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import time
from typing import Any

from impact_engine.project_storage import ensure_project_storage


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fingerprint(action: str, payload: dict[str, Any]) -> str:
    encoded = json.dumps({"action": action, "payload": payload}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class _ApprovalLock:
    """Tiny cross-process lock for the read-check-consume transition."""
    def __init__(self, path: Path) -> None:
        self.path = path.with_suffix(path.suffix + ".lock")
        self.fd: int | None = None

    def __enter__(self) -> None:
        deadline = time.monotonic() + 5
        while True:
            try:
                self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, str(os.getpid()).encode("ascii"))
                return None
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("approval is busy; retry the request")
                time.sleep(0.02)

    def __exit__(self, *_: Any) -> None:
        if self.fd is not None:
            os.close(self.fd)
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


class ApprovalStore:
    def __init__(self, project_path: str | Path) -> None:
        self.project_path = Path(project_path).expanduser().resolve()
        self.root = ensure_project_storage(self.project_path) / "approvals"
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, approval_id: str) -> Path:
        if not approval_id or any(part in approval_id for part in ("/", "\\", "..")):
            raise ValueError("approval_id is invalid")
        return self.root / f"{approval_id}.json"

    def _read(self, approval_id: str) -> dict[str, Any]:
        path = self._path(approval_id)
        if not path.is_file():
            raise FileNotFoundError(f"approval was not found: {approval_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write(path: Path, record: dict[str, Any]) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)

    def list(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                record.pop("token_hash", None)
                records.append(record)
            except (OSError, ValueError):
                continue
        return records

    def show(self, approval_id: str) -> dict[str, Any]:
        record = self._read(approval_id)
        # A verifier is not useful to the project owner and should not be
        # exposed through the host-facing CLI/API.
        record.pop("token_hash", None)
        return record

    def request(self, action: str, payload: dict[str, Any], *, ttl_seconds: int = 300) -> dict[str, Any]:
        approval_id = secrets.token_urlsafe(18)
        created = _now()
        record = {
            "id": approval_id, "action": action, "fingerprint": _fingerprint(action, payload),
            "payload": payload, "created_at": created.isoformat(),
            "expires_at": (created + timedelta(seconds=max(30, min(ttl_seconds, 900)))).isoformat(),
            "approved": False, "consumed": False,
        }
        self._write(self._path(approval_id), record)
        return {"approval_id": approval_id, "action": action, "payload": payload, "expires_at": record["expires_at"], "status": "pending"}

    def approve(self, approval_id: str) -> dict[str, Any]:
        path = self._path(approval_id)
        with _ApprovalLock(path):
            record = self._read(approval_id)
            if record.get("consumed") or _now() >= datetime.fromisoformat(record["expires_at"]):
                raise ValueError("approval is expired or already consumed")
            token = secrets.token_urlsafe(32)
            record.update({"approved": True, "token_hash": hashlib.sha256(token.encode("utf-8")).hexdigest(), "approved_at": _now().isoformat()})
            self._write(path, record)
        return {"approval_id": approval_id, "approval_token": token, "action": record["action"], "expires_at": record["expires_at"]}

    def consume(self, approval_id: str, token: str, action: str, payload: dict[str, Any]) -> None:
        path = self._path(approval_id)
        with _ApprovalLock(path):
            record = self._read(approval_id)
            if not record.get("approved") or record.get("consumed") or _now() >= datetime.fromisoformat(record["expires_at"]):
                raise ValueError("a current host approval is required")
            token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
            if not secrets.compare_digest(str(record.get("token_hash") or ""), token_hash):
                raise ValueError("approval token is invalid")
            if record.get("action") != action or record.get("fingerprint") != _fingerprint(action, payload):
                raise ValueError("approval does not match the requested action")
            record.update({"consumed": True, "consumed_at": _now().isoformat()})
            self._write(path, record)
