"""Crash-safe ownership for workspace analysis artifacts.

An analysis writes several artifacts that must describe the same source snapshot.
The lock is deliberately small, local to ``.impact_engine``, and self-healing:
an interrupted process cannot permanently block a workspace or corrupt the
next incremental run.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import time
from typing import Iterator

from impact_engine.security import validate_project_path


LOCK_FILE_NAME = ".analysis.lock"
DEFAULT_STALE_AFTER_SECONDS = 15 * 60


class AnalysisLockedError(RuntimeError):
    """Raised when another live process owns analysis for a workspace."""

    def __init__(self, lock_path: Path, owner: dict[str, object]):
        self.lock_path = lock_path
        self.owner = owner
        label = owner.get("owner", "unknown")
        pid = owner.get("pid", "unknown")
        super().__init__(f"Analysis is already running ({label}, pid {pid}): {lock_path}")


@dataclass(frozen=True)
class AnalysisLock:
    path: Path
    owner: dict[str, object]


def analysis_lock_path(project_path: str | Path) -> Path:
    root = validate_project_path(project_path)
    return root / ".impact_engine" / LOCK_FILE_NAME


def _read_lock(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, UnicodeDecodeError):
        return {}


def _pid_is_alive(pid: object) -> bool | None:
    """Return ``None`` when the PID cannot be verified on this host."""
    if not isinstance(pid, int) or pid <= 0:
        return None
    if os.name == "nt":
        # ``os.kill(pid, 0)`` is a liveness probe on POSIX, but Windows maps
        # it to process termination semantics.  Never use it there: locking
        # must not be capable of killing the editor or its analysis worker.
        import ctypes

        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            error = ctypes.get_last_error()
            # ERROR_ACCESS_DENIED still proves that a process with this PID
            # exists, while ERROR_INVALID_PARAMETER indicates it is gone.
            if error == 5:
                return True
            if error == 87:
                return False
            return None
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return None
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        # Signal 0 is a non-mutating liveness probe on POSIX.
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None
    return True


def _is_stale(path: Path, owner: dict[str, object], stale_after_seconds: float) -> bool:
    try:
        age = max(0.0, time.time() - path.stat().st_mtime)
    except OSError:
        return True
    hostname = owner.get("hostname")
    if not hostname or hostname == socket.gethostname():
        # A live process on this machine is authoritative.  In particular, a
        # large project may legitimately take longer than the lease period;
        # time alone must never let a second writer steal its artifacts.
        alive = _pid_is_alive(owner.get("pid"))
        if alive is True:
            return False
        if alive is False:
            return True
    # A foreign or unverifiable owner is recoverable only after its lease has
    # expired.  This avoids deleting a lock merely because a networked clock
    # or PID namespace cannot be inspected locally.
    return age >= stale_after_seconds


def _owner_payload(owner: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "owner": owner,
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def acquire_analysis_lock(
    project_path: str | Path,
    *,
    owner: str,
    stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS,
) -> AnalysisLock:
    """Acquire an exclusive workspace lock, reclaiming only proven-stale locks."""
    path = analysis_lock_path(project_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _owner_payload(owner)
    serialized = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))

    # A small bounded retry handles another process removing a stale lock between
    # our check and exclusive create without turning this into an unbounded wait.
    for _ in range(3):
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        except FileExistsError:
            existing = _read_lock(path)
            if not _is_stale(path, existing, stale_after_seconds):
                raise AnalysisLockedError(path, existing)
            try:
                path.unlink()
            except FileNotFoundError:
                continue
            except OSError:
                raise AnalysisLockedError(path, existing)
            continue
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            return AnalysisLock(path=path, owner=payload)
        except BaseException:
            try:
                path.unlink()
            except OSError:
                pass
            raise
    raise AnalysisLockedError(path, _read_lock(path))


def release_analysis_lock(lock: AnalysisLock) -> None:
    """Release only the lock owned by this process; never delete a replacement."""
    current = _read_lock(lock.path)
    if current.get("pid") != lock.owner.get("pid") or current.get("created_at") != lock.owner.get("created_at"):
        return
    try:
        lock.path.unlink()
    except FileNotFoundError:
        return


@contextmanager
def analysis_lock(project_path: str | Path, *, owner: str) -> Iterator[AnalysisLock]:
    lock = acquire_analysis_lock(project_path, owner=owner)
    try:
        yield lock
    finally:
        release_analysis_lock(lock)
