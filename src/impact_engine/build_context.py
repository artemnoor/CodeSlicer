"""Read-only build-context inspection for semantic adapters.

The structural graph deliberately excludes build output directories.  This
module is the narrow exception: it reads only build metadata needed to explain
the quality of C/C++ semantic evidence.  It never configures, builds, copies,
or links anything.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MAX_COMPILATION_DATABASE_BYTES = 16 * 1024 * 1024
_BUILD_MARKERS = {
    "cmake": ("CMakeLists.txt", "CMakePresets.json"),
    "meson": ("meson.build",),
    "bazel": ("BUILD", "BUILD.bazel", "WORKSPACE", "WORKSPACE.bazel"),
    "make": ("Makefile",),
    "ninja": ("build.ninja",),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_compile_commands(project_path: str | Path, override: str | Path | None = None) -> Path | None:
    """Find a local compilation database without treating it as source input."""
    project = Path(project_path).expanduser().resolve()
    if override is not None:
        candidate = Path(override).expanduser()
        if not candidate.is_absolute():
            raise ValueError("compile_commands path must be absolute")
        candidate = candidate.resolve()
        if candidate.name != "compile_commands.json" or not candidate.is_file():
            raise FileNotFoundError(f"compile_commands.json does not exist: {candidate}")
        return candidate
    candidates = [project / "compile_commands.json", project / "build" / "compile_commands.json", project / "out" / "compile_commands.json"]
    candidates.extend(sorted(project.glob("cmake-build-*/compile_commands.json")))
    return next((candidate.resolve() for candidate in candidates if candidate.is_file()), None)


def _load_database(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    if path.stat().st_size > MAX_COMPILATION_DATABASE_BYTES:
        return [], [f"compile_commands.json exceeds {MAX_COMPILATION_DATABASE_BYTES} byte read limit"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [], [f"invalid compile_commands.json: {exc}"]
    if not isinstance(data, list):
        return [], ["compile_commands.json must contain a JSON array"]
    entries = [item for item in data if isinstance(item, dict) and isinstance(item.get("file"), str)]
    if len(entries) != len(data):
        return entries, ["some compilation database entries were malformed and ignored"]
    return entries, []


def inspect_build_context(project_path: str | Path, *, compile_commands: str | Path | None = None) -> dict[str, Any]:
    """Return a versioned, no-write build-context contract."""
    project = Path(project_path).expanduser().resolve()
    if not project.is_dir():
        raise FileNotFoundError(f"project directory does not exist: {project}")
    markers = {system: [name for name in names if (project / name).is_file()] for system, names in _BUILD_MARKERS.items()}
    detected_systems = [system for system, names in markers.items() if names]
    database = find_compile_commands(project, compile_commands)
    diagnostics: list[str] = []
    entries: list[dict[str, Any]] = []
    if database:
        entries, diagnostics = _load_database(database)
    files: dict[str, int] = {}
    outside_workspace = 0
    configurations: dict[str, int] = {}
    for entry in entries:
        file_value = Path(str(entry["file"]))
        base = Path(str(entry.get("directory") or database.parent))
        source = (base / file_value).resolve() if not file_value.is_absolute() else file_value.resolve()
        key = str(source).lower()
        files[key] = files.get(key, 0) + 1
        if project not in source.parents and source != project:
            outside_workspace += 1
        argv = entry.get("arguments")
        command = " ".join(str(value) for value in argv) if isinstance(argv, list) else str(entry.get("command") or "")
        if "-DCMAKE_BUILD_TYPE=Debug" in command or "/Od" in command:
            configurations["debug"] = configurations.get("debug", 0) + 1
        if "-O2" in command or "-O3" in command or "/O2" in command:
            configurations["optimized"] = configurations.get("optimized", 0) + 1
    duplicate_tus = sum(1 for count in files.values() if count > 1)
    generated_dirs = [str(path.relative_to(project)) for path in (project / "generated", project / "build" / "generated", project / "out" / "generated") if path.is_dir()]
    if database is None:
        status, quality = "incomplete", "limited"
        reasons = ["compile_commands.json is missing"]
    elif diagnostics:
        status, quality = "invalid", "limited"
        reasons = list(diagnostics)
    elif not entries:
        status, quality = "empty", "limited"
        reasons = ["compile_commands.json has no usable translation units"]
    else:
        status, quality = "available", "likely"
        reasons = []
        if duplicate_tus:
            reasons.append(f"{duplicate_tus} translation unit(s) have multiple compile configurations")
            quality = "limited"
        if outside_workspace:
            reasons.append(f"{outside_workspace} compilation command(s) point outside the workspace")
    payload = {
        "schema_version": "CodeSlicerBuildContext/v1",
        "inspected_at": datetime.now(timezone.utc).isoformat(),
        "project_path": str(project),
        "build_systems": detected_systems,
        "markers": markers,
        "compile_commands": {
            "path": str(database) if database else None,
            "status": status,
            "fingerprint": _sha256(database) if database and database.is_file() else None,
            "modified_at": datetime.fromtimestamp(database.stat().st_mtime, tz=timezone.utc).isoformat() if database and database.is_file() else None,
            "translation_units": len(files),
            "entries": len(entries),
            "ambiguous_translation_units": duplicate_tus,
            "outside_workspace_entries": outside_workspace,
        },
        "generated_directories": generated_dirs,
        "configurations": configurations,
        "semantic_quality": {"level": quality, "reasons": reasons},
        "diagnostics": diagnostics,
    }
    return payload
