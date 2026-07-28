"""Killable local process boundary for plugin hooks.

This is a defensive Python API boundary, not an OS/kernel sandbox. Guards are
installed before a plugin module is imported, so import-time side effects are
subject to the same policy as the hook body.
"""
from __future__ import annotations

import builtins
import ctypes
import importlib.util
import io
import multiprocessing
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from impact_engine.models import GraphDocument

from .contracts import PluginContext, PluginDiagnostic, PluginResult


class PluginSandboxViolation(PermissionError):
    """A hook attempted an operation outside the plugin contract."""

    def __init__(self, message: str, *, code: str = "sandbox_violation") -> None:
        super().__init__(message)
        self.code = code


def _resolve_path(value: Any) -> Path:
    if isinstance(value, int):
        return Path(f"<fd:{value}>")
    return Path(value).expanduser().resolve()


def install_local_only_guards(project_path: Path, *, read_roots: tuple[Path, ...] = ()) -> callable:
    """Install guards before loading untrusted plugin code.

    Reads are allowed only from the project and explicitly supplied runtime
    roots. Writes and filesystem mutations are allowed only below the project
    ``.impact_engine`` cache. Network, process launch, ctypes loaders, delete,
    rename, recursive-delete, and common metadata mutation APIs are denied or
    checked.
    """

    project_root = project_path.resolve()
    cache_root = (project_root / ".impact_engine").resolve()
    allowed_roots = {project_root}
    allowed_roots.update(root.resolve() for root in read_roots if root)
    originals: list[tuple[Any, str, Any]] = []
    originals_by_name: dict[tuple[Any, str], Any] = {}
    original_open = builtins.open
    original_os_open = os.open
    previous_dont_write_bytecode = sys.dont_write_bytecode

    def replace(owner: Any, name: str, value: Any) -> None:
        original = getattr(owner, name)
        originals.append((owner, name, original))
        originals_by_name[(owner, name)] = original
        setattr(owner, name, value)

    def allowed_read(path: Path) -> bool:
        return any(path == root or root in path.parents for root in allowed_roots)

    def allowed_write(path: Path) -> bool:
        return path == cache_root or cache_root in path.parents

    def require_read(path: Any) -> Path:
        resolved = _resolve_path(path)
        if not allowed_read(resolved):
            raise PluginSandboxViolation(
                "plugin read is restricted to the project/runtime roots",
                code="read_outside_project",
            )
        return resolved

    def require_write(path: Any) -> Path:
        resolved = _resolve_path(path)
        if not allowed_write(resolved):
            raise PluginSandboxViolation(
                f"plugin mutation is restricted to {cache_root}",
                code="write_outside_cache",
            )
        return resolved

    def guarded_open(file, mode="r", *args, **kwargs):
        writing = any(flag in str(mode) for flag in ("w", "a", "x", "+"))
        if writing:
            require_write(file)
        else:
            require_read(file)
        return original_open(file, mode, *args, **kwargs)

    def guarded_os_open(file, flags, mode=0o777, *, dir_fd=None):
        write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
        if flags & write_flags:
            require_write(file)
        else:
            require_read(file)
        return original_os_open(file, flags, mode, dir_fd=dir_fd)

    def blocked_network(*args, **kwargs):
        raise PluginSandboxViolation("network access is disabled for plugins", code="network_denied")

    def blocked_process(*args, **kwargs):
        raise PluginSandboxViolation("subprocess execution is disabled for plugins", code="subprocess_denied")

    def guarded_unlink(path, *args, **kwargs):
        require_write(path)
        return originals_by_name[(os, "unlink")](path, *args, **kwargs)

    def guarded_remove(path, *args, **kwargs):
        require_write(path)
        return originals_by_name[(os, "remove")](path, *args, **kwargs)

    def guarded_rename(src, dst, *args, **kwargs):
        require_write(src)
        require_write(dst)
        return originals_by_name[(os, "rename")](src, dst, *args, **kwargs)

    def guarded_replace(src, dst, *args, **kwargs):
        require_write(src)
        require_write(dst)
        return originals_by_name[(os, "replace")](src, dst, *args, **kwargs)

    def guarded_rmdir(path, *args, **kwargs):
        require_write(path)
        return originals_by_name[(os, "rmdir")](path, *args, **kwargs)

    def guarded_mkdir(path, *args, **kwargs):
        require_write(path)
        return originals_by_name[(os, "mkdir")](path, *args, **kwargs)

    def guarded_makedirs(path, *args, **kwargs):
        require_write(path)
        return originals_by_name[(os, "makedirs")](path, *args, **kwargs)

    def guarded_renames(src, dst, *args, **kwargs):
        require_write(src)
        require_write(dst)
        return originals_by_name[(os, "renames")](src, dst, *args, **kwargs)

    def metadata_guard(name: str):
        def guarded(path, *args, **kwargs):
            require_write(path)
            return originals_by_name[(os, name)](path, *args, **kwargs)
        return guarded

    def guarded_rmtree(path, *args, **kwargs):
        require_write(path)
        return originals_by_name[(shutil, "rmtree")](path, *args, **kwargs)

    def guarded_copy(name: str):
        def guarded(src, dst, *args, **kwargs):
            require_read(src)
            require_write(dst)
            return originals_by_name[(shutil, name)](src, dst, *args, **kwargs)
        return guarded

    def guarded_move(src, dst, *args, **kwargs):
        require_write(src)
        require_write(dst)
        return originals_by_name[(shutil, "move")](src, dst, *args, **kwargs)

    replace(builtins, "open", guarded_open)
    replace(io, "open", guarded_open)
    replace(os, "open", guarded_os_open)
    for name in ("socket", "create_connection", "create_server", "getaddrinfo"):
        if hasattr(socket, name):
            replace(socket, name, blocked_network)
    for name in ("Popen", "run", "call", "check_call", "check_output"):
        replace(subprocess, name, blocked_process)
    for name in ("system", "popen"):
        replace(os, name, blocked_process)
    for name, wrapper in (
        ("unlink", guarded_unlink), ("remove", guarded_remove),
        ("rename", guarded_rename), ("replace", guarded_replace),
        ("rmdir", guarded_rmdir), ("mkdir", guarded_mkdir),
        ("makedirs", guarded_makedirs), ("renames", guarded_renames),
    ):
        if hasattr(os, name):
            replace(os, name, wrapper)
    for name in ("chmod", "chown", "utime", "truncate"):
        if hasattr(os, name):
            replace(os, name, metadata_guard(name))
    for name, wrapper in (
        ("rmtree", guarded_rmtree), ("copy", guarded_copy("copy")),
        ("copy2", guarded_copy("copy2")), ("copyfile", guarded_copy("copyfile")),
        ("copytree", guarded_copy("copytree")), ("move", guarded_move),
    ):
        if hasattr(shutil, name):
            replace(shutil, name, wrapper)
    for name in ("CDLL", "WinDLL", "PyDLL"):
        if hasattr(ctypes, name):
            replace(ctypes, name, blocked_process)

    sys.dont_write_bytecode = True

    def restore() -> None:
        for owner, name, original in reversed(originals):
            setattr(owner, name, original)
        sys.dont_write_bytecode = previous_dont_write_bytecode

    return restore


def _load_hook(module_name: str, module_file: str | None, qualname: str):
    if module_file:
        spec = importlib.util.spec_from_file_location(module_name, module_file)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load plugin module {module_file}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    else:
        module = __import__(module_name, fromlist=[qualname.split(".")[0]])
    target = module
    for part in qualname.split("."):
        if part == "<locals>":
            raise TypeError("plugin hooks must be module-level callables")
        target = getattr(target, part)
    return target


def _runtime_read_roots(module_file: Path | None) -> tuple[Path, ...]:
    roots: set[Path] = {Path(__file__).resolve().parents[3]}
    if module_file:
        roots.add(module_file.parent)
    for item in sys.path:
        if item:
            candidate = Path(item)
            if candidate.is_absolute() and candidate.exists():
                roots.add(candidate.resolve())
    return tuple(roots)


def _plugin_worker(payload: dict[str, Any], connection) -> None:
    """Spawn target; guards are installed before importing the hook module."""

    restore = lambda: None
    response: dict[str, Any]
    try:
        project_path = Path(payload["project_path"])
        module_file = Path(payload["module_file"]).resolve() if payload.get("module_file") else None
        restore = install_local_only_guards(project_path, read_roots=_runtime_read_roots(module_file))
        os.environ["IMPACT_ENGINE_PLUGIN_IMPORT_PROBE"] = payload["qualname"].split(".")[-1]
        hook = _load_hook(payload["module_name"], payload.get("module_file"), payload["qualname"])
        context = PluginContext(
            project_path,
            payload.get("inventory", {}),
            tuple(payload.get("selected_plugins", ())),
            timeout_seconds=float(payload.get("timeout_seconds", 30.0)),
        )
        graph = GraphDocument.from_dict(payload["graph"])
        result = hook(context, graph)
        if not isinstance(result, PluginResult):
            raise TypeError("plugin hook must return PluginResult")
        response = {
            "ok": True,
            "result": {
                "graph": (result.graph or graph).to_dict(),
                "facts": dict(result.facts),
                "diagnostics": [item.to_dict() for item in result.diagnostics],
                "provenance": dict(result.provenance),
            },
        }
    except BaseException as exc:
        response = {
            "ok": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "code": getattr(exc, "code", "plugin_execution_error"),
        }
    finally:
        restore()
        connection.send(response)
        connection.close()


def execute_in_process(
    hook,
    context: PluginContext,
    graph: GraphDocument,
    *,
    timeout_seconds: float,
) -> PluginResult:
    """Execute a module-level hook in a killable local process."""

    module = sys.modules.get(getattr(hook, "__module__", ""))
    module_file = getattr(module, "__file__", None)
    module_name = getattr(hook, "__module__", "")
    qualname = getattr(hook, "__qualname__", "")
    if not module_name or not qualname or "<locals>" in qualname:
        raise TypeError("plugin hooks must be module-level callables")

    multiprocessing_context = multiprocessing.get_context("spawn")
    parent, child = multiprocessing_context.Pipe(duplex=False)
    payload = {
        "module_name": module_name,
        "module_file": module_file,
        "qualname": qualname,
        "project_path": str(context.project_path),
        "inventory": dict(context.inventory),
        "selected_plugins": list(context.selected_plugins),
        "timeout_seconds": timeout_seconds,
        "graph": graph.to_dict(),
    }
    process = multiprocessing_context.Process(target=_plugin_worker, args=(payload, child))
    started = time.perf_counter()
    process.start()
    child.close()
    try:
        while True:
            if parent.poll(0.05):
                message = parent.recv()
                if not message.get("ok"):
                    code = message.get("code", "")
                    if code.endswith("denied") or code in {"write_outside_cache", "read_outside_project"}:
                        raise PluginSandboxViolation(message.get("error", "plugin sandbox violation"), code=code or "sandbox_violation")
                    raise RuntimeError(message.get("error", "plugin hook failed"))
                data = message["result"]
                return PluginResult(
                    graph=GraphDocument.from_dict(data["graph"]),
                    facts=data.get("facts", {}),
                    diagnostics=[PluginDiagnostic(**item) for item in data.get("diagnostics", [])],
                    provenance=data.get("provenance", {}),
                )
            if context.cancellation is not None and context.cancellation.is_set():
                raise TimeoutError("plugin execution cancelled")
            if time.perf_counter() - started >= timeout_seconds:
                raise TimeoutError(f"plugin hook exceeded {timeout_seconds:g}s timeout")
    finally:
        if process.is_alive():
            process.terminate()
        process.join(timeout=0.5)
        parent.close()
