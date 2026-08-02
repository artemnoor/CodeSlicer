"""Persistent, local-only state for analysis and incremental runs.

The analysis graph is deliberately kept as JSON.  This module adds the
missing durability contract around it: explicit cache keys, branch/scope
isolation, atomic multi-artifact commits, and an owner lock that works on
Windows and POSIX without an external service.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import signal
import socket
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

try:
    import orjson
except ImportError:  # pragma: no cover - standard library fallback
    orjson = None

from impact_engine import __version__
from impact_engine.scope import iter_project_files


# v3 invalidates graphs produced before evidence-first local semantic
# resolution existed for the non-Python language plugins.
# Framework manifests and their hook provenance participate in the canonical
# graph. v5 records a registry fingerprint, so a warm cache can validate packs
# without rebuilding the whole project's inventory.
CACHE_SCHEMA_VERSION = "impact-engine.cache.v7"
# Bump this whenever semantic interpretation changes while the on-disk graph
# schema remains compatible.  Otherwise a new CodeSlicer binary can present a
# stale graph from an earlier resolver as if it were freshly analysed.
PIPELINE_VERSION = "semantic-evidence.v6"
MARKER_NAME = ".cache.complete"
JOURNAL_NAME = ".cache.journal.json"
LOCK_NAME = ".analysis.lock"
DAEMON_STATE_NAME = "daemon.json"


class CacheBusyError(RuntimeError):
    """Another process currently owns the project analysis state."""


class CacheInvalidError(RuntimeError):
    """The cache bundle is present but cannot be trusted as a complete bundle."""


class AnalysisCancelled(RuntimeError):
    """Raised when a superseded or explicitly cancelled analysis is observed."""


class CancellationToken:
    """Small thread-safe cancellation primitive shared by CLI, watch and plugins."""

    def __init__(self) -> None:
        from threading import Event

        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    def is_set(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        if self.is_set():
            raise AnalysisCancelled("analysis cancelled")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize persisted artifacts deterministically without a Python-string copy.

    Large graphs are written several times during a full or incremental run.
    ``orjson`` is already an optional reader for this cache; when available it
    produces the same compact, sorted JSON representation directly as bytes.
    The standard-library branch deliberately remains the compatibility
    fallback, so artifact schema and cache keys do not depend on the optional
    accelerator.
    """
    if orjson is not None:
        return orjson.dumps(value, option=orjson.OPT_SORT_KEYS)
    return _canonical_json(value).encode("utf-8")


def _canonical_json_bytes(value: Any) -> bytes:
    """Return canonical JSON for an on-disk JSONL-compatible artifact."""
    return canonical_json_bytes(value) + b"\n"


def _sha256(value: str | bytes) -> str:
    data = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(data).hexdigest()


def _write_bytes_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json_atomic(path: str | Path, value: Any) -> Path:
    destination = Path(path).resolve()
    _write_bytes_atomic(destination, _canonical_json_bytes(value))
    return destination


def _read_json(path: Path) -> Any:
    if orjson is not None:
        return orjson.loads(path.read_bytes())
    return json.loads(path.read_text(encoding="utf-8"))


def _run_git(root: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args], cwd=root, check=True, capture_output=True, text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = completed.stdout.strip()
    return value or None


def git_context(root: str | Path, base: str | None = None) -> dict[str, str | None]:
    project = Path(root).resolve()
    # The previous implementation spawned eight git processes for every cache
    # metadata build. HEAD and its symbolic ref are available from one
    # rev-parse invocation; merge-base(HEAD, HEAD) is HEAD, so it needs no
    # second process unless the caller explicitly supplies a base.
    head = None
    branch = "detached"
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD", "--abbrev-ref", "HEAD"],
            cwd=project, check=True, capture_output=True, text=True, timeout=3,
        )
        lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
        if lines:
            head = lines[0]
        if len(lines) > 1 and lines[1] != "HEAD":
            branch = lines[1]
    except (OSError, subprocess.SubprocessError):
        pass
    ref = branch
    selected_base = base or head
    if base:
        selected_base = _run_git(project, "merge-base", "HEAD", base) or base
    return {
        "branch": branch,
        "ref": ref,
        "head": head,
        "base": selected_base,
        "head_fingerprint": _sha256(head or "no-git-head"),
        "base_fingerprint": _sha256(selected_base or "no-git-base"),
    }


def classify_path(relative_path: str) -> str:
    """Classify paths for honest coverage and narrow invalidation."""
    parts = {part.lower() for part in Path(relative_path).parts}
    name = Path(relative_path).name.lower()
    if parts & {"node_modules", "vendor", "third_party", "dist", "build", "target", ".next", "coverage"}:
        return "excluded_dependency_or_build"
    if name.endswith((".min.js", ".min.css", ".map")) or name in {"package-lock.json", "pnpm-lock.yaml", "yarn.lock"}:
        return "generated_or_lock"
    if parts & {"generated", "gen", "migrations"}:
        return "generated_or_migration"
    if name in {"pyproject.toml", "requirements.txt", "package.json", "go.mod", "go.sum", "pom.xml", "build.gradle", "tsconfig.json", "global.json"} or name.endswith((".sln", ".slnx")):
        return "manifest"
    return "source"


def project_snapshot(root: str | Path, scope: str | None = None) -> dict[str, str]:
    project = Path(root).resolve()
    prefix = (scope or "").replace("\\", "/").strip("/")
    if prefix == ".":
        prefix = ""
    scan_root = project / prefix if prefix and (project / prefix).is_dir() else project
    snapshot: dict[str, str] = {}
    for path in iter_project_files(scan_root):
        relative = path.relative_to(project).as_posix()
        if classify_path(relative) == "excluded_dependency_or_build":
            continue
        try:
            snapshot[relative] = _sha256(path.read_bytes())
        except OSError:
            # A file disappearing during a watch cycle is represented by its
            # absence; it must not make the entire bundle appear valid.
            continue
    return dict(sorted(snapshot.items()))


def project_snapshot_stats(root: str | Path, scope: str | None = None) -> dict[str, dict[str, int]]:
    """Return a cheap change detector for warm-cache validation.

    Content hashes remain the correctness authority for writes and misses. A
    warm no-change request only needs to prove that no file's size or mtime
    changed before it can reuse the already hashed snapshot artifact.
    """
    project = Path(root).resolve()
    prefix = (scope or "").replace("\\", "/").strip("/")
    if prefix == ".":
        prefix = ""
    scan_root = project / prefix if prefix and (project / prefix).is_dir() else project
    result: dict[str, dict[str, int]] = {}
    for path in iter_project_files(scan_root):
        relative = path.relative_to(project).as_posix()
        if classify_path(relative) == "excluded_dependency_or_build":
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        result[relative] = {"size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)}
    return dict(sorted(result.items()))


def snapshot_hash(snapshot: Mapping[str, str]) -> str:
    return _sha256(_canonical_json(dict(sorted(snapshot.items()))))


def root_identity(root: str | Path) -> str:
    project = str(Path(root).resolve()).replace("\\", "/").casefold()
    return _sha256(project)


def plugin_registry_fingerprint(project_path: str | Path) -> str:
    """Fingerprint local plugin assets without walking project source files.

    Framework selection cannot change while the source snapshot is unchanged;
    only the registry's manifests or hook/recipe implementations can alter the
    selected packs' output.  This small fixed-size check replaces an expensive
    warm-cache inventory scan across the user's repository.
    """
    try:
        from impact_engine.plugin_architecture.registry import discover_plugin_registry

        registry = discover_plugin_registry(project_path)
    except Exception:
        return "unavailable"
    entries: list[dict[str, str]] = []
    for plugin_id, manifest in sorted(registry.manifests.items()):
        manifest_path = Path(str(getattr(manifest, "path", "") or ""))
        assets = [manifest_path]
        if manifest_path:
            # The registry fingerprint is used by the stat-only warm path,
            # where no selection plan is rebuilt. Include every local Python
            # implementation in a pack so an adapter delegated from hooks.py
            # cannot silently leave an old graph marked fresh.
            try:
                assets.extend(
                    candidate for candidate in manifest_path.parent.rglob("*.py")
                    if "__pycache__" not in candidate.parts
                )
            except OSError:
                assets.extend((manifest_path.parent / "hooks.py", manifest_path.parent / "recipes.py"))
        digests: dict[str, str] = {}
        for asset in assets:
            if not asset:
                continue
            try:
                if asset.is_file():
                    key = asset.relative_to(manifest_path.parent).as_posix() if manifest_path and asset != manifest_path else asset.name
                    digests[key] = _sha256(asset.read_bytes())
            except OSError:
                digests[asset.name] = "missing"
        entries.append({"id": str(plugin_id), "assets": _canonical_json(digests)})
    return _sha256(_canonical_json(entries))


def _plugin_entries(plugin_plan: Any) -> list[dict[str, str]]:
    if plugin_plan is None:
        return []
    result: list[dict[str, str]] = []
    registry = getattr(plugin_plan, "registry", None)
    for plugin_id in getattr(plugin_plan, "selected_ids", lambda: ())():
        manifest = registry.manifests.get(plugin_id) if registry else None
        manifest_path = str(getattr(manifest, "path", "") or "")
        manifest_fingerprint = ""
        if manifest_path:
            try:
                manifest_fingerprint = _sha256(Path(manifest_path).read_bytes())
            except OSError:
                manifest_fingerprint = "missing"
        hook_fingerprint = ""
        entrypoint = str(getattr(manifest, "entrypoint", "") or "")
        if manifest_path and entrypoint:
            module_name = entrypoint.split(":", 1)[0].replace(".", "/")
            candidates = [
                Path(manifest_path).parent / f"{Path(module_name).name}.py",
                Path(manifest_path).parent / module_name / "__init__.py",
            ]
            for candidate in candidates:
                if candidate.exists():
                    try:
                        hook_fingerprint = _sha256(candidate.read_bytes())
                    except OSError:
                        hook_fingerprint = "missing"
                    break
        if manifest_path and not hook_fingerprint:
            for candidate in (Path(manifest_path).parent / "hooks.py", Path(manifest_path).parent / "recipes.py"):
                if candidate.exists():
                    try:
                        hook_fingerprint = _sha256(candidate.read_bytes())
                    except OSError:
                        hook_fingerprint = "missing"
                    break
        # A framework pack can delegate a hook into a sibling adapter module
        # (for example FastAPI route composition).  Hashing just ``hooks.py``
        # let a changed resolver reuse an old graph until a source file also
        # changed.  The pack directory is intentionally small and local, so a
        # deterministic fingerprint of its Python implementation files keeps
        # warm-cache validation correct without scanning project source.
        if manifest_path:
            pack_root = Path(manifest_path).parent
            files: list[dict[str, str]] = []
            try:
                for candidate in sorted(pack_root.rglob("*.py")):
                    if "__pycache__" in candidate.parts:
                        continue
                    files.append({
                        "path": candidate.relative_to(pack_root).as_posix(),
                        "sha256": _sha256(candidate.read_bytes()),
                    })
                if files:
                    hook_fingerprint = _sha256(_canonical_json(files))
            except OSError:
                hook_fingerprint = "missing"
        result.append({
            "id": plugin_id,
            "version": str(getattr(manifest, "version", "")),
            "cache_key": str(getattr(manifest, "cache_key", "")),
            "kind": str(getattr(manifest, "kind", "")),
            "manifest_fingerprint": manifest_fingerprint,
            "hook_fingerprint": hook_fingerprint,
        })
    return sorted(result, key=lambda item: item["id"])


@dataclass(frozen=True)
class CacheMetadata:
    project_root_identity: str
    branch: str
    ref: str
    head_fingerprint: str
    base_fingerprint: str
    source_snapshot_hash: str
    scan_scope: str
    scan_scope_hash: str
    plugin_registry_fingerprint: str = ""
    selected_plugins: tuple[dict[str, str], ...] = ()
    selected_framework_packs: tuple[dict[str, str], ...] = ()
    graph_schema_version: str = "GraphDocument/v1"
    engine_version: str = __version__
    analysis_pipeline_version: str = PIPELINE_VERSION
    runtime_dependency_version: str = f"python-{platform.python_version()}"
    resolution_profile: str = "bounded_exact_imports"
    created_at: float = field(default_factory=time.time)
    cache_status: str = "miss"
    cache_reason: str = "initial_scan"

    @property
    def cache_key(self) -> str:
        return _sha256(_canonical_json(self.to_dict(include_key=False)))

    def to_dict(self, *, include_key: bool = True) -> dict[str, Any]:
        data = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "project_root_identity": self.project_root_identity,
            "branch": self.branch,
            "ref": self.ref,
            "head_fingerprint": self.head_fingerprint,
            "base_fingerprint": self.base_fingerprint,
            "source_snapshot_hash": self.source_snapshot_hash,
            "scan_scope": self.scan_scope,
            "scan_scope_hash": self.scan_scope_hash,
            "plugin_registry_fingerprint": self.plugin_registry_fingerprint,
            "selected_plugins": list(self.selected_plugins),
            "selected_framework_packs": list(self.selected_framework_packs),
            "graph_schema_version": self.graph_schema_version,
            "engine_version": self.engine_version,
            "analysis_pipeline_version": self.analysis_pipeline_version,
            "runtime_dependency_version": self.runtime_dependency_version,
            "resolution_profile": self.resolution_profile,
            "created_at": self.created_at,
            "cache_status": self.cache_status,
            "cache_reason": self.cache_reason,
        }
        if include_key:
            data["cache_key"] = self.cache_key
        return data

    @classmethod
    def from_project(
        cls,
        root: str | Path,
        *,
        scope: str | None = None,
        plugin_plan: Any = None,
        base: str | None = None,
        snapshot: Mapping[str, str] | None = None,
        cache_status: str = "miss",
        cache_reason: str = "initial_scan",
        resolution_profile: str = "bounded_exact_imports",
    ) -> "CacheMetadata":
        project = Path(root).resolve()
        snap = dict(snapshot or project_snapshot(project, scope))
        git = git_context(project, base)
        entries = _plugin_entries(plugin_plan)
        language = tuple(item for item in entries if item["kind"] == "language")
        packs = tuple(item for item in entries if item["kind"] == "framework")
        scope_value = (scope or ".").replace("\\", "/").strip("/") or "."
        try:
            from impact_engine.extractors.tree_sitter.adapter import is_tree_sitter_available
            tree_sitter_status = "native" if is_tree_sitter_available() else "fallback"
        except Exception:
            tree_sitter_status = "unavailable"
        return cls(
            project_root_identity=root_identity(project),
            branch=str(git["branch"]), ref=str(git["ref"]),
            head_fingerprint=str(git["head_fingerprint"]), base_fingerprint=str(git["base_fingerprint"]),
            source_snapshot_hash=snapshot_hash(snap), scan_scope=scope_value,
            scan_scope_hash=_sha256(scope_value), plugin_registry_fingerprint=plugin_registry_fingerprint(project), selected_plugins=language,
            selected_framework_packs=packs, cache_status=cache_status, cache_reason=cache_reason,
            runtime_dependency_version=f"python-{platform.python_version()}|tree-sitter-{tree_sitter_status}",
            resolution_profile=resolution_profile,
        )


@dataclass(frozen=True)
class CacheLoad:
    status: str
    reason: str
    metadata: dict[str, Any] | None = None
    artifacts: dict[str, Any] = field(default_factory=dict)

    @property
    def hit(self) -> bool:
        return self.status == "hit"


class CacheLock:
    """Exclusive owner lock for one project's persistent state."""

    def __init__(self, root: str | Path, *, owner: str = "analysis", lock_name: str = LOCK_NAME) -> None:
        self.cache_root = Path(root).resolve() / ".impact_engine"
        self.path = self.cache_root / lock_name
        self.owner = owner
        self.nonce = uuid.uuid4().hex
        self.acquired = False

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        if os.name == "nt":
            try:
                completed = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}"],
                    capture_output=True, text=True, timeout=3,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                # ``tasklist`` can emit non-UTF output on localized Windows
                # installations.  A decoding fallback may leave stdout as
                # None; that must mean "cannot prove the owner is alive", not
                # a TypeError which leaves the caller with a stale lock.
                return str(pid) in (completed.stdout or "")
            except (OSError, subprocess.SubprocessError):
                return False
        try:
            os.kill(pid, 0)
        except (OSError, ProcessLookupError):
            return False
        return True

    def acquire(self) -> "CacheLock":
        self.cache_root.mkdir(parents=True, exist_ok=True)
        payload = {"pid": os.getpid(), "owner": self.owner, "nonce": self.nonce, "created_at": time.time()}
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            try:
                current = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                current = {}
            pid = int(current.get("pid", 0) or 0)
            if not self._pid_alive(pid):
                try:
                    self.path.unlink()
                except OSError:
                    pass
                return self.acquire()
            raise CacheBusyError(f"analysis state is owned by pid {pid} ({current.get('owner', 'unknown')})") from exc
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        self.acquired = True
        return self

    def release(self) -> None:
        if not self.acquired:
            return
        try:
            current = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            current = {}
        if current.get("nonce") == self.nonce:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
        self.acquired = False

    def __enter__(self) -> "CacheLock":
        return self.acquire()

    def __exit__(self, *_: Any) -> None:
        self.release()


class AtomicCacheStore:
    """Atomic bundle store for graph, raw facts, reverse index and review."""

    def __init__(self, project: str | Path) -> None:
        self.project = Path(project).resolve()
        self.root = self.project / ".impact_engine"
        self.root.mkdir(parents=True, exist_ok=True)

    def write_bundle(self, metadata: CacheMetadata | Mapping[str, Any], artifacts: Mapping[str, Any]) -> None:
        meta = metadata.to_dict() if isinstance(metadata, CacheMetadata) else dict(metadata)
        transaction = self.root / f".cache-txn-{uuid.uuid4().hex}"
        transaction.mkdir(parents=True, exist_ok=False)
        journal = {"transaction": transaction.name, "cache_key": meta.get("cache_key"), "started_at": time.time()}
        write_json_atomic(self.root / JOURNAL_NAME, journal)
        committed = False
        try:
            write_json_atomic(transaction / "metadata.json", meta)
            for name, value in artifacts.items():
                safe_name = Path(name).name
                write_json_atomic(transaction / safe_name, value)
            # Replace artifacts before the marker.  A crash leaves the journal
            # behind, so readers reject even a set of individually valid JSONs.
            for path in sorted(transaction.iterdir()):
                os.replace(path, self.root / path.name)
            write_json_atomic(self.root / MARKER_NAME, {"cache_key": meta.get("cache_key"), "written_at": time.time()})
            committed = True
        finally:
            if committed:
                try:
                    self.root.joinpath(JOURNAL_NAME).unlink()
                except FileNotFoundError:
                    pass
            try:
                transaction.rmdir()
            except OSError:
                # If a process was interrupted, the next load will reject the
                # journal/marker combination and the stale transaction is safe
                # to clean on the next explicit maintenance pass.
                pass

    def update_metadata(self, metadata: CacheMetadata | Mapping[str, Any], artifacts: Mapping[str, Any]) -> None:
        """Atomically update metadata/small artifacts without rewriting graph JSON."""
        meta = metadata.to_dict() if isinstance(metadata, CacheMetadata) else dict(metadata)
        transaction = self.root / f".cache-meta-txn-{uuid.uuid4().hex}"
        transaction.mkdir(parents=True, exist_ok=False)
        write_json_atomic(self.root / JOURNAL_NAME, {"transaction": transaction.name, "cache_key": meta.get("cache_key"), "started_at": time.time()})
        committed = False
        try:
            write_json_atomic(transaction / "metadata.json", meta)
            for name, value in artifacts.items():
                write_json_atomic(transaction / Path(name).name, value)
            for path in sorted(transaction.iterdir()):
                os.replace(path, self.root / path.name)
            write_json_atomic(self.root / MARKER_NAME, {"cache_key": meta.get("cache_key"), "written_at": time.time()})
            committed = True
        finally:
            if committed:
                try:
                    self.root.joinpath(JOURNAL_NAME).unlink()
                except FileNotFoundError:
                    pass
            try:
                transaction.rmdir()
            except OSError:
                pass

    def load(
        self,
        expected: CacheMetadata | Mapping[str, Any] | None = None,
        artifact_names: tuple[str, ...] | None = None,
    ) -> CacheLoad:
        if (self.root / JOURNAL_NAME).exists():
            return CacheLoad("invalidated", "interrupted_write")
        marker = self.root / MARKER_NAME
        metadata_path = self.root / "metadata.json"
        if not marker.exists() or not metadata_path.exists():
            return CacheLoad("miss", "cache_not_initialized")
        try:
            metadata = _read_json(metadata_path)
            marker_data = _read_json(marker)
        except (OSError, ValueError, TypeError):
            return CacheLoad("invalidated", "metadata_or_marker_invalid")
        if marker_data.get("cache_key") != metadata.get("cache_key"):
            return CacheLoad("invalidated", "marker_mismatch", metadata)
        if metadata.get("schema_version") != CACHE_SCHEMA_VERSION:
            return CacheLoad("invalidated", "schema_version_mismatch", metadata)
        if expected is not None:
            expected_data = expected.to_dict() if isinstance(expected, CacheMetadata) else dict(expected)
            for key in (
                "project_root_identity", "branch", "ref", "head_fingerprint", "base_fingerprint",
                "source_snapshot_hash", "scan_scope", "scan_scope_hash", "selected_plugins",
                "selected_framework_packs", "plugin_registry_fingerprint", "graph_schema_version", "engine_version",
                "analysis_pipeline_version", "runtime_dependency_version",
                "resolution_profile",
            ):
                if metadata.get(key) != expected_data.get(key):
                    reason = "branch_mismatch" if key in {"branch", "ref", "head_fingerprint", "base_fingerprint"} else f"{key}_mismatch"
                    return CacheLoad("miss", reason, metadata)
        artifacts: dict[str, Any] = {}
        names = artifact_names or ("graph.json", "facts.json", "reverse_index.json", "review.json", "snapshot.json", "snapshot_stats.json", "inventory.json", "raw_file_fragments.json")
        for name in names:
            path = self.root / name
            if path.exists():
                try:
                    artifacts[name] = _read_json(path)
                except (OSError, ValueError, TypeError):
                    return CacheLoad("invalidated", f"artifact_invalid:{name}", metadata)
        return CacheLoad("hit", "cache_hit", metadata, artifacts)


def daemon_state_path(project: str | Path) -> Path:
    return Path(project).resolve() / ".impact_engine" / DAEMON_STATE_NAME


def daemon_status(project: str | Path) -> dict[str, Any]:
    path = daemon_state_path(project)
    if not path.exists():
        return {"status": "stopped", "project": str(Path(project).resolve())}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "invalid", "project": str(Path(project).resolve())}
    pid = int(state.get("pid", 0) or 0)
    alive = CacheLock._pid_alive(pid)
    state["status"] = "running" if alive else "stale"
    state["project"] = str(Path(project).resolve())
    return state


def _write_daemon_state(project: Path, state: Mapping[str, Any]) -> None:
    write_json_atomic(daemon_state_path(project), dict(state))


def start_daemon(project: str | Path) -> dict[str, Any]:
    root = Path(project).resolve()
    root.mkdir(parents=True, exist_ok=True)
    current = daemon_status(root)
    if current.get("status") == "running":
        return {**current, "status": "already_running"}
    if current.get("status") in {"stale", "invalid"}:
        try:
            daemon_state_path(root).unlink()
        except FileNotFoundError:
            pass
    command = [os.fspath(Path(os.sys.executable)), "-m", "impact_engine.daemon", "--project", str(root)]
    kwargs: dict[str, Any] = {"cwd": root, "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    package_src = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(filter(None, [str(package_src), environment.get("PYTHONPATH", "")]))
    kwargs["env"] = environment
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen(command, **kwargs)
    state = {"status": "starting", "pid": process.pid, "project": str(root), "started_at": time.time(), "owner": "impact-engine"}
    _write_daemon_state(root, state)
    deadline = time.time() + 2.0
    while time.time() < deadline:
        current = daemon_status(root)
        if current.get("status") == "running" and current.get("port"):
            return current
        time.sleep(0.05)
    return daemon_status(root) if daemon_status(root).get("status") == "running" else state


def daemon_request(project: str | Path, method: str, params: Mapping[str, Any] | None = None, *, timeout: float = 120.0) -> dict[str, Any]:
    """Send one authenticated JSON-line request to the local daemon."""
    state = daemon_status(project)
    if state.get("status") != "running" or not state.get("port") or not state.get("token"):
        raise ConnectionError("local impact-engine daemon is not running")
    request = {
        "id": uuid.uuid4().hex,
        "method": method,
        "project": str(Path(project).resolve()),
        "params": dict(params or {}),
        "token": state["token"],
    }
    with socket.create_connection(("127.0.0.1", int(state["port"])), timeout=timeout) as connection:
        connection.settimeout(timeout)
        connection.sendall((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
        chunks: list[bytes] = []
        while True:
            chunk = connection.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
            if b"\n" in chunk:
                break
    payload = b"".join(chunks).splitlines()[0] if chunks else b"{}"
    response = json.loads(payload.decode("utf-8"))
    if response.get("status") == "error":
        raise RuntimeError(response.get("error", "daemon request failed"))
    return response


def stop_daemon(project: str | Path) -> dict[str, Any]:
    root = Path(project).resolve()
    state = daemon_status(root)
    pid = int(state.get("pid", 0) or 0)
    if pid and CacheLock._pid_alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    try:
        daemon_state_path(root).unlink()
    except FileNotFoundError:
        pass
    try:
        (root / ".impact_engine" / ".daemon.lock").unlink()
    except FileNotFoundError:
        pass
    return {"status": "stopped", "project": str(root), "pid": pid or None}


def cache_summary(load: CacheLoad, *, scope: str | None = None) -> dict[str, Any]:
    metadata = load.metadata or {}
    return {
        "status": load.status,
        "reason": load.reason,
        "branch": metadata.get("branch"),
        "snapshot": metadata.get("source_snapshot_hash"),
        "scope": scope or metadata.get("scan_scope", "."),
        "plugins": metadata.get("selected_plugins", []),
        "files_reused": 0,
        "files_reanalyzed": 0,
        "facts_reused": 0,
        "facts_rebuilt": 0,
    }
