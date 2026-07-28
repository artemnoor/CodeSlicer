"""Opt-in validation runner for real local Joern vulnerability corpora.

This module is intentionally separate from the Joern adapter. It may execute
only when the user supplies an absolute local Joern executable, an absolute
local corpus checkout, and an absolute manifest. It does not clone, download,
install, or contact a network. Reports contain bounded aggregate metrics only.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable

from impact_engine.adapters.joern import bounded_joern_context
from impact_engine.adapters.registry import AdapterRegistry, MAX_ARTIFACT_BYTES


MANIFEST_SCHEMA = "CodeSlicerJoernRealCorpusManifest/v1"
REPORT_SCHEMA = "CodeSlicerJoernRealCorpusReport/v1"
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_QUERY_BYTES = 256 * 1024
MAX_DIAGNOSTICS = 32
SAFE_CASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,96}$")
SAFE_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
SAFE_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
SAFE_SYMBOL = re.compile(r"^[A-Za-z_.$:<>~#/@+\-][A-Za-z0-9_.$:<>~#/@+\-]{0,159}$")
SECRET_LIKE = re.compile(r"(?:secret|token|password|passwd|authorization|bearer|cookie|api[_-]?key|private[_-]?key|credential)", re.I)
URL_RE = re.compile(r"(?:https?|file|ssh)://", re.I)


def _absolute(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{label} must be an absolute local path")
    return path.resolve()


def _safe_relative(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError(f"{label} must be a non-empty relative path")
    if SECRET_LIKE.search(value):
        raise ValueError(f"{label} contains a sensitive path marker")
    path = Path(value.replace("\\", "/"))
    if path.is_absolute() or str(path) in {".", ""} or any(part == ".." for part in path.parts):
        raise ValueError(f"{label} must be a relative path")
    return path.as_posix()


def _safe_text(value: Any, label: str, maximum: int = 400) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum or SECRET_LIKE.search(value) or URL_RE.search(value):
        raise ValueError(f"{label} contains unsafe or oversized text")
    return value


def _safe_command(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be a non-empty argv array")
    if any(URL_RE.search(item) for item in value):
        raise ValueError(f"{label} must not contain network URLs")
    return [item[:512] for item in value]


def _safe_id_list(value: Any, label: str, maximum: int = 100) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(f"{label} must be a bounded array")
    result: list[str] = []
    for item in value:
        text = _safe_text(item, label, 256)
        if not re.fullmatch(r"(?:joern_(?:vertex|edge|path|finding)_[0-9a-f]{24}|opaque_[A-Za-z0-9._-]{1,96})", text):
            raise ValueError(f"{label} must contain opaque local IDs")
        result.append(text)
    return result


def _safe_text_list(value: Any, label: str, maximum: int = 32) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(f"{label} must be a bounded array")
    return [_safe_text(item, label, 256) for item in value]


def _safe_materialization(value: Any, project_subpath: str, label: str = "materialization") -> dict[str, Any] | None:
    """Validate a declared local preparation step without executing it."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    kind = value.get("kind")
    if kind not in {"archive", "git-checkout"}:
        raise ValueError(f"{label}.kind must be archive or git-checkout")
    output_relative = _safe_relative(value.get("output_relative"), f"{label}.output_relative")
    if output_relative != project_subpath:
        raise ValueError(f"{label}.output_relative must equal project_subpath")
    instructions = _safe_text_list(value.get("instructions"), f"{label}.instructions", 8)
    result: dict[str, Any] = {"kind": kind, "output_relative": output_relative, "instructions": instructions}
    if kind == "archive":
        input_relative = _safe_relative(value.get("input_relative"), f"{label}.input_relative")
        artifact_sha256 = value.get("artifact_sha256")
        if not isinstance(artifact_sha256, str) or not SAFE_SHA256.fullmatch(artifact_sha256):
            raise ValueError(f"{label}.artifact_sha256 must be a SHA-256")
        result.update({"input_relative": input_relative, "artifact_sha256": artifact_sha256.lower()})
    else:
        source_repo_url = value.get("source_repo_url")
        source_commit_sha = value.get("source_commit_sha")
        if not isinstance(source_repo_url, str) or not source_repo_url.startswith("https://") or SECRET_LIKE.search(source_repo_url):
            raise ValueError(f"{label}.source_repo_url must be an HTTPS public reference")
        if not isinstance(source_commit_sha, str) or not SAFE_SHA.fullmatch(source_commit_sha):
            raise ValueError(f"{label}.source_commit_sha must be a full SHA")
        result.update({"source_repo_url": source_repo_url, "source_commit_sha": source_commit_sha.lower()})
    return result


def _safe_selector(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    allowed = {"kinds", "name_exact", "name_contains", "file_suffix", "line", "line_min", "line_max"}
    if set(value) - allowed:
        raise ValueError(f"{label} contains unsupported selector fields")
    kinds = value.get("kinds")
    if kinds is not None:
        if not isinstance(kinds, list) or not kinds or len(kinds) > 6:
            raise ValueError(f"{label}.kinds must be a bounded non-empty array")
        kinds = [str(item).upper() for item in kinds]
        if any(item not in {"METHOD", "CALL", "IDENTIFIER", "METHOD_PARAMETER_IN", "LITERAL", "CONTROL_STRUCTURE", "UNKNOWN"} for item in kinds):
            raise ValueError(f"{label}.kinds contains an unsupported node kind")
    name_exact = value.get("name_exact")
    name_contains = value.get("name_contains")
    if name_exact is not None:
        if not isinstance(name_exact, str) or not SAFE_SYMBOL.fullmatch(name_exact):
            raise ValueError(f"{label}.name_exact must be a safe symbol")
    if name_contains is not None:
        if not isinstance(name_contains, str) or not SAFE_SYMBOL.fullmatch(name_contains):
            raise ValueError(f"{label}.name_contains must be a safe symbol fragment")
    line_values: dict[str, int] = {}
    for key in ("line", "line_min", "line_max"):
        if value.get(key) is not None:
            if not isinstance(value[key], int) or not 1 <= value[key] <= 10_000_000:
                raise ValueError(f"{label}.{key} must be a valid source line")
            line_values[key] = value[key]
    if name_exact is None and name_contains is None and not line_values:
        raise ValueError(f"{label} requires a safe name or line selector")
    file_suffix = value.get("file_suffix")
    if file_suffix is not None:
        file_suffix = _safe_relative(file_suffix, f"{label}.file_suffix")
    result: dict[str, Any] = {}
    if kinds is not None:
        result["kinds"] = kinds
    if name_exact is not None:
        result["name_exact"] = name_exact
    if name_contains is not None:
        result["name_contains"] = name_contains
    if file_suffix is not None:
        result["file_suffix"] = file_suffix
    result.update(line_values)
    return result


def validate_real_manifest(data: Any) -> dict[str, Any]:
    """Validate and return only the bounded manifest contract."""
    if not isinstance(data, dict) or data.get("schema_version") != MANIFEST_SCHEMA:
        raise ValueError(f"manifest must use {MANIFEST_SCHEMA}")
    raw_cases = data.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("manifest cases must be a non-empty array")
    safe_cases: list[dict[str, Any]] = []
    for raw in raw_cases:
        if not isinstance(raw, dict):
            raise ValueError("manifest case must be an object")
        case_id = raw.get("case_id")
        if not isinstance(case_id, str) or not SAFE_CASE_ID.fullmatch(case_id) or SECRET_LIKE.search(case_id):
            raise ValueError("manifest case_id is unsafe")
        language = raw.get("language")
        if language not in {"C", "C++", "Java"}:
            raise ValueError("manifest language must be C, C++, or Java")
        url = raw.get("url")
        if not isinstance(url, str) or not url.startswith("https://") or SECRET_LIKE.search(url):
            raise ValueError("manifest url must be an HTTPS public reference")
        commit_sha = raw.get("commit_sha")
        if not isinstance(commit_sha, str) or not SAFE_SHA.fullmatch(commit_sha):
            raise ValueError("manifest commit_sha must be a full 40-character SHA")
        license_name = _safe_text(raw.get("license"), "manifest license")
        project_subpath = _safe_relative(raw.get("project_subpath", "."), "manifest project_subpath") if raw.get("project_subpath", ".") != "." else "."
        source = raw.get("source") if isinstance(raw.get("source"), dict) else {}
        sink = raw.get("sink") if isinstance(raw.get("sink"), dict) else {}
        source_safe = {"description": _safe_text(source.get("description"), "source description"), "query": _safe_text(source.get("query"), "source query")}
        sink_safe = {"description": _safe_text(sink.get("description"), "sink description"), "query": _safe_text(sink.get("query"), "sink query")}
        commands = raw.get("commands") if isinstance(raw.get("commands"), dict) else {}
        frontend_args = _safe_command(commands.get("frontend_args"), "commands.frontend_args")
        query_args = _safe_command(commands.get("query_args"), "commands.query_args")
        query_file = _safe_relative(commands.get("query_file"), "commands.query_file")
        expected = raw.get("expected") if isinstance(raw.get("expected"), dict) else {}
        confirmed_count = expected.get("confirmed_paths", 1)
        if not isinstance(confirmed_count, int) or confirmed_count < 1 or confirmed_count > 100:
            raise ValueError("expected.confirmed_paths must be between 1 and 100")
        expected_ids = {
            "confirmed_path_ids": _safe_id_list(expected.get("confirmed_path_ids"), "expected.confirmed_path_ids"),
            "source_node_ids": _safe_id_list(expected.get("source_node_ids"), "expected.source_node_ids"),
            "sink_node_ids": _safe_id_list(expected.get("sink_node_ids"), "expected.sink_node_ids"),
            "step_node_ids": _safe_id_list(expected.get("step_node_ids"), "expected.step_node_ids"),
            "prohibited_false_positive_paths": _safe_id_list(expected.get("prohibited_false_positive_paths"), "expected.prohibited_false_positive_paths"),
        }
        expected_context = _safe_text_list(expected.get("dangerous_call_context"), "expected.dangerous_call_context")
        source_selector = _safe_selector(expected.get("source_selector"), "expected.source_selector") if expected.get("source_selector") is not None else None
        sink_selector = _safe_selector(expected.get("sink_selector"), "expected.sink_selector") if expected.get("sink_selector") is not None else None
        min_steps = expected.get("min_steps", 1)
        if not isinstance(min_steps, int) or not 1 <= min_steps <= 100:
            raise ValueError("expected.min_steps must be between 1 and 100")
        expected_privacy = expected.get("privacy") if isinstance(expected.get("privacy"), dict) else {}
        if expected_privacy and expected_privacy != {"mode": "local-only", "network_used": False}:
            raise ValueError("expected.privacy must be the local-only contract")
        expected_freshness = expected.get("freshness", "verified")
        if expected_freshness not in {"verified", "unverified", "stale"}:
            raise ValueError("expected.freshness is unsupported")
        materialized = raw.get("materialized_source") if isinstance(raw.get("materialized_source"), dict) else {}
        materialized_url = materialized.get("url")
        if not isinstance(materialized_url, str) or not materialized_url.startswith("https://") or SECRET_LIKE.search(materialized_url):
            raise ValueError("materialized_source.url must be an HTTPS public reference")
        materialized_commit = materialized.get("commit_sha")
        materialized_artifact = materialized.get("artifact_sha256")
        if materialized_commit is not None and (not isinstance(materialized_commit, str) or not SAFE_SHA.fullmatch(materialized_commit)):
            raise ValueError("materialized_source.commit_sha must be a full SHA")
        if materialized_artifact is not None and (not isinstance(materialized_artifact, str) or not SAFE_SHA256.fullmatch(materialized_artifact)):
            raise ValueError("materialized_source.artifact_sha256 must be a SHA-256")
        if materialized_commit is None and materialized_artifact is None:
            raise ValueError("materialized_source requires a commit or artifact SHA")
        materialization = _safe_materialization(raw.get("materialization"), project_subpath)
        safe_cases.append({
            "case_id": case_id,
            "language": language,
            "url": url,
            "commit_sha": commit_sha.lower(),
            "license": license_name,
            "project_subpath": project_subpath,
            "source": source_safe,
            "sink": sink_safe,
            "commands": {"frontend_args": frontend_args, "query_args": query_args, "query_file": query_file},
            "expected": {
                "confirmed_paths": confirmed_count,
                "required_locations": bool(expected.get("required_locations", True)),
                **expected_ids,
                "dangerous_call_context": expected_context,
                "source_selector": source_selector,
                "sink_selector": sink_selector,
                "min_steps": min_steps,
                "privacy": {"mode": "local-only", "network_used": False},
                "freshness": expected_freshness,
            },
            "limitations": [_safe_text(item, "limitation") for item in (raw.get("limitations") or [])[:8] if isinstance(item, str)],
            "materialized_source": {
                "url": materialized_url,
                **({"commit_sha": materialized_commit.lower()} if materialized_commit is not None else {}),
                **({"artifact_sha256": materialized_artifact.lower()} if materialized_artifact is not None else {}),
            },
            **({"materialization": materialization} if materialization is not None else {}),
        })
    return {"schema_version": MANIFEST_SCHEMA, "cases": safe_cases}


def load_real_manifest(path: str | Path) -> dict[str, Any]:
    source = _absolute(path, "manifest_path")
    if not source.is_file():
        raise FileNotFoundError(f"manifest does not exist: {source}")
    if source.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError("manifest exceeds the bounded size limit")
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("manifest must be valid UTF-8 JSON") from exc
    safe = validate_real_manifest(data)
    safe["_manifest_path"] = str(source)
    return safe


def select_real_case(manifest: dict[str, Any], case_id: str) -> dict[str, Any]:
    for case in manifest.get("cases", []):
        if case.get("case_id") == case_id:
            return case
    raise ValueError(f"real corpus case not found: {case_id}")


def _replace_args(args: Iterable[str], values: dict[str, str]) -> list[str]:
    result = []
    for item in args:
        rendered = item
        for key, value in values.items():
            rendered = rendered.replace("{" + key + "}", value)
        result.append(rendered)
    return result


def _resolve_tool(path: Path, names: tuple[str, ...]) -> Path:
    if path.is_file():
        return path
    if path.is_dir():
        suffixes = (".bat", ".cmd", ".exe", "") if os.name == "nt" else ("", ".sh", ".run")
        for name in names:
            for suffix in suffixes:
                candidate = path / f"{name}{suffix}"
                if candidate.is_file():
                    return candidate.resolve()
    raise FileNotFoundError(f"local Joern executable was not found at {path}")


def _run_local(argv: list[str], *, timeout: float, env: dict[str, str]) -> dict[str, Any]:
    if any(URL_RE.search(item) for item in argv):
        raise ValueError("Joern command contains a network URL")
    started = time.perf_counter()
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, shell=False, env=env, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "elapsed_ms": round((time.perf_counter() - started) * 1000, 3), "returncode": None}
    return {"status": "ok" if completed.returncode == 0 else "error", "elapsed_ms": round((time.perf_counter() - started) * 1000, 3), "returncode": completed.returncode}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_materialization(case: dict[str, Any], corpus: Path, project: Path) -> dict[str, Any]:
    """Verify prepared input locally; never clone, download, or extract."""
    materialization = case.get("materialization")
    if not materialization:
        return {"status": "not_declared", "verified": False}
    if not project.is_dir():
        raise FileNotFoundError("materialization_required: prepared project directory is missing")
    kind = materialization["kind"]
    if kind == "archive":
        source = corpus / materialization["input_relative"]
        if not source.is_file():
            raise FileNotFoundError("materialization_required: declared archive is missing")
        actual = _sha256_file(source)
        if actual != materialization["artifact_sha256"]:
            raise ValueError("materialization_invalid: archive SHA-256 does not match manifest")
        return {"status": "verified", "verified": True, "kind": kind, "artifact_sha256": actual}
    git = shutil.which("git")
    if not git:
        raise FileNotFoundError("materialization_invalid: local git executable is unavailable")
    completed = subprocess.run([git, "-C", str(project), "rev-parse", "HEAD"], capture_output=True, text=True, shell=False, check=False)
    actual = completed.stdout.strip().lower() if completed.returncode == 0 else ""
    expected = materialization["source_commit_sha"]
    if actual != expected:
        raise ValueError("materialization_invalid: prepared git checkout commit does not match manifest")
    return {"status": "verified", "verified": True, "kind": kind, "source_commit_sha": actual}


def _sanitized_interchange(source: Path, target: Path) -> str:
    """Remove absolute project/artifact paths before the import step."""
    data = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != "CodeSlicerJoernInterchange/v1":
        raise ValueError("Joern convert output is not CodeSlicerJoernInterchange/v1")
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    data["metadata"] = {key: metadata[key] for key in ("tool", "tool_version", "source_format", "commit", "created_at") if key in metadata}
    bridge = data.get("bridge") if isinstance(data.get("bridge"), dict) else {}
    data["bridge"] = {key: bridge[key] for key in ("schema_version", "network_used", "source_kind", "confirmed_security_paths_require_explicit_taint") if key in bridge}
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return hashlib.sha256(target.read_bytes()).hexdigest()


def normalize_joern_flow_export(source: Path, target: Path) -> None:
    """Normalize Joern ``reachableByFlows(...).toJson`` output."""
    data = json.loads(source.read_text(encoding="utf-8"))
    if isinstance(data, dict) and data.get("schema_version") == "CodeSlicerJoernInterchange/v1":
        target.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return
    raw_paths = data.get("paths") if isinstance(data, dict) else data
    if not isinstance(raw_paths, list):
        raise ValueError("Joern flow output must be a JSON array or object with paths")
    vertices: list[dict[str, Any]] = []
    paths: list[dict[str, Any]] = []
    for path_index, raw_path in enumerate(raw_paths[:500]):
        elements = raw_path.get("elements") if isinstance(raw_path, dict) else raw_path
        if not isinstance(elements, list) or len(elements) < 2:
            continue
        vertex_ids: list[int] = []
        locations: list[dict[str, Any]] = []
        for element_index, element in enumerate(elements[:100]):
            if not isinstance(element, dict):
                continue
            node_type = str(element.get("nodeType") or element.get("type") or element.get("label") or "CALL").upper()
            kind = {"CALL": "CALL", "METHOD": "METHOD", "METHODPARAMETERIN": "METHOD_PARAMETER_IN", "METHOD_PARAMETER_IN": "METHOD_PARAMETER_IN", "IDENTIFIER": "IDENTIFIER", "LITERAL": "LITERAL", "CONTROLSTRUCTURE": "CONTROL_STRUCTURE", "CONTROL_STRUCTURE": "CONTROL_STRUCTURE"}.get(node_type.replace(" ", ""), "CALL")
            vertex_id = path_index * 1000 + element_index
            vertex_ids.append(vertex_id)
            properties: dict[str, Any] = {}
            file_value = element.get("file") or element.get("filename")
            line_value = element.get("lineNumber") if element.get("lineNumber") is not None else element.get("line")
            column_value = element.get("columnNumber") if element.get("columnNumber") is not None else element.get("column")
            if isinstance(file_value, str) and file_value and not URL_RE.search(file_value):
                try:
                    properties["FILENAME"] = _safe_relative(file_value, "Joern flow file")
                except ValueError:
                    properties.pop("FILENAME", None)
            for field in ("name", "method", "fullName", "methodFullName"):
                value = element.get(field)
                if isinstance(value, str) and SAFE_SYMBOL.fullmatch(value):
                    properties["NAME"] = value
                    break
            code_value = element.get("code")
            if "NAME" not in properties and isinstance(code_value, str) and not SECRET_LIKE.search(code_value):
                match = re.search(r"\b([A-Za-z_][A-Za-z0-9_.$:<>~#/@+\-]*)\s*\(", code_value)
                if match:
                    candidate = match.group(1).rsplit(".", 1)[-1]
                    if SAFE_SYMBOL.fullmatch(candidate):
                        properties["NAME"] = candidate
            tracked = element.get("tracked")
            if isinstance(tracked, str) and not SECRET_LIKE.search(tracked):
                match = re.search(r"\b([A-Za-z_][A-Za-z0-9_.$:<>~#/@+\-]*)\s*\(", tracked)
                if match and SAFE_SYMBOL.fullmatch(match.group(1)):
                    properties["NAME"] = match.group(1)
            if isinstance(line_value, int) and 1 <= line_value <= 10_000_000:
                properties["LINE_NUMBER"] = line_value
                properties["LINE_NUMBER_END"] = line_value
            if isinstance(column_value, int) and 0 <= column_value <= 100_000:
                properties["COLUMN_NUMBER"] = column_value
                properties["COLUMN_NUMBER_END"] = column_value + 1
            vertices.append({"id": vertex_id, "label": kind, "properties": properties})
            if properties.get("FILENAME") and properties.get("LINE_NUMBER"):
                locations.append({"file": properties["FILENAME"], "range": {"start_line": properties["LINE_NUMBER"], "start_character": properties.get("COLUMN_NUMBER", 0), "end_line": properties["LINE_NUMBER_END"], "end_character": properties.get("COLUMN_NUMBER_END", properties.get("COLUMN_NUMBER", 0))}})
        if len(vertex_ids) >= 2:
            paths.append({"id": f"flow-{path_index}", "source": vertex_ids[0], "steps": vertex_ids, "sink": vertex_ids[-1], "confidence": "confirmed", "locations": locations[:12]})
    target.write_text(json.dumps({"vertices": vertices[:5000], "edges": [], "paths": paths}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build_real_validation_report(case: dict[str, Any], overlay: dict[str, Any] | None, *, command_status: dict[str, Any], elapsed_ms: float, artifact_fingerprint: str | None = None) -> dict[str, Any]:
    paths = list((overlay or {}).get("taint_paths") or [])
    confirmed = sum(1 for item in paths if item.get("resolution") == "confirmed")
    likely = sum(1 for item in paths if item.get("resolution") == "likely")
    unresolved = sum(1 for item in paths if item.get("resolution") == "unresolved")
    expected_data = case.get("expected") or {}
    expected = int(expected_data.get("confirmed_paths", 1))
    expected_path_ids = set(expected_data.get("confirmed_path_ids") or [])
    observed_confirmed_ids = {str(item.get("id")) for item in paths if item.get("resolution") == "confirmed" and item.get("id")}
    missing_expected_ids = sorted(expected_path_ids - observed_confirmed_ids)
    prohibited_ids = set(expected_data.get("prohibited_false_positive_paths") or [])
    prohibited_observed = sorted(prohibited_ids & observed_confirmed_ids)
    diagnostics = [item for item in (overlay or {}).get("diagnostics", []) if isinstance(item, dict) and item.get("code")]
    if not paths:
        diagnostics.append({"code": "no_path_observed", "severity": "warning", "message": "Joern returned no explicit source-to-sink path; this is not evidence of safety"})
    location_contract_failures = 0
    for item in paths:
        if item.get("resolution") != "confirmed":
            continue
        if not item.get("source") or not item.get("sink") or not item.get("steps") or len(item.get("locations") or []) < 2:
            location_contract_failures += 1
    if location_contract_failures:
        diagnostics.append({"code": "confirmed_location_contract_violation", "severity": "error", "message": "A confirmed path did not contain the required bounded source/sink locations"})
    if missing_expected_ids:
        diagnostics.append({"code": "expected_confirmed_path_missing", "severity": "error", "message": "An expected opaque confirmed path was not observed"})
    if prohibited_observed:
        diagnostics.append({"code": "prohibited_false_positive_confirmed", "severity": "error", "message": "A prohibited opaque path was confirmed"})
    semantic_matches = {"source": 0, "sink": 0, "paths": 0}
    source_selector = expected_data.get("source_selector")
    sink_selector = expected_data.get("sink_selector")
    nodes_by_id = {str(item.get("id")): item for item in (overlay or {}).get("nodes", []) if isinstance(item, dict) and item.get("id")}

    def matches(node: dict[str, Any] | None, selector: dict[str, Any] | None) -> bool:
        if not node or not selector:
            return False
        kinds = selector.get("kinds") or []
        if kinds and str(node.get("kind", "")).upper() not in kinds:
            return False
        name = str(node.get("name") or "")
        if selector.get("name_exact") is not None and name != selector["name_exact"]:
            return False
        if selector.get("name_contains") is not None and selector["name_contains"] not in name:
            return False
        suffix = selector.get("file_suffix")
        if suffix and not str(node.get("file") or "").replace("\\", "/").endswith(suffix):
            return False
        line = ((node.get("range") or {}).get("start") or {}).get("line")
        if selector.get("line") is not None and line != selector["line"]:
            return False
        if selector.get("line_min") is not None and (line is None or line < selector["line_min"]):
            return False
        if selector.get("line_max") is not None and (line is None or line > selector["line_max"]):
            return False
        return True

    if source_selector or sink_selector:
        for path in paths:
            if path.get("resolution") != "confirmed":
                continue
            source_node = nodes_by_id.get(str(path.get("source")))
            sink_node = nodes_by_id.get(str(path.get("sink")))
            source_ok = matches(source_node, source_selector) if source_selector else True
            sink_ok = matches(sink_node, sink_selector) if sink_selector else True
            if source_ok:
                semantic_matches["source"] += 1
            if sink_ok:
                semantic_matches["sink"] += 1
            min_steps = int(expected_data.get("min_steps", 1))
            if source_ok and sink_ok and len(path.get("steps") or []) >= min_steps:
                semantic_matches["paths"] += 1
        if source_selector and semantic_matches["source"] < expected:
            diagnostics.append({"code": "expected_source_selector_unmatched", "severity": "error", "message": "Confirmed paths did not match the expected source selector"})
        if sink_selector and semantic_matches["sink"] < expected:
            diagnostics.append({"code": "expected_sink_selector_unmatched", "severity": "error", "message": "Confirmed paths did not match the expected sink selector"})
        if (source_selector or sink_selector) and semantic_matches["paths"] < expected:
            diagnostics.append({"code": "expected_semantic_path_missing", "severity": "error", "message": "Confirmed path did not satisfy source/sink selectors and minimum step length"})
    fresh = (overlay or {}).get("freshness") or {"status": "unknown", "verified": False}
    semantic_ok = not (source_selector or sink_selector) or semantic_matches["paths"] >= expected
    ok = confirmed >= expected and semantic_ok and not missing_expected_ids and not prohibited_observed and location_contract_failures == 0 and fresh.get("verified") is True
    return {
        "schema_version": REPORT_SCHEMA,
        "status": "ok" if ok else "failed",
        "case": {"case_id": case.get("case_id"), "language": case.get("language"), "url": case.get("url"), "commit_sha": case.get("commit_sha"), "license": case.get("license")},
        "expected": {
            "confirmed_paths": expected,
            "confirmed_path_ids": sorted(expected_path_ids),
            "source_node_ids": list(expected_data.get("source_node_ids") or []),
            "sink_node_ids": list(expected_data.get("sink_node_ids") or []),
            "step_node_ids": list(expected_data.get("step_node_ids") or []),
            "dangerous_call_context": list(expected_data.get("dangerous_call_context") or []),
            "source_selector": source_selector,
            "sink_selector": sink_selector,
            "min_steps": int(expected_data.get("min_steps", 1)),
            "prohibited_false_positive_paths": sorted(prohibited_ids),
            "required_locations": bool(expected_data.get("required_locations", True)),
            "freshness": expected_data.get("freshness", "verified"),
            "privacy": {"mode": "local-only", "network_used": False},
        },
        "observed": {
            "paths": len(paths), "confirmed": confirmed, "likely": likely, "unresolved": unresolved,
            "confirmed_path_ids": sorted(observed_confirmed_ids),
            "missing_expected_path_ids": missing_expected_ids,
            "prohibited_confirmed_path_ids": prohibited_observed,
            "semantic_matches": semantic_matches,
            "nodes": len((overlay or {}).get("nodes") or []), "edges": len((overlay or {}).get("edges") or []), "findings": len((overlay or {}).get("findings") or []),
        },
        "freshness": {"status": fresh.get("status", "unknown"), "verified": bool(fresh.get("verified", False))},
        "materialization": case.get("_materialization_status", {"status": "not_declared", "verified": False}),
        "commands": command_status,
        "elapsed_ms": round(elapsed_ms, 3),
        "artifact_fingerprint": artifact_fingerprint,
        "diagnostics": diagnostics[:MAX_DIAGNOSTICS],
        "privacy": {"mode": "local-only", "network_used": False, "raw_source_stored": False, "raw_graphson_ids_stored": False, "absolute_user_paths_stored": False, "joern_invoked": True},
        "review_invariance": {"status": "not_changed_by_runner", "canonical_graph_mutated": False},
    }


def run_real_corpus_validation(joern_path: str | Path, corpus_path: str | Path, manifest_path: str | Path, case_id: str, *, output_path: str | Path | None = None, impact_engine_path: str | Path | None = None, java_home: str | Path | None = None, timeout: float = 300.0) -> dict[str, Any]:
    """Run one explicit real-corpus validation and return its bounded report."""
    joern_input = _absolute(joern_path, "joern_path")
    corpus = _absolute(corpus_path, "corpus_path")
    manifest = load_real_manifest(manifest_path)
    case = select_real_case(manifest, case_id)
    if not corpus.is_dir():
        raise FileNotFoundError(f"corpus directory does not exist: {corpus}")
    project = (corpus / case["project_subpath"]).resolve()
    case["_materialization_status"] = _verify_materialization(case, corpus, project)
    if not project.is_dir():
        raise FileNotFoundError("manifest project_subpath does not exist")
    joern = _resolve_tool(joern_input, ("joern", "joern-cli"))
    joern_parse = _resolve_tool(joern.parent, ("joern-parse", "joern_parse"))
    cli_input = _absolute(impact_engine_path, "impact_engine_path") if impact_engine_path else None
    cli = cli_input or (Path(shutil.which("impact-engine")) if shutil.which("impact-engine") else None)
    if not cli or not cli.is_file():
        raise FileNotFoundError("impact-engine executable is required on PATH or via --impact-engine")
    java_home_path = _absolute(java_home, "java_home") if java_home else None
    if java_home_path and not (java_home_path / ("bin" if os.name != "nt" else "bin") / ("java.exe" if os.name == "nt" else "java")).is_file():
        raise FileNotFoundError(f"java_home does not contain a local Java executable: {java_home_path}")
    query_file = (Path(manifest["_manifest_path"]).parent / case["commands"]["query_file"]).resolve()
    if not query_file.is_file():
        raise FileNotFoundError(f"manifest query file does not exist: {query_file}")
    if query_file.stat().st_size > MAX_QUERY_BYTES:
        raise ValueError("Joern query file exceeds the bounded size limit")
    query_text = query_file.read_text(encoding="utf-8")
    if URL_RE.search(query_text):
        raise ValueError("Joern query contains a network URL")
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="codeslicer-joern-real-") as temp_name:
        temp = Path(temp_name)
        cpg = temp / "cpg.bin"
        query_output = temp / "query.json"
        converted = temp / "converted.json"
        values = {"project": str(project), "cpg_output": str(cpg), "query_file": str(query_file), "query_output": str(query_output), "case_id": case_id}
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        if java_home_path:
            env["JAVA_HOME"] = str(java_home_path)
            env["PATH"] = str(java_home_path / "bin") + os.pathsep + env.get("PATH", "")
        frontend = _run_local([str(joern_parse), *_replace_args(case["commands"]["frontend_args"], values)], timeout=timeout, env=env)
        query = _run_local([str(joern), *_replace_args(case["commands"]["query_args"], values)], timeout=timeout, env=env) if frontend["status"] == "ok" else {"status": "blocked", "elapsed_ms": 0, "returncode": None}
        commands = {"frontend": frontend, "query": query, "convert": {"status": "blocked", "elapsed_ms": 0, "returncode": None}}
        if query["status"] != "ok" or not query_output.is_file() or query_output.stat().st_size > MAX_ARTIFACT_BYTES:
            report = build_real_validation_report(case, None, command_status=commands, elapsed_ms=(time.perf_counter() - started) * 1000)
        else:
            flow_output = temp / "normalized-flow.json"
            normalized = None
            try:
                normalize_joern_flow_export(query_output, flow_output)
                normalized = json.loads(flow_output.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                commands["convert"] = {"status": "invalid_query_output", "elapsed_ms": 0, "returncode": None}
                report = build_real_validation_report(case, None, command_status=commands, elapsed_ms=(time.perf_counter() - started) * 1000)
            if normalized is not None and (not isinstance(normalized, dict) or not normalized.get("paths")):
                commands["convert"] = {"status": "no_path_observed", "elapsed_ms": 0, "returncode": None}
                report = build_real_validation_report(case, None, command_status=commands, elapsed_ms=(time.perf_counter() - started) * 1000)
            elif normalized is not None:
                convert = _run_local([str(cli), "--json", "adapters", "joern", "convert", str(flow_output), "--project", str(project), "--output", str(converted), "--json"], timeout=timeout, env=env)
                commands["convert"] = convert
                overlay = None
                fingerprint = None
                if convert["status"] == "ok" and converted.is_file():
                    # Keep the sanitized interchange in project-local storage.
                    # The registry records source_path for freshness; pointing
                    # it at a TemporaryDirectory would make a successful run
                    # become unverified as soon as this function returns.
                    registry = AdapterRegistry(str(project))
                    sanitized = registry.storage / "artifacts" / "joern" / "interchange.json"
                    sanitized.parent.mkdir(parents=True, exist_ok=True)
                    fingerprint = _sanitized_interchange(converted, sanitized)
                    imported = registry.import_artifact("joern", str(sanitized))
                    fingerprint = str((imported.get("adapter") or {}).get("artifact_fingerprint") or fingerprint)
                    registry.set_enabled("joern", True)
                    overlay = registry.overlay("joern")
                report = build_real_validation_report(case, overlay, command_status=commands, elapsed_ms=(time.perf_counter() - started) * 1000, artifact_fingerprint=fingerprint)
        if output_path:
            target = _absolute(output_path, "output_path")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
            report["report_written"] = True
        return report
